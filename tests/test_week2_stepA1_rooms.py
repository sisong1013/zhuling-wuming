"""Step A1：多房间并存 + 房间生命周期。"""

from __future__ import annotations

import asyncio

import pytest

from helpers import (
    close_all,
    full_room,
    my_token,
    persona_room,
    reconnect,
    start_game,
    state_of,
    submit_all_cards,
    wait_phase,
)


async def test_two_rooms_do_not_interfere(ws_base):
    """A 房间开局后，B 房间没有任何阶段推进（仍是 LOBBY 快照）。"""
    room_a = await full_room(ws_base, ["甲A", "乙A"])
    room_b = await full_room(ws_base, ["甲B", "乙B"])
    try:
        assert room_a[0].room_code != room_b[0].room_code
        st_b_before = state_of(room_b[0])
        assert st_b_before["status"] == "LOBBY"

        await start_game(room_a)
        for c in room_a:
            await wait_phase(c, "PHASE1", 1, timeout=8)

        # B 房间：窗口内收不到任何 phase:changed
        for c in room_b:
            msgs = await c.collect(0.5)
            assert all(m.get("type") != "phase:changed" for m in msgs), msgs
        assert st_b_before["roomCode"] == room_b[0].room_code
        assert st_b_before["count"] == 2
    finally:
        await close_all(room_a + room_b)


async def test_rooms_have_isolated_players_and_numbers(ws_base):
    """两个房间各自的玩家、编号互不可见。"""
    room_a = await full_room(ws_base, ["甲A", "乙A"])
    room_b = await full_room(ws_base, ["甲B", "乙B"])
    try:
        st_b = state_of(room_b[0])
        assert {p["nickname"] for p in st_b["players"]} == {"甲B", "乙B"}
        # 别人的编号不下发（players[] 里根本没有 roomNo 字段）
        assert all("roomNo" not in p for p in st_b["players"])

        await start_game(room_a)
        for c in room_a:
            await wait_phase(c, "PHASE1", 1, timeout=8)

        # 开局后 B 房间依然没有任何编号/阶段变化
        for c in room_b:
            msgs = await c.collect(0.4)
            assert all(m.get("type") != "phase:changed" for m in msgs)
            assert all((m.get("you") or {}).get("roomNo") is None for m in msgs)
    finally:
        await close_all(room_a + room_b)


async def test_lifecycle_status_real(ws_base):
    """REAL：LOBBY → PLAYING。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        st = state_of(clients[0])
        assert st["status"] == "LOBBY"

        await start_game(clients)
        await wait_phase(clients[0], "PHASE1", 1, timeout=8)
        st_playing = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("status") == "PLAYING", timeout=5
        )
        assert st_playing["phase"] == "PHASE1"
    finally:
        await close_all(clients)


async def test_lifecycle_status_persona(ws_base):
    """PERSONA：CARD_WRITING → READING → PLAYING。"""
    clients = await persona_room(ws_base, ["甲", "乙"], config={"readingSeconds": 30})
    try:
        st = state_of(clients[0])
        assert st["gameMode"] == "PERSONA"

        await submit_all_cards(clients)
        await clients[0].send("captain:startAssign")
        for c in clients:
            await wait_phase(c, "READING", timeout=8)
        st2 = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("status") == "READING", timeout=5
        )
        assert st2["phase"] == "READING"
    finally:
        await close_all(clients)


async def test_over_room_is_recycled(ws_base):
    """结束后保留一段时间可复盘，超时后回收（重连失败）。"""
    clients = await full_room(ws_base, ["甲", "乙"], config={"overRetentionSeconds": 1})
    try:
        tokens = {c.name: await my_token(c) for c in clients}
        await start_game(clients)
        board = {str(c.my_room_no): c.name for c in clients}
        await clients[0].send("phase1:submit", board=board)
        await clients[0].wait_for("game:over", timeout=6)

        # 复盘期内还能重连
        probe = await reconnect(ws_base, clients[1].room_code, clients[1].player_id, tokens["乙"])
        try:
            ok = await probe.wait_for("reconnect:ok", timeout=5)
            assert ok["snapshot"]["status"] == "OVER"
        finally:
            await probe.close()

        # 回收后房间消失
        await asyncio.sleep(2.6)
        gone = await reconnect(ws_base, clients[1].room_code, clients[1].player_id, tokens["乙"])
        try:
            fail = await gone.wait_for("reconnect:failed", timeout=6)
            assert fail["code"] == "RECONNECT_INVALID"
        finally:
            await gone.close()
    finally:
        await close_all(clients)


async def test_multiple_rooms_playing_at_once(ws_base):
    """三个房间可以同时处于 PLAYING。"""
    a = await full_room(ws_base, ["甲1", "乙1"])
    b = await full_room(ws_base, ["甲2", "乙2"])
    c = await full_room(ws_base, ["甲3", "乙3"])
    try:
        for room in (a, b, c):
            await start_game(room)
        for room in (a, b, c):
            for cl in room:
                await wait_phase(cl, "PHASE1", 1, timeout=10)
        for room in (a, b, c):
            st = await room[0].wait_for(
                "room:state", pred=lambda m: m.get("status") == "PLAYING", timeout=6
            )
            assert st["status"] == "PLAYING"
            assert st["count"] == 2
    finally:
        await close_all(a + b + c)
