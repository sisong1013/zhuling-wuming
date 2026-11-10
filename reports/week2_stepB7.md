# 第 2 周 · Step B7：AI 接口预留（占位）

- 状态：**完成**（本步用例 8 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/ai.py`（新文件）：`generate_ai_card()`、`ai_answer_as_persona()` —— 第 2 周返回确定性占位，第 3 周替换实现即可，调用方不改
- `server/state_machine.py`：`add_ai_player()`、`_ai_submit_card()`、`schedule_ai_actions()`、`_ai_phase1_action()`、`_ai_answer()`；AI 在阅读/回放阶段视为自动确认
- `server/ws_handlers.py`：`captain:addAi`
- `server/models.py`：`Player.is_ai`
- `tests/test_week2_stepB7_ai.py`：8 条用例

## 测试

本步新增 **8** 条用例，覆盖本步全部规则断言。

## 已知限制

- 占位实现不接任何 LLM（第 3 周接）；AI 只会「放弃本幕」+ 一句套模板回答
- AI 与真人在分配逻辑上完全同构，只按 `author_id != player.id` 校验

## 下一步：写 `reports/week2_final.md`

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
