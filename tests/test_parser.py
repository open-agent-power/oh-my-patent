"""解析层与自检层的测试。

重点覆盖两类容易出错的地方：
  1. **宽容度**——用户粘贴的稿件格式五花八门，解析不能因为写法不同就丢内容。
  2. **法律规则**——自检的判据必须与《专利法实施细则》和《专利审查指南》
     一致，既不能漏（放过错误），也不能过严（把合法写法报成错误）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from oh_my_patent import parser
from oh_my_patent.lint import Severity, lint
from oh_my_patent.schema import PatentType, parse_claims_block, parse_patent_type
from oh_my_patent.spec import SectionKey


class PatentTypeTest(unittest.TestCase):
    def test_aliases(self):
        for raw, expected in (
            ("invention", PatentType.INVENTION),
            ("发明", PatentType.INVENTION),
            ("发明专利", PatentType.INVENTION),
            ("utility", PatentType.UTILITY),
            ("实用新型", PatentType.UTILITY),
            ("design", PatentType.DESIGN),
            ("外观设计", PatentType.DESIGN),
        ):
            with self.subTest(raw=raw):
                self.assertIs(parse_patent_type(raw), expected)

    def test_default_is_invention(self):
        self.assertIs(parse_patent_type(None), PatentType.INVENTION)

    def test_unknown_type_raises_with_hint(self):
        with self.assertRaises(ValueError) as ctx:
            parse_patent_type("商标")
        self.assertIn("invention", str(ctx.exception))


class ClaimParsingTest(unittest.TestCase):
    def test_sequential_numbering(self):
        claims = parse_claims_block(
            "1. 一种装置，其特征在于，包括壳体。\n"
            "2. 根据权利要求1所述的装置，其特征在于，所述壳体为金属壳。\n"
        )
        self.assertEqual([c.number for c in claims], [1, 2])
        self.assertTrue(claims[0].independent)
        self.assertFalse(claims[1].independent)

    def test_range_reference_expansion(self):
        """「权利要求1至3中任一项」要展开成 [1, 2, 3]。"""
        claims = parse_claims_block(
            "1. 一种方法，其特征在于，包括步骤A。\n"
            "2. 根据权利要求1所述的方法，其特征在于，步骤A包括A1。\n"
            "3. 根据权利要求1或2所述的方法，其特征在于，步骤A包括A2。\n"
            "4. 根据权利要求1至3中任一项所述的方法，其特征在于，还包括步骤B。\n"
        )
        self.assertEqual(claims[2].references, [1, 2])
        self.assertEqual(claims[3].references, [1, 2, 3])

    def test_multiline_claim_is_joined(self):
        """项内手工换行应被合并成一项，而不是切成多项。"""
        claims = parse_claims_block(
            "1. 一种装置，其特征在于，包括：\n"
            "壳体，其内部形成有容纳空间；\n"
            "以及设置在所述容纳空间内的电路板。\n"
            "2. 根据权利要求1所述的装置，其特征在于，所述壳体为金属壳。\n"
        )
        self.assertEqual(len(claims), 2)
        self.assertIn("容纳空间", claims[0].text)
        self.assertIn("电路板", claims[0].text)
        self.assertNotIn("\n", claims[0].text)

    def test_second_independent_claim_detected(self):
        """方法+装置的双独权写法必须被识别为两项独立权利要求。"""
        claims = parse_claims_block(
            "1. 一种数据采集方法，其特征在于，包括步骤A。\n"
            "2. 根据权利要求1所述的方法，其特征在于，步骤A包括A1。\n"
            "3. 一种数据采集装置，其特征在于，包括处理器与存储器。\n"
        )
        self.assertEqual([c.number for c in claims if c.independent], [1, 3])

    def test_renumbering_when_prefix_missing(self):
        """没有编号时按空行分段并补编号，保证法定编号规则成立。"""
        claims = parse_claims_block(
            "一种装置，其特征在于，包括壳体。\n"
            "\n"
            "一种应用如上的装置的方法，其特征在于，包括步骤A。\n"
        )
        self.assertEqual([c.number for c in claims], [1, 2])


class MarkdownParsingTest(unittest.TestCase):
    SOURCE = """---
title: 一种测试装置
type: invention
applicant: 测试公司
inventors: [张三, 李四]
---

# 权利要求书

1. 一种测试装置，其特征在于，包括壳体。
2. 根据权利要求1所述的测试装置，其特征在于，所述壳体为金属壳。

# 说明书

## 技术领域
本发明涉及测试装置技术领域。

## 背景技术
现有装置存在缺陷。

## 发明内容

### 要解决的技术问题
成本高。

### 技术方案
采用替代材料。

### 有益效果
成本下降三成。

## 附图说明
图1为本发明实施例提供的测试装置的结构示意图。

## 具体实施方式
本实施例中，壳体采用铝合金制成。

# 摘要
本发明公开一种测试装置。
"""

    def setUp(self):
        self.draft = parser.parse_markdown(self.SOURCE)

    def test_frontmatter(self):
        self.assertEqual(self.draft.title, "一种测试装置")
        self.assertEqual(self.draft.applicant, "测试公司")
        self.assertEqual(self.draft.inventors, ["张三", "李四"])
        self.assertIs(self.draft.patent_type, PatentType.INVENTION)

    def test_sections_split_correctly(self):
        """每个章节都要落到各自字段，不能互相覆盖。"""
        self.assertIn("测试装置技术领域", self.draft.technical_field)
        self.assertIn("存在缺陷", self.draft.background)
        self.assertEqual(self.draft.problems.strip(), "成本高。")
        self.assertEqual(self.draft.solution.strip(), "采用替代材料。")
        self.assertEqual(self.draft.effects.strip(), "成本下降三成。")
        self.assertIn("铝合金", self.draft.embodiments)

    def test_technical_field_not_overwritten_by_drawing_desc(self):
        """附图说明章节不得覆盖技术领域。

        这两个章节曾经共用一个字段，导致技术领域被附图说明顶掉。
        """
        self.assertNotIn("图1", self.draft.technical_field)

    def test_drawings_extracted_from_captions(self):
        self.assertEqual(len(self.draft.drawings), 1)
        self.assertEqual(self.draft.drawings[0].number, 1)
        self.assertIn("结构示意图", self.draft.drawings[0].caption)

    def test_abstract(self):
        self.assertIn("测试装置", self.draft.abstract)

    def test_summary_parts_and_legacy_field(self):
        """summary_parts 是有序三段；solution 字段保留兼容。"""
        labels = [label for label, _ in self.draft.summary_parts]
        self.assertEqual(labels, ["要解决的技术问题", "技术方案", "有益效果"])

    def test_sections_follow_legal_order(self):
        keys = [key for key, _ in self.draft.sections()]
        self.assertEqual(
            keys,
            [
                SectionKey.TECHNICAL_FIELD,
                SectionKey.BACKGROUND,
                SectionKey.SUMMARY,
                SectionKey.DRAWING_DESC,
                SectionKey.EMBODIMENTS,
            ],
        )

    def test_summary_is_structured(self):
        self.assertTrue(self.draft.summary_is_structured)


class LenientParsingTest(unittest.TestCase):
    """用户粘贴的稿子写法各异，解析必须宽容。"""

    def test_bracket_headings_from_pasted_word_text(self):
        """从 Word 粘出来的【技术领域】式章节标记要能识别。"""
        draft = parser.parse_markdown(
            "【技术领域】\n本发明涉及测试领域。\n\n"
            "【背景技术】\n现有技术存在缺陷。\n\n"
            "【发明内容】\n本发明解决上述问题。\n\n"
            "【具体实施方式】\n具体说明。\n"
        )
        self.assertIn("测试领域", draft.technical_field)
        self.assertIn("缺陷", draft.background)
        self.assertIn("具体说明", draft.embodiments)

    def test_bracket_heading_with_inline_body(self):
        """【技术领域】标题与正文写在同一行时，正文不能丢。"""
        draft = parser.parse_markdown("【技术领域】本发明涉及测试领域。\n")
        self.assertIn("测试领域", draft.technical_field)

    def test_numbered_headings(self):
        draft = parser.parse_markdown(
            "# 说明书\n\n一、技术领域\n本发明涉及测试领域。\n\n"
            "二、背景技术\n现有技术存在缺陷。\n"
        )
        self.assertIn("测试领域", draft.technical_field)
        self.assertIn("缺陷", draft.background)

    def test_encoding_headings(self):
        """带冒号的标题「技术领域：」也要识别。"""
        draft = parser.parse_markdown("## 技术领域：\n本发明涉及测试领域。\n")
        self.assertIn("测试领域", draft.technical_field)

    def test_unknown_section_is_kept_not_dropped(self):
        """无法归类的章节要保留在 extra_sections，不能静默丢弃。"""
        draft = parser.parse_markdown(
            "## 技术领域\n本发明涉及测试领域。\n\n"
            "## 补充说明\n这是一段额外的内容。\n"
        )
        self.assertTrue(
            any("额外的内容" in (s.body or "") for s in draft.extra_sections),
            draft.extra_sections,
        )

    def test_hash_inside_fence_is_not_a_heading(self):
        """代码围栏内的 # 不能被当成标题。"""
        draft = parser.parse_markdown(
            "## 具体实施方式\n\n```\n# 这不是标题\n## 也不是\n```\n\n正文内容。\n"
        )
        self.assertIn("正文内容", draft.embodiments)

    def test_raises_when_no_content(self):
        with self.assertRaises(parser.ParseError) as ctx:
            parser.parse_markdown("# 无关章节\n\n随便写点。\n")
        # 报错信息要给出可操作的提示
        self.assertIn("技术领域", str(ctx.exception))

    def test_invalid_yaml_frontmatter_gives_readable_error(self):
        with self.assertRaises(parser.ParseError) as ctx:
            parser.parse_markdown('---\ntitle: "未闭合\n---\n\n## 技术领域\n内容。\n')
        self.assertIn("YAML", str(ctx.exception))


class TitleInferenceTest(unittest.TestCase):
    def test_title_inferred_from_first_claim(self):
        draft = parser.parse_markdown(
            "# 权利要求书\n\n"
            "1. 一种智能水表数据采集方法，其特征在于，包括步骤A。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及数据采集。\n"
        )
        self.assertEqual(draft.title, "一种智能水表数据采集方法")


class StructuredInputTest(unittest.TestCase):
    def test_json_input(self):
        payload = {
            "title": "一种测试装置",
            "type": "utility",
            "claims": ["一种测试装置，其特征在于，包括壳体。"],
            "abstract": "本发明公开一种测试装置。",
            "technical_field": "本实用新型涉及测试装置技术领域。",
            "drawings": [{"number": 1, "caption": "图1为本实用新型的结构示意图。"}],
        }
        draft = parser.loads(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(draft.title, "一种测试装置")
        self.assertIs(draft.patent_type, PatentType.UTILITY)
        self.assertEqual(len(draft.claims), 1)
        self.assertEqual(len(draft.drawings), 1)

    def test_nested_description_dict(self):
        payload = {
            "title": "一种测试装置",
            "description": {
                "technical_field": "本发明涉及测试装置技术领域。",
                "embodiments": "具体实施例内容。",
            },
        }
        draft = parser.loads(json.dumps(payload, ensure_ascii=False))
        self.assertIn("测试装置技术领域", draft.technical_field)
        self.assertIn("具体实施例", draft.embodiments)

    def test_load_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "draft.md"
            path.write_text(
                "---\ntitle: 一种测试装置\ntype: invention\n---\n\n"
                "# 说明书\n\n## 技术领域\n本发明涉及测试装置技术领域。\n",
                encoding="utf-8",
            )
            draft = parser.load(path)
            self.assertEqual(draft.title, "一种测试装置")
            self.assertEqual(draft.source_path, str(path))


class LintTest(unittest.TestCase):
    """自检判据必须与法规一致。"""

    def _draft(self, body: str, front: str = "title: 一种测试装置\ntype: invention"):
        return parser.parse_markdown(f"---\n{front}\n---\n\n{body}")

    def test_clean_invention_passes(self):
        draft = self._draft(
            "# 权利要求书\n\n"
            "1. 一种测试装置，其特征在于，包括壳体。\n"
            "2. 根据权利要求1所述的测试装置，其特征在于，所述壳体为金属壳。\n\n"
            "# 说明书\n\n"
            "## 技术领域\n本发明涉及测试装置技术领域。\n\n"
            "## 背景技术\n现有装置存在缺陷。\n\n"
            "## 发明内容\n本发明提供一种测试装置。\n\n"
            "## 具体实施方式\n壳体采用铝合金制成。\n\n"
            "# 摘要\n本发明公开一种测试装置，结构简单，便于制造。\n"
        )
        report = lint(draft)
        self.assertTrue(report.ok, report.render())

    def test_title_too_long_is_error(self):
        draft = self._draft(
            "# 权利要求书\n\n1. 一种装置，其特征在于，包括壳体。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置。\n\n## 具体实施方式\n内容。\n\n"
            "# 摘要\n摘要内容。\n",
            front=f"title: {'一' * 45}\ntype: invention",
        )
        codes = {i.code for i in lint(draft).errors}
        self.assertIn("TITLE-002", codes)

    def test_forbidden_title_word(self):
        draft = self._draft(
            "# 权利要求书\n\n1. 一种装置，其特征在于，包括壳体。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置。\n\n## 具体实施方式\n内容。\n\n"
            "# 摘要\n摘要内容。\n",
            front="title: 一种改进的测试装置\ntype: invention",
        )
        codes = {i.code for i in lint(draft).errors}
        self.assertIn("TITLE-004", codes)

    def test_multiple_independent_claims_is_warning_not_error(self):
        """方法+装置的双独权是合法写法，只能提示复核单一性。

        国知局官方答复与《审查指南》第二部分第六章 2.2.1 都确认：
        符合单一性时可以撰写两项以上独立权利要求。
        """
        draft = self._draft(
            "# 权利要求书\n\n"
            "1. 一种数据采集方法，其特征在于，包括步骤A。\n"
            "2. 根据权利要求1所述的方法，其特征在于，步骤A包括A1。\n"
            "3. 一种数据采集装置，其特征在于，包括处理器。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及数据采集。\n\n"
            "## 具体实施方式\n如图1所示，内容。\n\n"
            "# 摘要\n本发明公开一种数据采集方法。\n"
        )
        report = lint(draft)
        hits = [i for i in report.issues if i.code == "CLAIM-004"]
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0].severity, Severity.WARNING)

    def test_missing_abstract_is_error(self):
        draft = self._draft(
            "# 权利要求书\n\n1. 一种装置，其特征在于，包括壳体。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置。\n\n## 具体实施方式\n内容。\n"
        )
        codes = {i.code for i in lint(draft).errors}
        self.assertIn("ABS-001", codes)

    def test_abstract_over_300_chars_is_error(self):
        draft = self._draft(
            "# 权利要求书\n\n1. 一种装置，其特征在于，包括壳体。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置。\n\n## 具体实施方式\n内容。\n\n"
            f"# 摘要\n{'本发明公开一种装置。' * 30}\n"
        )
        # 「本发明公开一种装置。」9 字 x 30 = 270 字，尚未超限
        self.assertNotIn("ABS-002", {i.code for i in lint(draft).errors})

        over = self._draft(
            "# 权利要求书\n\n1. 一种装置，其特征在于，包括壳体。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置。\n\n## 具体实施方式\n内容。\n\n"
            f"# 摘要\n{'本发明公开一种装置。' * 35}\n"
        )
        self.assertIn("ABS-002", {i.code for i in lint(over).errors})

    def test_claim_referencing_later_claim_is_error(self):
        """从属权利要求只能引用在前的权利要求。"""
        draft = self._draft(
            "# 权利要求书\n\n"
            "1. 一种装置，其特征在于，包括壳体。\n"
            "2. 根据权利要求3所述的装置，其特征在于，所述壳体为金属壳。\n"
            "3. 根据权利要求1所述的装置，其特征在于，还包括盖体。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置。\n\n## 具体实施方式\n内容。\n\n"
            "# 摘要\n摘要内容。\n"
        )
        codes = {i.code for i in lint(draft).errors}
        self.assertIn("CLAIM-007", codes)

    def test_utility_requires_drawings(self):
        """实用新型必须有附图，这是与发明最硬的一条差别。"""
        draft = self._draft(
            "# 权利要求书\n\n1. 一种测试装置，其特征在于，包括壳体。\n\n"
            "# 说明书\n\n## 技术领域\n本实用新型涉及测试装置。\n\n"
            "## 具体实施方式\n壳体采用铝合金制成。\n\n"
            "# 摘要\n本实用新型公开一种测试装置。\n",
            front="title: 一种测试装置\ntype: utility",
        )
        codes = {i.code for i in lint(draft).errors}
        self.assertIn("DESC-007", codes)

    def test_utility_method_claim_is_error(self):
        """实用新型只保护产品的形状构造，不能有方法权利要求。"""
        draft = self._draft(
            "# 权利要求书\n\n"
            "1. 一种数据采集方法，其特征在于，包括步骤A。\n\n"
            "# 说明书\n\n## 技术领域\n本实用新型涉及数据采集。\n\n"
            "## 具体实施方式\n如图1所示，内容。\n\n"
            "# 摘要\n本实用新型公开一种数据采集方法。\n",
            front="title: 一种数据采集方法\ntype: utility",
        )
        codes = {i.code for i in lint(draft).errors}
        self.assertIn("CLAIM-013", codes)

    def test_placeholder_is_error(self):
        """残留占位符必须在交付前拦住。"""
        draft = self._draft(
            "# 权利要求书\n\n1. 一种装置，其特征在于，包括壳体。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及待补充技术领域。\n\n"
            "## 具体实施方式\n内容。\n\n"
            "# 摘要\n摘要内容。\n"
        )
        codes = {i.code for i in lint(draft).errors}
        self.assertIn("TXT-001", codes)

    def test_unknown_figure_reference_is_error(self):
        """正文引用了不存在的图号要报错。"""
        draft = self._draft(
            "# 权利要求书\n\n1. 一种装置，其特征在于，包括壳体。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置。\n\n"
            "## 附图说明\n图1为本发明的结构示意图。\n\n"
            "## 具体实施方式\n如图2所示，内容。\n\n"
            "# 摘要\n摘要内容。\n"
        )
        codes = {i.code for i in lint(draft).errors}
        self.assertIn("DESC-005", codes)

    def test_uncertain_wording_in_claim_is_warning(self):
        draft = self._draft(
            "# 权利要求书\n\n"
            "1. 一种装置，其特征在于，包括壳体，所述壳体最好是金属壳。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置。\n\n## 具体实施方式\n内容。\n\n"
            "# 摘要\n摘要内容。\n"
        )
        codes = {i.code for i in lint(draft).issues}
        self.assertIn("CLAIM-008", codes)

    def test_report_serialises_to_json(self):
        draft = self._draft(
            "# 权利要求书\n\n1. 一种装置，其特征在于，包括壳体。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置。\n\n## 具体实施方式\n内容。\n\n"
            "# 摘要\n摘要内容。\n"
        )
        payload = json.loads(lint(draft).to_json())
        self.assertIn("issues", payload)
        self.assertIn("ok", payload)


class DesignPatentTest(unittest.TestCase):
    """外观设计的文书结构与其他两种完全不同。"""

    SOURCE = """---
title: 一种水杯
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

## 是否请求保护色彩
否
"""

    def test_brief_fields(self):
        draft = parser.parse_markdown(self.SOURCE)
        self.assertIs(draft.patent_type, PatentType.DESIGN)
        self.assertEqual(draft.design_brief.usage, "用于盛装饮用水。")
        self.assertEqual(draft.design_brief.points, "在于产品的形状。")
        self.assertEqual(draft.design_brief.best_view, "立体图")
        self.assertFalse(draft.design_brief.color_protection)

    def test_design_has_no_claims_or_description(self):
        self.assertFalse(PatentType.DESIGN.has_claims)
        self.assertFalse(PatentType.DESIGN.has_description)

    def test_abstract_figure_uses_explicit_mark(self):
        draft = parser.parse_markdown(self.SOURCE)
        self.assertEqual(draft.abstract_figure.number, 7)

    def test_brief_produces_legal_items(self):
        """简要说明要按法定条目编号输出。"""
        from oh_my_patent.render import DocxRenderer
        from docx import Document

        draft = parser.parse_markdown(self.SOURCE)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "design.docx"
            DocxRenderer(draft).save(path)
            text = "\n".join(p.text for p in Document(str(path)).paragraphs)
        self.assertIn("本外观设计产品的名称：一种水杯。", text)
        self.assertIn("本外观设计产品的用途：", text)
        self.assertIn("本外观设计的设计要点：", text)
        self.assertIn("最能表明设计要点的图片或照片：立体图。", text)


if __name__ == "__main__":
    unittest.main()
