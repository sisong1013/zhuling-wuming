"""AI 内容生成：优先 LLM，失败/未配置时走确定性兜底。

对外两套 API：
- 同步：`generate_ai_card()`、`ai_answer_as_persona(card, question)` —— 纯离线兜底，永远可用
- 异步：`generate_ai_card_async()`、`ai_answer_as_persona_async(...)` —— 先问 LLM，拿不到就退回同步版

所有返回值都保证满足游戏规则（卡名 1–20 字、卡面 1–300 字、回答非空），
这样即使 LLM 抽风，写卡/答题也不会被判非法。
"""

from __future__ import annotations

import re

import random
from typing import Any

from . import llm_client

# 预设 AI 昵称（等待室添加 AI 时按顺序取）
AI_NICKNAMES = [
    "星辉剑士",
    "折纸诗人",
    "紫电琴师",
    "雾巷画匠",
    "琉璃小丑",
    "铁皮报幕员",
    "青苔占星师",
    "落雪的书吏",
]

CARD_POOL = [
    ("星夜的旅人", "常年在夜里赶路，说话总带着远方的风；不爱承诺，但答应的事一定做到。"),
    ("摆钟店的学徒", "对时间极度执着，回答前会先想清楚现在几点；讨厌别人打断他数秒。"),
    ("退隐的决斗者", "语气干脆，句子很短；讨厌拖泥带水的问题，喜欢用「是」「不是」结束对话。"),
    ("雨天的抄写员", "喜欢把别人的话重复一遍再回答，习惯用书面语，偶尔引用剧本。"),
    ("无名的厨师", "三句不离吃食，喜欢把问题和人比作一道菜，被夸厨艺时会害羞。"),
    ("守灯的老看门人", "话少、慢、爱叹气，记得剧团每一盏灯是哪年换的。"),
    ("月下的舞者", "说话带节奏，喜欢用比喻，情绪起伏大，被质疑时会绕圈走一步。"),
]

ANSWER_POOL = [
    "这个问题……容我看看灯，再慢慢说给你听。",
    "你要听真话还是好听的？我先给你一句好听的。",
    "我记性不好，但这件事我记得比谁都清楚。",
    "别急，让我把台词再念一遍——嗯，就是这样。",
    "你问得真准，可惜我偏不答得那么准。",
]

FALLBACK_NAME = "无名的临时演员"
FALLBACK_CONTENT = "没人记得他什么时候进团，只记得他总在换幕时出现。"


# ----------------------------------------------------------------------
# 同步兜底（纯离线，永不需要网络）
# ----------------------------------------------------------------------
def generate_ai_card() -> dict[str, Any]:
    """离线兜底卡：从固定池里挑一张，保证名字唯一性由调用方补序号。"""
    name, content = random.choice(CARD_POOL)
    return {"name": f"{name}·AI", "content": content}


def ai_answer_as_persona(card: Any, question: str) -> str:
    """离线兜底回答：按卡名给一句占位台词。"""
    name = getattr(card, "name", None)
    if name is None and isinstance(card, dict):
        name = card.get("name")
    name = name or "无名氏"
    return f"（{name}）{random.choice(ANSWER_POOL)}"


# ----------------------------------------------------------------------
# 异步：LLM 优先
# ----------------------------------------------------------------------
CARD_SYSTEM = """你在给一台舞台剧写「节目单上的角色一行说明」。

输出格式：只输出一行，卡名和说明之间用两个竖线隔开，不要任何其它字符。
三个示例（照这个长度和味道写）：
雾港更夫||每夜两点敲响港口的钟。谁问他为什么不睡，他就把钟敲得更响一点。
折纸诗人||只在雨天折纸船，把写坏的诗折进去放走。写完就忘，问起就说不记得。
落雪书吏||替人抄写那些说不出口的话。抄完，自己的记忆会少掉一小块。

要求：
- 卡名 3–14 个汉字，是行当或绰号（像上面三个），不是人名；
- 说明 40–90 个汉字，一段话，第三人称，写他的腔调、习惯和一个忌讳；
- 不写年龄、性别、外貌清单、技能效果；不出现编号、不出现英文、不要引号；
- 只回一行，不要解释、不要标题、不要 markdown。"""




def _strip_stage_direction(text: str) -> str:
    """去掉模型爱加的括号旁白：「（用茶渍画了个圈）散场以后…」→「散场以后…」。"""
    out = re.sub(r'^[（(][^）)]{0,40}[）)]\s*', '', (text or '').strip())
    return out.strip() or (text or '').strip()

def parse_card(text: str) -> dict[str, str] | None:
    """把模型输出解析成 {name, content}：竖线 > JSON > markdown 兜底。"""
    if not text:
        return None
    raw = text.strip().strip("`").strip()

    # ① 卡名 || 卡面（容忍单个竖线、全角竖线、多余空格）
    first_line = raw.splitlines()[0] if raw.splitlines() else raw
    for sep in ("||", "｜｜", "|", "｜"):
        if sep in first_line:
            head, _, tail = first_line.partition(sep)
            rest = " ".join(raw.splitlines()[1:]).strip()
            name = _clean(head)
            content = _clip_sentence(_clean(tail + (" " + rest if rest else "")))
            if name and content:
                return {"name": name[:14], "content": content}
            break

    # ② JSON（有些模型会自己给 JSON）
    data = llm_client.parse_json(raw)
    if data:
        name = _clean(str(data.get("name") or data.get("卡名") or ""))
        content = _clean(str(data.get("content") or data.get("卡面") or ""))
        if name and content:
            return {"name": name[:20], "content": content[:300]}

    # ③ markdown 兜底：挑「卡名/标题」行 + 最长的一段
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    name = ""
    for ln in lines:
        m = re.match(r"^#{0,6}\s*(?:\*\*)?(?:卡名|标题|名称)(?:\*\*)?\s*[:：]?\s*(.+)$", ln)
        if m:
            name = _clean(m.group(1))
            break
    if not name and lines:
        head = re.sub(r"^#+\s*", "", lines[0])
        head = re.split(r"[｜|：:]", head)[-1]
        name = _clean(head)

    body = " ".join(
        ln for ln in lines[1:] if not ln.startswith("|") and not ln.startswith("#")
    )
    content = _clean(body) or _clean(" ".join(lines[1:]))
    if name and content:
        return {"name": name[:20], "content": content[:300]}
    return None


def _clip_sentence(text: str, limit: int = 120) -> str:
    """超长时按句号/分号截断，避免半句话。"""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for mark in ("。", "；", "！", "？", ".", ";"):
        pos = cut.rfind(mark)
        if pos >= 20:
            return cut[: pos + 1]
    return cut.rstrip("，,、 ") + "……"


def _clean(text: str) -> str:
    text = re.sub(r"\*\*|`|#+", "", text or "")
    text = re.sub(r"^[\s:：\-•]+", "", text)
    return text.strip().strip("，,。.、；;")


BANNED_CARD_WORDS = ("岁", "姓名", "年龄", "性别", "身高", "技能", "效果")


def card_is_usable(card: dict[str, str] | None) -> bool:
    if not card:
        return False
    name, content = card.get("name", ""), card.get("content", "")
    if not (2 <= len(name) <= 14) or not (10 <= len(content) <= 130):
        return False
    if any(word in content for word in BANNED_CARD_WORDS):
        return False
    if any(ch.isascii() and ch.isalpha() for ch in name):
        return False
    return True


async def generate_ai_card_async(timeout: float = 15.0) -> dict[str, Any]:
    """问 LLM 要卡；格式不对就纠正一次，再不行退回离线兜底。"""
    ask = (
        "写一张新的人设卡。只回一行，格式：卡名||说明。"
        "卡名 3-14 字，说明 40-90 字（不要超过 90 字），不要姓名年龄性别。"
    )
    for attempt in range(2):
        raw = await llm_client.call_llm(CARD_SYSTEM, ask, timeout=timeout)
        card = parse_card(raw)
        if card_is_usable(card):
            return card  # type: ignore[return-value]
        if attempt == 0:
            ask = (
                "上一版格式不对。请严格只回一行：卡名||说明，"
                "卡名是行当绰号（3-14 字），说明 40-90 字一段话，"
                "不要姓名、年龄、性别、表格或任何解释。"
            )
    return generate_ai_card()


PERSONA_ANSWER_SYSTEM = """你在扮演剧团里的某个角色，正在回答别人的一句提问。

只输出一句台词，不要任何解释、不要引号、不要换行、不要括号旁白。

规则：
1) 第一人称口语，12–60 个汉字，一到两句话；
2) 贴合角色语气与忌讳，可以撒谎、可以打岔，但要沾着问题答；
3) 绝不说出自己的编号，也不直呼自己是哪张卡。"""


async def ai_answer_as_persona_async(
    card: Any, question: str, history: list[str] | None = None, timeout: float = 15.0
) -> str:
    card = card or {"name": FALLBACK_NAME, "content": FALLBACK_CONTENT}
    name = getattr(card, "name", None) or (card.get("name") if isinstance(card, dict) else None)
    content = getattr(card, "content", None) or (
        card.get("content") if isinstance(card, dict) else ""
    )
    prompt = [f"你扮演的角色：{name}", f"角色设定：{content}"]
    if history:
        prompt.append("之前的公开问答（仅供参考语气，不要照抄）：")
        prompt.extend(history[-6:])
    prompt.append(f"现在有人问你：{question}")
    prompt.append("请只说你要说的话。")
    text = await llm_client.call_llm(
        PERSONA_ANSWER_SYSTEM, "\n".join(prompt), timeout=timeout
    )
    text = _strip_stage_direction((text or "").strip().replace("\n", " "))
    if 1 <= len(text) <= 300:
        return text
    return ai_answer_as_persona(card, question)
