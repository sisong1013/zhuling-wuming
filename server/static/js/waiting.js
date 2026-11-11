/* waiting.js —— 等待室：房号、名册、队长台（配置 / 玩法 / 加 AI / 开演） */

import { esc, toast } from "./ui.js";

export function renderWaiting(root, state, { send }) {
  if (!root) return;
  const cfg = state.config || {};
  const isCaptain = !!(state.you && state.you.isCaptain);
  const aiCount = state.players.filter((p) => p.isAi).length;
  const full = state.count >= state.maxPlayers;

  const players = state.players
    .map((p) => {
      const tags = [];
      if (p.isCaptain) tags.push('<span class="tag">队长</span>');
      if (p.isAi) tags.push('<span class="tag ai">AI</span>');
      if (p.id === state.you.id) tags.push('<span class="tag self">你</span>');
      if (!p.connected) tags.push('<span class="tag off">掉线</span>');
      return `<li class="player-item"><span class="who">${esc(p.nickname)}</span>${tags.join("")}</li>`;
    })
    .join("");

  root.innerHTML = `
    <div class="card card--playbill room-card">
      <div class="card__rubric"><span>候场</span></div>
      <div class="room-head">
        <div>
          <p class="label">剧团号码</p>
          <p class="room-code" id="lobby-code">${esc(state.roomCode || "------")}</p>
        </div>
        <div class="room-meta">
          <p class="label">你的名牌</p>
          <p class="room-me">${esc(state.you.nickname || state.nickname || "—")}</p>
        </div>
      </div>
      <ul class="player-list" id="lobby-players">${players}</ul>
      <p class="hint">已就位 ${state.count}/${state.maxPlayers} 人${
        state.count < 2 ? "（至少 2 人才能开演，把号码发给朋友）" : ""
      }</p>
    </div>

    ${
      isCaptain
        ? `<div class="card" id="captain-panel">
             <div class="card__rubric"><span>团长台</span></div>
             <h2 class="card-title">幕次安排</h2>
             <div class="config-grid">
               <label class="field"><span>第一幕（秒）</span><input id="cfg-phase1" type="number" min="1" max="600" value="${cfg.phase1Seconds ?? 60}" /></label>
               <label class="field"><span>第二幕每题（秒）</span><input id="cfg-phase2" type="number" min="1" max="600" value="${cfg.phase2Seconds ?? 30}" /></label>
               <label class="field"><span>第三幕（秒）</span><input id="cfg-phase3" type="number" min="1" max="600" value="${cfg.phase3Seconds ?? 30}" /></label>
               <label class="field"><span>强制作答轮次</span><input id="cfg-forced" type="number" min="1" max="99" value="${cfg.forcedSubmitRound ?? 12}" /></label>
             </div>
             <div class="mode-row">
               <p class="label">玩法</p>
               <div class="row-actions">
                 <button class="btn mode-btn ${state.gameMode === "REAL" ? "primary" : ""}"
                   data-mode="REAL" aria-pressed="${state.gameMode === "REAL"}">
                   ${state.gameMode === "REAL" ? "✓ " : ""}猜真人
                 </button>
                 <button class="btn mode-btn ${state.gameMode === "PERSONA" ? "primary" : ""}"
                   data-mode="PERSONA" aria-pressed="${state.gameMode === "PERSONA"}">
                   ${state.gameMode === "PERSONA" ? "✓ " : ""}人设卡
                 </button>
               </div>
             </div>
             <div class="mode-row">
               <p class="label">陪演（AI）</p>
               <div class="row-actions">
                 <button class="btn" id="btn-add-ai-1" ${full ? "disabled" : ""}>+1 AI</button>
                 <button class="btn" id="btn-add-ai-2" ${full ? "disabled" : ""}>+2 AI</button>
               </div>
               <label class="field">
                 <span>问答模式</span>
                 <select id="qa-mode">
                   <option value="PUBLIC" ${(state.config && state.config.qaVisibility) === "PUBLIC" ? "selected" : ""}>全公开 · 问题和回答所有人可见</option>
                   <option value="SEMI" ${(state.config && state.config.qaVisibility) === "SEMI" ? "selected" : ""}>半公开 · 问题公开，回答只有问/答两人可见</option>
                   <option value="PRIVATE" ${(state.config && state.config.qaVisibility) === "PRIVATE" ? "selected" : ""}>私密 · 每对问答只有当事人可见</option>
                 </select>
               </label>
               <p class="hint">当前玩法：<b>${
                 state.gameMode === "PERSONA" ? "人设卡（先写卡 → 错位分配 → 读卡）" : "猜真人"
               }</b>；陪演 AI ${aiCount} 个</p>
             </div>
             <div class="row-actions">
               <button class="btn" id="btn-save-config">记下安排</button>
               <button class="btn primary" id="btn-start" ${state.count < 2 ? "disabled" : ""}>开演</button>
             </div>
           </div>`
        : `<div class="card muted"><p>等团长敲响开场铃…（当前玩法：${state.gameMode === "PERSONA" ? "人设卡" : "猜真人"}）</p></div>`
    }`;

  if (!isCaptain) return;

  root.querySelector("#btn-save-config")?.addEventListener("click", () => {
    send("setup:config", {
      phase1Seconds: Number(root.querySelector("#cfg-phase1").value),
      phase2Seconds: Number(root.querySelector("#cfg-phase2").value),
      phase3Seconds: Number(root.querySelector("#cfg-phase3").value),
      forcedSubmitRound: Number(root.querySelector("#cfg-forced").value),
    });
    toast("安排已记下");
  });

  root.querySelector("#qa-mode")?.addEventListener("change", (event) => {
    const mode = event.target.value;
    send("setup:config", { qaVisibility: mode });
    toast(
      { PUBLIC: "问答改为全公开", SEMI: "问答改为半公开（回答只有当事人能看到）", PRIVATE: "问答改为私密" }[mode] ||
        "已更新问答模式"
    );
  });

  root.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.mode;
      state.gameMode = mode; // 先本地生效，UI 立刻给反馈
      send("setup:config", { gameMode: mode });
      root.querySelectorAll(".mode-btn").forEach((other) => {
        const active = other.dataset.mode === mode;
        other.classList.toggle("primary", active);
        other.setAttribute("aria-pressed", String(active));
        const label = other.dataset.mode === "PERSONA" ? "人设卡" : "猜真人";
        other.textContent = `${active ? "✓ " : ""}${label}`;
      });
      const hintEl = root.querySelector(".mode-row .hint");
      if (hintEl) {
        hintEl.innerHTML = `当前玩法：<b>${
          mode === "PERSONA" ? "人设卡（先写卡 → 错位分配 → 读卡）" : "猜真人"
        }</b>；陪演 AI ${state.players.filter((p) => p.isAi).length} 个`;
      }
    });
  });

  root.querySelector("#btn-add-ai-1")?.addEventListener("click", () =>
    send("room:addAI", { count: 1 })
  );
  root.querySelector("#btn-add-ai-2")?.addEventListener("click", () =>
    send("room:addAI", { count: 2 })
  );
  root.querySelector("#btn-start")?.addEventListener("click", () => send("game:start"));
}
