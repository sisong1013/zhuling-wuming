"""Step A3：room:state 广播契约 + 变更广播。"""

from __future__ import annotations

import pytest

from helpers import (
    close_all,
    create_room,
    full_room,
    join_room,
    my_token,
    reconnect,
    start_game,
    state_of,
    wait_phase,
)

REQUIRED_TOP = {
    "type",
    "roomCode",
    "status",
    "phase",
    "gameMode",
    "visibility",
    "round",
    "captainId",
    "players",
    "maxPlayers",
    "config",
}
REQUIRED_PLAYER = {"id", "nickname", "isCaptain", "connected"}
REQUIRED_CONFIG = {
    "phase1Seconds",
    "phase2Seconds",
    "phase3Seconds",
    "readingSeconds",
    "forcedSubmitRound",
    "maxPlayers",
    "minPlayers",
    "cooldownRounds",
}


async def test_room_state_has_all_required_fields(ws_base):
    """room:state 顶层 + players[] + config 字段齐全。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        st = state_of(clients[0])
        assert REQUIRED_TOP <= set(st), REQUIRED_TOP - set(st)
        assert st["status"] == "LOBBY"
        assert st["gameMode"] == "REAL"
        assert st["visibility"] == "PUBLIC"
        assert st["maxPlayers"] == 8
        assert REQUIRED_CONFIG <= set(st["config"]), REQUIRED_CONFIG - set(st["config"])
        for p in st["players"]:
            assert REQUIRED_PLAYER <= set(p), REQUIRED_PLAYER - set(p)
            assert isinstance(p["connected"], bool)
            assert isinstance(p["isCaptain"], bool)
    finally:
        await close_all(clients)


async def test_state_broadcast_on_join(ws_base):
    """有人加入 → 广播新状态（count 变化 + 新玩家出现）。"""
    captain = await create_room(ws_base, "甲")
    guest = await join_room(ws_base, captain.room_code, "乙")
    try:
        st2 = await captain.wait_for(
            "room:state", pred=lambda m: m.get("count") == 2, timeout=8
        )
        assert {p["nickname"] for p in st2["players"]} == {"甲", "乙"}
        assert st2["onlineCount"] == 2
        assert st2["captainId"] == captain.player_id
    finally:
        await close_all([captain, guest])


async def test_state_broadcast_on_join_and_disconnect(ws_base):
    """加入 / 断线 / 重连各广播一次状态。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        assert state_of(clients[0])["count"] == 2
        token = await my_token(clients[1])
        room_code, player_id = clients[1].room_code, clients[1].player_id

        await clients[1].close()
        off = await clients[0].wait_for(
            "room:state",
            pred=lambda m: any(p["nickname"] == "乙" and not p["connected"] for p in m["players"]),
            timeout=8,
        )
        assert off["status"] == "LOBBY"

        back = await reconnect(ws_base, room_code, player_id, token)
        try:
            on = await clients[0].wait_for(
                "room:state",
                pred=lambda m: any(p["nickname"] == "乙" and p["connected"] for p in m["players"]),
                timeout=8,
            )
            assert on["onlineCount"] == 2
        finally:
            await back.close()
    finally:
        await close_all(clients)


async def test_state_has_no_number_mapping(ws_base):
    """别人的编号永不出现在 room:state 里。"""
    clients = await full_room(ws_base, ["甲", "乙", "丙"])
    try:
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)
        for c in clients:
            st = await c.wait_for("room:state", pred=lambda m: m.get("status") == "PLAYING", timeout=6)
            for p in st["players"]:
                assert "roomNo" not in p
            others = [p for p in st["players"] if p["id"] != st["you"]["id"]]
            assert others, "应该能看到别人"
            assert all("roomNo" not in p for p in others)
            assert st["you"]["roomNo"] in (1, 2, 3)
    finally:
        await close_all(clients)


async def test_phase_field_tracks_mode_flow(ws_base):
    """PERSONA：phase/status 随写卡、阅读推进。"""
    from helpers import persona_room, submit_all_cards, wait_phase as _wp

    clients = await persona_room(ws_base, ["甲", "乙"], config={"readingSeconds": 30})
    try:
        st = state_of(clients[0])
        assert st["phase"] == "CARD_WRITING"
        assert st["status"] == "CARD_WRITING"
        assert st["cards"] == {"submitted": 0, "assigned": False}

        await submit_all_cards(clients)
        st2 = await clients[0].wait_for(
            "room:state", pred=lambda m: (m.get("cards") or {}).get("submitted") == 2, timeout=8
        )
        assert st2["cards"]["submitted"] == 2

        await clients[0].send("captain:startAssign")
        await _wp(clients[0], "READING", timeout=8)
        st3 = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("status") == "READING", timeout=8
        )
        assert st3["cards"]["assigned"] is True
    finally:
        await close_all(clients)
