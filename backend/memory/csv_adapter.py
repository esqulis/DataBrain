"""CSV 读取适配：编码探测 + 分隔符嗅探 + 分块读取"""

from __future__ import annotations

import csv
import io
import os
from typing import Iterator

# 常见编码，按优先级尝试
_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1")
_SNIFF_DELIMITERS = ",;\t|"


def detect_encoding(path: str, sample_size: int = 256 * 1024) -> str:
    """探测文件编码。优先 BOM，其次试解码样本。"""
    with open(path, "rb") as f:
        head = f.read(sample_size)

    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
        return "utf-16"

    # 严格试 utf-8（整段样本必须可解码）
    try:
        head.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    for enc in ("gb18030", "gbk", "big5"):
        try:
            head.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue

    return "latin-1"


def detect_delimiter(path: str, encoding: str = "utf-8", sample_lines: int = 20) -> str:
    """嗅探分隔符：优先 csv.Sniffer，失败则按首行出现次数投票。"""
    try:
        with open(path, "r", encoding=encoding, errors="replace", newline="") as f:
            sample = "".join(f.readline() for _ in range(sample_lines))
    except OSError:
        return ","

    if not sample.strip():
        return ","

    # Sniffer
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=_SNIFF_DELIMITERS)
        if dialect.delimiter in _SNIFF_DELIMITERS:
            return dialect.delimiter
    except csv.Error:
        pass

    # 投票：取首行（非空）中出现最多的候选
    first_line = ""
    for line in sample.splitlines():
        if line.strip():
            first_line = line
            break
    if not first_line:
        return ","

    scores = {d: first_line.count(d) for d in _SNIFF_DELIMITERS}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ","


def read_csv_kwargs(path: str) -> dict:
    """返回可直接传给 pd.read_csv 的参数"""
    encoding = detect_encoding(path)
    sep = detect_delimiter(path, encoding=encoding)
    return {
        "encoding": encoding,
        "sep": sep,
        "engine": "python",  # python 引擎对自定义 sep 更稳
        "on_bad_lines": "skip",
    }


def count_csv_rows(path: str, kwargs: dict | None = None) -> int:
    """用 pandas 精确统计数据行数（不含表头）"""
    import pandas as pd

    kw = kwargs or read_csv_kwargs(path)
    # chunksize 只为计数
    kw = {**kw, "chunksize": 50000}
    total = 0
    for chunk in pd.read_csv(path, **kw):
        total += len(chunk)
    return total


def iter_csv_chunks(path: str, chunksize: int = 5000, kwargs: dict | None = None) -> Iterator:
    """按块读取 CSV"""
    import pandas as pd

    kw = kwargs or read_csv_kwargs(path)
    kw = {**kw, "chunksize": chunksize}
    return pd.read_csv(path, **kw)


def ingest_csv_to_sqlite(
    path: str,
    table_name: str,
    conn,
    task_id: str | None = None,
    progress_cb=None,
    chunksize: int = 5000,
    original_name: str | None = None,
) -> int:
    """分块写入 SQLite，返回写入行数。progress_cb(pct, message)"""
    kwargs = read_csv_kwargs(path)

    def _report(pct: int, msg: str):
        if progress_cb:
            progress_cb(pct, msg)

    _report(8, f"识别编码={kwargs['encoding']} 分隔符={kwargs['sep']!r}…")

    total = count_csv_rows(path, kwargs)
    _report(12, f"共 {total} 行，开始写入…")

    first = True
    processed = 0
    for chunk in iter_csv_chunks(path, chunksize=chunksize, kwargs=kwargs):
        # 统一列名为 str，避免 None 列
        chunk.columns = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(chunk.columns)]
        chunk.to_sql(table_name, conn, index=False, if_exists="replace" if first else "append")
        first = False
        processed += len(chunk)
        pct = min(90, 12 + int(78 * processed / max(total, 1)))
        _report(pct, f"处理中… {processed}/{max(total, 1)} 行")

    col_count = conn.execute(
        f'SELECT COUNT(*) FROM pragma_table_info("{table_name}")'
    ).fetchone()[0]
    conn.execute(
        "INSERT OR REPLACE INTO _meta (name, rows, columns, source_type, source_detail) VALUES (?,?,?,?,?)",
        (table_name, processed, col_count, "file", original_name or os.path.basename(path)),
    )
    conn.commit()
    return processed
