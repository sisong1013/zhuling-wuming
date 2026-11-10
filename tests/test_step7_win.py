"""Step 7：全对提交 → 立即结束并揭晓 fullBoard。"""

from __future__ import annotations

import pytest

from helpers import (
    close_all,
    correct_board,
    full_room,
    numbers_to_nicknames,
    start_game,
    wait_phase,
)

NAMES = ["甲", "乙", "丙", "丁"]


async def _started(ws_base, names=NAMES, config=None):
    clients = await full_room(ws_base, names, config=config)
    await start_game(clients)
    for c in clients:
        await wait_phase(c, "PHASE1", 1)
    return clients


async def test_correct_submit_ends_game_with_full_board(ws_base):
    clients = await _started(ws_base)
    winner = clients[1]
    try:
        god = numbers_to_nicknames(clients)  # {编号: 昵称}，测试侧还原
        board = {str(no): nick for no, nick in god.items()}
        await winner.send("phase1:submit", board=board)

        res = await winner.wait_for("submit:result", timeout=5)
        assert res["correct"] is True

        # 所有人立刻收到 game:over，且 fullBoard 是正确映射
        for c in clients:
            over = await c.wait_for("game:over", timeout=5)
            assert over["winnerId"] == winner.player_id
            fb = over["fullBoard"]
            assert set(fb.keys()) == {str(i) for i in range(1, len(clients) + 1)}
            for no, entry in fb.items():
                assert entry["nickname"] == god[int(no)]
            winner_entry = [p for p in clients if p.player_id == over["winnerId"]]
            assert len(winner_entry) == 1
    finally:
        await close_all(clients)


async def test_game_over_is_immediate_before_others_act(ws_base):
    """立刻结算：其他人还没来得及行动就已经结束。"""
    clients = await _started(ws_base)
    winner = clients[0]
    try:
        board = correct_board(clients)
        await winner.send("phase1:submit", board=board)
        over = await clients[0].wait_for("game:over", timeout=5)
        assert over["winnerId"] == winner.player_id
        # 其他人没有发出任何行动，也收到了 game:over
        others_msgs = await clients[2].collect(0.4)
        assert any(m.get("type") == "game:over" for m in others_msgs)
        # 结束后不应再出现 PHASE2（不会继续往下走）
        assert all(
            not (m.get("type") == "phase:changed" and m.get("phase") == "PHASE2")
            for m in others_msgs
        )
    finally:
        await close_all(clients)


async def test_game_over_state_and_actions_blocked(ws_base):
    clients = await _started(ws_base)
    winner = clients[0]
    try:
        await winner.send("phase1:submit", board=correct_board(clients))
        await winner.wait_for("game:over", timeout=5)

        # room:state 进入 OVER，并带 winnerId
        st = await winner.wait_for(
            "room:state", pred=lambda m: m.get("phase") == "OVER", timeout=5
        )
        assert st["winnerId"] == winner.player_id
        assert st["phase"] == "OVER"

        # 结束后的任何动作都被拒
        await winner.send("phase1:ask", targetRoomNo=clients[1].my_room_no, text="还能问吗")
        assert (await winner.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
        await winner.send("phase3:confirm")
        assert (await winner.wait_for("error", timeout=4))["code"] == "WRONG_PHASE"
    finally:
        await close_all(clients)


async def test_board_accepts_player_ids_too(ws_base):
    """宽容解析：看板值填 playerId 也算对。"""
    clients = await _started(ws_base, names=["甲", "乙"])
    winner = clients[0]
    try:
        board = {str(c.my_room_no): c.player_id for c in clients}
        await winner.send("phase1:submit", board=board)
        res = await winner.wait_for("submit:result", timeout=5)
        assert res["correct"] is True
        over = await clients[1].wait_for("game:over", timeout=5)
        assert over["winnerId"] == winner.player_id
    finally:
        await close_all(clients)


async def test_wrong_but_complete_board_does_not_end_game(ws_base):
    clients = await _started(ws_base)
    me = clients[0]
    try:
        board = correct_board(clients)
        # 交换两个编号的答案 → 完整但错
        keys = list(board.keys())
        board[keys[0]], board[keys[1]] = board[keys[1]], board[keys[0]]
        await me.send("phase1:submit", board=board)
        res = await me.wait_for("submit:result", timeout=5)
        assert res["correct"] is False
        assert res["cooldown"] == 3
        msgs = await me.collect(0.4)
        assert all(m.get("type") != "game:over" for m in msgs)
    finally:
        await close_all(clients)


async def test_two_player_game_win(ws_base):
    clients = await _started(ws_base, names=["甲", "乙"])
    try:
        await clients[1].send("phase1:submit", board=correct_board(clients))
        over = await clients[0].wait_for("game:over", timeout=5)
        assert over["winnerId"] == clients[1].player_id
        assert len(over["fullBoard"]) == 2
    finally:
        await close_all(clients)
