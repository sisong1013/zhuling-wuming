"""Step 6：PHASE3 回放确认、轮次推进、第 12 轮强制提交、冷却每轮递减。"""

from __future__ import annotations

import pytest

from helpers import (
    close_all,
    correct_board,
    finish_round,
    full_room,
    partial_board,
    phase_msg,
    skip_round,
    start_game,
    wait_phase,
    wrong_board,
)

NAMES = ["甲", "乙", "丙", "丁"]


async def _started(ws_base, names=NAMES, config=None):
    clients = await full_room(ws_base, names, config=config)
    await start_game(clients)
    for c in clients:
        await wait_phase(c, "PHASE1", 1)
    return clients


async def _ask_and_answer(ws_base_clients, text="问一句", answer="答一句"):
    """当前 round 里：甲问乙，其余跳过，乙作答 → 等 PHASE3。"""
    a, b, c, d = ws_base_clients
    await a.send("phase1:ask", targetRoomNo=b.my_room_no, text=text)
    for cl in (b, c, d):
        await cl.send("phase1:skip")
    q = await b.wait_for("phase2:nextQuestion", timeout=6)
    await b.send("phase2:answer", questionId=q["questionId"], text=answer)
    for cl in ws_base_clients:
        await wait_phase(cl, "PHASE3", None, timeout=6)
    return q


# ----------------------------------------------------------------------
# 回放
# ----------------------------------------------------------------------
async def test_phase3_replay_contains_questions_and_answers(ws_base):
    clients = await _started(ws_base, names=["甲", "乙"])
    a, b = clients
    try:
        await a.send("phase1:ask", targetRoomNo=b.my_room_no, text="你昨晚几点睡")
        await b.send("phase1:skip")
        q = await b.wait_for("phase2:nextQuestion", timeout=6)
        await b.send("phase2:answer", questionId=q["questionId"], text="十一点")

        replay = await a.wait_for("phase3:replay", timeout=6)
        assert replay["round"] == 1
        items = replay["items"]
        assert len(items) == 2
        q_item, a_item = items
        assert q_item["kind"] == "question"
        assert q_item["askerNickname"] == "甲"
        assert q_item["targetNickname"] == "乙"
        assert q_item["text"] == "你昨晚几点睡"
        assert q_item["status"] == "ANSWERED"
        assert a_item["kind"] == "answer"
        assert a_item["questionId"] == q_item["questionId"]
        assert a_item["answer"] == "十一点"
        assert a_item["timedOut"] is False
        # 回放同样发给另一个人
        replay_b = await b.wait_for("phase3:replay", timeout=4)
        assert replay_b["items"] == items
    finally:
        await close_all(clients)


async def test_all_confirm_advances_to_next_round(ws_base):
    clients = await _started(ws_base)
    a, b, c, d = clients
    try:
        await _ask_and_answer(clients)

        await a.send("phase3:confirm")
        prog = await a.wait_for("phase3:progress", timeout=4)
        assert prog["confirmed"] == [a.player_id]
        assert prog["total"] == 4

        # 其余三人确认 → 全员确认 → 下一轮（finish_round 内部已经等到 PHASE1 round 2）
        await finish_round(clients, 1)
        for cl in clients:
            msg = phase_msg(cl, "PHASE1", 2)
            assert msg["round"] == 2
            assert msg["forcedSubmit"] is False
    finally:
        await close_all(clients)


async def test_phase3_timeout_advances_round(ws_base):
    clients = await _started(ws_base, names=["甲", "乙"], config={"phase3Seconds": 1})
    try:
        for c in clients:
            await c.send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE3", 1, timeout=8)
        # 谁都不确认，等回放阶段超时
        for c in clients:
            await wait_phase(c, "PHASE1", 2, timeout=8)
    finally:
        await close_all(clients)


# ----------------------------------------------------------------------
# 冷却递减
# ----------------------------------------------------------------------
async def _next_round_cooldown(client, player_id, timeout=6.0):
    """等一条「轮次结束」导致的冷却变化（忽略提交错误产生的那条）。"""
    return await client.wait_for(
        "cooldown:updated",
        timeout=timeout,
        pred=lambda m: m["playerId"] == player_id and m.get("reason") == "round_end",
    )


async def test_cooldown_decrements_every_round(ws_base):
    clients = await _started(ws_base)
    me = clients[0]
    try:
        await me.send("phase1:submit", board=wrong_board(clients))
        res = await me.wait_for("submit:result", timeout=5)
        assert res["cooldown"] == 3
        for cl in clients[1:]:
            await cl.send("phase1:skip")
        for cl in clients:
            await wait_phase(cl, "PHASE3", 1, timeout=8)

        # 第 1 轮结束 → 3 → 2
        await finish_round(clients, 1)
        assert (await _next_round_cooldown(me, me.player_id))["cooldown"] == 2

        # 第 2 轮 → 1
        await skip_round(clients, 2)
        assert (await _next_round_cooldown(me, me.player_id))["cooldown"] == 1

        # 第 3 轮 → 0
        await skip_round(clients, 3)
        assert (await _next_round_cooldown(me, me.player_id))["cooldown"] == 0
    finally:
        await close_all(clients)


# ----------------------------------------------------------------------
# 强制提交轮
# ----------------------------------------------------------------------
async def test_forced_submit_round_rules(ws_base):
    """把强制提交轮改成第 2 轮：不完整罚 1 轮，完整但错也罚 1 轮；ASK/SKIP 被拒。"""
    clients = await _started(ws_base, config={"forcedSubmitRound": 2})
    try:
        await skip_round(clients, 1)  # 内部已等到 PHASE1 round 2

        msg = phase_msg(clients[0], "PHASE1", 2)
        assert msg["forcedSubmit"] is True
        for cl in clients:
            assert phase_msg(cl, "PHASE1", 2)["forcedSubmit"] is True

        p0, p1, p2, p3 = clients
        # 强制提交轮：不能再问、不能跳过
        await p0.send("phase1:ask", targetRoomNo=p1.my_room_no, text="还能问吗")
        assert (await p0.wait_for("error", timeout=4))["code"] == "FORCED_SUBMIT_REQUIRED"
        await p0.send("phase1:skip")
        assert (await p0.wait_for("error", timeout=4))["code"] == "FORCED_SUBMIT_REQUIRED"

        # 不完整 → 罚 1 轮
        await p0.send("phase1:submit", board=partial_board(clients))
        res0 = await p0.wait_for("submit:result", timeout=4)
        assert res0["correct"] is False
        assert res0["cooldown"] == 1
        assert res0["missing"] == [p3.my_room_no]
        cd0 = await p1.wait_for(
            "cooldown:updated", pred=lambda m: m["playerId"] == p0.player_id, timeout=4
        )
        assert cd0["cooldown"] == 1

        # 完整但全错 → 也罚 1 轮
        await p1.send("phase1:submit", board=wrong_board(clients))
        res1 = await p1.wait_for("submit:result", timeout=4)
        assert res1["correct"] is False
        assert res1["cooldown"] == 1
        cd1 = await p1.wait_for(
            "cooldown:updated", pred=lambda m: m["playerId"] == p1.player_id, timeout=4
        )
        assert cd1["cooldown"] == 1

        # 全员提交后进入回放阶段（本轮没人提问）
        await p2.send("phase1:submit", board=wrong_board(clients))
        await p3.send("phase1:submit", board=wrong_board(clients))
        for cl in clients:
            await wait_phase(cl, "PHASE3", 2, timeout=8)
    finally:
        await close_all(clients)


async def test_forced_submit_while_in_cooldown_penalty_two(ws_base):
    """提交时本身已在冷却期（强制轮）还错 → 罚 2 轮。"""
    clients = await _started(ws_base, config={"forcedSubmitRound": 2})
    p0 = clients[0]
    try:
        # 第 1 轮：p0 提交错误 → 冷却 3；本轮结束 → 2
        await p0.send("phase1:submit", board=wrong_board(clients))
        await p0.wait_for("submit:result", timeout=5)
        for cl in clients[1:]:
            await cl.send("phase1:skip")
        for cl in clients:
            await wait_phase(cl, "PHASE3", 1, timeout=8)
        await finish_round(clients, 1)
        assert (await _next_round_cooldown(p0, p0.player_id))["cooldown"] == 2

        # 第 2 轮是强制提交轮：冷却期也必须提交，错了罚 2 轮
        await p0.send("phase1:submit", board=wrong_board(clients))
        res = await p0.wait_for("submit:result", timeout=5)
        assert res["cooldown"] == 2
        cd = await clients[1].wait_for(
            "cooldown:updated",
            pred=lambda m: m["playerId"] == p0.player_id and m.get("round") == 2,
            timeout=4,
        )
        assert cd["cooldown"] == 2
    finally:
        await close_all(clients)


async def test_next_round_reopens_phase1_for_everyone(ws_base):
    clients = await _started(ws_base)
    try:
        await skip_round(clients, 1)
        st = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("round") == 2 and m.get("phase") == "PHASE1", timeout=6
        )
        assert all(p["cooldown"] == 0 for p in st["players"])
        assert st["you"]["acted"] is False
    finally:
        await close_all(clients)
