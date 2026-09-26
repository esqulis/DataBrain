"""DataEngine: 多表数据引擎 —— SQLite 磁盘存储（非内存）"""

import os
import pandas as pd
import sqlite3
import re
import threading
from typing import Any
from contextlib import contextmanager

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(_DATA_DIR, exist_ok=True)
_DB_PATH = os.path.join(_DATA_DIR, "engine.db")

# 连接级 PRAGMA：WAL 允许读写并发；busy_timeout 避免上传线程与查询线程互锁
_BUSY_TIMEOUT_MS = 8000
_CONNECT_TIMEOUT_S = 10.0
_pragma_applied: set[str] = set()
_pragma_lock = threading.Lock()


def _configure_sqlite_conn(conn: sqlite3.Connection, db_path: str | None = None) -> None:
    """统一 SQLite 连接参数（WAL + busy_timeout + NORMAL sync）"""
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    # journal_mode 是持久属性，每个库设一次即可；重复执行无害
    key = db_path or str(id(conn))
    with _pragma_lock:
        if key not in _pragma_applied:
            try:
                mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()
                if mode and str(mode[0]).lower() == "wal":
                    _pragma_applied.add(key)
            except sqlite3.Error:
                # 只读介质或网络盘可能拒绝 WAL，busy_timeout 仍然生效
                pass


def connect_engine_db(db_path: str | None = None) -> sqlite3.Connection:
    """打开 engine.db 并应用并发安全 PRAGMA"""
    path = db_path or _DB_PATH
    conn = sqlite3.connect(path, timeout=_CONNECT_TIMEOUT_S, check_same_thread=False)
    _configure_sqlite_conn(conn, path)
    return conn


@contextmanager
def engine_connection(db_path: str | None = None):
    """上下文管理：自动 commit/rollback/close"""
    conn = connect_engine_db(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


class DataEngine:
    """多表数据引擎 —— 数据存储在 SQLite 文件中，不占用内存"""

    def __init__(self):
        self._db_connector = None
        # _meta 表在 _get_conn 中自动创建

    def _ensure_db_dir(self):
        """确保 data/ 目录存在"""
        os.makedirs(_DATA_DIR, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        self._ensure_db_dir()
        conn = connect_engine_db(_DB_PATH)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _meta ("
            "name TEXT PRIMARY KEY, rows INTEGER, columns INTEGER, "
            "source_type TEXT DEFAULT 'unknown', source_detail TEXT DEFAULT '')"
        )
        return conn

    @contextmanager
    def connection(self):
        """业务代码优先用该上下文，自动提交/回滚/关闭"""
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def set_db_connector(self, connector):
        self._db_connector = connector

    def get_db_connector(self):
        return self._db_connector

    def clear_db_connector(self):
        self._db_connector = None

    # ----------------------------------------------------------------
    # 表注册（写入 SQLite 文件）
    # ----------------------------------------------------------------
    def add_table(self, name: str, df: pd.DataFrame, source_info: dict | None = None) -> str:
        clean_name = self._clean_name(name)
        with self.connection() as conn:
            # 重名处理
            existing = conn.execute("SELECT name FROM _meta WHERE name=?", (clean_name,)).fetchone()
            if existing:
                i = 1
                while conn.execute("SELECT name FROM _meta WHERE name=?", (f"{clean_name}_{i}",)).fetchone():
                    i += 1
                clean_name = f"{clean_name}_{i}"
            # 写入 SQLite
            df.to_sql(clean_name, conn, index=False, if_exists="replace")
            # 写入元数据
            info = source_info or {"type": "unknown"}
            conn.execute(
                "INSERT OR REPLACE INTO _meta (name, rows, columns, source_type, source_detail) VALUES (?,?,?,?,?)",
                (clean_name, len(df), len(df.columns),
                 info.get("type", "unknown"),
                 info.get("file_name", info.get("db_table", "")))
            )
        return clean_name

    def remove_table(self, name: str):
        with self.connection() as conn:
            conn.execute('DROP TABLE IF EXISTS "%s"' % name.replace('"', '""'))
            conn.execute("DELETE FROM _meta WHERE name=?", (name,))

    def clear(self):
        with self.connection() as conn:
            tables = conn.execute("SELECT name FROM _meta").fetchall()
            for (tname,) in tables:
                conn.execute('DROP TABLE IF EXISTS "%s"' % tname.replace('"', '""'))
            conn.execute("DELETE FROM _meta")

    # ----------------------------------------------------------------
    # 属性（从 SQLite 读取）
    # ----------------------------------------------------------------
    @property
    def db_connector(self):
        return self._db_connector

    @property
    def table_names(self) -> list[str]:
        with self.connection() as conn:
            rows = conn.execute("SELECT name FROM _meta ORDER BY name").fetchall()
            return [r[0] for r in rows]

    @property
    def table_count(self) -> int:
        with self.connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM _meta").fetchone()
            return row[0] if row else 0

    @property
    def total_rows(self) -> int:
        with self.connection() as conn:
            row = conn.execute("SELECT COALESCE(SUM(rows), 0) FROM _meta").fetchone()
            return row[0] if row else 0

    def get_df(self, name: str, max_rows: int = 1000) -> pd.DataFrame | None:
        """从 SQLite 读取表数据（默认最多 1000 行，避免内存暴涨）"""
        with self.connection() as conn:
            try:
                meta = conn.execute("SELECT name FROM _meta WHERE name=?", (name,)).fetchone()
                if not meta:
                    return None
                df = pd.read_sql(
                    'SELECT * FROM "%s" LIMIT %d' % (name.replace('"', '""'), max_rows),
                    conn,
                )
                return df
            except Exception:
                return None

    def get_all_dfs(self) -> dict[str, pd.DataFrame]:
        result = {}
        for name in self.table_names:
            df = self.get_df(name)
            if df is not None:
                result[name] = df
        return result

    def has_table(self, name: str) -> bool:
        with self.connection() as conn:
            return conn.execute("SELECT 1 FROM _meta WHERE name=?", (name,)).fetchone() is not None

    def get_source_info(self, name: str) -> dict:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT source_type, source_detail FROM _meta WHERE name=?", (name,)
            ).fetchone()
            if row:
                return {
                    "type": row[0],
                    "file_name": row[1] if row[0] == "file" else "",
                    "db_table": row[1] if row[0] == "db" else "",
                }
            return {"type": "unknown"}

    def summary(self) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT name, rows, columns, source_type, source_detail FROM _meta ORDER BY name"
            ).fetchall()
            return [
                {"name": r[0], "rows": r[1], "columns": r[2],
                 "source_type": r[3], "source_detail": r[4]}
                for r in rows
            ]

    def journal_mode(self) -> str:
        """当前数据库 journal 模式（诊断用）"""
        with self.connection() as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            return str(row[0]) if row else ""

    def table_row_count(self, name: str) -> int:
        """表真实行数（从 _meta，避免 COUNT(*) 全表扫描）"""
        with self.connection() as conn:
            row = conn.execute("SELECT rows FROM _meta WHERE name=?", (name,)).fetchone()
            return int(row[0]) if row else -1

    def _quote_ident(self, name: str) -> str:
        return '"%s"' % str(name).replace('"', '""')

    def sql_describe(self, table: str, columns: list[str] | None = None) -> pd.DataFrame | None:
        """SQL 聚合描述统计，避免拉全表进 pandas"""
        t = self._quote_ident(table)
        with self.connection() as conn:
            info = conn.execute(f"PRAGMA table_info({t})").fetchall()
            if not info:
                return None
            all_cols = [r[1] for r in info]
            numeric = []
            for r in info:
                ctype = (r[2] or "").upper()
                if any(k in ctype for k in ("INT", "REAL", "FLOA", "DOUB", "NUM", "DEC")):
                    numeric.append(r[1])
            if columns:
                numeric = [c for c in numeric if c in columns]
            if not numeric:
                return None
            parts = ["COUNT(*) AS _n"]
            for c in numeric:
                q = self._quote_ident(c)
                parts += [
                    f"AVG({q}) AS \"{c}_avg\"",
                    f"MIN({q}) AS \"{c}_min\"",
                    f"MAX({q}) AS \"{c}_max\"",
                    f"SUM({q}) AS \"{c}_sum\"",
                ]
            sql = f"SELECT {', '.join(parts)} FROM {t}"
            return pd.read_sql_query(sql, conn)

    def sql_monthly_series(
        self, table: str, date_col: str, value_col: str, agg: str = "SUM"
    ) -> pd.DataFrame | None:
        """按月 SQL 聚合时序，返回 billing_month / value 两列"""
        t = self._quote_ident(table)
        d = self._quote_ident(date_col)
        v = self._quote_ident(value_col)
        agg = agg.upper()
        if agg not in ("SUM", "AVG", "MIN", "MAX", "COUNT"):
            agg = "SUM"
        with self.connection() as conn:
            # SQLite: 尝试 date()/substr 解析
            sql = f'''
                SELECT
                    substr(CAST({d} AS TEXT), 1, 7) AS period,
                    {agg}(CAST({v} AS REAL)) AS value,
                    COUNT(*) AS n
                FROM {t}
                WHERE {d} IS NOT NULL AND {v} IS NOT NULL
                GROUP BY period
                ORDER BY period
            '''
            try:
                df = pd.read_sql_query(sql, conn)
            except Exception:
                return None
            if df is None or df.empty:
                return None
            # 列名统一，便于 forecast/trend 消费
            df = df.rename(columns={"period": date_col, "value": value_col})
            return df[[date_col, value_col]]

    # ----------------------------------------------------------------
    # 其他
    # ----------------------------------------------------------------
    def register_all_to_sqlite(self, conn) -> list[str]:
        """已存储在 SQLite 中，直接返回表名"""
        return self.table_names[:]

    def schema_text_for_llm(self, profiler) -> str:
        """从 SQLite 读取 schema 信息（不加载全部数据）"""
        from memory.data_profiler import DataProfiler
        if not isinstance(profiler, DataProfiler):
            profiler = DataProfiler()

        lines = [f"系统共加载 {self.table_count} 张数据表，总计 {self.total_rows} 行。\n"]
        for name in self.table_names:
            df = self.get_df(name)
            if df is not None:
                profile = profiler.analyze_dataframe(df)
                lines.append(f"─── 表: {name}（{len(df)} 行 × {len(df.columns)} 列）───")
                lines.append(profiler.schema_text(profile))
                lines.append("")
        return "\n".join(lines)

    def all_suggested_questions(self, profiler) -> list[str]:
        from memory.data_profiler import DataProfiler
        if not isinstance(profiler, DataProfiler):
            profiler = DataProfiler()
        questions = []
        for name in self.table_names:
            df = self.get_df(name)
            if df is not None:
                profile = profiler.analyze_dataframe(df)
                for q in profile.get("suggested_questions", []):
                    tagged = f"[{name}] {q}"
                    if tagged not in questions:
                        questions.append(tagged)
        return questions[:6]

    @staticmethod
    def _clean_name(name: str) -> str:
        name = name.rsplit(".", 1)[0] if "." in name else name
        name = re.sub(r"[^a-zA-Z0-9_一-鿿]", "_", name)
        name = re.sub(r"_+", "_", name).strip("_")
        return name if name else "table"

    @staticmethod
    def _num_rows(path: str) -> int:
        """快速取文件行数（用于预览）"""
        import csv
        try:
            with open(path, encoding="utf-8") as f:
                return sum(1 for _ in csv.reader(f)) - 1
        except Exception:
            return -1
