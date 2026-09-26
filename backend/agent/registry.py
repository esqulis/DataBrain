"""ToolRegistry: 工具注册与调度（后端版）"""

from agent.tool_schemas import ALL_TOOL_SCHEMAS
from tools.query import QueryTool
from tools.analyze import AnalyzeTool
from tools.visualize import VisualizeTool
from tools.report import ReportTool
from tools.statistical import StatisticalTool
from tools.knowledge import retrieve as knowledge_retrieve


class ToolRegistry:
    """工具注册中心 —— 注册、获取 schema、调度执行"""

    def __init__(self):
        self._tools = {}
        self.query = QueryTool()
        self.analyze = AnalyzeTool()
        self.visualize = VisualizeTool()
        self.report = ReportTool()
        self.statistical = StatisticalTool()
        self._data_engine = None
        self._register("query", self.query, "execute")
        self._register("analyze", self.analyze, "execute")
        self._register("visualize", self.visualize, "execute")
        self._register("report", self.report, "execute")
        self._register("statistical", self.statistical, "execute")
        self.execute_knowledge = lambda **kw: knowledge_retrieve(**kw)
        self._register("knowledge", self, "execute_knowledge")

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

    def _pick_table(self, args: dict | None) -> str | None:
        if not self._data_engine:
            return None
        table = None
        if isinstance(args, dict):
            table = args.get("table") or args.get("table_name")
        if table and self._data_engine.has_table(table):
            return table
        names = self._data_engine.table_names
        return names[0] if names else None

    def _load_for_analyze(self, table: str, action: str, args: dict) -> "object":
        """按动作加载数据；大表 forecast/trend 优先走 SQL 月度聚合"""
        engine = self._data_engine
        action = action or "describe"

        if action in ("forecast", "trend"):
            meta_rows = engine.table_row_count(table)
            # 大表：SQL 聚合成月度序列（通常几十~几百点）
            if meta_rows > 5000:
                params = args.get("params") or {}
                date_col = params.get("date_col")
                target_col = params.get("target_col")
                if not target_col:
                    cols = args.get("columns") or []
                    target_col = cols[0] if cols else None
                if date_col and target_col:
                    agg_df = engine.sql_monthly_series(table, date_col, target_col)
                    if agg_df is not None and len(agg_df) >= 3:
                        # forecast 期望原始日期列名，聚合后 date_col 列已是 YYYY-MM
                        return agg_df
            return engine.get_df(table, max_rows=10000)

        # describe/correlation/outlier 等：仍取样本，但大表可先 SQL 粗统计
        max_rows = 1000
        return engine.get_df(table, max_rows=max_rows)

    def execute(self, tool_name: str, args: dict, df=None) -> dict:
        """执行工具调用"""
        entry = self._tools.get(tool_name)
        if not entry:
            return {"success": False, "error": f"未知工具: {tool_name}"}

        instance, method_name = entry
        method = getattr(instance, method_name)

        if tool_name in ("analyze", "visualize", "statistical"):
            table = self._pick_table(args if isinstance(args, dict) else None)
            if isinstance(args, dict):
                args.pop("table", None)
                args.pop("table_name", None)
            if df is None and self._data_engine and table:
                if tool_name == "analyze":
                    df = self._load_for_analyze(table, args.get("action", "describe"), args)
                else:
                    action = args.get("action") if isinstance(args, dict) else None
                    max_rows = 10000 if action in ("forecast", "trend") else 1000
                    df = self._data_engine.get_df(table, max_rows=max_rows)
            # analyze 需要 action 和 columns，如果缺失则自动补全
            if tool_name == "analyze":
                if "action" not in args:
                    args["action"] = "describe"
                if "columns" not in args and df is not None:
                    args["columns"] = list(df.columns)
            result = method(df, **args)
        elif tool_name == "query":
            result = method(df, **args)
        else:
            result = method(**args)

        if result is None:
            return {"success": False, "error": "工具返回空"}
        return result
