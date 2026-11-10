"""Step B3：错位分配。"""

from __future__ import annotations

import pytest

from helpers import (
    assign_cards,
    card_board,
    close_all,
    collect_assigned,
    persona_room,
    state_of,
    submit_all_cards,
    wait_phase,
)


async def test_everyone_gets_someone_elses_card(ws_base):
    """错位：每人拿到的卡不是自己写的。"""
    clients = await persona_room(ws_base, ["甲", "乙", "丙"])
    try:
        own_names = await submit_all_cards(clients, prefix="名牌")
        await assign_cards(clients[0])
        for c in clients:
            await wait_phase(c, "READING", timeout=10)

        assigned = await collect_assigned(clients)
        for idx, c in enumerate(clients):
            got = (assigned[c.player_id].get("yourCard") or {}).get("name")
            assert got, "必须收到自己的卡"
            assert got != own_names[idx], f"{c.name} 拿到了自己写的卡 {got}"
            assert got in own_names, "拿到的卡必须是本房间的卡"
    finally:
        await close_all(clients)


async def test_room_numbers_still_random_and_unique(ws_base):
    """编号仍随机分配，且 1..n 各一个。"""
    clients = await persona_room(ws_base, ["甲", "乙", "丙", "丁"])
    try:
        await submit_all_cards(clients)
        await assign_cards(clients[0])
        for c in clients:
            await wait_phase(c, "READING", timeout=10)
        assigned = await collect_assigned(clients)

        nos = sorted(msg["yourRoomNo"] for msg in assigned.values())
        assert nos == [1, 2, 3, 4]
        for msg in assigned.values():
            assert sorted(msg["roomNos"]) == [1, 2, 3, 4]
    finally:
        await close_all(clients)


async def test_board_and_cooldown_reset_after_assign(ws_base):
    """分配后 board_json 清空、submit_cooldown 归零。"""
    clients = await persona_room(ws_base, ["甲", "乙"])
    try:
        # 写卡阶段先塞一个草稿（board:saveDraft 在第一幕才合法，这里直接看分配后的状态）
        await submit_all_cards(clients)
        await assign_cards(clients[0])
        for c in clients:
            await wait_phase(c, "READING", timeout=10)
        st = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("status") == "READING", timeout=8
        )
        assert st["you"]["draft"] == {}
        assert st["you"]["cooldown"] == 0
    finally:
        await close_all(clients)


async def test_derange_is_permutation(ws_base):
    """分配结果是一一对应的排列（每张卡只发给一个人）。"""
    clients = await persona_room(ws_base, ["甲", "乙", "丙", "丁"])
    try:
        names = await submit_all_cards(clients, prefix="卡")
        await assign_cards(clients[0])
        for c in clients:
            await wait_phase(c, "READING", timeout=10)
        assigned = await collect_assigned(clients)
        got = [(m.get("yourCard") or {}).get("name") for m in assigned.values()]
        assert sorted(got) == sorted(names), "每张卡必须恰好下发一次"
    finally:
        await close_all(clients)


def test_derange_unit_fallback_rotation():
    """随机洗牌失败时用旋转兜底（作者与座位同序的极端情况）。"""
    from server import rules
    from server.models import PersonaCard, Player

    players = [Player(id=f"p{i}", nickname=f"n{i}") for i in range(3)]
    cards = [
        PersonaCard(id=f"c{i}", game_id="123456", author_id=f"p{i}", name=f"卡{i}")
        for i in range(3)
    ]

    original = rules.random.shuffle
    try:
        rules.random.shuffle = lambda seq: None  # 洗牌变成「不变」
        mapping = rules.derange(cards, players)
    finally:
        rules.random.shuffle = original

    for p in players:
        assert mapping[p.id].author_id != p.id, "兜底也必须错位"
    assert sorted(c.id for c in mapping.values()) == ["c0", "c1", "c2"]


def test_derange_unit_count_mismatch():
    from server import rules
    from server.models import GameError, PersonaCard, Player

    players = [Player(id="p1", nickname="a"), Player(id="p2", nickname="b")]
    cards = [PersonaCard(id="c1", game_id="1", author_id="p1", name="卡1")]
    with pytest.raises(GameError) as exc:
        rules.derange(cards, players)
    assert exc.value.code == "CARD_COUNT_MISMATCH"
