#!/usr/bin/env python3
"""只读打开 Hermes 运行时 SQLite 库的工具函数。

为什么需要它: cron 调度器/网关会持续写 state.db 与 cron/executions.db。用
`file:...?mode=ro` 直连在写事务窗口内会随机报 "unable to open database file"
(SQLITE_CANTOPEN) —— 只读连接无法创建 WAL/-shm 协作文件。这个失败发生在
第一次语句执行时（sqlite3.connect 是惰性的），表现为看似随机的构建失败；
配合部署脚本的 `set -e` 会直接中止整晚的部署。

策略（逐级降级，永不因锁失败）:
  1) mode=ro 直连 + busy timeout，失败则重试（短暂窗口）
  2) 快照复制库文件(含 -wal/-shm)到临时目录后打开副本（彻底绕开锁竞争）
"""
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path


_SNAPSHOT_DIRS = {}


def connect_ro(path, retries=3, delay=0.4):
    """返回一个只读连接；必要时自动改用快照副本。"""
    path = Path(path)
    last = None
    for i in range(retries):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
            con.execute("SELECT 1").fetchone()  # 触发真正的打开（connect 是惰性的）
            return con
        except sqlite3.Error as e:
            last = e
            time.sleep(delay * (i + 1))
    # 快照回退：复制到临时目录再读，避免与写入方竞争
    try:
        tmp = Path(tempfile.mkdtemp(prefix="hermes-ro-"))
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(path) + suffix)
            if src.exists():
                shutil.copy2(src, tmp / (path.name + suffix))
        con = sqlite3.connect(f"file:{tmp / path.name}?mode=ro", uri=True, timeout=10)
        con.execute("SELECT 1").fetchone()
        _SNAPSHOT_DIRS[id(con)] = tmp  # 调用方 close 后由 close_ro 清理
        return con
    except sqlite3.Error:
        if last is None:
            raise
        raise last


def close_ro(con):
    """关闭连接并清理可能产生的快照目录。"""
    tmp = _SNAPSHOT_DIRS.pop(id(con), None)
    try:
        con.close()
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
