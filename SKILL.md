---
name: oh-my-patent
description: 自动化专利 SKILL，把一句话的技术想法变成可提交的专利申请文件（说明书、权利要求书、摘要、附图、简要说明），生成的 .docx 同时适配 WPS 与 Microsoft Office。当用户要求撰写、起草、生成、排版、检查专利或专利申请文件，或提到发明专利、实用新型、外观设计、权利要求书、说明书、技术交底书转申请文件、专利合规自检时使用。触发词：专利、专利申请、撰写专利、写专利、发明专利、实用新型、外观设计、权利要求书、说明书、专利摘要、技术交底书、专利申请文件、专利格式、专利排版、patent、claim drafting。
---

# oh-my-patent

**一句话自动化专利 SKILL，同时适配 WPS、Office。**

## 这个 Skill 做什么

把「一句话」变成「可提交的申请文件」：

```
用户的一句话 / 技术交底书 / 论文 / 产品文档
        │
        │  ① 你（AI）负责：理解技术方案、撰写正文
        ▼
   稿件 .md（结构化 Markdown）
        │
        │  ② 脚本负责：版面、格式、兼容性
        ├─ lint    形式合规自检
        └─ build   渲染成 .docx
        ▼
   申请文件 .docx（WPS 与 Office 版面一致）
```

**分工是刚性的**：内容的正确性由你负责，格式的正确性由脚本负责。
不要试图手工拼 `.docx`，也不要为了「格式好看」去改脚本产的 XML。
格式问题一律通过命令行选项调整，选项不够用就改 `oh_my_patent/spec.py`。

## 怎么用这个 Skill

本 Skill 采用**渐进式披露**：本文件只做编排。每一步的完整指令在 `prompts/` 下，
**用到哪一步才去 Read 哪个文件**——不要一次性全读。

### 路由判定表

先按用户的说法定去向，再看下面的通则。

| 用户这样说 | 前置门禁（不满足就停下说明） | 进入 | **明确不要做** |
| --- | --- | --- | --- |
| 写专利、起草申请文件、发明专利、实用新型、外观设计、权利要求书、说明书 | 无 | `prompts/01-intake.md` → `06` → `07` | 不要跳过 `01` 直接写正文；类型没定就动笔，后面全要重写 |
| 检查这篇专利稿、合规自检、格式对不对 | 已有稿件文件 | `prompts/07-self-check.md` | 不要为了让它通过而删掉合规内容 |
| 帮我扫描项目、项目里挖专利点、查新、写交底书 | —— | **未实现（P2）**，如实告知 | **不要**按 `prompts/02`~`05` 的规格假装执行——那几份是待建规格，不是可跑流程 |
| 我已经有 Word/PPT 交底书 | —— | 请他另存为文本或 Markdown | **不要**假装能读 `.docx` / `.pptx` |
| 改一下这篇、这里写错了、再补充一点 | 已有稿件 | **未实现（P4）**，可手工改稿后重跑 `07` | 不要覆盖旧稿 |

### 通则

- **工具归属**：所有对外脚本在 `tools/`，但真正的逻辑在 `oh_my_patent/` 包里。
  不要在 `tools/` 里堆业务逻辑——那样就没法自动化测试了。
- **单一入口**：`python tools/patent.py <子命令>`。不要绕过它直接调内部模块。
- **交付末块**：给用户的交付说明统一以「**交付后请确认**」收尾，列出需要他确认的事项。
- **能力自述**：用户问「你能做什么」时，如实说明当前可用的是
  「定类型 → 撰写 → 自检 → 出文件」，并明确讲清上游的扫描/挖掘/查新/交底书
  与迭代修订**尚未实现**。不要为了显得能干而模糊这一点。

## 命令行速查

完整选项见 `prompts/06-specification-build.md`。

```bash
python tools/patent.py info      稿件.md                 # 确认稿件被正确理解
python tools/patent.py template  invention -o 稿件.md     # 生成骨架
python tools/patent.py lint      稿件.md                 # 形式合规自检
python tools/patent.py lint      稿件.md --json          # 结构化结果
python tools/patent.py build     稿件.md -o outputs/申请文件.docx --strict
python tools/patent.py build     稿件.md -o outputs/ --split --page-numbers
```

**务必先 `lint` 再 `build`。** 直接 build 会把错误带进最终文件。

若没装依赖，也可以直接用解释器跑：`python tools/patent.py ...`。

## 交付纪律

- 产物写进 `outputs/`（已 gitignore）。真实案件的稿件不进公开仓库。
- 交付时**同时说明自检中发现的问题**。存在未修正的 `ERROR` 必须明确讲清楚，
  不能只报「已完成」。
- 自检发现问题就**直接改稿**，不要只交一份问题清单。
- **自检清单不写进正文**。申请文件里出现「自检」二字即不合格。

## 边界

- 本 Skill **不生成请求书**，也不代替专利代理师。产出的是文稿主体。
- 自检是**形式检查**，不构成专利性意见。新颖性、创造性、充分公开必须由人判断。
- 涉及真实案件时提醒用户：正式提交前应由具备资格的专利代理师审阅。

## 仓库结构

```
oh-my-patent/
├── SKILL.md          ← 你在这里：编排与路由
├── prompts/          ← 分步指令（渐进式披露，用到才读）
├── oh_my_patent/     ← 分层 Python 包（真正的逻辑）
│   ├── spec.py       版面规范常量（法规要求集中一处）
│   ├── schema.py     数据模型 + 权利要求分段/独权从权判定
│   ├── parser.py     宽容解析（Markdown / YAML / JSON）
│   ├── lint.py       形式合规自检
│   ├── lint_ai.py    AI 类发明的专门自检（2026 新指南）
│   ├── oxml.py       OOXML 底层修补（WPS/Office 双适配的关键）
│   └── render/docx.py
├── tools/            ← 对外脚本（薄，逻辑都在包里）
├── docs/             ← 格式规范与设计文档
├── examples/         ← 可直接跑的示例稿件
├── tests/            ← XML 层验收测试
└── outputs/          ← 产物（gitignore）
```

## 示例

`examples/` 下有四份完整可跑的稿件（发明 / 实用新型 / 外观设计 / AI 方法），
可直接用来验证环境：

```bash
python tools/patent.py lint examples/invention-example.md
python tools/patent.py build examples/invention-example.md -o outputs/申请文件.docx
```
