"""Step 3.3：AI 自动写卡（LLM 生成 + 延迟提交 + 合规校验）。"""

from __future__ import annotations

import asyncio
import time

import pytest

from helpers import (
    add_ai,
    ai_config,
    ai_decisions,
    close_all,
    fetch_ai_debug,
    full_room,
    start_game,
    state_of,
    submit_card,
    wait_phase,
)


def _base_of(ws_base: str) -> str:
    return ws_base.replace("ws://", "http://").replace("/ws", "")


async def test_ai_submits_card_automatically(ws_base):
    """AI 自己写卡并提交，进度到齐，卡名/卡面合规。"""
    clients = await full_room(
        ws_base, ["甲"], config=ai_config(gameMode="PERSONA", readingSeconds=30)
    )
    try:
        await add_ai(clients[0], 1)
        await start_game(clients)
        await wait_phase(clients[0], "CARD_WRITING", timeout=10)

        await submit_card(clients[0], "人类的卡", "这是真人类写的卡面。")
        prog = await clients[0].wait_for(
            "card:progress", pred=lambda m: m.get("submitted") == 2, timeout=12
        )
        assert prog["total"] == 2

        debug = await fetch_ai_debug(_base_of(ws_base))
        cards = ai_decisions(debug, "write_card", room=clients[0].room_code)
        assert cards, "AI 写卡没有被记录"
        for card in cards:
            assert 1 <= len(card["name"]) <= 20
            assert 1 <= len(card["content"]) <= 300
            assert card["name"] != "人类的卡"
    finally:
        await close_all(clients)


async def test_two_ai_cards_have_unique_names(ws_base):
    """两个 AI 都能把卡交进去：service 端「卡名唯一」约束下能到 3/3，
    说明撞名时服务端自动换了名字（否则第二张会被 CARD_NAME_TAKEN 挡住）。"""
    clients = await full_room(
        ws_base, ["甲"], config=ai_config(gameMode="PERSONA", readingSeconds=30)
    )
    try:
        await add_ai(clients[0], 2)
        await start_game(clients)
        await wait_phase(clients[0], "CARD_WRITING", timeout=10)

        await submit_card(clients[0], "人类卡", "人类卡面。")
        prog = await clients[0].wait_for(
            "card:progress", pred=lambda m: m.get("submitted") == 3, timeout=20
        )
        assert prog["submitted"] == 3
        assert prog["total"] == 3

        debug = await fetch_ai_debug(_base_of(ws_base))
        cards = ai_decisions(debug, "write_card", room=clients[0].room_code)
        assert len({c["_nickname"] for c in cards}) == 2, cards
    finally:
        await close_all(clients)


async def test_ai_card_submission_is_delayed(ws_base):
    """AI 不会瞬间交卡：提交应晚于写卡阶段开始约 aiCardDelaySeconds。"""
    clients = await full_room(
        ws_base,
        ["甲", "乙"],
        config=ai_config(gameMode="PERSONA", readingSeconds=30, aiCardDelaySeconds=1.5),
    )
    try:
        await add_ai(clients[0], 1)
        await start_game(clients)
        await wait_phase(clients[0], "CARD_WRITING", timeout=10)
        started = time.time()

        await submit_card(clients[0], "甲的卡", "甲卡面。")
        await submit_card(clients[1], "乙的卡", "乙卡面。")

        prog = await clients[0].wait_for(
            "card:progress", pred=lambda m: m.get("submitted") == 3, timeout=15
        )
        elapsed = time.time() - started
        assert prog["total"] == 3
        assert elapsed >= 1.0, f"AI 交卡太快了（{elapsed:.2f}s），延迟没生效"
    finally:
        await close_all(clients)


async def test_ai_thinking_broadcast_for_card(ws_base):
    """写卡时会广播 ai:thinking（kind=write_card）。"""
    clients = await full_room(
        ws_base, ["甲"], config=ai_config(gameMode="PERSONA", readingSeconds=30)
    )
    try:
        await add_ai(clients[0], 1)
        await start_game(clients)
        await wait_phase(clients[0], "CARD_WRITING", timeout=10)
        think = await clients[0].wait_for(
            "ai:thinking", pred=lambda m: m.get("kind") == "write_card", timeout=10
        )
        assert think["nickname"]
        assert state_of(clients[0])["phase"] == "CARD_WRITING"
    finally:
        await close_all(clients)
