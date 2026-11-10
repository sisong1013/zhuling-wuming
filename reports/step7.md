# Step 7 报告 · 获胜与揭晓

## 改动的文件
| 文件 | 作用 |
| --- | --- |
| `game/tests/test_step7_win.py` | Step 7 验收测试（6 条） |

`game/server/state_machine.py` 里 `_apply_submit()` + `game_over()` 在 Step 4 已经写好，
这一步把「全对 → 立即 `game:over` → `fullBoard` 正确揭晓」这条路径正式验收。

## 规则落地
- `_apply_submit()` 判定全对 → 先给提交者 `submit:result{correct:true}`，随后 `game_over()`：
  取消该房间全部定时器 → `phase=OVER` → 广播 `game:over{winnerId, fullBoard, round}` → 广播 `room:state`。
- `fullBoard` 形如 `{"1": {"nickname": "甲", "playerId": "p_..."}, ...}`，是**唯一**会下发完整映射的地方。
- 结束后 `room:state.phase == "OVER"` 且带 `winnerId`；任何动作都会被 `WRONG_PHASE` 拒绝。
- 看板值宽容解析：填昵称或 `playerId` 都算对。

## 测试结果
```
64 passed in 47.46s   # Step1..Step8 全量（Step7 本轮首次全绿时 52 passed）
```
Step 7 断言：
- 全对提交 → 提交者收到 `submit:result{correct:true}`，**所有人**收到 `game:over`，`winnerId` 正确，
  `fullBoard` 的键是 `1..n`、值与测试侧上帝的映射逐项一致
- 立刻结算：其他人还没行动就已收到 `game:over`，且不会再有 `phase:changed{PHASE2}`
- 结束后 `room:state{phase:OVER, winnerId}`；`phase1:ask` / `phase3:confirm` 均 `WRONG_PHASE`
- 完整但错的看板不会结束游戏（仍旧 `cooldown=3`，无 `game:over`）
- 2 人局同样能正常获胜并揭晓

## 当前限制
- 一局结束后不能在同一房间「再来一局」（需要重新建房）。
- `submit:result` 里的 `missing` / `wrong` 只回提交者，其他玩家只会看到 `cooldown:updated`。

## 下一步
Step 8：非法操作与错误码的完整覆盖。
