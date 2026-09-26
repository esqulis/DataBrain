"""UserPreferences: 记录用户的使用偏好"""


class UserPreferences:
    """用户偏好引擎"""

    def __init__(self):
        self.store = {
            "chart_preferred": True,
            "detail_level": "normal",
            "preferred_chart_types": {
                "trend": "line",
                "comparison": "bar",
                "proportion": "pie",
            },
            "max_rows_shown": 20,
            "language": "zh-CN",
        }

    def update_from_feedback(self, feedback_type: str, value: any):
        """从用户显式/隐式反馈更新偏好"""
        if feedback_type == "chart_preferred":
            self.store["chart_preferred"] = bool(value)
        elif feedback_type == "detail_level":
            if value in ("brief", "normal", "detailed"):
                self.store["detail_level"] = value
        elif feedback_type == "chart_type_preference":
            analysis_type, chart_type = value
            if analysis_type in self.store["preferred_chart_types"]:
                self.store["preferred_chart_types"][analysis_type] = chart_type
        elif feedback_type == "max_rows":
            self.store["max_rows_shown"] = max(5, min(100, int(value)))

    def get_style_hint(self) -> str:
        """返回注入到 system prompt 的风格提示"""
        hints = []
        if self.store["chart_preferred"]:
            hints.append("优先使用图表展示结果。")
        if self.store["detail_level"] == "brief":
            hints.append("结论简洁，只给出关键数字。")
        elif self.store["detail_level"] == "detailed":
            hints.append("给出详细的分析过程和中间数据。")
        return "\n".join(hints)

    def to_dict(self) -> dict:
        return dict(self.store)

    @classmethod
    def from_dict(cls, data: dict) -> "UserPreferences":
        obj = cls()
        if data:
            obj.store.update(data)
        return obj
