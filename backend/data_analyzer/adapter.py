"""data_analyzer 集成适配层 —— 接入 DataBrain 后端"""
import os, json, io, base64
from datetime import datetime
import pandas as pd
import numpy as np

class DataAnalyzerAdapter:
    """将 data_analyzer 的分析逻辑适配到 DataBrain 的 ECharts 体系"""

    def __init__(self, engine, output_dir: str = ""):
        self.engine = engine
        self.output_dir = output_dir or os.path.join(os.path.dirname(__file__), "..", "reports")
        os.makedirs(self.output_dir, exist_ok=True)

    def analyze_table(self, table_name: str) -> dict:
        """对指定表执行全自动分析，返回分析结果"""
        df = self.engine.get_df(table_name)
        if df is None or df.empty:
            return {"error": f"表 '{table_name}' 不存在或为空"}

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()

        # 描述性统计
        desc = df[numeric_cols].describe().to_dict() if numeric_cols else {}
        # 清洗 NaN/Inf 避免 JSON 序列化失败
        def _clean(v):
            if isinstance(v, float):
                if np.isnan(v) or np.isinf(v): return None
            return v
        desc = {col: {k: _clean(v) for k,v in stats.items()} for col,stats in desc.items()}

        # 相关性矩阵
        corr = df[numeric_cols].corr().round(4) if len(numeric_cols) > 1 else pd.DataFrame()
        corr_dict = corr.to_dict() if not corr.empty else {}
        corr_dict = {col: {k: _clean(v) for k,v in vals.items()} for col,vals in corr_dict.items()}

        # 缺失值
        missing = {col: int(df[col].isna().sum()) for col in df.columns}

        # 类别列分布
        cat_dist = {}
        for col in cat_cols[:5]:
            vc = df[col].value_counts().head(10)
            cat_dist[col] = {str(k): int(v) for k, v in vc.items()}

        # 异常值检测 (IQR)
        outliers = {}
        for col in numeric_cols:
            s = df[col].dropna()
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            low, high = q1 - 1.5*iqr, q3 + 1.5*iqr
            outlier_mask = (s < low) | (s > high)
            if outlier_mask.any():
                outliers[col] = {"count": int(outlier_mask.sum()), "ratio": round(float(outlier_mask.mean()*100), 1)}

        return {
            "table": table_name,
            "rows": len(df),
            "columns": len(df.columns),
            "numeric_cols": numeric_cols,
            "cat_cols": cat_cols,
            "describe": desc,
            "correlation": corr_dict,
            "missing": missing,
            "outliers": outliers,
            "cat_distribution": cat_dist,
        }

    def generate_report_html(self, analysis: dict, theme: str = "light") -> str:
        """从分析结果生成 HTML 报告，支持 light/dark 主题"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        table = analysis["table"]

        is_dark = theme == "dark"
        bg = "#1a1a2e" if is_dark else "#F5F0E8"
        box_bg = "#1f2b3d" if is_dark else "#fff"
        box_border = "#253548" if is_dark else "#EDE9E2"
        text_primary = "#e0e0e0" if is_dark else "#191919"
        text_secondary = "#b0b0b0" if is_dark else "#6B625A"
        text_muted = "#808080" if is_dark else "#9E968E"
        accent = "#D97757"
        th_bg = "#16213e" if is_dark else "#F5F0E8"
        th_color = "#b0b0b0" if is_dark else "#6B625A"
        td_color = "#e0e0e0" if is_dark else "#191919"
        tag_bg = "rgba(217,119,87,0.15)" if is_dark else "rgba(217,119,87,0.1)"

        # 统计表格
        desc_rows = ""
        for col, stats in analysis.get("describe", {}).items():
            desc_rows += f"<tr><td>{col}</td><td>{stats.get('mean',0):.2f}</td><td>{stats.get('std',0):.2f}</td><td>{stats.get('min',0):.2f}</td><td>{stats.get('50%',0):.2f}</td><td>{stats.get('max',0):.2f}</td></tr>"

        # 缺失值
        missing_rows = ""
        for col, cnt in analysis.get("missing", {}).items():
            if cnt > 0:
                missing_rows += f"<tr><td>{col}</td><td>{cnt}</td><td>{round(cnt/analysis['rows']*100,1)}%</td></tr>"

        # 异常值
        outlier_html = ""
        for col, info in analysis.get("outliers", {}).items():
            outlier_html += f"<p><b>{col}</b>: {info['count']} 个异常值 ({info['ratio']}%)</p>"

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>DataBrain 分析报告 - {table}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
body{{font-family:"Inter","Noto Sans SC",sans-serif;background:{bg};color:{text_primary};margin:0;padding:24px;-webkit-font-smoothing:antialiased}}
.box{{background:{box_bg};border:1px solid {box_border};border-radius:12px;padding:20px 24px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.04)}}
h1{{color:{text_primary};font-size:22px;margin:0 0 4px}}
h2{{color:{text_secondary};font-size:15px;border-left:3px solid {accent};padding-left:12px;margin:0 0 12px}}
p{{color:{text_secondary};font-size:14px;line-height:1.6;margin:0 0 8px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{padding:8px 12px;text-align:center;border-bottom:1px solid {box_border}}}
th{{background:{th_bg};color:{th_color};font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:0.05em}}
td{{color:{td_color}}}
.tag{{display:inline-block;padding:2px 12px;border-radius:99px;font-size:12px;background:{tag_bg};color:{accent};margin:2px}}
</style></head>
<body>
<div class="box"><h1>📊 DataBrain 自动分析报告</h1><p style="color:{text_muted};font-size:13px">数据表: {table} | {analysis['rows']}行×{analysis['columns']}列 | 生成: {now}</p></div>
<div class="box"><h2>📋 数据概况</h2>
<p>数值列: {', '.join(f'<span class="tag">{c}</span>' for c in analysis.get('numeric_cols',[]))}</p>
<p>类别列: {', '.join(f'<span class="tag">{c}</span>' for c in analysis.get('cat_cols',[]))}</p>
</div>
<div class="box"><h2>📈 描述性统计</h2>
<table><tr><th>字段</th><th>均值</th><th>标准差</th><th>最小值</th><th>中位数</th><th>最大值</th></tr>{desc_rows}</table></div>
{f'<div class="box"><h2>⚠️ 缺失值</h2><table><tr><th>字段</th><th>缺失数</th><th>缺失率</th></tr>{missing_rows}</table></div>' if missing_rows else ''}
{f'<div class="box"><h2>🔍 异常值检测</h2>{outlier_html}</div>' if outlier_html else ''}
</body></html>"""

    def generate_and_save(self, table_name: str, theme: str = "light") -> dict:
        """全自动分析 + 保存报告"""
        analysis = self.analyze_table(table_name)
        if "error" in analysis:
            return analysis

        # 保存 JSON
        json_path = os.path.join(self.output_dir, f"{table_name}_analysis.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)

        # 保存 HTML 报告
        html = self.generate_report_html(analysis, theme=theme)
        html_path = os.path.join(self.output_dir, f"{table_name}_report.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        return {
            "analysis": analysis,
            "report_html": html,
            "json_path": json_path,
            "html_path": html_path,
        }
