"""report 工具：自动生成决策分析报告"""
import json, hashlib, datetime, math
import pandas as pd
from shared_state import get_state
from tools.analyze import AnalyzeTool
from tools.visualize import VisualizeTool


def _clean_inf(obj):
    """递归清理 JSON 不兼容的 float 值（inf/NaN/-inf）"""
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _clean_inf(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_inf(v) for v in obj]
    return obj


class ReportTool:
    """决策报告生成工具 —— 综合统计 + 图表 + LLM 洞察"""

    def execute(self, topic: str = "", **kwargs) -> dict:
        state = get_state()
        engine = state.data_engine
        if engine.table_count == 0:
            return {"error": "尚未加载数据，请先上传数据"}
        tables = engine.table_names
        tbl = kwargs.get("table") or (tables[0] if tables else None)
        if not tbl:
            return {"error": "没有可用数据表"}
        df = engine.get_df(tbl)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        at = AnalyzeTool()
        stats = {}
        for action in ("describe", "correlation", "outlier"):
            r = at.execute(df, action, list(df.columns), {})
            if r and "error" not in r:
                stats[action] = r
        # 图表数据：大表自动聚合后出图，保证图与数据一致
        df_chart = df
        if len(df) > 500:
            cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
            num_cols = df.select_dtypes(include=["number"]).columns.tolist()
            if cat_cols and num_cols:
                # 用第一个类别列分组，对数值列求均值，保留趋势而非随机采样
                group_col = cat_cols[0]
                agg_cols = num_cols[:5]  # 最多5个数值列避免图太密
                try:
                    agg = df.groupby(group_col)[agg_cols].mean().reset_index()
                    df_chart = agg
                except Exception:
                    df_chart = df  # 聚合失败则回退
        chart = self._smart_chart(df_chart, topic, tbl)
        llm_insight = self._generate_insight(state, topic, tbl, df, stats)
        html = self._build_html(tbl, now, df, stats, chart["html"], llm_insight)
        out = f"决策报告已生成，覆盖 {len(df)} 行数据"
        result = {
            "report_html": html,
            "chart_option": chart["option"],
            "insight": f"{out}，包含描述统计、相关性、异常值检测和 {llm_insight.get('summary','')}",
            "table": tbl,
            "stats_summary": {
                "rows": len(df),
                "cols": len(df.columns),
                "describe_count": len(stats.get("describe", {}).get("results", {})),
                "outlier_columns": len(stats.get("outlier", {}).get("results", {})),
            },
        }
        # 清理 JSON 不兼容的 float（inf/NaN）
        return _clean_inf(result)

    @staticmethod
    def _smart_chart(df, topic, tbl):
        """智能出图 —— 使用 visualize tool 自动选类型"""
        vt = VisualizeTool()
        # 根据实际数据生成描述，帮助 AI 选对图
        nc = df.select_dtypes(include=["number"]).columns.tolist()
        cc = df.select_dtypes(include=["object", "category"]).columns.tolist()
        desc_parts = [f"{tbl} 数据分析"]
        if cc and nc:
            desc_parts.append(f"按{cc[0]}分组对比{nc[0]}")
        elif nc:
            desc_parts.append(f"{nc[0]}的数值分布")
        elif cc:
            desc_parts.append(f"{cc[0]}的类别分布和占比")
        data_desc = "，".join(desc_parts)
        desc = topic or data_desc
        r = vt.execute(df, chart_type="auto", title=f"{tbl} - {desc}", data_description=desc)
        opt = r.get("option")
        chart_html = ""
        if opt:
            import json
            opt_json = json.dumps(opt, ensure_ascii=False)
            import hashlib
            div_id = "chart-" + hashlib.md5(opt_json.encode()).hexdigest()[:8]
            chart_html = f'''<div id="{div_id}" style="width:100%;height:65vh;min-height:500px;margin:0 auto"></div>
<script>
try{{var c=echarts.init(document.getElementById("{div_id}"));
c.setOption({opt_json});
window.addEventListener('resize',function(){{c.resize()}});
}}catch(e){{console.error(e)}}</script>'''
        return {"html": chart_html, "option": opt}

    def _generate_insight(self, state, topic, tbl, df, stats) -> dict:
        brain = state.brain_manager.get_current_brain()
        if not brain:
            return {"summary": "数据统计概览", "detail": "未配置大脑"}
        nc = df.select_dtypes(include=["number"]).columns.tolist()
        parts = [f"数据表 '{tbl}'，{len(df)}行×{len(df.columns)}列"]
        if nc:
            desc = stats.get("describe", {}).get("results", {})
            for col in nc[:5]:
                if col in desc:
                    d = desc[col]
                    parts.append(f"- {col}: 均值{d.get('mean',0):.1f}, 范围[{d.get('min',0):.1f}~{d.get('max',0):.1f}]")
        # 类别列取值分布也喂给 LLM，避免它误判"数据缺少维度字段"
        cc = df.select_dtypes(include=["object", "category"]).columns.tolist()
        for col in cc[:6]:
            try:
                vc = df[col].value_counts(dropna=True).head(3)
                if len(vc):
                    items = "、".join(f"{k}({v})" for k, v in vc.items())
                    parts.append(f"- {col} 取值分布Top3: {items}")
            except Exception:
                pass
        outlier_data = stats.get("outlier", {}).get("results", {})
        if outlier_data:
            cols_with = [c for c, v in outlier_data.items() if v.get("outlier_count", 0) > 0]
            parts.append(f"- 异常值检出列: {', '.join(cols_with[:3])}")
        prompt = (
            f"你是一个数据分析专家。基于以下数据摘要，写一段200字以内的业务分析与决策建议。\n\n"
            f"{chr(10).join(parts)}\n\n用户关注的业务场景：{topic or '数据总体分析'}\n\n"
            f"请输出格式：\n【核心发现】(数据中最重要的2-3个现象)\n"
            f"【问题诊断】(需要注意的异常或风险)\n【决策建议】(基于数据的 actionable 建议)"
        )
        try:
            resp = brain.chat([{"role": "user", "content": prompt}], temperature=0.7)
            detail = resp.content
            detail = detail.encode("utf-8", errors="replace").decode("utf-8")
        except Exception as e:
            detail = f"洞察生成失败: {e}"
        return {"summary": f"含{len(nc)}个数值字段分析", "detail": detail}

    @staticmethod
    def _build_html(tbl, now, df, stats, chart_html, insight) -> str:
        nc = df.select_dtypes(include=["number"]).columns.tolist()
        desc_entries = ""
        desc_data = stats.get("describe", {}).get("results", {})
        for col in nc:
            d = desc_data.get(col, {})
            desc_entries += (
                f"<tr><td>{col}</td><td>{d.get('count',0)}</td>"
                f"<td>{d.get('mean',0):.2f}</td><td>{d.get('std',0):.2f}</td>"
                f"<td>{d.get('min',0):.2f}</td><td>{d.get('50%',0):.2f}</td>"
                f"<td>{d.get('max',0):.2f}</td></tr>")
        outlier_html = ""
        outlier_data = stats.get("outlier", {}).get("results", {})
        for col, v in outlier_data.items():
            if v.get("outlier_count", 0) > 0:
                outlier_html += (
                    f"<p class='tag'>{col}: {v['outlier_count']}个异常 ({v['outlier_ratio']}%)  "
                    f"正常范围 [{v['bounds']['low']}~{v['bounds']['high']}]</p>")
        detail_text = insight.get("detail", "").replace("\n", "<br>")
        body = f"""<div style="font-family:Inter,sans-serif;font-size:14px;line-height:1.6;color:#191919;padding:24px;background:#F5F0E8;min-height:100vh">
<div style="max-width:960px;margin:0 auto">
<div style="margin-bottom:16px"><h2 style="font-size:18px;margin:0 0 4px">DataBrain 决策分析报告</h2>
<p style="color:#6B625A;font-size:13px;margin:0">数据表: {tbl} | {len(df)}行×{len(df.columns)}列 | 生成: {now}</p></div>
<div style="margin-bottom:16px"><h3 style="font-size:15px;margin:0 0 8px">AI 洞察</h3><div style="background:#fff;border:1px solid #EDE9E2;border-radius:8px;padding:14px;font-size:13px">{detail_text}</div></div>
<div style="margin-bottom:16px"><h3 style="font-size:15px;margin:0 0 8px">可视化图表</h3><div style="background:#fff;border-radius:8px;padding:16px">{chart_html}</div></div>
<div style="margin-bottom:16px"><h3 style="font-size:15px;margin:0 0 8px">描述性统计</h3>
<div style="background:#fff;border-radius:8px;overflow:auto;padding:4px">
<table style="border-collapse:collapse;width:100%;font-size:12px"><tr style="background:#F5F0E8"><th style="padding:7px 10px;text-align:left;font-weight:600">字段</th><th style="padding:7px 10px;text-align:right">计数</th><th style="padding:7px 10px;text-align:right">均值</th><th style="padding:7px 10px;text-align:right">标准差</th><th style="padding:7px 10px;text-align:right">最小值</th><th style="padding:7px 10px;text-align:right">中位数</th><th style="padding:7px 10px;text-align:right">最大值</th></tr>{desc_entries}</table></div></div>
{f'<div style="margin-bottom:16px"><h3 style="font-size:15px;margin:0 0 8px">异常值检测</h3><div style="background:#fff;border-radius:8px;padding:12px;font-size:13px">{outlier_html}</div></div>' if outlier_html else ''}
</div></div>"""
        return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Inter","Noto Sans SC",sans-serif;-webkit-font-smoothing:antialiased}}
.tag{{margin-bottom:4px}}
</style></head><body>{body}</body></html>"""
