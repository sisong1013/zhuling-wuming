"""第 5 周：真模型的「单行契约」解析 + 写卡质量闸门（离线单测）。"""

from __future__ import annotations

import pytest

from server import ai, ai_agent
from server.models import GameConfig, GameMode, PersonaCard, Player, Room


class _Bot:
    room_no = 1


# ----------------------------------------------------------------------
# 写卡解析
# ----------------------------------------------------------------------
def test_parse_card_double_pipe():
    card = ai.parse_card("雾港更夫||每夜两点敲钟，谁问他为什么不睡，他就敲得更响。")
    assert card == {"name": "雾港更夫", "content": "每夜两点敲钟，谁问他为什么不睡，他就敲得更响"}


def test_parse_card_single_pipe():
    card = ai.parse_card("钟楼校准师 | 旧城钟楼里负责校准时间的人，最怕被问为什么总在午夜登塔。")
    assert card["name"] == "钟楼校准师"
    assert "午夜" in card["content"]


def test_parse_card_fullwidth_pipe():
    card = ai.parse_card("折纸诗人｜只在雨天折纸船，把写坏的诗折进去放走，写完就忘。")
    assert card["name"] == "折纸诗人"


def test_parse_card_from_json():
    card = ai.parse_card('{"name":"落雪书吏","content":"替人抄写说不出口的话，抄完记忆少一小块。"}')
    assert card["name"] == "落雪书吏"


def test_parse_card_from_markdown():
    raw = "## 卡名：守灯人\n\n他在灯塔上守了三十年，从不解释为什么不下塔。"
    card = ai.parse_card(raw)
    assert card["name"].endswith("守灯人")
    assert "灯塔" in card["content"]


def test_parse_card_rejects_garbage():
    assert ai.parse_card("") is None
    assert ai.parse_card("随便一句没有分隔符的话") is None


def test_clip_sentence_keeps_whole_sentence():
    long = "他每天都会擦拭那盏灯。" * 20
    clipped = ai._clip_sentence(long, limit=40)
    assert len(clipped) <= 41
    assert clipped.endswith("。")


def test_card_is_usable_gate():
    assert ai.card_is_usable({"name": "雾港更夫", "content": "每夜两点敲钟，讨厌被问为什么不睡所以敲更响。"})
    assert not ai.card_is_usable({"name": "苏晚", "content": "二十七岁，旧书店店主，说话慢半拍，记性极好。"})
    assert not ai.card_is_usable({"name": "雾港更夫", "content": "太短"})
    assert not ai.card_is_usable({"name": "FogKeeper", "content": "每夜两点敲钟，讨厌被问为什么不睡所以敲更响。"})


# ----------------------------------------------------------------------
# 决策解析
# ----------------------------------------------------------------------
def test_parse_decision_ask():
    got = ai_agent.parse_decision("ASK|2|你为什么总在夜里出门？", None, _Bot())
    assert got == {"action": "ASK", "targetRoomNo": 2, "text": "你为什么总在夜里出门？"}


def test_parse_decision_submit_and_skip():
    assert ai_agent.parse_decision("SUBMIT", None, _Bot())["action"] == "SUBMIT"
    assert ai_agent.parse_decision("SKIP", None, _Bot())["action"] == "SKIP"


def test_parse_decision_ignores_self_target():
    assert ai_agent.parse_decision("ASK|1|问自己？", None, _Bot()) is None


def test_parse_decision_handles_noise():
    raw = "我想了想，还是问吧。\nASK｜2｜你昨晚在哪？"
    got = ai_agent.parse_decision(raw, None, _Bot())
    assert got["targetRoomNo"] == 2


def test_parse_decision_rejects_garbage():
    assert ai_agent.parse_decision("我不确定。", None, _Bot()) is None


# ----------------------------------------------------------------------
# 看板逐行解析
# ----------------------------------------------------------------------
def test_parse_board_lines():
    room = Room(code="111111", config=GameConfig())
    room.players = {f"p{i}": Player(id=f"p{i}", nickname=f"人{i}", room_no=i + 1) for i in range(3)}
    board = ai_agent.parse_board_lines("1=雾港更夫\n2=折纸诗人\n3=落雪书吏", room)
    assert board == {1: "雾港更夫", 2: "折纸诗人", 3: "落雪书吏"}


def test_parse_board_lines_accepts_colon_and_bold():
    room = Room(code="222222", config=GameConfig())
    room.players = {f"p{i}": Player(id=f"p{i}", nickname=f"人{i}", room_no=i + 1) for i in range(2)}
    board = ai_agent.parse_board_lines("**1：**雾港更夫\n**2：**折纸诗人", room)
    assert board == {1: "雾港更夫", 2: "折纸诗人"}


def test_parse_board_lines_needs_content():
    room = Room(code="333333", config=GameConfig())
    room.players = {f"p{i}": Player(id=f"p{i}", nickname=f"人{i}", room_no=i + 1) for i in range(2)}
    assert ai_agent.parse_board_lines("我不太确定。", room) is None


def test_parse_decision_accepts_model_json():
    """思考型模型爱自创 JSON（target 还写成「1号」），也要认。"""
    raw = '{"action":"ask","target":"2号","question":"你昨晚在哪？"}'
    got = ai_agent.parse_decision(raw, None, _Bot())
    assert got == {"action": "ASK", "targetRoomNo": 2, "text": "你昨晚在哪？"}


def test_parse_decision_json_skip_and_submit():
    assert ai_agent.parse_decision('{"action":"skip"}', None, _Bot())["action"] == "SKIP"
    got = ai_agent.parse_decision('{"action":"submit","board":{"1":"x","2":"y"}}', None, _Bot())
    assert got["action"] == "SUBMIT"
    assert got["board"] == {"1": "x", "2": "y"}


def test_parse_decision_json_rejects_self_and_empty():
    assert ai_agent.parse_decision('{"action":"ask","target":"1号","question":"问自己"}', None, _Bot()) is None
    assert ai_agent.parse_decision('{"action":"ask","target":"3号"}', None, _Bot()) is None


def test_parse_decision_structural_board_is_validated_later():
    """宽松解析只负责取出来，合法性由 _board_is_plausible 兜。"""
    room = Room(code="444444", config=GameConfig())
    room.players = {f"p{i}": Player(id=f"p{i}", nickname=n, room_no=i + 1) for i, n in enumerate(["甲", "乙"])}
    bad = {1: "乙", 2: "乙"}  # 取值重复
    assert not ai_agent._board_is_plausible(room, room.players["p0"], bad)
