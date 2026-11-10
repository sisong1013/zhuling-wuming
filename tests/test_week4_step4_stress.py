"""Step 4.4：8 路并发 WebSocket 压力测试（阶段与计时器不崩）。"""

from __future__ import annotations

import asyncio
import time

import pytest

from helpers import WsClient, close_all, create_room, join_room, wait_phase

PLAYERS = 8


async def _build_room(ws_base, config: dict):
    captain = await create_room(ws_base, "甲0")
    clients = [captain]
    for i in range(1, PLAYERS):
        clients.append(await join_room(ws_base, captain.room_code, f"甲{i}"))
    await captain.send("setup:config", **config)
    msgs = await captain.collect(0.6)
    assert all(m.get("type") != "error" for m in msgs), msgs
    return clients


async def test_eight_concurrent_clients_two_rounds(ws_base):
    """8 个连接同时玩两轮：阶段照常推进，计时器不炸。"""
    clients = await _build_room(
        ws_base,
        {"phase1Seconds": 20, "phase2Seconds": 10, "phase3Seconds": 10, "forcedSubmitRound": 9},
    )
    try:
        await clients[0].send("game:start")
        for c in clients:
            msg = await c.wait_for("game:started", timeout=15)
            c.my_room_no = msg["yourRoomNo"]
            c.room_nos = msg["roomNos"]
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=20)

        # 两轮：全员略过 → 第三幕 → 确认 → 下一轮
        for round_no in (1, 2):
            for c in clients:
                await c.send("phase1:skip")
            for c in clients:
                await wait_phase(c, "PHASE3", round_no, timeout=30)
            for c in clients:
                await c.send("phase3:confirm")
            if round_no == 1:
                for c in clients:
                    await wait_phase(c, "PHASE1", 2, timeout=30)

        # 收尾：确认没有 error 帧堆积
        errors = []
        for c in clients:
            for m in await c.collect(0.2):
                if m.get("type") == "error":
                    errors.append(m)
        assert errors == [], f"并发下出现错误帧：{errors}"
    finally:
        await close_all(clients)


async def test_timers_do_not_double_fire(ws_base):
    """阶段超时只推进一次（避免计时器重复触发导致跳阶段）。"""
    clients = await _build_room(
        ws_base, {"phase1Seconds": 1, "phase2Seconds": 2, "phase3Seconds": 1}
    )
    try:
        await clients[0].send("game:start")
        for c in clients:
            await c.wait_for("game:started", timeout=15)

        # 谁都不动，让第一幕超时；收集 7 秒内收到的全部 phase:changed
        msgs = await clients[0].collect(7)
        seq = [m["phase"] for m in msgs if m.get("type") == "phase:changed"]
        assert seq, f"超时后没有任何阶段推进：{[m.get('type') for m in msgs]}"
        # 允许 PHASE1 → PHASE2 → PHASE3 → PHASE1（下一轮），但不能出现「同阶段重复跳」
        for a, b in zip(seq, seq[1:]):
            assert a != b, f"阶段重复跳转：{seq}"
    finally:
        await close_all(clients)


async def test_reconnect_storm_does_not_break_room(ws_base):
    """反复断线/重连后，房间仍可正常开局。"""
    clients = await _build_room(ws_base, {"phase1Seconds": 20})
    tokens = {}
    try:
        for c in clients:
            from helpers import my_token

            tokens[c.name] = await my_token(c)

        victim = clients[-1]
        for _ in range(3):
            await victim.close()
            back = await WsClient.connect(ws_base, "reconnect")
            back.player_id = victim.player_id
            back.room_code = victim.room_code
            await back.send(
                "conn:reconnect",
                roomCode=victim.room_code,
                playerId=victim.player_id,
                token=tokens[victim.name],
            )
            await back.wait_for("reconnect:ok", timeout=10)
            await back.close()

        await clients[0].send("game:start")
        await clients[0].wait_for("game:started", timeout=15)
        await wait_phase(clients[0], "PHASE1", 1, timeout=20)
    finally:
        await close_all(clients)
