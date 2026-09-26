# -*- coding: utf-8 -*-
"""Task3 回归：CSV 编码/分隔符探测 + 上传入库"""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import memory.data_engine as de
tmpdir = tempfile.mkdtemp(prefix="enginetest3_")
de._DB_PATH = os.path.join(tmpdir, "engine.db")
de._DATA_DIR = tmpdir
de._pragma_applied.clear()

from memory.csv_adapter import (
    detect_encoding, detect_delimiter, read_csv_kwargs,
    ingest_csv_to_sqlite, count_csv_rows,
)
from memory.data_engine import DataEngine

errors = []
work = tempfile.mkdtemp(prefix="csvsamples_")

def write(name, data: bytes):
    p = os.path.join(work, name)
    with open(p, "wb") as f:
        f.write(data)
    return p

# --- UTF-8 逗号 ---
p_utf8 = write("utf8.csv", "订单ID,金额\n1,10\n2,20\n".encode("utf-8"))
enc = detect_encoding(p_utf8)
sep = detect_delimiter(p_utf8, enc)
if enc not in ("utf-8", "utf-8-sig"):
    errors.append(f"utf8 enc={enc}")
if sep != ",":
    errors.append(f"utf8 sep={sep!r}")
else:
    print("OK utf-8 comma", enc, repr(sep))

# --- UTF-8 BOM ---
p_bom = write("bom.csv", b"\xef\xbb\xbf" + "colA,colB\n1,2\n".encode("utf-8"))
enc = detect_encoding(p_bom)
if enc != "utf-8-sig":
    errors.append(f"bom enc={enc}")
else:
    print("OK utf-8-sig BOM")

# --- GBK ---
p_gbk = write("gbk.csv", "订单ID,金额\n1,100\n2,200\n".encode("gbk"))
enc = detect_encoding(p_gbk)
kw = read_csv_kwargs(p_gbk)
import pandas as pd
df = pd.read_csv(p_gbk, **{k: v for k, v in kw.items() if k != "chunksize"})
if enc not in ("gb18030", "gbk"):
    errors.append(f"gbk enc={enc}")
elif list(df.columns) != ["订单ID", "金额"] or len(df) != 2:
    errors.append(f"gbk df={df}")
else:
    print("OK gbk", enc, list(df.columns))

# --- 分号 ---
p_semi = write("semi.csv", "a;b;c\n1;2;3\n4;5;6\n".encode("utf-8"))
kw = read_csv_kwargs(p_semi)
df = pd.read_csv(p_semi, **{k: v for k, v in kw.items() if k != "chunksize"})
if kw["sep"] != ";":
    errors.append(f"semi sep={kw['sep']!r}")
elif df.shape != (2, 3):
    errors.append(f"semi shape={df.shape}")
else:
    print("OK semicolon", kw["sep"], df.shape)

# --- Tab ---
p_tab = write("tab.csv", "x\ty\n1\t2\n3\t4\n".encode("utf-8"))
kw = read_csv_kwargs(p_tab)
if kw["sep"] != "\t":
    errors.append(f"tab sep={kw['sep']!r}")
else:
    print("OK tab", repr(kw["sep"]))

# --- 字段内换行计数 ---
p_nl = write("nl.csv", b'id,note\n1,"line1\nline2"\n2,ok\n')
n = count_csv_rows(p_nl, read_csv_kwargs(p_nl))
if n != 2:
    errors.append(f"embedded newline count={n} expect 2")
else:
    print("OK embedded newline count=2")

# --- 入库 ---
eng = DataEngine()
with eng.connection() as conn:
    n = ingest_csv_to_sqlite(p_gbk, "gbk_table", conn, original_name="gbk.csv")
    n2 = ingest_csv_to_sqlite(p_semi, "semi_table", conn, original_name="semi.csv")
if n != 2 or n2 != 2:
    errors.append(f"ingest rows gbk={n} semi={n2}")
else:
    g = eng.get_df("gbk_table")
    s = eng.get_df("semi_table")
    if list(g.columns) != ["订单ID", "金额"] or len(g) != 2:
        errors.append(f"gbk_table {g}")
    elif list(s.columns) != ["a", "b", "c"]:
        errors.append(f"semi_table cols {list(s.columns)}")
    else:
        print("OK ingest", g.shape, s.shape)
        info = eng.get_source_info("gbk_table")
        if info.get("file_name") != "gbk.csv":
            errors.append(f"source_detail={info}")
        else:
            print("OK source_detail")

# --- 大文件分块（> chunksize）---
big_path = os.path.join(work, "big.csv")
with open(big_path, "w", encoding="utf-8") as f:
    f.write("id,val\n")
    for i in range(12000):
        f.write(f"{i},{i*2}\n")
with eng.connection() as conn:
    nb = ingest_csv_to_sqlite(big_path, "big_table", conn, chunksize=1000)
if nb != 12000:
    errors.append(f"big rows={nb}")
else:
    meta = eng.summary()
    row = next((m for m in meta if m["name"] == "big_table"), None)
    if not row or row["rows"] != 12000:
        errors.append(f"meta rows={row}")
    else:
        print("OK big chunked", row["rows"])

print("---")
if errors:
    print("FAIL", len(errors))
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("ALL PASS")
