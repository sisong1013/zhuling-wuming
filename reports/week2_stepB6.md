# 第 2 周 · Step B6：回答的软约束

- 状态：**完成**（本步用例 4 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/state_machine.py`：`action_answer` 不做任何「是否符合人设」判断，`rules.sanitize_text` 后原样存储广播
- `README.md`：规则说明写明「贴合人设是玩家自觉约束，服务端不判定」
- `tests/test_week2_stepB6_softconstraint.py`：4 条用例（含 emoji/全角原样往返）

## 测试

本步新增 **4** 条用例，覆盖本步全部规则断言。

## 已知限制

- 空回答仍判 `INVALID_PAYLOAD`（软约束只针对内容风格，不放过非法载荷）

## 下一步：B7 AI 接口预留

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
