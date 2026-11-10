# 第 3 周 · Step 3.5：AI 第二幕扮演作答

- 状态：**完成**（本步 4 条用例全绿；第 1/2 周 128 条回归同时保持全绿）

## 改了哪些文件

- `server/ai.py`：`ai_answer_as_persona_async()`（人设/历史进 Prompt + 兜底台词）
- `server/ai_agent.py`：`answer_question()`
- `server/state_machine.py`：`_ai_answer()`，按字数给 2–5s 打字延迟（可配），再走 `action_answer`
- `tests/test_week3_step5_ai_answer.py`：4 条用例

## 测试

本步新增 **4** 条用例。

## 已知限制

- 提示词要求「不暴露编号」是软约束；测试只用正则兜住「N 号」这种直白泄露形态

## 下一步

见 `reports/week3_final.md`。

## 验证

```bash
cd game
bash scripts/selftest.sh                              # 全量（第 1/2/3 周）
bash scripts/selftest.sh tests/test_week3_stepX_*.py   # 单步
```

> 本机没有配 `LLM_API_KEY`，所有 AI 用例跑的是**兜底路径**（确定性决策/台词）；
> LLM 真正联网的那条路径由 `test_week3_step1_llm.py` 用 monkeypatch 覆盖（成功/超时/500/JSON 围栏）。
