"""AI 专门检查与附图标记检查的测试。

这个文件的重心有两个，缺一不可：

  1. **该报的要报**——新指南的两道门槛（充分公开、伦理合规）必须真的能拦住。
  2. **不该报的不能报**——静态检查最怕误报。一条检查只要偶尔胡说，
     使用者就会整体不信任它。因此这里专门构造了「看似命中、实则合规」
     的稿件来验证不误报。
"""

from __future__ import annotations

import unittest

from oh_my_patent.lint import ALL_CHECKS, lint
from oh_my_patent.parser import parse_markdown
from oh_my_patent.report import Severity


def make(body: str, front: str = "title: 一种测试方法\ntype: invention"):
    """拼一份稿件，正文由调用方给出。"""
    return parse_markdown(f"---\n{front}\n---\n\n{body}")


def codes(draft, prefix: str | None = None) -> set[str]:
    found = {i.code for i in lint(draft).issues}
    return {c for c in found if prefix is None or c.startswith(prefix)} if prefix else found


def issue_of(draft, code: str):
    for item in lint(draft).issues:
        if item.code == code:
            return item
    return None


def base(body: str, front: str = "title: 一种测试方法\ntype: invention"):
    """补上必需章节，让稿件能通过基础形式检查，从而隔离出 AI 专项结论。"""
    return make(
        "# 权利要求书\n\n"
        "1. 一种测试方法，其特征在于，包括步骤A。\n"
        "2. 根据权利要求1所述的测试方法，其特征在于，步骤A包括A1。\n\n"
        "# 说明书\n\n"
        "## 技术领域\n本发明涉及测试方法技术领域。\n\n"
        "## 背景技术\n现有方法存在缺陷。\n\n"
        f"## 发明内容\n{body}\n\n"
        "## 具体实施方式\n实施细节。\n\n"
        "# 摘要\n本发明公开一种测试方法。\n",
        front=front,
    )


class AiDisclosureTest(unittest.TestCase):
    """《专利审查指南》第二部分第九章 6.3.1 的充分公开要求。"""

    def test_non_ai_draft_triggers_nothing(self):
        """不涉及 AI 的稿件不应产生任何 AI 专项问题。

        这是最基本的一条：一个机械结构专利不该被 AI 规则打扰。
        """
        draft = base("本发明提供一种测试方法，通过改变连接顺序解决问题。")
        self.assertEqual(codes(draft, "AI-"), set())
        self.assertEqual(codes(draft, "ETH-"), set())

    def test_claim_mentions_ai_but_description_silent(self):
        """权利要求写了神经网络、说明书一个字没提 → 得不到说明书支持。"""
        draft = parse_markdown(
            "---\ntitle: 一种图像识别方法\ntype: invention\n---\n\n"
            "# 权利要求书\n\n"
            "1. 一种图像识别方法，其特征在于，将图像输入卷积神经网络得到分类结果。\n\n"
            "# 说明书\n\n"
            "## 技术领域\n本发明涉及图像识别技术领域。\n\n"
            "## 背景技术\n现有方法准确率低。\n\n"
            "## 发明内容\n本发明能够提高识别准确率。\n\n"
            "## 具体实施方式\n本实施例中采集图像并进行识别处理。\n\n"
            "# 摘要\n本发明公开一种图像识别方法。\n"
        )
        found = codes(draft, "AI-")
        self.assertIn("AI-001", found)
        self.assertIs(issue_of(draft, "AI-001").severity, Severity.ERROR)

    def test_training_case_requires_model_structure(self):
        """涉及模型构建／训练，但没写模块层级 → ERROR。"""
        draft = base(
            "本发明提供一种分类方法，构建卷积神经网络并对训练样本进行训练，"
            "以提高分类准确率。"
        )
        self.assertIn("AI-002", codes(draft, "AI-"))

    def test_structure_present_clears_ai_002(self):
        """写明了层级与连接关系后，AI-002 应当消失。"""
        draft = base(
            "本发明提供一种分类方法。具体地，构建一个编码器，"
            "所述编码器由四层卷积层与两层池化层交替连接而成，"
            "输入层接收图像，输出层经全连接层输出分类结果。"
            "训练时采用交叉熵损失函数，优化器为 Adam，学习率取 0.001，"
            "迭代 200 个轮次。输入数据为归一化后的图像张量，"
            "输出数据为类别概率向量。"
        )
        found = codes(draft, "AI-")
        self.assertNotIn("AI-002", found)
        self.assertNotIn("AI-003", found)
        self.assertNotIn("AI-004", found)

    def test_training_without_details_warns(self):
        """提到训练但没有任何训练细节 → WARNING。"""
        draft = base(
            "本发明提供一种方法，模型包含卷积层与池化层依次连接，"
            "并对模型进行训练后投入使用。"
        )
        self.assertIn("AI-003", codes(draft, "AI-"))
        self.assertIs(issue_of(draft, "AI-003").severity, Severity.WARNING)

    def test_missing_input_output_warns(self):
        """没有写明输入输出数据 → AI-004。"""
        draft = base(
            "本发明提供一种方法，模型包含卷积层与池化层依次连接。"
        )
        self.assertIn("AI-004", codes(draft, "AI-"))

    def test_blackbox_phrasing_warns(self):
        """黑箱式表述要被点出来。"""
        draft = base(
            "本发明提供一种方法，模型包含卷积层与池化层依次连接。"
            "具体算法不作限定，本领域技术人员可以自行选择。"
        )
        self.assertIn("AI-005", codes(draft, "AI-"))

    def test_effect_only_phrasing_warns(self):
        """只给效果承诺、不讲手段的表述要被点出来。"""
        draft = base(
            "本发明提供一种方法，采用神经网络提高识别准确率。"
            "模型包含卷积层与池化层依次连接。"
        )
        self.assertIn("AI-006", codes(draft, "AI-"))

    def test_ai_checks_only_read_description_not_claims(self):
        """AI-001 的判断依据必须是说明书，不能把权利要求算进去。

        若把权利要求也算作说明书内容，「权利要求写了、说明书没写」
        这种典型缺陷就永远查不出来。
        """
        draft = parse_markdown(
            "---\ntitle: 一种方法\ntype: invention\n---\n\n"
            "# 权利要求书\n\n"
            "1. 一种方法，其特征在于，使用大语言模型生成答案。\n\n"
            "# 说明书\n\n"
            "## 技术领域\n本发明涉及文本处理技术领域。\n\n"
            "## 具体实施方式\n接收请求并返回处理结果。\n\n"
            "# 摘要\n本发明公开一种方法。\n"
        )
        self.assertIn("AI-001", codes(draft, "AI-"))


class AiEthicsTest(unittest.TestCase):
    """专利法第 5 条第 1 款与指南新增第 6.1.1 节。"""

    def test_attribute_based_decision_is_error(self):
        """以性别、年龄作为决策依据 → ERROR（指南新增审查示例的正面命中）。"""
        draft = base(
            "本发明提供一种碰撞保护决策方法，根据行人的性别与年龄确定被保护对象，"
            "并据此控制安全气囊的展开策略。"
        )
        self.assertIn("ETH-001", codes(draft, "ETH-"))
        self.assertIs(issue_of(draft, "ETH-001").severity, Severity.ERROR)

    def test_sensitive_data_without_compliance_warns(self):
        """处理人脸数据但没作合法性声明 → WARNING。"""
        draft = base(
            "本发明提供一种识别方法，采集用户的人脸图像作为模型输入，"
            "模型包含卷积层与池化层依次连接。"
        )
        self.assertIn("ETH-002", codes(draft, "ETH-"))

    def test_sensitive_data_with_compliance_clears_warning(self):
        """声明了数据合法性之后，ETH-002 应当消失。"""
        draft = base(
            "本发明提供一种识别方法，所用样本均经当事人明示同意并作去标识化处理，"
            "符合个人信息保护法的相关规定。采集人脸图像作为模型输入，"
            "模型包含卷积层与池化层依次连接。"
        )
        self.assertNotIn("ETH-002", codes(draft, "ETH-"))

    def test_ethics_violation_does_not_depend_on_ai(self):
        """伦理检查不应被「是否涉及 AI」限制。

        以年龄决定人身权益的方案，无论有没有用模型都是问题。
        """
        draft = base(
            "本发明提供一种排序方法，根据用户的年龄确定服务优先级，"
            "并按照所述优先级分配资源。"
        )
        self.assertIn("ETH-001", codes(draft, "ETH-"))


class ReferenceNumeralTest(unittest.TestCase):
    """《专利法实施细则》第 21 条的附图标记一致性。"""

    def test_numeral_without_drawings_is_error(self):
        draft = base(
            "本发明提供一种装置，包括壳体1与设置于所述壳体1内部的电路板2，"
            "所述电路板2上焊接有芯片3。"
        )
        self.assertIn("REF-001", codes(draft, "REF-"))
        self.assertIs(issue_of(draft, "REF-001").severity, Severity.ERROR)

    def test_numeral_with_drawings_is_clean(self):
        """有附图时不应误报 REF-001。"""
        draft = parse_markdown(
            "---\ntitle: 一种装置\ntype: invention\n"
            "drawings:\n  - {number: 1, caption: 图1为本发明的结构示意图。}\n---\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置技术领域。\n\n"
            "## 具体实施方式\n如图1所示，装置包括壳体1与电路板2。\n\n"
            "# 摘要\n本发明公开一种装置。\n"
        )
        self.assertNotIn("REF-001", codes(draft, "REF-"))

    def test_measurements_are_not_mistaken_for_numerals(self):
        """量值不能被当成附图标记——误报会让整条检查失去可信度。

        刻意**不写空格**：中文稿件里「加热3分钟」通常紧挨着写，
        靠空格侥幸通过不算数。
        """
        draft = base(
            "本发明提供一种方法，其中加热3分钟，温度200度，投料量5千克，"
            "重复4次操作，部件间距离2毫米，共设置6个卡扣，用时不超过10秒。"
        )
        self.assertEqual(codes(draft, "REF-"), set())

    def test_claim_reference_range_is_not_a_numeral(self):
        """「权利要求1至5中任一项」里的 1 和 5 都不是附图标记。

        这是修过的一个真 bug：非贪婪正则从词中间起匹配，把「至5」
        切成了「至」+「5」，于是误报「权利要求引用了标记5」。
        """
        draft = base(
            "本发明提供一种方法，如权利要求1至5中任一项所述的方法。"
        )
        self.assertEqual(codes(draft, "REF-"), set())

    def test_figure_caption_numbers_are_not_numerals(self):
        """「图1」「实施例2」里的数字不是附图标记。"""
        draft = base(
            "本发明提供一种方法，图1展示了整体流程，实施例2给出具体参数，"
            "与对比例3相比效果更优。"
        )
        self.assertEqual(codes(draft, "REF-"), set())

    def test_claim_numeral_missing_from_description_is_error(self):
        """权利要求引用了说明书没有的标记 → ERROR。"""
        draft = parse_markdown(
            "---\ntitle: 一种装置\ntype: invention\n"
            "drawings:\n  - {number: 1, caption: 图1为本发明的结构示意图。}\n---\n\n"
            "# 权利要求书\n\n"
            "1. 一种装置，其特征在于，包括壳体1和盖板5。\n\n"
            "# 说明书\n\n## 技术领域\n本发明涉及装置技术领域。\n\n"
            "## 具体实施方式\n如图1所示，装置包括壳体1。\n\n"
            "# 摘要\n本发明公开一种装置。\n"
        )
        self.assertIn("REF-003", codes(draft, "REF-"))

    def test_design_patent_skips_numeral_check(self):
        """外观设计的图没有附图标记，不应产生 REF 类问题。"""
        draft = parse_markdown(
            "---\ntitle: 一种水杯\ntype: design\n"
            "drawings:\n  - {number: 1, caption: 主视图, path: 主视图.png}\n---\n\n"
            "# 外观设计简要说明\n\n## 用途\n用于盛装饮用水。\n\n"
            "## 设计要点\n在于产品的形状。\n\n## 最能表明设计要点的图片\n主视图\n"
        )
        # 简要说明里「图」相关表述不该被当成附图标记
        self.assertNotIn("REF-001", codes(draft, "REF-"))


class CheckRegistryTest(unittest.TestCase):
    """检查注册表自身的健全性。"""

    def test_all_checks_are_callable_and_uniquely_coded(self):
        draft = base("本发明提供一种测试方法。")
        seen: set[str] = set()
        for check in ALL_CHECKS:
            result = check(draft)
            self.assertIsInstance(result, list)
            for item in result:
                self.assertNotIn(
                    item.code, seen, f"检查代码重复：{item.code}"
                )
                seen.add(item.code)

    def test_every_issue_carries_a_hint(self):
        """每条问题都要给出改法。

        只报错不给改法，等于把问题原样丢回给使用者——这是检查工具的
        主要失败模式之一。
        """
        draft = parse_markdown(
            "---\ntitle: 一种待补充的装置\ntype: utility\n---\n\n"
            "# 权利要求书\n\n"
            "1. 一种数据采集方法，其特征在于，最好是采用神经网络，"
            "引用了图3和壳体9，其中根据用户的年龄确定优先级。\n\n"
            "# 说明书\n\n"
            "## 技术领域\n本实用新型涉及待补充技术领域。\n\n"
            "## 具体实施方式\n采用神经网络提高准确率，具体算法不作限定。\n"
        )
        report = lint(draft)
        self.assertTrue(report.errors, "构造的稿件应当触发错误")
        for item in report.issues:
            with self.subTest(code=item.code):
                self.assertTrue(item.hint.strip(), f"{item.code} 没有给出改法")


class ExamplesTest(unittest.TestCase):
    """examples/ 下的每份示例都必须干净通过自检。

    这条守卫的价值在于挡住"新增检查后误报既有示例"的回归。
    本次开发中它已经拦下两次：REF-002 把「权利要求1至5」拆出了假标记，
    AI-004 把智能水表那个非 AI 示例当成了算法申请。
    """

    #: 允许保留的提示代码。这里的取舍标准是：该代码是否指向**缺陷**。
    #:
    #: - ``CLAIM-004`` 双独权的单一性复核提示。方法+装置属于指南允许的
    #:   六种组合之一，属合法写法的正常提醒。
    #: - ``ABS-003`` 「摘要已逼近 300 字上限」。288 字完全合规，
    #:   这只是距离上限较近的顾问性提示，不是缺陷。
    #:
    #: 其余代码一旦出现在示例上，就说明检查误报了，测试应当失败。
    ALLOWED = {"CLAIM-004", "ABS-003"}

    def test_all_examples_lint_clean(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "examples"
        files = sorted(root.glob("*.md"))
        self.assertTrue(files, "examples 目录下应当有示例稿件")

        for path in files:
            with self.subTest(example=path.name):
                draft = parse_markdown(path.read_text(encoding="utf-8"))
                report = lint(draft)
                unexpected = [
                    i for i in report.issues if i.code not in self.ALLOWED
                ]
                self.assertEqual(
                    unexpected,
                    [],
                    f"{path.name} 出现预期外的问题：\n"
                    + "\n".join(i.render() for i in unexpected),
                )

    def test_ai_example_triggers_no_ai_issues(self):
        """AI 示例是按新指南的撰写要求写的，不该被 AI 检查挑出毛病。

        这份示例刻意写全了模型层级、连接关系、训练步骤与参数、
        输入输出数据——正是《审查指南》6.3.1 要求的四样东西。
        """
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "examples"
        path = root / "ai-method-example.md"
        self.assertTrue(path.exists(), "AI 示例稿件应当存在")

        draft = parse_markdown(path.read_text(encoding="utf-8"))
        ai_codes = codes(draft, "AI-")
        self.assertEqual(ai_codes, set(), f"AI 示例不该触发：{ai_codes}")


if __name__ == "__main__":
    unittest.main()
