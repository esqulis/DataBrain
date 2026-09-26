"""query 工具：SQL 查询执行器（支持数据引擎 + 数据库直连）"""

import os
import sqlite3
import re
import pandas as pd

ENGINE_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "engine.db")
# 无 LIMIT 的 SELECT 默认最多取这么多行，防止全表拉进内存
DEFAULT_ROW_CAP = 1000


def _open_engine_db():
    """带 busy_timeout/WAL 的 engine.db 只读友好连接"""
    from memory.data_engine import connect_engine_db
    return connect_engine_db(ENGINE_DB)


def enforce_limit(sql: str, limit: int = DEFAULT_ROW_CAP) -> str:
    """若 SQL 未显式 LIMIT，则外包一层限制行数"""
    s = sql.strip().rstrip(";").strip()
    if not s:
        return s
    if re.search(r"\bLIMIT\s+\d+(\s*,\s*\d+)?\s*$", s, re.IGNORECASE):
        return s
    # 中间出现 LIMIT（子查询）也视为已限制，避免破坏语义
    if re.search(r"\bLIMIT\s+\d+", s, re.IGNORECASE):
        return s
    return f"SELECT * FROM ({s}) AS _q_limited LIMIT {int(limit)}"


class QueryTool:
    """SQL 查询执行器 —— 支持内存引擎(多表)和直连数据库"""

    def __init__(self):
        self._last_successful_sql: str | None = None
        self._db_connector = None
        self._data_engine = None

    def set_db_connector(self, connector):
        self._db_connector = connector

    def clear_db_connector(self):
        self._db_connector = None

    def set_data_engine(self, engine):
        """设置多表数据引擎"""
        self._data_engine = engine
        # 如果引擎中有数据库连接器，同步过来
        if engine:
            conn = engine.get_db_connector()
            if conn:
                self._db_connector = conn

    def clear_data_engine(self):
        self._data_engine = None

    @property
    def is_db_mode(self) -> bool:
        return self._db_connector is not None

    @property
    def last_successful_sql(self) -> str | None:
        return self._last_successful_sql

    def execute(self, df: pd.DataFrame, sql: str, **kwargs) -> dict:
        """执行 SQL 查询"""
        if not sql or not sql.strip():
            return {"success": False, "error": "SQL 为空"}

        sql_stripped = sql.strip()
        if not re.match(r"^\s*SELECT\s", sql_stripped, re.IGNORECASE):
            return {"success": False, "error": "只支持 SELECT 查询"}

        # ---- 数据库直连模式 ----
        if self._db_connector:
            result = self._db_connector.execute(sql_stripped, limit=500)
            if result.get("success"):
                self._last_successful_sql = sql_stripped
            return result

        # ---- 多表内存引擎模式 ----
        if self._data_engine and self._data_engine.table_count > 0:
            return self._execute_on_engine(sql_stripped)

        # ---- 单表内存引擎模式（向后兼容） ----
        return self._execute_on_single_df(df, sql_stripped)

    def _execute_on_engine(self, sql: str) -> dict:
        """在多表引擎上执行 SQL（数据在磁盘 SQLite 中）"""
        if not os.path.exists(ENGINE_DB):
            return {"success": False, "error": "数据库文件不存在", "columns": [], "rows": [], "row_count": 0, "sql": sql}
        conn = None
        sql_exec = enforce_limit(sql)
        try:
            conn = _open_engine_db()
            result_df = pd.read_sql_query(sql_exec, conn)

            rows = result_df.values.tolist()
            columns = list(result_df.columns)
            rows = [[self._safe(v) for v in row] for row in rows]

            self._last_successful_sql = sql
            return {
                "success": True,
                "columns": columns,
                "rows": rows[:100],
                "row_count": len(rows),
                "sql": sql,
                "sql_executed": sql_exec if sql_exec != sql else None,
                "tables_used": self._data_engine.table_names if self._data_engine else [],
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "columns": [], "rows": [], "row_count": 0, "sql": sql,
            }
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    def _execute_on_single_df(self, df: pd.DataFrame, sql: str) -> dict:
        """在单表上执行 SQL（旧兼容）"""
        conn = sqlite3.connect(":memory:")
        try:
            df.to_sql("data", conn, index=False, if_exists="replace")
            result_df = pd.read_sql_query(sql, conn)
            conn.close()

            rows = result_df.values.tolist()
            columns = list(result_df.columns)
            rows = [[self._safe(v) for v in row] for row in rows]

            self._last_successful_sql = sql
            return {
                "success": True,
                "columns": columns,
                "rows": rows[:100],
                "row_count": len(rows),
                "sql": sql,
            }
        except Exception as e:
            try:
                conn.close()
            except Exception:
                pass
            return {
                "success": False,
                "error": str(e),
                "columns": [], "rows": [], "row_count": 0, "sql": sql,
            }

    @staticmethod
    def _safe(v):
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            return v
        return str(v) if v is not None else None
