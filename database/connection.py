"""ETK 精简版 connection — SQLite 兼容层
提供与原版 PostgreSQL 版相同接口:
  get_db_connection() -> contextmanager, yield conn (conn.cursor() 返回字典游标)
原版: psycopg2 + RealDictCursor + 连接池
本版: sqlite3 + Row (支持 row['col'] 访问)
"""
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("ETK_DB_PATH", "/config/etk.db")

_local = threading.local()


class _CtxCursor(sqlite3.Cursor):
    """支持 with 语法的 cursor（原版 psycopg2 cursor 支持 with，SQLite 原生不支持）"""
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            try:
                self.connection.commit()
            except Exception:
                pass
        else:
            try:
                self.connection.rollback()
            except Exception:
                pass
        return False


def _get_conn_inner():
    """线程内单连接"""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
        _init_schema(conn)
    return _local.conn


def _init_schema(conn):
    """建表（与原版 init_db 对应，只建翻译需要的表）"""
    conn.execute("""CREATE TABLE IF NOT EXISTS translation_cache (
        original_text TEXT PRIMARY KEY,
        translated_text TEXT,
        engine_used TEXT,
        last_updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS media_metadata (
        tmdb_id TEXT,
        item_type TEXT,
        title TEXT,
        overview TEXT,
        tagline TEXT,
        PRIMARY KEY (tmdb_id, item_type)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS app_settings (
        setting_key TEXT PRIMARY KEY,
        value_json TEXT,
        last_updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS processed_log (
        item_id TEXT PRIMARY KEY,
        item_name TEXT,
        item_type TEXT,
        processed_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS failed_log (
        item_id TEXT PRIMARY KEY,
        item_name TEXT,
        item_type TEXT,
        reason TEXT,
        error_message TEXT,
        failed_at TEXT
    )""")
    conn.commit()


@contextmanager
def get_db_connection():
    """兼容原版接口：yield 出支持 cursor() 的连接对象"""
    conn = _get_conn_inner()
    # 包一层代理：cursor() 返回支持 with 的 _CtxCursor（原版 psycopg2 风格）
    conn = _WrapConn(conn)
    try:
        yield conn
    except Exception:
        conn._raw.rollback()
        raise
    finally:
        # sqlite 单连接无需归还池，但保证提交
        try:
            conn._raw.commit()
        except Exception:
            pass


class _WrapConn:
    """sqlite3.Connection 的轻量代理：覆盖 cursor() 返回支持 with 的 _CtxCursor，
    其余属性透传（兼容原版 psycopg2 的 with conn.cursor() as c 语法）"""
    def __init__(self, raw):
        object.__setattr__(self, "_raw", raw)

    def cursor(self, *args, **kwargs):
        return self._raw.cursor(_CtxCursor)

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            try:
                self._raw.commit()
            except Exception:
                pass
        else:
            try:
                self._raw.rollback()
            except Exception:
                pass
        return False


def init_db():
    """建表（幂等）"""
    _get_conn_inner()
