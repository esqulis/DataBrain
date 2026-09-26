"""数据查询 / 分析 / 可视化 API"""

from __future__ import annotations
import os
import uuid
import threading
import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from shared_state import get_state
from tools.report import _clean_inf

router = APIRouter(tags=["data"])

# ── 上传进度追踪 ──
_upload_progress: dict[str, dict] = {}
_upload_lock = threading.Lock()

# ── 异步对话任务 ──
_chat_tasks: dict[str, dict] = {}
_chat_lock = threading.Lock()
_CHAT_TASK_TTL = 30 * 60  # 保留 30 分钟


def _set_task_progress(task_id: str, progress: int, message: str, status: str = "processing"):
    """线程安全地更新任务进度"""
    with _upload_lock:
        _upload_progress[task_id] = {"progress": progress, "message": message, "status": status}


def _set_chat_task(task_id: str, **fields):
    with _chat_lock:
        cur = _chat_tasks.get(task_id) or {
            "status": "queued", "progress": 0, "message": "排队中…",
            "response": None, "sql": None, "charts": [], "has_charts": False, "error": None,
        }
        cur.update(fields)
        _chat_tasks[task_id] = cur


def _cleanup_chat_tasks():
    import time
    now = time.time()
    with _chat_lock:
        dead = [k for k, v in _chat_tasks.items()
                if v.get("finished_at") and now - v["finished_at"] > _CHAT_TASK_TTL]
        for k in dead:
            _chat_tasks.pop(k, None)


def _run_chat(task_id: str, message: str):
    """后台执行 Agent 对话，完成后写入结果"""
    try:
        _set_chat_task(task_id, status="processing", progress=5, message="分析中…")
        state = get_state()
        agent, brain = _get_agent(state)
        if not brain or not agent:
            _set_chat_task(
                task_id, status="error", progress=0,
                error="未配置大脑，请先在界面中添加并切换大脑。",
                message="未配置大脑",
            )
            return

        _set_chat_task(task_id, progress=20, message="Agent 工具循环中…")
        result = agent.process_query(message)
        resp_text = result.get("response", "") or ""
        resp_text = resp_text.encode("utf-8", errors="replace").decode("utf-8")
        charts = result.get("charts") or []
        import time
        _set_chat_task(
            task_id,
            status="done",
            progress=100,
            message="完成",
            response=resp_text,
            sql=result.get("sql"),
            charts=charts,
            has_charts=len(charts) > 0,
            finished_at=time.time(),
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        import time
        _set_chat_task(
            task_id,
            status="error",
            progress=0,
            error=f"分析过程出错: {str(e)}",
            message=f"❌ {str(e)[:80]}",
            finished_at=time.time(),
        )


def _run_upload(task_id: str, file_path: str, filename: str):
    """后台线程处理上传"""
    try:
        state = get_state()
        engine = state.data_engine

        ext = os.path.splitext(filename)[1].lower()
        _set_task_progress(task_id, 5, "解析文件…")
        import pandas as pd

        if ext == ".csv":
            from memory.csv_adapter import read_csv_kwargs, ingest_csv_to_sqlite

            with engine.connection() as conn:
                clean_name = engine._clean_name(filename)
                existing = conn.execute("SELECT name FROM _meta WHERE name=?", (clean_name,)).fetchone()
                if existing:
                    i = 1
                    while conn.execute("SELECT name FROM _meta WHERE name=?", (f"{clean_name}_{i}",)).fetchone():
                        i += 1
                    clean_name = f"{clean_name}_{i}"

                kwargs = read_csv_kwargs(file_path)
                _set_task_progress(
                    task_id, 6,
                    f"识别编码={kwargs['encoding']} 分隔符={kwargs['sep']!r}…",
                )

                def _cb(pct: int, msg: str, _tid=task_id):
                    _set_task_progress(_tid, pct, msg)

                processed = ingest_csv_to_sqlite(
                    file_path, clean_name, conn,
                    progress_cb=_cb, chunksize=5000,
                    original_name=filename,
                )
            _set_task_progress(
                task_id, 100,
                f"✅ {filename} 完成 ({processed} 行, 编码 {kwargs['encoding']})",
                "done",
            )

        elif ext in (".xlsx", ".xls"):
            from openpyxl import load_workbook
            wb = load_workbook(file_path, read_only=True, data_only=True)
            ws = wb.active
            headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
            rows = []
            for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 1):
                rows.append(row)
                if i % 5000 == 0:
                    _set_task_progress(task_id, min(90, i // 500), f"读取 Excel… {i} 行")
                if len(rows) >= 50000:
                    break
            wb.close()
            _set_task_progress(task_id, 95, "写入 SQLite…")
            df = pd.DataFrame(rows, columns=headers)
            engine.add_table(filename, df, {"type": "file", "file_name": filename})
            _set_task_progress(task_id, 100, f"✅ {filename} 完成 ({len(rows)} 行)", "done")

        elif ext in (".md", ".mdx", ".txt"):
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            import re
            paragraphs = re.split(r"\n\s*\n", content)
            _set_task_progress(task_id, 90, "写入 SQLite…")
            df = pd.DataFrame({"content": paragraphs, "line_count": [len(p.split("\n")) for p in paragraphs]})
            engine.add_table(filename, df, {"type": "file", "file_name": filename})
            _set_task_progress(task_id, 100, f"✅ {filename} 完成 ({len(paragraphs)} 段)", "done")

        else:
            _set_task_progress(task_id, 0, f"不支持的文件格式: {ext}", "error")

    except Exception as e:
        _set_task_progress(task_id, 0, f"❌ 处理失败: {str(e)[:100]}", "error")

    finally:
        if os.path.exists(file_path):
            os.unlink(file_path)


# ── Schema ─────────────────────────────────────────
class QueryRequest(BaseModel):
    sql: str
    natural_query: str = ""


class AnalyzeRequest(BaseModel):
    action: str  # describe / correlation / groupby / trend / distribution / outlier / forecast
    columns: list[str] = []
    params: dict = {}
    table: str = ""  # 指定表名；空则用第一张表


class VisualizeRequest(BaseModel):
    data_description: str
    chart_type: str = "auto"
    title: str = "图表"
    table: str = ""  # 指定表名；空则用第一张表


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    sql: str | None = None
    charts: list[dict] | None = None
    has_charts: bool = False


class DbConnectRequest(BaseModel):
    db_type: str = "mysql"
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = ""
    sqlite_path: str = ""
    extra_params: dict = {}


# ── 端点 ───────────────────────────────────────────
@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传文件（后台处理，返回 task_id 用于轮询进度）"""
    state = get_state()
    engine = state.data_engine
    engine._ensure_db_dir()

    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1])
    content = await file.read()
    tmp.write(content)
    tmp.close()

    task_id = str(uuid.uuid4())[:12]
    _set_task_progress(task_id, 0, "排队中…")

    t = threading.Thread(target=_run_upload, args=(task_id, tmp.name, file.filename), daemon=True)
    t.start()

    return {"success": True, "task_id": task_id, "message": f"开始处理 {file.filename}"}


@router.get("/upload/status/{task_id}")
def upload_status(task_id: str):
    """查询上传处理进度"""
    with _upload_lock:
        status = _upload_progress.get(task_id)
    if not status:
        return {"progress": 0, "message": "未知任务", "status": "unknown"}
    return status


# ── 旧式同步上传（兼容小文件/瞬时完成场景） ──


@router.post("/load-sample")
def load_sample_data():
    """加载示例销售数据"""
    state = get_state()
    engine = state.data_engine

    sample_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sample_sales.csv")
    if not os.path.exists(sample_path):
        sample_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "sample_sales.csv")

    if os.path.exists(sample_path):
        df = pd.read_csv(sample_path)
        df.columns = [str(c) for c in df.columns]
        engine.clear()
        engine.add_table("sample_sales", df, {"type": "sample", "file_name": "sample_sales.csv"})
        return {"success": True, "table": "sample_sales", "rows": len(df), "columns": len(df.columns)}
    raise HTTPException(status_code=404, detail="示例数据文件未找到")


@router.post("/db/test")
def test_db_connection(req: DbConnectRequest):
    """测试数据库连接"""
    from memory.db_connector import DBConnector
    connector = DBConnector()
    try:
        if req.db_type == "sqlite":
            ok, msg = connector.test_connection(db_type="sqlite", path=req.sqlite_path, database=req.sqlite_path)
        else:
            ok, msg = connector.test_connection(
                db_type=req.db_type, host=req.host, port=req.port,
                user=req.user, password=req.password, database=req.database,
            )
        return {"success": ok, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/db/connect")
def connect_database(req: DbConnectRequest):
    """连接数据库。如果不指定数据库名，返回可用数据库列表"""
    from memory.db_connector import DBConnector
    state = get_state()
    engine = state.data_engine
    connector = DBConnector()

    try:
        if req.db_type == "sqlite":
            connector.connect(db_type="sqlite", path=req.sqlite_path, database=req.sqlite_path, **req.extra_params)
        else:
            connector.connect(
                db_type=req.db_type, host=req.host, port=req.port,
                user=req.user, password=req.password,
                database=req.database or "",
                **req.extra_params,
            )
        engine.set_db_connector(connector)

        # 没有指定数据库 → 返回可用列表
        if not req.database:
            databases = connector.get_databases()
            return {"success": True, "databases": databases, "message": "已连接到服务器，请选择数据库"}

        # 指定了数据库 → 加载表
        tables = connector.get_tables()
        loaded = 0
        for t in tables:
            tname = t.get("name", "")
            if tname:
                try:
                    df = connector.to_dataframe(tname)
                    if df is not None and not df.empty:
                        df.columns = [str(c) for c in df.columns]
                        engine.add_table(tname, df, {"type": "db", "db_table": tname, "db_type": req.db_type})
                        loaded += 1
                except Exception:
                    pass

        return {"success": True, "message": f"已连接 {req.database}，加载 {loaded}/{len(tables)} 张表", "tables_loaded": loaded}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/db/select")
def select_database(req: DbConnectRequest):
    """连接后选择数据库，重新加载该库的所有表"""
    from memory.db_connector import DBConnector
    state = get_state()
    engine = state.data_engine
    connector = DBConnector()

    if not req.database:
        raise HTTPException(status_code=400, detail="请指定数据库名")

    config = engine.db_connector.config if engine.db_connector else {}
    try:
        connector.connect(
            db_type=req.db_type or config.get("db_type", "mysql"),
            host=req.host or config.get("host", "localhost"),
            port=req.port or config.get("port", 3306),
            user=req.user or config.get("user", "root"),
            password=req.password or config.get("password", ""),
            database=req.database,
        )
        engine.set_db_connector(connector)

        tables = connector.get_tables()
        loaded = 0
        for t in tables:
            tname = t.get("name", "")
            if tname:
                try:
                    df = connector.to_dataframe(tname)
                    if df is not None and not df.empty:
                        df.columns = [str(c) for c in df.columns]
                        engine.add_table(tname, df, {"type": "db", "db_table": tname, "db_type": config.get("db_type", "mysql")})
                        loaded += 1
                except Exception:
                    pass

        return {"success": True, "message": f"已切换至 {req.database}，加载 {loaded}/{len(tables)} 张表"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/db/execute")
def execute_db_sql(req: dict):
    """对已连接的数据库执行任意 SQL（INSERT/UPDATE/DELETE/CREATE/DROP/ALTER）"""
    state = get_state()
    engine = state.data_engine
    connector = engine.db_connector
    if not connector or not connector.is_connected:
        raise HTTPException(400, detail="未连接数据库，请先通过数据库页面连接")

    sql = req.get("sql", "").strip()
    if not sql:
        raise HTTPException(400, detail="SQL 不能为空")
    sql_upper = sql.upper().strip()

    try:
        if sql_upper.startswith("SELECT") or sql_upper.startswith("SHOW") or sql_upper.startswith("DESC"):
            result = connector.execute(sql, limit=1000)
            return {"success": True, "type": "query", **result}
        else:
            cur = connector._execute(sql)
            affected = len(cur) if cur else 0
            # 如果是 DDL 刷新已加载的表缓存
            if any(k in sql_upper for k in ("CREATE TABLE", "DROP TABLE", "ALTER TABLE", "TRUNCATE")):
                engine._db_tables_cache = {}
            return {"success": True, "type": "execute", "affected_rows": affected, "message": "执行成功"}
    except Exception as e:
        return {"success": False, "error": str(e), "message": str(e)}


@router.get("/db/tables-server")
def list_server_tables():
    """列出已连接数据库中的所有表（实际 MySQL 表，非加载缓存）"""
    state = get_state()
    engine = state.data_engine
    connector = engine.db_connector
    if not connector or not connector.is_connected:
        raise HTTPException(400, detail="未连接数据库")
    try:
        tables = connector.get_tables()
        detail = []
        for t in tables:
            tname = t.get("name", "")
            try:
                schema = connector.get_table_schema(tname)
                row_count = connector.get_row_count(tname)
            except Exception:
                schema = []
                row_count = -1
            detail.append({"name": tname, "columns": len(schema), "rows": row_count, "schema": schema})
        return {"success": True, "tables": detail, "count": len(detail)}
    except Exception as e:
        raise HTTPException(400, detail=str(e))


def _get_db_connector(engine):
    """获取数据库连接器，带错误检查"""
    connector = engine.db_connector
    if not connector or not connector.is_connected:
        raise HTTPException(400, detail="未连接数据库")
    # 确保已选择数据库
    db_name = connector.config.get("database", "")
    if db_name:
        try:
            connector._execute("USE `%s`" % db_name)
        except Exception:
            pass
    return connector


@router.post("/db/drop-table")
def drop_server_table(req: dict):
    """删除已连接数据库中的指定表"""
    state = get_state()
    engine = state.data_engine
    connector = _get_db_connector(engine)
    table_name = req.get("table_name", "").strip()
    if not table_name:
        raise HTTPException(400, detail="表名不能为空")
    try:
        sql = f"DROP TABLE IF EXISTS `{table_name}`"
        connector._execute(sql)
        if table_name in engine.table_names:
            engine.remove_table(table_name)
        return {"success": True, "message": f"表「{table_name}」已删除"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/db/create-table")
def create_server_table(req: dict):
    """傻瓜式建表：传入表名和字段列表"""
    state = get_state()
    engine = state.data_engine
    connector = _get_db_connector(engine)
    table_name = req.get("table_name", "").strip()
    columns = req.get("columns", [])
    if not table_name:
        raise HTTPException(400, detail="表名不能为空")
    if not columns:
        raise HTTPException(400, detail="至少需要一个字段")
    try:
        cols_def = []
        for col in columns:
            name = col.get("name", "").strip()
            ctype = col.get("type", "VARCHAR(255)").strip()
            nullable = col.get("nullable", True)
            is_pk = col.get("primary_key", False)
            default_val = col.get("default", "")
            auto_inc = col.get("auto_increment", False)
            if not name or not ctype:
                continue
            parts = [f"`{name}` {ctype}"]
            if not nullable:
                parts.append("NOT NULL")
            if default_val:
                parts.append(f"DEFAULT {default_val}")
            if auto_inc:
                parts.append("AUTO_INCREMENT")
            if is_pk:
                parts.append("PRIMARY KEY")
            cols_def.append(" ".join(parts))
        if not cols_def:
            raise HTTPException(400, detail="无效的字段定义")
        sep = ",\n  "
        col_text = sep.join(cols_def)
        sql = "CREATE TABLE `%s` (\n  %s\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" % (table_name, col_text)
        connector._execute(sql)
        return {"success": True, "message": "表「%s」创建成功" % table_name, "sql": sql}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/db/insert-row")
def insert_db_row(req: dict):
    """傻瓜式插入数据：传入表名和字段值对"""
    state = get_state()
    engine = state.data_engine
    connector = _get_db_connector(engine)
    table_name = req.get("table_name", "").strip()
    data = req.get("data", {})
    if not table_name:
        raise HTTPException(400, detail="表名不能为空")
    if not data:
        raise HTTPException(400, detail="至少需要一个字段值")
    try:
        cols = ", ".join(f"`{k}`" for k in data.keys())
        placeholders = ", ".join("%s" for _ in data)
        sql = f"INSERT INTO `{table_name}` ({cols}) VALUES ({placeholders})"
        connector._execute(sql, list(data.values()))
        return {"success": True, "message": f"已插入 1 条记录到「{table_name}」"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/query")
def execute_query(req: QueryRequest):
    """对已加载的数据执行 SQL 查询"""
    state = get_state()
    engine = state.data_engine
    if engine.table_count == 0:
        raise HTTPException(status_code=400, detail="尚未加载数据，请先在界面上传数据。")

    from tools.query import QueryTool
    qt = QueryTool()
    qt.set_data_engine(engine)
    result = qt.execute(None, req.sql)
    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result.get("error", "查询失败"))
    # 清理 JSON 不兼容的 float
    return _clean_inf(result)


def _resolve_table(engine, table: str = "") -> str:
    """解析目标表名：优先用户指定，否则第一张表"""
    if table:
        # 允许前端传原始文件名，尝试清洗后匹配
        candidates = [table, engine._clean_name(table)]
        for name in engine.table_names:
            if name in candidates:
                return name
        # 宽松：忽略大小写
        lower_map = {n.lower(): n for n in engine.table_names}
        for c in candidates:
            if c.lower() in lower_map:
                return lower_map[c.lower()]
        raise HTTPException(status_code=404, detail=f"表 '{table}' 不存在，可用表: {engine.table_names}")
    if not engine.table_names:
        raise HTTPException(status_code=400, detail="没有可用数据表")
    return engine.table_names[0]


def _load_df_for_analysis(engine, table: str, action: str = ""):
    """按动作选择合适的行数上限"""
    max_rows = 10000 if action in ("forecast", "trend") else 1000
    name = _resolve_table(engine, table)
    df = engine.get_df(name, max_rows=max_rows)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"表 '{name}' 无数据")
    return name, df


@router.post("/analyze")
def execute_analyze(req: AnalyzeRequest):
    """对已加载的数据执行统计分析（可指定 table）"""
    state = get_state()
    engine = state.data_engine
    if engine.table_count == 0:
        raise HTTPException(status_code=400, detail="尚未加载数据")

    table_name, df = _load_df_for_analysis(engine, req.table, req.action)

    from tools.analyze import AnalyzeTool
    at = AnalyzeTool()
    params = dict(req.params or {})
    # 未显式指定日期/目标列时，用表名列兜底
    if req.action == "forecast":
        params.setdefault("date_col", params.get("date_col"))
        if req.columns:
            params.setdefault("target_col", req.columns[0])
    result = at.execute(
        df,
        action=req.action,
        columns=req.columns or list(df.columns),
        params=params,
    )
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    result["table"] = table_name
    result["row_sampled"] = len(df)
    return result


@router.post("/analyze/auto")
def auto_analyze(table_name: str = "", theme: str = "light"):
    """全自动数据分析 —— 使用 data_analyzer 引擎"""
    state = get_state()
    engine = state.data_engine
    if engine.table_count == 0:
        raise HTTPException(status_code=400, detail="尚未加载数据")

    target = table_name or (engine.table_names[0] if engine.table_names else "")
    if not target or target not in engine.table_names:
        raise HTTPException(status_code=404, detail=f"表 '{target}' 不存在")

    from data_analyzer.adapter import DataAnalyzerAdapter
    da = DataAnalyzerAdapter(engine)
    result = da.generate_and_save(target, theme=theme)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/report")
def generate_report(topic: str = "", table: str = ""):
    """生成决策分析报告"""
    from tools.report import ReportTool
    rt = ReportTool()
    result = rt.execute(topic=topic, table=table)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/visualize")
def execute_visualize(req: VisualizeRequest):
    """根据数据生成 ECharts 图表配置（可指定 table）"""
    state = get_state()
    from tools.visualize import VisualizeTool
    vt = VisualizeTool()

    engine = state.data_engine
    if engine.table_count == 0:
        raise HTTPException(status_code=400, detail="尚无数据")

    table_name, df = _load_df_for_analysis(engine, req.table)
    result = vt.execute(
        df,
        data_description=req.data_description,
        chart_type=req.chart_type,
        title=req.title,
    )
    if not result.get("chart_html") and not result.get("option"):
        raise HTTPException(status_code=422, detail="无法生成图表")
    result["table"] = table_name
    return result


@router.post("/tables/batch-add")
def batch_add_tables(data: dict):
    """批量添加多个表（JSON 格式）"""
    state = get_state()
    engine = state.data_engine
    added = []
    for tbl_name, records in data.items():
        if records:
            import pandas as pd
            df = pd.DataFrame(records)
            for c in df.columns:
                try: df[c] = pd.to_numeric(df[c], errors='ignore')
                except: pass
            engine.add_table(tbl_name, df, {"type": "batch"})
            added.append(tbl_name)
    return {"success": True, "tables_added": added}


@router.get("/tables")
def list_tables():
    """列出已加载的所有数据表"""
    state = get_state()
    engine = state.data_engine
    return {"tables": engine.summary(), "count": engine.table_count, "total_rows": engine.total_rows}


@router.delete("/tables/{table_name}")
def delete_table(table_name: str):
    """删除指定数据表"""
    state = get_state()
    engine = state.data_engine
    if table_name not in engine.table_names:
        raise HTTPException(status_code=404, detail=f"表 '{table_name}' 不存在")
    engine.remove_table(table_name)
    return {"success": True, "table": table_name, "remaining": engine.table_count}


@router.get("/tables/{table_name}/preview")
def preview_table(table_name: str, limit: int = 20):
    """预览指定表的前 N 行数据"""
    state = get_state()
    engine = state.data_engine
    if table_name not in engine.table_names:
        raise HTTPException(status_code=404, detail=f"表 '{table_name}' 不存在")
    df = engine.get_df(table_name)
    if df is None or df.empty:
        return {"columns": [], "rows": [], "total_rows": 0}
    rows = df.head(limit).values.tolist()
    rows = [[str(v) if v is not None else "" for v in row] for row in rows]
    return {"columns": list(df.columns), "rows": rows, "total_rows": len(df)}


# ── Agent 与会话管理 ─────────────────────────────
_agent_cache: dict[str, tuple] = {}  # brain_id → (AgentService, brain_id_hash)


def _get_agent(state) -> tuple:
    """获取当前大脑对应的 AgentService 实例（带缓存失效）"""
    cfg = state.brain_manager.get_current_config()
    brain = state.brain_manager.get_current_brain()
    if not cfg or not brain:
        return None, None

    key = f"{cfg.id}_{cfg.model}_{cfg.base_url}"
    cached = _agent_cache.get(key)
    if cached:
        return cached

    from agent.service import AgentService
    agent = AgentService(brain, state.data_engine)
    _agent_cache.clear()  # 只保留当前活跃的
    _agent_cache[key] = (agent, brain)
    return agent, brain


@router.post("/chat")
def chat(req: ChatRequest):
    """同步对话（兼容旧前端；长任务请改用 /chat/async）"""
    state = get_state()
    agent, brain = _get_agent(state)
    if not brain:
        raise HTTPException(status_code=400, detail="未配置大脑，请先在界面中添加并切换大脑。")

    try:
        result = agent.process_query(req.message)
        resp_text = result.get("response", "")
        # 清洗非法 Unicode 代理字符
        resp_text = resp_text.encode("utf-8", errors="replace").decode("utf-8")
        return ChatResponse(
            response=resp_text,
            sql=result.get("sql"),
            charts=result.get("charts", []),
            has_charts=len(result.get("charts", [])) > 0,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ChatResponse(
            response=f"❌ 分析过程出错: {str(e)}",
            sql=None,
        )


@router.post("/chat/async")
def chat_async(req: ChatRequest):
    """异步对话：立即返回 task_id，前端轮询 /chat/status/{task_id}"""
    _cleanup_chat_tasks()
    state = get_state()
    agent, brain = _get_agent(state)
    if not brain:
        raise HTTPException(status_code=400, detail="未配置大脑，请先在界面中添加并切换大脑。")

    task_id = str(uuid.uuid4())[:12]
    _set_chat_task(task_id, status="queued", progress=0, message="排队中…")
    t = threading.Thread(target=_run_chat, args=(task_id, req.message), daemon=True)
    t.start()
    return {"success": True, "task_id": task_id, "message": "已开始分析"}


@router.get("/chat/status/{task_id}")
def chat_status(task_id: str):
    """查询异步对话进度/结果"""
    _cleanup_chat_tasks()
    with _chat_lock:
        status = _chat_tasks.get(task_id)
    if not status:
        return {"status": "unknown", "progress": 0, "message": "未知任务"}
    # 返回副本，避免并发写
    return dict(status)


@router.post("/chat/clear")
def clear_chat():
    """清空当前 Agent 的对话历史"""
    state = get_state()
    agent, _ = _get_agent(state)
    if agent:
        agent.history.clear()
        agent._last_sql = None
        agent._pending_charts = []
        return {"success": True, "message": "对话历史已清空"}


@router.post("/knowledge")
def knowledge_query(req: dict):
    """从非结构化知识库检索信息"""
    from tools.knowledge import retrieve, get_stats
    stats = get_stats()  # 触发懒加载
    question_id = req.get("question_id")
    query = req.get("query", "")
    k = req.get("k", 3)
    results = retrieve(question_id=question_id, query=query, k=k)
    return {"results": results, "stats": stats}
