# 同类方案调查（2026-09-20）

> 目的：在 P1 开工前做一轮市场调查，找出**值得借鉴的现成方案**与**可以不必自研的轮子**。
> 与 `refactor-plan.md` / `absorption-plan.md` 配套——那两份讲怎么重构、吸收什么，这份讲
> 「外面已经有什么、哪些不必自己做」。
>
> **可信度分级**：本文每条结论都标了来源。
> `[实测]` = 本机跑过；`[API]` = 从官方接口取的真实数据；`[检索]` = 网页检索所得，未在本机验证。

## 1. 结论摘要

| 能力点 | 该不该自研 | 采用什么 | 依据 |
| --- | --- | --- | --- |
| LaTeX → OMML 公式 | **不自研** | `latex2mathml` + `mathml2omml-as`（均 MIT，纯 Python） | `[实测]` D4 |
| docx → Markdown | **不自研** | `mammoth`（BSD-2） | `[实测]` 可装可用 |
| pptx → 文本 | **不自研** | `python-pptx`（MIT） | `[实测]` 可装可用 |
| mermaid → PNG | **必须自研** | 无纯 Python 离线方案：Node + `mmdc` + Chrome | `[检索]` 已核实无替代 |
| OOXML 合法性校验 | **必须自研** | 官方 XSD 实测**不可用**，保留我们的拆 zip 方案 | `[实测]` 见 §3 |
| 中国专利检索数据源 | **部分自研** | EPO OPS 为主；**申请号校验位**离线自研 | `[检索]` |
| 中文 DOCX 排版 | **必须自研** | 无现成库解决 WPS/Office 差异；`docxtpl` 有许可问题 | `[检索]` |

**一句话**：解析类（读文档）与公式转换类的轮子已经很好，直接拿来用；
**生成类（写出 WPS/Office 双适配的 docx）没有任何现成轮子**——这正是本仓库的护城河。

## 2. 库层结论明细

### 2.1 公式链（已确认，维持 D4 结论）

| 库 | 版本 | 许可 | 状态 |
| --- | --- | --- | --- |
| `latex2mathml` | 3.81.1（2026-09-07） | MIT | 活跃，纯 Python |
| `mathml2omml-as` | 0.1.0（2025-06-03） | MIT | 版本少但可用，纯 Python |
| `math2docx` | 3.1.0（2026-04-08） | MIT | = 上述两步的 25 行封装 |

**没有更好的替代。** `pandoc` 质量最高但为系统级依赖且不继承参考件字体会导致字体回退，
已排除。**维持 D4：用库链，不自研，不用 pandoc。**

### 2.2 文档解析

| 库 | 许可 | 结论 |
| --- | --- | --- |
| `mammoth` 1.12.2 | BSD-2 | 主用。**但会丢弃 OMML 公式**——含公式的交底书会缺内容，需另写 OMML 提取 |
| `markitdown`（微软） | MIT | 底层就是 mammoth + python-pptx，同样丢公式。求快可用，可控性不如直接调底层 |
| `docx2python` | MIT | 结构化提取强（表格），但不输出 Markdown |
| `python-pptx` 1.0.2 | MIT | pptx 直接抽，可控 |

### 2.3 一个必须避开的许可陷阱

- **`docxtpl`（真名）是 LGPL-2.1-only**，引入需谨慎。
- **PyPI 上的 `python-docx-template` 是 GPLv3+ 的占位旧包，不要安装。**

本仓库是 MIT 的公开仓库，LGPL/GPL 依赖会污染许可边界。我们**不需要模板引擎**
（从零生成），所以这条只是提醒：**将来不要顺手装它。**

### 2.4 必须自研的部分

- **mermaid 离线渲染**：`mermaid-py` 只是 `mermaid.ink` 在线 API 的薄封装，
  `kroki` 客户端需要在线 kroki 服务（Java）。**纯 Python 离线渲染器不存在。**
  离线唯一稳路是 Node + `mmdc` + Chrome，且 **Chrome 路径必须自己探测**
  （基线把它写死成 macOS 路径，见避坑清单）。
- **OMML 公式提取**（mammoth 不给）：需自己从 `word/document.xml` 抽 `m:oMath` 节点。
- **WPS/Office 字体与渲染差异**：无现成库，见 §4.4。
- **中国专利申请号校验位**：纯算法，无依赖，值得直接实现（见 `prompts/04`）。

## 3. 反直觉结论：官方 OOXML XSD **不能**替代我们的校验

有人提出用 ECMA-376 / ISO/IEC 29500 的官方 XSD 做离线 schema 校验，比我们手写的
「拆 zip 检查」更权威。**实测后否决**。这是一个值得存档的否定结论。

### 实测过程与结果 `[实测]`

| 问题 | 实测结果 |
| --- | --- |
| XSD 能否拿到 | ECMA-376 免费包内的**只有 Strict 版** XSD；`standards.iso.org` 的免费入口**已关闭**，重定向到付费商店。过渡版（Transitional，即真实 docx 用的 `…/wordprocessingml/2006/main`）**不在官方免费包里** |
| Strict XSD 能用吗 | **不能**。lxml 加载直接失败：`attribute 'ref': QName '…}space' does not resolve`——libxml2 不支持 Strict XSD 的 `xml:space` 引用 |
| Transitional XSD 校验结果 | 能加载并运行 |
| **误报情况（关键）** | 我们的 `发明.docx` 与 **python-docx 生成的空白对照文档报完全相同的 4 个错**：`mc:Ignorable 不允许`（styles.xml / settings.xml）、`w:zoom 缺 percent`、`w14:docId not expected`。已核对：这些全部**源自 python-docx 的默认模板**，两边首部逐字一致 |

### 结论

**这不是我们的缺陷，是 schema 版本噪音。** 因为对照文件 100% 误报，
它**无法区分「真缺陷」与「版本不匹配」**，所以：

- **不可以**作为整包硬门禁（会把每份正常文件都判为不合格）
- **可以**作辅助：只校验 `word/document.xml`（主体内容能干净通过，能抓真实结构错误），
  `styles.xml` / `settings.xml` 的报错视为已知噪音
- **不可**替代我们现有的手写检查
- 过渡版 XSD 来源是第三方镜像而非 ECMA 官方包，**随仓库分发前还需法务确认许可**

**处置**：维持现状。我们的拆 zip 检查（107 项测试）继续作为主力，
XSD 校验不引入。这条否定结论已写进 `refactor-plan.md` 的「不建议做的事」。

## 4. 同类 skill 与产品层

### 4.1 最重要的一条：我们的基线上游已经重构了

`handsomestWei/patent-disclosure-skill` —— 就是 `.claude(2)` 里的那套，
**MIT，9893 star，且昨天（2026-09-19）还在推送** `[API]`。

| | 我们的快照 | 上游当前 |
| --- | --- | --- |
| commit | `c4b843e`（2026-05-28） | `c4ae70a`（2026-09-18） |
| 差距 | **落后 42 个提交，涉及 300 个文件** `[API]` | |

**上游已经从「单 skill + 扁平 prompts/」演化成「多子 skill 体系」**：

```
skills/
├── patent-disclosure/    交底（prompts/ 下按 发明/实用新型/外观/围栏 分）
├── patent-application/   申请文件四件套  ← 与我们的核心能力重叠
├── patent-docket/        案卷：一趟串起交底与申请
├── patent-search/        著录检索
├── patent-reader/        解读
├── patent-map/           专利地图
├── patent-oa/            审查答复
└── patent-exam-policy/   政策简报（当前 4.11.0）
```

每个子 skill 自带 `prompts/`、`references/`（含 `schemas/`）、`tools/`、**`tests/`**。
上游提交里有一条 `perf: 公布站检索增加自适应节流` —— 正好打在我们担心的脆弱点上。

**这对计划的影响**：P2 吸收上游之前**必须先重新同步到 `c4ae70a`**，
否则会照着一份 4 个月前的版本做。这条已写进 `refactor-plan.md`。

### 4.2 值得借鉴的编排设计（已吸收进本次 P1）

上游新的顶层 `SKILL.md` 是一个**纯路由器**，其中两点设计我们直接采用了：

1. **路由判定表的「明确不要做」列**。每一行不只说「去哪」，还说
   「**禁止**顺带做什么」。这防的是 Agent 漂移——用户只想检查格式，
   Agent 却顺手把权利要求重构了一遍。
2. **「须点名」门禁**。高成本或侵入性的能力（案卷、专利地图、审查答复）
   只有用户明确说出触发词才进入，不因相邻动作自动触发。

另有一个「调度视同点名」的例外规则：由案卷调度申请文件视为已点名，
但**仍须**满足「已指定交底目录」这个前置门禁。这个「放宽入口但不放宽门禁」的
处理方式值得记。

### 4.3 其他同类

| 对象 | URL | 许可 | 值得借鉴 |
| --- | --- | --- | --- |
| Claude-Patent-Creator | github.com/RobThePCGuy/Claude-Patent-Creator | MIT `[API]` | 把「形式检查」做成**独立 tool**；prior-art 设为硬前置 |
| legal-skills-open | github.com/ThomasMoreAI/legal-skills-open | Apache-2.0 `[API]` | 用 `PATENT_STATE.json` **状态持久化**以支持续写；跨法域分片 |
| AutoPatent | github.com/QiYao-Wang/AutoPatent | **无 LICENSE** `[API]` | 多智能体 Planner + Writer + **Examiner**（自检独立成角色）；大纲树 |

**AutoPatent 无 LICENSE，只能看思路不能搬代码。**

### 4.4 别人踩过的坑（与我们的经验高度重合）

| 坑 | 说明 | 我们的状态 |
| --- | --- | --- |
| `font.name` 只改 `ascii` | 必须用 oxml 设 `w:rFonts` 的 `eastAsia`，否则中文回退默认字体 | **已有**（`oxml.py`） |
| 样式名 ≠ XML id | `"Heading 2"`（显示名）与 `"Heading2"`（XML id）不同，写错会静默回退 Normal | 需在引入标题样式时注意 |
| 删段落会误删 `w:sectPr` | 节属性挂在段落上 | 需注意 |
| `{PAGE}` / `{NUMPAGES}` 域被 `.text` 赋值破坏 | python-docx issue #686 | **已规避**（页码用别的方式实现） |
| **哪些 OOXML 写法会让 Office 报损坏** | 元素顺序错、样式注入顺序错 | **已有**（`_PPR_ORDER` / `_RPR_ORDER`，107 项测试） |
| WPS 对多级列表的实现差异 | 常被重置为一级 | **已规避**（不用自动编号） |

**四条里三条我们早就解决了**——这印证了「写对」就是本仓库的差异化壁垒。

### 4.5 自检模块的补录来源

业内公认的形式检查清单来源：

- CNIPA：《专利法实施细则》第 20~22 条（说明书五部分、附图编号、**附图标记全文一致**、
  权利要求阿拉伯数字顺序编号、结尾仅句号、禁「如图所示」）、摘要 ≤300 字、
  电子申请形式要求
- USPTO：摘要 ≤150 词、35 USC 112 支持与可实施性

我们的自检已覆盖上述 CNIPA 条目的大部分。**待补**：权利要求「结尾仅句号」这一条
目前没有检查码；实施细则第 20~22 条的逐条对照表也值得在 `docs/format-spec.md` 里补齐。

## 5. 存疑与未核实项

诚实记下这一轮没弄清的，避免下次当成已知事实：

| 项 | 状态 |
| --- | --- |
| `mathml2omml-as` 长期维护性 | 只有 1 个版本（2025-06）。可用但社区小，**要留意它失修的风险**，封装层应便于替换 |
| `docxtpl` 的 LGPL 对本项目是否构成实际约束 | 只是提示，我们目前不引入 |
| mermaid 在 WPS 里的图片显示效果 | 未实测。mmdc 出的是标准 PNG，理论无问题 |
| 各商业产品（PatentPal 等）的流程切分 | `[检索]` 所得，未逐条核实其官方文档 |
| 「过渡版 XSD 随仓库分发的许可」 | 需法务确认，但既然决定不引入，暂不追究 |
