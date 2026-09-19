"""稿件解析：把 Markdown / YAML / JSON 稿件转成 :class:`PatentDraft`。

支持的输入形态
--------------
1. **结构化 Markdown**（推荐）。头部 YAML frontmatter 写著录项目，
   正文用 ``# 权利要求书`` ``# 说明书`` ``# 摘要`` 分部分，
   ``## 技术领域`` 分章节。这是 AI 起草时的写入格式。
2. **粘贴的既有文稿**。章节用 ``【技术领域】`` 这类方括号标记、
   完全不用 Markdown 语法的旧稿，也能直接吃进来。
3. **纯结构化数据**。``.yaml`` / ``.json`` 文件，字段名与
   :class:`PatentDraft` 对齐。

解析策略是**宽容优先**：无法归类的带标题段落会被收进 ``extra_sections``
而不是丢弃，宁可多留也不静默丢内容。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .schema import (
    DesignBrief,
    Drawing,
    PatentDraft,
    Subsection,
    build_claim,
    parse_claims_block,
    parse_patent_type,
)
from .spec import SectionKey

try:  # pragma: no cover - 只影响 frontmatter 的解析质量
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


class ParseError(ValueError):
    """稿件无法解析时抛出，消息里带可操作的修复建议。"""


# --------------------------------------------------------------------------
# 标题别名表
# --------------------------------------------------------------------------

def normalize_title(raw: str) -> str:
    """归一化标题，便于别名匹配。

    覆盖实务中常见的几种写法：``【技术领域】``、``一、技术领域``、
    ``1.技术领域``、``（一）技术领域``、``技术领域：``。
    """
    text = raw.strip()
    text = re.sub(r"^[【\[［(（]\s*", "", text)
    text = re.sub(r"\s*[】\]］)）]$", "", text)
    text = re.sub(r"^\s*[（(]\s*[一二三四五六七八九十]+\s*[)）]\s*", "", text)
    text = re.sub(r"^\s*(?:[一二三四五六七八九十]+|\d+)\s*[、.．,，)）]\s*", "", text)
    text = text.strip().rstrip("：:。.")
    return re.sub(r"\s+", "", text).lower()


_PART_ALIASES: dict[str, str] = {}
_SECTION_ALIASES: dict[str, SectionKey] = {}
_SUBSECTION_FIELDS: dict[str, str] = {}
_DESIGN_FIELDS: dict[str, str] = {}


def _register(mapping: dict, target, *names: str) -> None:
    for name in names:
        mapping[normalize_title(name)] = target


_register(_PART_ALIASES, "claims", "权利要求书", "权利要求", "claims", "claim")
_register(_PART_ALIASES, "description", "说明书", "说明书正文", "description", "specification")
_register(_PART_ALIASES, "abstract", "摘要", "说明书摘要", "abstract")
_register(_PART_ALIASES, "drawings", "附图", "说明书附图", "drawings", "figures")
_register(_PART_ALIASES, "design_brief", "简要说明", "外观设计简要说明", "design brief", "brief")

_register(_SECTION_ALIASES, SectionKey.TECHNICAL_FIELD,
          "技术领域", "所属技术领域", "technical field", "field")
_register(_SECTION_ALIASES, SectionKey.BACKGROUND,
          "背景技术", "现有技术", "背景", "background", "prior art")
_register(_SECTION_ALIASES, SectionKey.SUMMARY,
          "发明内容", "实用新型内容", "发明的内容", "summary", "disclosure")
_register(_SECTION_ALIASES, SectionKey.DRAWING_DESC,
          "附图说明", "附图简介", "图面说明", "drawing description",
          "brief description of drawings")
_register(_SECTION_ALIASES, SectionKey.EMBODIMENTS,
          "具体实施方式", "具体实施方法", "实施方式", "具体实施例", "实施例",
          "embodiments", "detailed description")

_register(_SUBSECTION_FIELDS, "problems",
          "要解决的技术问题", "技术问题", "解决的问题", "待解决的问题", "所解决的技术问题",
          "problems", "technical problem")
_register(_SUBSECTION_FIELDS, "solution",
          "技术方案", "技术方案内容", "解决方案", "方案", "solution", "technical solution")
_register(_SUBSECTION_FIELDS, "effects",
          "有益效果", "技术效果", "有益的技术效果", "效果",
          "beneficial effects", "effects")

_register(_DESIGN_FIELDS, "usage", "用途", "产品用途", "用途说明")
_register(_DESIGN_FIELDS, "points", "设计要点", "设计要点说明")
_register(_DESIGN_FIELDS, "best_view",
          "最能表明设计要点的图片", "最能表明设计要点的图片或照片", "代表图", "指定图片")
_register(_DESIGN_FIELDS, "omitted_views", "省略视图说明", "省略视图的情况", "省略视图")
_register(_DESIGN_FIELDS, "color_protection", "是否请求保护色彩", "请求保护色彩", "保护色彩")


# --------------------------------------------------------------------------
# Markdown 树
# --------------------------------------------------------------------------

@dataclass
class _Node:
    """Markdown 文档树的一个节点。``level == 0`` 表示文档根。"""

    level: int
    title: str
    body: str = ""
    children: list["_Node"] = field(default_factory=list)

    def walk(self):
        """先序遍历（不含自身），保证父节点先于子节点被访问。"""
        for child in self.children:
            yield child
            yield from child.walk()


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_BRACKET_HEADING_RE = re.compile(r"^\s*[【\[]\s*([^】\]]+?)\s*[】\]]\s*(.*)$")
#: 独占一行的「一、技术领域」「1. 技术领域」式标题。
_NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?:[一二三四五六七八九十]+|\d+)\s*[、.．]\s*(\S.*?)\s*$"
)


def known_headings() -> set[str]:
    """全部已知的标题别名（已归一化）。

    延迟到调用时组装，因为本模块在导入过程中会持续往各别名表里注册。
    """
    return (
        set(_PART_ALIASES)
        | set(_SECTION_ALIASES)
        | set(_SUBSECTION_FIELDS)
        | set(_DESIGN_FIELDS)
    )


def normalize_plain_text(text: str) -> str:
    """把「非 Markdown 写法」的章节标题升级成 Markdown 标题。

    用户从 Word 里粘出来的稿件通常长这样：

        【技术领域】
        本发明涉及……

    或者：

        一、技术领域
        本发明涉及……

    这两种都不是 Markdown 标题，直接交给树解析器会被当成正文，
    导致章节全部识别不出来。这里把它们统一成 ``## 技术领域``。

    **只在该行能匹配到已知章节名时才升级**，这是关键的安全阀：
    权利要求书里的 ``1. 一种装置，其特征在于……`` 同样符合「数字+顿号」
    的形式，但它的标题部分不在别名表里，因此会原样保留为正文。
    """
    headings = known_headings()
    output: list[str] = []

    for line in text.splitlines():
        bracket = _BRACKET_HEADING_RE.match(line)
        if bracket:
            title, rest = bracket.group(1).strip(), bracket.group(2).strip()
            output.append(f"## {title}")
            if rest:
                output.append(rest)
            continue

        numbered = _NUMBERED_HEADING_RE.match(line)
        if numbered:
            title = numbered.group(1).strip()
            if normalize_title(title) in headings:
                output.append(f"## {title}")
                continue

        output.append(line)

    return "\n".join(output)


def build_tree(text: str) -> _Node:
    """把 Markdown 文本解析成树。

    代码围栏内的 ``#`` 不会被当作标题——专利稿件里常有含 ``#`` 的
    化学式或代码片段。
    """
    root = _Node(level=0, title="")
    stack: list[_Node] = [root]
    buffer: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if buffer:
            stack[-1].body = _clean_text("\n".join(buffer))
            buffer.clear()

    for line in text.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            buffer.append(line)
            continue

        if fence is None:
            heading = _HEADING_RE.match(line)
            if heading:
                flush()
                level = len(heading.group(1))
                while len(stack) > 1 and stack[-1].level >= level:
                    stack.pop()
                node = _Node(level=level, title=heading.group(2).strip())
                stack[-1].children.append(node)
                stack.append(node)
                continue

        buffer.append(line)

    flush()
    return root


# --------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """切出 YAML frontmatter 与正文。没有 frontmatter 时返回空字典与原文。"""
    text = text.lstrip("\ufeff")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end():]
    if yaml is None:
        return _parse_simple_yaml(raw), body
    try:
        data = yaml.safe_load(raw) or {}
    except Exception as exc:  # noqa: BLE001 - 转成可读提示交给调用方
        raise ParseError(
            f"frontmatter 不是合法 YAML：{exc}\n"
            f'提示：值里含冒号时请用引号包起来，例如 title: "一种XX：装置"。'
        ) from exc
    if not isinstance(data, dict):
        raise ParseError("frontmatter 必须是键值对形式。")
    return data, body


def _parse_simple_yaml(raw: str) -> dict:
    """无 PyYAML 时的降级解析，只支持 ``key: value`` 与行内列表。"""
    data: dict = {}
    for line in raw.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key.strip()] = [
                item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()
            ]
        else:
            data[key.strip()] = value.strip("'\"")
    return data


# --------------------------------------------------------------------------
# 附图提取
# --------------------------------------------------------------------------

_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CAPTION_RE = re.compile(r"^\s*图\s*(\d+)\s*(.*)$")
_ABSTRACT_MARKERS = ("摘要附图", "摘要用图", "代表图")


def _extract_captions(text: str) -> list[tuple[int, str]]:
    """从附图说明文本里抽出「图N为……」这类整行句子。

    返回 ``(图号, 完整原句)``。保留完整原句而不是只留描述部分，
    因为说明书附图说明章节要求的就是完整句子。
    """
    found: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*+ ").strip()
        if not line:
            continue
        match = _CAPTION_RE.match(line)
        if match and match.group(2).strip():
            found.append((int(match.group(1)), line))
    return found


# --------------------------------------------------------------------------
# 主解析流程
# --------------------------------------------------------------------------

def parse_markdown(text: str, source: str = "") -> PatentDraft:
    """解析 Markdown 稿件。"""
    front, body_text = split_frontmatter(text)
    tree = build_tree(normalize_plain_text(body_text))

    draft = PatentDraft(title="")
    abstract_figure_no = _apply_frontmatter(draft, front)

    buckets: dict[str, list[str]] = {key: [] for key in set(_PART_ALIASES.values())}
    draw_captions: list[tuple[int, str]] = []
    draw_images: list[tuple[int, str, str, bool]] = []
    extra: list[Subsection] = []

    for node in tree.walk():
        key = normalize_title(node.title)
        body = node.body.strip()

        part_key = _PART_ALIASES.get(key)
        if part_key:
            if body:
                buckets[part_key].append(body)
            continue

        design_field = _DESIGN_FIELDS.get(key)
        if design_field:
            _apply_design_field(draft, design_field, body)
            continue

        subsection_field = _SUBSECTION_FIELDS.get(key)
        if subsection_field:
            _append(draft, subsection_field, body)
            continue

        section_key = _SECTION_ALIASES.get(key)
        if section_key is not None:
            if section_key is SectionKey.DRAWING_DESC:
                # 附图说明章节不单独存字段：渲染时由 drawings 逐条重建，
                # 保证「图N为……」的措辞与附图列表永远一致。
                draw_captions.extend(_extract_captions(body))
                leftover = _non_caption_lines(body)
                if leftover:
                    extra.append(Subsection(heading=node.title.strip(), body=leftover))
            elif section_key is SectionKey.SUMMARY:
                _append(draft, "solution", body)
            else:
                _append(draft, SECTION_FIELDS[section_key], body)
            continue

        if body or node.title.strip():
            extra.append(Subsection(heading=node.title.strip(), body=body))

    # ---- 权利要求书 ----
    if buckets["claims"]:
        draft.claims = parse_claims_block("\n".join(buckets["claims"]))

    # ---- 摘要 ----
    if buckets["abstract"]:
        draft.abstract = _strip_abstract_markers(_clean_text("\n".join(buckets["abstract"])))

    # ---- 附图 ----
    # 以 frontmatter 里给出的附图列表为基底：它提供了图片路径，
    # 而正文「附图说明」章节提供措辞。两者按图号合并，各补各的缺。
    merged: dict[int, Drawing] = {d.number: d for d in draft.drawings}
    for number, caption in draw_captions:
        merged.setdefault(number, Drawing(number=number)).caption = caption
    for number, alt, path, is_abstract in _collect_images(buckets["drawings"]):
        drawing = merged.setdefault(number, Drawing(number=number))
        drawing.path = path
        drawing.is_abstract = drawing.is_abstract or is_abstract
        if alt and not _is_abstract_caption(alt) and not drawing.caption:
            drawing.caption = alt
    draft.drawings = [merged[k] for k in sorted(merged)]

    if abstract_figure_no is not None:
        for drawing in draft.drawings:
            drawing.is_abstract = drawing.number == abstract_figure_no

    # ---- 外观设计：简要说明若整块写在专用部分里 ----
    if buckets["design_brief"] and not draft.design_brief.points:
        draft.design_brief.points = _clean_text("\n".join(buckets["design_brief"]))

    draft.extra_sections = extra
    draft.source_path = source
    _finalize(draft)
    return draft


#: 章节键到模型字段的映射。「发明内容」走 solution，由 sections() 负责拼装。
SECTION_FIELDS: dict[SectionKey, str] = {
    SectionKey.TECHNICAL_FIELD: "technical_field",
    SectionKey.BACKGROUND: "background",
    SectionKey.SUMMARY: "solution",
    SectionKey.EMBODIMENTS: "embodiments",
}


def _collect_images(blocks: list[str]) -> list[tuple[int, str, str, bool]]:
    """从附图部分的 Markdown 里抽出 ``![](path)`` 形式的图片。"""
    results: list[tuple[int, str, str, bool]] = []
    index = 0
    for block in blocks:
        for alt, path in _IMAGE_RE.findall(block):
            index += 1
            match = re.search(r"(\d+)", alt or "")
            number = int(match.group(1)) if match else index
            results.append((number, alt, path, _is_abstract_caption(alt)))
    return results


def _is_abstract_caption(text: str) -> bool:
    return any(marker in text for marker in _ABSTRACT_MARKERS)


def _non_caption_lines(text: str) -> str:
    """挑出附图说明里不是「图N为……」的行。"""
    kept: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _CAPTION_RE.match(line.lstrip("-*+ ").strip())
        if not (match and match.group(2).strip()):
            kept.append(line)
    return "\n".join(kept)


def _strip_abstract_markers(text: str) -> str:
    for marker in _ABSTRACT_MARKERS:
        text = text.replace(marker, "")
    return _clean_text(text)


def _append(draft: PatentDraft, field_name: str, body: str) -> None:
    """把一段正文并入某个字段，保留原有顺序。"""
    body = body.strip()
    if not body:
        return
    current = getattr(draft, field_name, "")
    setattr(draft, field_name, f"{current}\n\n{body}".strip() if current else body)


def _apply_design_field(draft: PatentDraft, field_name: str, body: str) -> None:
    if field_name == "color_protection":
        if body:
            draft.design_brief.color_protection = bool(re.search(r"是|要求|请求", body))
        return
    current = getattr(draft.design_brief, field_name, "")
    if not current and body:
        setattr(draft.design_brief, field_name, body)


def _clean_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --------------------------------------------------------------------------
# frontmatter 落库
# --------------------------------------------------------------------------

_FRONT_ALIASES: dict[str, str] = {}


def _register_front(field_name: str, *names: str) -> None:
    for name in names:
        _FRONT_ALIASES[name.strip().lower()] = field_name


_register_front("title", "title", "name", "名称", "发明名称", "专利名称", "外观设计名称")
_register_front("applicant", "applicant", "申请人")
_register_front("inventors", "inventors", "inventor", "发明人", "设计人")
_register_front("applicant_address", "address", "applicant_address", "申请人地址")

#: 可以直接写在 frontmatter 或顶层数据里的正文字段。
#:
#: 这让 ``.yaml`` / ``.json`` 稿件既可以写成长正文，也可以拆成结构化字段，
#: 两种写法都能用。
_BODY_FIELDS: dict[str, str] = {}


def _register_body(field_name: str, *names: str) -> None:
    for name in names:
        _BODY_FIELDS[name.strip().lower()] = field_name


_register_body("abstract", "abstract", "摘要", "说明书摘要")
_register_body("technical_field", "technical_field", "技术领域")
_register_body("background", "background", "背景技术", "现有技术")
_register_body("problems", "problems", "要解决的技术问题", "技术问题")
_register_body("solution", "solution", "技术方案", "发明内容", "实用新型内容")
_register_body("effects", "effects", "有益效果", "技术效果")
_register_body("embodiments", "embodiments", "具体实施方式", "实施例")

#: frontmatter 里可直接给出附图列表的键名。
_DRAWING_KEYS = ("drawings", "附图", "附图说明", "figures")
#: frontmatter 里可直接给出简要说明的键名。
_BRIEF_KEYS = ("design_brief", "brief", "简要说明", "外观设计简要说明")


def _parse_drawings(raw) -> list[Drawing]:
    """把各种写法的附图列表归一化成 :class:`Drawing` 列表。

    支持三种写法：带图号的完整对象、只有说明文字的字符串、
    以及一整段「图1为……」的文本。
    """
    drawings: list[Drawing] = []

    if isinstance(raw, str):
        for number, caption in _extract_captions(raw):
            drawings.append(Drawing(number=number, caption=caption))
        return drawings

    if not isinstance(raw, (list, tuple)):
        return drawings

    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            drawings.append(
                Drawing(
                    number=int(item.get("number", index)),
                    caption=str(item.get("caption", item.get("说明", "")) or ""),
                    path=item.get("path") or item.get("file") or None,
                    is_abstract=bool(item.get("abstract", item.get("摘要附图", False))),
                )
            )
        else:
            drawings.append(Drawing(number=index, caption=str(item)))
    return drawings


def _parse_brief(raw) -> DesignBrief:
    """把简要说明的字典归一化成 :class:`DesignBrief`。"""
    if not isinstance(raw, dict):
        return DesignBrief()
    return DesignBrief(
        usage=str(raw.get("usage", raw.get("用途", "")) or ""),
        points=str(raw.get("points", raw.get("设计要点", "")) or ""),
        best_view=str(raw.get("best_view", raw.get("代表图", raw.get("最能表明设计要点的图片", ""))) or ""),
        omitted_views=str(raw.get("omitted_views", raw.get("省略视图", "")) or ""),
        color_protection=bool(raw.get("color_protection", raw.get("保护色彩", False))),
    )


def _apply_frontmatter(draft: PatentDraft, front: dict) -> int | None:
    """把 frontmatter 写进模型，返回 ``abstract_figure`` 指定的图号（如有）。

    键名刻意保持宽容：中英文、常见别名都接受。
    """
    abstract_figure_no: int | None = None

    for raw_key, value in front.items():
        raw_key_str = str(raw_key).strip()
        lowered = raw_key_str.lower()

        if lowered in ("type", "类型", "专利类型", "patent_type"):
            draft.patent_type = parse_patent_type(None if value is None else str(value))
            continue

        if lowered in ("abstract_figure", "摘要附图", "abstract_figure_number"):
            if value not in (None, "", 0, "0"):
                match = re.search(r"(\d+)", str(value))
                if match:
                    abstract_figure_no = int(match.group(1))
            continue

        if lowered in _DRAWING_KEYS:
            draft.drawings = _parse_drawings(value)
            continue

        if lowered in _BRIEF_KEYS:
            draft.design_brief = _parse_brief(value)
            continue

        field_name = _FRONT_ALIASES.get(lowered) or _BODY_FIELDS.get(lowered)
        if field_name is None:
            continue
        if field_name in ("technical_field", "background", "problems", "solution",
                          "effects", "embodiments", "abstract"):
            if value is not None and str(value).strip():
                setattr(draft, field_name, str(value).strip())
            continue

        if field_name == "inventors":
            if isinstance(value, (list, tuple)):
                draft.inventors = [str(v).strip() for v in value if str(v).strip()]
            else:
                draft.inventors = [
                    part.strip()
                    for part in re.split(r"[,，、;；/\s]+", str(value or ""))
                    if part.strip()
                ]
        else:
            setattr(draft, field_name, "" if value is None else str(value).strip())

    return abstract_figure_no


# --------------------------------------------------------------------------
# 收尾
# --------------------------------------------------------------------------

def _finalize(draft: PatentDraft) -> None:
    """解析收尾：补名称、做最基本的可用性检查。"""
    if not draft.title.strip():
        draft.title = _infer_title_from_claims(draft)
    if not draft.title.strip():
        draft.title = "（未命名）"
    if not draft.has_any_content():
        raise ParseError(
            "稿子里没有识别到任何可用的申请文件内容。请至少提供以下之一：\n"
            "  - `# 权利要求书` 章节\n"
            "  - `# 说明书` 下的 `## 技术领域` / `## 背景技术` / `## 发明内容` / `## 具体实施方式`\n"
            "  - `# 摘要` 章节\n"
            "  - 外观设计的 `## 用途` / `## 设计要点` 等条目\n"
            "也可以用 `【技术领域】` 这样的方括号标记章节。"
        )


def _infer_title_from_claims(draft: PatentDraft) -> str:
    """名称缺失时，从第一项独立权利要求里抠出主题名称。"""
    if not draft.claims:
        return ""
    match = re.search(r"一种(.+?)[，,]", draft.claims[0].text)
    return f"一种{match.group(1).strip()}" if match else ""


# --------------------------------------------------------------------------
# 其它输入格式
# --------------------------------------------------------------------------

def parse_structured(data: dict, source: str = "") -> PatentDraft:
    """从 ``.yaml`` / ``.json`` 的字典直接构造模型。

    著录项目、正文字段、附图、简要说明全部交由 :func:`_apply_frontmatter`
    统一处理——它同时服务 Markdown 稿件的 frontmatter，两处共用一套别名，
    避免「同一份数据因为入口不同而解析结果不同」。

    这里只单独处理权利要求：它需要分段成 :class:`Claim` 对象。
    """
    data = dict(data)

    description = data.pop("description", None) or data.pop("说明书", None)
    if isinstance(description, dict):
        for key, value in description.items():
            data.setdefault(key, value)

    claims_raw = data.pop("claims", None) or data.pop("权利要求书", None)
    if claims_raw is None:
        claims_raw = data.pop("权利要求", None)

    draft = PatentDraft(title="")
    _apply_frontmatter(draft, data)

    if claims_raw:
        if isinstance(claims_raw, str):
            draft.claims = parse_claims_block(claims_raw)
        else:
            draft.claims = [
                build_claim(
                    index,
                    str(item.get("text", item.get("内容", "")))
                    if isinstance(item, dict)
                    else str(item),
                )
                for index, item in enumerate(claims_raw, start=1)
            ]

    draft.source_path = source
    _finalize(draft)
    return draft


def load(path: str | Path) -> PatentDraft:
    """按扩展名分派，读取一份稿件。"""
    path = Path(path)
    if not path.exists():
        raise ParseError(f"稿件文件不存在：{path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        if yaml is None:
            raise ParseError("解析 .yaml 稿件需要 PyYAML，请先 pip install pyyaml。")
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ParseError("YAML 稿件的顶层必须是键值对。")
        return parse_structured(data, source=str(path))

    if suffix == ".json":
        return parse_structured(json.loads(text), source=str(path))

    return parse_markdown(text, source=str(path))


def loads(text: str, source: str = "<string>") -> PatentDraft:
    """从字符串解析，先试 JSON，失败再按 Markdown 处理。"""
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                return parse_structured(data, source=source)
        except json.JSONDecodeError:
            pass
    return parse_markdown(text, source=source)
