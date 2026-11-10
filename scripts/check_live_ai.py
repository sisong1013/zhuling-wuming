"""线上真机抽检：AI 是否真的在用模型写卡（PERSONA 两人局，我拿到的就是 AI 的卡）。"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://zhuling-wuming.up.railway.app"
WS = BASE.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/ws"


async def main() -> None:
    ws = await websockets.connect(WS, open_timeout=25, ping_interval=20)
    events: list[dict] = []

    async def pump() -> None:
        async for raw in ws:
            events.append(json.loads(raw))

    task = asyncio.create_task(pump())

    async def send(kind: str, **payload) -> None:
        await ws.send(json.dumps({"type": kind, **payload}))

    async def wait(kind: str, timeout: float = 90, pred=None) -> dict:
        for _ in range(int(timeout * 10)):
            for msg in list(events):
                if msg.get("type") == kind and (pred is None or pred(msg)):
                    return msg
            await asyncio.sleep(0.1)
        raise TimeoutError(kind)

    await send("room:create", nickname="抽检员")
    st = await wait("room:state")
    code = st["roomCode"]
    await send("room:addAI", count=1)
    await asyncio.sleep(1)
    await send("setup:config", gameMode="PERSONA")
    await asyncio.sleep(1)
    await send("game:start")
    await wait("room:state", pred=lambda m: m.get("phase") == "CARD_WRITING", timeout=30)

    await send("card:submit", name="雨天的抄写员", content="替人抄写说不出口的话，抄完自己的记忆少一小块。")
    print("等 AI 写卡（走真模型要 10-20 秒）…")
    await wait("card:progress", pred=lambda m: m.get("submitted") == 2, timeout=120)

    await send("captain:startAssign")
    await wait("phase:changed", pred=lambda m: m.get("phase") == "READING", timeout=40)
    assigned = await wait("persona:assigned", timeout=30)
    their_card = assigned.get("yourCard", {})
    print("两人局错位分配 ⇒ 我拿到的就是 AI 的卡：")
    print("  卡名:", their_card.get("name"))
    print("  卡面:", (their_card.get("content") or "")[:90])
    name = their_card.get("name") or ""
    print("判断：", "看起来像真模型写的" if "·AI" not in name and len(name) >= 3 else "像是离线兜底池里的卡")
    task.cancel()
    await ws.close()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
