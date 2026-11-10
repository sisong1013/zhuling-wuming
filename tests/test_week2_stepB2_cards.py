"""Step B2：写卡阶段规则。"""

from __future__ import annotations

import pytest

from helpers import (
    close_all,
    full_room,
    persona_room,
    start_game,
    state_of,
    submit_card,
    submit_all_cards,
    wait_phase,
)


async def test_submit_card_ok(ws_base):
    """合法提交 → card:submitted + card:progress 递增。"""
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        ack = await submit_card(clients[0], "雾港的更夫", "每夜两点敲钟，讨厌别人问他为什么不睡。")
        assert ack["ok"] is True
        assert ack["card"]["name"] == "雾港的更夫"

        other = await clients[1].wait_for(
            "card:progress", pred=lambda m: m.get("submitted") == 1, timeout=6
        )
        assert other["total"] == 2
    finally:
        await close_all(clients)


async def test_name_is_trimmed_and_counted(ws_base):
    """卡名去首尾空格后 1–20 字。"""
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        ack = await submit_card(clients[0], "   带空格的卡名   ")
        assert ack["card"]["name"] == "带空格的卡名"

        # 20 字可以，21 字不行
        ok = "边" * 20
        ack2 = await submit_card(clients[1], ok)
        assert ack2["card"]["name"] == ok
    finally:
        await close_all(clients)


async def test_name_too_long_rejected(ws_base):
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        await clients[0].send("card:submit", name="边" * 21, content="内容")
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "CARD_NAME_INVALID"
    finally:
        await close_all(clients)


async def test_name_empty_rejected(ws_base):
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        await clients[0].send("card:submit", name="   ", content="内容")
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "CARD_NAME_INVALID"
    finally:
        await close_all(clients)


async def test_duplicate_name_rejected(ws_base):
    """同房间卡名唯一（含空格差异）。"""
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        await submit_card(clients[0], "同名卡")
        await clients[1].send("card:submit", name="  同名卡 ", content="另一张")
        err = await clients[1].wait_for("error", timeout=6)
        assert err["code"] == "CARD_NAME_TAKEN"
    finally:
        await close_all(clients)


async def test_content_limit(ws_base):
    """卡面 ≤300 字，且不能为空。"""
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        await clients[0].send("card:submit", name="长卡", content="字" * 301)
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "CARD_CONTENT_INVALID"

        await clients[0].send("card:submit", name="长卡", content="字" * 300)
        ack = await clients[0].wait_for("card:submitted", timeout=6)
        assert ack["ok"] is True

        await clients[1].send("card:submit", name="空卡", content="   ")
        err2 = await clients[1].wait_for("error", timeout=6)
        assert err2["code"] == "CARD_CONTENT_INVALID"
    finally:
        await close_all(clients)


async def test_duplicate_submit_rejected(ws_base):
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        await submit_card(clients[0], "第一张")
        await clients[0].send("card:submit", name="第二张", content="内容")
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "ALREADY_SUBMITTED"
    finally:
        await close_all(clients)


async def test_submit_outside_card_phase_rejected(ws_base):
    """未开局（LOBBY）提交 → WRONG_PHASE。"""
    clients = await full_room(ws_base, ["甲", "乙"], config={"gameMode": "PERSONA"})
    try:
        await clients[0].send("card:submit", name="早退的卡", content="内容")
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "WRONG_PHASE"
    finally:
        await close_all(clients)


async def test_start_assign_requires_captain_and_all_cards(ws_base):
    """分配：非队长 / 未交齐都拒绝。"""
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        # 一张都没交
        await clients[0].send("captain:startAssign")
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "CARDS_NOT_READY"

        await submit_all_cards(clients)

        # 非队长
        await clients[1].send("captain:startAssign")
        err2 = await clients[1].wait_for("error", timeout=6)
        assert err2["code"] == "NOT_CAPTAIN"

        # 队长可以
        await clients[0].send("captain:startAssign")
        for c in clients:
            await wait_phase(c, "READING", timeout=8)
    finally:
        await close_all(clients)


async def test_no_hard_timeout_in_card_phase(ws_base):
    """写卡阶段不设硬超时：等 2 秒仍在 CARD_WRITING。"""
    import asyncio

    clients = await persona_room(ws_base, ["甲", "乙"], config={"phase1Seconds": 1})
    try:
        await asyncio.sleep(2.0)
        st = state_of(clients[0])
        assert st["phase"] == "CARD_WRITING"
        assert st["deadline"] is None
    finally:
        await close_all(clients)
