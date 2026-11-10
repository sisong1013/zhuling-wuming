"""Step B6：回答的软约束（服务端不判定人设）。"""

from __future__ import annotations

import pytest

from helpers import (
    assign_cards,
    close_all,
    collect_assigned,
    persona_room,
    submit_all_cards,
    wait_phase,
)


async def _persona_playing(ws_base, names):
    """跑到第一幕（PHASE1），并把每人编号/卡名记到 client 上。"""
    clients = await persona_room(ws_base, names, config={"readingSeconds": 30})
    await submit_all_cards(clients)
    await assign_cards(clients[0])
    for c in clients:
        await wait_phase(c, "READING", timeout=12)
    await collect_assigned(clients)
    for c in clients:
        await c.send("reading:confirm")
    for c in clients:
        await wait_phase(c, "PHASE1", 1, timeout=12)
    return clients


async def _ask_then_answer(ws_base, ask_text: str, answer_text: str):
    """甲问乙 → 乙放弃 → 进第二幕 → 乙作答。"""
    clients = await _persona_playing(ws_base, ["甲", "乙"])
    asker, target = clients[0], clients[1]

    await asker.send("phase1:ask", targetRoomNo=target.my_room_no, text=ask_text)
    got = await target.wait_for("question:received", timeout=10)
    qid = got["questionId"]

    await target.send("phase1:skip")
    for c in clients:
        await wait_phase(c, "PHASE2", 1, timeout=12)

    await target.send("phase2:answer", questionId=qid, text=answer_text)
    pub = await asker.wait_for(
        "answer:public", pred=lambda m: m.get("questionId") == qid, timeout=12
    )
    return clients, pub, ask_text, got


async def test_answer_text_is_stored_verbatim(ws_base):
    """回答原样存储与广播（含标点、全角、emoji）。"""
    text = "【完全不像那张卡】我，呃……吃了碗面🍜，然后睡到日上三竿——真的！"
    clients, pub, _, _ = await _ask_then_answer(ws_base, "你昨夜在做什么？", text)
    try:
        assert pub["answer"] == text
        assert pub["status"] == "ANSWERED"
        assert pub["timedOut"] is False
    finally:
        await close_all(clients)


async def test_off_persona_answer_not_rejected(ws_base):
    """服务端不做「是否符合人设」判断：随便答也不报错。"""
    clients, pub, _, _ = await _ask_then_answer(ws_base, "一句话介绍你自己。", "我是我，不是卡。")
    try:
        assert pub["answer"] == "我是我，不是卡。"
        errs = [m for m in await clients[1].collect(0.3) if m.get("type") == "error"]
        assert errs == []
    finally:
        await close_all(clients)


async def test_question_text_also_unchecked(ws_base):
    """提问文本同样不做内容审查，原样广播。"""
    weird = "（⚠️测试）你、你、你到底是不是那张卡？"
    clients = await _persona_playing(ws_base, ["甲", "乙"])
    try:
        await clients[0].send("phase1:ask", targetRoomNo=clients[1].my_room_no, text=weird)
        got = await clients[1].wait_for("question:received", timeout=10)
        assert got["text"] == weird
    finally:
        await close_all(clients)


async def test_empty_answer_still_rejected(ws_base):
    """软约束只针对「人设」，空回答依旧非法。"""
    clients = await _persona_playing(ws_base, ["甲", "乙"])
    try:
        asker, target = clients[0], clients[1]
        await asker.send("phase1:ask", targetRoomNo=target.my_room_no, text="说点什么？")
        got = await target.wait_for("question:received", timeout=10)
        await target.send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE2", 1, timeout=12)

        await target.send("phase2:answer", questionId=got["questionId"], text="   ")
        err = await target.wait_for("error", timeout=8)
        assert err["code"] == "INVALID_PAYLOAD"
    finally:
        await close_all(clients)
