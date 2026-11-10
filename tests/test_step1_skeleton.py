"""Step 1：工程骨架自检 —— WebSocket 通、静态页能拿到。"""

from __future__ import annotations

import httpx

from helpers import WsClient


def test_healthz_ok(base):
    r = httpx.get(base + "/healthz", timeout=5)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_index_page_served(base):
    r = httpx.get(base + "/", timeout=5)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "诸伶无名" in body  # 品牌名（第 4 周改名：桌上剧团 · 诸伶无名）
    # 前端必须是原生 ES Module，不引框架
    assert 'type="module"' in body
    assert "socket.io" not in body.lower()


def test_static_assets_served(base):
    for path in ("/static/app.js", "/static/style.css"):
        r = httpx.get(base + path, timeout=5)
        assert r.status_code == 200, path
        assert len(r.text) > 100, path


async def test_ws_ping_pong(ws_base):
    c = await WsClient.connect(ws_base, "pinger")
    try:
        pong = await c.ping()
        assert pong["type"] == "pong"
    finally:
        await c.close()


async def test_ws_bad_json_gets_error(ws_base):
    c = await WsClient.connect(ws_base, "bad")
    try:
        await c.ws.send("这不是 JSON")
        err = await c.wait_error("BAD_JSON")
        assert err["type"] == "error"
    finally:
        await c.close()


async def test_ws_unknown_type_gets_error(ws_base):
    c = await WsClient.connect(ws_base, "unknown")
    try:
        await c.send("nope:nothing")
        err = await c.wait_error("UNKNOWN_TYPE")
        assert "code" in err and "message" in err
    finally:
        await c.close()
