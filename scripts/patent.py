#!/usr/bin/env python
"""免安装入口。

直接跑这个脚本即可，不需要先 ``pip install -e .``：

    python scripts/patent.py lint 稿件.md
    python scripts/patent.py build 稿件.md -o 申请文件.docx

它所做的唯一一件事，就是把仓库根目录塞进 ``sys.path`` 后转发给
:func:`oh_my_patent.cli.main`。真正的逻辑一行都不在这里。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from oh_my_patent.cli import main  # noqa: E402  (必须在 sys.path 调整之后导入)

if __name__ == "__main__":
    raise SystemExit(main())
