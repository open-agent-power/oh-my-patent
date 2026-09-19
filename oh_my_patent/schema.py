"""专利文书的数据模型。

设计原则：**模型只描述「文书是什么」，不掺杂任何排版细节。**
所有版面规则集中在 :mod:`oh_my_patent.spec` 与 :mod:`oh_my_patent.oxml`，
使同一份模型将来可以渲染成 docx、纯文本或其它载体，而不必改动解析逻辑。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .spec import SectionKey


# --------------------------------------------------------------------------
# 专利类型
# --------------------------------------------------------------------------

class PatentType(str, Enum):
    """三种专利类型。它们的文书结构差异大到必须分别处理。"""

    INVENTION = "invention"   # 发明专利
    UTILITY = "utility"       # 实用新型
    DESIGN = "design"         # 外观设计

    @property
    def label(self) -> str:
        """中文全称，用于文书正文。"""
        return {
            PatentType.INVENTION: "发明专利",
            PatentType.UTILITY: "实用新型专利",
            PatentType.DESIGN: "外观设计专利",
        }[self]

    @property
    def has_claims(self) -> bool:
        """外观设计没有权利要求书。"""
        return self is not PatentType.DESIGN

    @property
    def has_description(self) -> bool:
        """外观设计没有说明书，只有简要说明。"""
        return self is not PatentType.DESIGN


#: 稿件 frontmatter 里 ``type:`` 字段可接受的写法。
_TYPE_ALIASES: dict[str, PatentType] = {
    "invention": PatentType.INVENTION,
    "invent": PatentType.INVENTION,
    "发明": PatentType.INVENTION,
    "发明专利": PatentType.INVENTION,
    "utility": PatentType.UTILITY,
    "um": PatentType.UTILITY,
    "utility_model": PatentType.UTILITY,
    "实用新型": PatentType.UTILITY,
    "实用新型专利": PatentType.UTILITY,
    "design": PatentType.DESIGN,
    "外观": PatentType.DESIGN,
    "外观设计": PatentType.DESIGN,
    "外观设计专利": PatentType.DESIGN,
}


def parse_patent_type(raw: str | PatentType | None) -> PatentType:
    """把用户写的类型字符串归一化成 :class:`PatentType`。"""
    if isinstance(raw, PatentType):
        return raw
    if raw is None:
        return PatentType.INVENTION
    key = str(raw).strip().lower()
    if key in _TYPE_ALIASES:
        return _TYPE_ALIASES[key]
    raise ValueError(
        f"无法识别的专利类型：{raw!r}。"
        f"可用值：invention / utility / design，或 发明 / 实用新型 / 外观设计。"
    )


# --------------------------------------------------------------------------
# 权利要求
# --------------------------------------------------------------------------

#: 从属权利要求的开头模式。
_DEPENDENT_PREFIX = re.compile(
    r"^\s*(?:根据|如|按照|依据|如权利要求|根据权利要求)\s*"
)

#: 从属权利要求中的引用编号，支持
#: 「权利要求1」「权利要求 1-3」「权利要求1或2」「权利要求1至3中任一项」等写法。
_REFERENCE_PATTERN = re.compile(
    r"权利要求\s*(\d+(?:\s*[-~至或和、,，]\s*\d+)*)"
)

#: 权利要求条的编号前缀，如 ``1.`` ``1、`` ``1．`` ``（1）``。
_CLAIM_NUMBER_PREFIX = re.compile(r"^\s*[（(]?\s*(\d+)\s*[.、．)）]\s*")


@dataclass
class Claim:
    """一项权利要求。"""

    number: int
    text: str
    #: 独立权利要求（``True``）还是从属权利要求（``False``）。
    independent: bool = True
    #: 本项所引用的在先权利要求编号，仅从属权利要求有值。
    references: list[int] = field(default_factory=list)

    @property
    def kind_label(self) -> str:
        return "独立权利要求" if self.independent else "从属权利要求"

    def render_text(self) -> str:
        """渲染成申请文件中的一行，形如 ``1. 一种……。``"""
        return f"{self.number}. {self.text.strip()}"


def build_claim(number: int, text: str) -> Claim:
    """由编号与正文推断这是一项独立权利要求还是从属权利要求。

    判断依据：权利要求书中第一项必为独立权利要求；其余各项若以
    「根据权利要求……」或「如权利要求……」开头，且有明确引用编号，
    即认定为从属权利要求。
    """
    text = text.strip()
    independent = number == 1
    references: list[int] = []

    if not independent:
        match = _REFERENCE_PATTERN.search(text)
        if match and _DEPENDENT_PREFIX.match(text):
            independent = False
            references = _expand_references(match.group(1))
        elif _REFERENCE_PATTERN.search(text) and re.match(
            r"^\s*(根据|如|按照|依据)", text
        ):
            # 形如「根据权利要求所述的……」，引用编号缺失，仍按从属处理但不记引用
            independent = False
        else:
            # 既没有引用前缀也没有引用编号，视为又一项独立权利要求
            independent = True

    return Claim(number=number, text=text, independent=independent, references=references)


def _expand_references(raw: str) -> list[int]:
    """把 ``"1-3"`` / ``"1或2"`` / ``"1至3"`` 展开成 ``[1, 2, 3]``。"""
    numbers: list[int] = []
    for chunk in re.split(r"[或和、,，]", raw):
        chunk = chunk.strip()
        if not chunk:
            continue
        range_match = re.match(r"^(\d+)\s*[-~至]\s*(\d+)$", chunk)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start <= end:
                numbers.extend(range(start, end + 1))
            else:
                numbers.extend(range(end, start + 1))
        elif chunk.isdigit():
            numbers.append(int(chunk))
    # 去重并保持顺序
    seen: set[int] = set()
    unique: list[int] = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique


def parse_claims_block(block: str) -> list[Claim]:
    """把权利要求书整块文本切成若干项权利要求。

    先尝试按编号分段，容忍三种编号写法：``1.`` ``1、`` ``（1）``，
    也容忍某一项内部因手工换行而折成多行。

    如果通篇找不到任何编号，则退回**按空行分段**——用户直接把现有的
    权利要求粘进来时经常不带编号，这时空行是唯一可靠的边界。
    缺编号本身会由自检报出来，不必在这里猜。
    """
    if not _CLAIM_NUMBER_PREFIX.search(block):
        return _parse_unnumbered_claims(block)

    claims: list[Claim] = []
    buffer: list[str] = []
    current_number: int | None = None

    def flush():
        nonlocal buffer, current_number
        if current_number is not None and buffer:
            text = " ".join(part.strip() for part in buffer if part.strip())
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                claims.append(build_claim(current_number, text))
        buffer = []

    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            # 空行意味着当前项结束
            flush()
            current_number = None
            continue
        match = _CLAIM_NUMBER_PREFIX.match(line)
        if match:
            flush()
            current_number = int(match.group(1))
            buffer = [line[match.end():]]
        elif current_number is not None:
            buffer.append(line)
        # 编号之前的散落文字忽略（多为「权利要求书」这类标题）

    flush()

    # 编号乱序或跳号时，按出现顺序重新编号，保证法定编号规则成立。
    # 重新走一遍 build_claim 是因为编号变了，独立/从属的判断也要跟着刷新。
    if claims and [c.number for c in claims] != list(range(1, len(claims) + 1)):
        claims = [
            build_claim(index, claim.text)
            for index, claim in enumerate(claims, start=1)
        ]

    return claims


def _parse_unnumbered_claims(block: str) -> list[Claim]:
    """处理通篇没有编号的权利要求书：以空行为分段边界。"""
    chunks = [
        re.sub(r"\s+", " ", " ".join(line.strip() for line in chunk.splitlines())).strip()
        for chunk in re.split(r"\n\s*\n", block)
    ]
    texts = [chunk for chunk in chunks if chunk]
    if len(texts) <= 1:
        # 整块既没有空行也没有编号，只能整体算作一项
        collapsed = re.sub(r"\s+", " ", block).strip()
        texts = [collapsed] if collapsed else []
    return [build_claim(index, text) for index, text in enumerate(texts, start=1)]


# --------------------------------------------------------------------------
# 附图
# --------------------------------------------------------------------------

@dataclass
class Drawing:
    """一幅说明书附图。"""

    number: int
    caption: str = ""
    #: 图片文件路径（png/jpg）。为空时只输出图号说明，不嵌图。
    path: str | None = None
    #: 是否被指定为摘要附图。
    is_abstract: bool = False

    def render_caption(self) -> str:
        return self.caption.strip() or f"图{self.number}为本发明的结构示意图。"


# --------------------------------------------------------------------------
# 外观设计简要说明
# --------------------------------------------------------------------------

@dataclass
class DesignBrief:
    """外观设计简要说明的法定内容项。

    依据《专利审查指南》第一部分第三章，简要说明应当写明：产品的名称、
    用途、设计要点、最能表明设计要点的图片或照片，必要时写明省略视图的
    情况及请求保护色彩。
    """

    #: 产品用途
    usage: str = ""
    #: 设计要点
    points: str = ""
    #: 最能表明设计要点的图片名称，如「立体图」
    best_view: str = ""
    #: 省略视图的说明
    omitted_views: str = ""
    #: 是否请求保护色彩
    color_protection: bool = False

    def is_empty(self) -> bool:
        return not any(
            [self.usage, self.points, self.best_view, self.omitted_views]
        ) and not self.color_protection


# --------------------------------------------------------------------------
# 完整稿件
# --------------------------------------------------------------------------

@dataclass
class Subsection:
    """说明书某章节下的一段内容。

    ``heading`` 非空表示原文里带三级小标题，渲染方式由
    :class:`~oh_my_patent.spec.SubsectionStyle` 决定。
    """

    heading: str
    body: str


@dataclass
class PatentDraft:
    """一份完整的专利申请稿件。

    这是解析层与渲染层之间唯一的契约。
    """

    title: str
    patent_type: PatentType = PatentType.INVENTION

    # ---- 著录项目 ----
    applicant: str = ""
    inventors: list[str] = field(default_factory=list)
    applicant_address: str = ""

    # ---- 说明书正文 ----
    technical_field: str = ""
    background: str = ""
    problems: str = ""
    solution: str = ""
    effects: str = ""
    embodiments: str = ""

    # ---- 附带的其它章节，按原文顺序 ----
    extra_sections: list[Subsection] = field(default_factory=list)

    # ---- 附图 ----
    drawings: list[Drawing] = field(default_factory=list)

    # ---- 权利要求与摘要 ----
    claims: list[Claim] = field(default_factory=list)
    abstract: str = ""

    # ---- 外观设计专用 ----
    design_brief: DesignBrief = field(default_factory=DesignBrief)

    # ---- 溯源信息 ----
    #: 稿件来源文件路径，写进生成物的自定义属性，便于回溯。
    source_path: str = ""

    # ----------------------------------------------------------------
    # 便捷视图
    # ----------------------------------------------------------------

    @property
    def summary_section_title(self) -> str:
        """发明内容 / 实用新型内容，随类型切换。"""
        from .spec import SECTION_TITLES

        table = SECTION_TITLES.get(self.patent_type.value)
        if table is None:
            return "发明内容"
        return table[SectionKey.SUMMARY]

    @property
    def independent_claims(self) -> list[Claim]:
        return [c for c in self.claims if c.independent]

    @property
    def dependent_claims(self) -> list[Claim]:
        return [c for c in self.claims if not c.independent]

    @property
    def abstract_figure(self) -> Drawing | None:
        """摘要附图。

        显式指定为摘要附图的优先；没有指定时取编号最小的一幅。
        按编号而不是按列表顺序取，是为了让结果不受稿件里附图排列次序影响。

        之所以默认兜底而不是返回 ``None``：《专利法实施细则》要求有附图的
        申请必须提供一幅最能说明发明技术特征的附图，兜底比留空更合规。
        """
        for drawing in self.drawings:
            if drawing.is_abstract:
                return drawing
        return min(self.drawings, key=lambda d: d.number) if self.drawings else None

    @property
    def summary_is_structured(self) -> bool:
        """「发明内容」是否按技术问题／技术方案／有益效果三段组织。

        两种写法的渲染方式完全不同：

          - **分段式**（本属性为 ``True``）：作者显式写了「要解决的技术问题」
            和「有益效果」。此时各段可以带上对应的引导词。
          - **连写式**（``False``）：作者把整个发明内容写成连续几段，
            全部落在 ``solution`` 字段里。此时不能再补引导词，
            否则会凭空多出一个错误的「技术方案：」前缀。
        """
        return bool(self.problems.strip()) or bool(self.effects.strip())

    @property
    def summary_parts(self) -> list[tuple[str, str]]:
        """按法定顺序返回发明内容的分段，形如 ``[("技术方案", "...")]``。"""
        parts: list[tuple[str, str]] = []
        if self.problems.strip():
            parts.append(("要解决的技术问题", self.problems.strip()))
        if self.solution.strip():
            parts.append(("技术方案", self.solution.strip()))
        if self.effects.strip():
            parts.append(("有益效果", self.effects.strip()))
        return parts

    def sections(self) -> list[tuple[SectionKey, str]]:
        """按法定顺序返回说明书各章节及其正文。

        「发明内容」由技术问题、技术方案、有益效果三段拼成，
        中间不再插入小标题，直接连成规范段落。
        """
        result: list[tuple[SectionKey, str]] = []
        if self.technical_field.strip():
            result.append((SectionKey.TECHNICAL_FIELD, self.technical_field))
        if self.background.strip():
            result.append((SectionKey.BACKGROUND, self.background))

        summary_parts = [text for _, text in self.summary_parts]
        if summary_parts:
            result.append((SectionKey.SUMMARY, "\n\n".join(summary_parts)))

        if self.drawings:
            captions = [line for line in self._drawing_captions()]
            if captions:
                result.append((SectionKey.DRAWING_DESC, "\n".join(captions)))

        if self.embodiments.strip():
            result.append((SectionKey.EMBODIMENTS, self.embodiments))

        return result

    def _drawing_captions(self) -> list[str]:
        return [
            d.render_caption()
            for d in sorted(self.drawings, key=lambda x: x.number)
        ]

    def has_any_content(self) -> bool:
        return bool(
            self.claims
            or self.abstract.strip()
            or self.sections()
            or not self.design_brief.is_empty()
        )

    # ----------------------------------------------------------------
    # 遍历
    # ----------------------------------------------------------------

    def iter_text(self) -> list[tuple[str, str]]:
        """返回稿件中所有 ``(位置, 文本)`` 对。

        检查层需要"通读全稿找某个东西"，与其在每个检查函数里各写一遍
        遍历逻辑，不如把它放在模型上——位置标签也就只有这一处需要维护。
        """
        items: list[tuple[str, str]] = [("名称", self.title)]

        if self.abstract:
            items.append(("摘要", self.abstract))

        for claim in self.claims:
            items.append((f"权利要求{claim.number}", claim.text))

        for field_name, label in (
            ("technical_field", "技术领域"),
            ("background", "背景技术"),
            ("problems", "发明内容·技术问题"),
            ("solution", "发明内容·技术方案"),
            ("effects", "发明内容·有益效果"),
            ("embodiments", "具体实施方式"),
        ):
            value = getattr(self, field_name, "")
            if value:
                items.append((label, value))

        for index, subsection in enumerate(self.extra_sections, start=1):
            if subsection.body:
                items.append((subsection.heading or f"补充章节{index}", subsection.body))

        brief = self.design_brief
        for value, label in (
            (brief.usage, "简要说明·用途"),
            (brief.points, "简要说明·设计要点"),
            (brief.best_view, "简要说明·代表图"),
            (brief.omitted_views, "简要说明·省略视图"),
        ):
            if value:
                items.append((label, value))

        return items

    def claims_text(self) -> str:
        """全部权利要求的文本，用于「权利要求里有没有提到某件事」这类判断。"""
        return "\n".join(claim.text for claim in self.claims)

    def description_text(self) -> str:
        """说明书正文（技术领域 → 具体实施方式），**不含权利要求与摘要**。

        这个区分很关键：指南要求"说明书应当记载……"，判断依据只能是说明书
        本身。若把权利要求也算进去，会出现"权利要求写了但说明书没写"
        却被判为合规的情况——而这恰恰是「得不到说明书支持」的典型缺陷。
        """
        parts = [
            self.technical_field,
            self.background,
            self.problems,
            self.solution,
            self.effects,
            self.embodiments,
        ]
        parts.extend(s.body for s in self.extra_sections if s.body)
        return "\n".join(part for part in parts if part)
