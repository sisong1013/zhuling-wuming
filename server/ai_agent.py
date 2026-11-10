"""AI 玩家大脑：记忆、Prompt 组装、决策。

⚠️ 防作弊铁律
    组装 Prompt 时只允许出现：
      - 自己的编号 + 自己拿到的人设卡
      - 公开问答历史（谁问了谁什么、怎么答的）
      - 全场卡名表 / 全场昵称表（这两张表本身是公开信息）
      - 可选目标（只给编号，绝不给「编号→昵称」对应）
    任何「编号 ↔ 昵称」的成对信息都不允许进 Prompt —— 单元测试会扫描 Prompt 里
    每个其他人「编号」与「昵称」共行的情况来抓违规（见 tests/test_week3_ai_memory.py）。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

import re

from . import ai, llm_client
from .models import GameMode, Phase, QuestionStatus, Room

# ----------------------------------------------------------------------
# 记忆
# ----------------------------------------------------------------------


@dataclass
class AIMemory:
    """AI 的私有记忆：公开历史 + 自己的看板（带置信度）。"""

    public_log: list[dict[str, Any]] = field(default_factory=list)
    board: dict[int, str] = field(default_factory=dict)
    confidence: dict[int, float] = field(default_factory=dict)
    asked_targets: set[int] = field(default_factory=set)
    candidates: dict[int, set[str]] = field(default_factory=dict)  # 编号 → 还可能的取值
    reasoning: list[str] = field(default_factory=list)  # 推理痕迹（调试/复盘用）
    prompts: list[dict[str, Any]] = field(default_factory=list)  # 最近的 Prompt（调试用）
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def record_qa(
        self,
        round_no: int,
        asker_nickname: str,
        target_no: int | None,
        question: str,
        answer: str | None,
    ) -> None:
        self.public_log.append(
            {
                "round": round_no,
                "asker": asker_nickname,
                "targetNo": target_no,
                "question": question,
                "answer": answer,
            }
        )
        if target_no is not None:
            self.asked_targets.add(target_no)

    def log_history_lines(self, limit: int = 12) -> list[str]:
        lines: list[str] = []
        for item in self.public_log[-limit:]:
            target = item.get("targetNo")
            target_txt = f"{target} 号" if target is not None else "某人"
            answer = item.get("answer")
            answer_txt = answer if answer else "（超时未答）"
            lines.append(
                f"第{item['round']}轮 {item['asker']} 问 {target_txt}：{item['question']} —— 答：{answer_txt}"
            )
        return lines


def memory_of(player: Any) -> AIMemory:
    """取（或建）该 AI 的记忆。"""
    if getattr(player, "ai_memory", None) is None:
        player.ai_memory = AIMemory()
    return player.ai_memory


# ----------------------------------------------------------------------
# 公开信息组装
# ----------------------------------------------------------------------


def public_qa_lines(room: Room, limit: int = 12) -> list[str]:
    """从房间的题目列表重建「公开问答历史」（只用公开字段）。"""
    lines: list[str] = []
    done = [q for q in room.questions if q.status is not QuestionStatus.PENDING][-limit:]
    for q in done:
        asker = room.player(q.asker_id)
        target = room.player(q.target_id)
        asker_nick = asker.nickname if asker else "?"
        target_no = target.room_no if target else None
        target_txt = f"{target_no} 号" if target_no is not None else "某人"
        answer = q.answer if q.status is QuestionStatus.ANSWERED else "（超时未答）"
        lines.append(f"第{q.round}轮 {asker_nick} 问 {target_txt}：{q.text} —— 答：{answer}")
    return lines


def board_lines(memory: AIMemory, room: Room) -> list[str]:
    lines: list[str] = []
    for no in room.room_nos():
        guess = memory.board.get(no)
        conf = memory.confidence.get(no, 0.0)
        if guess:
            lines.append(f"{no} 号 → {guess}（置信度 {conf:.1f}）")
        else:
            lines.append(f"{no} 号 → 还不确定")
    return lines


PHASE1_SYSTEM = """你在玩一个社交推理剧团游戏「谁是几号」。你是其中一名玩家（AI），必须像普通玩家一样用提问和推理来猜测。

规则回顾：
- 场上每个编号（1 号、2 号……）对应一个人/一张卡，但没人知道对应关系；
- 你只知道自己的编号，以及你自己拿到的东西；
- 每轮你只能做一次动作：向某个人提问（ASK）、提交看板（SUBMIT）、或放弃（SKIP）；
- 提问会公开给所有人，对方必须回答；提交看板若全对就立刻获胜，若答错进冷却；
- 你绝对不能知道、也不能假设自己掌握「编号背后是谁」的答案，只能靠问答历史推理。

问题要像人问人：可以盘问作息、见过谁、怕什么、说话方式，不要直接问「你的卡名是什么」，也不要报自己的编号。
别人已经问过的问题不要重复。

输出格式（极其重要）：只输出一行，三个选项之一：
ASK|<编号数字>|<一句话问题>
SUBMIT
SKIP
不要 JSON、不要解释、不要 markdown。"""


def build_phase1_prompt(room: Room, player: Any) -> tuple[str, str]:
    """组装第一幕决策 Prompt（严格不含「编号→昵称」映射）。"""
    memory = memory_of(player)
    mode = room.game_mode
    lines: list[str] = []

    lines.append(f"【你】你是 {player.room_no} 号，昵称「{player.nickname}」。")
    if mode == GameMode.PERSONA.value:
        card = room.card_of(player)
        if card is not None:
            lines.append(f"【你拿到的卡】卡名：{card.name}")
            lines.append(f"【卡面】{card.content}")
        lines.append(f"【全场卡名表（公开）】{'、'.join(room.card_names())}")
    else:
        lines.append(f"【全场昵称表（公开）】{'、'.join(p.nickname for p in room.ordered_players())}")

    lines.append(f"【当前】第 {room.round} 轮，第一幕（讯问）。")
    lines.append(f"【你的冷却】{'冷却中，本轮只能放弃' if player.cooldown > 0 else '可以正常行动'}")

    qa = memory.log_history_lines() or public_qa_lines(room)
    lines.append("【公开问答历史】" + ("\n" + "\n".join(qa) if qa else "（还没有人说过的记录）"))
    lines.append("【你的看板】\n" + "\n".join(board_lines(memory, room)))

    targets = [no for no in room.room_nos() if no != player.room_no]
    lines.append(f"【可以提问的对象】（只写了编号）：{'、'.join(str(t) for t in targets)} 号")
    lines.append(
        "【提示】猜得对自己那格是白送的（你知道自己的身份），别人那格要靠问答历史推断。"
    )
    lines.append("现在输出你的 JSON 决策。")
    return PHASE1_SYSTEM, "\n".join(lines)


# ----------------------------------------------------------------------
# 决策
# ----------------------------------------------------------------------


def _guess_pool(room: Room) -> list[str]:
    if room.game_mode == GameMode.PERSONA.value:
        return room.card_names()
    return [p.nickname for p in room.ordered_players()]


def fallback_board(room: Room, player: Any) -> dict[int, str]:
    """离线兜底看板：先用约束传播，再用排除法补位（保证一人一号，不重复）。"""
    memory = memory_of(player)
    pool = _guess_pool(room)
    refresh_candidates(room, player)

    board: dict[int, str] = {}
    own_value = _own_identity(room, player)
    if own_value:
        board[player.room_no] = own_value

    used = set(board.values())
    for no in room.room_nos():
        if no == player.room_no:
            continue
        guess = memory.board.get(no) or next(iter(memory.candidates.get(no, set())), None)
        if not guess or guess in used:
            remaining = [c for c in pool if c not in used]
            guess = remaining[0] if remaining else None
        if guess:
            board[no] = guess
            used.add(guess)
            memory.board[no] = guess
            memory.confidence.setdefault(no, 0.4)
    return board


def _pick_fallback_question(room: Room, player: Any) -> tuple[int, str] | None:
    memory = memory_of(player)
    targets = [no for no in room.room_nos() if no != player.room_no]
    fresh = [t for t in targets if t not in memory.asked_targets] or targets
    if not fresh:
        return None
    target = random.choice(fresh)
    templates = [
        "你昨晚在剧团的哪盏灯下待得最久？",
        "如果今晚有人偷走你的道具，你第一句话会说什么？",
        "你最不喜欢的台词是哪一句？为什么？",
        "散场以后你会先做什么？",
        "在场这些人里，你最不想和谁对戏？",
    ]
    return target, random.choice(templates)


async def decide_phase1(room: Room, player: Any, timeout: float = 15.0) -> dict[str, Any]:
    """产出第一幕动作：{"action": "ASK|SUBMIT|SKIP", ...}。永不抛异常。"""
    memory = memory_of(player)
    system, user = build_phase1_prompt(room, player)
    memory.prompts.append({"kind": "phase1", "system": system, "user": user})
    memory.prompts[:] = memory.prompts[-20:]

    raw = await llm_client.call_llm(system, user, timeout=timeout)
    decision = parse_decision(raw, room, player)
    data = llm_client.parse_json(raw) if decision is None else None
    if data and decision is None:
        action = str(data.get("action", "")).upper()
        if action == "ASK":
            try:
                target = int(data.get("target_room"))
            except (TypeError, ValueError):
                target = None
            text = str(data.get("question_text", "")).strip()
            if target and target != player.room_no and text:
                decision = {"action": "ASK", "targetRoomNo": target, "text": text[:120]}
        elif action == "SUBMIT":
            decision = {"action": "SUBMIT", "board": None}  # 真正提交前会单独跑一次推理轮

        elif action == "SKIP":
            decision = {"action": "SKIP"}

    if decision is None:
        decision = _fallback_decision(room, player)

    memory.log(f"决策：{json.dumps(decision, ensure_ascii=False)}")
    return decision


def _as_room_no(value: object) -> int | None:
    """把 2 / "2" / "2号" / "2 号" 都认成 2。"""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def parse_decision(raw: str, room: Room, player: Any) -> dict[str, Any] | None:
    """解析模型输出，三种来源都认：

    ① 单行契约：ASK|2|问题 / SUBMIT / SKIP
    ② 模型自创的 JSON：{"action":"ask","target":"2号","question":"…"}
    ③ 中文动词开头的一行：问你…/ 提交 / 跳过（兜底识别 action 关键词）
    """
    if not raw:
        return None

    # ① 单行契约（从最后一行往前找，容忍前言废话）
    for line in reversed([ln.strip() for ln in raw.splitlines() if ln.strip()]):
        upper = line.upper()
        if upper.startswith("ASK"):
            parts = re.split(r"[|｜]", line)
            if len(parts) >= 3:
                target = _as_room_no(parts[1])
                text = parts[2].strip()
                if target and target != player.room_no and text:
                    return {"action": "ASK", "targetRoomNo": target, "text": text[:120]}
        if upper.startswith("SUBMIT"):
            return {"action": "SUBMIT", "board": None}
        if upper.startswith("SKIP"):
            return {"action": "SKIP"}

    # ② 模型自创 JSON
    data = llm_client.parse_json(raw)
    if isinstance(data, dict):
        action = str(data.get("action") or data.get("类型") or "").strip().lower()
        if action in {"ask", "问", "提问"}:
            target = _as_room_no(
                data.get("target_room")
                or data.get("targetRoomNo")
                or data.get("target")
                or data.get("target_room_no")
                or data.get("询问对象")
            )
            text = str(
                data.get("question_text")
                or data.get("question")
                or data.get("text")
                or data.get("问题")
                or ""
            ).strip()
            if target and target != player.room_no and text:
                return {"action": "ASK", "targetRoomNo": target, "text": text[:120]}
        if action in {"submit", "交", "提交", "呈上"}:
            board = data.get("board") if isinstance(data.get("board"), dict) else None
            return {"action": "SUBMIT", "board": board}
        if action in {"skip", "跳过", "pass", "略过"}:
            return {"action": "SKIP"}

    return None


def _fallback_decision(room: Room, player: Any) -> dict[str, Any]:
    """LLM 不可用/输出非法时的确定性策略：冷却→放弃；能问就问；否则交看板。"""
    if player.cooldown > 0:
        return {"action": "SKIP", "reason": "cooldown"}
    if room.round >= room.config.forced_submit_round:
        return {"action": "SUBMIT", "board": None, "reason": "forced"}
    picked = _pick_fallback_question(room, player)
    if picked is not None:
        target, text = picked
        return {"action": "ASK", "targetRoomNo": target, "text": text, "reason": "fallback_ask"}
    return {"action": "SUBMIT", "board": None, "reason": "fallback_submit"}


def _log(memory: AIMemory, line: str) -> None:  # pragma: no cover - 便捷方法挂载
    memory.decisions.append({"line": line})


AIMemory.log = _log  # type: ignore[attr-defined]




# ----------------------------------------------------------------------
# 约束传播：每个编号只能用「一个人/一张卡」，这是个双射问题
# ----------------------------------------------------------------------
def refresh_candidates(room: Room, player: Any) -> dict[int, set[str]]:
    """维护每个编号的候选集，并做两级传播：

    1. 每个候选值全局唯一（一个人只能对应一个编号）；
    2. 自己那格已知（白送），于是该值不再属于别人；
    3. 某编号只剩一个候选 → 直接确定，并从其他人的候选里剔除（连锁）。
    """
    memory = memory_of(player)
    pool = _guess_pool(room)

    if not memory.candidates:
        memory.candidates = {no: set(pool) for no in room.room_nos()}

    for no in room.room_nos():
        memory.candidates.setdefault(no, set(pool))

    own_value = _own_identity(room, player)
    if own_value:
        memory.board[player.room_no] = own_value
        memory.confidence[player.room_no] = 1.0
        for no in room.room_nos():
            if no == player.room_no:
                memory.candidates[no] = {own_value}
            else:
                memory.candidates[no].discard(own_value)

    # 连锁：单一候选 → 确定 → 从其他格剔除，直到稳定
    for _ in range(len(room.room_nos()) + 1):
        changed = False
        for no, options in memory.candidates.items():
            if no in memory.board:
                continue
            if len(options) == 1:
                value = next(iter(options))
                memory.board[no] = value
                memory.confidence[no] = max(memory.confidence.get(no, 0.0), 0.6)
                for other, other_options in memory.candidates.items():
                    if other != no and value in other_options:
                        other_options.discard(value)
                        changed = True
        if not changed:
            break
    return memory.candidates


def _own_identity(room: Room, player: Any) -> str:
    """自己那格的正确答案（PERSONA 是自己拿到的卡名，REAL 是自己昵称）。"""
    if room.game_mode == GameMode.PERSONA.value:
        card = room.card_of(player)
        return card.name if card else ""
    return player.nickname


async def decide_submit(room: Room, player: Any, timeout: float = 15.0) -> dict[str, Any]:
    """提交看板前的「推理轮」：先让模型基于历史推一遍，再退回约束传播。

    返回 {"board": {编号: 值}, "reasoning": str, "source": "llm"|"propagation"}
    """
    memory = memory_of(player)
    refresh_candidates(room, player)

    system = PHASE1_SYSTEM
    user = build_submit_prompt(room, player, memory)
    memory.prompts.append({"kind": "submit", "system": system, "user": user})
    memory.prompts[:] = memory.prompts[-20:]

    raw = await llm_client.call_llm(system, user, timeout=timeout)
    lines_board = parse_board_lines(raw, room)
    if lines_board and _board_is_plausible(room, player, lines_board):
        for no, value in lines_board.items():
            memory.board[no] = value
            memory.confidence[no] = 1.0
        reason = "按问答史排除（模型逐行给出）"
        memory.log(f"推理轮(LLM)：{reason}")
        return {"board": lines_board, "reasoning": reason, "source": "llm"}

    data = llm_client.parse_json(raw)
    if data and isinstance(data.get("board"), dict):
        board: dict[int, str] = {}
        for key, value in data["board"].items():
            try:
                no = int(key)
            except (TypeError, ValueError):
                continue
            board[no] = str(value).strip()
        if _board_is_plausible(room, player, board):
            for no, value in board.items():
                memory.board[no] = value
                memory.confidence[no] = 1.0
            reason = str(data.get("reasoning", "")).strip()[:200]
            memory.log(f"推理轮(LLM)：{reason}")
            return {"board": board, "reasoning": reason, "source": "llm"}

    board = fallback_board(room, player)
    reason = "按编号互斥关系收敛（约束传播）" if len(memory.board) >= len(room.room_nos()) else "约束传播 + 排除法补位"
    memory.log(f"推理轮(传播)：{reason}")
    return {"board": board, "reasoning": reason, "source": "propagation"}


BOARD_LINE = re.compile(r"^\s*(\d{1,2})\s*[=:：＝]\s*(.+?)\s*$")


def parse_board_lines(raw: str, room: Room) -> dict[int, str] | None:
    """解析「编号=取值」逐行格式；不完整则返回 None。"""
    board: dict[int, str] = {}
    for line in (raw or "").splitlines():
        m = BOARD_LINE.match(line.replace("**", ""))
        if not m:
            continue
        no = int(m.group(1))
        value = m.group(2).strip().strip("，,。.、")
        if no in room.room_nos() and value:
            board[no] = value
    return board or None


def _board_is_plausible(room: Room, player: Any, board: dict[int, str]) -> bool:
    """模型给的看板必须：覆盖全部编号、取值在池内、值不重复、自己那格正确。"""
    pool = set(_guess_pool(room))
    if set(board) != set(room.room_nos()):
        return False
    if any(not value or value not in pool for value in board.values()):
        return False
    if len(set(board.values())) != len(board):  # 一人一号，不能重复
        return False
    own = _own_identity(room, player)
    return not own or board.get(player.room_no) == own


def build_submit_prompt(room: Room, player: Any, memory: AIMemory) -> str:
    """提交看板的 Prompt：公开信息 + 自己的看板，要求给出完整推断。"""
    mode = room.game_mode
    lines = [f"【你】你是 {player.room_no} 号，昵称「{player.nickname}」。"]
    if mode == GameMode.PERSONA.value:
        card = room.card_of(player)
        if card is not None:
            lines.append(f"【你拿到的卡】{card.name}：{card.content}")
        lines.append(f"【全场卡名表（公开）】{'、'.join(room.card_names())}")
    else:
        lines.append(f"【全场昵称表（公开）】{'、'.join(p.nickname for p in room.ordered_players())}")

    qa = memory.log_history_lines() or public_qa_lines(room)
    lines.append("【公开问答历史】")
    lines.extend(qa or ["（还没有问过任何人）"])
    lines.append("【你的当前推断】")
    lines.extend(board_lines(memory, room))
    lines.append(
        "【输出格式】逐行给出每个编号，一行一个，不要解释、不要 JSON、不要 markdown："
    )
    lines.append("1=取值")
    lines.append("2=取值")
    lines.append(
        "（一人一号：取值不能重复；你自己那格就是你的身份；没把握的按排除法填满）"
    )
    return "\n".join(lines)

# ----------------------------------------------------------------------
# 第二幕作答
# ----------------------------------------------------------------------


async def answer_question(room: Room, player: Any, question: Any, timeout: float = 15.0) -> str:
    """按人设回答（PERSONA 按卡，REAL 按昵称）；永不返回空串。"""
    memory = memory_of(player)
    card: Any
    if room.game_mode == GameMode.PERSONA.value:
        card = room.card_of(player)
    else:
        card = {"name": player.nickname, "content": "你是剧团成员，语气自便。"}

    history = memory.log_history_lines(limit=4) or public_qa_lines(room, limit=4)
    text = await ai.ai_answer_as_persona_async(
        card, getattr(question, "text", ""), history=history, timeout=timeout
    )
    text = (text or "").strip()
    if not text:
        text = ai.ai_answer_as_persona(card, getattr(question, "text", ""))
    memory.log(f"作答：{text}")
    return text[:300]


# ----------------------------------------------------------------------
# 写卡
# ----------------------------------------------------------------------


async def write_card(room: Room, player: Any, timeout: float = 15.0) -> dict[str, Any]:
    """生成一张卡（LLM 优先），并保证同房间卡名唯一。"""
    data = await ai.generate_ai_card_async(timeout=timeout)
    name = str(data.get("name", "")).strip()[:20] or "无名的临时演员"
    content = str(data.get("content", "")).strip()[:300] or "没有人记得他的来历。"
    taken = set(room.card_names())
    base = name
    suffix = 1
    while name in taken:
        suffix += 1
        name = f"{base[:18]}·{suffix}"
    memory_of(player).log(f"写卡：{name}")
    return {"name": name, "content": content}


def phase_label(phase: Phase) -> str:
    return phase.value
