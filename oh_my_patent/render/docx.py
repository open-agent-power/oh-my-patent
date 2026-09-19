"""把稿件渲染成符合规范版面的 .docx。

版面规则全部来自 :mod:`oh_my_patent.spec`，底层 XML 修补全部委托给
:mod:`oh_my_patent.oxml`。本模块只负责「把哪些内容放成哪些段落」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt

from .. import oxml
from ..schema import PatentDraft, PatentType
from ..spec import (
    PART_ORDER,
    PART_TITLES,
    SECTION_TITLE_PATTERN,
    SECTION_TITLES,
    HEADING_NAME_FONT_SIZE_PT,
    TITLE_FONT_SIZE_PT,
    RenderOptions,
    SectionKey,
    SubsectionStyle,
)

#: A4 去掉左右页边距后可用的正文宽度（毫米）：210 - 25 - 15。
CONTENT_WIDTH_MM = 170.0
#: 插图的最大高度（毫米），超过就按高度反推宽度，避免图片把整页顶开。
MAX_IMAGE_HEIGHT_MM = 200.0
#: 插图的常规宽度（毫米）。
DEFAULT_IMAGE_WIDTH_MM = 150.0

#: 正文里的行内加粗标记，形如 ``**技术方案**``。
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
#: 渲染时需要在末尾留一个空格的引导词
_LEAD_IN_TEMPLATE = "**{label}：**"
#: 图片容器的元素路径。段落没有文字但有图片时，它依然是有内容的段落，
#: 不能被当成空段落清掉。
_W_DRAWING = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing"


@dataclass
class _Block:
    """说明书里的一个内容块。

    ``level == 1`` 对应 ``【技术领域】`` 这类法定章节；
    ``level == 2`` 对应章节内部的小标题。
    """

    level: int
    title: str
    paragraphs: list[str] = field(default_factory=list)


class DocxRenderer:
    """把一份 :class:`PatentDraft` 渲染成 .docx 文档。"""

    def __init__(self, draft: PatentDraft, options: RenderOptions | None = None):
        self.draft = draft
        self.options = options or RenderOptions()
        self._western, self._east_asian = self.options.resolved_fonts()
        self._doc: Document | None = None
        self._pending_break = False

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def render(self, parts: list[str] | None = None) -> Document:
        """把选定的部分合成**一个**文档，各部分之间按需分页。"""
        self._doc = self._new_document()
        builders = self._select_builders(parts)
        for index, (_, builder) in enumerate(builders):
            if index > 0 and self.options.page_break_between_parts:
                self._pending_break = True
            builder()
        self._pending_break = False
        self._trim_trailing_empty()
        return self._doc

    def render_split(self) -> list[tuple[str, Document]]:
        """每个部分各自成文，返回 ``[(部分键, 文档)]``。

        国知局的电子申请要求各部分独立成文件、独立编页，
        这个模式对应真实提交场景。

        没有实际内容的部分会被跳过——一份只有版面设置、没有任何段落的
        ``.docx`` 提交上去只会添乱，不如不产出。
        """
        results: list[tuple[str, Document]] = []
        for key, builder in self._select_builders(None):
            self._doc = self._new_document()
            self._pending_break = False
            builder()
            self._trim_trailing_empty()
            if not self._has_content():
                continue
            results.append((key, self._doc))
        return results

    def save(self, path: str | Path, parts: list[str] | None = None) -> Path:
        """渲染并写出单个文件。"""
        document = self.render(parts)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(path))
        return path

    def save_split(self, output_dir: str | Path, stem: str | None = None) -> list[Path]:
        """渲染并写出拆分后的多个文件，返回写出的文件列表。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = stem or _safe_filename(self.draft.title)

        written: list[Path] = []
        for key, document in self.render_split():
            target = output_dir / f"{stem}_{PART_TITLES.get(key, key)}.docx"
            document.save(str(target))
            written.append(target)
        return written

    # ------------------------------------------------------------------
    # 文档骨架
    # ------------------------------------------------------------------

    def _new_document(self) -> Document:
        document = Document()
        oxml.configure_document(document, self.options)
        if self.options.page_numbers:
            oxml.add_page_number_footer(
                document.sections[0], self._western, self._east_asian, self.options.body_size
            )
        return document

    def _select_builders(self, parts: list[str] | None):
        available = self._builders()
        if parts is None:
            return available
        wanted = set(parts)
        return [(key, builder) for key, builder in available if key in wanted]

    def _builders(self):
        """按法定顺序列出本稿件需要输出的部分。"""
        draft = self.draft

        if draft.patent_type is PatentType.DESIGN:
            if not draft.design_brief.is_empty() or draft.title:
                return [("design_brief", self._render_design_brief)]
            return []

        builders = [
            ("claims", self._render_claims),
            ("description", self._render_description),
            ("abstract", self._render_abstract),
            ("drawings", self._render_drawings),
        ]
        return [
            (key, builder)
            for key, builder in builders
            if key in PART_ORDER
        ]

    def _trim_trailing_empty(self) -> None:
        """删除文末多余的空段落。

        空段落会让最终页多出一行，在分页处的表现尤其明显。
        但含图片的段落即使没有文字也必须保留。
        """
        body = self._doc.element.body
        while True:
            paragraphs = self._doc.paragraphs
            if not paragraphs:
                return
            last = paragraphs[-1]
            if last.text.strip() or last._element.findall(f".//{_W_DRAWING}"):
                return
            body.remove(last._element)

    def _has_content(self) -> bool:
        """文档里是否有实际内容（文字或图片）。"""
        for paragraph in self._doc.paragraphs:
            if paragraph.text.strip():
                return True
            if paragraph._element.findall(f".//{_W_DRAWING}"):
                return True
        return False

    # ------------------------------------------------------------------
    # 通用段落构造
    # ------------------------------------------------------------------

    def _add_paragraph(
        self,
        text: str = "",
        *,
        align=None,
        indent_chars: float | None = None,
        bold: bool = False,
        size: float | None = None,
        space_before: float | None = None,
        keep_with_next: bool = False,
    ):
        """新建一个段落，并把「待分页」标记消费掉。"""
        paragraph = self._doc.add_paragraph()

        if self._pending_break:
            oxml.set_page_break_before(paragraph, True)
            self._pending_break = False

        size = size if size is not None else self.options.body_size
        if indent_chars is None:
            indent_chars = self.options.first_line_indent

        oxml.set_paragraph_format(
            paragraph,
            line_spacing=self.options.line_spacing,
            first_line_indent_chars=indent_chars,
            char_width_pt=size,
            space_before_pt=space_before,
            space_after_pt=0,
            alignment=align if align is not None else WD_ALIGN_PARAGRAPH.LEFT,
            keep_with_next=keep_with_next,
        )
        self._write_text(paragraph, text, size, bold)
        return paragraph

    def _write_text(self, paragraph, text: str, size: float, bold: bool) -> None:
        """写入文字，支持 ``**加粗**`` 行内标记。"""
        position = 0
        for match in _BOLD_RE.finditer(text):
            if match.start() > position:
                self._add_run(paragraph, text[position:match.start()], size, bold)
            self._add_run(paragraph, match.group(1), size, True)
            position = match.end()
        tail = text[position:]
        if tail or position == 0:
            self._add_run(paragraph, tail, size, bold)

    def _add_run(self, paragraph, text: str, size: float, bold: bool):
        run = paragraph.add_run(text)
        oxml.set_run_font(
            run, self._western, self._east_asian, size_pt=size, bold=bold
        )
        return run

    def _add_image(self, path: str | Path):
        """插入一张居中插图，自动约束到正文宽度与最大高度之内。"""
        from docx.image.image import Image as _DocxImage

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"附图文件不存在：{path}")

        natural = _DocxImage.from_file(str(path))
        ratio = natural.height / natural.width if natural.width else 1.0

        width = min(DEFAULT_IMAGE_WIDTH_MM, CONTENT_WIDTH_MM)
        height = width * ratio
        if height > MAX_IMAGE_HEIGHT_MM:
            height = MAX_IMAGE_HEIGHT_MM
            width = height / ratio

        shape = self._doc.add_picture(str(path), width=Mm(width), height=Mm(height))
        paragraph = self._doc.paragraphs[-1]

        if self._pending_break:
            oxml.set_page_break_before(paragraph, True)
            self._pending_break = False

        oxml.set_paragraph_format(
            paragraph,
            alignment=WD_ALIGN_PARAGRAPH.CENTER,
            first_line_indent_chars=0,
            line_spacing=1.0,
            char_width_pt=self.options.body_size,
            space_after_pt=6,
        )
        return shape

    def _add_part_title(self, key: str):
        """居中的文书名称，如「权利要求书」。"""
        if not self.options.include_part_titles:
            return None
        return self._add_paragraph(
            PART_TITLES.get(key, key),
            align=WD_ALIGN_PARAGRAPH.CENTER,
            indent_chars=0,
            bold=True,
            size=TITLE_FONT_SIZE_PT,
            space_before=0,
            keep_with_next=True,
        )

    @staticmethod
    def _paragraphs_of(text: str) -> list[str]:
        """把一段文本切成段落。

        **每一处换行都视为段落边界。** 中文文书没有硬折行的习惯，
        稿件里出现换行就意味着一段的结束。行内需要软换行的场景极少，
        而「每个附图说明单独成段」这类需求非常常见，所以取这个规则。

        段落内部多余的空白会被压缩掉，因为从 PDF 或网页复制过来的文本
        常带着不规则的空格。
        """
        result: list[str] = []
        for chunk in re.split(r"\n+", text.strip()):
            cleaned = re.sub(r"[ \t\u3000]+", " ", chunk).strip()
            if cleaned:
                result.append(cleaned)
        return result

    # ------------------------------------------------------------------
    # 各部分渲染
    # ------------------------------------------------------------------

    def _render_claims(self) -> None:
        claims = self.draft.claims
        if not claims:
            return
        self._add_part_title("claims")
        for claim in claims:
            self._add_paragraph(claim.render_text())

    def _render_description(self) -> None:
        blocks = self._description_blocks()
        if not blocks:
            return

        # 说明书首行是发明名称，居中、三号加粗，与请求书中的名称一致。
        self._add_paragraph(
            self.draft.title,
            align=WD_ALIGN_PARAGRAPH.CENTER,
            indent_chars=0,
            bold=True,
            size=HEADING_NAME_FONT_SIZE_PT,
            space_before=0,
            keep_with_next=True,
        )

        for block in blocks:
            if block.level == 1:
                self._add_paragraph(
                    SECTION_TITLE_PATTERN.format(title=block.title),
                    indent_chars=0,
                    bold=self.options.bold_sections,
                    keep_with_next=True,
                )
            else:
                self._add_paragraph(
                    block.title,
                    indent_chars=0,
                    bold=True,
                    keep_with_next=True,
                )
            for paragraph_text in block.paragraphs:
                self._add_paragraph(paragraph_text)

    def _description_blocks(self) -> list[_Block]:
        """组装说明书的全部内容块，顺序严格遵循审查指南。"""
        draft = self.draft
        titles = SECTION_TITLES.get(draft.patent_type.value, SECTION_TITLES["invention"])
        blocks: list[_Block] = []

        if draft.technical_field.strip():
            blocks.append(
                _Block(1, titles[SectionKey.TECHNICAL_FIELD], self._paragraphs_of(draft.technical_field))
            )
        if draft.background.strip():
            blocks.append(
                _Block(1, titles[SectionKey.BACKGROUND], self._paragraphs_of(draft.background))
            )

        blocks.extend(self._summary_blocks(titles[SectionKey.SUMMARY]))

        captions = [
            drawing.render_caption()
            for drawing in sorted(draft.drawings, key=lambda d: d.number)
        ]
        if captions:
            blocks.append(_Block(1, titles[SectionKey.DRAWING_DESC], captions))

        if draft.embodiments.strip():
            blocks.append(
                _Block(1, titles[SectionKey.EMBODIMENTS], self._paragraphs_of(draft.embodiments))
            )

        for subsection in draft.extra_sections:
            heading = subsection.heading.strip()
            body = subsection.body.strip()
            if not heading and not body:
                continue
            blocks.append(
                _Block(
                    2,
                    heading or "补充说明",
                    self._paragraphs_of(body) if body else [],
                )
            )

        return blocks

    def _summary_blocks(self, title: str) -> list[_Block]:
        """按设定的处理方式展开「发明内容」。"""
        draft = self.draft

        if not draft.summary_is_structured:
            # 连写式：整段正文直接放在【发明内容】下，不加任何引导词。
            body = draft.solution or "\n\n".join(
                text for _, text in draft.summary_parts
            )
            return [_Block(1, title, self._paragraphs_of(body))] if body.strip() else []

        parts = draft.summary_parts
        style = self.options.subsection_style

        if style is SubsectionStyle.FLATTEN:
            merged = "\n\n".join(text for _, text in parts)
            return [_Block(1, title, self._paragraphs_of(merged))]

        if style is SubsectionStyle.KEEP:
            blocks: list[_Block] = []
            problems = [text for label, text in parts if label == "要解决的技术问题"]
            blocks.append(
                _Block(1, title, self._paragraphs_of(problems[0]) if problems else [])
            )
            for label, text in parts:
                if label == "要解决的技术问题":
                    continue
                blocks.append(_Block(2, label, self._paragraphs_of(text)))
            return blocks

        # INLINE（默认）：把小标题变成正文段落开头的加粗引导词
        merged_paragraphs: list[str] = []
        for label, text in parts:
            paragraphs = self._paragraphs_of(text)
            if not paragraphs:
                continue
            paragraphs[0] = _LEAD_IN_TEMPLATE.format(label=label) + paragraphs[0]
            merged_paragraphs.extend(paragraphs)
        return [_Block(1, title, merged_paragraphs)] if merged_paragraphs else []

    def _render_abstract(self) -> None:
        abstract = self.draft.abstract.strip()
        figure = self.draft.abstract_figure
        has_figure = bool(figure and figure.path)
        if not abstract and not has_figure:
            return

        self._add_part_title("abstract")
        for paragraph_text in self._paragraphs_of(abstract):
            self._add_paragraph(paragraph_text)

        if has_figure:
            try:
                self._add_image(figure.path)
            except (FileNotFoundError, ValueError) as exc:
                self._add_paragraph(f"（摘要附图缺失：{exc}）")

    def _render_drawings(self) -> None:
        drawings = [d for d in sorted(self.draft.drawings, key=lambda d: d.number) if d.path]
        if not drawings:
            return

        self._add_part_title("drawings")
        for drawing in drawings:
            try:
                self._add_image(drawing.path)
            except (FileNotFoundError, ValueError) as exc:
                self._add_paragraph(f"（图{drawing.number}缺失：{exc}）")
                continue
            self._add_paragraph(
                f"图{drawing.number}",
                align=WD_ALIGN_PARAGRAPH.CENTER,
                indent_chars=0,
                size=self.options.body_size,
            )

    def _render_design_brief(self) -> None:
        """外观设计简要说明。

        审查指南要求写明：产品名称、用途、设计要点、最能表明设计要点的
        图片或照片；必要时写明省略视图的情况与是否请求保护色彩。
        条目按法定顺序编号。
        """
        draft = self.draft
        brief = draft.design_brief

        items: list[tuple[str, str]] = [(f"本外观设计产品的名称：{draft.title}。", draft.title)]
        if brief.usage:
            items.append((f"本外观设计产品的用途：{brief.usage.rstrip('。')}。", brief.usage))
        if brief.points:
            items.append(
                (f"本外观设计的设计要点：{brief.points.rstrip('。')}。", brief.points)
            )
        if brief.best_view:
            items.append(
                (
                    f"最能表明设计要点的图片或照片：{brief.best_view.rstrip('。')}。",
                    brief.best_view,
                )
            )
        if brief.omitted_views:
            items.append(
                (f"省略视图说明：{brief.omitted_views.rstrip('。')}。", brief.omitted_views)
            )
        if brief.color_protection:
            items.append(
                ("请求保护的外观设计包含色彩。", "请求保护色彩")
            )

        self._add_part_title("design_brief")
        for index, (paragraph_text, _) in enumerate(items, start=1):
            self._add_paragraph(f"{index}. {paragraph_text}")

        for extra in draft.extra_sections:
            if extra.body.strip():
                for paragraph_text in self._paragraphs_of(extra.body):
                    self._add_paragraph(paragraph_text)

        for drawing in sorted(draft.drawings, key=lambda d: d.number):
            if drawing.path:
                try:
                    self._add_image(drawing.path)
                except (FileNotFoundError, ValueError) as exc:
                    self._add_paragraph(f"（图片缺失：{exc}）")


# --------------------------------------------------------------------------
# 便捷函数
# --------------------------------------------------------------------------

def render_docx(
    draft: PatentDraft,
    output: str | Path,
    options: RenderOptions | None = None,
    split: bool = False,
) -> list[Path]:
    """把稿件渲染成 .docx。

    :param output: ``split=False`` 时是输出文件路径；``split=True`` 时是输出目录
    :param split: 是否每个部分独立成文件（对应国知局电子申请的真实提交形态）
    :return: 实际写出的文件列表
    """
    renderer = DocxRenderer(draft, options)
    if split:
        return renderer.save_split(output)
    return [renderer.save(output)]


def _safe_filename(name: str) -> str:
    """把发明名称转成安全的文件名。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip(" .")
    cleaned = re.sub(r"_{2,}", "_", cleaned)
    return cleaned[:80] or "patent"
