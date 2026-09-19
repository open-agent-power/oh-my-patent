"""命令行入口。

三个子命令对应流水线上的三个动作：

  ``build``     稿件 → 申请文件 .docx
  ``lint``      只做自检，不生成文件
  ``info``      打印解析结果摘要，用于确认稿件被正确理解
  ``template``  生成稿件骨架，降低从零起草的门槛

设计上刻意让 ``build`` 与 ``lint`` 分离：先生成再自己检查，
不如先检查再生成。``build --strict`` 把两者串起来，
自检不过就拒绝出文件，避免不合格的稿子流到交付环节。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, parser as draft_parser
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
# 入口
# --------------------------------------------------------------------------

_COMMANDS = {
    "build": cmd_build,
    "lint": cmd_lint,
    "info": cmd_info,
    "template": cmd_template,
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
