#!/usr/bin/env python
"""把一份 .pptx 按页转成 Markdown，供 Agent 阅读。

    python tools/pptx_to_md.py -i 评审.pptx -o outputs/scan/评审.md

省略 ``-o`` 时打到标准输出。

几点与常见做法的差别：

- **表格是合法的 Markdown 表格**（带 ``| --- |`` 分隔行）。少了那一行，
  渲染器不会把它认成表格——很多同类脚本正好漏了这一行。
- **幻灯片里的公式不会被静默丢掉**，会转成 ``⟪公式N: …⟫`` 占位并告警
  （占位是退化的，必须向用户核实原式）。
- **没提取到文字的那一页会被点名**。纯图形页（架构图、流程图）转出来是空的，
  这必须让 Agent 知道——否则它会以为「这页没什么内容」而跳过整页信息。

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
        description="PowerPoint (.pptx) → Markdown（按页，保留公式位置并告警）"
    )
    p.add_argument("-i", "--input", required=True, help="输入 .pptx 路径")
    p.add_argument("-o", "--output", help="输出 .md 路径。省略时打到标准输出")
    p.add_argument(
        "--media-dir",
        help="图片输出目录。省略时为「与 .md 同级的 {md 主名}_media」",
    )
    p.add_argument("--no-images", action="store_true", help="不导出幻灯片图片")
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
        result = ingest.pptx_to_markdown(
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
