# 第 3 周 · Step 3.3：AI 写卡

- 状态：**完成**（本步 4 条用例全绿；第 1/2 周 128 条回归同时保持全绿）

## 改了哪些文件

- `server/ai.py`：`generate_ai_card_async()`（LLM 生成 + 合规校验 + 兜底）、`generate_ai_card()`（离线池）
- `server/ai_agent.py`：`write_card()`（重名自动加序号）
- `server/state_machine.py`：`_ai_write_card()`，进 `CARD_WRITING` 后自动触发，延迟 `aiCardDelaySeconds` 再提交
- `tests/test_week3_step3_ai_card.py`：4 条用例

## 测试

本步新增 **4** 条用例。

## 已知限制

- 生成延迟是固定基准（默认 2s），不是随机；想更拟人可改成 1.5–3s 随机

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
