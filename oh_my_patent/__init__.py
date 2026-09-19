"""oh-my-patent —— 自动化专利 SKILL，同时适配 WPS、Office。

一句话说清这个包做什么：
把一份结构化的专利稿件，渲染成符合国家知识产权局版面要求的申请文件，
并且保证生成的文件在 WPS 与 MS Office 下打开时版面一致。

流水线：

    稿件(.md/.yaml/.json)
        │
        ├─ parser  解析成 PatentDraft 模型
        ├─ lint    跑一遍形式合规自检
        └─ render  按规范版面写出 .docx

各层职责边界清楚，互不渗透：
``parser`` 只负责「读懂」，``lint`` 只负责「挑错」，
``render`` 只负责「排版」，版面常量集中在 ``spec``。
"""

__version__ = "0.1.0"

from .lint import Issue, LintReport, Severity, lint
from .parser import ParseError, load, loads, parse_markdown, parse_structured
from .render import DocxRenderer, render_docx
from .schema import (
    Claim,
    DesignBrief,
    Drawing,
    PatentDraft,
    PatentType,
    build_claim,
    parse_claims_block,
)
from .spec import Font, RenderOptions, SubsectionStyle

__all__ = [
    "__version__",
    # 模型
    "PatentDraft",
    "PatentType",
    "Claim",
    "Drawing",
    "DesignBrief",
    "build_claim",
    "parse_claims_block",
    # 解析
    "load",
    "loads",
    "parse_markdown",
    "parse_structured",
    "ParseError",
    # 自检
    "lint",
    "LintReport",
    "Issue",
    "Severity",
    # 渲染
    "render_docx",
    "DocxRenderer",
    "RenderOptions",
    "SubsectionStyle",
    "Font",
]
