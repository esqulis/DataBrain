"""DBConnector: 多数据库连接管理（MySQL / MariaDB / PostgreSQL / SQLite）"""

import sqlite3
from typing import Any

try:
    import pymysql

    HAS_MYSQL = True
except ImportError:
    HAS_MYSQL = False

try:
    import psycopg2

    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False


class DBConnector:
    """数据库连接管理器 —— 统一接口封装"""

    def __init__(self):
        self._conn = None
        self._db_type: str | None = None
        self._config: dict = {}

    # ----------------------------------------------------------------
    # 连接管理
    # ----------------------------------------------------------------
    def connect(
        self,
        db_type: str,
        host: str = "localhost",
        port: int | None = None,
        user: str = "",
        password: str = "",
        database: str = "",
        **kwargs,
    ) -> bool:
        """连接到数据库。db_type: mysql / postgresql / sqlite"""
        self.disconnect()
        self._db_type = db_type
        self._config = {
            "db_type": db_type,
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            **kwargs,
        }

        try:
            if db_type in ("mysql", "mariadb"):
                if not HAS_MYSQL:
                    raise ImportError("pymysql 未安装，请执行 pip install pymysql")
                port = port or 3306
                self._conn = pymysql.connect(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    database=database,
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor,
                    **kwargs,
                )

            elif db_type == "postgresql":
                if not HAS_POSTGRES:
                    raise ImportError("psycopg2 未安装，请执行 pip install psycopg2-binary")
                port = port or 5432
                self._conn = psycopg2.connect(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    dbname=database,
                    **kwargs,
                )

            elif db_type == "sqlite":
                path = kwargs.get("path") or database
                self._conn = sqlite3.connect(path)
                self._conn.row_factory = sqlite3.Row

            else:
                raise ValueError(f"不支持的数据库类型: {db_type}")

            return True

        except Exception as e:
            self._conn = None
            raise e

    def disconnect(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
        self._db_type = None
        self._config = {}

    @property
    def is_connected(self) -> bool:
        if not self._conn:
            return False
        try:
            self._conn.cursor().execute("SELECT 1")
            return True
        except Exception:
            return False

    @property
    def db_type(self) -> str | None:
        return self._db_type

    @property
    def config(self) -> dict:
        return dict(self._config)

    # ----------------------------------------------------------------
    # schema 探查
    # ----------------------------------------------------------------
    def get_tables(self) -> list[dict]:
        """列出所有表（名称 + 注释）"""
        if not self._conn:
            return []

        try:
            if self._db_type in ("mysql", "mariadb"):
                db = self._config.get("database", "")
                cur = self._execute(
                    "SELECT TABLE_NAME AS name, TABLE_COMMENT AS comment "
                    "FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
                    "ORDER BY TABLE_NAME",
                    params=[db],
                )
                return cur

            elif self._db_type == "postgresql":
                cur = self._execute(
                    "SELECT tablename AS name, obj_description(c.oid) AS comment "
                    "FROM pg_tables t "
                    "LEFT JOIN pg_class c ON c.relname = t.tablename "
                    "WHERE schemaname = 'public' ORDER BY tablename"
                )
                return cur

            elif self._db_type == "sqlite":
                cur = self._execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                return [{"name": r["name"], "comment": ""} for r in cur]

        except Exception as e:
            return [{"error": str(e)}]

        return []

    def get_table_schema(self, table_name: str) -> list[dict]:
        """获取表结构的列信息"""
        if not self._conn:
            return []

        try:
            if self._db_type in ("mysql", "mariadb"):
                db = self._config.get("database", "")
                return self._execute(
                    "SELECT COLUMN_NAME AS name, DATA_TYPE AS dtype, "
                    "IFNULL(CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION) AS length, "
                    "IF(IS_NULLABLE='YES', 1, 0) AS nullable, "
                    "IFNULL(COLUMN_DEFAULT, '') AS default_val, "
                    "IF(COLUMN_KEY='PRI', 1, 0) AS is_pk, "
                    "COLUMN_COMMENT AS comment "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                    "ORDER BY ORDINAL_POSITION",
                    params=[db, table_name],
                )

            elif self._db_type == "postgresql":
                return self._execute(
                    "SELECT column_name AS name, data_type AS dtype, "
                    "COALESCE(character_maximum_length, numeric_precision::text) AS length, "
                    "CASE WHEN is_nullable='YES' THEN 1 ELSE 0 END AS nullable, "
                    "COALESCE(column_default, '') AS default_val, "
                    "COALESCE((SELECT 1 FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu USING(constraint_name) "
                    "WHERE tc.table_name = %s AND kcu.column_name = c.column_name "
                    "AND tc.constraint_type = 'PRIMARY KEY'), 0) AS is_pk, "
                    "'' AS comment "
                    "FROM information_schema.columns c "
                    "WHERE table_name = %s ORDER BY ordinal_position",
                    params=[table_name, table_name],
                )

            elif self._db_type == "sqlite":
                cur = self._execute(f"PRAGMA table_info(\"{table_name}\")")
                return [
                    {
                        "name": r.get("name", ""),
                        "dtype": r.get("type", ""),
                        "nullable": 1 - r.get("notnull", 0),
                        "is_pk": r.get("pk", 0),
                    }
                    for r in cur
                ]

        except Exception as e:
            return [{"error": str(e)}]

        return []

    def get_databases(self) -> list[str]:
        """列出 MySQL 服务器上所有可用的数据库名"""
        if not self._conn:
            return []
        try:
            if self._db_type in ("mysql", "mariadb"):
                cur = self._execute("SHOW DATABASES")
                return [list(r.values())[0] for r in cur if list(r.values())[0] not in ("information_schema", "performance_schema", "mysql", "sys")]
            return [self._config.get("database", "")]
        except Exception:
            return []

    def get_row_count(self, table_name: str) -> int:
        """快速获取表行数"""
        try:
            result = self._execute(f'SELECT COUNT(*) AS cnt FROM "{table_name}"')
            if result:
                return int(result[0]["cnt"])
        except Exception:
            try:
                result = self._execute(f"SELECT COUNT(*) AS cnt FROM {table_name}")
                if result:
                    return int(result[0]["cnt"])
            except Exception:
                pass
        return -1

    # ----------------------------------------------------------------
    # 数据查询
    # ----------------------------------------------------------------
    def execute(self, sql: str, limit: int = 200) -> dict:
        """执行 SQL 查询，返回统一格式的 dict"""
        try:
            rows = self._execute(sql)
            if not rows:
                return {"success": True, "columns": [], "rows": [], "row_count": 0, "sql": sql}

            columns = list(rows[0].keys()) if rows else []
            data = []
            for r in rows[:limit]:
                data.append([self._safe(v) for v in r.values()])

            return {
                "success": True,
                "columns": columns,
                "rows": data,
                "row_count": len(rows),
                "sql": sql,
            }

        except Exception as e:
            return {"success": False, "error": str(e), "columns": [], "rows": [], "row_count": 0, "sql": sql}

    def _execute(self, sql: str, params: list | None = None) -> list[dict]:
        """底层执行，返回 list[dict]"""
        if not self._conn:
            raise ConnectionError("数据库未连接")

        cur = self._conn.cursor()

        if self._db_type == "postgresql":
            cur.execute(sql, params or [])
        elif self._db_type == "sqlite":
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
        else:
            cur.execute(sql, params or [])

        result = cur.fetchall()
        cur.close()

        if self._db_type == "sqlite":
            return [dict(r) for r in result]

        return list(result)

    # ----------------------------------------------------------------
    # 加载为 DataFrame
    # ----------------------------------------------------------------
    def to_dataframe(self, table_or_sql: str) -> "pd.DataFrame":
        """将表或查询结果转为 pandas DataFrame"""
        import pandas as pd

        if self._db_type in ("mysql", "mariadb"):
            import pymysql

            conn = pymysql.connect(
                host=self._config["host"],
                port=self._config.get("port", 3306),
                user=self._config["user"],
                password=self._config["password"],
                database=self._config["database"],
                charset="utf8mb4",
            )
            df = pd.read_sql(
                f"SELECT * FROM {table_or_sql} LIMIT 100000" if not table_or_sql.strip().upper().startswith("SELECT")
                else table_or_sql,
                conn,
            )
            conn.close()
            return df

        elif self._db_type == "postgresql":
            import psycopg2

            conn = psycopg2.connect(
                host=self._config["host"],
                port=self._config.get("port", 5432),
                user=self._config["user"],
                password=self._config["password"],
                dbname=self._config["database"],
            )
            df = pd.read_sql(
                f"SELECT * FROM {table_or_sql} LIMIT 100000" if not table_or_sql.strip().upper().startswith("SELECT")
                else table_or_sql,
                conn,
            )
            conn.close()
            return df

        else:
            return pd.read_sql(
                f"SELECT * FROM \"{table_or_sql}\" LIMIT 100000" if not table_or_sql.strip().upper().startswith("SELECT")
                else table_or_sql,
                self._conn,
            )

    # ----------------------------------------------------------------
    # 测试连接
    # ----------------------------------------------------------------
    def test_connection(
        self,
        db_type: str,
        host: str = "localhost",
        port: int | None = None,
        user: str = "",
        password: str = "",
        database: str = "",
        **kwargs,
    ) -> tuple[bool, str]:
        """测试数据库连接是否可用"""
        saved_conn = self._conn
        saved_type = self._db_type
        saved_cfg = self._config

        try:
            self.connect(db_type, host, port, user, password, database, **kwargs)
            self.disconnect()
            self._conn = saved_conn
            self._db_type = saved_type
            self._config = saved_cfg
            return True, "连接成功"
        except Exception as e:
            self._conn = saved_conn
            self._db_type = saved_type
            self._config = saved_cfg
            return False, str(e)

    # ----------------------------------------------------------------
    # 辅助
    # ----------------------------------------------------------------
    @staticmethod
    def _safe(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return v
        return str(v)
