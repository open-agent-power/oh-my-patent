"""申请文件版面格式规范常量。

本模块只放「规范怎么说」这一类硬事实，不放任何实现逻辑。
所有数值都对应国家知识产权局《专利审查指南》对申请文件格式的要求，
集中在此处便于审阅与调整。

主要依据：
  - 《专利审查指南》第一部分第一章  发明专利申请的初步审查
  - 《专利审查指南》第一部分第二章  实用新型专利申请的初步审查
  - 《专利审查指南》第一部分第三章  外观设计专利申请的初步审查

需要注意，审查指南只给出「范围」而非「唯一值」的地方（例如字号），
这里选取的是实务中最通用、且在 WPS 与 MS Office 下表现一致的取值。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# --------------------------------------------------------------------------
# 纸张与页边距
# --------------------------------------------------------------------------

#: A4 纵向，单位毫米
PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 297.0

#: 页边距（毫米）。指南规定：上 25、左 25、右 15、下 15。
MARGIN_TOP_MM = 25.0
MARGIN_LEFT_MM = 25.0
MARGIN_RIGHT_MM = 15.0
MARGIN_BOTTOM_MM = 15.0

#: 指南要求字高介于 0.28cm ~ 0.5cm，正文取小四（12pt ≈ 0.42cm）居中最稳妥。
BODY_FONT_SIZE_PT = 12.0
#: 文书名称（如「权利要求书」）与发明名称的居中标题字号，二号加粗。
TITLE_FONT_SIZE_PT = 22.0
#: 发明名称在说明书首行的字号，三号加粗。
HEADING_NAME_FONT_SIZE_PT = 16.0
#: 【技术领域】这类章节标题字号，与正文一致，符合公开文本的朴素排版。
SECTION_FONT_SIZE_PT = 12.0

#: 行距倍数。指南要求行距不小于 0.28cm，1.5 倍行距是最常见的实务取值。
LINE_SPACING = 1.5

#: 正文首行缩进字符数（中文文书惯例 2 字符 = 2 em）。
FIRST_LINE_INDENT_CHARS = 2


# --------------------------------------------------------------------------
# 字体
# --------------------------------------------------------------------------

class Font(str, Enum):
    """指南允许在申请文件中使用的汉字字体：宋体、仿宋、黑体。"""

    SONG = "宋体"
    FANGSONG = "仿宋"
    HEI = "黑体"

    @property
    def western(self) -> str:
        """与中文字体配对的西文字体。

        西文必须显式指定，且必须与中文字体分开声明（OOXML 的
        ``w:rFonts`` 区分 ``w:ascii`` / ``w:hAnsi`` 与 ``w:eastAsia``）。
        否则 WPS 与 MS Office 会各自套用不同的西文回退字体，
        导致同一份文件在两处渲染出的字形宽度不同、行break位置漂移。
        """
        return {
            Font.SONG: "Times New Roman",
            Font.FANGSONG: "Times New Roman",
            Font.HEI: "Arial",
        }[self]


#: 正文默认字体：宋体。
BODY_FONT = Font.SONG


# --------------------------------------------------------------------------
# 说明书章节结构
# --------------------------------------------------------------------------

class SectionKey(str, Enum):
    """说明书的标准章节。键名与审查指南的表述一一对应。"""

    TECHNICAL_FIELD = "technical_field"      # 技术领域
    BACKGROUND = "background"                # 背景技术
    SUMMARY = "summary"                      # 发明内容 / 实用新型内容
    DRAWING_DESC = "drawing_desc"            # 附图说明
    EMBODIMENTS = "embodiments"              # 具体实施方式


#: 说明书章节的规范排列顺序。渲染与校验都以此为准。
SECTION_ORDER: tuple[SectionKey, ...] = (
    SectionKey.TECHNICAL_FIELD,
    SectionKey.BACKGROUND,
    SectionKey.SUMMARY,
    SectionKey.DRAWING_DESC,
    SectionKey.EMBODIMENTS,
)

#: 章节标题。发明与实用新型只有「发明内容 / 实用新型内容」一处差异。
SECTION_TITLES: dict[str, dict[SectionKey, str]] = {
    "invention": {
        SectionKey.TECHNICAL_FIELD: "技术领域",
        SectionKey.BACKGROUND: "背景技术",
        SectionKey.SUMMARY: "发明内容",
        SectionKey.DRAWING_DESC: "附图说明",
        SectionKey.EMBODIMENTS: "具体实施方式",
    },
    "utility": {
        SectionKey.TECHNICAL_FIELD: "技术领域",
        SectionKey.BACKGROUND: "背景技术",
        SectionKey.SUMMARY: "实用新型内容",
        SectionKey.DRAWING_DESC: "附图说明",
        SectionKey.EMBODIMENTS: "具体实施方式",
    },
}

#: 章节标题在正文中的书写形式，如 ``【技术领域】``。
SECTION_TITLE_PATTERN = "【{title}】"


# --------------------------------------------------------------------------
# 各文书部分的文件标题
# --------------------------------------------------------------------------

PART_TITLES: dict[str, str] = {
    "claims": "权利要求书",
    "description": "说明书",
    "abstract": "说明书摘要",
    "drawings": "说明书附图",
    "design_brief": "外观设计简要说明",
}

#: 单文件输出时各部分的排列顺序。
#:
#: 采用与专利说明书单行本一致的阅读顺序。真正提交到国知局电子申请系统
#: 时，各部分应当拆成独立文件（``--split``），届时本顺序只影响文件命名。
PART_ORDER: tuple[str, ...] = ("claims", "description", "abstract", "drawings")


# --------------------------------------------------------------------------
# 长度与数量限制
# --------------------------------------------------------------------------

#: 摘要（含标点）不得超过 300 字。
ABSTRACT_MAX_CHARS = 300

#: 发明名称一般不超过 25 字，特殊情况可至 40 字，超过即提示。
TITLE_RECOMMENDED_MAX_CHARS = 25
TITLE_ABSOLUTE_MAX_CHARS = 40

#: 申请文件中所有文书（权利要求书/说明书/摘要）各自独立编页。
PAGE_NUMBER_REQUIRED = False


# --------------------------------------------------------------------------
# 名称禁用词
# --------------------------------------------------------------------------

#: 名称中不得出现的用语。
#:
#: 依据：发明名称应当清楚、简要地反映要求保护的技术方案的主题和类型，
#: 不得含有非技术用语，也不得使用「专利」「新型」这类会引起误解的词。
#: 注意「技术」「方法」「装置」本身都是合法用词，不要误判。
TITLE_FORBIDDEN_WORDS: tuple[str, ...] = (
    "专利",
    "新型",
    "改进",
    "及其他",
    "等类似",
)

#: 名称中应当尽量避免、但不算硬性违规的用语（含糊的范围表述）。
TITLE_SOFT_WORDS: tuple[str, ...] = (
    "等",
    "系列",
    "各种",
    "一类",
)

#: 权利要求中不得使用的不确定用语。
#:
#: 依据：《专利审查指南》第二部分第二章 3.2.2——权利要求中不得使用
#: 「例如」「最好是」「尤其是」「必要时」等类似用语，也不得使用含义
#: 不确定的表述，否则保护范围不清楚。
CLAIM_UNCERTAIN_WORDS: tuple[str, ...] = (
    "最好是",
    "最好",
    "例如",
    "尤其是",
    "必要时",
    "大约",
    "左右",
    "等等",
    "较佳地",
    "优选为",
)

#: 摘要中不得出现的商业性宣传用语。
ABSTRACT_HYPE_WORDS: tuple[str, ...] = (
    "最佳",
    "最好",
    "首创",
    "独创",
    "领先",
    "世界第一",
    "国内首创",
    "填补空白",
    "革命性",
)

#: 稿件中残留占位符的特征串。这些内容一旦进入正式申请文件就是硬伤，
#: 必须在交付前拦住。
PLACEHOLDER_PATTERNS: tuple[str, ...] = (
    "XXX",
    "xxx",
    "XX公司",
    "待补充",
    "待填写",
    "待完善",
    "TODO",
    "TBD",
    "【】",
    "（略）",
    "此处省略",
)

#: 名称中不得使用的标点（编号用的括号、引号、省略号等）。
TITLE_FORBIDDEN_PUNCTUATION: tuple[str, ...] = (
    "《", "》", "「", "」", "……", "。", "，", "、", "；", "：", "！", "？",
)


# --------------------------------------------------------------------------
# 渲染选项
# --------------------------------------------------------------------------

class SubsectionStyle(str, Enum):
    """说明书中三级小标题的处理方式。

    审查指南要求说明书正文由「技术领域、背景技术、发明内容、附图说明、
    具体实施方式」五部分组成，并未规定其下还能再分小标题。实务中代理人
    的正式稿普遍写成连续段落。但 AI 起草初稿时用小标题组织内容更清晰，
    因此提供三种处理方式，默认取最贴近正式稿的 ``INLINE``。
    """

    #: 把 ``### 要解决的技术问题`` 并入紧随段落，成为加粗的引导词。
    INLINE = "inline"
    #: 原样保留为独立的加粗段落，便于内部审阅。
    KEEP = "keep"
    #: 直接丢弃小标题，只保留正文，得到最「干净」的正式稿。
    FLATTEN = "flatten"


@dataclass
class RenderOptions:
    """渲染一份申请文件时可控的全部开关。"""

    #: 正文汉字字体。
    font: Font = BODY_FONT
    #: 正文字号（pt）。
    body_size: float = BODY_FONT_SIZE_PT
    #: 行距倍数。
    line_spacing: float = LINE_SPACING
    #: 首行缩进字符数。
    first_line_indent: int = FIRST_LINE_INDENT_CHARS
    #: 是否给【技术领域】这类章节标题加粗。
    bold_sections: bool = False
    #: 三级小标题的处理方式。
    subsection_style: SubsectionStyle = SubsectionStyle.INLINE
    #: 每个部分（权利要求书/说明书/摘要）是否另起一页。默认开启，
    #: 因为国知局的电子申请按部分独立编页。
    page_break_between_parts: bool = True
    #: 是否输出部分的文件标题（如居中的「权利要求书」）。
    include_part_titles: bool = True
    #: 是否在页脚居中放置页码。
    page_numbers: bool = PAGE_NUMBER_REQUIRED

    def resolved_fonts(self) -> tuple[str, str]:
        """返回 ``(西文字体, 中文字体)``。"""
        return self.font.western, self.font.value
