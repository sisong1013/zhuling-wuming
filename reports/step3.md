# Step 3 报告 · 开局与随机编号

## 改动的文件
| 文件 | 作用 |
| --- | --- |
| `game/server/state_machine.py` | 新增 `start_game()`（队长/阶段/人数校验 → 随机编号 → 逐人下发 `game:started`）、`enter_phase1()`（阶段时间戳 + 可取消定时器）、`phase1_progress()`；`enter_phase2` 先留桩 |
| `game/server/ws_handlers.py` | 新增 `game:start` handler 并注册到分发表 |
| `game/tests/helpers.py` | 新增「映射泄露」探测器 `find_number_mappings` / `assert_no_mapping` |
| `game/tests/test_step3_start.py` | Step 3 验收测试（7 条） |

## 关键实现
- `assign_room_numbers()`：把 `1..n` 洗牌后按入房顺序发，**每个连接只收到自己的 `yourRoomNo`**。
- `game:started{yourRoomNo, roomNos, nicknames, ...}`：`roomNos` 固定升序 `[1..n]`，`nicknames` 按入房顺序，
  两者之间没有位置对应关系 → 无法顺序反推映射。
- `room:state` 里 `players[]` 永远不带 `roomNo`，只有 `you.roomNo`（本人）。
- 阶段时间戳由服务端生成（`deadline = now + phase1_seconds`），前端只负责显示。

## 测试结果
```
23 passed in 8.44s   # Step1(6) + Step2(10) + Step3(7)
```
Step 3 断言：
- 非队长 `game:start` → `error NOT_CAPTAIN`，且窗口内没有任何 `phase:changed`
- 重复开局 → `error WRONG_PHASE`
- 1 人开局 → `error NOT_ENOUGH_PLAYERS`
- 4 人开局：`yourRoomNo` 互不相同且恰为 `{1,2,3,4}`；`roomNos == [1,2,3,4]`；昵称数组含全部 4 人
- `phase:changed{phase:PHASE1, round:1, deadline≈now+60, forcedSubmit:false}`
- **整条流程的所有消息**都通过「映射泄露」扫描：不存在以 ≥2 个编号为键的对象；`game:started` 的字段集合被逐字校验；`room:state.players[]` 无 `roomNo`
- 两个房间各自开局，编号分配都合法且房间之间互不影响

## 当前限制
- `enter_phase2` 此时是桩（`NotImplementedError`），Step 5 实现；Step 4 会先补「PHASE1 → PHASE2」这条边。
- 没有「重新开局 / 再来一局」；游戏结束后房间就是结束态。

## 下一步
Step 4：PHASE1 三选一（ASK / SUBMIT / SKIP）、冷却、进度、提前进 PHASE2 与超时进 PHASE2。
