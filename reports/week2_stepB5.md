# 第 2 周 · Step B5：PERSONA 判定与揭晓

- 状态：**完成**（本步用例 5 条全绿，且第 1 周 64 条回归用例同时保持全绿）
- 自动验收：`bash scripts/selftest.sh` 退出码 0

## 改了哪些文件

- `server/rules.py`：`truth_for(room)`（REAL→昵称 / PERSONA→卡名）、`_resolve_guess()`（REAL 认昵称或 id，PERSONA 认卡名或卡 id）、`judge_board()` 改为模式无关外壳
- `server/state_machine.py`：`reveal_cards()`；`game_over` 对 PERSONA 下发 `reveal:[{roomNo,cardName,cardContent,authorNickname}]`，REAL 仍下发 `fullBoard`
- `tests/test_week2_stepB5_judge.py`：5 条用例

## 测试

本步新增 **5** 条用例，覆盖本步全部规则断言。

## 已知限制

- 冷却/强制提交/每轮冷却 -1 完全沿用第 1 周，未因模式改变（由第 1 周用例继续守护）

## 下一步：B6 回答软约束

## 验证方式

```bash
cd game
bash scripts/selftest.sh                       # 全量（第 1 周 + 第 2 周）
bash scripts/selftest.sh tests/test_week2_stepX_*.py   # 单步
```

## 下一步

见 `reports/week2_final.md`。
