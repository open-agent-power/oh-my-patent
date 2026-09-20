"""合规自检：在交付前把不符合规范的地方挑出来。

设计取舍
--------
这个模块**不试图做实质审查**。新颖性、创造性、说明书是否充分公开，
这些必须由人判断，静态检查做不了也不该假装能做。

它只做一件事：把「格式与形式上的硬性要求」查一遍。这类问题量大、
机械、且一旦漏过就会导致补正通知书，正是最值得交给机器的那部分。
"""

from __future__ import annotations

import re

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


# 结果类型与共享工具集中在 report 模块，各组检查共用同一套结构。
from .lint_ai import AI_CHECKS
from .report import Issue, LintReport, Severity, count_chars  # noqa: F401

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
    #
    # 位置说明：本项是**整篇级**检查（只看权利要求书的第 1 项），所以放在
    # 上面那个**逐项**循环之外。这也是源码里 `CLAIM-010` 出现在 `CLAIM-011`、
    # `CLAIM-012` 之后的原因——不是码号乱序，而是逐项检查与整篇检查分属两段。
    # 判定逻辑彼此独立，互不影响。
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
    for _, text in draft.iter_text():
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
    # 码号与其余各组保持同一种写法：`前缀-三位数字`。
    # 早先这里用的是 `DES-USAGE` 这样的词码，与同组的 `DES-IMAGES`、
    # 以及全项目的 `TITLE-001` / `CLAIM-001` 风格不一致，已统一为数字码。
    required = (
        ("DES-001", brief.usage, "用途", "简要说明应当写明产品的用途。"),
        ("DES-002", brief.points, "设计要点", "简要说明应当写明设计要点。"),
        ("DES-003", brief.best_view, "最能表明设计要点的图片", "应当指定最能表明设计要点的一幅视图。"),
    )
    for code, value, label, hint in required:
        if not value.strip():
            issues.append(
                Issue(Severity.ERROR, code, f"简要说明缺少「{label}」项。", "简要说明", hint)
            )

    if not draft.drawings:
        issues.append(
            Issue(
                Severity.ERROR,
                "DES-004",
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
                    "DES-005",
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
    for location, text in draft.iter_text():
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
                "在稿件 frontmatter 写 `inventors: [姓名]`。"
                "注意《专利审查指南》（2026-01-01 施行）要求发明人应当是自然人，"
                "并填写全部发明人的真实身份信息；不得填写单位、集体或者人工智能名称。",
            )
        )
    return issues


# --------------------------------------------------------------------------
# 附图标记一致性
# --------------------------------------------------------------------------

#: 附图标记的识别式：**完整的汉字串**后紧跟 1~3 位数字。
#:
#: 用贪婪的 ``+`` 而不是 :{1,8}?`` 是有原因的：非贪婪模式会从词中间起匹配，
#: 「权利要求1至5」会被切出「至」+「5」这种假标记，进而误报。
#: 取完整汉字串后再看它的结尾，才能正确判断这是不是部件名称。
_NUMERAL_RUN_RE = re.compile(r"([\u4e00-\u9fa5]+)(\d{1,3})(?![0-9])")

#: 数字后面紧跟这些字，说明它是量值而不是附图标记（「3 个」「2 毫米」）。
_MEASURE_UNITS: tuple[str, ...] = (
    "毫米", "厘米", "分米", "千米", "公里", "米", "μm", "um", "nm",
    "千克", "公斤", "克", "毫克", "吨",
    "毫秒", "微秒", "纳秒", "秒", "分钟", "小时", "天", "年", "月", "日",
    "个", "条", "层", "块", "片", "根", "段", "倍", "次", "步", "种",
    "位", "台", "套", "组", "项", "款", "页", "行", "列", "字", "人",
    "%", "％", "℃", "度", "分", "时",
    "伏", "安", "瓦", "赫兹", "欧", "字节", "比特", "像素",
)

#: 汉字串以这些词结尾时，后面跟的数字是条目编号而不是附图标记。
#:
#: 这张表要够全：只要漏一个，「实施例2」这类写法就会让检查误报。
#: 收词原则是「宁可多排除」——漏掉一个真标记只是少一条提醒，
#: 误报一次却会让使用者不再信任整条检查。
_NUMERAL_NOUN_SUFFIXES: tuple[str, ...] = (
    "权利要求", "实施例", "实施方式", "对比例", "比较例", "例",
    "步骤", "图", "方面", "方案", "方式", "情况", "问题", "效果",
    "特征", "文献", "对比", "段落", "序号", "编号", "号码",
    "试样", "样品", "样本", "参数", "指标", "条件",
    "第", "式", "表", "类", "级", "阶段", "周期", "时刻", "种", "条", "项",
)

#: 以这些字结尾的汉字串也不构成部件名称——它们多是把两个编号连起来的
#: 连接词，例如「权利要求1至5」中的「至」。
_NUMERAL_CONNECTORS: tuple[str, ...] = (
    "至", "和", "或", "及", "与", "以及", "或者", "及其",
)


def _looks_like_reference_numeral(run: str, tail: str) -> bool:
    """判断「汉字串 + 数字」是不是一个附图标记。

    只看数字两侧的局部特征，**不去猜那个部件叫什么**。原因是中文没有
    词边界，脚本无法可靠切出「壳体」「杯盖」这样的名词——但判断
    「这个数字是不是附图标记」并不需要知道名词，只需要排除掉
    条目编号与量值两类干扰。
    """
    if run.endswith(_NUMERAL_CONNECTORS):
        return False
    if run.endswith(_NUMERAL_NOUN_SUFFIXES):
        return False
    if any(tail.lstrip().startswith(unit) for unit in _MEASURE_UNITS):
        return False
    return True


def _extract_reference_numerals(text: str) -> set[int]:
    """抽出文本中用到的附图标记编号。

    刻意**只返回编号集合**，不试图建立「编号 → 部件名称」的对应关系。
    那个映射需要中文分词，脚本做不可靠；而一条经常出错的检查，
    比没有检查更糟——使用者会连正确的提醒一起不信任。

    识别规则偏保守：宁可漏掉一些标记，也不要把「3 个」「2 毫米」
    这类量值误判进来。
    """
    numbers: set[int] = set()
    for match in _NUMERAL_RUN_RE.finditer(text):
        run = match.group(1)
        number = int(match.group(2))
        tail = text[match.end(): match.end() + 3]
        if _looks_like_reference_numeral(run, tail):
            numbers.add(number)
    return numbers


def check_reference_numerals(draft: PatentDraft) -> list[Issue]:
    """附图标记的一致性检查。

    依据《专利法实施细则》第 21 条：几幅附图应当按照「图1，图2，……」
    顺序编号排列；**说明书文字部分中未提及的附图标记不得在附图中出现，
    附图中未出现的附图标记不得在说明书文字部分中提及**；表示同一组成部分
    的附图标记应当一致。

    本工具读不了图片内容，所以"附图中出现了什么标记"无从得知，
    只能检查文字侧的一致性——而这一侧恰恰是最容易漏的：
    说明书满篇「壳体1」「杯盖2」，却一张图都没登记。
    """
    issues: list[Issue] = []
    if draft.patent_type is PatentType.DESIGN:
        # 外观设计的图没有附图标记，检查不适用
        return issues

    claim_numerals = _extract_reference_numerals(draft.claims_text())
    description_numerals = _extract_reference_numerals(draft.description_text())

    if not claim_numerals and not description_numerals:
        return issues

    # ---- REF-001：说明书用了附图标记，但稿件没有附图 ----
    #
    # 这是最容易踩的硬伤。细则第 21 条明确：附图中未出现的附图标记
    # 不得在说明书文字部分中提及。
    if description_numerals and not draft.drawings:
        sample = "、".join(str(n) for n in sorted(description_numerals)[:5])
        issues.append(
            Issue(
                Severity.ERROR,
                "REF-001",
                f"说明书使用了附图标记（{sample}），但稿件中没有任何附图。",
                "说明书",
                "《专利法实施细则》第 21 条：附图中未出现的附图标记不得在"
                "说明书文字部分中提及。请补交附图，或删除说明书中的附图标记。",
            )
        )

    # ---- REF-002 / REF-003：权利要求引用了说明书里没有的标记 ----
    if claim_numerals:
        if not description_numerals:
            sample = "、".join(str(n) for n in sorted(claim_numerals)[:5])
            issues.append(
                Issue(
                    Severity.ERROR,
                    "REF-002",
                    f"权利要求中引用了附图标记（{sample}），"
                    f"但说明书正文中找不到任何附图标记。",
                    "权利要求书",
                    "权利要求中的附图标记必须与说明书、附图保持一致。"
                    "请先在说明书对应部件名称后加上相同的标记。",
                )
            )
        else:
            missing = sorted(claim_numerals - description_numerals)
            if missing:
                sample = "、".join(str(n) for n in missing[:5])
                issues.append(
                    Issue(
                        Severity.ERROR,
                        "REF-003",
                        f"权利要求引用了说明书未出现的附图标记：{sample}。",
                        "权利要求书",
                        "《专利法实施细则》第 21 条：表示同一组成部分的附图标记"
                        "应当一致，且附图中未出现的标记不得在文字部分中提及。"
                        "请核对权利要求与说明书的标记编号是否对齐。",
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
    check_reference_numerals,
    check_placeholders,
    check_metadata,
) + AI_CHECKS


def lint(draft: PatentDraft) -> LintReport:
    """对一份稿件跑完全部检查。"""
    report = LintReport()
    for check in ALL_CHECKS:
        report.issues.extend(check(draft))
    return report
