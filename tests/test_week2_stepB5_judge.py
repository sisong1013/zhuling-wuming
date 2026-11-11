"""Step B5：PERSONA 判定与揭晓。"""

from __future__ import annotations

import pytest

from helpers import (
    assign_cards,
    card_board,
    close_all,
    collect_assigned,
    full_room,
    persona_room,
    shuffled_card_board,
    start_game,
    state_of,
    submit_all_cards,
    wait_phase,
)


async def _persona_playing(ws_base, names, config=None):
    """跑到第一幕，并把每人的编号/卡名记到 client 上。"""
    clients = await persona_room(ws_base, names, config=config)
    cards = await submit_all_cards(clients)
    await assign_cards(clients[0])
    for c in clients:
        await wait_phase(c, "READING", timeout=12)
    await collect_assigned(clients)
    for c in clients:
        await c.send("reading:confirm")
    for c in clients:
        await wait_phase(c, "PHASE1", 1, timeout=12)
    return clients, cards


async def test_correct_persona_board_wins_with_reveal(ws_base):
    """看板全对 → 胜；game:over 带 reveal（编号/卡名/卡面/作者）。"""
    clients, cards = await _persona_playing(ws_base, ["甲", "乙", "丙"])
    try:
        board = card_board(clients)
        await clients[0].send("phase1:submit", board=board)

        over = await clients[0].wait_for("game:over", timeout=10)
        assert over["gameMode"] == "PERSONA"
        assert over["winnerId"] == clients[0].player_id
        assert "fullBoard" not in over

        reveal = over["reveal"]
        assert len(reveal) == 3
        by_name = {cards[i]: clients[i].name for i in range(len(cards))}
        for item in reveal:
            assert set(item) == {"roomNo", "cardName", "cardContent", "authorNickname"}
            assert item["cardName"] in cards
            assert item["cardContent"]
            assert item["authorNickname"] == by_name[item["cardName"]]
        assert sorted(item["roomNo"] for item in reveal) == [1, 2, 3]
    finally:
        await close_all(clients)


async def test_wrong_persona_board_triggers_cooldown(ws_base):
    """错的看板 → submit:result 里有错项 + 冷却 3 轮。"""
    clients, _ = await _persona_playing(ws_base, ["甲", "乙"])
    try:
        board = shuffled_card_board(clients)
        await clients[0].send("phase1:submit", board=board)
        res = await clients[0].wait_for("submit:result", timeout=8)
        assert res["correct"] is False
        assert res["wrong"], "应当指出错误编号"

        cd = await clients[0].wait_for(
            "cooldown:updated", pred=lambda m: m.get("reason") == "submit_wrong", timeout=8
        )
        assert cd["cooldown"] == 3
    finally:
        await close_all(clients)


async def test_partial_persona_board_reports_missing(ws_base):
    """少填一格 → missing 列表非空、不算正确。"""
    clients, _ = await _persona_playing(ws_base, ["甲", "乙"])
    try:
        board = card_board(clients)
        # 本人那格是「白送」的：服务端会用真值补齐，所以必须丢「别人的」格子才算缺格
        own = str(state_of(clients[0])["you"]["roomNo"])
        dropped = next(no for no in board if str(no) != own)
        board.pop(dropped)
        await clients[0].send("phase1:submit", board=board)
        res = await clients[0].wait_for("submit:result", timeout=8)
        assert res["correct"] is False
        assert str(dropped) in [str(x) for x in res["missing"]]
    finally:
        await close_all(clients)


async def test_own_cell_is_free_in_persona(ws_base):
    """自己那格是白送：把别人全部猜对、自己那格填自己卡名即可全对。"""
    clients, _ = await _persona_playing(ws_base, ["甲", "乙", "丙"])
    try:
        board = card_board(clients)
        # 主动确认：本人格 = 自己拿到的卡名
        me = clients[0]
        assert board[str(me.my_room_no)] == me.assigned_card["name"]
        await me.send("phase1:submit", board=board)
        res = await me.wait_for("submit:result", timeout=10)
        assert res["correct"] is True
    finally:
        await close_all(clients)


async def test_real_mode_over_payload_unchanged(ws_base):
    """REAL 模式仍然下发 fullBoard，没有 reveal。"""
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=8)
        board = {str(c.my_room_no): c.name for c in clients}
        await clients[0].send("phase1:submit", board=board)
        over = await clients[0].wait_for("game:over", timeout=8)
        assert over["gameMode"] == "REAL"
        assert "reveal" not in over
        assert over["fullBoard"]
    finally:
        await close_all(clients)
