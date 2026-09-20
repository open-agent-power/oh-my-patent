"""把项目材料（Word / PowerPoint）读成 Agent 能用的 Markdown。

为什么要有这一层：用户在写交底书之前，手里通常已经有一堆现成材料——
立项报告、技术方案、评审 PPT、测试记录。它们大多是 .docx / .pptx。
Agent 读不了二进制，必须先把它们变成文本。

**为什么不用 mammoth 的 Markdown 输出直接了事**（这是本模块存在的全部理由）：

本机实测（2026-09-20，mammoth 1.12.2）表明，那条最省事的路径有两处**静默失真**：

1. **内嵌公式（OMML）被整段丢弃。** mammoth 只往 warnings 里塞一句
   ``An unrecognised element was ignored: ...oMath``——不说是第几处、丢在哪。
   实测一份含 ``E = ½mv²`` 的文档，转出来的行内公式位置**只剩一个空格**
   （``其中质量  单位为千克。``），读者完全看不出这里原本有个公式。
   技术方案里的公式往往就是发明的核心，这种丢失是致命的。

2. **Markdown writer 不认表格**，把每个单元格摊成一个独立段落。
   ``参数/含义/m/质量`` 变成四行文字，行列关系全没了。
   （它的 HTML writer 反而正确，说明问题只在 Markdown 这一层。）

所以本模块的做法是：

- 转换**之前**先把 ``m:oMath`` / ``m:oMathPara`` 替换成可识别的占位文本
  （``⟪公式1: E=12mv2⟫``），公式的位置因此得以保留，warnings 也随之清空；
- 走 mammoth 的 **HTML** 输出，再交给 markdownify 落 Markdown，
  表格结构得以还原，并顺手修掉 markdownify 的「空表头行」；
- 公式的**文本近似是退化的**（分式会摊平、上下标会掉），所以每一处公式
  都会产生一条 :class:`Notice`，由调用方决定怎么向用户交代。

一句话：**宁可给一个「此处有公式，但需要向用户核实」的显式标记，
也不要给一份看起来完整、其实缺了关键公式的文本。**

依赖是**可选**的：只有读 Office 材料才需要 mammoth / markdownify / python-pptx，
生成 .docx 的路径一行都不会碰它们。缺依赖时抛 :class:`MissingDependency`，
而不是让整个包 import 失败。
"""

from __future__ import annotations

import importlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

__all__ = [
    "MissingDependency",
    "IngestError",
    "Notice",
    "IngestResult",
    "docx_to_markdown",
    "pptx_to_markdown",
    "convert",
    "SUPPORTED_SUFFIXES",
]


# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

_MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

_MATH = f"{{{_MATH_NS}}}"
_W = f"{{{_W_NS}}}"
_A = f"{{{_A_NS}}}"

_DOCX_MAIN_PART = "word/document.xml"

#: 公式占位符的包围符号。刻意避开 ``[]``——那在 Markdown 里是链接语法，
#: 会被渲染器和下游解析器误读。``⟪⟫`` 罕见且不会被任何 Markdown 方言占用。
_PLACEHOLDER_OPEN = "⟪"
_PLACEHOLDER_CLOSE = "⟫"

#: 能直接处理的扩展名。
DOCX_SUFFIXES = frozenset({".docx", ".docm", ".dotx"})
PPTX_SUFFIXES = frozenset({".pptx", ".pptm", ".ppsx", ".potx"})
SUPPORTED_SUFFIXES = DOCX_SUFFIXES | PPTX_SUFFIXES

#: mammoth 默认的 style map 只认英文样式名（``Heading 1``），
#: 而中文 Word 里这些样式的名字是「标题 1」。补上中文名，否则
#: 一份全中文的立项报告转出来会**一个标题都不剩**，全变成普通段落。
_CJK_STYLE_MAP = """
p[style-name='标题'] => h1:fresh
p[style-name='标题 1'] => h1:fresh
p[style-name='标题 2'] => h2:fresh
p[style-name='标题 3'] => h3:fresh
p[style-name='标题 4'] => h4:fresh
p[style-name='标题 5'] => h5:fresh
p[style-name='标题 6'] => h6:fresh
p[style-name='副标题'] => h2:fresh
p[style-name='题注'] => p:fresh
r[style-name='引用'] => blockquote > p
"""


# --------------------------------------------------------------------------
# 结果类型
# --------------------------------------------------------------------------


class MissingDependency(RuntimeError):
    """读取 Office 材料所需的可选依赖没有安装。

    生成路径（``build`` / ``lint``）不需要这些库，所以这里抛异常，
    而不是在 import 期就让整个包挂掉。
    """


class IngestError(RuntimeError):
    """源文件本身有问题（不是 .docx / 损坏 / 打不开）。"""


@dataclass(frozen=True)
class Notice:
    """转换过程中的一条提示。

    用结构化字段而不是裸字符串，是为了让调用方能按 ``code`` 分类处理：
    比如 ``FORMULA_APPROXIMATED`` 必须转达给用户，而 ``IMAGE_SKIPPED``
    在「本来就没打算要图」的场景下可以忽略。
    """

    level: str  # "warning" | "info"
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - 便于调试打印
        return f"[{self.level}] {self.code}: {self.message}"


@dataclass
class IngestResult:
    """一次转换的产物。

    :param source: 被转换的源文件
    :param markdown: 转换出的 Markdown 正文
    :param notices: 过程中的提示，**调用方有责任查看**
    :param media_dir: 图片落盘目录；没有抽图时为 ``None``
    :param images: 已落盘的图片路径
    :param stats: 计数，便于在报告里写「本文档含 3 张图、5 处公式」
    """

    source: Path
    markdown: str
    notices: list[Notice] = field(default_factory=list)
    media_dir: Path | None = None
    images: list[Path] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def warnings(self) -> list[Notice]:
        return [n for n in self.notices if n.level == "warning"]

    @property
    def infos(self) -> list[Notice]:
        """非 warning 级的提示（``info``）。

        单独给一个属性，是为了让「哪些提示要显示」只有一处定义。
        最初 ``markdown_header`` 与 ``cli`` 各自过滤一遍、两处都只取
        ``warnings``，于是 ``SLIDE_TITLE_ONLY`` 这类「**有内容我没能给你**」
        的提示在两个出口同时消失——同一个错误写了两遍。
        收敛到这里之后，加一类新提示不会再漏掉一个出口。
        """
        return [n for n in self.notices if n.level != "warning"]

    def warning_codes(self) -> set[str]:
        return {n.code for n in self.warnings}


# --------------------------------------------------------------------------
# 可选依赖
# --------------------------------------------------------------------------


def _require(module_name: str, pip_name: str, purpose: str) -> Any:
    """惰性导入一个可选依赖，缺了就给人话。"""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - 依赖齐全时走不到
        raise MissingDependency(
            f"{purpose}需要 {pip_name}，但它没有安装。\n"
            f"  安装：pip install {pip_name}\n"
            f"  （生成 .docx 的路径不需要它，只有读取 Word / PPT 材料时才需要。）"
        ) from exc


# --------------------------------------------------------------------------
# 公式处理：把 OMML 变成占位文本
# --------------------------------------------------------------------------


def _shadowed_ids(root: Any, tag: str) -> set[int]:
    """收集 ``tag`` 元素及其全部后代的 ``id()``。

    用于在遍历时跳过公式子树的内部节点——否则 ``m:t`` 会被当成正文
    文本重复输出一遍。
    """
    skip: set[int] = set()
    for element in root.iter(tag):
        for descendant in element.iter():
            skip.add(id(descendant))
    return skip


def _math_text(element: Any) -> str:
    """把一处公式里所有 ``m:t`` 文本按文档序拼起来。

    这只是**可读近似**，不是等价转换：分式会被摊平成 ``12``（而不是 ``1/2``），
    上下标会掉层级，求和的上下限会混进主干。调用方必须把它当「线索」而非「内容」。
    """
    chunks: list[str] = []
    for node in element.iter(f"{_MATH}t"):
        if node.text:
            chunks.append(node.text)
    return "".join(chunks).strip()


def _blank_run(text: str) -> Any:
    """造一个 ``<w:r><w:t>text</w:t></w:r>``，用来顶替公式元素。"""
    from lxml import etree

    run = etree.Element(f"{_W}r")
    node = etree.SubElement(run, f"{_W}t")
    node.set(_XML_SPACE, "preserve")
    node.text = text
    return run


def _replace_omml(part_xml: bytes, counter: list[int]) -> tuple[bytes, int]:
    """把 ``word/document.xml`` 里的公式换成占位文本 run。

    :return: ``(改写后的 XML, 本次替换的数量)``

    顺序很重要：先处理 ``m:oMathPara``（块级，自身包含 ``m:oMath``），
    再处理剩下的 ``m:oMath``（行内）。若不先处理外层，内层的 ``m:oMath``
    会先被换掉，外层 ``oMathPara`` 就变成一个空壳。
    """
    from lxml import etree

    before = counter[0]
    root = etree.fromstring(part_xml)

    for tag in (f"{_MATH}oMathPara", f"{_MATH}oMath"):
        for element in list(root.iter(tag)):
            parent = element.getparent()
            if parent is None:
                continue
            # 块级公式的内层 oMath：外层已经处理掉了，这里跳过。
            if element.tag == f"{_MATH}oMath" and parent.tag == f"{_MATH}oMathPara":
                continue
            counter[0] += 1
            label = (
                f"{_PLACEHOLDER_OPEN}公式{counter[0]}: {_math_text(element)}"
                f"{_PLACEHOLDER_CLOSE}"
            )
            parent.replace(element, _blank_run(label))

    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    ), counter[0] - before


def _repack_with_patched_document(source: Path, counter: list[int]) -> io.BytesIO:
    """把 .docx 重新打包，其中 ``document.xml`` 已被公式占位改写。

    mammoth 接受文件对象；给它一个内存里改过的 zip，就不用先落盘临时文件。
    其余部件原样搬运——只动 ``document.xml``，别的部件碰都不碰。
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(source, "r") as src:
        if _DOCX_MAIN_PART not in set(src.namelist()):
            raise IngestError(
                f"{source.name} 里找不到 {_DOCX_MAIN_PART}，"
                "它可能不是真正的 .docx（旧版 .doc 改名而来？）。"
            )
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == _DOCX_MAIN_PART:
                    data, _ = _replace_omml(data, counter)
                dst.writestr(item, data)
    buffer.seek(0)
    return buffer


# --------------------------------------------------------------------------
# HTML → Markdown 的收尾
# --------------------------------------------------------------------------

_EMPTY_TABLE_ROW = re.compile(r"^\|(?:\s*\|)+$")
_SEPARATOR_ROW = re.compile(r"^\|[\s:\-|]+\|\s*$")


def _promote_first_table_row(text: str) -> str:
    """把 Markdown 表格里那个空表头行换成第一行数据。

    mammoth 输出的 ``<tr>`` 一律是 ``<td>``（没有 ``<th>``），markdownify
    只好在前面补一行空表头 + 分隔行，于是渲染出来是个空表头上面挂着数据。
    这里把「空行 + 分隔行 + 首个数据行」重排成「数据行 + 分隔行」。
    """
    lines = text.split("\n")
    out: list[str] = []
    index = 0
    while index < len(lines):
        window = lines[index : index + 3]
        is_empty_header = (
            len(window) == 3
            and _EMPTY_TABLE_ROW.match(window[0])
            and _SEPARATOR_ROW.match(window[1])
            and not _EMPTY_TABLE_ROW.match(window[2])
        )
        if is_empty_header:
            out.append(window[2])
            out.append(window[1])
            index += 3
            continue
        out.append(lines[index])
        index += 1
    return "\n".join(out)


def _tidy(markdown: str) -> str:
    """压掉多余空行、去掉行尾空格，并把表格表头扶正。"""
    text = _promote_first_table_row(markdown)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


# --------------------------------------------------------------------------
# 图片
# --------------------------------------------------------------------------


def _extension_for_content_type(content_type: str) -> str:
    subtype = (content_type or "").split("/")[-1].lower().strip()
    if not subtype or subtype == "octet-stream":
        return "bin"
    if subtype == "jpeg":
        return "jpg"
    return subtype[:12]


def _make_image_converter(
    media_dir: Path | None,
    link_base: Path,
    notices: list[Notice],
    images: list[Path],
    counter: list[int],
) -> Callable[[Any], dict[str, str]]:
    """构造 mammoth 的图片回调：落盘 + 返回 Markdown 能用的相对路径。"""

    def save_image(image: Any) -> dict[str, str]:
        counter[0] += 1
        if media_dir is None:
            notices.append(
                Notice(
                    "warning",
                    "IMAGE_SKIPPED",
                    f"文档中的第 {counter[0]} 张图片没有被导出，"
                    "正文里只留下了位置标记——需要看图时请回原文件。",
                )
            )
            return {"src": "", "alt": f"图片{counter[0]}（未导出）"}

        ext = _extension_for_content_type(getattr(image, "content_type", "") or "")
        filename = f"img_{counter[0]:04d}.{ext}"
        out_path = media_dir / filename
        try:
            with image.open() as handle:
                out_path.write_bytes(handle.read())
        except Exception as exc:  # pragma: no cover - 取决于坏图
            notices.append(
                Notice("warning", "IMAGE_FAILED", f"第 {counter[0]} 张图片导出失败：{exc}")
            )
            return {"src": "", "alt": ""}

        images.append(out_path)
        try:
            relative = out_path.relative_to(link_base).as_posix()
        except ValueError:
            relative = out_path.as_posix()
        alt = getattr(image, "alt_text", None) or f"图{counter[0]}"
        return {"src": relative, "alt": alt}

    return save_image


# --------------------------------------------------------------------------
# .docx
# --------------------------------------------------------------------------


def docx_to_markdown(
    source: str | Path,
    *,
    media_dir: str | Path | None = None,
    link_base: str | Path | None = None,
    extract_images: bool = True,
) -> IngestResult:
    """把 .docx 转成 Markdown。

    :param source: 源 .docx 路径
    :param media_dir: 图片落盘目录；省略时为 ``<源目录>/<源文件名>_media``
    :param link_base: Markdown 中图片相对路径的基准目录；省略时取 ``media_dir`` 的上级
    :param extract_images: 置 False 则完全不碰图片
    :raises MissingDependency: 缺 mammoth / markdownify
    :raises IngestError: 源文件不是可读的 .docx
    """
    mammoth = _require("mammoth", "mammoth", "把 Word 转成文本")
    markdownify_mod = _require("markdownify", "markdownify", "把 HTML 收尾成 Markdown")

    path = Path(source).expanduser()
    if not path.is_file():
        raise IngestError(f"文件不存在：{path}")
    if path.suffix.lower() not in DOCX_SUFFIXES:
        raise IngestError(
            f"{path.name} 不是 .docx（Office Open XML）。"
            "旧版 .doc 请先用 Word 另存为 .docx。"
        )

    notices: list[Notice] = []
    images: list[Path] = []
    image_counter = [0]

    if extract_images:
        resolved_media = (
            Path(media_dir).expanduser()
            if media_dir is not None
            else path.parent / f"{path.stem}_media"
        )
        resolved_media.mkdir(parents=True, exist_ok=True)
        base = Path(link_base).expanduser() if link_base is not None else resolved_media.parent
    else:
        resolved_media = None
        base = path.parent

    formula_counter = [0]
    patched = _repack_with_patched_document(path, formula_counter)

    # 无论抽不抽图**都要**挂 converter。不挂的话，mammoth 会退回默认行为，
    # 把每张图片转成 base64 data URI 直接内联进正文——一份带截图的材料
    # 会变成几 MB 的单行字符串，而且 `--no-images` 这个参数就名不副实了
    # （它承诺「不导出图片」，实际却把图片塞进了正文）。
    convert_options: dict[str, Any] = {
        "style_map": _CJK_STYLE_MAP,
        "convert_image": mammoth.images.img_element(
            _make_image_converter(resolved_media, base, notices, images, image_counter)
        ),
    }

    try:
        result = mammoth.convert_to_html(patched, **convert_options)
    except Exception as exc:
        raise IngestError(f"解析 {path.name} 失败：{exc}") from exc

    for message in result.messages:
        text = getattr(message, "message", str(message))
        level = getattr(message, "type", "warning")
        notices.append(
            Notice("warning" if level == "warning" else "info", "MAMMOTH", text)
        )

    body = markdownify_mod.markdownify(
        result.value or "", heading_style="ATX", bullets="-"
    )
    markdown = _tidy(body)

    if formula_counter[0]:
        notices.append(
            Notice(
                "warning",
                "FORMULA_APPROXIMATED",
                f"本文档含 {formula_counter[0]} 处内嵌公式，已就地转成"
                f"「{_PLACEHOLDER_OPEN}公式N: …{_PLACEHOLDER_CLOSE}」占位文本。"
                "**占位里的式子是退化的**：分式被摊平（1/2 会变成 12）、"
                "上下标会掉层级——它只能用来定位「这里有个公式」，不能当作原式照抄。"
                "凡涉及公式的技术特征，请向用户索取 LaTeX 或图片原式后再动笔。",
            )
        )

    stats = {
        "formulas": formula_counter[0],
        "images": len(images),
        "characters": len(markdown),
    }
    return IngestResult(
        source=path,
        markdown=markdown,
        notices=notices,
        media_dir=resolved_media,
        images=images,
        stats=stats,
    )


# --------------------------------------------------------------------------
# .pptx
# --------------------------------------------------------------------------


def _paragraph_text(paragraph: Any, counter: list[int]) -> str:
    """取一个 ``<a:p>`` 的文本，并把其中的公式换成占位符。

    不直接用 python-pptx 的 ``text_frame.text``——它只读 ``a:t``，
    幻灯片里的公式（``m:oMath``）会被无声跳过。
    """
    roots = list(paragraph.iter(f"{_MATH}oMath"))
    if not roots:
        return "".join(node.text or "" for node in paragraph.iter(f"{_A}t"))

    hidden = _shadowed_ids(paragraph, f"{_MATH}oMath")
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_MATH}oMath":
            counter[0] += 1
            parts.append(
                f"{_PLACEHOLDER_OPEN}公式{counter[0]}: {_math_text(node)}"
                f"{_PLACEHOLDER_CLOSE}"
            )
            continue
        if id(node) in hidden:
            continue
        if node.tag == f"{_A}t":
            parts.append(node.text or "")
        elif node.tag == f"{_A}br":
            parts.append("\n")
    return "".join(parts)


def _shape_kind(shape: Any) -> str:
    try:
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            return "picture"
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            return "group"
    except Exception:  # pragma: no cover - python-pptx 内部枚举异常
        pass
    if getattr(shape, "has_table", False):
        return "table"
    if getattr(shape, "has_text_frame", False):
        return "text"
    return "other"


def _is_title_placeholder(shape: Any) -> bool:
    """判断一个文本框是不是「标题」占位符。

    用来区分「这一页有正文」和「这一页只有个标题」——后者在真实 PPT 里
    通常是纯图形页（架构图、流程图），必须单独提示。
    """
    try:
        return bool(shape.is_placeholder) and shape.placeholder_format.idx == 0
    except (AttributeError, ValueError):  # pragma: no cover - 非占位符形状
        return False


def _table_to_markdown(table: Any) -> str:
    """把一个 python-pptx 表格转成**合法**的 Markdown 表格。

    注意这里**必须**补上 ``| --- |`` 分隔行：没有它，Markdown 渲染器
    不会把这段认成表格。上游同功能脚本正是漏了这一行（``pptx_to_md.py:52``），
    它输出的是「看起来像表格、实际渲染成一行竖线」的东西。
    """
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [
            (cell.text or "").strip().replace("\n", " ").replace("|", "\\|")
            for cell in row.cells
        ]
        rows.append(cells)
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    lines = ["| " + " | ".join(rows[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _walk_shapes(shapes: Iterable[Any]) -> Iterable[Any]:
    """深度优先摊平组合形状（组合里还能再套组合）。"""
    for shape in shapes:
        if _shape_kind(shape) == "group":
            yield from _walk_shapes(shape.shapes)
        else:
            yield shape


def pptx_to_markdown(
    source: str | Path,
    *,
    media_dir: str | Path | None = None,
    link_base: str | Path | None = None,
    extract_images: bool = True,
) -> IngestResult:
    """把 .pptx 按页转成 Markdown（每页一个 ``## 第 N 页``）。

    参数含义与 :func:`docx_to_markdown` 一致。
    """
    pptx_module = _require("pptx", "python-pptx", "读取 PowerPoint")
    path = Path(source).expanduser()
    if not path.is_file():
        raise IngestError(f"文件不存在：{path}")
    if path.suffix.lower() not in PPTX_SUFFIXES:
        raise IngestError(
            f"{path.name} 不是 .pptx（Office Open XML）。"
            "旧版 .ppt 请先用 PowerPoint 另存为 .pptx。"
        )

    notices: list[Notice] = []
    images: list[Path] = []

    if extract_images:
        resolved_media = (
            Path(media_dir).expanduser()
            if media_dir is not None
            else path.parent / f"{path.stem}_media"
        )
        resolved_media.mkdir(parents=True, exist_ok=True)
        base = Path(link_base).expanduser() if link_base is not None else resolved_media.parent
    else:
        resolved_media = None
        base = path.parent

    try:
        presentation = pptx_module.Presentation(str(path))
    except Exception as exc:
        raise IngestError(f"打不开 {path.name}：{exc}") from exc

    formula_counter = [0]
    image_counter = [0]
    lines: list[str] = [f"# {path.stem}", ""]
    slides_without_text = 0
    slides_title_only = 0

    for slide_number, slide in enumerate(presentation.slides, start=1):
        lines.append(f"## 第 {slide_number} 页")
        lines.append("")
        produced = 0
        # 只数「正文」形状（排除标题）。一页只有标题，往往意味着内容全在
        # 一张图里——而图是提取不出来的。
        content_shapes = 0

        for shape in _walk_shapes(slide.shapes):
            kind = _shape_kind(shape)

            if kind == "picture":
                image_counter[0] += 1
                if resolved_media is None:
                    notices.append(
                        Notice(
                            "warning",
                            "IMAGE_SKIPPED",
                            f"第 {slide_number} 页的图片没有导出（未指定图片目录）。",
                        )
                    )
                    continue
                try:
                    blob = shape.image.blob
                    ext = (shape.image.ext or "png").lower()
                    ext = "jpg" if ext == "jpeg" else ext
                    out_path = resolved_media / f"slide{slide_number:02d}_{image_counter[0]:04d}.{ext}"
                    out_path.write_bytes(blob)
                    images.append(out_path)
                    try:
                        relative = out_path.relative_to(base).as_posix()
                    except ValueError:
                        relative = out_path.as_posix()
                    lines.append(f"![幻灯片 {slide_number} 图 {image_counter[0]}]({relative})")
                    lines.append("")
                    produced += 1
                    content_shapes += 1
                except Exception as exc:  # pragma: no cover - 取决于坏图
                    notices.append(
                        Notice(
                            "warning",
                            "IMAGE_FAILED",
                            f"第 {slide_number} 页图片导出失败：{exc}",
                        )
                    )
                continue

            if kind == "table":
                block = _table_to_markdown(shape.table)
                if block:
                    lines.append(block)
                    lines.append("")
                    produced += 1
                    content_shapes += 1
                continue

            if kind == "text":
                # 走 XML 而不是 shape.text_frame.text，公式才不会丢。
                chunks: list[str] = []
                for paragraph in shape.text_frame._txBody.iter(f"{_A}p"):
                    text = _paragraph_text(paragraph, formula_counter).strip()
                    if text:
                        chunks.append(text)
                if chunks:
                    lines.extend(chunks)
                    lines.append("")
                    produced += 1
                    if not _is_title_placeholder(shape):
                        content_shapes += 1

        if not produced:
            slides_without_text += 1
            notices.append(
                Notice(
                    "info",
                    "SLIDE_EMPTY",
                    f"第 {slide_number} 页没有提取到文本或表格"
                    "——它可能是纯图形（架构图、流程图）或图片，"
                    "这类内容必须回头看原文件，不要凭页码猜。",
                )
            )
        elif content_shapes == 0:
            # 这一页有标题、却没别的正文。真实评审 PPT 里，这种页面
            # 十有八九把全部内容画成了一张架构图——图上没有可提取的文字，
            # 转出来就只剩一个标题。不提示的话，Agent 会认为「这页没内容」。
            slides_title_only += 1
            notices.append(
                Notice(
                    "info",
                    "SLIDE_TITLE_ONLY",
                    f"第 {slide_number} 页只有标题、没有正文"
                    "——这类页面通常是整页的图形（架构图、流程图、示意图），"
                    "图上的文字提取不出来。请回看原文件确认这页画了什么。",
                )
            )

        try:
            notes_frame = slide.notes_slide.notes_text_frame
            notes = (notes_frame.text or "").strip() if notes_frame is not None else ""
        except (AttributeError, ValueError):
            notes = ""
        if notes:
            lines.append(f"**第 {slide_number} 页备注**：")
            lines.append("")
            lines.append(notes)
            lines.append("")

    if formula_counter[0]:
        notices.append(
            Notice(
                "warning",
                "FORMULA_APPROXIMATED",
                f"演示文稿含 {formula_counter[0]} 处内嵌公式，已就地转成占位文本；"
                "占位里的式子是**退化**的（分式摊平、上下标掉层级），"
                "涉及时请向用户索取原式。",
            )
        )

    markdown = _tidy("\n".join(lines))
    stats = {
        "slides": len(presentation.slides),
        "slides_without_text": slides_without_text,
        "slides_title_only": slides_title_only,
        "formulas": formula_counter[0],
        "images": len(images),
        "characters": len(markdown),
    }
    return IngestResult(
        source=path,
        markdown=markdown,
        notices=notices,
        media_dir=resolved_media,
        images=images,
        stats=stats,
    )


# --------------------------------------------------------------------------
# 分派
# --------------------------------------------------------------------------


def convert(
    source: str | Path,
    *,
    media_dir: str | Path | None = None,
    link_base: str | Path | None = None,
    extract_images: bool = True,
) -> IngestResult:
    """按扩展名挑合适的转换器。"""
    path = Path(source).expanduser()
    suffix = path.suffix.lower()
    if suffix in DOCX_SUFFIXES:
        return docx_to_markdown(
            path,
            media_dir=media_dir,
            link_base=link_base,
            extract_images=extract_images,
        )
    if suffix in PPTX_SUFFIXES:
        return pptx_to_markdown(
            path,
            media_dir=media_dir,
            link_base=link_base,
            extract_images=extract_images,
        )
    if suffix == ".doc":
        raise IngestError(
            f"{path.name} 是旧版 .doc 格式，本工具读不了。"
            "请让用户用 Word 另存为 .docx，或先转成 Markdown / 纯文本。"
        )
    if suffix == ".ppt":
        raise IngestError(
            f"{path.name} 是旧版 .ppt 格式，本工具读不了。"
            "请让用户用 PowerPoint 另存为 .pptx。"
        )
    raise IngestError(
        f"不支持的类型 {suffix or '（无扩展名）'}。"
        f"目前能读：{'、'.join(sorted(SUPPORTED_SUFFIXES))}。"
    )


# --------------------------------------------------------------------------
# 给人看 / 给 Agent 看的输出
# --------------------------------------------------------------------------


def format_notices(result: IngestResult) -> str:
    """把提示排成人能读的多行文本（给终端用）。"""
    if not result.notices:
        return "转换完成，没有需要提醒的地方。"
    lines = [f"共 {len(result.notices)} 条提示："]
    for notice in result.notices:
        lines.append(f"  [{notice.level}] {notice.code}")
        lines.append(f"      {notice.message}")
    return "\n".join(lines)


def markdown_header(result: IngestResult) -> str:
    """生成写进 Markdown 文件顶部的提示注记。

    **为什么要把提示写进正文而不仅是终端**：读这份 Markdown 的是 Agent，
    它通常只 Read 文件、看不到转换时的 stderr。提示只打在终端上，
    等于没打——Agent 会以为手上是一份完整的文本，然后在缺了公式的
    技术方案上写权利要求。

    **为什么 info 级也必须写**：``warnings`` 只覆盖「输出可能不可靠」，
    而 ``SLIDE_TITLE_ONLY`` / ``SLIDE_EMPTY`` 这类 info 说的是
    「**有内容我没能给你**」。实测一份 PPT 的第 4 页只剩「系统架构」四个字，
    Agent 读到的就是一页没有内容的东西，绝不会想到它原本是整张架构图。
    对只有 Read 权限的 Agent 而言，「我没读到」和「材料里没有」必须能被
    区分开——这正是本模块存在的理由，漏掉 info 级就等于漏掉一半。
    所以这里按级别分组，列出**全部**提示。
    """
    stats = result.stats
    summary = "、".join(
        f"{key} {value}" for key, value in stats.items() if isinstance(value, int)
    )
    lines = [
        "<!--",
        f"  本文件由 oh-my-patent 从 {result.source.name} 自动转换，请勿手改。",
        f"  源文件：{result.source}",
        f"  统计：{summary}",
    ]
    warnings = result.warnings
    infos = result.infos
    if warnings:
        lines.append("")
        lines.append("  ⚠ 转换告警（读这份文件前务必先看）：")
        for notice in warnings:
            lines.append(f"    - {notice.code}：{notice.message}")
    if infos:
        lines.append("")
        lines.append("  · 其它提示（同样影响你对这份材料的理解）：")
        for notice in infos:
            lines.append(f"    - {notice.code}：{notice.message}")
    lines.append("-->")
    return "\n".join(lines) + "\n\n"

