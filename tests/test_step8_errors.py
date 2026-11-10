"""Step 8：非法操作一律被拒（阶段 / 重复 / 权限 / 人数 / 载荷）。"""

from __future__ import annotations

import pytest

from helpers import (
    WsClient,
    close_all,
    correct_board,
    finish_round,
    full_room,
    join_room,
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


# ----------------------------------------------------------------------
# 阶段校验
# ----------------------------------------------------------------------
async def test_game_actions_rejected_in_lobby(ws_base):
    clients = await full_room(ws_base, ["甲", "乙"])
    me = clients[0]
    try:
        await me.send("phase1:ask", targetRoomNo=1, text="开局前问一句")
        assert (await me.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
        await me.send("phase1:submit", board={})
        assert (await me.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
        await me.send("phase1:skip")
        assert (await me.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
        await me.send("phase2:answer", questionId="q_x", text="x")
        assert (await me.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
        await me.send("phase3:confirm")
        assert (await me.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
        await me.send("board:saveDraft", board={})
        assert (await me.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
    finally:
        await close_all(clients)


async def test_phase2_and_phase3_actions_rejected_out_of_phase(ws_base):
    clients = await _started(ws_base)
    a, b, c, d = clients
    try:
        # PHASE1 里不能答题 / 确认
        await b.send("phase2:answer", questionId="q_x", text="抢答")
        assert (await b.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
        await b.send("phase3:confirm")
        assert (await b.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"

        # 进 PHASE3 后不能再提问 / 提交
        await a.send("phase1:ask", targetRoomNo=b.my_room_no, text="问一句")
        for cl in (b, c, d):
            await cl.send("phase1:skip")
        q = await b.wait_for("phase2:nextQuestion", timeout=6)
        await b.send("phase2:answer", questionId=q["questionId"], text="答一句")
        for cl in clients:
            await wait_phase(cl, "PHASE3", 1, timeout=6)

        await a.send("phase1:ask", targetRoomNo=b.my_room_no, text="回放阶段再问")
        assert (await a.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
        await a.send("phase1:submit", board=correct_board(clients))
        assert (await a.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
        await a.send("phase2:answer", questionId=q["questionId"], text="补答")
        assert (await a.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
    finally:
        await close_all(clients)


# ----------------------------------------------------------------------
# 重复行动
# ----------------------------------------------------------------------
async def test_duplicate_actions_rejected(ws_base):
    clients = await _started(ws_base)
    me = clients[0]
    try:
        await me.send("phase1:skip")
        await me.wait_for("phase1:progress", timeout=4)
        await me.send("phase1:skip")
        assert (await me.wait_for("error", timeout=4))["code"] == "ALREADY_ACTED"
        await me.send("phase1:ask", targetRoomNo=clients[1].my_room_no, text="再来")
        assert (await me.wait_for("error", timeout=4))["code"] == "ALREADY_ACTED"
        await me.send("phase1:submit", board=correct_board(clients))
        assert (await me.wait_for("error", timeout=4))["code"] == "ALREADY_ACTED"
    finally:
        await close_all(clients)


async def test_duplicate_confirm_rejected(ws_base):
    clients = await _started(ws_base, names=["甲", "乙"])
    me = clients[0]
    try:
        for c in clients:
            await c.send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE3", 1, timeout=8)
        await me.send("phase3:confirm")
        await me.wait_for("phase3:progress", timeout=4)
        await me.send("phase3:confirm")
        assert (await me.wait_for("error", timeout=4))["code"] == "ALREADY_CONFIRMED"
    finally:
        await close_all(clients)


# ----------------------------------------------------------------------
# 权限
# ----------------------------------------------------------------------
async def test_non_captain_cannot_config(ws_base):
    clients = await full_room(ws_base, ["队长", "队员"])
    try:
        await clients[1].send("setup:config", phase1Seconds=5)
        assert (await clients[1].wait_for("error", timeout=4))["code"] == "NOT_CAPTAIN"
    finally:
        await close_all(clients)


async def test_captain_cannot_config_after_start(ws_base):
    clients = await _started(ws_base)
    try:
        await clients[0].send("setup:config", phase1Seconds=5)
        assert (await clients[0].wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
    finally:
        await close_all(clients)


async def test_invalid_config_values_rejected(ws_base):
    c = await full_room(ws_base, ["队长"])
    try:
        await c[0].send("setup:config", phase1Seconds=9999)
        assert (await c[0].wait_for("error", timeout=4))["code"] == "INVALID_CONFIG"
        await c[0].send("setup:config", maxPlayers=99)
        assert (await c[0].wait_for("error", timeout=4))["code"] == "INVALID_CONFIG"
        await c[0].send("setup:config", nonsense=1)
        assert (await c[0].wait_for("error", timeout=4))["code"] == "INVALID_CONFIG"
    finally:
        await close_all(c)


# ----------------------------------------------------------------------
# 人数上限
# ----------------------------------------------------------------------
async def test_room_full_rejected(ws_base):
    captain = await full_room(ws_base, ["p1"])
    clients = [captain[0]]
    try:
        for i in range(2, 9):  # 凑满 8 人
            clients.append(await join_room(ws_base, captain[0].room_code, f"p{i}"))
        extra = await WsClient.connect(ws_base, "p9")
        try:
            await extra.send("room:join", roomCode=captain[0].room_code, nickname="p9")
            err = await extra.wait_for("room:error", timeout=4)
            assert err["code"] == "ROOM_FULL"
        finally:
            await extra.close()
    finally:
        await close_all(clients)


async def test_custom_max_players_enforced(ws_base):
    clients = await full_room(ws_base, ["甲", "乙"], config={"maxPlayers": 2})
    extra = await WsClient.connect(ws_base, "丙")
    try:
        await extra.send("room:join", roomCode=clients[0].room_code, nickname="丙")
        assert (await extra.wait_for("room:error", timeout=4))["code"] == "ROOM_FULL"
    finally:
        await extra.close()
        await close_all(clients)


# ----------------------------------------------------------------------
# 身份 / 载荷
# ----------------------------------------------------------------------
async def test_actions_require_room(ws_base):
    c = await WsClient.connect(ws_base, "路人")
    try:
        for mtype, payload in (
            ("phase1:ask", {"targetRoomNo": 1, "text": "hi"}),
            ("phase1:submit", {"board": {}}),
            ("phase3:confirm", {}),
            ("game:start", {}),
            ("setup:config", {"phase1Seconds": 5}),
        ):
            await c.send(mtype, **payload)
            err = await c.wait_for("error", timeout=4)
            assert err["code"] == "NOT_IN_ROOM", (mtype, err)
    finally:
        await c.close()


async def test_invalid_payloads_rejected(ws_base):
    clients = await _started(ws_base)
    me = clients[0]
    try:
        await me.send("phase1:ask", targetRoomNo="不是数字", text="问")
        assert (await me.wait_for("error", timeout=4))["code"] == "INVALID_TARGET"
        await me.send("phase1:ask", targetRoomNo=clients[1].my_room_no, text="")
        assert (await me.wait_for("error", timeout=4))["code"] == "INVALID_PAYLOAD"
        await me.send("phase1:submit", board="不是对象")
        assert (await me.wait_for("error", timeout=4))["code"] == "INVALID_PAYLOAD"
        await me.send("phase1:submit", board={"x": "甲"})
        assert (await me.wait_for("error", timeout=4))["code"] == "INVALID_PAYLOAD"
        await me.send("board:saveDraft", board=[1, 2, 3])
        assert (await me.wait_for("error", timeout=4))["code"] == "INVALID_PAYLOAD"
        # 依然没有消耗行动机会
        await me.send("phase1:skip")
        prog = await me.wait_for("phase1:progress", timeout=4)
        assert me.player_id in prog["acted"]
    finally:
        await close_all(clients)


async def test_cooldown_player_can_skip_but_not_submit(ws_base):
    """冷却期：只能 ASK / SKIP，不能提交。"""
    clients = await _started(ws_base)
    me = clients[0]
    try:
        await me.send("phase1:submit", board=wrong_board(clients))
        await me.wait_for("submit:result", timeout=5)
        for cl in clients[1:]:
            await cl.send("phase1:skip")
        for cl in clients:
            await wait_phase(cl, "PHASE3", 1, timeout=8)
        await finish_round(clients, 1)

        # 第 2 轮：冷却 2 → 不能提交，但能跳过
        await me.send("phase1:submit", board=correct_board(clients))
        assert (await me.wait_for("error", timeout=4))["code"] == "PLAYER_IN_COOLDOWN"
        await me.send("phase1:skip")
        prog = await me.wait_for("phase1:progress", timeout=4)
        assert me.player_id in prog["acted"]
    finally:
        await close_all(clients)
