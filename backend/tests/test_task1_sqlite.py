# -*- coding: utf-8 -*-
"""Task1 回归：SQLite WAL + busy_timeout + 并发读写"""
import os
import sys
import threading
import time

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

# 使用临时库，避免污染生产 engine.db
import tempfile
from pathlib import Path

import pandas as pd

# 先 patch 路径再 import engine
import memory.data_engine as de

tmpdir = tempfile.mkdtemp(prefix="enginetest_")
test_db = os.path.join(tmpdir, "engine.db")
de._DB_PATH = test_db
de._DATA_DIR = tmpdir
de._pragma_applied.clear()

from memory.data_engine import DataEngine, connect_engine_db

errors = []

# --- 1) journal_mode 必须是 wal ---
eng = DataEngine()
mode = eng.journal_mode()
if mode.lower() != "wal":
    errors.append(f"journal_mode 期望 wal，实际 {mode!r}")
else:
    print("OK journal_mode =", mode)

# --- 2) busy_timeout 生效 ---
conn = connect_engine_db(test_db)
bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
if int(bt) < 1000:
    errors.append(f"busy_timeout 期望 >=1000，实际 {bt}")
else:
    print("OK busy_timeout =", bt)
conn.close()

# --- 3) 基本读写 ---
df = pd.DataFrame({"id": [1, 2, 3], "val": ["a", "b", "c"]})
name = eng.add_table("t1", df, {"type": "file", "file_name": "t1.csv"})
if name != "t1":
    errors.append(f"add_table 名称异常: {name}")
got = eng.get_df("t1")
if got is None or len(got) != 3:
    errors.append(f"get_df 异常: {got}")
else:
    print("OK add/get", got.shape)

# --- 4) 并发读写不应 database is locked ---
lock_errs = []
write_done = threading.Event()

def writer():
    try:
        for i in range(30):
            eng.add_table(f"w{i}", pd.DataFrame({"x": range(200)}), {"type": "file"})
            time.sleep(0.01)
    except Exception as e:
        lock_errs.append(f"writer: {type(e).__name__}: {e}")
    finally:
        write_done.set()

def reader():
    try:
        for _ in range(40):
            _ = eng.table_names
            _ = eng.get_df("t1")
            time.sleep(0.005)
    except Exception as e:
        lock_errs.append(f"reader: {type(e).__name__}: {e}")

tw = threading.Thread(target=writer)
tr = threading.Thread(target=reader)
tw.start(); tr.start()
tw.join(30); tr.join(30)
write_done.wait(5)

if lock_errs:
    errors.extend(lock_errs)
else:
    print("OK concurrent read/write no lock errors")

# --- 5) connection() 上下文自动提交 ---
with eng.connection() as c:
    c.execute("INSERT OR REPLACE INTO _meta (name, rows, columns, source_type, source_detail) VALUES ('ctx',1,1,'file','x')")
if not eng.has_table("ctx"):
    errors.append("connection() 上下文未自动提交")
else:
    print("OK context manager commit")

# --- 6) QueryTool 走同一连接配置 ---
from tools.query import QueryTool
# 重新指向测试库
import tools.query as qmod
qmod.ENGINE_DB = test_db
qt = QueryTool()
qt.set_data_engine(eng)
r = qt.execute(None, 'SELECT * FROM "t1"')
if not r.get("success"):
    errors.append(f"QueryTool 失败: {r.get('error')}")
elif r.get("row_count") != 3:
    errors.append(f"QueryTool 行数: {r.get('row_count')}")
else:
    print("OK QueryTool", r["row_count"], "rows")

print("---")
if errors:
    print("FAIL", len(errors))
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("ALL PASS")
