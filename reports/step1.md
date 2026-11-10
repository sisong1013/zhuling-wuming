# Step 1 报告 · 工程骨架

## 改动的文件
| 文件 | 作用 |
| --- | --- |
| `game/server/main.py` | FastAPI 应用骨架：`GET /`（入口页）、`GET /healthz`、`WS /ws`（Step 1 只做 ping/pong）、`/static` 静态托管 |
| `game/server/static/index.html` | 单页三视图（入口 / 等待室 / 游戏）+ 结束遮罩，原生 HTML |
| `game/server/static/style.css` | 深色石板底 + 荧光绿/青强调色；卡片布局、编号等宽字体 |
| `game/server/static/app.js` | 原生 ES Module：WebSocket 连接、心跳、消息分发表骨架 |
| `game/tests/conftest.py` | 起真实 uvicorn 子进程（空闲端口 + `/healthz` 探活），提供 `base` / `ws_base` fixture |
| `game/tests/helpers.py` | 测试用 `WsClient`（backlog + `wait_for` 带超时）、建房/加入/开局流程封装 |
| `game/tests/test_step1_skeleton.py` | Step 1 验收测试 |
| `game/scripts/selftest.sh` | 一键自测（自动挑一个装好依赖的解释器，跑 pytest） |
| `game/pytest.ini` / `game/requirements.txt` | pytest 配置（`asyncio_mode=auto`）、依赖清单 |

## 测试结果
```
16 passed in 1.98s   # Step1(6) + Step2(10，见 step2.md)
```
Step 1 自身 6 条断言全绿：
- `GET /healthz` 200
- `GET /` 200、`text/html`、页面含标题、`type="module"`、无 socket.io
- `/static/app.js`、`/static/style.css` 200
- WS `ping` → `pong`
- 非法 JSON → `error BAD_JSON`
- 未知 type → `error UNKNOWN_TYPE`

## 过程中踩的坑（已修）
- `tests/helpers.py` 的 `wait_for` 最初通过 `recv()` 读消息，而 `recv()` 会优先从 backlog 取，
  导致「取出 → 不匹配 → 压回 backlog」的忙等死循环（表现为 4s 后抛出一条含上千条 `room:state` 的超时）。
  改成 `wait_for` 直接读 socket、只有非匹配消息才进 backlog。

## 当前限制
- 环境里没有 `bash`，`scripts/selftest.sh` 用 Git Bash（`C:\Program Files\Git\bin\bash.exe`）执行；
  脚本会自动探测 `.venv` / `../.venv` 里装好依赖的解释器。
- 前端此时只完成连接与心跳，业务视图留给后续 Step。

## 下一步
Step 2：房间码机制（建房 / 加入 / 人数广播 / 错误码）。
