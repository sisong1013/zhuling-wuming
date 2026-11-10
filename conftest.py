"""仓库根 conftest：把项目根目录加进 sys.path。

为什么需要它：CI 里用的是裸 `pytest`（脚本模式），这时当前目录**不会**自动进 sys.path，
而测试文件里有 `from server import ...` 的模块级导入，就会报
`ModuleNotFoundError: No module named 'server'`。
本地因为常用 `python -m pytest`（模块模式会把 cwd 加进 sys.path）而掩盖了这个差异。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
