"""真机联调：用真实 LLM 陪演一局，打印 AI 的卡 / 提问 / 作答 / 推理。

用法：先起服务（AI_DEBUG=1 开了的话还能看 /debug/ai），再
  .venv\\Scripts\\python.exe scripts/demo_llm_game.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

try:
    import websockets
except ImportError:  # pragma: no cover
    print("需要 websockets")
    raise

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000/ws"


class Client:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ws = None
        self.state: dict = {}
        self.events: list[dict] = []

    async def connect(self) -> None:
        self.ws = await websockets.connect(WS)
        self.task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            self.events.append(msg)
            kind = msg.get("type")
            if kind == "room:state":
                self.state = msg

    async def send(self, kind: str, **payload) -> None:
        await self.ws.send(json.dumps({"type": kind, **payload}))

    async def wait(self, kind: str, timeout: float = 90, pred=None) -> dict:
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            for msg in list(self.events):
                if msg.get("type") == kind and (pred is None or pred(msg)):
                    return msg
            await asyncio.sleep(0.1)
        raise TimeoutError(f"{self.name} 等 {kind} 超时")

    def phase(self) -> str:
        return self.state.get("phase", "?")


def debug_ai() -> dict:
    with urllib.request.urlopen(BASE + "/debug/ai", timeout=10) as resp:
        return json.loads(resp.read())


async def main() -> None:
    human = Client("甲")
    await human.connect()
    await human.send("room:create", nickname="甲")
    await human.wait("room:state")
    code = human.state["roomCode"]
    print(f"房间 {code}")

    await human.send("room:addAI", count=1)
    await asyncio.sleep(0.5)
    await human.send("setup:config", gameMode="PERSONA")
    await asyncio.sleep(0.5)
    await human.send("game:start")
    card_phase = await human.wait("room:state", pred=lambda m: m.get("phase") == "CARD_WRITING")
    print("进入写卡；等 AI 用真模型写卡（推理模型约 5-15 秒）…")

    await human.send("card:submit", name="雨天的抄写员", content="替人抄写说不出口的话，抄完自己的记忆少一小块。")
    await human.wait("card:progress", pred=lambda m: m.get("submitted") == 2, timeout=120)

    debug = debug_ai()
    room = next(r for r in debug["rooms"] if r["roomCode"] == code)
    ai_card = [
        c for c in debug["ais"][0]["decisions"] if c.get("kind") == "card"
    ] if debug.get("ais") else []
    print("AI 写的卡：", json.dumps(ai_card[:2], ensure_ascii=False)[:400])

    await human.send("captain:startAssign")
    await human.wait("phase:changed", pred=lambda m: m.get("phase") == "READING", timeout=60)
    assigned = await human.wait("persona:assigned", timeout=30)
    print("我拿到的卡：", assigned.get("yourCard", {}).get("name"))

    await human.send("reading:confirm")
    await human.wait("phase:changed", pred=lambda m: m.get("phase") == "PHASE1", timeout=60)
    print("第一幕开始，等 AI 决策…")

    for _ in range(60):
        await asyncio.sleep(1)
        debug = debug_ai()
        ai = next((a for a in debug.get("ais", []) if a.get("roomCode", code) == code), None)
        decisions = [d for d in (ai or {}).get("decisions", []) if d.get("kind") == "phase1"]
        if decisions:
            print("AI 第一幕决策：", json.dumps(decisions[-1], ensure_ascii=False)[:300])
            break

    # AI 若发问，进入第二幕作答
    try:
        await human.wait("phase:changed", pred=lambda m: m.get("phase") == "PHASE2", timeout=90)
        q = await human.wait("question:public", timeout=15)
        print("公开问答：", json.dumps(q, ensure_ascii=False)[:300])
        await asyncio.sleep(12)  # 等 AI 按人设作答
        debug = debug_ai()
        answers = [d for d in ai["decisions"] if d.get("kind") == "answer"]
        print("AI 的作答：", json.dumps(answers[-1], ensure_ascii=False)[:300] if answers else "（无）")
    except TimeoutError:
        print("本轮 AI 没提问（可能选了提交/跳过）")

    print("LLM 统计：", json.dumps(debug_ai()["llm"], ensure_ascii=False))
    await human.ws.close()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
