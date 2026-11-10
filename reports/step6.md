# Step 6 报告 · 回放确认、轮次推进与强制提交

## 改动的文件
| 文件 | 作用 |
| --- | --- |
| `game/server/state_machine.py` | 新增 `action_confirm`（PHASE3 确认 + `phase3:progress`）、`end_round`（冷却递减 + 广播 + 进下一轮 `enter_phase1`）；`cooldown:updated` 增加 `reason`（`submit_wrong` / `round_end`）与 `round` 字段 |
| `game/server/ws_handlers.py` | 新增 `phase3:confirm` handler |
| `game/tests/helpers.py` | 新增 `finish_round` / `skip_round` 流程封装；`wait_phase` 会把收到的 `phase:changed` 记进 `client.phase_log`，配套 `phase_msg()` 便于事后取字段 |
| `game/tests/test_step6_rounds.py` | Step 6 验收测试（7 条） |

## 规则落地
- **PHASE3**：进入时广播 `phase3:replay{round,items}`（question / answer 两类条目）+ `phase:changed{PHASE3,deadline}`；
  全员确认 → `end_round`；重复确认 → `ALREADY_CONFIRMED`；阶段不符 → `WRONG_PHASE`。
- **end_round**：先对所有 `cooldown>0` 的玩家 `-1` 并逐条广播 `cooldown:updated{reason:"round_end"}`，
  然后 `round += 1`，广播 `round:ended{endedRound,nextRound}`，再 `enter_phase1`（新一轮固定清零行动标记）。
- **第 12 轮强制提交**（测试里用 `forcedSubmitRound=2` 缩短）：
  - `enter_phase1` 里 `forcedSubmit = round >= forcedSubmitRound`，并写进 `phase:changed`
  - 强制轮里 `ASK` / `SKIP` 一律 `FORCED_SUBMIT_REQUIRED`
  - 提交错误（含不完整）→ 冷却 `1` 轮；提交时本身已在冷却期 → 冷却 `2` 轮
  - 强制轮超时 → 未提交者按「草稿/空板」结算（必然判错 → 罚 1 轮）
- 冷却语义按题面直读实现：`cooldown_rounds=3` 表示「计数 3，每轮结束 -1」，因此实际错过的提交机会是 2 轮。

## 测试结果
```
46 passed in 38.73s   # Step1..Step6
```
Step 6 断言：
- `phase3:replay` 的条目内容正确（提问者/被问者昵称、问题文本、回答文本、`timedOut=false`），两个人都收到同一份
- 部分确认 → `phase3:progress{confirmed:[...],total:4}`；全员确认 → 下一轮 `phase:changed{PHASE1,round:2}`
- 不确认 + `phase3Seconds=1` → 超时自动进下一轮
- 错误提交后冷却 `3`，第 1/2/3 轮结束依次广播 `2 / 1 / 0`
- 强制轮（第 2 轮）：`forcedSubmit=true`；`phase1:ask`/`phase1:skip` 被拒；不完整 → `cooldown=1` 且 `missing` 指出缺哪个编号；完整但错 → 同样 `1`
- 冷却期玩家在强制轮提交错误 → `cooldown=2`
- 新一轮所有人 `cooldown=0`、`acted=false`

## 当前限制
- 强制轮从第 12 轮开始后，之后每一轮都是强制提交轮（直到有人全对）；这是题面「第 12 轮强制提交」的直读实现。
- 冷却递减发生在「当轮结束」，因此「冷却 3 轮」= 计数从 3 开始每轮 -1（实际少 2 次提交机会）。

## 下一步
Step 7：全对提交 → 立即 `game:over` 并揭晓 `fullBoard`。
