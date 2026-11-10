"""线上冒烟：对任意部署地址做一轮真机自检（HTTP + WebSocket + 一局开局）。

用法：
    python scripts/smoke_remote.py https://zhuling-wuming.fly.dev
    python scripts/smoke_remote.py http://127.0.0.1:8000

退出码 0 = 全部通过；非 0 = 有失败项（会逐条打印原因）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import websockets
except ImportError:  # pragma: no cover
    print("需要 websockets：pip install -r requirements-dev.txt")
    raise SystemExit(2)


def http_get(url: str, timeout: float = 15) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "zhuling-smoke/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, b"", dict(exc.headers or {})
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc).encode(), {}


class Client:
    def __init__(self, ws_url: str, name: str) -> None:
        self.ws_url = ws_url
        self.name = name
        self.ws = None
        self.state: dict = {}
        self.events: list[dict] = []
        self.error: dict | None = None

    async def connect(self) -> None:
        self.ws = await websockets.connect(self.ws_url, open_timeout=20, ping_interval=20)
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                self.events.append(msg)
                if msg.get("type") == "room:state":
                    self.state = msg
                if msg.get("type") == "error":
                    self.error = msg
        except Exception:  # noqa: BLE001
            return

    async def send(self, kind: str, **payload) -> None:
        await self.ws.send(json.dumps({"type": kind, **payload}))

    async def wait(self, kind: str, timeout: float = 30, pred=None) -> dict:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for msg in list(self.events):
                if msg.get("type") == kind and (pred is None or pred(msg)):
                    return msg
            await asyncio.sleep(0.05)
        raise TimeoutError(f"{self.name} 等 {kind} 超时")

    async def close(self) -> None:
        try:
            await self.ws.close()
        except Exception:  # noqa: BLE001
            pass


RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'✅' if ok else '❌'} {name}{('  — ' + detail) if detail and not ok else ''}")


async def main() -> int:
    raw_base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    base = raw_base.rstrip("/")
    ws_url = urllib.parse.urlparse(base)
    ws_scheme = "wss" if ws_url.scheme == "https" else "ws"
    WS = f"{ws_scheme}://{ws_url.netloc}/ws"

    print(f"目标：{base}\n")

    # ---------- HTTP ----------
    status, body, headers = http_get(base + "/healthz")
    ok = status == 200 and b'"ok":true' in body.replace(b" ", b"")
    check("GET /healthz 200", ok, f"status={status} body={body[:80]!r}")

    if ok:
        try:
            health = json.loads(body)
            check(
                "healthz.service 名称正确",
                health.get("service") == "zhuling-wuming",
                str(health.get("service")),
            )
            check("单进程模式（rooms 字段存在）", "rooms" in health, str(health))
        except json.JSONDecodeError:
            check("healthz 是合法 JSON", False)

    status, body, headers = http_get(base + "/")
    html = body.decode("utf-8", "ignore")
    ctype = {k.lower(): v for k, v in headers.items()}.get("content-type", "")
    check("GET / 200 html", status == 200 and "text/html" in ctype, f"status={status} ctype={ctype}")
    check("页面含品牌名", "诸伶无名" in html)
    check("og:image 是绝对地址", 'property="og:image"' in html and base in html)
    check("没有残留占位符", "__OG_BASE__" not in html)

    for path in ("/static/style.css", "/static/style.v4.css", "/static/app.js",
                 "/static/js/ws.js", "/static/favicon.svg", "/favicon.ico", "/static/og.png"):
        status, body, headers = http_get(base + path)
        check(f"GET {path} 200", status == 200, f"status={status}")

    status, _, _ = http_get(base + "/debug/ai")
    if status in (403, 404):
        check("生产环境 /debug/ai 已关闭", True)
    else:
        print(f"⚠️  /debug/ai 返回 {status} —— 说明 AI_DEBUG=1，线上请务必关掉")

    # ---------- WebSocket ----------
    a, b = Client(WS, "甲"), Client(WS, "乙")
    try:
        await a.connect()
        await a.send("room:create", nickname="甲")
        await a.wait("room:state", timeout=20)
        code = a.state.get("roomCode")
        check("建房成功", bool(code), str(a.state)[:160])

        await b.connect()
        await b.send("room:join", roomCode=code, nickname="乙")
        await b.wait("room:state", timeout=20)
        check("第二人入场", not b.error, str(b.error))

        await asyncio.sleep(0.6)
        check("名册 2 人", len(a.state.get("players", [])) == 2, str(len(a.state.get("players", []))))

        await a.send("room:addAI", count=1)
        await asyncio.sleep(1.2)
        check("加 AI 成功", len(a.state.get("players", [])) == 3, str(len(a.state.get("players", []))))

        await a.send("setup:config", phase1Seconds=8, phase2Seconds=8, phase3Seconds=5)
        await asyncio.sleep(0.4)
        await a.send("game:start")
        started = await a.wait("phase:changed", timeout=25)
        check("开演进入 PHASE1", started.get("phase") == "PHASE1", str(started)[:160])
        check("PHASE1 带 deadline", isinstance(started.get("deadline"), (int, float)), str(started)[:160])

        # 非法操作要被拦（防止线上被乱来）
        b.error = None
        await b.send("card:submit", name="x", content="y")
        await asyncio.sleep(0.5)
        check("非写卡阶段的非法提交被拦", b.error is not None, "没有收到 error 帧")

        # 断线重连：拿到 token 后重连
        token = (a.state.get("you") or {}).get("reconnectToken")
        player_id = (a.state.get("you") or {}).get("playerId") or (a.state.get("you") or {}).get("id")
        check("room:state 下发重连凭据", bool(token) and bool(player_id))

        if token and player_id:
            a2 = Client(WS, "甲-重连")
            try:
                await a2.connect()
                await a2.send("conn:reconnect", roomCode=code, playerId=player_id, token=token)
                msg = await a2.wait("reconnect:ok", timeout=15)
                check("刷新后能回座", (msg.get("snapshot") or {}).get("roomCode") == code)
            except TimeoutError:
                check("刷新后能回座", False, "reconnect:ok 超时")
            finally:
                await a2.close()
    except TimeoutError as exc:
        check("WebSocket 基础流程", False, str(exc))
    finally:
        await a.close()
        await b.close()

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} 通过")
    if bad:
        print("失败项：")
        for name, _, detail in bad:
            print(f"  - {name} {detail}")
        return 1
    print("🎭 这台机器可以发给朋友玩了")
    return 0


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
