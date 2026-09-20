"""外观设计简要说明的自检测试。

为什么单独一个文件：`lint.check_design()` 原先**零测试覆盖**，
同时它用着一套与全项目不一致的词码（`DES-USAGE` / `DES-POINTS` /
`DES-BEST_VIEW` 与 `DES-IMAGES` / `DES-PATH` 混用）。
统一为 `DES-001`~`DES-005` 之后，这里把行为钉住。

另设一道**命名约定守门测试**，防止将来新增检查项时又跑出别的写法。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from oh_my_patent import parser
from oh_my_patent.lint import Severity, check_design, lint

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 完整的简要说明，应当零 DES 告警。
COMPLETE = """---
title: 水杯
type: design
drawings:
  - {number: 1, caption: 主视图, path: 主视图.png}
  - {number: 7, caption: 立体图, path: 立体图.png, abstract: true}
---

# 外观设计简要说明

## 用途
用于盛装饮用水。

## 设计要点
在于产品的形状。

## 最能表明设计要点的图片
立体图
"""


def design_codes(source: str) -> set[str]:
    """取出一份稿件上命中的全部 DES-* 码。"""
    report = lint(parser.parse_markdown(source))
    return {i.code for i in report.issues if i.code.startswith("DES-")}


class DesignCheckTest(unittest.TestCase):
    def test_complete_brief_has_no_issues(self):
        self.assertEqual(design_codes(COMPLETE), set())

    def test_missing_usage(self):
        source = COMPLETE.replace("## 用途\n用于盛装饮用水。\n\n", "")
        self.assertIn("DES-001", design_codes(source))

    def test_missing_points(self):
        source = COMPLETE.replace("## 设计要点\n在于产品的形状。\n\n", "")
        self.assertIn("DES-002", design_codes(source))

    def test_missing_best_view(self):
        source = COMPLETE.replace("## 最能表明设计要点的图片\n立体图\n", "")
        self.assertIn("DES-003", design_codes(source))

    def test_no_drawings(self):
        source = COMPLETE[: COMPLETE.index("drawings:")].rstrip() + "\n---\n\n" + COMPLETE[
            COMPLETE.index("# 外观设计简要说明") :
        ]
        codes = design_codes(source)
        self.assertIn("DES-004", codes)
        # 没有图时不该再抱怨路径缺失，两者是互斥分支
        self.assertNotIn("DES-005", codes)

    def test_drawing_without_path(self):
        source = COMPLETE.replace(
            "  - {number: 1, caption: 主视图, path: 主视图.png}\n", "  - {number: 1, caption: 主视图}\n"
        )
        self.assertIn("DES-005", design_codes(source))

    def test_missing_items_are_errors_and_path_is_warning(self):
        """级别本身也是契约：缺条目是硬伤，缺图片文件路径只是提醒。"""
        source = COMPLETE.replace("## 用途\n用于盛装饮用水。\n\n", "").replace(
            "  - {number: 1, caption: 主视图, path: 主视图.png}\n", "  - {number: 1, caption: 主视图}\n"
        )
        by_code = {i.code: i for i in lint(parser.parse_markdown(source)).issues}
        self.assertIs(by_code["DES-001"].severity, Severity.ERROR)
        self.assertIs(by_code["DES-005"].severity, Severity.WARNING)


class DesignChecksAreScopedTest(unittest.TestCase):
    """适用性：DES-* 只该在外观设计稿件上出现。"""

    INVENTION = """---
title: 一种测试装置
type: invention
---

# 权利要求书

1. 一种测试装置，其特征在于，包括壳体。

# 说明书

## 技术领域
本发明涉及测试装置技术领域。

## 背景技术
现有装置存在缺陷。

## 发明内容
本发明提供一种测试装置。

## 具体实施方式
参照图1，本实施例包括壳体。
"""

    def test_invention_draft_yields_no_des_codes(self):
        self.assertEqual(design_codes(self.INVENTION), set())

    def test_direct_call_on_non_design_draft(self):
        """直接调用也要早退，不能只靠 lint() 的聚合。"""
        draft = parser.parse_markdown(self.INVENTION)
        self.assertEqual(check_design(draft), [])


class CheckCodeNamingGateTest(unittest.TestCase):
    """守门：检查码必须统一为 `前缀-三位数字`。

    这道测试的存在理由：本案刚把 `DES-USAGE` 这类词码统一掉。
    没有守门测试，下次加检查项很容易又写出一套自己的风格。
    """

    PATTERN = re.compile(r'^[A-Z]{2,7}-\d{3}$')

    def _codes_in(self, filename: str) -> set[str]:
        source = (REPO_ROOT / "oh_my_patent" / filename).read_text(encoding="utf-8")
        return set(re.findall(r'"([A-Z]{2,7}-[^"]*)"', source))

    def test_all_codes_follow_convention(self):
        for filename in ("lint.py", "lint_ai.py"):
            with self.subTest(module=filename):
                for code in self._codes_in(filename):
                    self.assertRegex(code, self.PATTERN, f"{filename} 里的 {code} 不符合命名约定")

    def test_design_codes_are_numeric(self):
        """专项钉住本案的改动点，防止回退成词码。"""
        for code in self._codes_in("lint.py"):
            if code.startswith("DES-"):
                self.assertRegex(code, r"^DES-\d{3}$")


if __name__ == "__main__":
    unittest.main()
