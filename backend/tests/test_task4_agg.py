# -*- coding: utf-8 -*-
"""Task4 回归：query 强制 LIMIT + 大表 SQL 聚合"""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import memory.data_engine as de
tmpdir = tempfile.mkdtemp(prefix="enginetest4_")
de._DB_PATH = os.path.join(tmpdir, "engine.db")
de._DATA_DIR = tmpdir
de._pragma_applied.clear()

import pandas as pd
from memory.data_engine import DataEngine
from tools.query import QueryTool, enforce_limit

errors = []

# --- enforce_limit 单元 ---
cases = [
    ("SELECT * FROM t", True),
    ("SELECT * FROM t LIMIT 5", False),
    ("SELECT * FROM t limit 10;", False),
    ("SELECT COUNT(*) FROM t", True),
    ("SELECT a FROM t WHERE a IN (SELECT b FROM u LIMIT 3)", False),
]
for sql, expect_wrap in cases:
    out = enforce_limit(sql)
    wrapped = "_q_limited" in out
    if wrapped != expect_wrap:
        errors.append(f"enforce_limit({sql!r}) -> {out!r} wrap={wrapped} expect {expect_wrap}")
    else:
        print("OK limit", sql[:40], "->", "WRAPPED" if wrapped else "KEEP")

# --- 大表 SQL 月度聚合 ---
eng = DataEngine()
# 8000 行客户级明细，12 个月
rows = []
for m in range(1, 13):
    for i in range(700):
        rows.append({
            "customer_id": f"c{i}",
            "billing_month": f"2024-{m:02d}-15",
            "amount": 10 + (i % 20) + m,
        })
big = pd.DataFrame(rows)
eng.add_table("bills_big", big, {"type": "file"})
n = eng.table_row_count("bills_big")
if n != len(big):
    errors.append(f"row_count={n} expect {len(big)}")
else:
    print("OK row_count", n)

agg = eng.sql_monthly_series("bills_big", "billing_month", "amount")
if agg is None or len(agg) != 12:
    errors.append(f"sql_monthly_series len={None if agg is None else len(agg)}")
else:
    print("OK monthly series", len(agg), "first", agg.iloc[0].to_dict())

desc = eng.sql_describe("bills_big", ["amount"])
if desc is None or "amount_avg" not in desc.columns:
    errors.append(f"sql_describe cols={None if desc is None else list(desc.columns)}")
else:
    print("OK sql_describe avg=", float(desc["amount_avg"].iloc[0]))

# --- QueryTool 强制 LIMIT ---
# 指向测试库
import tools.query as qmod
qmod.ENGINE_DB = de._DB_PATH
# 重新 import helper 绑定
from tools.query import QueryTool
qt = QueryTool()
qt.set_data_engine(eng)
r = qt.execute(None, "SELECT * FROM bills_big")
if not r.get("success"):
    errors.append(f"select all fail: {r.get('error')}")
else:
    # 强制 LIMIT 1000，返回 row_count 应 <= 1000（不是 8000）
    if r["row_count"] > 1000:
        errors.append(f"LIMIT 未生效 row_count={r['row_count']}")
    else:
        print("OK LIMIT cap row_count=", r["row_count"], "exec=", (r.get("sql_executed") or "")[:60])

r2 = qt.execute(None, "SELECT COUNT(*) AS c FROM bills_big")
if not r2.get("success"):
    errors.append(f"count fail: {r2.get('error')}")
elif r2["rows"][0][0] != len(big):
    errors.append(f"count={r2['rows']} expect {len(big)}")
else:
    print("OK count still accurate", r2["rows"][0][0])

# --- registry 大表 forecast 走 SQL 聚合 ---
from agent.registry import ToolRegistry
reg = ToolRegistry()
reg.set_data_engine(eng)
res = reg.execute("analyze", {
    "action": "forecast",
    "columns": ["amount"],
    "table": "bills_big",
    "params": {"date_col": "billing_month", "target_col": "amount", "periods": 6},
})
if not res.get("success") and res.get("error"):
    errors.append(f"registry forecast error: {res.get('error')}")
elif res.get("action") != "forecast":
    errors.append(f"registry forecast action={res.get('action')} keys={list(res)[:8]}")
else:
    rows = (res.get("results") or {}).get("rows") or []
    if len(rows) != 6:
        errors.append(f"forecast periods={len(rows)}")
    else:
        print("OK registry forecast via SQL agg", rows[0], "->", rows[-1])
        print("   insight:", res.get("insight"))

print("---")
if errors:
    print("FAIL", len(errors))
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("ALL PASS")
