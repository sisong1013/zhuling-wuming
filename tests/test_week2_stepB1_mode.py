"""Step B1：模式选择（REAL / PERSONA）与分叉。"""

from __future__ import annotations

import pytest

from helpers import (
    close_all,
    full_room,
    persona_room,
    set_mode,
    start_game,
    state_of,
    wait_phase,
)


async def test_default_mode_is_real(ws_base):
    """默认 REAL，且第 1 周流程不变。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        assert state_of(clients[0])["gameMode"] == "REAL"
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=8)
        st = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("status") == "PLAYING", timeout=6
        )
        assert st["gameMode"] == "REAL"
    finally:
        await close_all(clients)


async def test_captain_can_pick_persona(ws_base):
    """队长在 SETUP 选 PERSONA → 开局进入 CARD_WRITING。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await set_mode(clients[0], "PERSONA")
        assert state_of(clients[0])["gameMode"] == "PERSONA"

        await start_game(clients)
        for c in clients:
            await wait_phase(c, "CARD_WRITING", timeout=8)
        st = state_of(clients[0])
        assert st["gameMode"] == "PERSONA"
    finally:
        await close_all(clients)


async def test_invalid_mode_rejected(ws_base):
    """gameMode 只接受 REAL / PERSONA。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await clients[0].send("setup:config", gameMode="TEAM")
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "INVALID_CONFIG"
        assert state_of(clients[0])["gameMode"] == "REAL"
    finally:
        await close_all(clients)


async def test_non_captain_cannot_pick_mode(ws_base):
    """只有队长能改模式。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await clients[1].send("setup:config", gameMode="PERSONA")
        err = await clients[1].wait_for("error", timeout=6)
        assert err["code"] == "NOT_CAPTAIN"
        assert state_of(clients[0])["gameMode"] == "REAL"
    finally:
        await close_all(clients)


async def test_mode_locked_after_start(ws_base):
    """开局后不能改模式。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await start_game(clients)
        await wait_phase(clients[0], "PHASE1", 1, timeout=8)
        await clients[0].send("setup:config", gameMode="PERSONA")
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "WRONG_PHASE"
        assert state_of(clients[0])["gameMode"] == "REAL"
    finally:
        await close_all(clients)


async def test_persona_flow_reaches_playing(ws_base):
    """PERSONA：写卡 → 分配 → 阅读 → 第一幕（PLAYING）。"""
    from helpers import submit_all_cards

    clients = await persona_room(ws_base, ["甲", "乙"], config={"readingSeconds": 30})
    try:
        await submit_all_cards(clients)
        await clients[0].send("captain:startAssign")
        for c in clients:
            await wait_phase(c, "READING", timeout=8)
            await c.send("reading:confirm")
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)
        st = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("status") == "PLAYING", timeout=6
        )
        assert st["phase"] == "PHASE1"
        assert st["gameMode"] == "PERSONA"
    finally:
        await close_all(clients)
