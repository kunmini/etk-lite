"""ETK 精简版 settings_db — AI 配置从 config_manager 读取"""
import json
import logging

from . import connection

logger = logging.getLogger(__name__)


def get_setting(setting_key: str):
    """兼容原版：优先查 app_settings 表，没有则从 config_manager 环境变量读"""
    try:
        with connection.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value_json FROM app_settings WHERE setting_key = ?", (setting_key,))
            row = cursor.fetchone()
            if row:
                raw = row["value_json"]
                if raw:
                    try:
                        return json.loads(raw)
                    except Exception:
                        return raw
    except Exception as e:
        logger.debug(f"读取设置 {setting_key} 失败: {e}")

    # 回退到环境变量
    import config_manager
    cfg = config_manager.APP_CONFIG
    return cfg.get(setting_key)


def save_setting(setting_key: str, value) -> None:
    try:
        with connection.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO app_settings (setting_key, value_json, last_updated_at) VALUES (?,?,datetime('now'))",
                (setting_key, json.dumps(value, ensure_ascii=False)))
    except Exception as e:
        logger.error(f"保存设置 {setting_key} 失败: {e}")


def delete_setting(setting_key: str) -> None:
    try:
        with connection.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM app_settings WHERE setting_key = ?", (setting_key,))
    except Exception as e:
        logger.error(f"删除设置 {setting_key} 失败: {e}")
