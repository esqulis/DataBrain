"""ToolRegistry: 工具注册与调度"""

from core.tool_schemas import ALL_TOOL_SCHEMAS
from tools.query import QueryTool
from tools.analyze import AnalyzeTool
from tools.visualize import VisualizeTool
from tools.report import ReportTool


class ToolRegistry:
    """工具注册中心 —— 注册、获取 schema、调度执行"""

    def __init__(self):
        self._tools = {}
        self.query = QueryTool()
        self.analyze = AnalyzeTool()
        self.visualize = VisualizeTool()
        self.report = ReportTool()
        self._data_engine = None
        self._register("query", self.query, "execute")
        self._register("analyze", self.analyze, "execute")
        self._register("visualize", self.visualize, "execute")
        self._register("report", self.report, "execute")

    def set_data_engine(self, engine):
        """注入多表数据引擎"""
        self._data_engine = engine
        self.query.set_data_engine(engine)

    def clear_data_engine(self):
        self._data_engine = None
        self.query.clear_data_engine()

    def set_db_connector(self, connector):
        self.query.set_db_connector(connector)

    def clear_db_connector(self):
        self.query.clear_db_connector()

    @property
    def is_db_mode(self) -> bool:
        return self.query.is_db_mode

    def _register(self, name: str, instance, method: str):
        self._tools[name] = (instance, method)

    def get_schemas(self) -> list[dict]:
        return list(ALL_TOOL_SCHEMAS)

    @property
    def last_successful_sql(self) -> str | None:
        return self.query.last_successful_sql

    def execute(self, tool_name: str, args: dict, df=None) -> dict:
        """执行工具调用"""
        entry = self._tools.get(tool_name)
        if not entry:
            return {"success": False, "error": f"未知工具: {tool_name}"}

        instance, method_name = entry
        method = getattr(instance, method_name)

        if tool_name in ("analyze", "visualize"):
            # 如果 DataEngine 有多个表，使用第一个主表作为 df
            if df is None and self._data_engine and self._data_engine.table_count > 0:
                primary = self._data_engine.table_names[0]
                df = self._data_engine.get_df(primary)
            result = method(df, **args)
        elif tool_name == "query":
            result = method(df, **args)
        else:
            result = method(**args)

        if result is None:
            return {"success": False, "error": "工具返回空"}
        return result
