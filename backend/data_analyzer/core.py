import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.stats import pearsonr
from .report import ReportGenerator

# 全局中文字体配置
plt.rcParams["font.sans-serif"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False
sns.set_style("whitegrid")

class DataAnalysisPlatform:
    def __init__(self, output_dir="./output"):
        self.output_dir = output_dir
        self.chart_dir = os.path.join(output_dir, "charts")
        os.makedirs(self.chart_dir, exist_ok=True)
        self.df = None
        self.numeric_cols = []
        self.chart_path_list = []
        self.stat_result = {}

    def load_data(self, csv_path):
        """从csv文件加载数据"""
        self.df = pd.read_csv(csv_path)
        self._preprocess()
        return self

    def load_from_dataframe(self, df):
        """直接传入DataFrame加载数据（业务系统嵌入用）"""
        self.df = df.copy()
        self._preprocess()
        return self

    def _preprocess(self):
        """数据预处理：筛选数值列、统计缺失值"""
        self.numeric_cols = self.df.select_dtypes(include=[np.number]).columns.tolist()
        self.stat_result["shape"] = self.df.shape
        self.stat_result["num_cols"] = self.numeric_cols
        self.stat_result["missing"] = self.df.isnull().sum().sum()
        self.stat_result["describe"] = self.df[self.numeric_cols].describe().to_dict()
        self.stat_result["corr"] = self.df[self.numeric_cols].corr()

    def describe(self):
        """返回统计指标，供业务系统调用"""
        return self.stat_result

    # ===================== 8种图表绘制函数 =====================
    def _save_fig(self, name):
        path = os.path.join(self.chart_dir, f"{name}.png")
        plt.tight_layout()
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        self.chart_path_list.append(path)
        return path

    def plot_boxplot(self):
        """箱线图"""
        plt.figure(figsize=(10, 6))
        sns.boxplot(data=self.df[self.numeric_cols], palette="Set2")
        plt.title("各数值字段箱线图（分布与异常值）")
        return self._save_fig("01_箱线图")

    def plot_scatter_with_trend(self, x_col=None, y_col=None):
        """散点图+趋势线+相关系数标注，默认取前两列"""
        if not x_col: x_col = self.numeric_cols[0]
        if not y_col: y_col = self.numeric_cols[1]
        x = self.df[x_col].dropna()
        y = self.df[y_col].dropna()
        corr, p_val = pearsonr(x, y)

        plt.figure(figsize=(10, 6))
        sns.regplot(x=x, y=y, scatter_kws={"alpha":0.6}, line_kws={"color":"red"})
        plt.title(f"散点趋势图 {x_col} - {y_col} | r={corr:.3f} P={p_val:.4f}")
        plt.xlabel(x_col)
        plt.ylabel(y_col)
        return self._save_fig("02_散点趋势相关图")

    def plot_corr_heatmap(self):
        """相关性热力图"""
        plt.figure(figsize=(9,7))
        corr = self.df[self.numeric_cols].corr()
        sns.heatmap(corr, annot=True, cmap="coolwarm", vmin=-1, vmax=1, fmt=".2f")
        plt.title("变量相关性热力图")
        return self._save_fig("03_相关性热力图")

    def plot_bar_chart(self):
        """柱状图（均值对比）"""
        mean_data = self.df[self.numeric_cols].mean()
        plt.figure(figsize=(10,6))
        sns.barplot(x=mean_data.index, y=mean_data.values, palette="viridis")
        plt.title("各字段均值对比柱状图")
        plt.xticks(rotation=30)
        return self._save_fig("04_均值柱状图")

    def plot_donut_pie(self):
        """环形饼图（取第一列求和占比）"""
        val = self.df[self.numeric_cols[0]].value_counts()
        plt.figure(figsize=(7,7))
        wedges, texts, autotexts = plt.pie(val.values, labels=val.index, autopct="%.1f%%", pctdistance=0.8)
        centre_circle = plt.Circle((0,0), 0.60, fc="white")
        plt.gca().add_artist(centre_circle)
        plt.title(f"环形饼图 {self.numeric_cols[0]} 分布")
        return self._save_fig("05_环形饼图")

    def plot_line_time_trend(self):
        """时间折线图（用行索引模拟时间轴）"""
        plt.figure(figsize=(12,5))
        for col in self.numeric_cols[:3]:
            plt.plot(self.df.index, self.df[col], label=col, alpha=0.8)
        plt.legend()
        plt.grid(alpha=0.3)
        plt.title("时间趋势折线图（索引为时间序列）")
        return self._save_fig("06_时间趋势折线图")

    def plot_pair_scatter_matrix(self):
        """配对散点矩阵"""
        g = sns.pairplot(self.df[self.numeric_cols[:4]], diag_kind="kde")
        g.fig.suptitle("配对散点矩阵（多变量关系）", y=1.02)
        return self._save_fig("07_配对散点矩阵")

    def generate_all_charts(self):
        """一键生成全套8类图表"""
        self.chart_path_list.clear()
        self.plot_boxplot()
        self.plot_scatter_with_trend()
        self.plot_corr_heatmap()
        self.plot_bar_chart()
        self.plot_donut_pie()
        self.plot_line_time_trend()
        self.plot_pair_scatter_matrix()
        return self.chart_path_list

    def generate_report(self, fmt="all"):
        """生成 txt/html/json 报告"""
        reporter = ReportGenerator(self.output_dir, self.stat_result, self.chart_path_list)
        return reporter.generate_all(fmt=fmt)

    def auto_analyze(self):
        """一键全流程：加载-绘图-生成全部报告"""
        charts = self.generate_all_charts()
        reports = self.generate_report(fmt="all")
        return {
            "chart_list": charts,
            "report_files": reports,
            "stats": self.stat_result
        }