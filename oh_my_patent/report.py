"""检查结果的公共类型。

单独成模块，是因为检查项已经分成几组（形式合规、AI 专门规则……），
各组都要产出同样结构的 :class:`Issue`。放在这里可以避免组与组之间
互相导入形成环。

这一层只回答「发现了什么问题、多严重、怎么改」，不关心
「怎么发现的」——那是各组检查自己的事。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum


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
    #: 怎么改。检查的价值很大程度上取决于这一项——只报错不给改法，
    #: 等于把问题原样丢回给使用者。
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
# 共享的文本工具
# --------------------------------------------------------------------------

def count_chars(text: str) -> int:
    """统计字数：忽略空白，汉字与标点各计一字。

    这是全部字数相关判据（摘要 300 字上限、名称 25 字上限等）统一使用的口径。

    之所以要显式约定：字数统计在不同软件、不同历史时期的口径并不统一，
    有的把段落符也算进去。这里取最保守的口径——精确统计可见字符，
    不含任何格式符。本地统计不超，就不会超。
    """
    return len(re.sub(r"\s", "", text))


def first_line(text: str, limit: int = 40) -> str:
    """取一小段摘要用于报错信息，让使用者能定位到具体位置。"""
    collapsed = re.sub(r"\s+", " ", text.strip())
    return collapsed[:limit] + ("…" if len(collapsed) > limit else "")


def snippet(text: str, needle: str, radius: int = 12) -> str:
    """截取 ``needle`` 在 ``text`` 中的上下文，用于报错信息。"""
    index = text.find(needle)
    if index < 0:
        return first_line(text)
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"
