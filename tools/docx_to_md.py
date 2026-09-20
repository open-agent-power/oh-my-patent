#!/usr/bin/env python
"""把一份 .docx 转成 Markdown，供 Agent 阅读。

    python tools/docx_to_md.py -i 立项报告.docx -o outputs/scan/立项报告.md
    python tools/docx_to_md.py -i a.docx --media-dir 图片/     # 图片另存他处

省略 ``-o`` 时打到标准输出。

**与同类工具的差别**（这是它存在的理由）：Word 里的内嵌公式不会被静默丢掉。
朴素转换（mammoth 的 Markdown 输出）会把公式整段吞掉，只留一个空格，
于是 Agent 读到一份「看起来完整、其实缺了核心公式」的技术方案。
这里改为就地转成 ``⟪公式N: …⟫`` 占位，并把告警写进 .md 顶部。

**但占位里的式子是退化的**：分式被摊平（``1/2`` 变成 ``12``）、上下标会掉层级。
它只用来定位「这里有个公式」，绝不能当原式照抄——必须向用户索取原式。

真正的逻辑在 :mod:`oh_my_patent.ingest`，这里只做参数解析与落盘。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from oh_my_patent import ingest  # noqa: E402  (必须在 sys.path 调整之后导入)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Word (.docx) → Markdown（保留公式位置并告警）"
    )
    p.add_argument("-i", "--input", required=True, help="输入 .docx 路径")
    p.add_argument("-o", "--output", help="输出 .md 路径。省略时打到标准输出")
    p.add_argument(
        "--media-dir",
        help="图片输出目录。省略时为「与 .md 同级的 {md 主名}_media」",
    )
    p.add_argument("--no-images", action="store_true", help="不导出图片")
    p.add_argument("--no-header", action="store_true", help="不写顶部元信息与告警注记")
    args = p.parse_args(argv)

    source = Path(args.input).expanduser()
    target = Path(args.output).expanduser() if args.output else None
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)

    if args.media_dir:
        media = Path(args.media_dir).expanduser()
    elif target is not None:
        media = target.parent / f"{target.stem}_media"
    else:
        media = source.parent / f"{source.stem}_media"

    try:
        result = ingest.docx_to_markdown(
            source, media_dir=media, extract_images=not args.no_images
        )
    except (ingest.IngestError, ingest.MissingDependency) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    text = result.markdown
    if not args.no_header:
        text = ingest.markdown_header(result) + text

    if target is not None:
        target.write_text(text, encoding="utf-8")
        print(f"已写入：{target}")
        print(f"图片目录：{media}")
    else:
        print(text)

    print(ingest.format_notices(result), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
