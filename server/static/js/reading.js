/* reading.js —— 阅读：自己拿到的卡 + 打乱的卡名 chip + 示意 */

import { esc } from "./ui.js";

export function renderReading(root, state, { send }) {
  if (!root) return;
  const card = state.yourCard;
  const prog = state.readingProgress || { confirmed: 0, total: state.count };
  const chips = (state.cardNames || [])
    .map((name) => `<span class="chip">${esc(name)}</span>`)
    .join("");

  root.innerHTML = `
    <div class="card card--playbill reading-card">
      <div class="card__rubric"><span>读卡</span></div>
      <h2 class="card-title">你拿到的人设卡</h2>

      <div class="reading-body ${card ? "" : "is-empty"}">
        <p class="reading-name" id="reading-card-name">${esc(card?.name || "（还没收到）")}</p>
        <p class="reading-content" id="reading-card-content">${esc(card?.content || "")}</p>
      </div>

      <p class="hint">接下来说话就按这个角色的语气来——<b>别人要猜的正是「几号拿到了这张卡」</b>。
      你可以撒谎，但别把卡名念出来。</p>

      <h3 class="sub-title">场上的卡（顺序已打乱）</h3>
      <div class="chips" id="card-chips">${chips || '<span class="chip muted">（暂无）</span>'}</div>

      <div class="row-actions">
        <button class="btn primary" id="btn-confirm-reading" ${state.readingConfirmed ? "disabled" : ""}>
          ${state.readingConfirmed ? "已示意" : "我读完了"}
        </button>
      </div>
      <p class="hint">${prog.confirmed}/${prog.total} 人读完了</p>
    </div>`;

  root.querySelector("#btn-confirm-reading")?.addEventListener("click", () =>
    send("reading:confirm", {})
  );
}
