/* timer.js —— 环形倒计时（只读服务端 deadline，本地算进度） */

const R = 16;
const C = 2 * Math.PI * R;

let ticker = null;

export function mountTimer(root) {
  if (!root || root.dataset.ready === "1") return root;
  root.dataset.ready = "1";
  root.innerHTML = `
    <span class="label">沙漏</span>
    <span class="timer__row">
      <svg class="ring" viewBox="0 0 40 40" aria-hidden="true">
        <circle class="ring__bg" cx="20" cy="20" r="${R}"></circle>
        <circle class="ring__fg" cx="20" cy="20" r="${R}"
          stroke-dasharray="${C.toFixed(2)}" stroke-dashoffset="0"></circle>
      </svg>
      <b class="timer__text">—</b>
    </span>`;
  return root;
}

export function renderTimer(root, state) {
  if (!root) return;
  const fg = root.querySelector(".ring__fg");
  const text = root.querySelector(".timer__text");
  const { deadline, phase } = state;

  if (!deadline) {
    // 没有 deadline 时不要每 200ms 重写 DOM（省性能，也避免无意义变动）
    if (fg && fg.style.strokeDashoffset !== String(C)) fg.style.strokeDashoffset = String(C);
    if (text && text.textContent !== "—") text.textContent = "—";
    root.classList.remove("is-danger");
    document.body.classList.remove("is-danger");
    return;
  }

  const total = phaseTotal(state, deadline);
  const left = Math.max(0, deadline - Date.now() / 1000);
  const pct = Math.max(0, Math.min(1, left / total));
  const offset = String(Math.round(C * (1 - pct) * 100) / 100);
  if (fg && fg.style.strokeDashoffset !== offset) fg.style.strokeDashoffset = offset;
  const label = `${left.toFixed(0)}s`;
  if (text && text.textContent !== label) text.textContent = label;

  const danger = left <= 10;
  root.classList.toggle("is-danger", danger);
  document.body.classList.toggle("is-danger", danger);
}

/** 本阶段总时长：用 config 里的秒数兜底，拿不到就按当前剩余推断 */
function phaseTotal(state, deadline) {
  const cfg = state.config || {};
  const map = {
    PHASE1: cfg.phase1Seconds,
    PHASE2: cfg.phase2Seconds,
    PHASE3: cfg.phase3Seconds,
    READING: cfg.readingSeconds,
  };
  const known = map[state.phase];
  if (known) return known;
  return Math.max(1, deadline - Date.now() / 1000);
}

export function startTicker(getState, getRoot) {
  if (ticker) clearInterval(ticker);
  ticker = setInterval(() => {
    const root = getRoot();
    if (root) renderTimer(root, getState());
  }, 200);
}
