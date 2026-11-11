"""纯函数规则层：房间码、昵称、编号分配、看板判定、冷却、可见性裁剪。

这一层不碰 WebSocket、不碰 asyncio，方便单测与推理。
"""

from __future__ import annotations

import random
import re
from typing import Any, Iterable

from .models import (
    GameConfig,
    GameError,
    GameMode,
    PersonaCard,
    Player,
    Question,
    QuestionStatus,
    Room,
    Visibility,
)

NICKNAME_MAX = 16
ASK_TEXT_MAX = 200
ANSWER_TEXT_MAX = 400
ROOM_CODE_LEN = 6

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


# ----------------------------------------------------------------------
# 输入清洗
# ----------------------------------------------------------------------
def sanitize_text(raw: Any, max_len: int) -> str:
    """去首尾空白、压掉控制字符、限制长度。"""
    if not isinstance(raw, str):
        raise GameError("INVALID_PAYLOAD", "文本必须是字符串")
    text = _CTRL.sub(" ", raw).strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def normalize_nickname(raw: Any) -> str:
    """昵称：非空、≤16 字符、不能含控制字符。"""
    if not isinstance(raw, str):
        raise GameError("NICKNAME_INVALID", "昵称必须是字符串")
    nick = sanitize_text(raw, NICKNAME_MAX)
    if not nick:
        raise GameError("NICKNAME_INVALID", "昵称不能为空")
    return nick


# ----------------------------------------------------------------------
# 房间码
# ----------------------------------------------------------------------
def generate_room_code(taken: Iterable[str]) -> str:
    """生成 6 位数字房间码，全局唯一（内存里查重，最多试 2000 次）。"""
    taken_set = set(taken)
    for _ in range(2000):
        code = "".join(random.choice("0123456789") for _ in range(ROOM_CODE_LEN))
        if code not in taken_set:
            return code
    raise GameError("ROOM_CODE_EXHAUSTED", "房间码生成失败，请重试")


# ----------------------------------------------------------------------
# 编号分配
# ----------------------------------------------------------------------
def assign_room_numbers(player_ids: list[str]) -> dict[str, int]:
    """随机分配 1..n 的编号（洗牌后按玩家顺序发）。"""
    n = len(player_ids)
    numbers = list(range(1, n + 1))
    random.shuffle(numbers)
    return {pid: numbers[i] for i, pid in enumerate(player_ids)}


# ----------------------------------------------------------------------
# 看板
# ----------------------------------------------------------------------
def normalize_board(raw: Any) -> dict[int, str]:
    """把客户端看板 `{编号: 昵称}` 规范成 `{int: str}`。

    宽容点：键可以是 "1" 或 1；值可以是昵称或 playerId（由判定时再解析）。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise GameError("INVALID_PAYLOAD", "看板必须是 {编号: 昵称} 对象")
    out: dict[int, str] = {}
    for key, val in raw.items():
        try:
            no = int(key)
        except (TypeError, ValueError):
            raise GameError("INVALID_PAYLOAD", f"看板编号必须是整数：{key!r}")
        if not isinstance(val, str):
            raise GameError("INVALID_PAYLOAD", "看板的值必须是昵称字符串")
        out[no] = val.strip()
    return out


def normalize_board_for_storage(raw: Any) -> dict[str, str]:
    """存草稿用：统一存成 {字符串编号: 昵称}，方便原样回传前端。"""
    board = normalize_board(raw)
    return {str(k): v for k, v in sorted(board.items())}


def truth_for(room: Room) -> dict[int, str]:
    """当前模式的「编号 → 正确答案」真值表。

    REAL   : 编号 → 昵称
    PERSONA: 编号 → 人设卡名（卡按 assigned_room_no 落到编号上）
    """
    if room.game_mode == GameMode.PERSONA.value:
        return {
            c.assigned_room_no: c.name
            for c in room.cards
            if c.assigned_room_no is not None
        }
    return {p.room_no: p.nickname for p in room.players.values() if p.room_no is not None}


def _resolve_guess(room: Room, guess: str) -> str | None:
    """把玩家填的值解析成「同一套真值词汇」。

    REAL   : 接受昵称或 playerId，统一成昵称
    PERSONA: 接受卡名或卡 id，统一成卡名
    """
    guess = (guess or "").strip()
    if not guess:
        return None
    if room.game_mode == GameMode.PERSONA.value:
        for card in room.cards:
            if guess == card.name or guess == card.id:
                return card.name
        return None
    by_nick = {p.nickname: p for p in room.players.values()}
    by_id = {p.id: p for p in room.players.values()}
    hit = by_nick.get(guess) or by_id.get(guess)
    return hit.nickname if hit else None


def judge_board(board: dict[int, str], room: Room, player: "Player | None" = None) -> dict[str, Any]:
    """判定看板是否「全对」（模式无关的外壳，内部按 game_mode 取真值）。

    自己那格是「白送的」：客户端不填、或老客户端根本没提交它，
    这里都按真值补齐，避免出现「明明全对却被判错」。
    """
    expected = truth_for(room)
    if player is not None and player.room_no in expected and not board.get(player.room_no):
        board = {**board, player.room_no: expected[player.room_no]}
    missing = sorted(no for no in expected if no not in board or not board[no])

    wrong: list[int] = []
    resolved: dict[int, str] = {}
    for no, guess in board.items():
        if no not in expected or not guess:
            continue
        hit = _resolve_guess(room, guess)
        resolved[no] = hit or guess
        if hit != expected[no]:
            wrong.append(no)
    extra = sorted(no for no in board if no not in expected)
    return {
        "correct": not missing and not wrong and not extra,
        "missing": missing,
        "wrong": sorted(wrong),
        "extra": extra,
        "resolved": resolved,
    }


# ----------------------------------------------------------------------
# 人设卡
# ----------------------------------------------------------------------
CARD_NAME_MAX = 20
CARD_CONTENT_MAX = 300


def normalize_card_name(raw: Any, taken_names: Iterable[str]) -> str:
    """卡名：去首尾空格后 1–20 字，且同房间唯一（超长直接拒绝，不静默截断）。"""
    if not isinstance(raw, str):
        raise GameError("INVALID_PAYLOAD", "卡名必须是字符串")
    name = _CTRL.sub(" ", raw).strip()
    if not name:
        raise GameError("CARD_NAME_INVALID", "卡名不能为空")
    if len(name) > CARD_NAME_MAX:
        raise GameError("CARD_NAME_INVALID", f"卡名最多 {CARD_NAME_MAX} 个字")
    if name in set(taken_names):
        raise GameError("CARD_NAME_TAKEN", "这个卡名已经被用过了")
    return name


def normalize_card_content(raw: Any) -> str:
    """卡面描述：≤300 字，不能为空（超长直接拒绝）。"""
    if not isinstance(raw, str):
        raise GameError("INVALID_PAYLOAD", "卡面内容必须是字符串")
    content = _CTRL.sub(" ", raw).strip()
    if not content:
        raise GameError("CARD_CONTENT_INVALID", "卡面内容不能为空")
    if len(content) > CARD_CONTENT_MAX:
        raise GameError("CARD_CONTENT_INVALID", f"卡面最多 {CARD_CONTENT_MAX} 个字")
    return content


def derange(cards: list[PersonaCard], players: list[Player]) -> dict[str, PersonaCard]:
    """错位分配：保证每人拿到的卡 author_id ≠ 自己 id。

    先随机洗牌（最多 100 次），仍不成则退化为整体旋转兜底。
    """
    if len(cards) != len(players):
        raise GameError("CARD_COUNT_MISMATCH", "卡数量与玩家数量不一致")

    for _ in range(100):
        shuffled = cards[:]
        random.shuffle(shuffled)
        if len({c.id for c in shuffled}) == len(shuffled) and all(
            c.author_id != p.id for c, p in zip(shuffled, players)
        ):
            return {p.id: c for c, p in zip(shuffled, players)}

    rotated = cards[:]
    for _ in range(len(cards)):
        rotated = rotated[1:] + rotated[:1]
        if all(c.author_id != p.id for c, p in zip(rotated, players)):
            return {p.id: c for c, p in zip(rotated, players)}
    raise GameError("CARD_ASSIGN_FAILED", "无法完成错位分配")


# ----------------------------------------------------------------------
# 冷却
# ----------------------------------------------------------------------
def cooldown_after_wrong(config: GameConfig, *, forced: bool, was_in_cooldown: bool) -> int:
    """提交错误后的冷却轮数。

    - 普通轮：冷却 3 轮（config.cooldown_rounds）
    - 强制提交轮：罚 1 轮；若提交时本身在冷却期则罚 2 轮
    """
    if not forced:
        return config.cooldown_rounds
    return config.forced_wrong_in_cooldown_penalty if was_in_cooldown else config.forced_wrong_penalty


def decrement_cooldowns(room: Room) -> list[dict[str, Any]]:
    """每轮结束所有冷却 -1，返回变化列表（供广播 cooldown:updated）。"""
    changed: list[dict[str, Any]] = []
    for p in room.players.values():
        if p.cooldown > 0:
            p.cooldown = max(0, p.cooldown - 1)
            changed.append({"playerId": p.id, "cooldown": p.cooldown})
    return changed


# ----------------------------------------------------------------------
# 可见性裁剪（第一周只实现 PUBLIC）
# ----------------------------------------------------------------------
def visibility_for(room: "Room") -> Visibility:
    """房间配置里的问答模式 → 问题对象的可见性。"""
    raw = str(getattr(room.config, "qa_visibility", "PUBLIC") or "PUBLIC").upper()
    try:
        return Visibility(raw)
    except ValueError:
        return Visibility.PUBLIC


def clip_text(
    visibility: Visibility,
    text: str | None,
    *,
    asker_id: str,
    target_id: str,
    viewer_id: str | None,
    kind: str = "question",
) -> str | None:
    """按可见性裁剪问答内容。

    第一周：
    - PUBLIC  → 所有人看到原文
    - SEMI    → 骨架：只有提问者与被问者看得到（占位实现，规则未定稿）
    - PRIVATE → 骨架：只有被问者看得到（占位实现，规则未定稿）
    """
    if text is None:
        return None
    party = viewer_id in (asker_id, target_id)
    if visibility is Visibility.PUBLIC:
        # 全公开：问题和回答都全员可见
        return text
    if visibility is Visibility.SEMI:
        # 半公开：问题全员可见，回答只有当事人（问者/被问者）看得到
        return text if (kind != "answer" or party) else None
    if visibility is Visibility.PRIVATE:
        # 私密：问题与回答都只有当事人看得到
        return text if party else None
    return None


# ----------------------------------------------------------------------
# 回放条目
# ----------------------------------------------------------------------
def build_replay_items(
    room: Room, round_no: int | None = None, viewer_id: str | None = None
) -> list[dict[str, Any]]:
    """构建本轮回放条目：每条提问 + 它的回答（已回答 / 超时）。

    按 viewer_id 裁剪：私密问答对旁观者整条隐藏；半公开的回答对旁观者只留「已作答」。
    """
    items: list[dict[str, Any]] = []
    for q in room.round_questions(round_no):
        party = viewer_id is None or viewer_id in (q.asker_id, q.target_id)
        if q.visibility is Visibility.PRIVATE and not party:
            continue
        asker = room.player(q.asker_id)
        target = room.player(q.target_id)
        items.append(
            {
                "kind": "question",
                "questionId": q.id,
                "askerId": q.asker_id,
                "askerNickname": asker.nickname if asker else "?",
                "targetId": q.target_id,
                "targetNickname": target.nickname if target else "?",
                "text": clip_text(
                    q.visibility,
                    q.text,
                    asker_id=q.asker_id,
                    target_id=q.target_id,
                    viewer_id=viewer_id,
                    kind="question",
                ),
                "targetNo": target.room_no if target else None,
                "status": q.status.value,
                "visibility": q.visibility.value,
            }
        )
        if q.status is not QuestionStatus.PENDING:
            items.append(
                {
                    "kind": "answer",
                    "questionId": q.id,
                    "targetId": q.target_id,
                    "targetNickname": target.nickname if target else "?",
                    "answer": clip_text(
                        q.visibility,
                        q.answer,
                        asker_id=q.asker_id,
                        target_id=q.target_id,
                        viewer_id=viewer_id,
                        kind="answer",
                    ),
                    "masked": (
                        q.visibility is Visibility.SEMI
                        and not party
                        and q.answer is not None
                    ),
                    "timedOut": q.status is QuestionStatus.TIMEOUT,
                }
            )
    return items


def question_public_payload(
    room: Room, q: Question, viewer_id: str | None = None
) -> dict[str, Any] | None:
    """question:public 载荷：提问本身是公开信息。"""
    asker = room.player(q.asker_id)
    target = room.player(q.target_id)
    if q.visibility is Visibility.PRIVATE and viewer_id not in (q.asker_id, q.target_id):
        return None  # 私密：旁观者连「有人被问了」都不该知道
    return {
        "type": "question:public",
        "questionId": q.id,
        "round": q.round,
        "askerId": q.asker_id,
        "askerNickname": asker.nickname if asker else "?",
        "targetId": q.target_id,
        "targetNickname": target.nickname if target else "?",
        "targetNo": target.room_no if target else None,  # 被问的是几号（公开信息）
        "text": clip_text(
            q.visibility,
            q.text,
            asker_id=q.asker_id,
            target_id=q.target_id,
            viewer_id=viewer_id,
            kind="question",
        ),
        "visibility": q.visibility.value,
        "status": q.status.value,
    }


def answer_public_payload(
    room: Room, q: Question, viewer_id: str | None = None
) -> dict[str, Any] | None:
    """answer:public 载荷：回答（或超时）也是公开信息。"""
    target = room.player(q.target_id)
    if q.visibility is Visibility.PRIVATE and viewer_id not in (q.asker_id, q.target_id):
        return None
    party = viewer_id in (q.asker_id, q.target_id)
    return {
        "type": "answer:public",
        "questionId": q.id,
        "round": q.round,
        "targetId": q.target_id,
        "targetNickname": target.nickname if target else "?",
        "targetNo": target.room_no if target else None,
        "answer": clip_text(
            q.visibility,
            q.answer,
            asker_id=q.asker_id,
            target_id=q.target_id,
            viewer_id=viewer_id,
            kind="answer",
        ),
        "status": q.status.value,
        "timedOut": q.status is QuestionStatus.TIMEOUT,
        # 半公开：非当事人收到的是「已作答，但内容看不到」
        "masked": q.visibility is Visibility.SEMI and not party and q.answer is not None,
    }

# ----------------------------------------------------------------------
# 赛后复盘：名场面时间线
# ----------------------------------------------------------------------
HIGHLIGHT_LABELS = {
    "opening": "开场第一问",
    "timeout": "超时未答",
    "sharp": "神准提问",
    "self_reveal": "自曝身份",
    "longest": "名场面台词",
}


def build_timeline(
    room: "Room", winner_id: str | None = None, viewer_id: str | None = None
) -> list[dict[str, Any]]:
    """把整局的公开问答整理成时间线（含高亮标记），用于谢幕复盘。

    高亮规则（全部基于事实，不做语义猜测）：
    - opening      ：全场第一问
    - timeout      ：该问题超时未答
    - sharp        ：胜者在这一问之后，把被问者猜对了（他当时问对了人）
    - self_reveal  ：回答里出现了自己的昵称或自己拿到的卡名（自曝）
    - longest      ：该轮字数最多的回答
    """
    items: list[dict[str, Any]] = []
    winner = room.player(winner_id) if winner_id else None
    winner_board = (winner.submitted_board or {}) if winner else {}

    by_round: dict[int, list[Any]] = {}
    for q in sorted(room.questions, key=lambda x: (x.round, x.created_at)):
        by_round.setdefault(q.round, []).append(q)

    for round_no in sorted(by_round):
        questions = by_round[round_no]
        # 本轮最长回答
        answered = [
            q for q in questions if q.status is QuestionStatus.ANSWERED and q.answer
        ]
        longest_id = max(answered, key=lambda q: len(q.answer or "")).id if answered else None

        for q in questions:
            party = viewer_id is None or viewer_id in (q.asker_id, q.target_id)
            if q.visibility is Visibility.PRIVATE and not party:
                continue
            asker = room.player(q.asker_id)
            target = room.player(q.target_id)
            tags: list[str] = []

            if q is room.questions[0] if room.questions else False:
                tags.append("opening")
            if q.status is QuestionStatus.TIMEOUT:
                tags.append("timeout")
            if q.id == longest_id:
                tags.append("longest")

            if q.status is QuestionStatus.ANSWERED and q.answer:
                own_values = {target.nickname} if target else set()
                card = room.card_of(target) if target else None
                if card is not None:
                    own_values.add(card.name)
                if any(v and v in q.answer for v in own_values):
                    tags.append("self_reveal")

            if winner_board and target is not None and target.room_no is not None:
                guessed = winner_board.get(str(target.room_no)) or winner_board.get(
                    target.room_no
                )
                if guessed and _answer_matches(room, guessed, target):
                    tags.append("sharp")

            # 答案相关的高亮（自曝 / 最长回答）对非当事人没有意义，也会泄露内容
            if not party:
                tags = [t for t in tags if t not in ("self_reveal", "longest")]
            masked = (
                q.visibility is Visibility.SEMI and not party and q.answer is not None
            )

            items.append(
                {
                    "questionId": q.id,
                    "round": q.round,
                    "askerNickname": asker.nickname if asker else "?",
                    "askerId": q.asker_id,
                    "targetNo": target.room_no if target else None,
                    "targetNickname": target.nickname if target else "?",
                    "visibility": q.visibility.value,
                    "question": clip_text(
                        q.visibility,
                        q.text,
                        asker_id=q.asker_id,
                        target_id=q.target_id,
                        viewer_id=viewer_id,
                        kind="question",
                    ),
                    "answer": clip_text(
                        q.visibility,
                        q.answer,
                        asker_id=q.asker_id,
                        target_id=q.target_id,
                        viewer_id=viewer_id,
                        kind="answer",
                    ),
                    "masked": masked,
                    "status": q.status.value,
                    "timedOut": q.status is QuestionStatus.TIMEOUT,
                    "highlights": tags,
                    "highlightLabels": [HIGHLIGHT_LABELS[t] for t in tags],
                }
            )
    return items


def _answer_matches(room: "Room", guess: str, target: "Player") -> bool:
    """胜者看板里这条是否等于该玩家的真实身份。"""
    if room.game_mode == GameMode.PERSONA.value:
        card = room.card_of(target)
        return bool(card) and (guess == card.name or guess == card.id)
    return guess in (target.nickname, target.id)
