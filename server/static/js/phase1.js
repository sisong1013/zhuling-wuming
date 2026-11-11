/* phase1.js —— 第一幕 · 讯问：提问 / 略过 / 开看板 */

import { esc, toast } from "./ui.js";
import { toggleBoard } from "./board.js";

export function renderPhase1(root, state, { send }) {
  if (!root) return;
  const cooldown = state.you.cooldown || 0;
  const acted = !!state.acted;
  const targets = (state.roomNos.length ? state.roomNos : []).filter(
    (no) => no !== state.myRoomNo
  );
  const options = targets
    .map((no) => `<option value="${no}">#${no}</option>`)
    .join("");
  // 冷却只限制「呈上看板」，提问/略过照常（这是规则本意）
  const canSubmitBlocked = cooldown > 0 && !state.forcedSubmit;
  const canAsk = !acted && !state.forcedSubmit;

  root.innerHTML = `
    <div class="card action-card">
      <div class="card__rubric"><span>本幕行事</span></div>
      <h2 class="card-title">第一幕 · 讯问</h2>

      <p class="hint">${state.forcedSubmit
        ? "强制作答轮：只能呈上看板，答错（含不完整）要罚轮次。"
        : "每轮一次机会：问某人一个问题 / 呈上看板 / 略过。"}</p>

      <div class="ask-row">
        <label class="field narrow">
          <span>问几号</span>
          <select id="ask-target" ${canAsk ? "" : "disabled"}>${options || '<option value="">—</option>'}</select>
        </label>
        <label class="field grow">
          <span>问题</span>
          <input id="ask-text" maxlength="120" placeholder="问一件只有那位才知道的事"
            ${canAsk ? "" : "disabled"} />
        </label>
        <button class="btn primary" id="btn-ask" ${canAsk ? "" : "disabled"}>讯问他</button>
      </div>

      <div class="row-actions between">
        <button class="link-btn" id="btn-board-inline">◆ 打开观众板（${
          canSubmitBlocked ? "冷却中，暂不可呈" : "呈上看板"
        }）</button>
        <button class="btn ghost" id="btn-skip" ${acted ? "disabled" : ""}>略过本轮</button>
      </div>

      <p class="hint">${
        cooldown > 0
          ? `你在冷却期（剩 ${cooldown} 轮）：不能呈上看板，但可以继续提问或略过`
          : acted
          ? "本幕已行动，等其他人…"
          : "提问会公开给所有人，也会消耗本轮唯一的机会。"
      }</p>

      <h3 class="sub-title">本幕进度</h3>
      <div class="progress-chips">
        ${state.players
          .map((p) => {
            const kind = (state.progress.kinds || {})[p.id];
            const acted = (state.progress.acted || []).includes(p.id);
            const label = acted
              ? { ASK: "已提问", SUBMIT: "已呈看板", SKIP: "已略过" }[kind] || "已行动"
              : p.cooldown > 0
              ? "冷却中"
              : "待行动";
            const cls = acted
              ? kind === "SUBMIT"
                ? "done submit"
                : kind === "ASK"
                ? "done ask"
                : "done skip"
              : p.cooldown > 0
              ? "cold"
              : "waiting";
            return `<span class="chip ${cls}">${esc(p.nickname)}${p.isAi ? " · AI" : ""}<i>${label}</i></span>`;
          })
          .join("")}
      </div>
    </div>`;

  root.querySelector("#btn-ask")?.addEventListener("click", () => {
    const target = root.querySelector("#ask-target")?.value;
    const text = root.querySelector("#ask-text")?.value.trim();
    if (!target) return toast("选个编号", "error");
    if (!text) return toast("问题不能为空", "error");
    send("phase1:ask", { targetRoomNo: Number(target), text });
  });

  root.querySelector("#btn-skip")?.addEventListener("click", () => send("phase1:skip"));
  root.querySelector("#btn-board-inline")?.addEventListener("click", () => toggleBoard(true));
}
