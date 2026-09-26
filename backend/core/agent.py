"""AnalysisAgent: 对话式数据分析的主循环 (多表版)"""

import json

from core.llm_client import LLMClient
from core.tools import ToolRegistry
from memory.data_profiler import DataProfiler
from memory.pattern_memory import PatternMemory
from memory.preferences import UserPreferences


class AnalysisAgent:
    """数据分析 Agent 主循环"""

    def __init__(self, llm_client: LLMClient, tools: ToolRegistry,
                 profiler: DataProfiler, patterns: PatternMemory,
                 preferences: UserPreferences):
        self.llm = llm_client
        self.tools = tools
        self.profiler = profiler
        self.patterns = patterns
        self.prefs = preferences
        self.max_turns = 20
        self.history: list[dict] = []
        self._last_sql: str | None = None
        self._pending_charts: list[str] = []

    @property
    def last_successful_sql(self) -> str | None:
        return self._last_sql

    @staticmethod
    def _estimate_turns(query: str) -> int:
        """根据问题复杂度动态调整最大工具调用次数"""
        q = query.lower()
        # 简单查询：数据预览、简单过滤、计数
        simple = any(k in q for k in ("多少条", "有哪些", "列出", "预览", "show", "list", "count", "数据概况"))
        if simple:
            return 8
        # 中等：分组统计、排序、单表分析
        medium = any(k in q for k in ("统计", "排序", "分组", "group", "order", "平均", "sum", "前", "top", "最高", "最低"))
        if medium:
            return 15
        # 复杂：多表、预测、报告、可视化
        if any(k in q for k in ("报告", "report", "预测", "forecast", "趋势")):
            return 25
        if any(k in q for k in ("join", "多表", "关联", "对比", "analyse", "分析", "画", "图", "chart", "visual")):
            return 20
        # 默认
        return 15

    def process_query(self, user_input: str, data_source, data_context: dict) -> dict:
        """处理一条用户问题。
        data_source: DataEngine 实例（多表）或 DataFrame（单表兼容）
        """
        self._pending_charts = []

        system_prompt = self._build_system_prompt(data_context)

        # 检索相似 Pattern
        matched = self.patterns.retrieve(
            user_input, data_context.get("table_names", [""])[0] if data_context.get("table_names") else ""
        )
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

        max_turns = self._estimate_turns(user_input)

        for turn in range(max_turns):
            response = self.llm.chat(messages, tools=tool_schemas)

            if response.has_tool_calls:
                for tc in response.tool_calls:
                    messages.append({
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
                    })
                    result = self.tools.execute(tc["name"], tc["args"], df=None)
                    result_str = self._format_tool_result(result)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

                    if tc["name"] == "visualize" and result.get("chart_html"):
                        self._pending_charts.append(result["chart_html"])

                    if tc["name"] == "query" and result.get("success"):
                        self._last_sql = result.get("sql")
            else:
                final = response.content

                if self._last_sql:
                    qtype = self.patterns._classify_query(user_input)
                    tbl_name = ", ".join(data_context.get("table_names", []))
                    self.patterns.store(
                        user_input, self._last_sql,
                        table_name=tbl_name,
                        query_type=qtype,
                    )

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

    # ----------------------------------------------------------------
    def _build_system_prompt(self, ctx: dict) -> str:
        is_db = ctx.get("is_db_mode", False)
        t_count = ctx.get("table_count", 0)

        lines = [
            "你是一个智能数据分析助手，名为 DataBrain。",
            "你可以对用户上传的数据进行查询、分析和可视化。",
            "",
            "# 可用工具",
            "1. query: 用 SQL 查询数据（支持 SELECT 语句）",
            "2. analyze: 统计分析（描述性统计、相关性、分布、异常值等）",
            "3. visualize: 将数据绘制成 ECharts 图表",
            "4. report: 生成完整的决策分析报告（含图表+LLM洞察）",
            "",
            "# 工作流程",
            "1. 先用 query 获取数据",
            "2. 需要统计洞察时用 analyze",
            "3. 需要展示时用 visualize 生成图表",
            "4. 最后用文字给出结论",
            "",
            "# 重要规则",
            "- SQL 中中文字段名必须用双引号括起来",
            "- 只用 SELECT 语句",
            "- 如果 SQL 报错，分析错误原因并重新生成正确的 SQL",
            "- 一次只调用一个工具",
            "- 给出结论时用中文，数据要结合具体数值",
        ]

        # 多表上下文
        if t_count > 1:
            lines.append(f"\n# 当前系统有 {t_count} 张数据表")
            lines.append(f"可用表名: {', '.join(ctx.get('table_names', []))}")
            lines.append("你可以在 SQL 中 JOIN 多张表进行联表分析。")
            lines.append("")

        if ctx.get("schema_text"):
            lines.append(f"\n# 数据表 Schema 信息\n{ctx['schema_text']}")

        if is_db:
            lines.append(f"\n# 数据源：数据库 ({ctx.get('db_type', '')})")
            lines.append("查询直接在数据库上执行，支持完整 SQL 语法。")

        if ctx.get("suggested_questions"):
            lines.append("\n# 用户可能感兴趣的问题\n" + "\n".join(
                f"- {q}" for q in ctx["suggested_questions"][:6]
            ))

        return "\n".join(lines)

    # ----------------------------------------------------------------
    @staticmethod
    def _format_tool_result(result: dict) -> str:
        if result.get("error"):
            return f"执行出错: {result['error']}"

        if "chart_html" in result:
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
