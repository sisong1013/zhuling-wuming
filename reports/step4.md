# Step 4 报告 · PHASE1 三选一与冷却

## 改动的文件
| 文件 | 作用 |
| --- | --- |
| `game/server/state_machine.py` | 新增 `action_ask` / `action_submit` / `action_skip`、`_after_phase1_action`（进度广播 + 全员行动提前进 PHASE2）、`_apply_submit`（结算 + 冷却）、`game_over`、强制提交轮的 `on_phase1_timeout`；`enter_phase2` 先给出阶段骨架 |
| `game/server/ws_handlers.py` | 新增 `phase1:ask` / `phase1:submit` / `phase1:skip` handler |
| `game/tests/helpers.py` | 新增 `correct_board` / `wrong_board` / `partial_board` / `act_all` |
| `game/tests/test_step4_phase1.py` | Step 4 验收测试（10 条） |

## 规则落地
- **每人每轮一次**：`player.action_round == room.round` 判断，重复行动回 `ALREADY_ACTED`。
- **ASK**：校验目标编号存在、不是自己、文本非空（≤200 字）；生成 `Question` 并广播 `question:public`（PUBLIC）。
- **SUBMIT**：立即结算。全对 → `submit:result{correct:true}` + `game:over`（Step 7 详测）；错 → 冷却 `3` 轮，
  广播 `cooldown:updated{playerId,cooldown}`，并回 `submit:result{correct:false,missing,wrong,cooldown}`。
- **冷却期不能提交**：`PLAYER_IN_COOLDOWN`（校验顺序：阶段 → 冷却 → 重复行动 → 载荷，
  这样「冷却期再提交」拿到的是更具体的拒绝码）。
- **SKIP**：可带草稿一并保存，消耗本轮行动机会。
- **全员行动 → 立即进 PHASE2**（并取消 PHASE1 定时器）；**超时 → 进 PHASE2**；
  强制提交轮的超时则按「草稿/空板提交」结算（罚 1 轮）。
- 行动后广播 `phase1:progress{acted,pending,total}` 与最新 `room:state`（客户端据此更新冷却显示）。

## 测试结果
```
33 passed in 15.47s   # Step1(6)+Step2(10)+Step3(7)+Step4(10)
```
Step 4 断言：
- ASK 后**所有人**收到 `question:public`（含 askerId / targetId / 文本 / 轮次 / PENDING），进度只含 asker
- 问自己 / 问不存在的编号 → `INVALID_TARGET`；空问题 → `INVALID_PAYLOAD`；三次失败都不消耗行动机会
- 同轮第二次行动 → `ALREADY_ACTED`
- 错误提交 → `submit:result{correct:false, cooldown:3}` + 全员收到 `cooldown:updated{cooldown:3}` + `room:state` 里该玩家 `cooldown=3`
- 冷却期内再提交 → `PLAYER_IN_COOLDOWN`
- 全员行动（2 ask + 2 skip）→ 6s 内收到 `phase:changed{PHASE2, round:1}` 且 deadline 在未来
- 都不行动 + `phase1Seconds=1` → 服务端定时器把房间推进到 PHASE2
- `board:saveDraft` 在 PHASE1 可用，回 `board:draftSaved`

## 当前限制
- PHASE2 此刻只广播阶段变化，作答队列在 Step 5 实现。
- 提交错误时的 `missing` / `wrong` 明细只回给提交者本人（不广播，避免泄露）。

## 下一步
Step 5：PHASE2 —— 按被问者排队、被问者之间并行、单题 30s 超时不惩罚、全部结束进 PHASE3。
