"""工具 Schema 定义 —— 供 LLM function calling 使用"""

QUERY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "query",
        "description": "对数据执行 SQL 查询，获取结构化数据。适合筛选、聚合、分组统计等",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "要执行的 SQL SELECT 语句。列名如果是中文需加双引号。"
                },
                "natural_query": {
                    "type": "string",
                    "description": "用自然语言描述本次查询意图"
                }
            },
            "required": ["sql", "natural_query"]
        }
    }
}

ANALYZE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "analyze",
        "description": "对数据进行统计分析：描述性统计、相关性、分布、异常值检测、趋势分析等",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "describe", "correlation", "groupby",
                        "trend", "distribution", "outlier",
                        "forecast"
                    ],
                    "description": "分析操作类型。forecast: 时序预测（使用Prophet），需要指定日期列和目标数值列"
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要分析的列名列表"
                },
                "params": {
                    "type": "object",
                    "description": "额外参数，如 groupby_col, target_col, method 等",
                    "properties": {
                        "groupby_col": {"type": "string"},
                        "target_col": {"type": "string"},
                        "method": {"type": "string"}
                    }
                }
            },
            "required": ["action", "columns"]
        }
    }
}

VISUALIZE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "visualize",
        "description": "将数据绘制成图表（ECharts）。支持柱状图、折线图、饼图、散点图等",
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["auto", "bar", "line", "pie", "scatter", "grouped_bar", "stacked_bar"],
                    "description": "图表类型，auto 让系统自动选择"
                },
                "data_description": {
                    "type": "string",
                    "description": "要展示的数据内容描述"
                },
                "title": {
                    "type": "string",
                    "description": "图表标题"
                }
            },
            "required": ["data_description", "title"]
        }
    }
}


REPORT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report",
        "description": "生成一份完整的决策分析报告，包含描述统计、可视化图表、LLM业务洞察与决策建议。适合用户要求'生成报告'、'分析报告'、'决策报告'时调用",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "报告关注的业务场景或分析主题，如'销售情况'、'用户行为分析'"
                }
            },
            "required": ["topic"]
        }
    }
}

# 延迟绑定：等 REPORT_SCHEMA 定义后再组合
ALL_TOOL_SCHEMAS = [QUERY_SCHEMA, ANALYZE_SCHEMA, VISUALIZE_SCHEMA, REPORT_SCHEMA]
