/* lobby.js —— 入口页：昵称 + 建房 / 凭房号入场 */

import { esc, toast } from "./ui.js";

export function renderLobby(root, state, { send }) {
  if (!root) return;
  const saved = state.nickname || "";

  root.innerHTML = `
    <div class="card card--playbill">
      <div class="card__rubric"><span>入席</span></div>
      <h2 class="card-title">填写你的席次名牌</h2>
      <label class="field">
        <span>你的昵称</span>
        <input id="nickname" maxlength="16" autocomplete="off" placeholder="比如：阿墨" value="${esc(saved)}" />
      </label>
      <div class="row-actions">
        <button class="btn primary" id="btn-create">组建剧团（当团长）</button>
      </div>
      <div class="divider"><span>或</span></div>
      <div class="join-row">
        <label class="field grow">
          <span>剧团票根上的号码</span>
          <input id="room-code" maxlength="6" inputmode="numeric" autocomplete="off" placeholder="6 位数字" />
        </label>
        <button class="btn" id="btn-join">入场</button>
      </div>
    </div>

    <div class="card card--rulebook">
      <div class="card__rubric"><span>戏目说明</span></div>
      <h2 class="card-title">怎么玩</h2>
      <ol class="rules">
        <li>团长组建剧团，拿到 <b>6 位号码</b>；其余人凭号码入场。</li>
        <li><b>猜真人</b>：开演时每人领到一枚编号，但谁也不知道自己是几号。</li>
        <li><b>人设卡</b>：每人写一张卡，错位发到别人手里，你要猜「几号是谁的卡」。</li>
        <li><b>第一幕 · 讯问</b>：每轮一次机会 —— 问某人一个问题 / 呈上看板 / 略过。</li>
        <li><b>第二幕 · 应答</b>：被问者依序作答，公开可见；可以撒谎。</li>
        <li><b>第三幕 · 复述</b>：复诵本轮问答，全员示意后进入下一轮。</li>
        <li>全部猜中即刻谢幕；结束后有 <b>名场面复盘</b> 可看。</li>
      </ol>
    </div>`;

  const nick = () => root.querySelector("#nickname").value.trim();

  root.querySelector("#btn-create").addEventListener("click", () => {
    if (!nick()) return toast("先起个名字", "error");
    send("room:create", { nickname: nick() });
  });

  root.querySelector("#btn-join").addEventListener("click", () => {
    const code = root.querySelector("#room-code").value.trim();
    if (!nick()) return toast("先起个名字", "error");
    if (!/^\d{6}$/.test(code)) return toast("号码是 6 位数字", "error");
    send("room:join", { roomCode: code, nickname: nick() });
  });

  root.querySelectorAll("input").forEach((input) => {
    input.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      if (input.id === "nickname") root.querySelector("#btn-create").click();
      else root.querySelector("#btn-join").click();
    });
  });
}
