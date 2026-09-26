"""visualize 工具：ECharts 图表生成"""

import json
import hashlib


class VisualizeTool:
    """可视化工具 —— 自动选图 + ECharts option 生成（JSON 模式供前端 VChart 渲染）"""

    def execute(self, df, **kwargs) -> dict:
        """兼容旧接口：内部调用 execute_json，额外生成 HTML"""
        result = self.execute_json(df, **kwargs)
        if result.get("option"):
            result["chart_html"] = self._render_echarts(result["option"])
        return result

    def execute_json(self, df, **kwargs) -> dict:
        """主入口

        支持的参数（来自 LLM）:
          - data_description: 数据内容描述
          - chart_type: 图表类型 auto/bar/line/pie/scatter/grouped_bar/stacked_bar
          - title: 图表标题
          - query_result: 前一步 query 的结果 dict（如有）
        """
        data_desc = kwargs.get("data_description", "")
        chart_type = kwargs.get("chart_type", "auto")
        title = kwargs.get("title", "数据分析图表")
        query_result = kwargs.get("query_result")

        # 优先使用 query_result（有 columns+rows 即可用；success 缺失也接受）
        if query_result and query_result.get("columns") and query_result.get("rows") is not None:
            columns = query_result.get("columns", [])
            rows = query_result.get("rows", [])
            # 如果查询结果太大（>500行），用聚合代替全量出图
            if len(rows) > 500 and columns:
                import pandas as pd
                try:
                    pdf = pd.DataFrame(rows, columns=columns)
                    cat_cols = [c for c in columns if pdf[c].dtype == 'object']
                    num_cols = [c for c in columns if pdf[c].dtype in ('int64','float64')]
                    if cat_cols and num_cols:
                        agg = pdf.groupby(cat_cols[0])[num_cols[:3]].mean().reset_index()
                        columns = list(agg.columns)
                        rows = [list(r) for r in agg.values]
                except Exception:
                    pass  # 聚合失败就用原始数据
        else:
            columns = []
            rows = []
            # 从 df 取前 100 行
            for col in df.columns:
                columns.append(col)
            for _, row in df.head(100).iterrows():
                rows.append([self._safe(v) for v in row])

        if not columns or not rows:
            return {
                "option": None,
                "chart_type": "none",
                "title": title,
                "insight": "没有数据",
            }

        # 自动选图
        if chart_type == "auto":
            chart_type = self._infer_chart_type(columns, rows, data_desc)
        chart_type = self._normalize_chart_type(chart_type)

        # 提取维度列与数值列
        dim_col, val_cols = self._split_dim_values(columns, rows)
        config = self._build_chart_config(chart_type, title, columns, rows, dim_col, val_cols)

        insight = f"已生成{title}（{chart_type}）"
        return {
            "option": config,
            "chart_type": chart_type,
            "title": title,
            "insight": insight,
        }

    # ----------------------------------------------------------------
    # 自动选图
    # ----------------------------------------------------------------
    def _infer_chart_type(self, columns, rows, desc: str) -> str:
        desc_lower = desc.lower()
        if any(w in desc_lower for w in ("饼图", "占比", "比例", "pie")):
            return "pie"
        if any(w in desc_lower for w in ("散点", "scatter", "相关性")):
            return "scatter"
        if any(w in desc_lower for w in ("趋势", "走势", "变化", "线图", "line")):
            return "line"
        if any(w in desc_lower for w in ("堆叠", "stack")):
            return "stacked_bar"
        if any(w in desc_lower for w in ("雷达", "radar", "多维度", "综合评分")):
            return "radar"
        if any(w in desc_lower for w in ("箱线", "boxplot", "异常值", "离群")):
            return "boxplot"
        if any(w in desc_lower for w in ("热力", "heatmap", "热度", "密集")):
            return "heatmap"

        dim, vals = self._split_dim_values(columns, rows)
        # 计算每个维度的唯一值数量
        dim_idx = 0
        if dim and dim in columns:
            dim_idx = columns.index(dim)
        n_cats = len(set(self._row_str(r, dim_idx) for r in rows)) if dim else 0
        n_vals = len(vals)
        if n_cats > 20 and n_vals == 1:
            return "bar"
        if n_cats <= 12 and n_vals == 1:
            return "pie"
        if n_vals > 3:
            return "grouped_bar"
        if n_vals > 1:
            return "grouped_bar"
        return "bar"

    def _normalize_chart_type(self, ct: str) -> str:
        mapping = {
            "柱状图": "bar", "条形图": "bar", "bar": "bar",
            "折线图": "line", "line": "line",
            "饼图": "pie", "pie": "pie",
            "散点图": "scatter", "scatter": "scatter",
            "分组柱状图": "grouped_bar", "grouped_bar": "grouped_bar",
            "堆叠柱状图": "stacked_bar", "stacked": "stacked_bar", "stacked_bar": "stacked_bar",
            "雷达图": "radar", "radar": "radar",
            "箱线图": "boxplot", "boxplot": "boxplot",
            "热力图": "heatmap", "heatmap": "heatmap",
        }
        return mapping.get(ct, "bar")

    # ----------------------------------------------------------------
    # 维度/数值列拆分
    # ----------------------------------------------------------------
    def _split_dim_values(self, columns, rows):
        """智能拆分：找字符串/类别列作维度，数值列作值"""
        if not columns:
            return None, []

        import re
        _id_pat = re.compile(r"(^|_)(id|no|num|code|编号|号码)$|编号|identifier", re.I)

        # 判断列是数值的规则：检查第一行的值
        def _is_num_col(idx):
            for r in rows[:5]:
                try:
                    float(r[idx])
                    return True
                except (ValueError, TypeError, IndexError):
                    pass
            return False

        # ID 类列（列名像主键/编号）：永远不当数值系列，也优先不当维度
        def _is_id_col(idx):
            return bool(_id_pat.search(str(columns[idx])))

        numeric_indices = [i for i in range(len(columns)) if _is_num_col(i) and not _is_id_col(i)]
        cat_indices = [i for i in range(len(columns)) if i not in numeric_indices]

        # 维度优先选"低基数类别列"（取值数最少且 ≥2），避免拿几十万唯一值的 ID 列当 X 轴
        def _card(idx):
            return len(set(self._row_str(r, idx) for r in rows))
        if cat_indices:
            non_id = [i for i in cat_indices if not _is_id_col(i)] or cat_indices
            dim_idx = min(non_id, key=_card) if len(non_id) > 1 else non_id[0]
            dim = columns[dim_idx]
            vals = [columns[i] for i in numeric_indices if i != dim_idx]
        elif numeric_indices:
            dim = columns[numeric_indices[0]]
            vals = [columns[i] for i in numeric_indices[1:]]
        else:
            dim = columns[0]
            vals = columns[1:]

        return dim, vals

    # ----------------------------------------------------------------
    # ECharts 配置
    # ----------------------------------------------------------------
    def _build_chart_config(self, chart_type, title, columns, rows, dim_col, val_cols):
        idx_map = {c: i for i, c in enumerate(columns)}
        dim_idx = idx_map.get(dim_col, 0)

        config = {
            "title": {"text": title, "textStyle": {"color": "#e0e0e0", "fontSize": 16}},
            "tooltip": {"trigger": "axis", "backgroundColor": "rgba(30,30,40,0.9)",
                        "borderColor": "#555", "textStyle": {"color": "#fff"}},
            "backgroundColor": "transparent",
            "grid": {"left": "3%", "right": "4%", "bottom": "10%", "containLabel": True},
        }

        labels = [self._row_str(r, dim_idx) for r in rows] if rows else []
        is_pie_friendly = len(set(labels)) <= 15 and len(val_cols) <= 2

        # ── 雷达图 ──
        if chart_type == "radar":
            indicators = [{"name": self._row_str(r, dim_idx), "max": max(self._row_val(r, idx_map.get(val_cols[0], 1)) for r in rows) * 1.2 or 100} for r in rows]
            series_data = []
            for vi, vcol in enumerate(val_cols[:1]):
                vidx = idx_map.get(vcol, vi + 1)
                series_data.append({"value": [self._row_val(r, vidx) for r in rows], "name": vcol})
            config["radar"] = {"indicator": indicators, "center": ["50%", "55%"], "radius": "65%"}
            config["series"] = [{"type": "radar", "data": series_data, "symbol": "none", "lineStyle": {"width": 2}}]
            config["tooltip"] = {"trigger": "item"}
            return config

        # ── 箱线图 ──
        if chart_type == "boxplot":
            import statistics
            data = []
            for vi, vcol in enumerate(val_cols[:5]):
                vidx = idx_map.get(vcol, vi + 1)
                vals = sorted([self._row_val(r, vidx) for r in rows if self._row_val(r, vidx) != 0])
                if vals:
                    q1, q2, q3 = statistics.quantiles(vals, n=4)
                    data.append([min(vals), q1, q2, q3, max(vals)])
            config["xAxis"] = {"type": "category", "data": val_cols[:5], "name": dim_col, "nameTextStyle": {"color": "#999", "fontSize": 12}, "axisLabel": {"color": "#999"}}
            config["yAxis"] = {"type": "value", "name": val_cols[0] if val_cols else "", "nameTextStyle": {"color": "#999", "fontSize": 12}, "axisLabel": {"color": "#999"}}
            config["series"] = [{"type": "boxplot", "data": data, "itemStyle": {"color": "#5B8FF9", "borderColor": "#333"}}]
            return config

        # ── 热力图 ──
        if chart_type == "heatmap":
            x_cats = list(dict.fromkeys(self._row_str(r, dim_idx) for r in rows))[:15]
            y_cats = val_cols[:8]
            heat_data = []
            for ri, r in enumerate(rows[:15]):
                for ci, c in enumerate(y_cats):
                    cidx = idx_map.get(c, ci + 1)
                    heat_data.append([ri, ci, self._row_val(r, cidx)])
            config["xAxis"] = {"type": "category", "data": x_cats, "axisLabel": {"rotate": 45, "color": "#999"}}
            config["yAxis"] = {"type": "category", "data": y_cats, "axisLabel": {"color": "#999"}}
            config["visualMap"] = {"min": 0, "max": max(d[2] for d in heat_data) or 1, "calculable": True, "orient": "horizontal", "left": "center", "bottom": "0%"}
            config["series"] = [{"type": "heatmap", "data": heat_data, "label": {"show": True, "color": "#333"}, "emphasis": {"itemStyle": {"shadowBlur": 10}}}]
            return config

        if chart_type == "pie":
            val_idx = idx_map.get(val_cols[0], 1) if val_cols else 1
            data = [{"name": self._row_str(r, dim_idx), "value": self._row_val(r, val_idx)} for r in rows[:20]]
            config["series"] = [{
                "type": "pie",
                "radius": ["30%", "60%"],
                "center": ["50%", "55%"],
                "data": data,
                "label": {"color": "#ccc", "fontSize": 12},
                "itemStyle": {"borderColor": "transparent"},
                "emphasis": {"itemStyle": {"shadowBlur": 10, "shadowColor": "rgba(0,0,0,0.3)"}},
            }]
            config["tooltip"] = {"trigger": "item", "formatter": "{b}: {c} ({d}%)"}
            return config

        if chart_type == "scatter":
            x_idx = idx_map.get(val_cols[0], 1) if len(val_cols) > 0 else 1
            y_idx = idx_map.get(val_cols[1], 2) if len(val_cols) > 1 else x_idx
            data = [[self._row_val(r, x_idx), self._row_val(r, y_idx), self._row_str(r, dim_idx)] for r in rows]
            config["xAxis"] = {"type": "value", "name": val_cols[0] if len(val_cols) > 0 else "", "nameTextStyle": {"color": "#999", "fontSize": 12}, "axisLabel": {"color": "#999"}}
            config["yAxis"] = {"type": "value", "name": val_cols[1] if len(val_cols) > 1 else "", "nameTextStyle": {"color": "#999", "fontSize": 12}, "axisLabel": {"color": "#999"}}
            config["series"] = [{
                "type": "scatter",
                "data": [[d[0], d[1]] for d in data],
                "symbolSize": 12,
                "itemStyle": {"color": "#5B8FF9", "opacity": 0.7},
            }]
            return config

        # 柱状图 / 折线图
        is_line = chart_type == "line"
        series = []
        colors = ["#5B8FF9", "#F6BD16", "#E86452", "#6DC8EC", "#945FB9", "#FF9845"]

        if chart_type in ("grouped_bar", "stacked_bar"):
            for vi, vcol in enumerate(val_cols):
                vidx = idx_map.get(vcol, vi + 1)
                series.append({
                    "type": "bar" if not is_line else "line",
                    "name": vcol,
                    "data": [self._row_val(r, vidx) for r in rows],
                    "itemStyle": {"color": colors[vi % len(colors)]},
                })
        else:
            val_idx = idx_map.get(val_cols[0], 1) if val_cols else 1
            series.append({
                "type": "bar" if not is_line else "line",
                "name": val_cols[0] if val_cols else "值",
                "data": [self._row_val(r, val_idx) for r in rows],
                "itemStyle": {"color": colors[0]},
            })

        if chart_type == "stacked_bar":
            for s in series:
                s["stack"] = "total"

        config["legend"] = {"data": [s["name"] for s in series], "textStyle": {"color": "#aaa"}}
        # 计算标签平均长度，用于决定是否显示文本
        avg_label_len = sum(len(l) for l in labels) / max(len(labels), 1)
        show_label_text = avg_label_len < 30  # 长文本标签不显示文字，靠 tooltip 悬停
        x_label_cfg = {"color": "#999", "rotate": 30}
        if not show_label_text:
            x_label_cfg["show"] = False
        else:
            x_label_cfg["interval"] = max(1, len(labels)//15 - 1)
        config["xAxis"] = {"type": "category", "data": labels, "name": dim_col, "nameTextStyle": {"color": "#999", "fontSize": 12}, "axisLabel": x_label_cfg}
        config["yAxis"] = {"type": "value", "name": val_cols[0] if val_cols else "", "nameTextStyle": {"color": "#999", "fontSize": 12}, "axisLabel": {"color": "#999"}}
        for s in series:
            s["barMaxWidth"] = 40
        config["series"] = series

        if rows and len(rows) > 10:
            config["dataZoom"] = [
                {"type": "inside", "start": 0, "end": 30},
                {"type": "inside", "yAxisIndex": 0, "start": 0, "end": 100},
            ]
            config["yAxis"]["min"] = 0

        return config

    # ----------------------------------------------------------------
    # 安全行访问
    # ----------------------------------------------------------------
    @staticmethod
    def _row_val(row: list, idx: int) -> float:
        """安全获取行中指定索引的值，越界返回 0"""
        try:
            return float(row[idx]) if row[idx] is not None else 0
        except (IndexError, ValueError, TypeError):
            return 0

    @staticmethod
    def _row_str(row: list, idx: int) -> str:
        """安全获取行中指定索引的字符串，越界返回 ''"""
        try:
            return str(row[idx]) if row[idx] is not None else ""
        except IndexError:
            return ""

    # ----------------------------------------------------------------
    # 渲染 HTML
    # ----------------------------------------------------------------
    def _render_echarts(self, config: dict) -> str:
        uid = hashlib.md5(json.dumps(config, sort_keys=True).encode()).hexdigest()[:8]
        config_json = json.dumps(config, ensure_ascii=False)
        return f"""<div id="chart-{uid}" style="width:100%;height:400px;"></div>
<script>
try {{
    var chart = echarts.init(document.getElementById('chart-{uid}'));
    chart.setOption({config_json});
    window.addEventListener('resize', function(){{ chart.resize(); }});
}} catch(e) {{ console.error('chart error:', e); }}
</script>"""

    @staticmethod
    def _num(v):
        try:
            return float(v) if v is not None else 0
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe(v):
        if isinstance(v, (int, float)):
            return v
        if v is None:
            return None
        return str(v)
