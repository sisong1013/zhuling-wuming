"""验证「全对就赢」：用 /debug/ai 的真值提交完整看板，应当 game:over。"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

import websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
WS = BASE.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/ws"


class C:
    def __init__(self, name: str) -> None:
        self.name = name
        self.events: list[dict] = []
        self.state: dict = {}

    async def connect(self) -> None:
        self.ws = await websockets.connect(WS)
        self.task = asyncio.create_task(self.pump())

    async def pump(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            self.events.append(msg)
            if msg.get("type") == "room:state":
                self.state = msg

    async def send(self, kind: str, **payload) -> None:
        await self.ws.send(json.dumps({"type": kind, **payload}))

    async def wait(self, kind: str, timeout: float = 25, pred=None) -> dict:
        for _ in range(int(timeout * 10)):
            for msg in list(self.events):
                if msg.get("type") == kind and (pred is None or pred(msg)):
                    return msg
            await asyncio.sleep(0.1)
        raise TimeoutError(kind)


def truth_of(code: str) -> dict:
    with urllib.request.urlopen(BASE + "/debug/ai", timeout=10) as resp:
        data = json.loads(resp.read())
    room = next(r for r in data["rooms"] if r["roomCode"] == code)
    return room["truth"]


async def main() -> None:
    a, b = C("甲"), C("乙")
    await a.connect()
    await a.send("room:create", nickname="甲")
    await a.wait("room:state")
    code = a.state["roomCode"]

    await b.connect()
    await b.send("room:join", roomCode=code, nickname="乙")
    await b.wait("room:state")
    await a.wait("room:state", pred=lambda m: len(m.get("players", [])) == 2)

    await a.send("setup:config", gameMode="REAL")
    await asyncio.sleep(0.4)
    await a.send("game:start")
    await a.wait("phase:changed", pred=lambda m: m.get("phase") == "PHASE1", timeout=20)

    truth = truth_of(code)
    board = {str(no): name for no, name in truth.items()}
    print("真值:", truth)
    print("提交:", board)

    # 只提交非自己的格子（模拟"本人那格白送、客户端没填"的旧行为）
    my_no = a.state["you"]["roomNo"]
    partial = {k: v for k, v in board.items() if int(k) != my_no}
    print(f"故意不填自己那格（{my_no} 号），验证服务端兜底：", partial)

    await a.send("phase1:submit", board=partial)
    res = await a.wait("submit:result", timeout=20)
    print("提交结果:", {k: res.get(k) for k in ("correct", "missing", "wrong", "cooldown")})

    if res.get("correct"):
        over = await a.wait("game:over", timeout=20)
        print("✅ 全对即获胜，game:over 收到：winner =", over.get("winnerNickname") or over.get("winnerId"))
    else:
        print("❌ 仍然判错（这就是用户遇到的 bug）")

    await a.ws.close()
    await b.ws.close()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
