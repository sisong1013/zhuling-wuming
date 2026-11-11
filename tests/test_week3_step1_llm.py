"""Step 3.1：LLM 封装（无 Key / 超时 / 报错 一律兜底，永不卡死）。"""

from __future__ import annotations

import asyncio

import pytest

import pytest

from server import llm_client


@pytest.fixture(autouse=True)
def _allow_llm_in_this_module(monkeypatch):
    """CI 的 job env 里带着 LLM_DISABLE=1（防真调用）；本模块已 monkeypatch，
    不会真的发请求，所以这里把它解开，测的是降级/解析逻辑。"""
    monkeypatch.delenv("LLM_DISABLE", raising=False)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个用例默认：没有 Key、没有自定义 base url。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    yield


async def test_without_key_never_calls_network(monkeypatch):
    """没配 Key 时直接返回空串，连请求都不发。"""

    async def boom(*args, **kwargs):  # pragma: no cover - 不该被调用
        raise AssertionError("没配 Key 不应该发起网络请求")

    monkeypatch.setattr(llm_client, "_request", boom)
    assert llm_client.is_available() is False
    assert await llm_client.call_llm("s", "u") == ""


async def test_success_path(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    calls: list[tuple] = []

    async def fake(system, user, timeout, json_mode, model=None, budget=0):
        calls.append((system, user, timeout, json_mode, model))
        return "你好"

    monkeypatch.setattr(llm_client, "_request", fake)
    assert llm_client.is_available() is True
    out = await llm_client.call_llm("sys", "usr", timeout=3)
    assert out == "你好"
    assert calls == [("sys", "usr", 3, False, "gpt-4o-mini")]  # 默认模型


async def test_timeout_returns_fallback(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    async def slow(*args, **kwargs):
        raise asyncio.TimeoutError("boom")

    monkeypatch.setattr(llm_client, "_request", slow)
    assert await llm_client.call_llm("s", "u", timeout=0.05) == ""


async def test_http_error_returns_fallback(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    async def bad(*args, **kwargs):
        raise RuntimeError("502 Bad Gateway")

    monkeypatch.setattr(llm_client, "_request", bad)
    assert await llm_client.call_llm("s", "u") == ""


async def test_json_mode_parses_object(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    async def fake(system, user, timeout, json_mode, model=None, budget=0):
        assert json_mode is True
        return '{"action":"SKIP"}'

    monkeypatch.setattr(llm_client, "_request", fake)
    data = await llm_client.call_llm_json("s", "u")
    assert data == {"action": "SKIP"}


async def test_json_mode_with_fence_and_garbage(monkeypatch):
    """模型爱加 ```json 围栏或前言，要能捞出来。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    async def fenced(*args, **kwargs):
        return '当然可以，这是结果：\n```json\n{"action":"ASK","target_room":2}\n```'

    monkeypatch.setattr(llm_client, "_request", fenced)
    data = await llm_client.call_llm_json("s", "u")
    assert data == {"action": "ASK", "target_room": 2}

    assert llm_client.parse_json("完全不是 JSON") is None
    assert llm_client.parse_json("") is None


def test_stats_shape(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "qwen-turbo")
    st = llm_client.stats()
    assert st["configured"] is True
    assert st["model"] == "qwen-turbo"
    assert set(st) == {
        "configured",
        "baseUrl",
        "model",
        "chain",
        "maxTokens",
        "lastModel",
        "calls",
        "fallbacks",
    }
    assert st["chain"] == ["qwen-turbo"]


def test_default_model_is_cheap_one(monkeypatch):
    assert llm_client.model_name() == "gpt-4o-mini"
    assert llm_client.base_url() == "https://api.openai.com/v1"


def test_dotenv_candidates_point_to_game_root():
    """`.env` 应该放在 game/ 下（不是项目根、不是 server/ 下）。"""
    from server import main

    first = main.ENV_CANDIDATES[0]
    assert first.name == ".env"
    assert first.parent == main.GAME_ROOT
    # 仓库目录在 CI 里叫别的名字（zhuling-wuming），所以判断「这里有服务代码」而不是目录名
    assert (first.parent / "server" / "main.py").is_file()
