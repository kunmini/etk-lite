"""ETK 精简版 actor_db — 翻译缓存管理器（SQLite）"""
import logging
from typing import Dict, Optional

from . import connection
from utils import contains_chinese

logger = logging.getLogger(__name__)


class ActorDBManager:
    """翻译缓存管理（原版 ActorDBManager 精简，只保留翻译缓存）"""

    def get_translation_from_db(self, cursor, text: str, by_translated_text: bool = False) -> Optional[Dict[str, str]]:
        try:
            if by_translated_text:
                sql = "SELECT original_text, translated_text, engine_used FROM translation_cache WHERE translated_text = ?"
            else:
                sql = "SELECT original_text, translated_text, engine_used FROM translation_cache WHERE original_text = ?"
            cursor.execute(sql, (text,))
            row = cursor.fetchone()
            if not row:
                return None
            translated = row["translated_text"]
            if translated and not contains_chinese(translated):
                # 坏数据，清理
                cursor.execute("DELETE FROM translation_cache WHERE original_text = ?", (text,))
                return None
            return {"original_text": row["original_text"],
                    "translated_text": row["translated_text"],
                    "engine_used": row["engine_used"]}
        except Exception as e:
            logger.debug(f"翻译缓存读取失败: {e}")
            return None

    def save_translation_to_db(self, cursor, original_text, translated_text, engine_used):
        if isinstance(translated_text, (list, tuple, set)):
            translated_text = next((x for x in translated_text if isinstance(x, str) and x.strip()), None)
        if not translated_text:
            return
        translated_text = str(translated_text).strip()
        if not translated_text or not contains_chinese(translated_text):
            logger.warning(f"翻译结果不含中文或为空，丢弃。原文: {original_text}")
            return
        try:
            cursor.execute(
                """INSERT OR REPLACE INTO translation_cache (original_text, translated_text, engine_used, last_updated_at)
                   VALUES (?,?,?,datetime('now'))""",
                (str(original_text).strip(), translated_text, engine_used))
        except Exception as e:
            logger.error(f"翻译缓存保存失败: {e}")


def get_actor_db_manager():
    return ActorDBManager()
