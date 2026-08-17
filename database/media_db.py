"""ETK 精简版 media_db — 本地翻译元数据缓存（SQLite）"""
import logging
from typing import Dict, Optional

from . import connection

logger = logging.getLogger(__name__)


# ---------- processed_log / failed_log（防重复翻译 + 失败记录） ----------

def is_processed(item_id: str) -> bool:
    """该条目是否已处理过（防止重复翻译烧 AI 钱）"""
    try:
        with connection.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM processed_log WHERE item_id = ?", (str(item_id),))
            return cursor.fetchone() is not None
    except Exception:
        return False


def mark_processed(item_id: str, item_name: str = "", item_type: str = "") -> None:
    try:
        with connection.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO processed_log (item_id, item_name, item_type, processed_at) VALUES (?,?,?,datetime('now'))",
                (str(item_id), item_name, item_type))
    except Exception as e:
        logger.debug(f"标记已处理失败: {e}")


def record_failed(item_id: str, item_name: str = "", item_type: str = "",
                  reason: str = "", error_message: str = "") -> None:
    try:
        with connection.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO failed_log (item_id, item_name, item_type, reason, error_message, failed_at) VALUES (?,?,?,?,?,datetime('now'))",
                (str(item_id), item_name, item_type, reason, str(error_message)[:500]))
    except Exception as e:
        logger.debug(f"记录失败失败: {e}")


def clear_processed() -> int:
    """清空已处理记录（强制重新翻译全库）"""
    try:
        with connection.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM processed_log")
            return cursor.rowcount
    except Exception:
        return 0


def clear_failed() -> int:
    try:
        with connection.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM failed_log")
            return cursor.rowcount
    except Exception:
        return 0


def get_failed_list(limit: int = 50) -> list:
    try:
        with connection.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM failed_log ORDER BY failed_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]
    except Exception:
        return []
