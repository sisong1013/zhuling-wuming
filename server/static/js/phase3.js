/* phase3.js —— 第三幕 · 复述：本轮问答回放 + 全员示意 */

import { esc } from "./ui.js";

export function renderPhase3(root, state, { send }) {
  if (!root) return;
  const items = state.replay || [];
  const confirmed = state.progress?.confirmed ?? 0;
  const total = state.progress?.total ?? state.count;

  const rows = items.length
    ? items
        .map(
          (item) => `
      <li class="replay-item ${item.status === "TIMEOUT" ? "is-timeout" : ""}">
        <p class="replay-who">
          <b>${esc(item.askerNickname)}</b> →
          <b>${esc(item.targetNickname)}</b>
        </p>
        <p class="replay-q">${esc(item.question)}</p>
        <p class="replay-a">${item.status === "TIMEOUT" ? "（超时未答）" : esc(item.answer || "")}</p>
      </li>`
        )
        .join("")
    : `<li class="replay-item"><p class="replay-a">本轮没有人提问。</p></li>`;

  root.innerHTML = `
    <div class="card action-card">
      <div class="card__rubric"><span>本幕行事</span></div>
      <h2 class="card-title">第三幕 · 复述</h2>
      <p class="hint">把本轮的问答过一遍，全员示意后进入下一轮。</p>
      <ul class="replay">${rows}</ul>
      <div class="row-actions">
        <button class="btn primary" id="btn-confirm" ${state.confirmedRound === state.round ? "disabled" : ""}>
          我看完了
        </button>
      </div>
      <p class="hint">${confirmed}/${total} 人已示意</p>
    </div>`;

  root.querySelector("#btn-confirm")?.addEventListener("click", () => {
    send("phase3:confirm");
    state.confirmedRound = state.round;
    root.querySelector("#btn-confirm").disabled = true;
  });
}
