/* phase2.js —— 第二幕 · 应答：我若被问就作答，否则看进度 */

import { esc, toast } from "./ui.js";

export function renderPhase2(root, state, { send }) {
  if (!root) return;
  const q = state.currentQuestion;
  const progress = state.progress || {};
  const answered = progress.answered ?? 0;
  const total = progress.total ?? state.count;

  const body = q
    ? `<div class="question-box">
         <p class="label">${esc(q.askerNickname || "有人")} 问你</p>
         <p class="question-text">${esc(q.text)}</p>
         <label class="field">
           <span>你的回答（按你拿到的角色语气来，可以撒谎）</span>
           <textarea id="answer-text" rows="3" maxlength="300" placeholder="一句话就够，别报自己的编号"></textarea>
         </label>
         <div class="row-actions">
           <button class="btn primary" id="btn-answer">作答</button>
         </div>
       </div>`
    : `<div class="question-box waiting">
         <p class="question-text">这一轮没有你的问题，等别人作答…</p>
         <p class="hint">已回答 ${answered}/${total}</p>
       </div>`;

  root.innerHTML = `
    <div class="card action-card">
      <div class="card__rubric"><span>本幕行事</span></div>
      <h2 class="card-title">第二幕 · 应答</h2>
      ${body}
      <p class="hint">每个人并行作答，答完就公开；超时记 TIMEOUT（不罚）。</p>
    </div>`;

  root.querySelector("#btn-answer")?.addEventListener("click", () => {
    const text = root.querySelector("#answer-text")?.value.trim();
    if (!text) return toast("总得说点什么", "error");
    send("phase2:answer", { questionId: q.questionId, text });
    state.currentQuestion = null;
  });
}
