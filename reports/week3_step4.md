# 第 3 周 · Step 3.4：AI 第一幕决策

- 状态：**完成**（本步 6 条用例全绿；第 1/2 周 128 条回归同时保持全绿）

## 改了哪些文件

- `server/ai_agent.py`：`build_phase1_prompt()`、`decide_phase1()`、`_fallback_decision()`、`fallback_board()`
- `server/state_machine.py`：`schedule_ai_actions()`（0.8–1.7 倍随机延迟）、`_ai_phase1_action()`（ASK/SUBMIT/SKIP 走真人的 `action_*` 校验）
- `tests/test_week3_step4_ai_phase1.py`：6 条用例

## 测试

本步新增 **6** 条用例。

## 已知限制

- LLM 输出非法 JSON / 越界目标 → 立刻退回兜底策略，不会卡住阶段
- AI 被拒绝（冷却、非法目标）时降级为「放弃本轮」，不吃掉阶段

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
