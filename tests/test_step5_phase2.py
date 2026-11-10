"""Step 5：PHASE2 —— 被问者按队列逐题作答、被问者之间并行、超时不惩罚、答完进 PHASE3。"""

from __future__ import annotations

import asyncio

import pytest

from helpers import close_all, full_room, start_game, wait_phase

NAMES = ["甲", "乙", "丙", "丁"]


async def _started(ws_base, names=NAMES, config=None):
    clients = await full_room(ws_base, names, config=config)
    await start_game(clients)
    for c in clients:
        await wait_phase(c, "PHASE1", 1)
    return clients


async def _ask(asker, target, text):
    await asker.send("phase1:ask", targetRoomNo=target.my_room_no, text=text)


async def test_two_targets_get_questions_in_parallel(ws_base):
    """A→B、C→D 两道题同时在进行，互不阻塞。"""
    clients = await _started(ws_base)
    a, b, c, d = clients
    try:
        await _ask(a, b, "乙，你喜欢猫吗")
        await _ask(c, d, "丁，你几点睡")
        await b.send("phase1:skip")
        await d.send("phase1:skip")
        for cl in clients:
            await wait_phase(cl, "PHASE2", 1, timeout=6)

        q_for_b = await b.wait_for("phase2:nextQuestion", timeout=4)
        q_for_d = await d.wait_for("phase2:nextQuestion", timeout=4)
        assert q_for_b["askerId"] == a.player_id
        assert q_for_d["askerId"] == c.player_id
        assert q_for_b["questionId"] != q_for_d["questionId"]
        # 两道题各自有独立的 deadline
        assert q_for_b["deadline"] > 0 and q_for_d["deadline"] > 0

        # 只有真正被问的人收到 nextQuestion
        for observer in (a, c):
            msgs = await observer.collect(0.3)
            assert all(m.get("type") != "phase2:nextQuestion" for m in msgs)

        # 两人各自作答，互不影响
        await b.send("phase2:answer", questionId=q_for_b["questionId"], text="喜欢")
        await d.send("phase2:answer", questionId=q_for_d["questionId"], text="一点")
        ans_b = await a.wait_for(
            "answer:public", pred=lambda m: m["questionId"] == q_for_b["questionId"], timeout=4
        )
        ans_d = await c.wait_for(
            "answer:public", pred=lambda m: m["questionId"] == q_for_d["questionId"], timeout=4
        )
        assert ans_b["answer"] == "喜欢" and ans_b["status"] == "ANSWERED"
        assert ans_d["answer"] == "一点" and ans_d["status"] == "ANSWERED"
        for cl in clients:
            await wait_phase(cl, "PHASE3", 1, timeout=6)
    finally:
        await close_all(clients)


async def test_same_target_queue_is_sequential(ws_base):
    """两个人问同一个人：被问者一次只拿到一道题，答完才推下一道。"""
    clients = await _started(ws_base)
    a, b, c, d = clients
    try:
        await _ask(a, b, "第一问")
        await _ask(c, b, "第二问")
        await b.send("phase1:skip")
        await d.send("phase1:skip")
        await wait_phase(b, "PHASE2", 1, timeout=6)

        first = await b.wait_for("phase2:nextQuestion", timeout=4)
        assert first["text"] == "第一问"
        # 答题前不应该再收到第二道题
        idle = await b.collect(0.4)
        assert all(m.get("type") != "phase2:nextQuestion" for m in idle), idle

        await b.send("phase2:answer", questionId=first["questionId"], text="答第一问")
        second = await b.wait_for("phase2:nextQuestion", timeout=4)
        assert second["text"] == "第二问"
        assert second["questionId"] != first["questionId"]

        await b.send("phase2:answer", questionId=second["questionId"], text="答第二问")
        for cl in clients:
            await wait_phase(cl, "PHASE3", 1, timeout=6)
    finally:
        await close_all(clients)


async def test_timeout_of_one_does_not_block_another(ws_base):
    """一人超时记 TIMEOUT、不惩罚，另一人的作答照常完成。"""
    clients = await _started(ws_base, config={"phase2Seconds": 1})
    a, b, c, d = clients
    try:
        await _ask(a, b, "会被忽略的问题")
        await _ask(c, d, "会被回答的问题")
        await b.send("phase1:skip")
        await d.send("phase1:skip")
        await wait_phase(b, "PHASE2", 1, timeout=6)

        qb = await b.wait_for("phase2:nextQuestion", timeout=4)
        qd = await d.wait_for("phase2:nextQuestion", timeout=4)

        # d 立刻回答；b 什么都不做等超时
        await d.send("phase2:answer", questionId=qd["questionId"], text="我答了")
        ok = await c.wait_for(
            "answer:public", pred=lambda m: m["questionId"] == qd["questionId"], timeout=4
        )
        assert ok["status"] == "ANSWERED"

        to = await a.wait_for(
            "answer:public", pred=lambda m: m["questionId"] == qb["questionId"], timeout=6
        )
        assert to["status"] == "TIMEOUT"
        assert to["timedOut"] is True
        assert to["answer"] is None

        # 超时没有任何冷却惩罚；两题都结束 → 立刻进 PHASE3（一起收下来验证，避免丢掉消息）
        msgs = await a.collect(1.0)
        assert all(m.get("type") != "cooldown:updated" for m in msgs), [
            m for m in msgs if m.get("type") == "cooldown:updated"
        ]
        assert any(
            m.get("type") == "phase:changed" and m.get("phase") == "PHASE3" for m in msgs
        ), [m.get("type") for m in msgs]

        for cl in (b, c, d):
            await wait_phase(cl, "PHASE3", 1, timeout=8)
    finally:
        await close_all(clients)


async def test_answer_validation(ws_base):
    clients = await _started(ws_base)
    a, b, c, d = clients
    try:
        await _ask(a, b, "问题一")
        for cl in (b, c, d):
            await cl.send("phase1:skip")
        await wait_phase(b, "PHASE2", 1, timeout=6)
        q = await b.wait_for("phase2:nextQuestion", timeout=4)

        # 不是被问者
        await c.send("phase2:answer", questionId=q["questionId"], text="我来插一嘴")
        assert (await c.wait_for("error", timeout=4))["code"] == "NOT_YOUR_QUESTION"
        # 空回答
        await b.send("phase2:answer", questionId=q["questionId"], text="   ")
        assert (await b.wait_for("error", timeout=4))["code"] == "INVALID_PAYLOAD"
        # 不存在的问题
        await b.send("phase2:answer", questionId="q_not_exist", text="x")
        assert (await b.wait_for("error", timeout=4))["code"] == "QUESTION_NOT_FOUND"
        # 正常回答
        await b.send("phase2:answer", questionId=q["questionId"], text="正常回答")
        await a.wait_for(
            "answer:public", pred=lambda m: m["questionId"] == q["questionId"], timeout=4
        )
        # 重复回答
        await b.send("phase2:answer", questionId=q["questionId"], text="再答一次")
        assert (await b.wait_for("error", timeout=4))["code"] in (
            "ALREADY_ANSWERED",
            "WRONG_PHASE",
        )
    finally:
        await close_all(clients)


async def test_no_questions_goes_straight_to_phase3(ws_base):
    clients = await _started(ws_base, names=["甲", "乙"])
    try:
        for c in clients:
            await c.send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE3", 1, timeout=6)
        replay = await clients[0].wait_for("phase3:replay", timeout=4)
        assert replay["items"] == []
    finally:
        await close_all(clients)


async def test_phase2_progress_counts(ws_base):
    clients = await _started(ws_base)
    a, b, c, d = clients
    try:
        await _ask(a, b, "问题一")
        for cl in (b, c, d):
            await cl.send("phase1:skip")
        await wait_phase(b, "PHASE2", 1, timeout=6)
        q = await b.wait_for("phase2:nextQuestion", timeout=4)
        prog = await a.wait_for(
            "phase2:progress", pred=lambda m: m.get("total", 0) >= 1 and m.get("round") == 1, timeout=4
        )
        assert prog["total"] == 1
        await b.send("phase2:answer", questionId=q["questionId"], text="答")
        done = await a.wait_for(
            "phase2:progress", pred=lambda m: m.get("answered") == 1, timeout=4
        )
        assert done["pending"] == []
        assert done["total"] == 1
    finally:
        await close_all(clients)
