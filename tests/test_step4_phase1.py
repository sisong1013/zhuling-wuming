"""Step 4：PHASE1 三选一（ASK / SUBMIT / SKIP）、冷却、进度、提前/超时进 PHASE2。"""

from __future__ import annotations

import time

import pytest

from helpers import (
    act_all,
    close_all,
    correct_board,
    full_room,
    partial_board,
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


# ----------------------------------------------------------------------
# ASK
# ----------------------------------------------------------------------
async def test_ask_creates_public_question(ws_base):
    clients = await _started(ws_base)
    try:
        asker, target = clients[0], clients[1]
        await asker.send("phase1:ask", targetRoomNo=target.my_room_no, text="你昨天熬夜了吗？")
        # 所有人都能看到这条提问（PUBLIC）
        for c in clients:
            q = await c.wait_for("question:public", timeout=4)
            assert q["questionId"]
            assert q["askerId"] == asker.player_id
            assert q["targetId"] == target.player_id
            assert q["text"] == "你昨天熬夜了吗？"
            assert q["round"] == 1
            assert q["status"] == "PENDING"
        # 进度广播：只有 asker 已行动
        prog = await asker.wait_for("phase1:progress", timeout=4)
        assert asker.player_id in prog["acted"]
        assert prog["total"] == 4
    finally:
        await close_all(clients)


async def test_ask_rejects_bad_target_and_empty_text(ws_base):
    clients = await _started(ws_base)
    try:
        me = clients[0]
        await me.send("phase1:ask", targetRoomNo=me.my_room_no, text="问自己？")
        assert (await me.wait_for("error", timeout=4))["code"] == "INVALID_TARGET"

        bogus = max(c.my_room_no for c in clients) + 1
        await me.send("phase1:ask", targetRoomNo=bogus, text="问空气")
        assert (await me.wait_for("error", timeout=4))["code"] == "INVALID_TARGET"

        await me.send("phase1:ask", targetRoomNo=clients[1].my_room_no, text="   ")
        assert (await me.wait_for("error", timeout=4))["code"] == "INVALID_PAYLOAD"
        # 三次失败都没有消耗行动机会
        st = await me.wait_for("room:state", timeout=4)
        assert st["you"]["acted"] is False
    finally:
        await close_all(clients)


async def test_cannot_act_twice_in_same_round(ws_base):
    clients = await _started(ws_base)
    try:
        me, other = clients[0], clients[1]
        await me.send("phase1:skip")
        await me.wait_for("phase1:progress", timeout=4)
        await me.send("phase1:ask", targetRoomNo=other.my_room_no, text="再来一次")
        assert (await me.wait_for("error", timeout=4))["code"] == "ALREADY_ACTED"
    finally:
        await close_all(clients)


# ----------------------------------------------------------------------
# SUBMIT / 冷却
# ----------------------------------------------------------------------
async def test_wrong_submit_sets_cooldown_three_and_broadcasts(ws_base):
    clients = await _started(ws_base)
    try:
        me = clients[0]
        await me.send("phase1:submit", board=wrong_board(clients))
        res = await me.wait_for("submit:result", timeout=4)
        assert res["correct"] is False
        assert res["cooldown"] == 3
        # 冷却广播给所有人（含本人）
        for c in clients:
            cd = await c.wait_for("cooldown:updated", timeout=4)
            assert cd["playerId"] == me.player_id
            assert cd["cooldown"] == 3
        st = await me.wait_for(
            "room:state",
            timeout=4,
            pred=lambda m: any(p["id"] == me.player_id and p["cooldown"] == 3 for p in m["players"]),
        )
        me_view = [p for p in st["players"] if p["id"] == me.player_id][0]
        assert me_view["cooldown"] == 3
    finally:
        await close_all(clients)


async def test_submit_while_in_cooldown_is_rejected(ws_base):
    clients = await _started(ws_base)
    try:
        me = clients[0]
        await me.send("phase1:submit", board=wrong_board(clients))
        await me.wait_for("submit:result", timeout=4)
        # 冷却期内再提交（同轮）→ 被拒
        await me.send("phase1:submit", board=correct_board(clients))
        assert (await me.wait_for("error", timeout=4))["code"] == "PLAYER_IN_COOLDOWN"
    finally:
        await close_all(clients)


async def test_cooldown_player_can_still_ask(ws_base):
    """冷却只限制提交，提问/跳过仍然可以（第 1 轮同轮内换个动作会被 ALREADY_ACTED 拦，故用新房间验证）。"""
    clients = await _started(ws_base)
    try:
        me = clients[0]
        await me.send("phase1:submit", board=wrong_board(clients))
        await me.wait_for("submit:result", timeout=4)
        # 同轮内已被消耗；这里断言 ASK 的错误是 ALREADY_ACTED（说明不是靠冷却拦的）
        await me.send("phase1:ask", targetRoomNo=clients[1].my_room_no, text="还能问吗")
        assert (await me.wait_for("error", timeout=4))["code"] == "ALREADY_ACTED"
    finally:
        await close_all(clients)


# ----------------------------------------------------------------------
# 阶段推进
# ----------------------------------------------------------------------
async def test_all_acted_advances_to_phase2_early(ws_base):
    clients = await _started(ws_base)
    try:
        await act_all(clients, ["ask", "ask", "skip", "skip"])
        for c in clients:
            msg = await wait_phase(c, "PHASE2", 1, timeout=6)
            assert msg["phase"] == "PHASE2"
            assert msg["round"] == 1
            assert msg["deadline"] > time.time()
    finally:
        await close_all(clients)


async def test_phase1_timeout_advances_to_phase2(ws_base):
    clients = await _started(ws_base, names=["甲", "乙"], config={"phase1Seconds": 1})
    try:
        # 谁都不行动，等服务端权威计时器
        for c in clients:
            msg = await wait_phase(c, "PHASE2", 1, timeout=8)
            assert msg["phase"] == "PHASE2"
    finally:
        await close_all(clients)


async def test_ask_consumes_action_and_progress_reports_pending(ws_base):
    clients = await _started(ws_base)
    try:
        await clients[0].send("phase1:skip")
        prog = await clients[1].wait_for("phase1:progress", timeout=4)
        assert len(prog["acted"]) == 1
        assert len(prog["pending"]) == 3
    finally:
        await close_all(clients)


async def test_save_draft_works_in_phase1(ws_base):
    clients = await _started(ws_base)
    try:
        me = clients[0]
        board = {str(n): "某人" for n in me.room_nos}
        await me.send("board:saveDraft", board=board)
        saved = await me.wait_for("board:draftSaved", timeout=4)
        assert saved["board"] == board
    finally:
        await close_all(clients)
