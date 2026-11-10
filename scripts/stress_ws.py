"""压力测试脚本：N 路并发 WebSocket 打一局，打印阶段耗时。

用法：
    python scripts/stress_ws.py                 # 默认 8 人 2 轮，连本机 8000
    python scripts/stress_ws.py --players 8 --rounds 3 --url ws://127.0.0.1:8000/ws
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import websockets


class Client:
    def __init__(self, ws):
        self.ws = ws
        self.name = ""
        self.player_id = ""
        self.room_code = ""
        self.room_no = None

    async def send(self, mtype: str, **payload) -> None:
        await self.ws.send(json.dumps({"type": mtype, **payload}))

    async def wait(self, mtype: str, timeout: float = 15.0, pred=None) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise TimeoutError(f"{self.name} 等 {mtype} 超时")
            raw = await asyncio.wait_for(self.ws.recv(), remain)
            msg = json.loads(raw)
            if msg.get("type") == mtype and (pred is None or pred(msg)):
                return msg


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8000/ws")
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()

    clients: list[Client] = []
    timings: dict[str, list[float]] = {}

    for i in range(args.players):
        ws = await websockets.connect(args.url, max_size=2**22)
        clients.append(Client(ws))

    captain = clients[0]
    await captain.send("room:create", nickname="甲0")
    created = await captain.wait("room:created")
    captain.player_id = created["playerId"]
    captain.room_code = created["roomCode"]
    captain.name = "甲0"
    code = created["roomCode"]
    print(f"房间 {code}，加入 {args.players} 人…")

    for idx, c in enumerate(clients[1:], start=1):
        c.name = f"甲{idx}"
        await c.send("room:join", roomCode=code, nickname=c.name)
        joined = await c.wait("room:joined")
        c.player_id = joined["playerId"]
        c.room_code = code

    await captain.send(
        "setup:config",
        phase1Seconds=20,
        phase2Seconds=10,
        phase3Seconds=10,
        forcedSubmitRound=99,
    )
    await captain.wait("room:state", pred=lambda m: m.get("config", {}).get("phase1Seconds") == 20)

    t0 = time.monotonic()
    await captain.send("game:start")
    for c in clients:
        msg = await c.wait("game:started", timeout=20)
        c.room_no = msg["yourRoomNo"]
    timings.setdefault("start", []).append(time.monotonic() - t0)
    print(f"开局成功，用时 {timings['start'][-1]:.2f}s")

    for round_no in range(1, args.rounds + 1):
        t1 = time.monotonic()
        for c in clients:
            await c.send("phase1:skip")
        for c in clients:
            await c.wait("phase:changed", timeout=40, pred=lambda m: m["phase"] == "PHASE3")
        timings.setdefault("phase1→phase3", []).append(time.monotonic() - t1)

        t2 = time.monotonic()
        for c in clients:
            await c.send("phase3:confirm")
        if round_no < args.rounds:
            for c in clients:
                await c.wait("phase:changed", timeout=40, pred=lambda m: m["phase"] == "PHASE1")
            timings.setdefault("phase3→下一轮", []).append(time.monotonic() - t2)
        print(f"第 {round_no} 轮完成")

    print("\n=== 阶段耗时（秒）===")
    for key, values in timings.items():
        print(f"{key:14s} n={len(values):2d} median={statistics.median(values):.2f} max={max(values):.2f}")

    for c in clients:
        await c.ws.close()


if __name__ == "__main__":
    asyncio.run(main())
