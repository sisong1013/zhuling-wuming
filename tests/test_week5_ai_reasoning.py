"""第 5 周：AI 推理升级（约束传播 + 提交前推理轮 + 模型降级链）。"""

from __future__ import annotations

import pytest

from server import ai_agent, llm_client
from server.models import GameConfig, GameMode, PersonaCard, Player, Room


# ----------------------------------------------------------------------
# 造一个离线房间（PERSONA / REAL 都行）
# ----------------------------------------------------------------------
def make_room(n: int = 4, mode: str = "PERSONA"):
    room = Room(code="123456", config=GameConfig())
    room.game_mode = GameMode.PERSONA.value if mode == "PERSONA" else GameMode.REAL.value
    players = [
        Player(id=f"p{i}", nickname=["甲", "乙", "丙", "丁", "戊"][i], room_no=i + 1)
        for i in range(n)
    ]
    room.players = {p.id: p for p in players}
    room.captain_id = players[0].id
    if mode == "PERSONA":
        names = ["雾港更夫", "折纸诗人", "青苔占星师", "落雪书吏", "无名小丑"][:n]
        cards = []
        for i, p in enumerate(players):
            card = PersonaCard(
                id=f"c{i}", game_id=room.code, author_id=p.id, name=names[i], content="卡面"
            )
            card.assigned_room_no = p.room_no
            p.assigned_card_id = card.id
            cards.append(card)
        room.cards = cards
        room.assigned = True
    return room, players


def test_own_cell_always_correct_persona():
    room, players = make_room(4)
    for p in players:
        board = ai_agent.fallback_board(room, p)
        assert board[p.room_no] == room.card_of(p).name


def test_own_cell_always_correct_real():
    room, players = make_room(4, mode="REAL")
    for p in players:
        board = ai_agent.fallback_board(room, p)
        assert board[p.room_no] == p.nickname


def test_board_is_bijection():
    """一人一号：看板取值不能重复，且必须覆盖全部编号。"""
    room, players = make_room(4)
    for p in players:
        board = ai_agent.fallback_board(room, p)
        assert set(board) == set(room.room_nos())
        assert len(set(board.values())) == len(board)


def test_two_player_board_is_fully_correct():
    """2 人 PERSONA：错位分配是唯一解，约束传播应当直接全对。"""
    room, players = make_room(2)
    for p in players:
        board = ai_agent.fallback_board(room, p)
        truth = {
            pl.room_no: room.card_of(pl).name for pl in players
        }
        assert board == truth, f"{p.nickname} 的推断应有唯一解：{board} vs {truth}"


def test_propagation_eliminates_known_value():
    room, players = make_room(3)
    bot = players[2]
    ai_agent.refresh_candidates(room, bot)
    memory = ai_agent.memory_of(bot)
    own = room.card_of(bot).name
    for no, options in memory.candidates.items():
        if no != bot.room_no:
            assert own not in options, "自己那张卡不该再出现在别人候选里"


# ----------------------------------------------------------------------
# 提交前推理轮
# ----------------------------------------------------------------------
async def test_reasoning_round_uses_llm(monkeypatch):
    room, players = make_room(3)
    bot = players[1]
    truth = {p.room_no: room.card_of(p).name for p in players}

    async def fake_text(system, user, timeout=15.0):
        assert "编号" in user or "推断" in user
        # 模型按「编号=取值」逐行回答
        return "\n".join(f"{no}={name}" for no, name in truth.items())

    monkeypatch.setattr(llm_client, "call_llm", fake_text)
    verdict = await ai_agent.decide_submit(room, bot)
    assert verdict["source"] == "llm"
    assert verdict["board"] == truth
    assert verdict["reasoning"], "推理痕迹不能为空"


async def test_reasoning_round_rejects_bad_board(monkeypatch):
    """模型给错自己那格 → 直接拒绝，退回约束传播（自己格必须对）。"""
    room, players = make_room(3)
    bot = players[0]
    wrong = {1: "折纸诗人", 2: "雾港更夫", 3: "青苔占星师"}

    async def bad(system, user, timeout=15.0):
        return "1=折纸诗人\n2=雾港更夫\n3=青苔占星师"  # 1 号那格是错的

    monkeypatch.setattr(llm_client, "call_llm", bad)
    verdict = await ai_agent.decide_submit(room, bot)
    assert verdict["source"] == "propagation"
    assert verdict["board"][bot.room_no] == room.card_of(bot).name


async def test_reasoning_round_rejects_duplicate_values(monkeypatch):
    room, players = make_room(3)
    bot = players[0]

    async def dup(system, user, timeout=15.0):
        return "1=雾港更夫\n2=雾港更夫\n3=青苔占星师"  # 取值重复，必须被拒

    monkeypatch.setattr(llm_client, "call_llm", dup)
    verdict = await ai_agent.decide_submit(room, bot)
    assert verdict["source"] == "propagation"
    assert len(set(verdict["board"].values())) == len(verdict["board"])


async def test_reasoning_round_without_llm(monkeypatch):
    """没有模型也要给出一份合法看板。"""
    room, players = make_room(4)
    bot = players[3]

    async def empty(system, user, timeout=15.0):
        return ""

    monkeypatch.setattr(llm_client, "call_llm", empty)
    verdict = await ai_agent.decide_submit(room, bot)
    assert verdict["source"] == "propagation"
    assert set(verdict["board"]) == set(room.room_nos())


# ----------------------------------------------------------------------
# 模型降级链
# ----------------------------------------------------------------------
async def test_model_fallback_chain(monkeypatch):
    monkeypatch.delenv("LLM_DISABLE", raising=False)  # CI 的 job env 里带着它
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "primary-model")
    monkeypatch.setenv("LLM_MODEL_FALLBACKS", "backup-a, backup-b")
    assert llm_client.model_chain() == ["primary-model", "backup-a", "backup-b"]

    seen: list[str] = []

    async def fake(system, user, timeout, json_mode, model=None, budget=0):
        seen.append(model)
        if model == "primary-model":
            raise RuntimeError("429 rate limited")
        return "备份模型的回答"

    monkeypatch.setattr(llm_client, "_request", fake)
    out = await llm_client.call_llm("s", "u")
    assert out == "备份模型的回答"
    assert seen == ["primary-model", "backup-a"]  # 第一个失败即降级
    assert llm_client.stats()["lastModel"] == "backup-a"


async def test_all_models_fail_falls_back_to_empty(monkeypatch):
    monkeypatch.delenv("LLM_DISABLE", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "only-model")
    monkeypatch.delenv("LLM_MODEL_FALLBACKS", raising=False)

    async def boom(*args, **kwargs):
        raise RuntimeError("500")

    monkeypatch.setattr(llm_client, "_request", boom)
    assert await llm_client.call_llm("s", "u") == ""
    assert llm_client.stats()["fallbacks"] >= 1


def test_prompt_has_no_mapping_in_submit_round():
    """推理轮的 Prompt 同样不能出现「编号 → 昵称」成对信息。"""
    room, players = make_room(3)
    bot = players[2]
    ai_agent.refresh_candidates(room, bot)
    memory = ai_agent.memory_of(bot)
    text = ai_agent.build_submit_prompt(room, bot, memory)
    for p in players:
        if p.room_no == bot.room_no:
            continue
        for line in text.splitlines():
            assert not (str(p.room_no) in line and p.nickname in line), f"泄露：{line}"
