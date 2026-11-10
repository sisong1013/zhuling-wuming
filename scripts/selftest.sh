#!/usr/bin/env bash
# 一键自测：起真实 uvicorn（由 pytest 的 conftest 负责），跑全部 pytest。
# 用法：bash scripts/selftest.sh [额外的 pytest 参数]
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

# 选解释器：优先项目内 venv（Windows / POSIX 两套路径都试），最后才是系统 python。
# 判定标准不是「存在」，而是「能 import fastapi」——WindowsApps 的假 python3 要排除。
CANDIDATES=()
if [[ -n "${PYTHON:-}" ]]; then
  CANDIDATES+=("$PYTHON")
fi
CANDIDATES+=(
  ".venv/Scripts/python.exe"
  ".venv/bin/python"
  "../.venv/Scripts/python.exe"
  "../.venv/bin/python"
  "python3"
  "python"
  "py -3.11"
)

PY=""
for cand in "${CANDIDATES[@]}"; do
  if command -v $cand >/dev/null 2>&1; then
    if $cand -c "import fastapi, uvicorn, pytest, pytest_asyncio, websockets, httpx" >/dev/null 2>&1; then
      PY="$cand"
      break
    fi
  fi
done

if [[ -z "$PY" ]]; then
  echo "[selftest] ❌ 找不到装好依赖的 Python。请先建 venv 并 pip install -r requirements.txt"
  exit 2
fi

echo "[selftest] 解释器: $PY"
"$PY" -c "import sys; print('[selftest] 版本:', sys.version.split()[0])"

echo "[selftest] pytest 开始"
"$PY" -m pytest -q "$@"
RC=$?

if [[ $RC -eq 0 ]]; then
  echo "[selftest] ✅ 全部通过"
else
  echo "[selftest] ❌ 有失败，退出码 $RC"
fi
exit $RC
