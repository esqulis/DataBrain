"""AgentService: 智能数据分析 Agent 主循环（后端版）"""

from __future__ import annotations
import json
import os
from agent.registry import ToolRegistry
from memory.data_profiler import DataProfiler
from memory.pattern_memory import PatternMemory
from memory.preferences import UserPreferences


class AgentService:
    """数据分析 Agent 主循环 —— 支持多轮工具调用"""

    def __init__(self, brain, data_engine):
        self.brain = brain
        self.data_engine = data_engine
        self.tools = ToolRegistry()
        self.tools.set_data_engine(data_engine)
        self.profiler = DataProfiler()
        self.patterns = PatternMemory()
        self.prefs = UserPreferences()
        self.max_turns = 12
        self.history: list[dict] = []
        self._last_sql: str | None = None
        self._pending_charts: list[dict] = []
        self._last_query_result: dict | None = None
        self._round_queries: list[dict] = []  # 本轮全部成功查询，供 visualize 按相关性挑选
        # schema 预分析缓存：同一数据快照只 profile 一次，避免每条消息重算导致超时
        self._schema_cache_key: str | None = None
        self._schema_cache: dict | None = None

    @staticmethod
    def _estimate_turns(query: str) -> int:
        q = query.lower()
        # 复杂多条件分析先行匹配
        if any(k in q for k in ("同时满足", "高于平均", "低于平均", "环比增长", "同比增长")):
            return 12
        if any(k in q for k in ("多少条", "有哪些", "列出", "预览", "show", "list", "count", "数据概况")):
            return 6
        if any(k in q for k in ("统计", "排序", "分组", "group", "order", "平均", "sum", "前", "top", "最高", "最低")):
            return 10
        if any(k in q for k in ("报告", "report", "预测", "forecast", "趋势")):
            return 12
        if any(k in q for k in ("join", "多表", "关联", "对比", "analyse", "分析", "画", "图", "chart", "visual")):
            return 12
        return 10

    def _pick_query_result(self, vis_args: dict, user_text: str = "") -> tuple:
        """从本轮全部查询结果里挑与 visualize 意图最相关的一份：
        用户问题/标题/描述里点名的列名、表名优先；同分取最近一次查询。
        返回 (best, best_score)，score 为 0 表示没有任何查询与画图意图相关。"""
        import re
        title = str(vis_args.get("title", "") or "")
        desc = str(vis_args.get("data_description", "") or "")
        text = f"{user_text} {title} {desc}"

        def score(q: dict) -> int:
            s = 0
            for c in (q.get("columns") or []):
                c = str(c)
                if c and c in text:
                    s += 4  # 问题/标题里点名列（如"所属行业""客户数量"）
            sql = str(q.get("sql", "") or "")
            for m in re.findall(r"FROM\s+[\"'`]?([^\s,\(\)]+)", sql, re.I):
                base = m.strip("'\"`;")
                if base and base in text:
                    s += 3  # 问题/标题里点名表
            if 0 < len(q.get("rows") or []) <= 60:
                s += 1  # 聚合结果规模加分
            return s

        best = self._round_queries[0]
        best_score = score(best)
        for q in self._round_queries[1:]:
            sc = score(q)
            if sc >= best_score:
                best, best_score = q, sc
        return best, best_score

    def _schema_snapshot_key(self) -> str:
        """表名/行数/列数变化时才失效 schema 缓存"""
        try:
            parts = []
            for t in self.data_engine.summary():
                parts.append(f"{t.get('name')}:{t.get('rows')}:{t.get('columns')}")
            return "|".join(parts)
        except Exception:
            return str(self.data_engine.table_count)

    def _get_schema_bundle(self) -> dict:
        key = self._schema_snapshot_key()
        if self._schema_cache is not None and self._schema_cache_key == key:
            return self._schema_cache

        schema_text = self.data_engine.schema_text_for_llm(self.profiler)
        suggested = self.data_engine.all_suggested_questions(self.profiler)
        self._schema_cache = {
            "schema_text": schema_text,
            "suggested": suggested,
            "table_names": self.data_engine.table_names,
        }
        self._schema_cache_key = key
        return self._schema_cache

    def process_query(self, user_input: str) -> dict:
        """处理一条用户问题，返回 { response, charts, sql }"""
        self._pending_charts = []
        # 每轮请求开始先清空上一轮残留的查询结果，防止 visualize 画到别的表的数据
        self._last_query_result = None
        self._round_queries = []

        # 构建上下文（带缓存，避免每条消息重 profile 全表导致网关 504）
        schema_text = ""
        suggested = []
        table_names = []
        if self.data_engine.table_count > 0:
            bundle = self._get_schema_bundle()
            schema_text = bundle["schema_text"]
            suggested = bundle["suggested"]
            table_names = bundle["table_names"]

        system_prompt = self._build_system_prompt({
            "schema_text": schema_text,
            "suggested_questions": suggested,
            "table_count": self.data_engine.table_count,
            "table_names": table_names,
            "is_db_mode": self.tools.is_db_mode,
        })

        # 检索相似 Pattern
        primary_table = table_names[0] if table_names else ""
        matched = self.patterns.retrieve(user_input, primary_table)
        if matched:
            refs = []
            for p in matched[:2]:
                refs.append(f"- 历史相似问题「{p['user_query']}」→ SQL: {p['sql']}")
            system_prompt += "\n\n[系统提示：以下历史查询可供参考]\n" + "\n".join(refs)

        style = self.prefs.get_style_hint()
        if style:
            system_prompt += "\n\n[用户偏好]\n" + style

        tool_schemas = self.tools.get_schemas()

        messages = [{"role": "system", "content": system_prompt}]
        for msg in self.history[-6:]:
            messages.append(msg)
        messages.append({"role": "user", "content": user_input})

        max_turns = min(self.max_turns, self._estimate_turns(user_input))

        for turn in range(max_turns):
            # 重试最多3次
            response = None
            for attempt in range(3):
                try:
                    response = self.brain.chat(messages, tools=tool_schemas)
                    if response and (response.content or response.has_tool_calls):
                        break
                except Exception:
                    import time
                    time.sleep(2 * (attempt + 1))
            if response is None:
                return {"response": "❌ 大脑调用失败（重试3次后仍无响应）"}

            if response.has_tool_calls:
                # 最后一轮：不再执行工具，强制要最终答案，避免「分析超时」
                if turn == max_turns - 1:
                    messages.append({
                        "role": "user",
                        "content": "【系统】工具调用轮次已用尽。请不要再调用任何工具，"
                                   "根据上面已获得的查询/分析结果，直接用中文写出最终结论"
                                   "（含关键数值；若有预测结果请列表说明）。"
                    })
                    try:
                        final_resp = self.brain.chat(messages, tools=None)
                        final = (final_resp.content if final_resp else "") or "分析未能在限定轮次内完成，请简化问题后重试。"
                    except Exception as e:
                        final = f"分析未能在限定轮次内完成: {e}"
                    self.history.append({"role": "user", "content": user_input})
                    self.history.append({"role": "assistant", "content": final})
                    return {
                        "response": final,
                        "charts": self._pending_charts,
                        "sql": self._last_sql,
                    }

                for tc in response.tool_calls:
                    msg = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"], ensure_ascii=False),
                            },
                        }]
                    }
                    if response.reasoning_content:
                        msg["reasoning_content"] = response.reasoning_content
                    messages.append(msg)
                    # visualize 铁律：本轮还没有与画图意图相关的查询结果就拒绝执行，
                    # 防止 LLM 查错表后抢跑画图（画成别的表的数据）
                    if tc["name"] == "visualize":
                        best_qr, best_score = (None, 0)
                        if self._round_queries:
                            best_qr, best_score = self._pick_query_result(tc["args"], user_input)
                        if best_score <= 0:
                            result = {"success": False,
                                      "error": "当前没有与要可视化的内容匹配的查询结果（可能查错了表）。"
                                               "请先用 query 对用户问题所指的表执行查询（SELECT 要画的维度和数值），"
                                               "确认查询结果的列与图表标题对应后，再调用 visualize。"}
                        else:
                            tc["args"]["query_result"] = best_qr
                            result = self.tools.execute(tc["name"], tc["args"])
                    else:
                        result = self.tools.execute(tc["name"], tc["args"])
                        # 保存本轮成功查询，供后续 visualize 挑选
                        if tc["name"] == "query" and result.get("success"):
                            qr = {
                                "success": True,
                                "sql": result.get("sql", ""),
                                "columns": result.get("columns", []),
                                "rows": result.get("rows", []),
                            }
                            self._round_queries.append(qr)
                            self._last_query_result = qr

                    result_str = self._format_tool_result(result)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

                    if tc["name"] == "visualize" and result.get("option"):
                        self._pending_charts.append(result["option"])

                    if tc["name"] == "report" and isinstance(result, dict) and result.get("chart_option"):
                        self._pending_charts.append(result["chart_option"])

                    if tc["name"] == "query" and result.get("success"):
                        self._last_sql = result.get("sql")
            else:
                final = response.content

                # 存储 Pattern
                if self._last_sql:
                    qtype = self._classify_query(user_input)
                    tbl_name = ", ".join(table_names)
                    self.patterns.store(user_input, self._last_sql,
                                        table_name=tbl_name, query_type=qtype)

                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": final})
                if len(self.history) > 40:
                    self.history = self.history[-40:]

                return {
                    "response": final,
                    "charts": self._pending_charts,
                    "sql": self._last_sql,
                }

        return {
            "response": "分析超时，请简化问题或分步提问。",
            "charts": self._pending_charts,
            "sql": self._last_sql,
        }

    def _build_system_prompt(self, ctx: dict) -> str:
        is_db = ctx.get("is_db_mode", False)
        t_count = ctx.get("table_count", 0)

        lines = [
            "你是一个智能数据分析助手，名为 DataBrain。",
            "你可以对用户上传的数据进行查询、分析和可视化。",
            "",
            "# 可用工具",
            "1. query: 用 SQL 查询数据（支持 SELECT 语句）",
            "2. analyze: 统计分析（describe/correlation/groupby/trend/distribution/outlier/forecast）。"
            "用户要求「时序预测/预测未来N期/forecast」时，直接调用 analyze(action='forecast')，"
            "并在 params 里传 date_col（如 billing_month）、target_col（如 账单金额）、periods（如 10）。"
            "多表时必须传 table=用户点名的表名。",
            "3. visualize: 将数据绘制成 ECharts 图表。支持类型：bar(柱状图), line(折线图), pie(饼图), scatter(散点图), grouped_bar(分组柱状图), stacked_bar(堆叠柱状图), radar(雷达图), boxplot(箱线图), heatmap(热力图)。自动选图时用chart_type='auto'",
            "4. knowledge: 从非结构化知识库检索信息。如果知道问题ID传入question_id精确匹配，否则传入query语义搜索。返回包含数据内容的结果。",
            "   分段读取：长内容会自动分段返回（每段默认2000字符）。当返回中显示 has_more=true 或出现[内容分段...]提示时，用提示中给出的 offset 值再次调用本工具继续读取后续内容，直到读完全文或已找到答案。",
            "5. report: 生成完整的决策分析报告（含图表+LLM洞察）",
            "6. statistical: 执行统计检验（T检验/方差分析/线性回归/卡方检验），适合比较差异、预测、分析关联性",
            "",
            "# 工具调用前请先在心中规划（Hermes scratch_pad 风格）：",
            "- Goal: 复述用户请求的目标",
            "- Actions: 列出将要调用的函数及参数（形如 functions.函数名(参数=值)），无需调用则写 None",
            "- Observation: 预判工具返回后需要关注的数据点",
            "- Reflection: 检查所选工具是否与目标相关、必需参数是否齐全；若不齐全，先补齐再调用",
            "规划完成后一次只调用一个工具，等待结果回传再决定下一步。",
            "",
            "# 工作流程",
            "1. 先用 query 获取数据（简单预测可跳过，直接 analyze forecast）",
            "2. 需要统计洞察时用 analyze",
            "3. 需要展示时用 visualize 生成图表",
            "4. 最后用文字给出结论",
            "5. 用户要预测时：analyze(action='forecast') → 如有结果再 visualize → 文字总结",
            "6. 接近轮次上限时不要再开新工具，直接根据已有结果写最终结论",
            "",
            "# visualize 使用铁律",
            "- 必须先用 query 查出要画的数据，再调 visualize；visualize 只会使用本轮最近一次 query 的结果绘图",
            "- 严禁在未执行 query 的情况下直接调用 visualize",
            "",
            "# 重要规则",
            "- SQL 中中文字段名必须用双引号括起来",
            "- 只用 SELECT 语句",
            "- 如果 SQL 报错，分析错误原因并重新生成正确的 SQL（工具结果会包在 tool 响应中回传）",
            "- 一次只调用一个工具",
            "- 给出结论时用中文，数据要结合具体数值",
        ]

        if t_count > 1:
            lines.append(f"\n# 当前系统有 {t_count} 张数据表")
            lines.append(f"可用表名: {', '.join(ctx.get('table_names', []))}")
            lines.append("你可以在 SQL 中 JOIN 多张表进行联表分析。")

        if ctx.get("schema_text"):
            lines.append(f"\n# 数据表 Schema 信息\n{ctx['schema_text']}")

        if is_db:
            lines.append(f"\n# 数据源：数据库")
            lines.append("查询直接在数据库上执行，支持完整 SQL 语法。")

        if ctx.get("suggested_questions"):
            lines.append("\n# 用户可能感兴趣的问题\n" + "\n".join(
                f"- {q}" for q in ctx["suggested_questions"][:6]
            ))

        return "\n".join(lines)

    @staticmethod
    def _format_tool_result(result: dict) -> str:
        if not isinstance(result, (dict, list)):
            return str(result)
        if isinstance(result, list):
            # 知识检索结果：分段时保留完整分段内容，仅超长兜底截断
            if result and isinstance(result[0], dict) and result[0].get("id") and result[0].get("content"):
                c = result[0]["content"]
                if len(c) > 6000:
                    hint = f" [内容过长已兜底截断，总长{len(c)}字符，请用 offset 分段读取剩余部分]"
                    return f"[知识检索: {result[0]['id'][:8]}] {c[:6000]}{hint}"
                return f"[知识检索: {result[0]['id'][:8]}] {c}"
            return f"[结果列表: {len(result)} 项]"

        if result.get("error"):
            return f"执行出错: {result['error']}"

        if "chart_html" in result or "option" in result:
            return f"[图表已生成] 类型={result.get('chart_type','')} 标题={result.get('title','')}"

        if "columns" in result and "rows" in result:
            cols = result.get("columns", [])
            rows = result.get("rows", [])
            lines = [f"查询结果：{result.get('row_count', len(rows))} 行"]
            if result.get("tables_used"):
                lines.append(f"涉及表: {', '.join(result['tables_used'])}")
            lines.append(" | ".join(str(c) for c in cols))
            lines.append("-" * 60)
            for row in rows[:20]:
                lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
            if len(rows) > 20:
                lines.append(f"... 还有 {len(rows) - 20} 行")
            return "\n".join(lines)

        parts = []
        if result.get("insight"):
            parts.append(f"洞察: {result['insight']}")
        if result.get("results"):
            parts.append(f"数据: {result['results']}")
        return "\n".join(parts) if parts else str(result)

    @staticmethod
    def _classify_query(query: str) -> str:
        q = query.lower()
        if any(kw in q for kw in ("趋势", "变化", "增长", "走势", "逐月", "按月", "随时间")):
            return "trend"
        if any(kw in q for kw in ("对比", "比较", "vs", "versus")):
            return "comparison"
        if any(kw in q for kw in ("占比", "比例", "分布", "百分比", "饼图")):
            return "proportion"
        if any(kw in q for kw in ("筛选", "过滤", "大于", "小于", "等于", "条件", "where")):
            return "filter"
        if any(kw in q for kw in ("平均", "均值", "总和", "合计", "统计", "汇总", "每个", "各")):
            return "aggregation"
        return "aggregation"
