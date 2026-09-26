import os
import json
from datetime import datetime

class ReportGenerator:
    def __init__(self, output_dir, stats_dict, chart_paths):
        self.output_dir = output_dir
        self.stats = stats_dict
        self.charts = chart_paths
        self.time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def generate_txt(self):
        """生成纯文本报告 .txt"""
        txt_path = os.path.join(self.output_dir, "analysis_report.txt")
        lines = [
            "=" * 60,
            f"数据分析自动报告 | 生成时间：{self.time_str}",
            "=" * 60,
            "\n【一、数据基础信息】",
            f"数据行数：{self.stats['shape'][0]}  数据列数：{self.stats['shape'][1]}",
            f"数值字段列表：{self.stats['num_cols']}",
            f"缺失值统计：{self.stats['missing']}",
            "\n【二、描述性统计】"
        ]
        for col, desc in self.stats["describe"].items():
            lines.append(f"\n字段 {col}:")
            for k, v in desc.items():
                lines.append(f"  {k}: {v:.4f}")

        lines.extend([
            "\n【三、相关性矩阵】",
            str(self.stats["corr"]),
            "\n【四、生成图表清单】"
        ])
        for p in self.charts:
            lines.append(f"- {p}")

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return txt_path

    def generate_json(self):
        """生成JSON结构化报告"""
        json_path = os.path.join(self.output_dir, "analysis_report.json")
        data = {
            "report_time": self.time_str,
            "basic_info": {
                "rows": self.stats["shape"][0],
                "cols": self.stats["shape"][1],
                "numeric_columns": self.stats["num_cols"],
                "missing_count": self.stats["missing"]
            },
            "descriptive_statistics": self.stats["describe"],
            "correlation_matrix": self.stats["corr"].to_dict(),
            "chart_file_list": self.charts
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return json_path

    def generate_html(self):
        """生成带样式HTML可视化报告"""
        html_path = os.path.join(self.output_dir, "analysis_report.html")
        chart_html = ""
        for img in self.charts:
            chart_html += f'<div style="margin:20px 0;"><h3>{os.path.basename(img)}</h3><img src="{img}" style="max-width:90%;border:1px solid #ccc;"></div>'

        html_template = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>数据分析报告</title>
<style>
body{{font-family:Microsoft YaHei;margin:30px;background:#f7f9fc;}}
.box{{background:#fff;padding:20px;border-radius:8px;box-shadow:0 1px 5px #ddd;margin-bottom:20px;}}
h1{{color:#2c3e50;}}
h2{{color:#34495e;border-left:4px solid #3498db;padding-left:10px;}}
table{{border-collapse:collapse;width:100%;margin:10px 0;}}
td,th{{border:1px solid #ddd;padding:8px;text-align:center;}}
th{{background:#3498db;color:white;}}
</style>
</head>
<body>
<div class="box">
<h1>📊 自动数据分析报告</h1>
<p>生成时间：{self.time_str}</p>
</div>

<div class="box">
<h2>一、数据概况</h2>
<p>数据集尺寸：{self.stats['shape'][0]}行 × {self.stats['shape'][1]}列</p>
<p>数值字段：{self.stats['num_cols']}</p>
<p>缺失值总量：{self.stats['missing']}</p>
</div>

<div class="box">
<h2>二、描述性统计</h2>
<table>
<tr><th>字段</th><th>均值</th><th>标准差</th><th>最小值</th><th>中位数</th><th>最大值</th></tr>
"""
        for col, desc in self.stats["describe"].items():
            html_template += f"""
<tr>
<td>{col}</td>
<td>{desc['mean']:.2f}</td>
<td>{desc['std']:.2f}</td>
<td>{desc['min']:.2f}</td>
<td>{desc['50%']:.2f}</td>
<td>{desc['max']:.2f}</td>
</tr>
"""
        html_template += f"""
</table>
</div>

<div class="box">
<h2>三、全部可视化图表</h2>
{chart_html}
</div>
</body>
</html>
"""
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_template)
        return html_path

    def generate_all(self, fmt="all"):
        """批量生成报告：txt/html/json"""
        res = {}
        if fmt in ["all", "txt"]:
            res["txt"] = self.generate_txt()
        if fmt in ["all", "json"]:
            res["json"] = self.generate_json()
        if fmt in ["all", "html"]:
            res["html"] = self.generate_html()
        return res