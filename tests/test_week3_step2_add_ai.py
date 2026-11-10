"""Step 3.2：等待室添加 AI（room:addAI）。"""

from __future__ import annotations

import pytest

from helpers import (
    add_ai,
    add_ai as _add_ai,
    close_all,
    create_room,
    full_room,
    join_room,
    start_game,
    state_of,
    wait_phase,
)

PRESET = {"星辉剑士", "折纸诗人", "紫电琴师", "雾巷画匠", "琉璃小丑", "铁皮报幕员", "青苔占星师", "落雪的书吏"}


async def test_captain_adds_two_ai(ws_base):
    """队长加 2 个 AI：名单出现、isAi=true、connected=true。"""
    clients = await full_room(ws_base, ["甲"])
    try:
        ack = await add_ai(clients[0], 2)
        assert ack["count"] == 3
        assert len(ack["players"]) == 2

        st = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("count") == 3, timeout=8
        )
        bots = [p for p in st["players"] if p.get("isAi")]
        assert len(bots) == 2
        assert all(p["connected"] is True for p in bots)
        assert {p["nickname"] for p in bots} <= PRESET
        assert len({p["nickname"] for p in bots}) == 2
        assert st["onlineCount"] == 3
    finally:
        await close_all(clients)


async def test_non_captain_cannot_add_ai(ws_base):
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await clients[1].send("room:addAI", count=1)
        err = await clients[1].wait_for("error", timeout=6)
        assert err["code"] == "NOT_CAPTAIN"
        assert state_of(clients[0])["count"] == 2
    finally:
        await close_all(clients)


async def test_count_validation(ws_base):
    """一次只能 1–2 个，且必须是整数。"""
    clients = await full_room(ws_base, ["甲"])
    try:
        await clients[0].send("room:addAI", count=3)
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "INVALID_PAYLOAD"

        await clients[0].send("room:addAI", count="两个")
        err2 = await clients[0].wait_for("error", timeout=6)
        assert err2["code"] == "INVALID_PAYLOAD"
    finally:
        await close_all(clients)


async def test_cannot_add_ai_after_start(ws_base):
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await start_game(clients)
        await wait_phase(clients[0], "PHASE1", 1, timeout=8)
        await clients[0].send("room:addAI", count=1)
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "WRONG_PHASE"
    finally:
        await close_all(clients)


async def test_room_capacity_guard(ws_base):
    """2 真人 + maxPlayers=3 时，加 2 个 AI 会被挡。"""
    clients = await full_room(ws_base, ["甲", "乙"], config={"maxPlayers": 3})
    try:
        await clients[0].send("room:addAI", count=2)
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "ROOM_FULL"
    finally:
        await close_all(clients)


async def test_ai_shows_up_in_ai_thinking_during_game(ws_base):
    """开局后 AI 会广播「正在想」——说明它作为玩家在跑。"""
    from helpers import ai_config

    clients = await full_room(
        ws_base, ["甲"], config=ai_config(gameMode="PERSONA", readingSeconds=30)
    )
    try:
        await add_ai(clients[0], 1)
        await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 2, timeout=8)
        await start_game(clients)
        await wait_phase(clients[0], "CARD_WRITING", timeout=10)

        think = await clients[0].wait_for("ai:thinking", timeout=10)
        assert think["kind"] in ("write_card", "phase1", "answer")
        assert think["nickname"]
    finally:
        await close_all(clients)
