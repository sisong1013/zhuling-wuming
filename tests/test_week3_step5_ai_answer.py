"""Step 3.5：AI 第二幕扮演作答。"""

from __future__ import annotations

import re
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


async def _persona_with_ai(ws_base):
    """PERSONA：1 真人 + 1 AI，跑到第一幕。"""
    clients = await full_room(
        ws_base,
        ["甲"],
        config=ai_config(gameMode="PERSONA", readingSeconds=30, phase2Seconds=4),
    )
    await add_ai(clients[0], 1)
    await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 2, timeout=8)
    await start_game(clients)
    await wait_phase(clients[0], "CARD_WRITING", timeout=10)

    await submit_card(clients[0], "人类的卡", "人类写的卡面。")
    await clients[0].wait_for("card:progress", pred=lambda m: m.get("submitted") == 2, timeout=15)
    await clients[0].send("captain:startAssign")
    await wait_phase(clients[0], "READING", timeout=12)
    await clients[0].send("reading:confirm")
    await wait_phase(clients[0], "PHASE1", 1, timeout=20)
    return clients


async def _ai_room_no(base: str, room_code: str) -> int:
    debug = await fetch_ai_debug(base)
    for ai in debug["ais"]:
        if ai["room"] == room_code:
            return ai["roomNo"]
    raise AssertionError("找不到房间里的 AI")


async def test_ai_answers_question(ws_base):
    """真人问 AI → 第二幕 AI 按人设作答，答案非空且合规。"""
    clients = await _persona_with_ai(ws_base)
    base = _base_of(ws_base)
    try:
        ai_no = await _ai_room_no(base, clients[0].room_code)
        await clients[0].send("phase1:ask", targetRoomNo=ai_no, text="你昨晚在哪盏灯下？")
        # 真人放弃本轮 → 进第二幕，AI 自己作答
        started = time.time()
        pub = await clients[0].wait_for(
            "answer:public",
            pred=lambda m: m.get("status") in ("ANSWERED", "TIMEOUT"),
            timeout=25,
        )
        elapsed = time.time() - started
        assert pub["status"] == "ANSWERED", "AI 应该作答而不是超时"
        text = pub["answer"]
        assert isinstance(text, str) and text.strip()
        assert len(text) <= 300
        assert elapsed >= 0.1, "打字延迟没生效"

        think = [m for m in await clients[0].collect(0.1)]
        assert all(m.get("type") != "error" for m in think)
    finally:
        await close_all(clients)


async def test_ai_answer_does_not_leak_own_number(ws_base):
    """回答里不能出现自己的编号（防自曝）。"""
    clients = await _persona_with_ai(ws_base)
    base = _base_of(ws_base)
    try:
        ai_no = await _ai_room_no(base, clients[0].room_code)
        await clients[0].send("phase1:ask", targetRoomNo=ai_no, text="你是几号？")
        pub = await clients[0].wait_for(
            "answer:public",
            pred=lambda m: m.get("status") in ("ANSWERED", "TIMEOUT"),
            timeout=25,
        )
        assert pub["status"] == "ANSWERED"
        assert not re.search(rf"(?<!\d){ai_no}\s*号", pub["answer"] or ""), (
            f"AI 回答里泄露了编号：{pub['answer']}"
        )

        debug = await fetch_ai_debug(base)
        answers = ai_decisions(debug, "answer", room=clients[0].room_code)
        assert answers, "作答没有被记录"
        assert answers[-1]["answer"].strip()
    finally:
        await close_all(clients)


async def test_ai_thinking_broadcast_for_answer(ws_base):
    """作答前会广播 ai:thinking(kind=answer)。"""
    clients = await _persona_with_ai(ws_base)
    base = _base_of(ws_base)
    try:
        ai_no = await _ai_room_no(base, clients[0].room_code)
        await clients[0].send("phase1:ask", targetRoomNo=ai_no, text="说点什么。")
        think = await clients[0].wait_for(
            "ai:thinking", pred=lambda m: m.get("kind") == "answer", timeout=20
        )
        assert think["nickname"]
    finally:
        await close_all(clients)


async def test_answer_falls_back_when_llm_missing(ws_base):
    """没有 LLM 也必须给出兜底台词（游戏不许卡住）。"""
    clients = await _persona_with_ai(ws_base)
    base = _base_of(ws_base)
    try:
        debug = await fetch_ai_debug(base)
        assert debug["llm"]["configured"] is False, "测试环境不应真的配 LLM Key"

        ai_no = await _ai_room_no(base, clients[0].room_code)
        await clients[0].send("phase1:ask", targetRoomNo=ai_no, text="你最怕什么？")
        pub = await clients[0].wait_for(
            "answer:public",
            pred=lambda m: m.get("status") in ("ANSWERED", "TIMEOUT"),
            timeout=25,
        )
        assert pub["status"] == "ANSWERED"
        assert (pub["answer"] or "").strip()
    finally:
        await close_all(clients)
