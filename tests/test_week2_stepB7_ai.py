"""Step B7：AI 接口预留（占位实现）+ AI 玩家参与全流程。"""

from __future__ import annotations

import asyncio

import pytest

from helpers import (
    assign_cards,
    card_board,
    close_all,
    collect_assigned,
    full_room,
    set_mode,
    start_game,
    state_of,
    submit_all_cards,
    wait_phase,
)


def _ai_names(clients):
    return [p["nickname"] for p in state_of(clients[0])["players"]]


def test_generate_ai_card_stub():
    from server import ai

    card = ai.generate_ai_card()
    assert set(card) == {"name", "content"}
    assert isinstance(card["name"], str) and card["name"]
    assert isinstance(card["content"], str) and card["content"]
    assert len(card["name"]) <= 20


def test_ai_answer_stub():
    from server import ai
    from server.models import PersonaCard

    card = PersonaCard(id="c1", game_id="123456", author_id="p1", name="摆钟店的学徒", content="…")
    out = ai.ai_answer_as_persona(card, "现在几点？")
    assert isinstance(out, str) and out
    assert "摆钟店的学徒" in out
    # 也接受 dict 形式（第 3 周可能直接传 LLM 返回的 JSON）
    out2 = ai.ai_answer_as_persona({"name": "雨天的抄写员"}, "怎么写？")
    assert "雨天的抄写员" in out2


async def test_captain_can_add_ai(ws_base):
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await clients[0].send("captain:addAi", nickname="木偶·壹")
        st = await clients[1].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)
        assert "木偶·壹" in [p["nickname"] for p in st["players"]]
        assert st["onlineCount"] == 3
    finally:
        await close_all(clients)


async def test_non_captain_cannot_add_ai(ws_base):
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await clients[1].send("captain:addAi", nickname="偷来的木偶")
        err = await clients[1].wait_for("error", timeout=6)
        assert err["code"] == "NOT_CAPTAIN"
    finally:
        await close_all(clients)


async def test_ai_submits_card_automatically(ws_base):
    """AI 也会写卡：不用真人替它提交。"""
    clients = await full_room(ws_base, ["甲", "乙"], config={"gameMode": "PERSONA"})
    try:
        await clients[0].send("captain:addAi", nickname="木偶·壹")
        await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)

        await start_game(clients)
        for c in clients:
            await wait_phase(c, "CARD_WRITING", timeout=10)

        # 真人各交一张 → 进度应该直接到 3/3（AI 自己交过了）
        await submit_all_cards(clients)
        prog = await clients[0].wait_for(
            "card:progress", pred=lambda m: m.get("submitted") == 3, timeout=10
        )
        assert prog["total"] == 3
    finally:
        await close_all(clients)


async def test_ai_participates_in_assignment(ws_base):
    """AI 的卡会被真人拿到，AI 也拿到真人的卡（作者 != 自己）。"""
    clients = await full_room(ws_base, ["甲", "乙"], config={"gameMode": "PERSONA"})
    try:
        await clients[0].send("captain:addAi", nickname="木偶·壹")
        await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "CARD_WRITING", timeout=10)

        human_cards = await submit_all_cards(clients)
        await clients[0].wait_for(
            "card:progress", pred=lambda m: m.get("submitted") == 3, timeout=10
        )
        await assign_cards(clients[0])
        for c in clients:
            await wait_phase(c, "READING", timeout=12)
        await collect_assigned(clients)

        got = [c.assigned_card["name"] for c in clients]
        # 两个真人拿到的卡必须不同，且都不能是自己写的
        assert len(set(got)) == 2, f"真人拿到了重复的卡：{got}"
        assert got[0] != human_cards[0]
        assert got[1] != human_cards[1]
        # AI 的卡必然在其中之一（3 人 3 卡，错位后必然交叉）
        ai_card_assigned_to_human = any(g not in human_cards for g in got)
        human_card_held_by_ai = any(h not in got for h in human_cards)
        assert ai_card_assigned_to_human and human_card_held_by_ai, (got, human_cards)
    finally:
        await close_all(clients)


async def test_ai_acts_automatically_in_phase1(ws_base):
    """AI 会自动行动，不阻塞「全员行动」。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await clients[0].send("captain:addAi", nickname="木偶·壹")
        await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)

        # 两个真人放弃，AI 若不自行动则永远进不了第二幕
        for c in clients:
            await c.send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE2", 1, timeout=15)
    finally:
        await close_all(clients)


async def test_ai_answers_question_automatically(ws_base):
    """问 AI 玩家 → 进第二幕后 AI 自动作答（占位回答里带卡名）。"""
    clients = await full_room(ws_base, ["甲", "乙"], config={"gameMode": "PERSONA"})
    try:
        await clients[0].send("captain:addAi", nickname="木偶·壹")
        await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "CARD_WRITING", timeout=10)
        await submit_all_cards(clients)
        await clients[0].wait_for(
            "card:progress", pred=lambda m: m.get("submitted") == 3, timeout=10
        )
        await assign_cards(clients[0])
        for c in clients:
            await wait_phase(c, "READING", timeout=12)
        await collect_assigned(clients)
        for c in clients:
            await c.send("reading:confirm")
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=12)

        # AI 的编号 = 编号表里两个真人没有的那个
        human_nos = {c.my_room_no for c in clients}
        ai_no = ([n for n in [1, 2, 3] if n not in human_nos] or [None])[0]
        assert ai_no is not None

        await clients[0].send("phase1:ask", targetRoomNo=ai_no, text="你是哪张卡？")
        # 真人都放弃本轮 → 进第二幕，AI 会自动回答
        await clients[1].send("phase1:skip")
        pub = await clients[0].wait_for(
            "answer:public",
            pred=lambda m: m.get("status") in ("ANSWERED", "TIMEOUT"),
            timeout=20,
        )
        assert pub["status"] == "ANSWERED", "AI 应该自动回答而不是超时"
        assert pub["answer"]
    finally:
        await close_all(clients)
