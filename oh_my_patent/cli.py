"""命令行入口。

子命令对应流水线上的几个动作：

  ``build``     稿件 → 申请文件 .docx
  ``lint``      只做自检，不生成文件
  ``info``      打印解析结果摘要，用于确认稿件被正确理解
  ``template``  生成稿件骨架，降低从零起草的门槛
  ``ingest``    项目材料（Word / PowerPoint）→ Markdown，供 Agent 阅读

设计上刻意让 ``build`` 与 ``lint`` 分离：先生成再自己检查，
不如先检查再生成。``build --strict`` 把两者串起来，
自检不过就拒绝出文件，避免不合格的稿子流到交付环节。

``ingest`` 是流水线的**最上游**：用户手里的立项报告、评审 PPT 大多是
Office 文件，Agent 读不了，得先转成文本。它和 ``build`` 方向相反，
所以依赖也是分开的——不读 Office 材料就永远用不到那几个库。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, parser as draft_parser
from . import ingest as ingest_mod
from .lint import lint
from .render import render_docx
from .schema import PatentDraft, PatentType
from .spec import (
    BODY_FONT_SIZE_PT,
    LINE_SPACING,
    Font,
    RenderOptions,
    SubsectionStyle,
)


def _force_utf8() -> None:
    """Windows 控制台默认可能是 GBK，中文报告会直接乱码或抛异常。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # pragma: no cover
            pass


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------

_FONT_CHOICES = {
    "宋体": Font.SONG,
    "song": Font.SONG,
    "simsun": Font.SONG,
    "仿宋": Font.FANGSONG,
    "fangsong": Font.FANGSONG,
    "黑体": Font.HEI,
    "hei": Font.HEI,
    "simhei": Font.HEI,
}

_TYPE_CHOICES = {
    "invention": PatentType.INVENTION,
    "发明": PatentType.INVENTION,
    "utility": PatentType.UTILITY,
    "实用新型": PatentType.UTILITY,
    "design": PatentType.DESIGN,
    "外观设计": PatentType.DESIGN,
}


def _add_render_options(sub: argparse.ArgumentParser) -> None:
    group = sub.add_argument_group("版面选项")
    group.add_argument(
        "--font",
        default="宋体",
        choices=sorted(_FONT_CHOICES),
        help="正文字体。指南只允许宋体、仿宋、黑体（默认：宋体）",
    )
    group.add_argument(
        "--font-size",
        type=float,
        default=BODY_FONT_SIZE_PT,
        help=f"正文字号（磅）。指南要求字高 0.28~0.5cm 之间（默认：{BODY_FONT_SIZE_PT:g}）",
    )
    group.add_argument(
        "--line-spacing",
        type=float,
        default=LINE_SPACING,
        help=f"行距倍数（默认：{LINE_SPACING:g}）",
    )
    group.add_argument(
        "--subsection-style",
        default=SubsectionStyle.INLINE.value,
        choices=[s.value for s in SubsectionStyle],
        help=(
            "「发明内容」下三级小标题的处理方式。"
            "inline=并入段落做加粗引导词（默认），keep=保留独立小标题，flatten=只留正文"
        ),
    )
    group.add_argument(
        "--bold-sections",
        action="store_true",
        help="给【技术领域】这类章节标题加粗（默认不加粗，与公开文本一致）",
    )
    group.add_argument(
        "--no-part-titles",
        action="store_true",
        help="不输出居中的「权利要求书」「说明书摘要」等文书名称",
    )
    group.add_argument(
        "--no-page-breaks",
        action="store_true",
        help="各部分之间不分页，连续排下来",
    )
    group.add_argument(
        "--page-numbers",
        action="store_true",
        help="在页脚居中添加页码",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="oh-my-patent",
        description="自动化专利 SKILL —— 把稿件渲染成符合国知局版面要求的申请文件，同时适配 WPS 与 Office。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  oh-my-patent lint 稿件.md\n"
            "  oh-my-patent build 稿件.md -o 申请文件.docx\n"
            "  oh-my-patent build 稿件.md -o 申请文件/ --split --page-numbers\n"
            "  oh-my-patent template invention -o 新稿件.md\n"
        ),
    )
    ap.add_argument("--version", action="version", version=f"oh-my-patent {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    # ---- build ----
    p_build = sub.add_parser("build", help="把稿件渲染成 .docx 申请文件")
    p_build.add_argument("draft", help="稿件文件（.md / .yaml / .yml / .json）")
    p_build.add_argument("-o", "--output", required=True, help="输出的 .docx 路径，或 --split 时的输出目录")
    p_build.add_argument("--type", choices=sorted(_TYPE_CHOICES), help="覆盖稿件中的专利类型")
    p_build.add_argument("--split", action="store_true", help="每个部分独立成文件（对应电子申请的真实提交形态）")
    p_build.add_argument("--strict", action="store_true", help="自检不通过时拒绝生成文件")
    p_build.add_argument("--force", action="store_true", help="即使自检有错误也照常生成")
    p_build.add_argument("--json", action="store_true", help="以 JSON 输出自检结果")
    _add_render_options(p_build)

    # ---- lint ----
    p_lint = sub.add_parser("lint", help="只做合规自检，不生成文件")
    p_lint.add_argument("draft", help="稿件文件（.md / .yaml / .yml / .json）")
    p_lint.add_argument("--type", choices=sorted(_TYPE_CHOICES), help="覆盖稿件中的专利类型")
    p_lint.add_argument("--json", action="store_true", help="以 JSON 输出，便于程序消费")

    # ---- info ----
    p_info = sub.add_parser("info", help="打印解析结果摘要")
    p_info.add_argument("draft", help="稿件文件（.md / .yaml / .yml / .json）")
    p_info.add_argument("--type", choices=sorted(_TYPE_CHOICES), help="覆盖稿件中的专利类型")
    p_info.add_argument("--json", action="store_true", help="以 JSON 输出")

    # ---- template ----
    p_tpl = sub.add_parser("template", help="生成稿件骨架")
    p_tpl.add_argument(
        "patent_type",
        choices=sorted(_TYPE_CHOICES),
        help="要生成的专利类型",
    )
    p_tpl.add_argument("-o", "--output", help="输出路径。省略时写到标准输出")
    p_tpl.add_argument("--docx", action="store_true", help="改生成 .docx 空白模板而不是 Markdown 骨架")
    p_tpl.add_argument("--style", help=".docx 模板中的字体（仅 --docx 时有效）", default="宋体")
    p_tpl.add_argument("--font-size", type=float, default=BODY_FONT_SIZE_PT, help="正文字号（仅 --docx 时有效）")

    # ---- ingest ----
    p_ing = sub.add_parser(
        "ingest",
        help="把 Word / PowerPoint 材料转成 Markdown",
        description=(
            "读取项目里的 .docx / .pptx，转成 Agent 可读的 Markdown。"
            "内嵌公式会就地转成占位文本并**显式告警**（分式与上下标会退化），"
            "不会像朴素转换那样静默丢掉。"
        ),
    )
    p_ing.add_argument(
        "sources",
        nargs="+",
        help="源文件或目录。给目录时会递归找出其中全部 .docx / .pptx",
    )
    p_ing.add_argument(
        "-o",
        "--output",
        help="输出目录（每个源文件生成一个同名 .md）。省略时打到标准输出",
    )
    p_ing.add_argument(
        "--media-dir",
        help="图片输出目录。省略时为「与 .md 同级的 {名字}_media」",
    )
    p_ing.add_argument(
        "--no-images",
        action="store_true",
        help="不导出图片，只在正文留下位置提示",
    )
    p_ing.add_argument(
        "--no-header",
        action="store_true",
        help="不在 .md 顶部写入转换元信息与告警注记",
    )
    p_ing.add_argument("--json", action="store_true", help="以 JSON 输出汇总")

    return ap


# --------------------------------------------------------------------------
# 命令实现
# --------------------------------------------------------------------------

def _make_options(args: argparse.Namespace) -> RenderOptions:
    options = RenderOptions()
    options.font = _FONT_CHOICES.get(getattr(args, "font", "宋体"), Font.SONG)
    options.body_size = getattr(args, "font_size", BODY_FONT_SIZE_PT) or BODY_FONT_SIZE_PT
    options.line_spacing = getattr(args, "line_spacing", LINE_SPACING) or LINE_SPACING
    options.subsection_style = SubsectionStyle(
        getattr(args, "subsection_style", SubsectionStyle.INLINE.value)
    )
    options.bold_sections = bool(getattr(args, "bold_sections", False))
    options.include_part_titles = not bool(getattr(args, "no_part_titles", False))
    options.page_break_between_parts = not bool(getattr(args, "no_page_breaks", False))
    options.page_numbers = bool(getattr(args, "page_numbers", False))
    return options


def _load_draft(path: str, type_override: str | None = None) -> PatentDraft:
    draft = draft_parser.load(path)
    if type_override:
        draft.patent_type = _TYPE_CHOICES[type_override]
    return draft


def cmd_build(args: argparse.Namespace) -> int:
    draft = _load_draft(args.draft, args.type)
    report = lint(draft)

    if args.json:
        print(report.to_json())
    else:
        print(report.render())
        print()

    if not report.ok and args.strict and not args.force:
        print(
            f"自检发现 {len(report.errors)} 个错误，已拒绝生成文件。"
            "修正后重试，或加 --force 强制生成。",
            file=sys.stderr,
        )
        return 2

    options = _make_options(args)
    written = render_docx(draft, args.output, options=options, split=args.split)
    print(f"已生成 {len(written)} 个文件：")
    for path in written:
        size_kb = path.stat().st_size / 1024
        print(f"  {path}  ({size_kb:.1f} KB)")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    draft = _load_draft(args.draft, args.type)
    report = lint(draft)
    print(report.to_json() if args.json else report.render())
    return 0 if report.ok else 2


def cmd_info(args: argparse.Namespace) -> int:
    draft = _load_draft(args.draft, args.type)

    claims = draft.claims
    info = {
        "名称": draft.title,
        "类型": draft.patent_type.label,
        "申请人": draft.applicant or None,
        "发明人": draft.inventors or None,
        "权利要求项数": len(claims),
        "其中独立权利要求": [c.number for c in draft.independent_claims],
        "其中从属权利要求": [c.number for c in draft.dependent_claims],
        "摘要字数": len(draft.abstract.replace(" ", "").replace("\n", "")),
        "附图数量": len(draft.drawings),
        "摘要附图": (draft.abstract_figure.number if draft.abstract_figure else None),
        "章节字数": {
            "技术领域": len(draft.technical_field),
            "背景技术": len(draft.background),
            "发明内容·技术问题": len(draft.problems),
            "发明内容·技术方案": len(draft.solution),
            "发明内容·有益效果": len(draft.effects),
            "具体实施方式": len(draft.embodiments),
        },
        "来源文件": draft.source_path or None,
    }

    if args.json:
        import json

        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    print(f"名称        {draft.title}")
    print(f"类型        {draft.patent_type.label}")
    if draft.applicant:
        print(f"申请人      {draft.applicant}")
    if draft.inventors:
        print(f"发明人      {'、'.join(draft.inventors)}")
    print()
    if draft.patent_type.has_claims:
        print(
            f"权利要求    {len(claims)} 项"
            f"（独立 {'、'.join(str(c.number) for c in draft.independent_claims) or '无'}"
            f" / 从属 {'、'.join(str(c.number) for c in draft.dependent_claims) or '无'}）"
        )
        print(f"摘要        {info['摘要字数']} 字 / 上限 300 字")
    print(f"附图        {len(draft.drawings)} 幅")
    print()
    print("章节字数：")
    for name, length in info["章节字数"].items():
        if length:
            print(f"  {name:<22}{length}")
    if draft.extra_sections:
        print()
        print("额外识别的章节：")
        for extra in draft.extra_sections:
            preview = extra.body.strip().splitlines()[0][:40] if extra.body.strip() else ""
            print(f"  · {extra.heading or '(无标题)'}  {preview}")
    return 0


def cmd_template(args: argparse.Namespace) -> int:
    if args.docx:
        return _write_docx_template(args)
    return _write_markdown_template(args)


_MARKDOWN_TEMPLATES: dict[PatentType, str] = {
    PatentType.INVENTION: """---
title: 一种待填写的主题名称
type: invention
applicant: 待补充申请人名称
inventors: [待补充发明人]
---

# 权利要求书

1. 一种待填写的主题名称，其特征在于，包括：待补充技术特征。
2. 根据权利要求1所述的待填写的主题名称，其特征在于，待补充附加技术特征。

# 说明书

## 技术领域
本发明涉及待补充技术领域，具体涉及一种待填写的主题名称。

## 背景技术
待补充：现有技术是怎么做的、存在什么缺陷。

## 发明内容

### 要解决的技术问题
待补充：本发明要解决的技术问题。

### 技术方案
待补充：为解决上述技术问题所采用的技术方案，应与独立权利要求一致但可以写得更完整。

### 有益效果
待补充：本发明相对于现有技术取得的有益效果。

## 附图说明
图1为待补充的示意图。

## 具体实施方式
待补充：至少给出一个完整可实施的实施例，充分展开技术方案，使本领域技术人员能够实现。必要时给出多个实施例以支撑权利要求的保护范围。

# 摘要
待补充：写明技术问题、技术方案要点与主要用途，总字数不超过 300 字。
""",
    PatentType.UTILITY: """---
title: 一种待填写的产品名称
type: utility
applicant: 待补充申请人名称
inventors: [待补充发明人]
---

# 权利要求书

1. 一种待填写的产品名称，其特征在于，包括：待补充结构特征。
2. 根据权利要求1所述的待填写的产品名称，其特征在于，待补充附加结构特征。

# 说明书

## 技术领域
本实用新型涉及待补充技术领域，具体涉及一种待填写的产品名称。

## 背景技术
待补充：现有产品在结构上存在什么缺陷。

## 发明内容

### 要解决的技术问题
待补充：本实用新型要解决的技术问题。

### 技术方案
待补充：为解决上述技术问题所采用的技术方案。实用新型只保护产品的形状、构造或其结合，不保护方法和材料本身。

### 有益效果
待补充：本实用新型相对于现有技术取得的有益效果。

## 附图说明
图1为待补充的结构示意图。

## 具体实施方式
待补充：给出至少一个完整可实施的结构实施例，说明各部件的位置关系与连接关系。

# 摘要
待补充：写明技术问题、技术方案要点与主要用途，总字数不超过 300 字。
""",
    PatentType.DESIGN: """---
title: 待填写的产品名称
type: design
applicant: 待补充申请人名称
inventors: [待补充设计人]
drawings:
  - {number: 1, caption: 主视图, path: 待补充图片路径}
  - {number: 2, caption: 后视图, path: 待补充图片路径}
  - {number: 3, caption: 左视图, path: 待补充图片路径}
  - {number: 4, caption: 右视图, path: 待补充图片路径}
  - {number: 5, caption: 俯视图, path: 待补充图片路径}
  - {number: 6, caption: 仰视图, path: 待补充图片路径}
  - {number: 7, caption: 立体图, path: 待补充图片路径, abstract: true}
---

# 外观设计简要说明

## 用途
待补充：本外观设计产品的用途。

## 设计要点
待补充：本外观设计的设计要点，通常在于产品的形状。

## 最能表明设计要点的图片
立体图

## 省略视图说明
待补充：如有视图因对称或相同而省略，在此说明。

## 是否请求保护色彩
否
""",
}


def _write_markdown_template(args: argparse.Namespace) -> int:
    patent_type = _TYPE_CHOICES[args.patent_type]
    content = _MARKDOWN_TEMPLATES[patent_type]
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"已写出稿件骨架：{path}")
        print("提示：所有「待补充」都需要替换成真实内容，自检会把残留的占位符标出来。")
    else:
        print(content)
    return 0


def _write_docx_template(args: argparse.Namespace) -> int:
    patent_type = _TYPE_CHOICES[args.patent_type]
    draft = draft_parser.parse_markdown(_MARKDOWN_TEMPLATES[patent_type])
    options = RenderOptions()
    options.font = _FONT_CHOICES.get(args.style, Font.SONG)
    options.body_size = args.font_size

    output = args.output or f"模板_{patent_type.label}.docx"
    written = render_docx(draft, output, options=options)
    print(f"已写出 .docx 模板：{written[0]}")
    print("提示：模板中保留了「待补充」占位文字，替换完成后可用 lint 子命令复查。")
    return 0


# --------------------------------------------------------------------------
# ingest：把散落的项目材料读成文本
# --------------------------------------------------------------------------

_NOISE_DIRS = {"__pycache__", "node_modules"}

#: 用户会往项目目录里放、但本工具读不了的 Office 材料。
#: 目录扫描遇到它们**必须点名报告**——静默跳过等于悄悄丢掉用户材料：
#: 用户以为全部处理完了，实际有半数的技术文档 Agent 根本没看到。
_UNSUPPORTED_OFFICE = {
    ".doc": "旧版 Word，请另存为 .docx",
    ".ppt": "旧版 PowerPoint，请另存为 .pptx",
    ".wps": "WPS 文字，请另存为 .docx",
    ".dps": "WPS 演示，请另存为 .pptx",
    ".xls": "Excel 工作簿，本工具不处理表格",
    ".xlsx": "Excel 工作簿，本工具不处理表格",
    ".xlsm": "Excel 工作簿，本工具不处理表格",
    ".et": "WPS 表格，本工具不处理表格",
    ".pdf": "PDF，请先转成 .docx 或文本",
    ".rtf": "RTF，请另存为 .docx",
    ".odt": "ODT，请另存为 .docx",
}


def _iter_ingest_sources(
    raw_paths: list[str],
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """把「文件或目录」的参数展平成待处理清单。

    :return: ``(可转换的文件, 发现但读不了的文件及原因)``。第二个返回值不是
        可有可无的装饰——把它丢掉，就变成了静默漏材料。

    给目录时会递归查找，但**跳过隐藏目录与依赖目录**——用户的工程目录里
    躺着 ``.git``、``node_modules``、``__pycache__`` 是完全正常的事，
    进去翻找既慢又没意义。
    """
    found: list[Path] = []
    unsupported: list[tuple[Path, str]] = []

    for raw in raw_paths:
        path = Path(raw).expanduser()
        if not path.is_dir():
            # 不在这里判断存在性：交给 convert 报错，消息里会带上完整路径。
            found.append(path)
            continue

        for child in sorted(path.rglob("*")):
            if not child.is_file():
                continue
            # Office 打开文档时会生成 ~$ 开头的锁文件，不是真内容。
            if child.name.startswith("~$"):
                continue
            relative = child.relative_to(path)
            if any(
                part.startswith(".") or part in _NOISE_DIRS for part in relative.parts
            ):
                continue

            suffix = child.suffix.lower()
            if suffix in ingest_mod.SUPPORTED_SUFFIXES:
                found.append(child)
            elif suffix in _UNSUPPORTED_OFFICE:
                unsupported.append((child, _UNSUPPORTED_OFFICE[suffix]))

    seen: set[str] = set()
    unique: list[Path] = []
    for path in found:
        key = str(path.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique, unsupported


def _report_unsupported(
    unsupported: list[tuple[Path, str]], *, stream, limit: int = 12
) -> None:
    """把「发现了但读不了」的材料点名列出。

    这是刻意的啰嗦：用户丢来一个项目目录，如果里面躺着 .doc 或 .pdf，
    我们只字不提就等于替用户决定了「这些不重要」——而它们可能恰好
    是核心的技术方案文档。
    """
    if not unsupported:
        return
    print(file=stream)
    print(f"另有 {len(unsupported)} 个文件没有处理（本工具读不了）：", file=stream)
    for path, reason in unsupported[:limit]:
        print(f"  · {path.name}  —— {reason}", file=stream)
    if len(unsupported) > limit:
        print(f"  · … 还有 {len(unsupported) - limit} 个", file=stream)
    print("  请把它们另存为 .docx / .pptx，或直接提供文本后重扫。", file=stream)


def cmd_ingest(args: argparse.Namespace) -> int:
    import json
    from collections import Counter

    sources, unsupported = _iter_ingest_sources(args.sources)
    if not sources:
        print(
            "没有找到可转换的文件（支持 "
            + "、".join(sorted(ingest_mod.SUPPORTED_SUFFIXES))
            + "）。",
            file=sys.stderr,
        )
        _report_unsupported(unsupported, stream=sys.stderr)
        return 2

    out_dir = Path(args.output).expanduser() if args.output else None
    if out_dir is None and len(sources) > 1:
        print("要转换多个文件，请用 -o 指定输出目录。", file=sys.stderr)
        return 2
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    # 同名不同扩展名（``方案.docx`` 与 ``方案.pptx``）会撞到同一个 ``方案.md``，
    # 后转的把先转的覆盖掉——而汇总还报「已转换 2 个」，是假成功。
    # 只有真冲突时才给名字补上原扩展名，不冲突就保持干净的文件名。
    stem_counts = Counter(path.stem for path in sources)

    explicit_media = Path(args.media_dir).expanduser() if args.media_dir else None
    if explicit_media is not None:
        explicit_media.mkdir(parents=True, exist_ok=True)
    # 多个源文件共用一个 --media-dir 会互相覆盖图片（每个文件都从 img_0001
    # 开始编号）。所以只要源文件不止一个，就按源文件名再分一层子目录。
    share_media = explicit_media is not None and len(sources) == 1

    records: list[dict] = []
    for source in sources:
        stem = source.stem
        if stem_counts[stem] > 1:
            stem = f"{stem}.{source.suffix.lstrip('.').lower()}"

        if out_dir is not None:
            target: Path | None = out_dir / f"{stem}.md"
            if explicit_media is None:
                media = out_dir / f"{stem}_media"
            elif share_media:
                media = explicit_media
            else:
                media = explicit_media / stem
        else:
            target = None
            media = (
                explicit_media / stem
                if explicit_media is not None
                else source.parent / f"{stem}_media"
            )

        try:
            result = ingest_mod.convert(
                source, media_dir=media, extract_images=not args.no_images
            )
        except (ingest_mod.IngestError, ingest_mod.MissingDependency) as exc:
            print(f"[跳过] {source.name}：{exc}", file=sys.stderr)
            records.append({"source": str(source), "ok": False, "error": str(exc)})
            continue

        text = result.markdown
        if not args.no_header:
            text = ingest_mod.markdown_header(result) + text

        records.append(
            {
                "source": str(source),
                "ok": True,
                "output": str(target) if target else None,
                "stats": result.stats,
                "warnings": [
                    {"code": n.code, "message": n.message} for n in result.warnings
                ],
                "infos": [
                    {"code": n.code, "message": n.message} for n in result.infos
                ],
            }
        )

        if target is not None:
            target.write_text(text, encoding="utf-8")
        else:
            print(text)

    failures = [r for r in records if not r["ok"]]
    succeeded = [r for r in records if r["ok"]]

    if args.json:
        _report_unsupported(unsupported, stream=sys.stderr)
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 2 if failures else 0

    if out_dir is None:
        _report_unsupported(unsupported, stream=sys.stderr)
        return 2 if failures else 0

    print(f"已转换 {len(succeeded)} / {len(records)} 个文件：")
    for record in records:
        name = Path(record["source"]).name
        if not record["ok"]:
            print(f"  ✗ {name}  跳过（{record['error'].splitlines()[0]}）")
            continue
        stats = record["stats"]
        detail = "、".join(f"{k} {v}" for k, v in stats.items())
        print(f"  ✓ {name}  →  {record['output']}")
        print(f"      {detail}")
        for warning in record["warnings"]:
            print(f"      ⚠ {warning['code']}")
        for info in record["infos"]:
            print(f"      · {info['code']}")

    warned = [r for r in succeeded if r["warnings"]]
    if warned:
        print()
        print(
            f"注意：{len(warned)} 个文件带有告警（已写进 .md 顶部注记）。"
            "带公式的文件必须向用户核实原式后再动笔。"
        )
    noted = [r for r in succeeded if r["infos"]]
    if noted:
        print(
            f"另有 {len(noted)} 个文件带其它提示，同样写进了 .md 顶部注记——"
            "它们说的是「有内容没能提取出来」，不要当成「材料里没有」。"
        )
    _report_unsupported(unsupported, stream=sys.stdout)
    return 2 if failures else 0


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

_COMMANDS = {
    "build": cmd_build,
    "lint": cmd_lint,
    "info": cmd_info,
    "template": cmd_template,
    "ingest": cmd_ingest,
}


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    ap = build_parser()
    args = ap.parse_args(argv)

    handler = _COMMANDS[args.command]
    try:
        return handler(args)
    except draft_parser.ParseError as exc:
        print(f"稿件解析失败：\n{exc}", file=sys.stderr)
        return 1
    except ingest_mod.MissingDependency as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except ingest_mod.IngestError as exc:
        print(f"材料读取失败：{exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"文件不存在：{exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"参数或内容有误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("\n已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
