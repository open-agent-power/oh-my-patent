# 重构计划：以第三方 skill 包为基线

> 状态：**D1 已定（开发区放 `.claude` 内）｜D2 已定（不做 MCP）｜D3 已定（见 §6）｜D4 已实测结案**
> ｜**P1 已完成（2026-09-20）｜P2 增加一条前置：先重新同步上游（见 §7.1）**
> 起草：2026-09-19 ｜ 更新：2026-09-20
>
> **配套文档**：`absorption-plan.md` —— 四路并发调查的结论、三档吸收清单、能力映射表、
> 分阶段实施步骤与避坑清单。那份讲「吸收什么、怎么落」，这份讲「整体怎么重构」。
> `landscape-survey.md` —— 同类方案调查：市面上的现成轮子哪些能用、哪些不能用、哪些必须自研。

## 1. 范围

以 `$workspace/.claude(2)/.claude/skills/` 下解压出的三套第三方 skill 为**能力基线**，
吸收本仓库（oh-my-patent）已验证的工程资产，重构为一个覆盖
**「技术想法 → 可递交申请文件」** 全链路的 Agent Skill。

## 2. 基线盘点

| skill | 定位 | 在链路中的位置 | 许可 |
| --- | --- | --- | --- |
| `patent-disclosure-skill` | 项目扫描 → 专利点挖掘 → CNIPA 查新 → 技术交底书 → 迭代 | **上游** | **MIT** ✅ |
| `patent-writing` | 参考 docx 提格式 → pandoc 出 OMML → 申请说明书 | **下游** | **无 LICENSE** ⚠️ |
| `wps-skills` | WPS 加载项 + MCP Server（243 工具），操控**已打开**的文档 | 工具层（旁路） | **无 LICENSE** ⚠️ |

**许可边界是这个计划最硬的约束**：
只有 `patent-disclosure-skill` 是 MIT，**其代码可以借鉴、修改、再分发**（需保留版权声明）。
另两个没有许可文件，法律上默认「保留所有权利」——**只能参考思路后独立实现，不能搬运代码**。
本计划后续所有「吸收」，都按这条线执行。

### 基线的组织范式（值得学的地方）

三套共同遵循 [AgentSkills](https://agentskills.io) 惯例，核心是**渐进式披露**：

```
{skill}/
├── SKILL.md      ← 唯一入口：触发条件 + 工具映射 + 步骤序列 + prompts 索引
├── prompts/      ← 分步指令，Agent 在运行时 Read 加载（避免单文件过长）
├── tools/        ← 可执行脚本，与编排解耦
├── docs/         ← PRD 与结构说明
├── examples/     ← 可提交的虚构原材料
├── outputs/      ← 产物，整目录 gitignore
└── tests/
```

对照本仓库现状：我们的 `SKILL.md` 是**单体**（300+ 行，撰写要点全塞在里面），
而基线把「编排」与「细则」分开。这是我们结构上最该改的一处。

## 3. 已盘出的基线能力与依赖

| 能力 | 依赖 | 备注 |
| --- | --- | --- |
| 项目扫描（含 Office 先转 MD） | `mammoth`、`python-pptx` | 纪律明确：**不得因只读得懂文本而漏掉 Word/PPT** |
| CNIPA 公布公告站检索 | **`playwright` + chromium**（体积大） | 自己实现了爬取，失败降级 WebSearch |
| 交底书成文（md + docx） | `python-docx` | 定稿强制双格式 + 时间戳命名 |
| mermaid 图渲染 | **Node + mmdc + Chrome** | 黑白主题，转 PNG 后嵌 docx |
| 原生 OMML 公式 | 基线用 **pandoc**（系统级） | **不复用**。改用 `latex2mathml` + `mathml2omml-as`（均 MIT、纯 Python，见 D4） |
| 申请说明书生成 | `pandoc` + `python-docx` | 见 `patent-writing`（macOS 专用链） |
| 迭代（合并 / 纠错） | 无额外依赖 | 另存时间戳新稿，不覆盖；留修订记录 |
| WPS 文档操控 | Node ≥18 + WPS 加载项 + MCP | `wps-skills`，243 个工具 |

## 4. 本仓库已有资产（要保住的）

| 资产 | 位置 | 为什么不能丢 |
| --- | --- | --- |
| **OOXML 双适配** | `oxml.py` | WPS/Office 版面一致的全部根因分析都在这里；基线三套**都没有** |
| **XML 合法性测试** | `tests/`（107 项） | 把 docx 当 zip 拆开校验 schema 顺序、关系可达、主题引用清零 |
| **格式合规自检** | `lint.py` / `lint_ai.py` | 52 个检查码，命名统一为 `前缀-三位数字`，含 2026-01-01 新指南的 AI 类判据 |
| **三种专利类型渲染** | `render/docx.py` | 发明 / 实用新型 / 外观设计，含拆分成独立文件 |
| **宽容解析** | `parser.py` | Markdown / YAML / JSON，兼容 `【技术领域】` 式旧稿 |
| **零外部依赖** | 仅 `python-docx` | 可自动化测试的前提 |

一句话概括分工：**基线强在「想什么」（挖掘、查新、组织），本仓库强在「写对」（格式、合规、可测）。**

## 5. 目标架构（建议）

顶层采用基线的 AgentSkills 范式，**内部保留本仓库的模块化包结构**：

```
oh-my-patent/
├── SKILL.md                     ← 精简为编排：触发条件 + 步骤序列 + prompts 索引
├── prompts/                     ← 新增：分步指令
│   ├── 01-intake.md             ← 边界与输入
│   ├── 02-project-scan.md       ← 项目扫描（Office 先转 MD）
│   ├── 03-patent-points.md      ← 专利点挖掘与融合
│   ├── 04-prior-art-search.md   ← 查新
│   ├── 05-disclosure-build.md   ← 技术交底书
│   ├── 06-specification-build.md← 申请文件（本仓库强项）
│   ├── 07-self-check.md         ← 自检
│   └── iteration/               ← 迭代：merge / correction
├── oh_my_patent/                ← 保留：分层 Python 包
│   ├── spec.py  schema.py  parser.py
│   ├── lint.py  lint_ai.py  report.py
│   ├── oxml.py                  ← 双适配核心
│   ├── cli.py
│   └── render/
├── tools/                       ← 对外脚本（md↔docx、mermaid、查新）
├── docs/                        ← PRD、架构、格式规范、本计划
├── examples/                    ← 示例原材料
├── tests/
└── outputs/                     ← 产物（gitignore）
```

关键点：`tools/` 下是**薄脚本**，真正的逻辑仍在 `oh_my_patent/` 包里 ——
这样既符合基线的调用习惯，又保住了可测试性。

> **P1 已按此落地**（2026-09-20）。两点实现上的补充：
>
> 1. **未实现的步骤不写空壳流程。** `02`~`05` 与 `iteration/` 六份文件顶部都带
>    「状态：未实现」标记，内容写的是**待建规格**（目标 / 硬约束 / 依赖 / 验收），
>    不是可执行流程。SKILL.md 的路由表把它们标成「未实现（P2/P4）」，
>    并在「明确不要做」一列写明**不得按规格假装执行**——否则 Agent 会照着
>    一份规格去演一遍，产出看起来完整其实不存在的能力。
> 2. **`references/` 并入 `docs/`**，`scripts/` 并入 `tools/`。原来两个目录职责重叠
>    （`scripts/` 与计划中的 `tools/` 都是「对外脚本」），合并后只有一个去处。

## 6. 需要拍板的决策点

### D1 · 开发区位置——**已定：放在 `.claude` 内**

开发在 `.claude(2)/.claude/skills/` 下进行。定下之后，有三件事必须在开工前处理，
否则会一路绊到结束：

| 问题 | 现状 | 处理 |
| --- | --- | --- |
| **三套嵌套 `.git`** | 三个 skill 各自带 `.git` | ✅ **已处理**：归档为 `skills/_upstream-git.tar.gz`（1.5 MB，173 文件）后移出，工作区只留本仓库这一个 `.git` |
| **25302 个 node_modules 文件** | 拖慢所有文件操作与搜索 | 建议删除（`npm install` 随时可恢复），只留源码 |
| **许可边界** | 两套无 LICENSE | ✅ **已处理**：`skills/UPSTREAM.md` 记录来源仓库、基线 commit、许可边界、上游已知坑 |

另：`__MACOSX/` 与 `.DS_Store` 是解压残留，可直接清掉。

### D2 · WPS 适配路线——**已定：不做 MCP**

继续用 OOXML 直写，靠 `oxml.py` 保证 WPS / Office 版面一致。

`wps-skills` 那 243 个工具解决的是「操控已打开文档」，与我们「从零生产文件」
不是同一问题；引入会多出三个故障点（装加载项、WPS 须运行、Node 须编译），
且该层无法自动化测试。**该套只作能力参照，不引入代码。**

### D3 · 外部重依赖要不要——**已定**

依据见 `landscape-survey.md`（本轮实地调查，含一次否决性实测）。

| 依赖 | 用途 | 决定 | 理由 |
| --- | --- | --- | --- |
| `mammoth` | Word → Markdown | **引入**（硬依赖） | BSD-2，纯 Python，轻量。**已知缺口：会丢 OMML 公式**，公式需另写提取 |
| `python-pptx` | PPT 取文本/表格 | **引入**（硬依赖） | MIT，纯 Python，轻量 |
| `latex2mathml` + `mathml2omml-as` | LaTeX → OMML 公式 | **引入**（硬依赖） | 均 MIT、纯 Python、共约 100 KB。见 D4 |
| `playwright` + chromium | CNIPA 公布公告站检索 | **可选依赖** | 约数百 MB。装了才启用直查，否则**降级联网搜索并明确告知用户** |
| Node + `mmdc` + Chrome | mermaid 图 → PNG | **可选依赖** | **已核实：纯 Python 离线渲染器不存在**（`mermaid-py` 只是在线 API 封装）。离线唯一稳路，Chrome 路径须自行探测 |
| `pandoc` | Markdown → OMML | **排除** | 系统级安装（非 pip），且不继承参考件字体会导致字体回退。已有纯 Python 替代 |
| `docxtpl` / `python-docx-template` | 模板引擎 | **不引入** | 前者 LGPL-2.1，后者是 GPLv3+ 的占位旧包。我们不需要模板引擎 |

**原则**：解析类依赖可以放宽（读得越多越好），**生成路径必须保持零外部依赖**——
那正是「生成的文件 XML 合法」这条底线的可测试性来源。

### D4 · 公式支持——已调查，结论如下

> **原推荐（「自研 OMML」）作废。** 那个理由是从 `patent-writing` 的故障表里转述的，
> 我没有验证。实测后推翻，改用现成库链。

**现成链路存在，且全部 MIT：**

| 库 | 作用 | 许可 | 体积 |
| --- | --- | --- | --- |
| `latex2mathml` | LaTeX → MathML，纯 Python | MIT | 79 KB |
| `mathml2omml-as` | MathML → OMML，纯 Python | MIT | 24 KB |
| `math2docx` | 上述两者的 25 行封装 | MIT | 3 KB |

**本机实测结论：**

1. **链路可用。** `\frac` / `\sqrt` / `\sum` / `\mathbb{R}` 均正确转为标准 OMML
   （`m:nary` + `m:chr val="∑"`、`m:sSup`、`m:sSub`），`\mathbb{R}` 落成 Unicode `ℝ`，
   正文无 LaTeX 残留。
2. **结构合法。** 行内公式在 `<w:p>` 内与 `w:r` 交错，`pPr` 保持最前；
   块级公式用 `m:oMathPara` 包 `m:oMath`。
3. **与现有流程不冲突。** 跑 `de_theme_fonts()` 前后 `oMath` 计数不变、
   `m:sty` / `m:t` 内容完好。
4. **缺口是硬的。** 现有渲染层把 `$$...$$` 原样吐出成文本，
   `\frac{q_i^T k_j}{\sqrt{d_k}}` 会直接印在正文里 —— 这不是「不够好」，
   是**当前会产出不可递交的内容**。

**两个必须自己处理的坑（实测踩到）：**

- `mathml2omml.convert()` 的返回值**不带命名空间声明**，直接 `parse_xml()` 报
  `Namespace prefix m on oMath is not defined`。必须借一个带 `xmlns:m` 的外层元素
  注册命名空间再取出子元素——`math2docx` 那 25 行封装解决的正是这个，它不是多余的。
- 同一次 `convert()` 的返回值**自带 `<m:oMath>` 根标签**，再包一层会得到
  `<m:oMath><m:oMath>` 嵌套（schema 非法）。

**结论**：用 `latex2mathml` + `mathml2omml-as`。**不引入 pandoc**（系统级依赖，
且 pandoc 不继承参考件 Normal 样式字体会导致字体回退，`patent-writing` 为此写了
200 行后处理）；**不自研**（无必要）。封装成约 30 行的 `math.py`，
命名空间处理与降级逻辑都在里面。转换失败时保留原 LaTeX 并标注提示，不中断生成。

## 7. 分阶段实施

| 阶段 | 内容 | 产出 | 状态 |
| --- | --- | --- | --- |
| **P0** 认知对齐 | 细读基线核心文件，产出「能力-实现对照表」 | `docs/absorption-plan.md`（四路并发调查的合并结论，取代原计划的 `baseline-study.md`） | **已完成** |
| **P1** 结构重构 | SKILL.md 拆分 → `prompts/`；建立 `tools/`、`docs/`、`outputs/`；现有代码**零行为变更** | 目录就位；**验收见 §7.2** | **已完成 2026-09-20** |
| **P2** 吸收上游 | **先重新同步上游**（§7.1），再吸收项目扫描、专利点挖掘、查新、交底书 | 新增 prompts + 脚本，含测试 | 待启动 |
| **P3** 公式与附图 | 新增 `math.py`（LaTeX→OMML 封装）；渲染层识别 `$…$` 与 `$$…$$`；mermaid 出图 | `m:oMath` / `m:oMathPara` 进入 XML，附测试 | 待启动 |
| **P4** 迭代模式 | merge / correction 两条路 + 时间戳命名 + 修订记录 | CLI 新增 `revise` 子命令 | 待启动 |
| **P5** WPS 适配 | 按 D2 执行 | 待定 | 待定 |

**P1 的硬约束**：只搬家、不改行为。重构与功能新增绝不混在同一步，
否则「测试全绿」就失去意义——分不清是重构没改坏，还是新代码掩盖了问题。

### 7.1 P2 的前置：上游已经重构了

调查中发现，MIT 那套基线 `handsomestWei/patent-disclosure-skill` 在上游已经大幅演进：

| | 我们的快照 | 上游当前 |
| --- | --- | --- |
| commit | `c4b843e`（2026-05-28） | `c4ae70a`（2026-09-18） |
| 形态 | 单 skill + 扁平 `prompts/` | **8 个子 skill**（`skills/<name>/`），各带 `prompts/`、`references/`、`tools/`、`tests/` |

差距 **42 个提交、300 个文件**。上游提交里有 `perf: 公布站检索增加自适应节流`，
正好打在我们担心的抓取脆弱点上。

**因此 P2 第一步不是写代码，而是先把快照重新同步到 `c4ae70a`**，
否则会照着一份四个月前的版本做吸收。同步后要重新过一遍三档吸收清单——
上游新出现的 `patent-application` 子 skill 与我们的核心能力重叠，
需要重新判断「吸收」还是「保持独立实现」。

### 7.2 P1 验收标准的更正（原标准不可达）

原定验收是「四示例输出与重构前**逐字节一致**」。**这条标准写错了，按它永远过不了。**

实测：同一份稿件连跑两次，`.docx` 的 sha256 **不同**。逐条目拆开比对后确认，
**所有 zip 条目的内容字节完全一致，差异只在条目时间戳**（python-docx 写入时
把每个条目的 mtime 设成构建时刻）。文件级哈希天然不可复现。

**更正为内容级判据**：

> 重构前后各构建一次，拆开 zip 逐条目比对：**条目清单与顺序相同，
> 且每个条目的内容字节完全一致**（容器时间戳不在判据内）。

P1 实际验收结果：

| 项 | 结果 |
| --- | --- |
| 测试 | **107 项全绿**（96 项原有 + 11 项新增） |
| 四示例 docx 内容比对 | 发明 / 实用新型 / 外观设计 / AI 方法 **四个全部逐条目字节一致** |
| 四示例自检输出 | 不变（`CLAIM-004` + `ABS-003`，与重构前一致） |

顺带记一个可选改进：给 `build` 加一个**可复现构建**开关（写入固定 mtime），
就能让文件级哈希稳定、验收判据简化为一次 sha256 比对。属行为变更，未纳入 P1。

## 8. 风险

| 风险 | 影响 | 处置 |
| --- | --- | --- |
| 许可 | `patent-writing` / `wps-skills` 无 LICENSE | 只参考思路，独立实现；MIT 那套保留版权声明 |
| 基线为 macOS 而本机是 Windows | `brew` / `open -a` / `pkill` 全不可用 | 所有吸收项必须自己实现，不照抄命令 |
| 基线依赖 Claude 生态 | `CLAUDE_SKILL_DIR` 等 | 改用本仓库自己的路径解析 |
| 引入重依赖后不可测 | 破坏「可自动化测试」这一立身之本 | 公式库是纯 Python，可测；`playwright` 做成可选 + 降级路径；`pandoc` 已排除 |
| **凭转述下技术结论** | 本次 D4 已犯过一次：推荐「自研 OMML」却从未实测 | 凡涉及「某工具做不到 X」，先在本机跑一次再写进计划 |
| **上游快照会过期** | 本地基线落后上游 42 个提交、300 个文件；照着旧版吸收会白做 | P2 开工前先同步到 `c4ae70a`（§7.1），此后定期核对 |
| 范围膨胀 | 全链路做完体量远大于当前 | 按阶段交付，每阶段可独立使用 |

## 9. 不建议做的事

1. **不要把 100MB 压缩包或 `node_modules` 纳入任何提交**（已 gitignore）。
2. **不要为吸收功能而放弃「生成的文件 XML 合法」这条底线**——
   基线三套的验证方式是「用 WPS 打开看一眼」，而 WPS 对 OOXML 过于宽容，
   这恰好掩盖了会致 Office 报损坏的那类缺陷。
3. **不要在结构重构里顺手改行为。** P1 的执行方式：搬家与 `DES-*` 码归一同批完成，
   但**行为中立性用实测证明，而不是靠提交粒度的声明**——
   重构前后各构建一次四示例，逐条目比对内容（全一致），
   码归一另配 11 项新测试。
   （原打算把两者拆成两个提交，实操上做不到干净拆分：`format-spec.md` 同时是
   搬家对象与码表载体，拆开会产生「文档引用了尚不存在的路径与码」的中间态，
   反而更难验证。）
4. **不要引入官方 OOXML XSD 做 schema 门禁。** 已实测否决：ECMA 免费包里只有
   Strict 版 XSD（而真实 docx 用的是 Transitional），Strict 版在 lxml 下根本加载不了；
   过渡版校验时，**python-docx 生成的空白对照文档也报同样 4 个错**，
   无法区分「真缺陷」与「版本噪音」。详见 `landscape-survey.md` §3。
5. **不要安装 `docxtpl`（LGPL-2.1）或 `python-docx-template`（GPLv3+ 占位旧包）。**
   本仓库是 MIT，引入会污染许可边界，而我们并不需要模板引擎。
6. **不要用 `font.name` 去设中文字体。** 它只改 `ascii`，中文会回退默认字体——
   必须走 `oxml.set_run_font()` 把 `eastAsia` 写全。这是社区反复踩的坑，我们已规避。
