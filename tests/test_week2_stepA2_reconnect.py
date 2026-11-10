"""Step A2：断线重连 / 保留座位 / 在线人数 / 心跳。"""

from __future__ import annotations

import asyncio

import pytest

from helpers import (
    close_all,
    full_room,
    my_token,
    reconnect,
    skip_round,
    start_game,
    state_of,
    wait_phase,
)


def _player_state(state: dict, nickname: str) -> dict:
    for p in state["players"]:
        if p["nickname"] == nickname:
            return p
    raise AssertionError(f"{nickname} 不在 room:state 里：{[p['nickname'] for p in state['players']]}")


async def test_reconnect_token_issued_per_player(ws_base):
    """入座即发 token，且每人不同。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        t1 = await my_token(clients[0])
        t2 = await my_token(clients[1])
        assert t1 and t2 and t1 != t2
        assert len(t1) >= 8
    finally:
        await close_all(clients)


async def test_disconnect_keeps_seat_and_marks_offline(ws_base):
    """断线：座位保留，connected=0，房间广播更新。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await clients[1].close()
        st = await clients[0].wait_for(
            "room:state",
            pred=lambda m: any(
                p["nickname"] == "乙" and not p["connected"] for p in m["players"]
            ),
            timeout=8,
        )
        assert st["count"] == 2  # 座位没被踢
        assert st["onlineCount"] == 1
        assert _player_state(st, "乙")["connected"] is False
    finally:
        await close_all(clients)


async def test_reconnect_restores_identity_and_snapshot(ws_base):
    """凭 token 重连：恢复身份 + 完整快照 + 广播在线。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    token = await my_token(clients[1])
    try:
        await start_game(clients)
        await wait_phase(clients[1], "PHASE1", 1, timeout=8)
        room_no = state_of(clients[1])["you"]["roomNo"]
        room_code = clients[1].room_code
        player_id = clients[1].player_id

        await clients[1].close()
        await clients[0].wait_for(
            "room:state",
            pred=lambda m: any(
                p["nickname"] == "乙" and not p["connected"] for p in m["players"]
            ),
            timeout=8,
        )

        back = await reconnect(ws_base, room_code, player_id, token)
        try:
            ok = await back.wait_for("reconnect:ok", timeout=8)
            snap = ok["snapshot"]
            assert snap["status"] == "PLAYING"
            assert snap["phase"] == "PHASE1"
            assert snap["yourRoomNo"] == room_no
            assert snap["gameMode"] == "REAL"
            assert len(snap["players"]) == 2
            assert snap["board"] == {}

            st = await clients[0].wait_for(
                "room:state",
                pred=lambda m: any(
                    p["nickname"] == "乙" and p["connected"] for p in m["players"]
                ),
                timeout=8,
            )
            assert st["onlineCount"] == 2
        finally:
            await back.close()
    finally:
        await close_all(clients)


async def test_reconnect_with_bad_token_fails(ws_base):
    """token 不对 → reconnect:failed。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        probe = await reconnect(ws_base, clients[1].room_code, clients[1].player_id, "bogus-token")
        try:
            fail = await probe.wait_for("reconnect:failed", timeout=6)
            assert fail["code"] == "RECONNECT_INVALID"
        finally:
            await probe.close()
    finally:
        await close_all(clients)


async def test_reconnect_unknown_room_fails(ws_base):
    """房间不存在 → reconnect:failed。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        probe = await reconnect(ws_base, "000000", clients[1].player_id, "whatever")
        try:
            fail = await probe.wait_for("reconnect:failed", timeout=6)
            assert fail["code"] == "RECONNECT_INVALID"
        finally:
            await probe.close()
    finally:
        await close_all(clients)


async def test_offline_player_does_not_block_phase1(ws_base):
    """断线玩家不阻塞「全员行动」。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=8)

        await clients[1].close()
        await clients[0].wait_for(
            "room:state",
            pred=lambda m: any(
                p["nickname"] == "乙" and not p["connected"] for p in m["players"]
            ),
            timeout=8,
        )

        # 只剩甲在线：甲一人行动即可推进到第二幕
        await clients[0].send("phase1:skip")
        await wait_phase(clients[0], "PHASE2", 1, timeout=10)
    finally:
        await close_all(clients)


async def test_heartbeat_marks_player_offline(ws_base):
    """服务端 60s 无消息判掉线（测试把阈值压到 1s）。"""
    # 阈值压到 2s；整套跑的时候机器忙，判定窗口给足，避免偶发假失败
    clients = await full_room(ws_base, ["甲", "乙"], config={"heartbeatSeconds": 2})
    try:
        # 乙保持心跳，甲彻底沉默
        deadline = asyncio.get_event_loop().time() + 30
        found = None
        while asyncio.get_event_loop().time() < deadline:
            await clients[1].send("ping", t=1)
            await clients[1].wait_for("pong", timeout=5)
            await asyncio.sleep(0.5)
            try:
                st = await clients[1].wait_for(
                    "room:state",
                    pred=lambda m: any(
                        p["nickname"] == "甲" and not p["connected"] for p in m["players"]
                    ),
                    timeout=1.2,
                )
                found = st
                break
            except asyncio.TimeoutError:
                continue
        assert found is not None, "服务端没有按心跳阈值把甲判掉线"
        assert _player_state(found, "乙")["connected"] is True
        assert found["onlineCount"] == 1
    finally:
        await close_all(clients)
