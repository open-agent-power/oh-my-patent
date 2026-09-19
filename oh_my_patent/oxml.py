"""OOXML 底层修补层：让同一份 .docx 在 WPS 与 MS Office 下渲染一致。

为什么需要这一层
----------------
``python-docx`` 的默认模板继承自 Word 的主题（theme）机制，Normal 样式里的
字体写的是 ``w:asciiTheme="minorHAnsi"`` / ``w:eastAsiaTheme="minorEastAsia"``
这样的**主题引用**，而不是字体名。主题引用最终解析成什么字体，取决于每台机器
上的主题定义与软件版本：

  - MS Office 解析 ``minorEastAsia`` → 通常得到「等线」或「宋体」（随版本变化）
  - WPS      解析 ``minorEastAsia`` → 通常得到「宋体」，但西文回退不同

结果是同一份文件在两个软件里字宽不同、每行容纳的字数不同，中文文书会整体
「串行」，页数和断页位置全部漂移。对专利文书这种对版面有硬性要求的场景，
这是不可接受的。

本模块做三件事：

  1. **去主题化**：把所有 ``*Theme`` 属性替换成显式字体名。
  2. **补全字体声明**：``w:rFonts`` 的四个属性（ascii / hAnsi / eastAsia / cs）
     全部显式写入，并设置 ``w:hint="eastAsia"``。
  3. **统一默认样式与文档级设置**：docDefaults、Normal 样式、settings.xml 的
     兼容性开关、以及正文段落的中西文自动间距，全部显式化，消除两个软件各自
     不同的默认值。

除此之外，渲染层一律使用**纯文本编号**而不用 ``w:numPr`` 自动编号列表——
WPS 对 ``numbering.xml`` 的实现与 Office 存在已知差异，会让权利要求编号
在 WPS 中显示为 • 或错位。
"""

from __future__ import annotations

from functools import lru_cache

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt
from lxml import etree

# --------------------------------------------------------------------------
# OOXML schema 规定的子元素顺序
#
# ECMA-376 要求这些元素严格按序出现，顺序错了 Office 会直接报「文件已损坏」，
# 而 WPS 往往宽容地照常打开——这个不对称是排查兼容问题时最容易踩的坑。
# 因此本模块一律通过 _insert_ordered() 插入，而不是简单 append。
# --------------------------------------------------------------------------

_RPR_ORDER: tuple[str, ...] = (
    "w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps",
    "w:smallCaps", "w:strike", "w:dstrike", "w:outline", "w:shadow",
    "w:emboss", "w:imprint", "w:noProof", "w:snapToGrid", "w:vanish",
    "w:webHidden", "w:color", "w:spacing", "w:w", "w:kern", "w:position",
    "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect", "w:bdr", "w:shd",
    "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
    "w:eastAsianLayout", "w:specVanish", "w:oMath",
)

_PPR_ORDER: tuple[str, ...] = (
    "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore",
    "w:framePr", "w:widowControl", "w:numPr", "w:suppressLineNumbers",
    "w:pBdr", "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku",
    "w:wordWrap", "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE",
    "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid",
    "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
    "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
    "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr",
    "w:sectPr", "w:pPrChange",
)

#: 所有 「主题引用」形式的字体属性，必须被显式字体名替换掉。
_THEME_FONT_ATTRS: tuple[str, ...] = (
    "w:asciiTheme",
    "w:hAnsiTheme",
    "w:eastAsiaTheme",
    "w:cstheme",
)

#: 主题色引用，同理需要去掉，否则配色随软件主题变化。
_THEME_COLOR_ATTRS: tuple[str, ...] = ("w:themeColor", "w:themeTint", "w:themeShade")

#: 主题填充引用，出现在表格底色与段落底纹上。
_THEME_FILL_ATTRS: tuple[str, ...] = ("w:themeFill", "w:themeFillTint", "w:themeFillShade")


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _qualified(tag: str) -> str:
    """把 ``"w:rFonts"`` 归一化成 ``"{http://...}rFonts"``。

    必须归一化之后再比较：lxml 元素的 ``.tag`` 是带命名空间的 Clark 记法，
    而上面的顺序表写的是 ``w:`` 前缀简写。两者直接比较永远不相等，
    会让 :func:`insert_ordered` 静默退化成 ``append()``——生成的文件
    在 WPS 里能打开，在 Office 里却可能被判为损坏。
    """
    return tag if tag.startswith("{") else qn(tag)


@lru_cache(maxsize=None)
def _qualified_order(order: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_qualified(tag) for tag in order)


def insert_ordered(parent, child, order: tuple[str, ...]):
    """按 schema 顺序把 ``child`` 插入 ``parent``。"""
    normalized = _qualified_order(tuple(order))
    try:
        target = normalized.index(child.tag)
    except ValueError:
        parent.append(child)
        return child
    for existing in parent:
        try:
            position = normalized.index(existing.tag)
        except ValueError:
            continue
        if position > target:
            existing.addprevious(child)
            return child
    parent.append(child)
    return child


def get_or_add(parent, tag: str, order: tuple[str, ...]):
    """取 ``parent`` 下的 ``tag`` 子元素，不存在则按序新建。"""
    el = parent.find(qn(tag))
    if el is None:
        el = OxmlElement(tag)
        insert_ordered(parent, el, order)
    return el


def drop_theme_attributes(el) -> None:
    """删除元素上的全部主题引用属性（字体与颜色）。"""
    if el is None:
        return
    for attr in _THEME_FONT_ATTRS + _THEME_COLOR_ATTRS + _THEME_FILL_ATTRS:
        key = qn(attr)
        if key in el.attrib:
            del el.attrib[key]


def _de_theme_element(el, western: str, east_asian: str) -> int:
    """把单个元素上的主题引用**替换**成显式值，返回处理的引用数。

    这里刻意采用「替换」而不是「删除」：

    ``python-docx`` 的默认模板来自英文版 Word，主题里
    ``<a:ea typeface=""/>`` 是**空字符串**——中文字体只写在按脚本区分
    的 ``<a:font script="Hans" typeface="宋体"/>`` 里。这意味着「主题里
    的中文字体是什么」完全交给各软件自行决定：MS Office 会走脚本回退
    得到宋体，WPS 则可能用自己的一套默认值。

    如果只是把 ``w:eastAsiaTheme`` 删掉，该样式会回退到 docDefaults
    的字体，表面上也能看，但样式面板里会显示成「未设置」，用户日后
    在 WPS 或 Word 里重新应用样式时又会引入新的差异。显式写上字体名，
    差异才真正被消除。

    颜色同理：《专利审查指南》要求申请文件黑白清楚，所以凡是引用
    主题色的地方一律落成纯黑（``000000``），表格底色落成纯白。
    """
    changed = 0
    tag = el.tag

    if tag == qn("w:rFonts"):
        mapping = (
            ("w:asciiTheme", "w:ascii", western),
            ("w:hAnsiTheme", "w:hAnsi", western),
            ("w:eastAsiaTheme", "w:eastAsia", east_asian),
            ("w:cstheme", "w:cs", western),
        )
        for theme_attr, plain_attr, font_name in mapping:
            if el.get(qn(theme_attr)) is None:
                continue
            del el.attrib[qn(theme_attr)]
            el.set(qn(plain_attr), font_name)
            changed += 1
        if changed:
            # 中文字体的选择同时受 hint 影响，一并写明确
            el.set(qn("w:hint"), "eastAsia")
        return changed

    if tag == qn("w:color"):
        if any(el.get(qn(a)) is not None for a in _THEME_COLOR_ATTRS):
            drop_theme_attributes(el)
            el.set(qn("w:val"), "000000")
            changed += 1
        return changed

    if tag == qn("w:shd"):
        if el.get(qn("w:themeFill")) is not None:
            del el.attrib[qn("w:themeFill")]
            el.set(qn("w:fill"), "FFFFFF")
            changed += 1
        drop_theme_attributes(el)
        return changed

    for attr in _THEME_FONT_ATTRS + _THEME_COLOR_ATTRS + _THEME_FILL_ATTRS:
        key = qn(attr)
        if key in el.attrib:
            del el.attrib[key]
            changed += 1
    return changed


def _de_theme_tree(el, western: str, east_asian: str) -> int:
    """递归处理整棵子树。"""
    if el is None:
        return 0
    return sum(_de_theme_element(node, western, east_asian) for node in el.iter())


def de_theme_fonts(document, western: str, east_asian: str) -> int:
    """去除整份文档的主题字体/颜色依赖。

    覆盖四类位置，缺一处都会留下隐患：

    1. ``styles.xml`` —— 里面几十个用不到的标题样式与表格样式全都挂着
       ``majorEastAsia`` 这类主题引用。虽然不影响本次输出，但只要用户
       在 WPS 里手动套用一次样式，差异就会回来。
    2. ``document.xml`` 正文。
    3. 各节的 ``sectPr``。
    4. 其余 XML 部分。重点是 ``stylesWithEffects.xml``：``python-docx``
       的默认模板来自 Word 2010 时代，这份「样式效果」文件是 ``styles.xml``
       的完整副本，同样挂着主题引用，只清 ``styles.xml`` 会把它整份漏掉。
    """
    total = _de_theme_tree(document.styles.element, western, east_asian)
    total += _de_theme_tree(document.element.body, western, east_asian)
    for section in document.sections:
        total += _de_theme_tree(section._sectPr, western, east_asian)

    handled = {"/word/styles.xml", "/word/document.xml"}
    for part in _iter_package_parts(document):
        partname = str(getattr(part, "partname", ""))
        if partname in handled:
            continue

        element = getattr(part, "element", None)
        if element is not None:
            total += _de_theme_tree(element, western, east_asian)
            continue

        # python-docx 把 stylesWithEffects.xml、theme1.xml 这类它不解析的
        # 部分当作裸 Part 保存，没有 element 可供操作，只能在字节层面替换。
        blob = getattr(part, "_blob", None)
        if not blob:
            continue
        new_blob = de_theme_blob(blob, western, east_asian)
        if new_blob is not blob:
            part._blob = new_blob
            total += 1

    return total


#: 用于重写 python-docx 不解析的 XML 部分。禁用实体解析，
#: 避免处理来自外部模板的文件时引入 XXE 风险。
_PACKAGE_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    load_dtd=False,
    no_network=True,
    remove_blank_text=False,
    huge_tree=False,
)


def de_theme_blob(blob: bytes, western: str, east_asian: str) -> bytes:
    """替换 XML 部分里的主题字体与主题色引用。

    只用于 python-docx 不解析、拿不到 element 的部分。

    这里刻意**不用正则做字节替换**：主题属性常常与目标属性共存
    （例如 ``<w:shd w:fill="auto" w:themeFill="accent1"/>``），
    直接把 ``themeFill`` 改写成 ``fill`` 会产出两个 ``w:fill``，
    重复属性会让 XML 直接非法。走 lxml 解析则天然没有这个问题。

    :param blob: 原始 XML 字节
    :return: 替换后的字节；未发生替换（或不是 XML）时原样返回入参对象
    """
    if not blob.lstrip()[:1] == b"<":
        return blob

    try:
        root = etree.fromstring(blob, parser=_PACKAGE_XML_PARSER)
    except etree.XMLSyntaxError:
        # 解析不了就原样放过：宁可留下主题引用，也不能产出坏文件。
        return blob

    if _de_theme_tree(root, western, east_asian) == 0:
        return blob

    # lxml 会沿用原文档里已声明的命名空间前缀（w:、r:、a: 等），
    # 因此序列化结果与 python-docx 写出的其它部分保持一致。
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )


def _iter_package_parts(document) -> list:
    """列出包内所有部分。取不到时返回空列表，不影响主流程。"""
    package = getattr(document.part, "package", None)
    if package is None:  # pragma: no cover - 防御性分支
        return []
    try:
        return list(package.iter_parts())
    except Exception:  # pragma: no cover
        return []


# --------------------------------------------------------------------------
# 字符级设置
# --------------------------------------------------------------------------

def set_run_font(
    run,
    western: str,
    east_asian: str,
    size_pt: float | None = None,
    bold: bool | None = None,
):
    """把一个 run 的字体、字号、粗体全部显式写死。

    :param western: 西文（含数字、标点）字体名，如 ``"Times New Roman"``
    :param east_asian: 汉字字体名，如 ``"宋体"``
    :param size_pt: 字号（磅）。``w:sz`` 与 ``w:szCs`` 会同步设置，
                    否则复杂文种脚本下的字号会回退到 10pt。
    :param bold: ``True`` 加粗、``False`` 去粗、``None`` 不改动
    """
    rPr = run._element.get_or_add_rPr()

    rFonts = get_or_add(rPr, "w:rFonts", _RPR_ORDER)
    drop_theme_attributes(rFonts)
    rFonts.set(qn("w:ascii"), western)
    rFonts.set(qn("w:hAnsi"), western)
    rFonts.set(qn("w:eastAsia"), east_asian)
    rFonts.set(qn("w:cs"), western)
    # hint=eastAsia 让「中文标点、全角字符、以及落在模糊区间的字符」
    # 一律使用 eastAsia 字体。缺了它，Office 与 WPS 会对同一段的中文标点
    # 各选各的字体，标点宽度不一会直接导致行尾对齐差异。
    rFonts.set(qn("w:hint"), "eastAsia")

    # 语言标记决定断行规则、标点挤压与拼写检查。不显式设置时，
    # 两个软件会按各自 locale 推断，中文标点的行首行尾禁则表现不同。
    lang = get_or_add(rPr, "w:lang", _RPR_ORDER)
    lang.set(qn("w:val"), "en-US")
    lang.set(qn("w:eastAsia"), "zh-CN")

    if size_pt is not None:
        half_points = str(int(round(size_pt * 2)))
        for tag in ("w:sz", "w:szCs"):
            get_or_add(rPr, tag, _RPR_ORDER).set(qn("w:val"), half_points)
        # 同时写 python-docx 的视图属性，方便调用方读取
        run.font.size = Pt(size_pt)

    if bold is not None:
        for tag in ("w:b", "w:bCs"):
            existing = rPr.find(qn(tag))
            if bold:
                get_or_add(rPr, tag, _RPR_ORDER).set(qn("w:val"), "1")
            elif existing is not None:
                rPr.remove(existing)

    return run


# --------------------------------------------------------------------------
# 段落级设置
# --------------------------------------------------------------------------

def set_paragraph_format(
    paragraph,
    *,
    line_spacing: float | None = None,
    first_line_indent_chars: float | None = None,
    char_width_pt: float = 12.0,
    space_before_pt: float | None = None,
    space_after_pt: float | None = None,
    alignment=None,
    keep_with_next: bool = False,
    keep_together: bool = False,
):
    """设置段落格式，中文相关的属性直接落到 XML 上。

    ``python-docx`` 表达不了「首行缩进 2 字符」这种字符单位的缩进，
    只能设磅值。而字符缩进是中文文书的要求（缩进量应随字号变化），
    因此这里直接写 ``w:firstLineChars``。

    :param char_width_pt: 用于把字符缩进换算成磅值兜底，应与段落字号一致。
    """
    pPr = paragraph._element.get_or_add_pPr()

    if line_spacing is not None:
        spacing = get_or_add(pPr, "w:spacing", _PPR_ORDER)
        # lineRule=auto 时 w:line 是 1/240 行，1.5 倍行距 = 360
        spacing.set(qn("w:line"), str(int(round(line_spacing * 240))))
        spacing.set(qn("w:lineRule"), "auto")
    if space_before_pt is not None or space_after_pt is not None:
        spacing = get_or_add(pPr, "w:spacing", _PPR_ORDER)
        if space_before_pt is not None:
            spacing.set(qn("w:before"), str(int(round(space_before_pt * 20))))
            spacing.set(qn("w:beforeAutospacing"), "0")
        if space_after_pt is not None:
            spacing.set(qn("w:after"), str(int(round(space_after_pt * 20))))
            spacing.set(qn("w:afterAutospacing"), "0")

    if first_line_indent_chars is not None:
        ind = get_or_add(pPr, "w:ind", _PPR_ORDER)
        if first_line_indent_chars <= 0:
            ind.set(qn("w:firstLineChars"), "0")
            ind.set(qn("w:firstLine"), "0")
        else:
            ind.set(qn("w:firstLineChars"), str(int(round(first_line_indent_chars * 100))))
            # 兜底磅值：万一步骤中 firstLineChars 被其它软件忽略，仍能缩进
            twips = first_line_indent_chars * char_width_pt * 20
            ind.set(qn("w:firstLine"), str(int(round(twips))))
            for attr in ("w:hanging", "w:hangingChars"):
                key = qn(attr)
                if key in ind.attrib:
                    del ind.attrib[key]

    if alignment is not None:
        paragraph.alignment = alignment

    if keep_with_next or keep_together:
        if keep_with_next:
            get_or_add(pPr, "w:keepNext", _PPR_ORDER).set(qn("w:val"), "1")
        if keep_together:
            get_or_add(pPr, "w:keepLines", _PPR_ORDER).set(qn("w:val"), "1")
    else:
        # 显式关闭，避免继承到 Word 模板中可能存在的「与下段同页」
        for tag in ("w:keepNext", "w:keepLines"):
            existing = pPr.find(qn(tag))
            if existing is not None:
                pPr.remove(existing)

    return paragraph


def set_no_proof(paragraph) -> None:
    """关闭该段落的拼写/语法检查标记。

    专利文本充满自造词、化学式与编号，让两个软件都别去标红，
    否则在 WPS 里满屏波浪线，打印出来却没问题，干扰审阅。
    """
    for run in paragraph.runs:
        rPr = run._element.get_or_add_rPr()
        get_or_add(rPr, "w:noProof", _RPR_ORDER).set(qn("w:val"), "1")


# --------------------------------------------------------------------------
# 文档级设置
# --------------------------------------------------------------------------

def configure_document(document, options) -> None:
    """把默认模板里的「隐式默认值」全部替换成显式声明。

    应当在写入任何内容之前调用一次。
    """
    western, east_asian = options.resolved_fonts()

    # 先整体去主题化，再把 docDefaults 与 Normal 定成本文档的字体。
    # 顺序不能反：去主题化会替换掉已存在的字体声明，放在后面会把
    # 刚设好的值再覆盖一遍（虽然结果相同，但语义混乱）。
    de_theme_fonts(document, western, east_asian)

    _patch_doc_defaults(document, western, east_asian, options)
    _patch_normal_style(document, western, east_asian, options)
    _patch_settings(document)
    configure_section(document.sections[0])


def _patch_doc_defaults(document, western: str, east_asian: str, options) -> None:
    """修补 styles.xml 的 docDefaults。

    docDefaults 是整个文档的最后兜底。默认模板在这里同样使用主题引用，
    且只声明了西文字体，没有 ``w:eastAsia``——这正是「中文在 Office 里
    变成等线、在 WPS 里变成宋体」的根因。
    """
    styles_el = document.styles.element

    doc_defaults = styles_el.find(qn("w:docDefaults"))
    if doc_defaults is None:
        doc_defaults = OxmlElement("w:docDefaults")
        styles_el.insert(0, doc_defaults)

    # ---- 字符默认值 ----
    rpr_default = doc_defaults.find(qn("w:rPrDefault"))
    if rpr_default is None:
        rpr_default = OxmlElement("w:rPrDefault")
        doc_defaults.insert(0, rpr_default)
    rPr = rpr_default.find(qn("w:rPr"))
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        rpr_default.append(rPr)

    _de_theme_tree(rPr, western, east_asian)

    rFonts = get_or_add(rPr, "w:rFonts", _RPR_ORDER)
    drop_theme_attributes(rFonts)
    rFonts.set(qn("w:ascii"), western)
    rFonts.set(qn("w:hAnsi"), western)
    rFonts.set(qn("w:eastAsia"), east_asian)
    rFonts.set(qn("w:cs"), western)
    rFonts.set(qn("w:hint"), "eastAsia")

    lang = get_or_add(rPr, "w:lang", _RPR_ORDER)
    lang.set(qn("w:val"), "en-US")
    lang.set(qn("w:eastAsia"), "zh-CN")

    half_points = str(int(round(options.body_size * 2)))
    for tag in ("w:sz", "w:szCs"):
        get_or_add(rPr, tag, _RPR_ORDER).set(qn("w:val"), half_points)

    # 字距调整阈值。两个软件对「何时启用西文字距调整」的默认阈值不同，
    # 显式写 2（半磅）与 Word 中文档的常规表现对齐。
    get_or_add(rPr, "w:kern", _RPR_ORDER).set(qn("w:val"), "2")

    # ---- 段落默认值 ----
    ppr_default = doc_defaults.find(qn("w:pPrDefault"))
    if ppr_default is None:
        ppr_default = OxmlElement("w:pPrDefault")
        doc_defaults.append(ppr_default)
    pPr = ppr_default.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        ppr_default.append(pPr)

    # 中西文之间自动间距：两个软件默认都是开，但显式声明可避免
    # 某些 WPS 精简版把默认值改成关导致版面偏窄。
    for tag in ("w:autoSpaceDE", "w:autoSpaceDN"):
        get_or_add(pPr, tag, _PPR_ORDER).set(qn("w:val"), "1")

    spacing = get_or_add(pPr, "w:spacing", _PPR_ORDER)
    spacing.set(qn("w:line"), str(int(round(options.line_spacing * 240))))
    spacing.set(qn("w:lineRule"), "auto")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:before"), "0")


def _patch_normal_style(document, western: str, east_asian: str, options) -> None:
    """修补 Normal 样式，并确保它不再引用主题字体。"""
    normal = document.styles["Normal"]
    normal.font.name = western
    normal.font.size = Pt(options.body_size)

    rPr = normal.element.get_or_add_rPr()
    _de_theme_tree(rPr, western, east_asian)

    rFonts = get_or_add(rPr, "w:rFonts", _RPR_ORDER)
    rFonts.set(qn("w:ascii"), western)
    rFonts.set(qn("w:hAnsi"), western)
    rFonts.set(qn("w:eastAsia"), east_asian)
    rFonts.set(qn("w:cs"), western)
    rFonts.set(qn("w:hint"), "eastAsia")

    pf = normal.paragraph_format
    pf.line_spacing = options.line_spacing
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)


def _patch_settings(document) -> None:
    """修补 settings.xml 中的兼容性与排版开关。

    这些开关在 WPS 与 Word 中的默认值并不总是一致，显式写死可以
    消除「同一文件在两处行距/断行不同」的一整类问题。
    """
    settings = document.settings.element

    # 不做自动断字。中文文档断字规则差异很大，直接关掉最稳。
    for tag in ("w:autoHyphenation", "w:doNotHyphenateCaps"):
        existing = settings.find(qn(tag))
        if existing is None:
            existing = OxmlElement(tag)
            settings.append(existing)
        existing.set(qn("w:val"), "0" if tag == "w:autoHyphenation" else "1")

    # 明确的兼容模式版本。缺失时 WPS 可能按兼容模式（Word 2003）排版，
    # 得到明显不同的行距与字距。
    compat = settings.find(qn("w:compat"))
    if compat is None:
        compat = OxmlElement("w:compat")
        settings.append(compat)
    found_mode = False
    for setting in compat.findall(qn("w:compatSetting")):
        if setting.get(qn("w:name")) == "compatibilityMode":
            setting.set(qn("w:val"), "15")
            found_mode = True
    if not found_mode:
        node = OxmlElement("w:compatSetting")
        node.set(qn("w:name"), "compatibilityMode")
        node.set(qn("w:uri"), "http://schemas.microsoft.com/office/word")
        node.set(qn("w:val"), "15")
        compat.append(node)


def configure_section(section) -> None:
    """设置纸张为 A4、页边距符合指南，并关闭文档网格。

    关闭文档网格（``docGrid type="default"``）很关键：若启用行网格，
    段落行距会被吸附到网格上，而 WPS 与 Word 的网格吸附算法存在差异，
    会导致两个软件里每页行数不同。关掉后行距完全由段落自身的
    ``w:spacing`` 决定，结果稳定可预测。
    """
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Mm(25)
    section.left_margin = Mm(25)
    section.right_margin = Mm(15)
    section.bottom_margin = Mm(15)
    section.header_distance = Mm(15)
    section.footer_distance = Mm(10)

    sectPr = section._sectPr
    doc_grid = sectPr.find(qn("w:docGrid"))
    if doc_grid is None:
        doc_grid = OxmlElement("w:docGrid")
        sectPr.append(doc_grid)
    doc_grid.set(qn("w:type"), "default")
    for attr in ("w:linePitch", "w:charSpace"):
        key = qn(attr)
        if key in doc_grid.attrib:
            del doc_grid.attrib[key]


def add_page_number_footer(section, western: str, east_asian: str, size_pt: float) -> None:
    """在页脚居中放置页码（PAGE 域）。

    用最朴素的 PAGE 域，不用 ``w:fldSimple`` 之外的花样。
    域代码在 WPS 与 Office 中都能正确求值。
    """
    footer = section.footer
    footer.is_linked_to_previous = False
    paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    paragraph.text = ""
    paragraph.alignment = 1  # CENTER

    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._element.append(fld_begin)
    run._element.append(instr)
    run._element.append(fld_end)

    set_run_font(run, western, east_asian, size_pt=size_pt)


def set_page_break_before(paragraph, on: bool = True) -> None:
    """让某个段落从新的一页开始。

    用段落的 ``w:pageBreakBefore`` 而不是插入一个含分页符的空段落，
    这样不会在上一部分末尾留下一个多余的空行——那个空行在 WPS 里
    有时会被撑成整整一页空白，是「生成的文档莫名多出空白页」的常见原因。
    """
    pPr = paragraph._element.get_or_add_pPr()
    if on:
        get_or_add(pPr, "w:pageBreakBefore", _PPR_ORDER).set(qn("w:val"), "1")
    else:
        existing = pPr.find(qn("w:pageBreakBefore"))
        if existing is not None:
            pPr.remove(existing)


def add_page_break(document):
    """插入一个独立的分页符段落。

    仅在确实需要「整页空白」时使用；常规的「另起一页」请用
    :func:`set_page_break_before`。
    """
    from docx.enum.text import WD_BREAK

    paragraph = document.add_paragraph()
    run = paragraph.add_run()
    run.add_break(WD_BREAK.PAGE)
    return paragraph
