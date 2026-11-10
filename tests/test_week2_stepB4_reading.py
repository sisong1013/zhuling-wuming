"""Step B4：阅读阶段（persona:assigned 内容 + 确认 + 超时）。"""

from __future__ import annotations

import asyncio
import time

import pytest

from helpers import (
    assign_cards,
    close_all,
    collect_assigned,
    persona_room,
    state_of,
    submit_all_cards,
    wait_phase,
)


async def _reach_reading(ws_base, names, config=None):
    clients = await persona_room(ws_base, names, config=config)
    cards = await submit_all_cards(clients)
    await assign_cards(clients[0])
    for c in clients:
        await wait_phase(c, "READING", timeout=10)
    return clients, cards


async def test_persona_assigned_payload(ws_base):
    """persona:assigned：本人编号、卡面、打乱的卡名表、deadline。"""
    clients, cards = await _reach_reading(ws_base, ["甲", "乙", "丙"], config={"readingSeconds": 30})
    try:
        assigned = await collect_assigned(clients)
        for c in clients:
            msg = assigned[c.player_id]
            assert msg["yourRoomNo"] in (1, 2, 3)
            assert sorted(msg["roomNos"]) == [1, 2, 3]
            assert msg["yourCard"]["name"] in cards
            assert msg["yourCard"]["content"]
            assert sorted(msg["cardNames"]) == sorted(cards)
            assert msg["deadline"] > time.time() - 5
            assert len(msg["cardNames"]) == 3
    finally:
        await close_all(clients)


async def test_card_names_are_shuffled_not_author_order(ws_base):
    """卡名表必须打乱，至少不能恒等于作者顺序。"""
    clients = await persona_room(ws_base, ["甲", "乙", "丙", "丁"])
    try:
        cards = await submit_all_cards(clients, prefix="序")
        await assign_cards(clients[0])
        for c in clients:
            await wait_phase(c, "READING", timeout=10)
        assigned = await collect_assigned(clients)
        orders = [tuple(m["cardNames"]) for m in assigned.values()]
        assert any(list(o) != cards for o in orders), f"卡名表看起来没打乱：{orders}"
    finally:
        await close_all(clients)


async def test_no_mapping_leaked_in_persona_assigned(ws_base):
    """payload 里不能有「卡→作者」或「卡→编号」映射字段。"""
    clients, _ = await _reach_reading(ws_base, ["甲", "乙"])
    try:
        assigned = await collect_assigned(clients)
        allowed = {
            "type",
            "yourRoomNo",
            "roomNos",
            "yourCard",
            "cardNames",
            "deadline",
        }
        for c in clients:
            msg = assigned[c.player_id]
            assert set(msg) <= allowed, f"多了字段：{set(msg) - allowed}"
            assert set(msg["yourCard"]) == {"name", "content"}
            blob = str(msg)
            for other in clients:
                if other is c:
                    continue
                # 别人的昵称不该出现在我的 persona:assigned 里
                assert other.name not in blob
    finally:
        await close_all(clients)


async def test_reading_confirm_progress_and_start(ws_base):
    """reading:progress 递增；全员确认进入第一幕。"""
    clients, _ = await _reach_reading(ws_base, ["甲", "乙"], config={"readingSeconds": 30})
    try:
        await collect_assigned(clients)
        await clients[0].send("reading:confirm")
        prog = await clients[1].wait_for(
            "reading:progress", pred=lambda m: m.get("confirmed") == 1, timeout=8
        )
        assert prog["total"] == 2

        await clients[1].send("reading:confirm")
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)
    finally:
        await close_all(clients)


async def test_double_confirm_rejected(ws_base):
    clients, _ = await _reach_reading(ws_base, ["甲", "乙"], config={"readingSeconds": 30})
    try:
        await collect_assigned(clients)
        await clients[0].send("reading:confirm")
        await clients[0].send("reading:confirm")
        err = await clients[0].wait_for("error", timeout=8)
        assert err["code"] == "ALREADY_CONFIRMED"
    finally:
        await close_all(clients)


async def test_reading_timeout_starts_round(ws_base):
    """阅读超时（1s）自动进入第一幕。"""
    clients, _ = await _reach_reading(ws_base, ["甲", "乙"], config={"readingSeconds": 1})
    try:
        await collect_assigned(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=12)
    finally:
        await close_all(clients)


async def test_confirm_outside_reading_rejected(ws_base):
    """未分配前确认 → WRONG_PHASE。"""
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        await clients[0].send("reading:confirm")
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "WRONG_PHASE"
    finally:
        await close_all(clients)
