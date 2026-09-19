"""AI／算法类发明专利的专门检查。

依据
----
《专利审查指南》第二部分第九章第 6 章（2025 年修改，国家知识产权局令
第 84 号，2025-11-10 公布，**自 2026-01-01 起施行**）。

本次修改对 AI 相关申请加了两道实质门槛，都落在说明书上：

**门槛一 · 充分公开**（第 6.3.1 节，对应专利法第 26 条第 3 款）

指南把 AI 相关申请分成两种情形，要求各有侧重：

  - 涉及**人工智能模型的构建或者训练**的，说明书一般需要清楚记载模型
    必要的**模块、层级或者连接关系**，训练必需的**具体步骤、参数**等；
  - 涉及**在具体领域或者场景中应用**人工智能模型或算法的，说明书一般需要
    清楚记载模型或算法**如何与具体场景结合**，算法或模型的**输入、输出
    数据如何设置**以表明其内在关联关系。

落脚点都是同一句：使所属技术领域的技术人员按照说明书记载的内容，
**能够实现**该发明的解决方案。指南新增的审查示例（例 20 公开充分、
例 21 公开不充分）就是在划这条线。

**门槛二 · 伦理合规**（新增第 6.1.1 节，对应专利法第 5 条第 1 款）

申请文件中记载的数据采集、标签管理、规则设置、推荐决策等内容，
如果违反法律、社会公德或者妨害公共利益，不予授权。指南新增的审查示例中，
以行人性别、年龄作为碰撞保护对象决策依据的方案被明确排除。

实现的取舍
----------
本模块只做**静态检查**，能发现「明显缺失」与「明显违规表述」，
不能替代实质判断。

判据刻意偏保守。理由：AI 相关申请的说明书质量差别极大，一个看似含糊的
表述在具体语境下可能完全合规。因此宁可多提醒，也不轻易判死——
凡是不够确定的，一律降级为 ``WARNING`` 并附上具体核查指引，
让使用者自己判断，而不是替审查员下结论。

与其他检查的分工
----------------
- 本模块只管 **AI／算法专有**的判据；
- 通用的形式要求（术语、摘要字数、图号一致性等）在 :mod:`oh_my_patent.lint`。

引用规范：本模块报出的每一条，都应在 ``message`` 或 ``hint`` 里说清
依据哪一条规则——使用者有权知道这个判据是从哪来的，才有可能判断它是否
适用于自己的案子。
"""

from __future__ import annotations

import re

from .report import Issue, Severity
from .schema import PatentDraft
from .spec import (
    AI_BLACKBOX_PHRASES,
    AI_CORE_KEYWORDS,
    AI_EFFECT_ONLY_PHRASES,
    AI_IO_KEYWORDS,
    AI_STRUCTURE_KEYWORDS,
    AI_TASK_KEYWORDS,
    AI_TRAINING_DETAIL_KEYWORDS,
    DECISION_VERBS,
    ETHICS_COMPLIANCE_KEYWORDS,
    ETHICS_SENSITIVE_KEYWORDS,
    ETHICS_VIOLATION_PHRASES,
    HIGH_STAKES_TERMS,
    PERSONAL_ATTRIBUTES,
)

# 《专利审查指南》第二部分第九章第 6 章的简称，用于在报错信息里标注出处。
_GUIDELINE = "《专利审查指南》第二部分第九章 6.3.1"

#: 指向「模型的构建或训练」情形的信号词。
_BUILD_SIGNALS: tuple[str, ...] = (
    "构建", "训练", "搭建", "建立模型", "设计模型", "网络结构", "模型结构",
    "迭代训练", "优化模型",
)

#: 指向「模型在具体场景中应用」情形的信号词。
_APPLY_SIGNALS: tuple[str, ...] = (
    "部署", "调用", "输入到", "送入", "推理", "在线服务", "上线运行",
    "应用于", "用于识别", "用于预测", "用于分类",
)


def _hits(text: str, keywords: tuple[str, ...]) -> list[str]:
    """返回 ``text`` 中出现的关键词（去重，保持给定顺序）。"""
    seen: list[str] = []
    for keyword in keywords:
        if keyword in text and keyword not in seen:
            seen.append(keyword)
    return seen


def _format_hits(hits: list[str], limit: int = 4) -> str:
    shown = "、".join(hits[:limit])
    return f"{shown} 等" if len(hits) > limit else shown


# --------------------------------------------------------------------------
# 门槛一：充分公开
# --------------------------------------------------------------------------

def check_ai_disclosure(draft: PatentDraft) -> list[Issue]:
    """AI 相关申请的说明书充分公开检查。

    只看**说明书正文**，不看权利要求。这个区分是要紧的：指南要求的是
    「说明书应当记载……」，若把权利要求也算进来，就会出现「权利要求里
    写了某个算法、说明书里完全没写」反而被判合规的情况——而这正是
    「权利要求得不到说明书支持」最典型的成因。
    """
    issues: list[Issue] = []

    claims_text = draft.claims_text()
    description = draft.description_text()

    ai_in_claims = _hits(claims_text, AI_CORE_KEYWORDS)
    ai_in_description = _hits(description, AI_CORE_KEYWORDS)

    # 本组检查只在稿件真的涉及模型／算法时执行。判断依据必须是核心词，
    # 不能用任务词（图像识别、机器翻译……）——那类词判别力太弱，
    # 会让机械结构、纯规则算法的专利被 AI 规则无谓打扰。
    if not ai_in_claims and not ai_in_description:
        return issues

    # ---- AI-001：权利要求写了 AI，说明书却没说 ----
    if ai_in_claims and not ai_in_description:
        # 任务词在这里才派上用场：若说明书只写了领域词，把它讲出来，
        # 使用者一眼就能看出"缺的是算法不是领域"。
        domain_only = _hits(description, AI_TASK_KEYWORDS)
        detail = (
            f"（说明书只有领域层面的表述「{_format_hits(domain_only)}」，"
            f"这不足以公开技术方案）"
            if domain_only
            else "（说明书通篇未见任何算法或模型）"
        )
        issues.append(
            Issue(
                Severity.ERROR,
                "AI-001",
                f"权利要求中出现了「{_format_hits(ai_in_claims)}」，"
                f"但说明书未描述该算法或模型{detail}。",
                "说明书",
                "依据专利法第 26 条第 4 款，权利要求应当以说明书为依据。"
                "请先在说明书中补写该算法／模型的实现方式，再保留相应的权利要求特征。",
            )
        )
        # 说明书一个字都没写，后面的结构性检查无从谈起
        return issues

    is_build_case = bool(_hits(description, _BUILD_SIGNALS))
    is_apply_case = bool(_hits(description, _APPLY_SIGNALS))

    structure_hits = _hits(description, AI_STRUCTURE_KEYWORDS)
    io_hits = _hits(description, AI_IO_KEYWORDS)

    # ---- AI-002：模型架构未公开（构建／训练情形）----
    if is_build_case or not is_apply_case:
        if not structure_hits:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "AI-002",
                    f"说明书涉及 AI 模型的构建或训练（出现「"
                    f"{_format_hits(_hits(description, _BUILD_SIGNALS))}」），"
                    f"但未记载模型必要的模块、层级或者连接关系。",
                    "具体实施方式",
                    f"{_GUIDELINE}：涉及人工智能模型的构建或者训练，"
                    f"一般需要在说明书中清楚记载模型必要的模块、层级或者连接关系。"
                    f"请写明网络由哪些层／模块构成、彼此如何连接（例如"
                    f"「编码器由 4 层卷积层与 2 层池化层交替连接而成」）。",
                )
            )

    # ---- AI-003：训练细节缺失 ----
    if "训练" in description and not _hits(description, AI_TRAINING_DETAIL_KEYWORDS):
        issues.append(
            Issue(
                Severity.WARNING,
                "AI-003",
                "说明书提到「训练」，但未记载训练必需的具体步骤或参数。",
                "具体实施方式",
                f"{_GUIDELINE} 要求记载训练必需的具体步骤、参数等。"
                f"建议补上损失函数、优化器、学习率、迭代轮次、样本来源与规模等"
                f"（属本领域公知常识的部分可只作说明，不必穷举）。",
            )
        )

    # ---- AI-004：场景应用的输入输出关系未写明 ----
    #
    # 判据分两层：先看有没有「输入／输出 + 数据名词」的常见搭配；
    # 搭不满时，只要文中同时出现「输入」与「输出」就放过——这一条只是
    # WARNING，误报的代价大于漏报。
    io_hits = _hits(description, AI_IO_KEYWORDS)
    has_io_vocabulary = "输入" in description and "输出" in description
    if not io_hits and not has_io_vocabulary:
        severity = Severity.WARNING if is_apply_case else Severity.INFO
        issues.append(
            Issue(
                severity,
                "AI-004",
                "说明书中未见对算法或模型输入、输出数据的描述。",
                "具体实施方式",
                f"{_GUIDELINE}：涉及在具体领域或者场景中应用人工智能模型或算法，"
                f"一般需要记载算法或模型的输入、输出数据如何设置以表明其内在关联关系。"
                f"请写明输入是什么、输出是什么、两者为何构成这种映射。",
            )
        )

    # ---- AI-005：黑箱式表述 ----
    blackbox = _hits(description + draft.solution, AI_BLACKBOX_PHRASES)
    if blackbox:
        issues.append(
            Issue(
                Severity.WARNING,
                "AI-005",
                f"说明书中出现黑箱式表述：「{_format_hits(blackbox)}」。",
                "具体实施方式",
                f"这类措辞本身不违规，但在 AI 相关申请中是审查员认定"
                f"「公开不充分」的常见抓手（参见指南新增审查示例例 21，"
                f"其说明书正是因未记载具体指标与权重而被认定披露不足）。"
                f"请确认每一处都有对应的具体实现细节，否则予以删除。",
            )
        )

    # ---- AI-006：只给效果承诺，没给技术手段 ----
    effect_only = _hits(description + draft.solution, AI_EFFECT_ONLY_PHRASES)
    if effect_only:
        issues.append(
            Issue(
                Severity.WARNING,
                "AI-006",
                f"存在偏重效果承诺的表述：「{_format_hits(effect_only)}」。",
                "发明内容·技术方案",
                f"指南要求说明书清楚、完整地描述**解决方案**，只写"
                f"「采用某种模型提高某项指标」不足以支撑。请确认该处紧接其后"
                f"已写明具体技术手段；若能改写为"
                f"「通过 X 得到 Y，据此使 Z 提高」，会更稳。",
            )
        )

    return issues


# --------------------------------------------------------------------------
# 门槛二：伦理合规
# --------------------------------------------------------------------------

_ATTR_ALT = "|".join(PERSONAL_ATTRIBUTES)
_HIGH_STAKES_ALT = "|".join(HIGH_STAKES_TERMS)
_DECISION_ALT = "|".join(DECISION_VERBS)
_PREPOSITION_ALT = "根据|基于|按照|依据|以|按"

#: 人身属性 → 决策动词。中间允许插入「行人的」这类修饰语，因此不能用
#: 整串比对，必须走模式匹配。
_ATTR_THEN_VERB = rf"({_ATTR_ALT})[^。；！？\n]{{0,12}}?({_DECISION_ALT})"
#: 介词／决策动词 → 人身属性。
_VERB_THEN_ATTR = rf"({_PREPOSITION_ALT}|{_DECISION_ALT})[^。；！？\n]{{0,12}}?({_ATTR_ALT})"
#: 人身属性与高风险语境共现——决策影响到人身权益或社会资源分配。
_ATTR_NEAR_HIGH_STAKES = rf"({_ATTR_ALT})[^。；！？\n]{{0,15}}?({_HIGH_STAKES_ALT})"

_ATTR_PATTERNS = (
    re.compile(_ATTR_THEN_VERB),
    re.compile(_VERB_THEN_ATTR),
    re.compile(_ATTR_NEAR_HIGH_STAKES),
)


def _find_attribute_decisions(text: str) -> list[tuple[str, str, bool]]:
    """找出「以人身属性作决策依据」的表述。

    :return: ``[(原文片段, 命中的属性, 是否涉及高风险语境)]``
    """
    found: list[tuple[str, str, bool]] = []
    seen: set[str] = set()

    for pattern in _ATTR_PATTERNS:
        for match in pattern.finditer(text):
            fragment = match.group(0)
            if fragment in seen:
                continue
            seen.add(fragment)
            groups = [g for g in match.groups() if g]
            attribute = next(
                (g for g in groups if g in PERSONAL_ATTRIBUTES), groups[0]
            )
            high_stakes = any(g in HIGH_STAKES_TERMS for g in groups)
            found.append((fragment, attribute, high_stakes))

    return found


def check_ai_ethics(draft: PatentDraft) -> list[Issue]:
    """专利法第 5 条第 1 款与指南新增第 6.1.1 节的合规检查。

    指南新增审查示例中有两个反例：一个在顾客未察觉的情况下采集面部与身份
    信息做精准营销，一个以行人性别、年龄决定碰撞保护对象。前者因数据获取
    不合法、后者因违背社会公德被排除。

    这两类都不能靠"改文字"绕过去——它们指向技术方案本身的设计。因此本检查
    的定位是**尽早把问题暴露出来**，避免在投入全部撰写工作之后才发现方案
    不可申请。

    严重程度分两档，依据是决策影响的对象：

    - 影响人身权益或社会资源分配（高风险语境）→ ``ERROR``
    - 仅作为一般推荐／处理逻辑的依据 → ``WARNING``，提示评估合规性

    之所以不一律判死：以年龄确定给药剂量这类医疗方案是完全正当的，
    静态检查看不出语境差别，交给使用者判断比替审查员下结论更负责。
    """
    issues: list[Issue] = []
    text = "\n".join(payload for _, payload in draft.iter_text())

    # ---- ETH-001：明确违规表述，或人身属性与高风险语境共现 ----
    explicit = _hits(text, ETHICS_VIOLATION_PHRASES)
    decisions = _find_attribute_decisions(text)
    high_stakes = [item for item in decisions if item[2]]

    if explicit or high_stakes:
        if explicit:
            detail = "、".join(f"「{p}」" for p in explicit[:3])
            attribute_hint = ""
        else:
            fragments = [f"「{frag}」" for frag, _, _ in high_stakes[:3]]
            detail = "、".join(fragments)
            attribute_hint = (
                f"（涉及人身属性：{'、'.join(sorted({a for _, a, _ in high_stakes}))}）"
            )

        issues.append(
            Issue(
                Severity.ERROR,
                "ETH-001",
                f"技术方案以人的固有属性作为决策依据，且该决策影响人身权益"
                f"或社会资源分配：{detail}{attribute_hint}。",
                "技术方案",
                "依据专利法第 5 条第 1 款及《专利审查指南》第二部分第九章"
                "新增第 6.1.1 节，妨害公共利益的发明创造不授予专利权。"
                "指南新增的审查示例明确指出：人的生命具有同等价值和尊严，"
                "以行人性别、年龄决定碰撞保护对象属于违反社会公德。"
                "这不是措辞问题，需要重新设计技术方案——"
                "改用与决策目标直接相关的客观技术量（如距离、速度、碰撞风险"
                "评估值）作为依据。",
            )
        )
    else:
        # ---- ETH-003：一般性的属性决策，提示评估合规性 ----
        general = [item for item in decisions if not item[2]]
        if general:
            fragments = "、".join(f"「{frag}」" for frag, _, _ in general[:3])
            attributes = "、".join(sorted({a for _, a, _ in general}))
            issues.append(
                Issue(
                    Severity.WARNING,
                    "ETH-003",
                    f"技术方案以人身属性（{attributes}）作为处理逻辑的依据：{fragments}。",
                    "技术方案",
                    "指南新增第 6.1.1 节要求审查数据采集、标签管理、规则设置、"
                    "推荐决策等内容是否违反法律或妨害公共利益。"
                    "若该属性与决策目标确实存在必要的技术关联（例如医疗场景中"
                    "按年龄确定给药剂量），在说明书中写明这一必要性的理由即可；"
                    "若属可选设计，建议改用客观技术量。",
                )
            )

    # ---- ETH-002：高敏数据但未见合法性说明 ----
    sensitive = _hits(text, ETHICS_SENSITIVE_KEYWORDS)
    if sensitive and not _hits(text, ETHICS_COMPLIANCE_KEYWORDS):
        issues.append(
            Issue(
                Severity.WARNING,
                "ETH-002",
                f"技术方案处理敏感个人信息（{_format_hits(sensitive)}），"
                f"但说明书中未见数据获取与处理合法性的说明。",
                "具体实施方式",
                "指南新增第 6.1.1 节要求审查数据采集、标签管理等内容是否"
                "违反法律或妨害公共利益。建议在说明书中声明数据来源与处理的"
                "合法性，例如「所用样本均经当事人明示同意并作去标识化处理，"
                "符合《个人信息保护法》的相关规定」。",
            )
        )

    return issues


#: 本模块提供的全部检查，供 :mod:`oh_my_patent.lint` 汇入总表。
AI_CHECKS = (
    check_ai_disclosure,
    check_ai_ethics,
)