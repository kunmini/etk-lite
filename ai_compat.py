#!/usr/bin/env python3
"""
ETK 精简版 — OpenAI 兼容客户端包装器
解决: 硅基流动/DeepSeek/Ollama 等服务的 response_format=json_object 兼容性差异
- OpenAI/DeepSeek/硅基流动/Moonshot: 支持 json_object
- Ollama 等本地服务: 可能不支持 → 自动降级重试（去掉 response_format）
用法: 在初始化 AITranslator 前，把 client 换成 CompatClient
"""
import json
import logging
import re

logger = logging.getLogger(__name__)


class CompatChatCompletions:
    """包装 chat.completions，json_object 失败自动降级重试"""

    def __init__(self, inner):
        self._inner = inner

    def create(self, *args, **kwargs):
        try:
            return self._inner.create(*args, **kwargs)
        except Exception as e:
            # 仅当使用了 response_format 且错误疑似"不支持"时降级
            if "response_format" in kwargs and self._is_unsupported_json_error(e):
                logger.warning(
                    f"当前服务不支持 response_format=json_object，自动降级重试: {type(e).__name__}: {str(e)[:80]}")
                kwargs.pop("response_format", None)
                return self._inner.create(*args, **kwargs)
            raise

    @staticmethod
    def _is_unsupported_json_error(e) -> bool:
        msg = str(e).lower()
        markers = (
            "response_format", "json_object", "not supported", "unsupported",
            "badrequest", "invalid_request", "400", "invalid parameter",
            "additional properties", "json mode", "does not support",
        )
        return any(m in msg for m in markers)


class CompatClient:
    """包装 OpenAI client，暴露相同接口"""

    def __init__(self, inner):
        self._inner = inner
        self.chat = inner.chat
        # 用包装后的 chat.completions
        self.chat.completions = CompatChatCompletions(inner.chat.completions)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def wrap_client(client):
    """把普通 OpenAI client 包成兼容版（幂等）"""
    if client is None:
        return None
    if isinstance(client, CompatClient):
        return client
    return CompatClient(client)
