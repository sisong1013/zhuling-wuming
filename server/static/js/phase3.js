/* phase3.js —— 第三幕 · 复述：本轮问答回放 + 全员示意 */

import { esc } from "./ui.js";

export function renderPhase3(root, state, { send }) {
  if (!root) return;
  const items = state.replay || [];
  const confirmedIds = Array.isArray(state.progress?.confirmed) ? state.progress.confirmed : [];
  const confirmed = confirmedIds.length;
  const total = state.progress?.total ?? state.count;

  // 服务端给的是「问题条目 + 回答条目」两条，这里按 questionId 配对成一行
  const threads = [];
  for (const item of items) {
    let thread = threads.find((t) => t.questionId === item.questionId);
    if (!thread) {
      thread = { questionId: item.questionId };
      threads.push(thread);
    }
    if (item.kind === "answer") thread.answer = item;
    else thread.question = item;
  }

  const answerLine = (ans) => {
    if (!ans) return "（待答）";
    if (ans.timedOut) return "（超时未答）";
    if (ans.masked) return "🔒 已作答（内容仅当事人可见）";
    return esc(ans.answer || "");
  };

  const rows = threads.length
    ? threads
        .map((thread) => {
          const q = thread.question || {};
          const ans = thread.answer;
          const timeout = ans && ans.timedOut;
          const target = q.targetNo != null ? `#${q.targetNo}` : esc(q.targetNickname || "?");
          return `
      <li class="replay-item ${timeout ? "is-timeout" : ""} ${ans && ans.masked ? "is-masked" : ""}">
        <p class="replay-who">
          <b>${esc(q.askerNickname || "?")}</b> 问 <b>${target}</b>
        </p>
        <p class="replay-q">${esc(q.text || "")}</p>
        <p class="replay-a">${answerLine(ans)}</p>
      </li>`;
        })
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
      <div class="progress-chips">
        ${(state.players || [])
          .map(
            (p) =>
              `<span class="chip ${confirmedIds.includes(p.id) ? "done" : "waiting"}">${esc(
                p.nickname
              )}${p.isAi ? " · AI" : ""}<i>${
                confirmedIds.includes(p.id) ? "已示意" : "还没看"
              }</i></span>`
          )
          .join("")}
      </div>
      <p class="hint">${confirmed}/${total} 人已示意</p>
    </div>`;

  root.querySelector("#btn-confirm")?.addEventListener("click", () => {
    send("phase3:confirm");
    state.confirmedRound = state.round;
    root.querySelector("#btn-confirm").disabled = true;
  });
}
