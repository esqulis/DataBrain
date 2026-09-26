import pandas as pd
import numpy as np
from data_analyzer import DataAnalysisPlatform

# ---------------------- 测试1：最简3行调用方式 ----------------------
if __name__ == "__main__":
    # 生成100行6列测试数据
    np.random.seed(42)
    test_df = pd.DataFrame({
        "销量": np.random.normal(100, 20, 100),
        "成本": np.random.normal(60, 15, 100),
        "广告投入": np.random.normal(30, 8, 100),
        "客流量": np.random.normal(500, 80, 100),
        "客单价": np.random.normal(25, 5, 100),
        "评分": np.random.randint(1,6,100)
    })
    test_df.to_csv("test_data.csv", index=False)

    # 最简调用
    platform = DataAnalysisPlatform(output_dir="./output")
    platform.load_data("test_data.csv")
    result = platform.auto_analyze()
    print("✅ 全套图表与报告生成完成！")
    print("图表文件：", result["chart_list"])
    print("报告文件：", result["report_files"])

    # ---------------------- 测试2：嵌入业务系统示例 ----------------------
    class YourBusinessSystem:
        def __init__(self):
            self.analyzer = DataAnalysisPlatform(output_dir="./reports")

        def process_df(self, df):
            self.analyzer.load_from_dataframe(df)
            stats = self.analyzer.describe()
            report = self.analyzer.generate_report(fmt="html")
            return stats, report

    print("\n===== 业务系统嵌入测试 =====")
    sys = YourBusinessSystem()
    stat_info, html_report = sys.process_df(test_df)
    print("统计指标示例：", stat_info["num_cols"])
    print("HTML报告路径：", html_report["html"])