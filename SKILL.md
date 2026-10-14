---
name: yoho-design-extractor
description: 从网站网址提取有来源依据的设计规范，生成 DESIGN.md、CSS Variables、Tailwind v4、Design Tokens 和 Refero 式 preview.html。用于网站设计语言分析与设计文件交付；不用于整站复刻、普通内容抓取、网站开发或修改业务代码。单独提供网址但没有设计提取意图时不触发。
license: MIT
compatibility: 核心脚本需要 Python 3.10+，只使用标准库；采集需要宿主浏览器、Firecrawl 连接器、已有 CLI 或 HTTP API 中的一条可用路线。HTTP 路线无需安装 Firecrawl。可选凭据页需要 Node.js 22.18+ 和系统凭据服务。跨平台代码不等于跨平台已实测。
metadata:
  version: "0.1.0"
---

# yoho-design-extractor

把网站的实际设计语言整理为可复用文件和可浏览的样式参考页。
截图证明构图，源声明和计算样式证明数值；设计用途由 Agent 解释。
采集、解释和补全保持分离，所有导出来自同一份 `design.json`。

## 1. 确定范围

以输入 URL 为起点，在新输出目录初始化。
`<python>` 是已确认的 Python 3.10+；`<skill>` 是本 Skill 目录。

```text
<python> <skill>/scripts/design.py init <url> --out <run-directory>
```

默认 standard：通常 3 个代表页面、最多 5 页。
`--mode single` 只采输入页；`--mode extended --max-pages N` 使用用户给定上限。
页面与视口、交互状态分开记录；单页站或新增页面无新增设计信息可提前停止。
输出目录位于 Skill 外部；恢复既有运行时不覆盖其他网站或产物。
此时阅读 [采集规范](references/collection.md)，按不同页面结构选页。
默认扩展同源公开页面，跨域或登录内容采用用户明确指定的范围。

## 2. 选择采集后端

运行只读检查，同时检查宿主浏览器和连接器能力。

```text
<python> <skill>/scripts/design.py doctor
```

优先复用已有能力，不要求用户预装另一套 Skill。

| 环境 | 动作 |
| --- | --- |
| 宿主有可读 DOM 和计算样式的浏览器 | 读取 [浏览器适配](references/browser.md)，运行共用探针 |
| 已有 Firecrawl 连接器 | 按 [Firecrawl 适配](references/firecrawl.md) 和实际工具合同调用 |
| 已有 CLI | 使用采集器的 --transport cli |
| 有运行时凭据或系统凭据 | 使用采集器的 --transport api，无需安装 CLI |
| 缺少云端配置，浏览器可用 | 走浏览器路线 |
| 没有完整采集路线 | 保存证据，说明缺失能力，配置后恢复 |

只有选中 Firecrawl 路线才读取其配置说明。
首次登录、保存凭据或安装依赖按已有授权执行；缺授权时说明影响再询问。
安装与配置不是每次提取的前置步骤。

## 3. 采集并检查证据

先采输入页，检查最终 URL、页面身份、字体状态和采样截断。
从导航候选选不同结构的代表页，更新 plan.json 的 pages 与 selectionNotes。
pages 是 URL 字符串数组；执行前运行 design.py check-plan。
每页采桌面与移动视口；截图、样式和状态标签保持一致。
主题差异、代表组件 hover/focus/可安全展开状态按实际能力观察。
未观察状态写入 coverage.gaps，不用静态 CSS 规则冒充行为验证。
宿主探针结果保存为 JSON 后经 design.py ingest 纳入账本。
Firecrawl 脚本自动采 default 状态、导入并清理会话。

```text
<python> <skill>/scripts/design.py check-plan --run <run-directory>
<python> <skill>/scripts/capture_firecrawl.py --run <run-directory> --transport cli
<python> <skill>/scripts/design.py coverage --run <run-directory>
```

初始计划只含输入页；批采集按当前计划执行，不自动选择整站页面。
相同页面、视口、状态默认复用已成功快照；追加后核对覆盖。
访问失败、挑战页、采样截断和未访问候选写入账本。
认证失败或额度不足时核对状态一次，停止云端调用并保留结果。

## 4. 整理设计规范

阅读 [数据与解释](references/model.md)，生成初始数据。

```text
<python> <skill>/scripts/design.py build --run <run-directory>
```

脚本归并实测值和排版组合，不替 Agent 作审美或语义判断。
阅读 design.json，通过 evidenceIds 回看观察，修改名称、用途和摘要。
解释标 inferred，补充规则标 proposed，无法验证项标 unknown。
补充代表组件、布局、意象、Do/Don't 与 Agent Prompt Guide；附来源依据。
完成解释后将 review.status 设为 reviewed；导出器拒绝未审核候选。
字体栈不等于实际渲染字体；单个间距不证明基础网格。
等色不同义保留语义角色，视口差异保持上下文，渐变和阴影保留完整值。
再次 build 产生 design.candidate.json，保留人工解释过的 design.json。
按新增证据合并候选，不用未审核候选替换已有解释。

## 5. 生成与验证

阅读 [交付规范](references/delivery.md)，生成并验证。

```text
<python> <skill>/scripts/design.py export --run <run-directory>
<python> <skill>/scripts/design.py verify --run <run-directory>
```

交付 DESIGN.md、DESIGN.compact.md、tokens.css、tailwind.css、design-tokens.json、
preview.html、design.json 与 evidence/。
浏览器检查桌面与移动、导出切换、复制、下载，并比较代表样本与源证据。
程序检查类型、引用和导出一致性；视觉质量由浏览器检查与人判断。

## 完成与恢复

报告 preview、输出目录、实采页数、视口/状态覆盖、验证结果和主要缺口。
结果是已采范围的设计参考，不宣称恢复了原始私有设计系统。
预览默认本地文件，不发布网站或发送产物给无关服务。
失败时说明已保存内容、停止阶段和继续所需动作，保留可恢复证据。
