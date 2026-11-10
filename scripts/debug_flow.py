"""临时调试脚本：复现「全员确认后进入下一轮」的广播问题，打印每条连接收到的消息。"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

GAME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME_DIR / "tests"))

from helpers import WsClient, create_room, join_room  # noqa: E402


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def main() -> None:
    port = free_port()
    env = dict(os.environ, PYTHONPATH=str(GAME_DIR), PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "debug"],
        cwd=str(GAME_DIR), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/healthz", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    ws_url = base.replace("http", "ws") + "/ws"
    try:
        captain = await create_room(ws_url, "甲")
        clients = [captain]
        for nick in ("乙", "丙", "丁"):
            clients.append(await join_room(ws_url, captain.room_code, nick))
        for c in clients:
            await c.collect(0.1)
        await captain.send("game:start")
        for c in clients:
            m = await c.wait_for("game:started")
            c.my_room_no = m["yourRoomNo"]
            c.room_nos = m["roomNos"]
            c.nicknames = m["nicknames"]
        for c in clients:
            await c.wait_for("phase:changed", pred=lambda m: m.get("phase") == "PHASE1")

        a, b, c_, d = clients
        await a.send("phase1:ask", targetRoomNo=b.my_room_no, text="问一句")
        for cl in (b, c_, d):
            await cl.send("phase1:skip")
        q = await b.wait_for("phase2:nextQuestion")
        await b.send("phase2:answer", questionId=q["questionId"], text="答一句")
        for cl in clients:
            await cl.wait_for("phase:changed", pred=lambda m: m.get("phase") == "PHASE3")

        for cl in clients:
            await cl.send("phase3:confirm")
        await asyncio.sleep(1.0)
        for cl in clients:
            msgs = await cl.collect(0.5)
            print(f"== {cl.name} ==")
            for m in msgs:
                print("  ", m.get("type"), json.dumps(m, ensure_ascii=False)[:160])
    finally:
        for cl in clients:
            await cl.close()
        proc.terminate()
        proc.wait(10)


asyncio.run(main())
