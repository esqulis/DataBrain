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
        "description": "对数据进行统计分析：描述性统计、相关性、分布、异常值、趋势，以及时序预测（forecast）",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "describe", "correlation", "groupby",
                        "trend", "distribution", "outlier", "forecast"
                    ],
                    "description": "分析类型。forecast=时序预测，需在 params 中给出 date_col、target_col、periods"
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要分析的列名列表（forecast 时填目标数值列即可）"
                },
                "table": {
                    "type": "string",
                    "description": "可选：指定分析哪张表。多表时务必填写用户点名的表，如 monthly_bills"
                },
                "params": {
                    "type": "object",
                    "description": "额外参数",
                    "properties": {
                        "groupby_col": {"type": "string"},
                        "target_col": {"type": "string", "description": "目标数值列（forecast/groupby）"},
                        "date_col": {"type": "string", "description": "日期/月份列（forecast/trend）"},
                        "periods": {"type": "integer", "description": "预测期数，默认 10"},
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
                    "enum": ["auto", "bar", "line", "pie", "scatter", "grouped_bar", "stacked_bar", "radar", "boxplot", "heatmap"],
                    "description": "图表类型：auto让系统自动选择，radar雷达图, boxplot箱线图, heatmap热力图",
                },
                "data_description": {
                    "type": "string",
                    "description": "要展示的数据内容描述"
                },
                "title": {
                    "type": "string",
                    "description": "图表标题"
                },
                "table": {
                    "type": "string",
                    "description": "可选：指定从哪张表取数绘图（多表时必填）"
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

STATISTICAL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "statistical",
        "description": "执行统计假设检验与分析：T检验（比较两组均值差异）、方差分析（ANOVA，比较多组均值差异）、线性回归（预测与归因分析）、卡方检验（类别变量关联性）。返回统计结果和文字解读。",
        "parameters": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["ttest", "anova", "linear_regression", "chisquare"],
                    "description": "统计方法：ttest=T检验(T检验)，anova=方差分析(ANOVA)，linear_regression=线性回归，chisquare=卡方检验"
                },
                "params": {
                    "type": "object",
                    "description": "方法参数。ttest需要 group_col(分组列)+test_cols(数值列) 或 popmean(总体均值)；anova需要 group_col(分组列)+test_cols(数值列)；linear_regression需要 target(目标变量)+features(自变量列表)；chisquare需要 row_col(行变量)+col_col(列变量)",
                    "properties": {
                        "group_col": {"type": "string", "description": "分组变量列名（T检验/方差分析）"},
                        "test_cols": {"type": "array", "items": {"type": "string"}, "description": "要检验的数值列"},
                        "test_col": {"type": "string"},
                        "paired": {"type": "boolean", "description": "是否配对T检验"},
                        "popmean": {"type": "number", "description": "总体均值（单样本T检验）"},
                        "target": {"type": "string", "description": "目标变量（回归）"},
                        "features": {"type": "array", "items": {"type": "string"}, "description": "自变量列表（回归）"},
                        "row_col": {"type": "string", "description": "行变量（卡方检验）"},
                        "col_col": {"type": "string", "description": "列变量（卡方检验）"}
                    }
                }
            },
            "required": ["method", "params"]
        }
    }
}

# 延迟绑定
ALL_TOOL_SCHEMAS = [QUERY_SCHEMA, ANALYZE_SCHEMA, VISUALIZE_SCHEMA, REPORT_SCHEMA, STATISTICAL_SCHEMA]

KNOWLEDGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "knowledge",
        "description": "从非结构化知识库中检索信息。如果知道问题ID传入question_id精确匹配，否则传入query语义搜索。",
        "parameters": {
            "type": "object",
            "properties": {
                "question_id": {"type": "string", "description": "问题ID"},
                "query": {"type": "string", "description": "搜索文本"},
                "k": {"type": "integer", "description": "返回条数", "default": 3},
                "offset": {"type": "integer", "description": "分段读取起始字符位置，默认0。返回结果中 has_more=true 时，用上次的 offset+本次内容长度继续读取", "default": 0},
                "length": {"type": "integer", "description": "每段读取的字符数，默认2000", "default": 2000}
            }
        }
    }
}

ALL_TOOL_SCHEMAS = [QUERY_SCHEMA, ANALYZE_SCHEMA, VISUALIZE_SCHEMA, REPORT_SCHEMA, STATISTICAL_SCHEMA, KNOWLEDGE_SCHEMA]
