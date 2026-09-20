# 吸收方案（四路并发调查结论）

> 配套 `refactor-plan.md`。那份讲「怎么重构」，这份讲「从基线吸收什么、怎么落」。
> 调查时间：2026-09-20

## 0. 调查方式

四路并发，各查一块，结论均带文件行号：

| 路 | 范围 | 产出 |
| --- | --- | --- |
| ① | `patent-disclosure-skill/prompts/` 全部 11 个文件 | 流程设计与硬约束清单 |
| ② | `patent-disclosure-skill/tools/` 全部 9 个脚本 + 3 个测试 | 可复用工具与实现雷区 |
| ③ | `wps-skills/` 全部（含安装脚本、MCP 架构） | 架构真相与危险性 |
| ④ | 本仓库 `oh_my_patent/` 全部 | 我方接口清单与能力缺口 |

## 1. 三套基线的实证质量

**这一节推翻了外部评测长文的排序。** 长文说 `wps-skills` 「很适合做 Office Workflow」——实证相反。

| 基线 | 长文评价 | 实证结论 | 证据 |
| --- | --- | --- | --- |
| `patent-disclosure-skill` | ⭐ 最值得研究 | ✅ **成立**，但价值在**流程纪律**而非代码 | 11 个 prompt 有真硬约束；有 3 个测试 |
| `patent-writing` | 偏最终文档生成 | ⚠️ **只取它的坑表**，工具链整条作废 | 全链 macOS 专用；公式走 PNG 而非 OMML |
| `wps-skills` | ⭐ 适合做 Office Workflow | ❌ **Windows 实现是坏的** | 见下 |

### `wps-skills` 的三个硬伤（都经过验证）

1. **Windows 链路是断的。** 架构上 Windows 走 `powershell -File scripts/wps-com.ps1`
   调用 COM，但**该文件不存在** —— Windows 上每次工具调用都会因缺文件 reject。
   （macOS/Linux 走 HTTP 轮询，实现是另一套 6611 行的脚本。）
2. **零真实测试。** `jest.config.js` 设了覆盖率阈值，但它的 `testMatch` 指向
   `src/tests/**`，而**该目录不存在**。配置是摆设。
3. **工具数量三处不一致**：文档写 243 / 224 / 231，代码实际注册 235。

另：`auto-install.ps1` 会改写用户的 `~/.claude/settings.json`（先读→转 JSON→写回，
原文件 JSON 损坏时走 catch 重建，**有覆盖风险**）；`wps-claude-addon/js/main.js`
仅 54 行，疑似桩。

**这对我们意味着什么**：D2「不做 MCP」的决定不仅成立，理由还比我原先说的更硬 ——
原来我讲的是「场景不匹配」，现在是「**它在 Windows 上是坏的，且没有测试**」。

## 2. 吸收清单（三档，按许可划界）

> 许可红线见 `UPSTREAM.md`：只有 `patent-disclosure-skill` 是 MIT，**代码可搬**；
> 另两套无 LICENSE，**只能学思路，独立实现**。

### 第一档 · 照搬组织形式（无许可问题）

1. **`SKILL.md` 只做编排**，细则拆进 `prompts/`，按步骤 `Read` 加载
2. **每个 prompt 头部写「执行门禁」**：先 Read 哪个文件、禁止做什么
3. **交付双格式 + 时间戳命名 + 不覆盖旧稿**
4. **迭代留痕**：案件目录追加修订对话记录，含时间/类型/说明/产出文件名
5. **自检发现问题就直接改稿**，而不是只输出一份报告
6. **自检清单不写进正文**（正文里出现「自检」二字即不合格）

### 第二档 · 搬代码或借鉴实现（限 MIT 那套）

1. **查新著录硬规定**：每条现有技术必须附**经核验可访问**的公开源 URL，禁止编造；
   `abstract` 非空时必须先消化再概括，禁止凭标题杜撰；检索说明里**禁泄露工具名**
2. **公式体例（§7.7）**：维度用**正体下标**（`b_{i,\mathrm{cpu}}`，不用 `^{cpu}` 易误读为幂）；
   禁止同一字母多义；行内/块级 LaTeX 分隔符全文统一；块级公式尽量单行
3. **脱敏四类**：业务抽象化、分类用 A/B/C、数值改为「一定规模」、公司产品名删除
4. **可复用脚本**：`docx_to_md.py`、`pptx_to_md.py`（mammoth / python-pptx）、
   `cnipa_epub_parse.py`（纯正则，无重依赖）
5. **`md_to_docx.py` 的字体处理思路**可借鉴 —— 它确实显式设了 `w:eastAsia`；
   但**它没设 `w:hint`**，而这是我们的技能里强调的关键项，我们不能跟着漏

### 第三档 · 只学思路、独立实现（无 LICENSE 那两套）

1. **从参考 docx 提取格式参数**（`patent-writing` Step 1）——
   解决了「代理所有自己的模板怎么办」：读参考件的行距/缩进/字体，让 `spec.py` 常量可被覆盖
2. **长文档位置索引方案**（`wps-skills` 的 `get_paragraphs(start,end)`、
   `find_in_document` 只返回位置、按关键字/书签定点填充）——
   这是我们「局部修改已有 docx」短板的现成设计参考
3. **SKILL.md 的「场景示例 + 工具签名表」写法** —— 比纯能力清单更可执行

## 3. 能力映射表

| 基线能力 | 我方现状 | 落到哪里 | 动作 |
| --- | --- | --- | --- |
| SKILL.md 编排 + prompts 分步 | 单体 300+ 行 | `SKILL.md` + `prompts/` | **拆分** |
| 项目扫描（含 Office 转 MD） | 无 | `prompts/02` + `tools/docx_to_md.py` | 新增 |
| 专利点挖掘与融合 | 无 | `prompts/03` | 新增 |
| 联网查新 | 无 | `prompts/04` + `tools/cnipa.py` | 新增（可选依赖） |
| 技术交底书 | 无 | `prompts/05` | 新增 |
| **申请文件生成** | ✅ 完整（lint + render） | 保留，作为强项 | **保留** |
| **OOXML 双适配** | ✅ 完整（oxml.py） | 保留 | **保留** |
| **XML 层测试体系** | ✅ 107 项 | 保留并扩展 | **保留** |
| 公式 OMML | 无 | `oh_my_patent/math.py` | 新增（方案已定，见 D4） |
| mermaid 出图 | 无 | `tools/mermaid.py` | 新增（自己实现） |
| 迭代修订 | 无 | `cli.py` 加 `revise` 子命令 | 新增 |
| Word/PPT 输入 | 无 | `tools/docx_to_md.py` | 新增 |

## 4. 实施步骤

### P1 · 结构重构（只搬家，零行为变更）——**已完成 2026-09-20**

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 1. `SKILL.md` 拆分 → `prompts/01`~`07` | 完成 | SKILL.md 由 312 行缩到 **119 行**，改为纯编排（路由判定表 + 通则） |
| 2. 新建 `tools/`、`docs/`、`outputs/` | 完成 | `outputs/` 用 `outputs/*` + `!outputs/.gitkeep` 保目录、不保内容 |
| 3. `references/format-spec.md` → `docs/format-spec.md` | 完成 | `references/`、`scripts/` 两个目录已合并掉（`scripts/patent.py` → `tools/patent.py`） |
| 4. 清理 `lint.py` 的 `DES-*` 命名 | 完成 | `DES-USAGE`/`DES-POINTS`/`DES-BEST_VIEW`/`DES-IMAGES`/`DES-PATH` → **`DES-001`~`DES-005`** |
| 4b. 清理「码号乱序」 | **未做，判定为误报** | 见下 |
| 5. 验收 | 完成 | 见下 |

**关于 4b（码号乱序）**：核下来这不是缺陷。`CLAIM-011`/`CLAIM-012` 是**逐项**检查
（在 `for claim in draft.claims` 循环内），`CLAIM-010` 是**整篇**检查（只看第 1 项，
在循环外），两者的源码相邻关系是结构决定的，不是排错。
重编号只会把 `docs/format-spec.md` 里公开的码表搅乱、且让已发布的三个码含义漂移，
**收益为零、风险非零**。已改为在这两处各加一段注释说明位置原因，行为零变更。

**顺带补的洞**：`check_design()` 原先**零测试覆盖**，本次新增
`tests/test_lint_design.py`（11 项），含一道**命名约定守门测试**
（扫描源码里的检查码字面量，断言全部匹配 `前缀-三位数字`），防止下次又跑出别的写法。

**验收（P1 实际结果，判据已更正）**：

| 项 | 结果 |
| --- | --- |
| 测试 | **107 项全绿**（96 原有 + 11 新增） |
| 四示例 docx | 发明 / 实用新型 / 外观设计 / AI 方法，与重构前**逐条目内容字节一致** |
| 四示例自检输出 | 不变 |

> **原定的「逐字节一致」判据不可达，已更正为「逐条目内容一致」。**
> 实测同一稿件连跑两次，文件 sha256 就不同——差异只在 zip 条目的 mtime
> （python-docx 写入时设为构建时刻），所有条目内容完全一致。
> 详见 `refactor-plan.md` §7.2。

### P2 · 吸收上游能力

1. 搬 `docx_to_md.py` / `pptx_to_md.py`（MIT），补测试
2. 写 `prompts/02`（项目扫描）、`03`（专利点）、`05`（交底书）
3. 写 `prompts/04` + `tools/cnipa.py`，`playwright` 做成**可选依赖**，没装就降级联网搜索
4. **验收**：拿一个真实项目跑「扫描 → 专利点 → 交底书」全链路

### P3 · 公式与附图

1. 新增 `oh_my_patent/math.py`（`latex2mathml` + `mathml2omml-as`，命名空间与降级都封在里面）
2. 渲染层识别 `$…$`（行内）与 `$$…$$`（块级）
3. `tools/mermaid.py` 自己实现（**不要抄**它那份，见避坑表）
4. **验收**：含公式的稿件产出 `m:oMath`，无 LaTeX 残留；新增 XML 层测试

### P4 · 迭代修订

1. `cli.py` 加 `revise --kind merge|correct`
2. 时间戳命名 + 修订记录留痕
3. **验收**：连续改稿三次，旧稿均在，记录完整

## 5. 避坑清单（都要在实现时防）

| 坑 | 出处 | 我们的做法 |
| --- | --- | --- |
| **mermaid 写死 macOS Chrome 路径** | `wps-skills/.mmdc_chrome.json` | 自己实现，Chrome 路径从环境探测 |
| **CNIPA 靠 Playwright + 活站** | `cnipa_epub_*.py` | 可选依赖；站改版即失效，必须有降级 |
| **未设 `w:hint`** | 第三方 `md_to_docx.py` | 我们已有 `hint="eastAsia"`，不能跟着漏 |
| **零 XML 层校验** | 三套**全都没有** | 保留并扩展我们的拆 zip 测试 |
| **安装脚本改写用户配置** | `auto-install.ps1` 写 `~/.claude/settings.json` | 我们不提供写配置的脚本 |
| **工具数量膨胀** | `wps-skills` 235 个工具 | 我们 CLI 保持 5 个子命令的克制 |
| **测试依赖真实联网** | `test_cnipa_epub_chain.py` | 我们的测试一律离线可跑 |

## 6. 我方代码已修（本次调查顺带发现）

- `schema.py`：删除两处**重复定义**（`summary_parts`、`summary_is_structured` 各写了
  两遍，后者覆盖前者；两处逻辑等价，属开发过程遗留的死代码）
- `lint_ai.py`：清除死导入 `snippet`
- 验证：96 项测试全绿，四示例自检结果不变

> 注：第四路调查报告称这两处重复「行为不一致」，经核查**描述有误** ——
> 两处逻辑等价（一处用元组推导、一处用 if 追加，过滤空项的行为相同）。
> 是重复定义，不是行为分歧。
