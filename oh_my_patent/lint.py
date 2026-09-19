"""合规自检：在交付前把不符合规范的地方挑出来。

设计取舍
--------
这个模块**不试图做实质审查**。新颖性、创造性、说明书是否充分公开，
这些必须由人判断，静态检查做不了也不该假装能做。

它只做一件事：把「格式与形式上的硬性要求」查一遍。这类问题量大、
机械、且一旦漏过就会导致补正通知书，正是最值得交给机器的那部分。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum

from .schema import PatentDraft, PatentType
from .spec import (
    ABSTRACT_HYPE_WORDS,
    ABSTRACT_MAX_CHARS,
    CLAIM_UNCERTAIN_WORDS,
    PLACEHOLDER_PATTERNS,
    SECTION_ORDER,
    SECTION_TITLES,
    TITLE_ABSOLUTE_MAX_CHARS,
    TITLE_FORBIDDEN_PUNCTUATION,
    TITLE_FORBIDDEN_WORDS,
    TITLE_RECOMMENDED_MAX_CHARS,
    TITLE_SOFT_WORDS,
    SectionKey,
)


class Severity(str, Enum):
    """问题严重程度。

    ``ERROR``   几乎必然导致补正或不予受理，必须改。
    ``WARNING`` 形式上可被接受，但实务中会被审查员指出，建议改。
    ``INFO``    提示性信息，供人工复核。
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 0, "warning": 1, "info": 2}[self.value]

    @property
    def label(self) -> str:
        return {"error": "错误", "warning": "警告", "info": "提示"}[self.value]


@dataclass
class Issue:
    """一条检查结果。"""

    severity: Severity
    code: str
    message: str
    location: str = ""
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "location": self.location,
            "hint": self.hint,
        }

    def render(self) -> str:
        icon = {"error": "✗", "warning": "!", "info": "·"}[self.severity.value]
        where = f" [{self.location}]" if self.location else ""
        line = f"  {icon} {self.severity.label} · {self.code}{where}\n      {self.message}"
        if self.hint:
            line += f"\n      → {self.hint}"
        return line


@dataclass
class LintReport:
    """一次自检的完整结果。"""

    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """没有 ``ERROR`` 级别的硬伤即视为通过。"""
        return not self.errors

    def sorted_issues(self) -> list[Issue]:
        return sorted(self.issues, key=lambda i: i.severity.rank)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "info_count": len(self.issues) - len(self.errors) - len(self.warnings),
            "issues": [i.to_dict() for i in self.sorted_issues()],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def render(self) -> str:
        if not self.issues:
            return "✓ 自检通过：未发现格式或形式上的问题。"

        lines = [
            f"自检结果：{len(self.errors)} 个错误 / "
            f"{len(self.warnings)} 个警告 / "
            f"{len(self.issues) - len(self.errors) - len(self.warnings)} 条提示",
            "",
        ]
        lines.extend(issue.render() for issue in self.sorted_issues())
        return "\n".join(lines)


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

def count_chars(text: str) -> int:
    """统计摘要字数：忽略空白，汉字与标点各计一字。"""
    return len(re.sub(r"\s", "", text))


def _collect_text(draft: PatentDraft) -> list[tuple[str, str]]:
    """返回稿件中所有 ``(位置, 文本)``，用于全稿扫描。"""
    items: list[tuple[str, str]] = [("名称", draft.title)]
    if draft.abstract:
        items.append(("摘要", draft.abstract))
    for claim in draft.claims:
        items.append((f"权利要求{claim.number}", claim.text))
    for field_name, label in (
        ("technical_field", "技术领域"),
        ("background", "背景技术"),
        ("problems", "发明内容·技术问题"),
        ("solution", "发明内容·技术方案"),
        ("effects", "发明内容·有益效果"),
        ("embodiments", "具体实施方式"),
    ):
        value = getattr(draft, field_name, "")
        if value:
            items.append((label, value))
    brief = draft.design_brief
    for value, label in (
        (brief.usage, "简要说明·用途"),
        (brief.points, "简要说明·设计要点"),
        (brief.best_view, "简要说明·代表图"),
        (brief.omitted_views, "简要说明·省略视图"),
    ):
        if value:
            items.append((label, value))
    return items


# --------------------------------------------------------------------------
# 各项检查
# --------------------------------------------------------------------------

def check_title(draft: PatentDraft) -> list[Issue]:
    """发明名称的形式要求。"""
    issues: list[Issue] = []
    title = draft.title.strip()

    if not title or title == "（未命名）":
        issues.append(
            Issue(
                Severity.ERROR,
                "TITLE-001",
                "缺少发明名称。",
                "名称",
                "在稿件 frontmatter 写 `title:`，或让第一项权利要求以「一种……」开头。",
            )
        )
        return issues

    length = count_chars(title)
    if length > TITLE_ABSOLUTE_MAX_CHARS:
        issues.append(
            Issue(
                Severity.ERROR,
                "TITLE-002",
                f"名称 {length} 字，超过 40 字的上限。",
                "名称",
                "发明名称一般不超过 25 字，特殊情况也不得超过 40 字。",
            )
        )
    elif length > TITLE_RECOMMENDED_MAX_CHARS:
        issues.append(
            Issue(
                Severity.WARNING,
                "TITLE-003",
                f"名称 {length} 字，超过一般要求的 25 字。",
                "名称",
                "若不属特殊情况，建议精简到 25 字以内。",
            )
        )

    for word in TITLE_FORBIDDEN_WORDS:
        if word in title:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "TITLE-004",
                    f"名称中含禁用词「{word}」。",
                    "名称",
                    "名称不得含有非技术用语或易引起误解的词。",
                )
            )

    for word in TITLE_SOFT_WORDS:
        if word in title:
            issues.append(
                Issue(
                    Severity.INFO,
                    "TITLE-005",
                    f"名称中含含糊表述「{word}」，可能被认为指代范围不清楚。",
                    "名称",
                )
            )
            break

    for punct in TITLE_FORBIDDEN_PUNCTUATION:
        if punct in title:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "TITLE-006",
                    f"名称中含标点「{punct}」。",
                    "名称",
                    "发明名称中不得使用标点符号（必要的括号除外）。",
                )
            )
            break

    if draft.patent_type is PatentType.DESIGN and "外观设计" in title:
        issues.append(
            Issue(
                Severity.WARNING,
                "TITLE-007",
                "名称中不应包含「外观设计」字样。",
                "名称",
                "名称应直接写明产品名称，类型由申请表单另行确定。",
            )
        )

    return issues


def check_claims(draft: PatentDraft) -> list[Issue]:
    """权利要求书的形式要求。"""
    issues: list[Issue] = []

    if not draft.patent_type.has_claims:
        return issues

    if not draft.claims:
        issues.append(
            Issue(
                Severity.ERROR,
                "CLAIM-001",
                "缺少权利要求书。",
                "权利要求书",
                "发明与实用新型专利申请必须提交权利要求书。",
            )
        )
        return issues

    # 编号必须连续且从 1 开始
    expected = list(range(1, len(draft.claims) + 1))
    actual = [claim.number for claim in draft.claims]
    if actual != expected:
        issues.append(
            Issue(
                Severity.ERROR,
                "CLAIM-002",
                f"权利要求编号不连续：得到 {actual}，应为 {expected}。",
                "权利要求书",
                "每项权利要求应当用阿拉伯数字顺序编号。",
            )
        )

    independents = draft.independent_claims
    if len(independents) == 0:
        issues.append(
            Issue(
                Severity.ERROR,
                "CLAIM-003",
                "未识别到独立权利要求。",
                "权利要求书",
                "权利要求书中应当至少有一项独立权利要求，且写在从属权利要求之前。",
            )
        )
    elif len(independents) > 1:
        # 多项独立权利要求本身是合法的。《专利法实施细则》要求「一项发明
        # 或者实用新型应当只有一个独立权利要求」，但国知局的官方解释与
        # 最高人民法院的答复都确认：在符合单一性要求的前提下，权利要求书
        # 中可以有两项以上独立权利要求，其中写在最前面的为第一独立权利要求，
        # 其余为并列独立权利要求。《审查指南》第二部分第六章 2.2.1 进一步
        # 列出了六种允许的撰写方式，例如「方法和为实施该方法而专门设计的
        # 设备的独立权利要求」。因此这里只能提示复核单一性，不能判为错误。
        issues.append(
            Issue(
                Severity.WARNING,
                "CLAIM-004",
                f"存在 {len(independents)} 项独立权利要求（编号 "
                f"{'、'.join(str(c.number) for c in independents)}）。",
                "权利要求书",
                "多项独立权利要求在符合单一性时是允许的，但需确认它们属于一个总的"
                "发明构思、包含相同或相应的特定技术特征。常见允许组合：产品+专用于"
                "制造该产品的方法、产品+该产品的用途、方法+为实施该方法而专门设计的"
                "设备。若不属于同一构思，应分案申请。",
            )
        )

    for claim in draft.claims:
        location = f"权利要求{claim.number}"

        if claim.independent and "其特征在于" not in claim.text:
            issues.append(
                Issue(
                    Severity.WARNING,
                    "CLAIM-005",
                    "独立权利要求中没有「其特征在于」。",
                    location,
                    "独立权利要求应当包含前序部分与特征部分，"
                    "通常以「其特征在于」划界。",
                )
            )

        if not claim.independent and not claim.references:
            issues.append(
                Issue(
                    Severity.WARNING,
                    "CLAIM-006",
                    "从属权利要求未写明所引用的权利要求编号。",
                    location,
                    "从属权利要求应在开头写明「根据权利要求X所述的……」。",
                )
            )

        for ref in claim.references:
            if ref >= claim.number:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        "CLAIM-007",
                        f"引用了编号 {ref} 的权利要求，但其在本项（{claim.number}）之后或就是本项。",
                        location,
                        "从属权利要求只能引用在它之前的权利要求。",
                    )
                )

        for word in CLAIM_UNCERTAIN_WORDS:
            if word in claim.text:
                issues.append(
                    Issue(
                        Severity.WARNING,
                        "CLAIM-008",
                        f"含含义不确定的用语「{word}」。",
                        location,
                        "权利要求中不得使用「例如」「最好是」这类用语，否则保护范围不清楚。",
                    )
                )
                break

        claim_length = count_chars(claim.text)
        if claim_length > 800:
            issues.append(
                Issue(
                    Severity.INFO,
                    "CLAIM-009",
                    f"该项权利要求长达 {claim_length} 字。",
                    location,
                    "过长的权利要求可读性差，也更容易被指出缺乏单一性，建议拆分。",
                )
            )

        # 《专利法实施细则》：除绝对必要外，权利要求中不得使用
        # 「如说明书……部分所述」或者「如图……所示」的用语。
        awkward = re.search(r"如(?:说明书|图)[^，。；]{0,12}(?:所述|所示)", claim.text)
        if awkward:
            issues.append(
                Issue(
                    Severity.WARNING,
                    "CLAIM-011",
                    f"使用了「{awkward.group(0)}」。",
                    location,
                    "权利要求应当自身完整地限定保护范围，除绝对必要外不得引用"
                    "说明书或附图。",
                )
            )

        # 《专利法实施细则》：权利要求书中可以有化学式或数学式，但不得有插图。
        if re.search(r"!\[[^\]]*\]\(", claim.text):
            issues.append(
                Issue(
                    Severity.ERROR,
                    "CLAIM-012",
                    "权利要求中含插图。",
                    location,
                    "权利要求书中不得有插图。需要说明时改用文字或化学式、数学式。",
                )
            )

    # 第一项权利要求必须是独立权利要求：从属权利要求需要有可引用的在先
    # 权利要求，排在首位时无权利要求可引。
    if independents and draft.claims and not draft.claims[0].independent:
        issues.append(
            Issue(
                Severity.ERROR,
                "CLAIM-010",
                "第一项权利要求不是独立权利要求。",
                "权利要求1",
                "第一独立权利要求应当写在同一发明或实用新型的从属权利要求之前。",
            )
        )

    issues.extend(_check_utility_claims(draft))
    return issues


def _check_utility_claims(draft: PatentDraft) -> list[Issue]:
    """实用新型特有的限制。

    《专利审查指南》第一部分第二章与国知局的官方答复都明确：实用新型
    只保护产品的形状、构造或者其结合，权利要求书**只能包含产品权利要求**，
    不能包含方法权利要求。这是实用新型最常见的实质缺陷之一。
    """
    issues: list[Issue] = []
    if draft.patent_type is not PatentType.UTILITY:
        return issues

    for claim in draft.independent_claims:
        subject = _claim_subject(claim.text)
        if not subject:
            continue
        if any(word in subject for word in ("方法", "工艺", "用途", "流程", "制备")):
            issues.append(
                Issue(
                    Severity.ERROR,
                    "CLAIM-013",
                    f"实用新型的独立权利要求主题为方法类（「{subject}」）。",
                    f"权利要求{claim.number}",
                    "实用新型只保护产品的形状、构造或者其结合，权利要求书只能包含"
                    "产品权利要求。方法类主题应改为实用新型无法保护，需申请发明专利。",
                )
            )

    return issues


def _claim_subject(text: str) -> str:
    """从独立权利要求里抠出主题名称，即「一种」与第一个逗号之间的部分。"""
    match = re.match(r"\s*一种(.+?)[，,]", text)
    return match.group(1).strip() if match else ""


def check_description(draft: PatentDraft) -> list[Issue]:
    """说明书的形式要求。"""
    issues: list[Issue] = []
    if not draft.patent_type.has_description:
        return issues

    titles = SECTION_TITLES.get(draft.patent_type.value, SECTION_TITLES["invention"])
    present: list[SectionKey] = []
    if draft.technical_field.strip():
        present.append(SectionKey.TECHNICAL_FIELD)
    if draft.background.strip():
        present.append(SectionKey.BACKGROUND)
    if draft.summary_parts:
        present.append(SectionKey.SUMMARY)
    if draft.drawings:
        present.append(SectionKey.DRAWING_DESC)
    if draft.embodiments.strip():
        present.append(SectionKey.EMBODIMENTS)

    if not present:
        issues.append(
            Issue(
                Severity.ERROR,
                "DESC-001",
                "说明书没有任何内容。",
                "说明书",
                "至少应写明技术领域、背景技术、发明内容和具体实施方式。",
            )
        )
        return issues

    # 必需章节
    for key in (
        SectionKey.TECHNICAL_FIELD,
        SectionKey.BACKGROUND,
        SectionKey.SUMMARY,
        SectionKey.EMBODIMENTS,
    ):
        if key not in present:
            issues.append(
                Issue(
                    Severity.WARNING,
                    "DESC-002",
                    f"缺少【{titles[key]}】章节。",
                    "说明书",
                    "说明书应当包括技术领域、背景技术、发明内容、附图说明和具体实施方式五个部分。",
                )
            )

    # 章节顺序
    order = [k for k in SECTION_ORDER if k in present]
    if present != order:
        issues.append(
            Issue(
                Severity.ERROR,
                "DESC-003",
                "说明书各部分的排列顺序不符合法定顺序。",
                "说明书",
                "应当按「技术领域 → 背景技术 → 发明内容 → 附图说明 → 具体实施方式」排列。",
            )
        )

    # 附图说明与附图的对应关系
    if draft.drawings and SectionKey.DRAWING_DESC not in present:
        issues.append(
            Issue(
                Severity.ERROR,
                "DESC-004",
                f"稿件含 {len(draft.drawings)} 幅附图，但没有附图说明。",
                "附图说明",
                "有附图的说明书必须写明各幅附图的内容。",
            )
        )

    # 实用新型必须有附图。《专利法实施细则》规定，实用新型专利申请的
    # 说明书应当有表示要求保护的产品的形状、构造或者其结合的附图——
    # 这是实用新型与发明在申请文件上最硬的一条差别。
    if draft.patent_type is PatentType.UTILITY and not draft.drawings:
        issues.append(
            Issue(
                Severity.ERROR,
                "DESC-007",
                "实用新型专利申请没有附图。",
                "附图",
                "实用新型专利申请的说明书必须有表示要求保护的产品的形状、构造或者"
                "其结合的附图，不能省略。",
            )
        )

    # 正文引用的图号必须真实存在
    known = {drawing.number for drawing in draft.drawings}
    referenced: set[int] = set()
    for _, text in _collect_text(draft):
        for match in re.finditer(r"图\s*(\d+)", text):
            referenced.add(int(match.group(1)))
    unknown = sorted(referenced - known)
    if unknown:
        issues.append(
            Issue(
                Severity.ERROR,
                "DESC-005",
                f"正文引用了不存在的图号：{'、'.join(f'图{n}' for n in unknown)}。",
                "说明书",
                "要么补充这些附图，要么修正引用。附图中未出现的图号会引发补正。",
            )
        )

    if draft.drawings and not any(drawing.caption.strip() for drawing in draft.drawings):
        issues.append(
            Issue(
                Severity.INFO,
                "DESC-006",
                "各幅附图都没有单独的说明文字，将使用默认措辞。",
                "附图说明",
                "建议逐幅写明「图N为……示意图」。",
            )
        )

    return issues


def check_abstract(draft: PatentDraft) -> list[Issue]:
    """摘要的形式要求。"""
    issues: list[Issue] = []
    if not draft.patent_type.has_claims:
        return issues

    text = draft.abstract.strip()
    if not text:
        issues.append(
            Issue(
                Severity.ERROR,
                "ABS-001",
                "缺少说明书摘要。",
                "摘要",
                "发明与实用新型专利申请必须提交摘要，且不得超过 300 字。",
            )
        )
        return issues

    length = count_chars(text)
    if length > ABSTRACT_MAX_CHARS:
        issues.append(
            Issue(
                Severity.ERROR,
                "ABS-002",
                f"摘要 {length} 字，超过 300 字的上限。",
                "摘要",
                f"需要删减约 {length - ABSTRACT_MAX_CHARS} 字。",
            )
        )
    elif length > ABSTRACT_MAX_CHARS - 20:
        issues.append(
            Issue(
                Severity.WARNING,
                "ABS-003",
                f"摘要 {length} 字，已逼近 300 字上限。",
                "摘要",
            )
        )

    for word in ABSTRACT_HYPE_WORDS:
        if word in text:
            issues.append(
                Issue(
                    Severity.WARNING,
                    "ABS-004",
                    f"摘要中含商业性宣传用语「{word}」。",
                    "摘要",
                    "摘要不得使用商业性宣传用语，这类表述会被要求删除。",
                )
            )

    if not re.search(r"[。；;]", text):
        issues.append(
            Issue(
                Severity.INFO,
                "ABS-005",
                "摘要通篇没有句号，可能是一整句未断开的文字。",
                "摘要",
                "摘要应当写明技术问题、技术方案要点和主要用途。",
            )
        )

    return issues


def check_design(draft: PatentDraft) -> list[Issue]:
    """外观设计简要说明的形式要求。"""
    issues: list[Issue] = []
    if draft.patent_type is not PatentType.DESIGN:
        return issues

    brief = draft.design_brief
    required = (
        ("usage", brief.usage, "用途", "简要说明应当写明产品的用途。"),
        ("points", brief.points, "设计要点", "简要说明应当写明设计要点。"),
        ("best_view", brief.best_view, "最能表明设计要点的图片", "应当指定最能表明设计要点的一幅视图。"),
    )
    for code, value, label, hint in required:
        if not value.strip():
            issues.append(
                Issue(Severity.ERROR, f"DES-{code.upper()}", f"简要说明缺少「{label}」项。", "简要说明", hint)
            )

    if not draft.drawings:
        issues.append(
            Issue(
                Severity.ERROR,
                "DES-IMAGES",
                "没有登记任何外观设计图片。",
                "外观设计",
                "外观设计的保护范围以图片或照片为准，必须提交六面视图，必要时补充立体图与剖视图。",
            )
        )
    else:
        missing = [d.number for d in draft.drawings if not d.path]
        if missing:
            issues.append(
                Issue(
                    Severity.WARNING,
                    "DES-PATH",
                    f"以下视图没有实际的图片文件路径：{'、'.join(map(str, missing))}。",
                    "外观设计",
                    "生成文档时这些位置会留空，需要在交付前补齐图片。",
                )
            )

    return issues


def check_placeholders(draft: PatentDraft) -> list[Issue]:
    """扫描全稿，拦住未替换的占位内容。

    这是 AI 起草稿件最容易出问题的地方：模型有时会留下 ``XXX``
    或「待补充」，一旦进了正式申请文件就是硬伤。
    """
    issues: list[Issue] = []
    for location, text in _collect_text(draft):
        for pattern in PLACEHOLDER_PATTERNS:
            if pattern in text:
                index = text.find(pattern)
                snippet = text[max(0, index - 12): index + len(pattern) + 12]
                issues.append(
                    Issue(
                        Severity.ERROR,
                        "TXT-001",
                        f"疑似残留占位符「{pattern}」：…{snippet}…",
                        location,
                        "交付前必须替换为真实内容。",
                    )
                )
                break
    return issues


def check_metadata(draft: PatentDraft) -> list[Issue]:
    """著录项目的完整性提示。"""
    issues: list[Issue] = []
    if not draft.applicant.strip():
        issues.append(
            Issue(
                Severity.INFO,
                "META-001",
                "未填写申请人。",
                "著录项目",
                "本工具不生成请求书，申请人信息仅用于文档属性与正文中的必要引用。",
            )
        )
    if not draft.inventors:
        issues.append(
            Issue(
                Severity.INFO,
                "META-002",
                "未填写发明人 / 设计人。",
                "著录项目",
            )
        )
    return issues


#: 按顺序执行的全部检查。
ALL_CHECKS = (
    check_title,
    check_claims,
    check_description,
    check_abstract,
    check_design,
    check_placeholders,
    check_metadata,
)


def lint(draft: PatentDraft) -> LintReport:
    """对一份稿件跑完全部检查。"""
    report = LintReport()
    for check in ALL_CHECKS:
        report.issues.extend(check(draft))
    return report
