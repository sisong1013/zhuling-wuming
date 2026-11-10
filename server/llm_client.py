"""LLM 客户端（OpenAI 兼容接口）。

设计目标：**永远不把游戏卡死**。
- 无 API Key / 未配置 → 立即返回兜底空串（不发起任何网络请求）
- 超时（默认 15s）/ HTTP 错误 / 解析失败 → 返回兜底空串，并记一条日志
- `json_mode=True` 时要求服务端返回 JSON 对象，并做一次宽松解析

调用方拿到空串时应当走各自的离线兜底逻辑（见 `server/ai.py`）。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger("game.llm")

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
FALLBACK_TEXT = ""


class BudgetExceeded(RuntimeError):
    """推理把 max_tokens 吃干净了，content 为空。"""


def _env(name: str, default: str = "") -> str:
    """读环境变量（.env 已由 main 在启动时加载，这里只读 os.environ）。"""
    value = os.environ.get(name)
    return value if value else default


def api_key() -> str:
    return _env("LLM_API_KEY")


def base_url() -> str:
    return _env("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def model_name() -> str:
    return _env("LLM_MODEL", DEFAULT_MODEL)


def max_tokens() -> int:
    """输出预算。推理型模型会先烧 reasoning_tokens，给少了 content 会是空的。"""
    try:
        return max(200, int(_env("LLM_MAX_TOKENS", "2400")))
    except ValueError:
        return 2400


def model_chain() -> list[str]:
    """主模型 + 备选模型（LLM_MODEL_FALLBACKS 逗号分隔），去重保序。"""
    chain = [model_name()]
    for extra in _env("LLM_MODEL_FALLBACKS", "").split(","):
        name = extra.strip()
        if name and name not in chain:
            chain.append(name)
    return chain


def is_available() -> bool:
    """有没有配 Key；没配就不要发请求（省得每次等超时）。

    LLM_DISABLE=1 时强制走离线兜底（自动化测试用，避免真的花钱/被限流）。
    """
    if _env("LLM_DISABLE") == "1":
        return False
    return bool(api_key())


def stats() -> dict[str, Any]:
    """给 /debug/ai 与报告用的轻量统计。"""
    return {
        "configured": is_available(),
        "baseUrl": base_url() if is_available() else None,
        "model": model_name(),
        "chain": model_chain() if is_available() else [],
        "maxTokens": max_tokens(),
        "lastModel": _CALLS.get("model"),
        "calls": _CALLS["total"],
        "fallbacks": _CALLS["fallback"],
    }


_CALLS: dict[str, Any] = {"total": 0, "fallback": 0, "model": None}


async def _request(
    system_prompt: str,
    user_prompt: str,
    timeout: float,
    json_mode: bool,
    model: str | None = None,
    budget: int = 0,
) -> str:
    """真正的 HTTP 调用（测试里会被 monkeypatch 掉）。"""
    payload: dict[str, Any] = {
        "model": model or model_name(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": budget if budget else max_tokens(),
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    url = f"{base_url()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    choice = (data.get("choices") or [{}])[0]
    content = ((choice.get("message") or {}).get("content") or "").strip()
    if not content and choice.get("finish_reason") == "length":
        # 预算被 reasoning 吃掉 → 明确告诉调用方"这是预算问题"，可加钱重试
        raise BudgetExceeded("输出预算被推理占满（finish_reason=length）")
    return content


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    timeout: float = 15.0,
    json_mode: bool = False,
) -> str:
    """统一入口：成功返回文本，任何失败都返回 `FALLBACK_TEXT`（空串）。"""
    _CALLS["total"] += 1
    if not is_available():
        _CALLS["fallback"] += 1
        return FALLBACK_TEXT

    last_exc: Exception | None = None
    for model in model_chain():  # 降级链：主模型挂了换备选，全挂才兜底
        budget = 0
        for attempt in range(2):  # 预算被推理吃掉时，翻倍再试一次
            try:
                text = await _request(
                    system_prompt,
                    user_prompt,
                    timeout,
                    json_mode,
                    model=model,
                    budget=budget,
                )
                if text:
                    _CALLS["model"] = model
                    return text
                last_exc = RuntimeError("模型返回空内容")
                break
            except BudgetExceeded as exc:
                last_exc = exc
                if attempt == 0:
                    budget = min(6000, max_tokens() * 2)
                    log.info("LLM(%s) 预算不足，加到 %s 重试", model, budget)
                    continue
                log.warning("LLM(%s) 加预算后仍为空: %s", model, exc)
                break
            except Exception as exc:  # noqa: BLE001 - 任何异常都不许冒泡
                last_exc = exc
                log.warning("LLM(%s) 调用失败，尝试下一个: %s: %s", model, type(exc).__name__, exc)
                break

    _CALLS["fallback"] += 1
    if last_exc is not None:
        log.warning("LLM 全链路失败（已兜底）: %s: %s", type(last_exc).__name__, last_exc)
    return FALLBACK_TEXT


_JSON_OBJ = re.compile(r"\{.*\}", re.S)


def parse_json(text: str) -> dict[str, Any] | None:
    """宽松解析：先整体 loads，再退化为截取第一个 {...}。"""
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJ.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def call_llm_json(
    system_prompt: str, user_prompt: str, timeout: float = 15.0
) -> dict[str, Any] | None:
    """强制 JSON 输出；拿不到合法对象就返回 None（调用方走兜底）。"""
    text = await call_llm(system_prompt, user_prompt, timeout=timeout, json_mode=True)
    return parse_json(text)
