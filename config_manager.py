"""ETK 精简版 config_manager — 读环境变量/JSON 配置"""
import json
import logging
import os

logger = logging.getLogger(__name__)

CONFIG_FILE = os.environ.get("ETK_CONFIG_FILE", "/config/config.json")


def _default_config() -> dict:
    return {
        "ai_provider": os.environ.get("AI_PROVIDER", "openai"),
        "ai_api_key": os.environ.get("AI_API_KEY", ""),
        "ai_model_name": os.environ.get("AI_MODEL", "deepseek-chat"),
        "ai_base_url": os.environ.get("AI_BASE_URL", "https://api.deepseek.com/v1"),
        "ai_translation_mode": os.environ.get("AI_MODE", "quality"),
        "ai_translate_title": os.environ.get("AI_TRANSLATE_TITLE", "true").lower() in ("1", "true", "yes"),
        "ai_translate_overview": os.environ.get("AI_TRANSLATE_OVERVIEW", "true").lower() in ("1", "true", "yes"),
        "ai_translate_actor_role": os.environ.get("AI_TRANSLATE_ACTOR", "false").lower() in ("1", "true", "yes"),
        "ai_joke_fallback": os.environ.get("AI_JOKE_FALLBACK", "false").lower() in ("1", "true", "yes"),
        "ai_request_timeout": int(os.environ.get("AI_REQUEST_TIMEOUT", "120")),  # AI 请求超时（秒），硅基流动慢时防误杀
        "tmdb_api_key": os.environ.get("TMDB_API_KEY", ""),
        "emby_url": os.environ.get("EMBY_URL", "http://127.0.0.1:8096"),
        "emby_api_key": os.environ.get("EMBY_API_KEY", ""),
    }

def load_config() -> dict:
    cfg = _default_config()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                file_cfg = json.load(f)
            if isinstance(file_cfg, dict):
                cfg.update({k: v for k, v in file_cfg.items() if v not in (None, "")})
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
    return cfg


APP_CONFIG = load_config()


def is_system_configured() -> bool:
    return bool(APP_CONFIG.get("ai_api_key"))


def get_proxies_for_requests() -> dict:
    return {}
