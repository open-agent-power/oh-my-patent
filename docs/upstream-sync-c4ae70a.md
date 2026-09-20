# 上游同步报告：handsomestWei/patent-disclosure-skill

> **来源与性质**：这是一份**只读侦察报告**，由调查 Agent 在 2026-09-20 生成，
> 归档自 `D:/tmp/upstream/report.md`（原始下载与解压在 `D:/tmp/upstream/`，未进仓库）。
> 报告中的「未核实」标注表示调查者未实际验证，**不要当作结论使用**。
>
> **用途**：P2 的前置材料。上游从单 skill 重构为 8 个子 skill，本地快照已落后四个月；
> 这份报告讲清了「变了什么、哪些值得吸收、哪些不该吸」，是 `docs/absorption-plan.md` 的补充。
> 上游 commit `c4ae70a`（2026-09-18）｜许可 **MIT**。

---

# 上游同步侦察报告：handsomestWei/patent-disclosure-skill

> 侦察兵任务：把 4 个月前的快照（commit `c4b843e`，2026-05-28）拉到最新（`c4ae70a`，2026-09-18），
> 看清上游变成了什么、哪些值得吸收。
> **硬性约束已遵守**：未改动 `D:\XiangMuLuoDi\Development\oh-my-patent` 任何文件；所有下载/解压在 `D:/tmp/upstream/`；未运行上游任何脚本（仅读取）；结论尽量指到 `文件:行号`，未实测/未读到的标注「未核实」。

---

## A. 上游最新快照（实际拿到什么）

- **实际 commit**：`c4ae70afba0fe9ff75d04e827a410554c58e0345`（已用 `gh api .../commits/c4ae70a` 核验），提交信息 `feat: refine disclosure flow`，作者日期 `2026-09-18T04:07:11Z`。
- **对比基线**：旧快照 `c4b843e2037376ce65a63f8db09b0cf635002b8f`（2026-05-28），与任务描述一致。
- **总文件数 / 体积**：当前 `448` 个文件、`du -sh` ≈ **13 MB**；旧快照 `51` 文件、`907 KB`。
- **获取方式**：`curl -sL` 跟随 GitHub codeload 重定向下载 `archive/<sha>.tar.gz`（gh api 对二进制重定向支持差，已换法子并如实记录）。
- **目录树（到第三层）**：

```
patent-disclosure-skill/                (仓库根)
├── SKILL.md            # 顶层路由器（子技能路由入口）
├── LICENSE / README.md / INSTALL.md / requirements.txt
├── .github/workflows
├── docs/
├── scripts/
└── skills/             # 8 个子 skill（详见 B）
    ├── patent-application/  prompts/ references/ tests/ tools/
    ├── patent-disclosure/   examples/ prompts/ references/ tests/ tools/
    ├── patent-docket/       assets/ examples/ prompts/ references/ tests/ tools/
    ├── patent-exam-policy/  docs/ prompts/ references/
    ├── patent-map/          data/ prompts/ tests/ tools/ web/
    ├── patent-oa/           assets/ docs/ examples/ prompts/ references/ tests/ tools/
    ├── patent-reader/       assets/ docs/ examples/ prompts/ references/ tests/ tools/
    └── patent-search/       prompts/ references/ tests/ tools/
```

**结论**：上游形态从「单 `SKILL.md` + 扁平 `prompts/`（11 文件）+ `tools/`（9 个 .py）+ `tests/`（3）」**重构为「1 个顶层路由器 + 8 个独立子 skill 包」**，文件数从 51 涨到 448。

---

## B. 8 个子 skill 各自是什么 + 路由

顶层 `SKILL.md`（`cur/SKILL.md`）是纯**路由器**，不承载正文。它用「能力总览表」(`:16-25`) + 「路由判定表」(`:27-41`) 按用户意图 `Read` 对应子 skill 的 `SKILL.md` 再执行。关键纪律：
- **须点名**才进入的包：申请文件、案卷、专利地图、审查答复、政策简报（`:29` 注释）；交底/检索可因意图自动进入。
- **禁止跨包调用**其他子技能的 `tools/`（`:46`），`browser.py`、`md_to_docx.py` 等「各包自带副本」（`:45`）。
- 交付末块统一标题 `交付后请确认`（`:48`）。

| # | 子 skill | 一句话职责 | prompts | tools | references | tests |
|---|----------|-----------|---------|-------|-----------|-------|
| 1 | **patent-disclosure** | 交底书：专利点挖掘→轻量查新→成文（发明/实用/外观）+ 保护型 1+N 围栏旁路 | 19（含 `invention/` `utility_model/` `design/` `fence/` 子目录） | 31（含 `crawl/` `vendor/` `fence/`） | 有（`schemas/` `formulas/` `scorecards/`） | 24 |
| 2 | **patent-application** | 已有交底 → 权要/说明书/摘要/附图 四件套（须显式、须指定交底目录） | 14 | 15（含 `emit_application_docx.py` `md_to_docx.py` `math_to_omml.py`） | 4（含 `disclosure_to_spec_map.md` `promo_terms.yaml`） | 8 |
| 3 | **patent-docket** | 案卷：交底到申请一趟串起来（须显式） | 10 | 8 | 7（`phases.yaml` `docket.schema.yaml` 等） | 1 |
| 4 | **patent-search** | 著录检索：CNIPA 公布公告站高级查询 + 从图/权要生成检索式 | 2 | 10（`cnipa_crawler.py` `cnipa_parse.py` `cnipa_search.py` 等） | 1 | 2 |
| 5 | **patent-reader** | 解读：公开号/PDF/全文 → 通俗笔记 + 图谱（Obsidian 入库） | 7 | 多（`analyze/` `browser/` `crawl/` `extract/` `vault/` `shared/`） | 6 | 10 |
| 6 | **patent-oa** | 审查答复：案例入库 + RAG 增强答复生成 | 8 | 21（`emit_opinion_docx.py` `embed.py` `ingest_*` 等） | 1 | 3 |
| 7 | **patent-map** | 专利地图：已解读入库摊成五种语义地形图（本机 web） | 2 | 11（`serve_map.py` `embed_layout.py` `ipc_scheme/` 等） | 0 | 1 |
| 8 | **patent-exam-policy** | 政策简报：对照国知局口径说明对写法/本稿影响（改技能为旁路） | 6 | **0** | 4（`sources.yaml` `topic_prompt_map.md`） | **0** |

**8 个之间怎么串**：顶层路由器按意图 `Read` 子 `SKILL.md`；`patent-docket` 作为「案卷」可**调度**申请文件/交底（视为已点名，但仍须有交底目录，`cur/SKILL.md:47`）；`patent-disclosure` 的交底完成后**不**自动进申请文件，须用户点名（`patent-disclosure/SKILL.md:27`）。各包通过 `outputs/<案件>/` 落盘衔接，不直接 import 彼此 `tools/`。

---

## C. 精确增量：旧快照没有的东西

旧快照（`old/`）形态：扁平 `prompts/` 11 文件（含 `disclosure_builder.md` `prior_art_search.md` `project_scan.md` `merger.md` `patent_points_analyzer.md` `template_reference.md` 等）+ `tools/` 9 个 .py（`cnipa_epub_crawler.py` `cnipa_epub_parse.py` `cnipa_epub_search.py` `docx_to_md.py` `pptx_to_md.py` `md_to_docx.py` `math_render.py` `mermaid_render.py` `iteration_dialog_log.py`）+ `tests/` 3。

**1) 新增的 prompt 文件（路径级，节选要点）**
- 整个 `patent-application/prompts/`（14 个）是**全新包**：`claim_strategy.md` `claims_builder.md` `specification_builder.md` `numeral_register.md` `consistency.md` `guardrails.md` `intake.md` `issues.md` `iteration*.md` `material_gate.md` `figures.md` `design_application.md` `self_check.md`。
- 整个 `patent-docket/`、`patent-search/`、`patent-reader/`、`patent-oa/`、`patent-map/`、`patent-exam-policy/` 的 prompts 全部为新增。
- `patent-disclosure/prompts/` 内新增类型子目录 `invention/ utility_model/ design/` 与 `fence/`（保护型 1+N 旁路）。

**2) 被改写的核心 prompt（从内容与 commit 判断）**
- `prior_art_search.md`：从单段查新**重写为两段式**（召回→按分类号收口，`:16-49`）+ **D1 锁定与区别特征 Fk 三态门禁**（`:142-196`），并新增「`abstract` 必用」「链接照抄 `link`、禁止编造」硬规（详见 D.3）。
- `disclosure_builder.md`：**拆为** `invention/utility_model/design/` 三套（旧为单文件）；新增 `fence/` 围栏旁路。
- `merger.md` 强化「非破坏性合并 + 新时间戳文件 + 禁止覆盖」（`:7`）。

**3) 新增/变化的 `tools/`，尤其 CNIPA 公布站检索**
- CNIPA 工具被**改名 + 拆分 + 重构**：
  - 旧 `tools/cnipa_epub_{crawler,parse,search}.py` → 新 `patent-disclosure/tools/crawl/cnipa_epub_{crawler,parse,search}.py` **+ 新增 `cnipa_epub_nav.py`**（+361 行，兜底整页导航路径）。
  - 另起新包 `patent-search/tools/cnipa_{crawler,parse,search}.py`（著录检索，与交底包查新分离）。
- **「perf: 公布站检索增加自适应节流」提交 `ce538604`** 实际改动（`gh api .../commits/ce538604` 核验）：
  - `SKILL.md` +1/-1；`patent-disclosure/tools/README.md` +2/-1；
  - `patent-disclosure/tools/crawl/cnipa_epub_crawler.py` **+528/-320**；
  - `patent-disclosure/tools/crawl/cnipa_epub_nav.py` **+361（新文件）**；
  - `patent-search/tools/cnipa_crawler.py` +83/-21。
- **节流到底改了什么 / 怎么实现**（读 `cnipa_epub_crawler.py`）：
  - 引入 `_PaceController` 类（**`:325`**），思路取自 **TCP Vegas/BBR**：以**响应延迟**而非「被拒」为主信号，在会话报废前退让（`:61` `:172` `:326`）。
  - 间隔持久化到临时目录 `cnipa_epub_pace.json`（常量 `FAST_PACE_FILENAME` 在 **`:210`**，`_pace_path()` 在 `:312`，读写在 `:342`/`:363`），按新鲜度衰减后作为下一轮起点。
  - 双路径：`EPUB_FAST_FETCH` 默认走 **A 路径 fetch**（实测每词 0.3–0.5s），任何一步不达预期**自动回退**到 **B 路径整页导航**（约 20s，新文件 `cnipa_epub_nav.py`）。
  - 限流是**会话级不可逆**：连续无间隔提交第 3 次起被拒；`_FastSession.rebuild()`（**`:480`**，带冷却 `FAST_REBUILD_COOLDOWN_SEC`，`:490`）丢弃脏 context 重建，重建前先冷却。
  - 相关配套提交：`41ef544d` 快速失败策略、`b1d5a311` 避免假超时、`defc31d9` 加固结果就绪判定。
- 其它新工具：各包 `md_to_docx.py`/`math_to_omml.py` 副本、`emit_application_docx.py`、`emit_opinion_docx.py`、`serve_map.py`、CAD 相关 `cad_scan.py`/`step_to_views.py` 等。

---

## D. 四个能力点：上游现在怎么做

### D.1 项目扫描（Office → 文本）
- 入口 `patent-disclosure/prompts/project_scan.md`。要求凡遇 `.docx`/`.pptx` **必须先转 Markdown 再读**（`:103-118`），用本仓库脚本：
  - `python .../tools/docx_to_md.py -i x.docx -o x.md`
  - `python .../tools/pptx_to_md.py -i x.pptx -o x.md`（`:112-115`）
  - 输出旁生成 `{md主名}_media/` 存嵌入图（`:117`）。
- **用的库**：`docx_to_md.py`/`pptx_to_md.py` 基于 python-docx / python-pptx 抽取（库名按文件名与同仓 `requirements.txt` 推断；**具体实现细节未逐行读，未核实**）。
- **公式（OMML）处理**：对 `docx_to_md.py` 全文 `grep omml|OMML|oMath|math|公式` **无任何匹配**（见侦察命令输出）。即项目扫描的 Office 转文本链路**未发现对 Word 内嵌公式（OMML/oMath）的提取逻辑**——源设计文档里的公式大概率在扫描转换中**丢失**（只取正文/表格/图片）。**具体丢失行为需实跑 `docx_to_md.py` 确认（按约束未运行脚本，标「未核实」）**。

### D.2 专利点挖掘与融合
- 入口 `patent-disclosure/prompts/invention/patent_points_analyzer.md`（发明；实用/外观各有同构文件）。
- **真硬约束**：
  - Step 3 列 **3–5 个**候选点，每条须含技术背景/创新点/与现有技术区别/可实施性；「可基于已有事实**适度推演**，但须有技术合理性支撑」（`:13`）——即**禁止无依据编造**，但允许有限推演。
  - Step 4 工作标题的领域对象「须能在 3.1/框图/流程/实施例落地」，**「不要选事后只能写成空泛『系统/模块』的名称」**（`:20`，硬约束）。
  - 最终以 Step 5 的 **D1 锁定 + 区别特征 Fk** 复核为准；**「不过」仍进 Step 6，区别改对材料/常规做法写，不要停笔，也不要指定不相干文献当 D1 或空喊『创新性强』」**（`:31`）。
- **输出结构**：默认优先产出**最有价值的一篇**交底书；保护型 1+N 不在本步拆，等首篇定稿后走 `fence/`（`:24`）。

### D.3 查新 / 现有技术检索（硬规定全清单）
- 入口 `patent-disclosure/prompts/prior_art_search.md`。核实并补全同类硬规：
  1. **「公开源 URL（必填）：每一条必须附带至少一个可公开访问、与著录项一致的链接…禁止编造或猜测 URL；写入前应在浏览器中打开确认页面可访问且对应同一文献/专利」**（`:129`）——与你记忆一致，已核实。
  2. **「链接与著录…`link` 字段…禁止编造。不得用 Google Patents URL 替换已有 `link`」**（`:103`）。
  3. **`abstract` 必用**：含 `abstract` 的条目「必基于对该 `abstract` 的完整阅读与理解后再撰写；**禁止**仅凭标题、公开号或 URL **臆造**方案要点」；且「不得大段逐字粘贴官方摘要」（`:96-100`）。
  4. **禁止编造条目凑数**：第二轮筛后 <4 条仍少时「1.1 如实写『检索范围内近邻较少』，**禁止编造条目凑数**」（`:49`）。
  5. **证据级别诚实**：定位稿须标「摘要 / 公开文本未通读 / 领域较远」，**「禁止把摘要级判断写成已核实全文」**（`:146`）。
  6. **降级纪律**：`stage=goto|gate|submit` 导航失败 ≠ 0 条，**「禁止当成检索不到」「禁止改走需登录的专利检索及分析系统」**（`:42`）；仅有 stderr/乱码而退出码 0 且 JSON 非空 → 不降级（`:92`）。
  7. **内部元信息不得进交底书 1.1**：脚本名、`Playwright`、`WebSearch`、Agent、仓库名等禁止写入（`:208`）。

### D.4 技术交底书（成文格式/命名/纪律）
- 成文由 `disclosure_builder.md`（按类型拆 `invention/utility_model/design/`）驱动；`template_reference.md` 给模板。
- **命名规则**：交付/迭代落盘为 **`{案件名}_{YYYYMMDDHHmmss}.md`** 并生成同名 `.docx`（`merger.md:7,24`）；迭代**「禁止覆盖上一轮交付文件（除非用户明确要求覆盖）」**（`:7`）。
- **不覆盖旧稿纪律**：合并结果须写入**新带时间戳文件**（`:7,24`）；已有申请产出上改稿须「新时间戳目录」（patent-application `SKILL.md:15`）。
- **交付末块固定标题 `## 交付后请确认`**（顶层 `SKILL.md:48`、各包统一）。

---

## E. `patent-application` 子 skill 到底做什么

- **输入输出**：输入 = 用户指定的**交底材料目录**（缺交底书/schema/线稿则终止，引导先补，`SKILL.md:9-10,16`）；输出 = **四件套**：权利要求书、说明书、摘要、说明书附图（Markdown + Word + 黑白图），落到 `outputs/patent-application/{案件}_{时间戳}/`（`SKILL.md:12,22`）。
- **怎么产出 docx**：`tools/emit_application_docx.py` 把目录下 Markdown 转 Word，核心是 `from md_to_docx import convert_md_to_docx`（`emit_application_docx.py:19,61`）。`md_to_docx.py` 的库：**python-docx**（`from docx import Document`、`from docx.oxml import OxmlElement`、`from docx.oxml.ns import qn`，`md_to_docx.py:20-24`），即先用 python-docx 高层 API，再用 `OxmlElement`/`qn` 手动拼底层 OOXML（列表 `numPr`、样式 `rFonts` 等）。
- **与我们 python-docx 直写 OOXML 路线：是同一件事还是不同事？** —— **同一工具链家族（都是 python-docx）**，但**工作流不同**：上游是「Markdown 中间表示 → `md_to_docx` 通用转换器」；我们路线是更直接的 OOXML 受控写入。二者在「用什么库」上重叠，在「架构」上不同。
- **是否处理致损三件套（元素顺序 / 字体 hint / theme fonts）**：
  - **字体 hint（eastAsia）**：**有**。`_set_run_font` 设 `run.font.name` 并 `run._element.rPr.rFonts.set(qn("w:eastAsia"), name)`（`md_to_docx.py:657-659`）；样式级也设 eastAsia「宋体」（`:1056`）。这是 CJK 渲染正确的关键。
  - **theme fonts**：**未核实到专门处理**。上游对所有 run/style 用**显式 `rFonts` 字体名**（而非 `w:themeFont` 主题引用），从机制上**规避了 theme font 缺失**问题——这本身是安全选择，但属于「不用 theme」而非「处理 theme」。
  - **OOXML 元素顺序**：**存在潜在脆弱点，未见显式守卫**。列表编号 `_set_paragraph_num_id` 用 `p_pr.append(num_pr)` 把 `w:numPr` 追加到 `w:pPr` **末尾**（`:772-782`）；而 CT_PPr 模式中 `numPr` 必须排在 `pPr` 内 `rPr`（最后一项）**之前**。若某段落 `pPr` 已含 `rPr`，此处会导致顺序非法、潜在致损。未见对 `numPr`/各元素顺序的显式校正逻辑（**未核实是否会实际触发**，取决于 python-docx 是否已在 `get_or_add_pPr` 后先写入 rPr）。
- **判断：吸收 还是 保持独立？** —— **建议保持独立，可局部借鉴。** 理由：
  1. 我们的护城河是「107 项测试把 docx 当 zip 拆开校验 XML 合法性 + WPS/Office 一致」。上游 `md_to_docx` 是**通用 Markdown→docx 转换器**，且有上述 `numPr` 顺序脆弱点与无 theme/元素顺序正确性层——吸收它**不会增强**、反而可能**回退**我们对 OOXML 合法性的保证。
  2. 上游路线以 Markdown 为中间格式，与我们的「直写受控 OOXML」架构冲突，吸收 = 改写我们整套产出管线。
  3. **可借鉴的硬化点**（非吸收整体）：① eastAsia 字体 hint 写法（我们是否覆盖 CJK 字体需自查）；② OMML 公式双轨（上游 `math_to_omml.py` 优先 OMML、matplotlib PNG 兜底，`md_to_docx.py:125,377`）；③ 列表「每组有序列表从 1 重计」克隆编号实例（`_new_list_num_id`，`:791-824`）。

---

## F. 许可与合规

- **LICENSE 准确路径与类型**：`cur/LICENSE`（仓库根），**MIT License**，著作权 `Copyright (c) 2026 handsomestWei`（`:1-3`）。旧快照 `old/LICENSE` 同路径同内容。
- **文件头版权声明**：对全部 `.py` 做 `grep -l "Copyright"`，**仅 1 个测试文件**含 `Copyright` 字样（`skills/patent-reader/tests/test_patent_reader_debt_fixes.py`）。即绝大多数源码**没有逐文件版权头**。→ 搬运时**必须保留仓库根 `LICENSE` 全文**（MIT 第 12–13 行要求「上述版权声明与许可声明须包含在所有副本或实质部分中」），但无逐文件头需要逐一保留。
- **第三方代码 / 无许可内容疑点**：
  1. **`skills/patent-disclosure/tools/vendor/mermaid.min.js`（≈2.5 MB）**：第三方 Mermaid.js  vendored 副本。`vendor/README.md` 存在但**其内单独许可未在此处逐行核验**（Mermaid 本身为 MIT；**搬运前须确认该 vendor 文件自带许可文本，标「未核实」**）。
  2. `tools/package.json` 列 `devDependencies`：`@mermaid-js/mermaid-cli` `puppeteer`（legacy，非运行依赖，`package.json` 描述已注明「now uses Playwright + vendor/mermaid.min.js and does not require this package」）——属构建期依赖，不是混入的无许可源码。
  3. `cnipa_epub_crawler.py:18` 有注释「分析 by Claude Opus 5 Extra High」——系**分析过程署名**，非第三方代码拷贝，不构成许可风险。
  4. **未发现**其他明显抄录别处、无署名的代码块（仅静态阅读，未做逐文件溯源比对；如需强保证建议对 `tools/` 做一次 license/CD 扫描，标「未核实」）。

---

## 摘要（给 P2 决策用）

- **上游实际形态**：单 skill 已重构为「顶层路由器 + 8 个独立子 skill 包」（448 文件/13MB），新增了申请文件、案卷、检索、解读、OA、地图、政策简报 7 个包，CNIPA 检索被改名拆分并加了自适应节流。
- **对 P2 影响最大的 3 个发现**：
  1. **CNIPA 检索已重写**：双路径（fetch 0.3–0.5s / 整页导航兜底）+ `_PaceController` 类 TCP-BBR 节流 + 会话级限流重建冷却（`cnipa_epub_crawler.py:325,210,480`）。照 4 个月前版本做会漏掉整套稳定性工程。
  2. **查新硬规已系统化**：URL 必填可访问且禁止编造（`:129`）、`abstract` 必用禁止臆造（`:96`）、证据级别诚实（`:146`）、降级纪律（`:42,92`）——可直接借鉴进我们的查新 prompt。
  3. **项目扫描对 Word 公式（OMML）无提取逻辑**（grep 无匹配），源设计文档公式在扫描中丢失——我们若吸收其扫描链路需先补 OMML 提取。
- **`patent-application` 判断**：与我们同为 python-docx 路线，**建议保持独立**（吸收会回退我们对 OOXML 合法性的 107 测试保证，且上游 `numPr` 顺序无显式守卫、`md_to_docx.py:782`）。可借鉴：eastAsia 字体 hint、OMML 双轨、列表从 1 重计。
- **「照旧版本做就会白做」的坑**：4 个月前 `c4b843e` 还没有申请文件/案卷/OA/地图/解读/政策/检索这 7 个包，CNIPA 还是旧 `cnipa_epub_*` 无节流无 nav 兜底——照那份做等于在一套已被上游拆分重写的设计上二次开发。
- **合规**：MIT（根 `LICENSE`，©2026 handsomestWei），源码基本无逐文件版权头，搬运须保留根 LICENSE；注意 `tools/vendor/mermaid.min.js` 第三方资产须先确认其自带许可（未核实）。
