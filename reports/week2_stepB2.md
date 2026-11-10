# 第 2 周 · Step B2：写卡阶段 CARD_WRITING

- 状态：**完成**（本步用例 10 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/rules.py`：`normalize_card_name()`（1–20 字、同房间唯一、超长直接拒绝）、`normalize_card_content()`（1–300 字）、`CARD_NAME_MAX / CARD_CONTENT_MAX`
- `server/state_machine.py`：`enter_card_writing()`、`submit_card()`、`start_assign()`
- `server/ws_handlers.py`：`card:submit`、`captain:startAssign`
- `tests/test_week2_stepB2_cards.py`：10 条用例

## 测试

本步新增 **10** 条用例，覆盖本步全部规则断言。

## 已知限制

- 写卡不设硬超时（规则如此），靠队长手动触发分配；无「催交」机制

## 下一步：B3 错位分配

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
