# Step 5 报告 · PHASE2 排队作答

## 改动的文件
| 文件 | 作用 |
| --- | --- |
| `game/server/models.py` | `Room.phase2_active`（被问者 → 当前进行中的问题 id） |
| `game/server/rules.py` | 新增 `build_replay_items()`（本轮回放条目）、`answer_public_payload()` 已有 |
| `game/server/state_machine.py` | 重写 `enter_phase2`：按被问者分队列、队列间并行；新增 `_serve_next_for_target`、`_notify_waiting`、`action_answer`、`on_question_timeout`、`_after_answer`、`phase2_progress`、`enter_phase3`（阶段 + 回放广播 + 定时器） |
| `game/server/ws_handlers.py` | 新增 `phase2:answer` handler |
| `game/tests/test_step5_phase2.py` | Step 5 验收测试（6 条） |

## 规则落地
- **按人排队**：同一被问者的多个问题串行；`phase2_active[targetId]` 记录在答的题，答完/超时才推下一道。
- **人与人并行**：所有有问题的被问者在进入 PHASE2 时同时开跑，各自独立的单题定时器
  （`room:<code>:q:<qid>`，可取消）。
- **单题 30s**：超时记 `TIMEOUT`，**不惩罚**、不冷却，广播 `answer:public{timedOut:true, answer:null}` 后继续队列。
- **全部结束 → PHASE3**：`_after_answer` 检查本轮是否还有 PENDING，没有就进回放阶段；
  本轮完全没人提问时 `enter_phase2` 直接跳 PHASE3（会先广播一次空 PHASE2）。
- 事件：进队列时给被问者 `question:received{queuePosition}`；轮到答题时 `phase2:nextQuestion{questionId,text,deadline}`；
  提问者收到 `phase2:waiting{waiting,answered}`；全过程 `phase2:progress{total,answered,timedOut,pending,active}`。
- 鉴权：不是被问者 → `NOT_YOUR_QUESTION`；同一题重复答 → `ALREADY_ANSWERED`；未知题目 → `QUESTION_NOT_FOUND`；空回答 → `INVALID_PAYLOAD`。

## 测试结果
```
39 passed in 33.93s   # Step1..Step5
```
Step 5 断言：
- A→B、C→D 两题**同时**被推送（questionId 不同、asker 正确），吃瓜群众不会收到 `phase2:nextQuestion`
- 两人各自作答互不影响，答完自动进 PHASE3
- 同一个人被两人问：答题前**不会**提前收到第二题；答完第一题立刻收到第二题
- `phase2Seconds=1` 时：B 超时（`TIMEOUT`/`timedOut:true`/`answer:null`、无 `cooldown:updated`）不影响 D 正常作答，两者都结束后进 PHASE3
- 非被问者抢答 / 空回答 / 未知题目 / 重复回答 全部被拒
- 没人提问 → 直接 PHASE3，`phase3:replay.items == []`
- `phase2:progress` 的 total/answered/pending 数字正确

## 当前限制
- PHASE3 的「确认」与轮次推进在 Step 6 实现（当前 `end_round` 为桩）。
- 一轮内同一被问者队列过长时，阶段 `deadline` 只是兜底显示（`phase2Seconds × 最长队列`），真正的推进靠单题定时器。

## 下一步
Step 6：PHASE3 确认 + end_round（冷却递减）+ 第 12 轮强制提交与罚则。
