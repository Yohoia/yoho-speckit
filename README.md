![SpecKit：从网站观察到设计文件](assets/readme/hero.svg)

# SpecKit

把网站的视觉语言整理为有来源依据的设计文件和本地预览。
展示名称为 **SpecKit**，安装标识与 Skill 目录名为 `speckit`。

![测试样例的排版、颜色与圆角示意](assets/readme/specimen.svg)

同一份设计模型导出文档、样式和可预览文件；原始CSS、元素计算样式、匹配候选和用途解释分别保存。

[开始使用](#开始使用) · [交付文件](#交付文件) · [采集与边界](#采集与边界) · [开发与来源](#开发与来源)

## 开始使用

让 Agent 安装：

```text
请帮我安装这个 Skill：https://github.com/Yohoia/yoho-speckit
```

也可使用 Skills CLI：

```bash
npx skills add Yohoia/yoho-speckit --skill speckit
```

安装前准备 **Python 3.10+、Node.js 22+、Chrome/Chromium**。
采集只使用本地浏览器的CDP接口，无需npm依赖、SDK或API Key。
浏览器不在默认位置时，设置 `SPECKIT_CHROME_PATH` 为可执行文件路径。
运行 `python3 scripts/design.py doctor` 可检查依赖；Windows使用 `py -3`。

首次请求示例：

```text
提取这个网站的设计规范，生成 DESIGN.md 和可预览的样式文件：<网址>。只分析这一个页面。
```

手动安装时，把本仓库复制为 Agent 的 `speckit` Skill 文件夹；也可直接引用 [SKILL.md](SKILL.md)。
依赖安装由用户选择，Skill不会自动安装软件或更改个人浏览器配置。

## 交付文件

输出保存在Skill外部的新目录，整个目录可搬移。

| 文件 | 用途 |
| --- | --- |
| `DESIGN.md` / `DESIGN.compact.md` | 完整与精简设计参考 |
| `tokens.css` / `tokens.compact.css` | CSS Variables：完整分类 / 颜色与字体 |
| `tailwind.css` / `tailwind.compact.css` | Tailwind v4：完整主题 / 颜色与字体 |
| `design-tokens.json` / `design-tokens.compact.json` | CSS方向的Design Tokens交换文件 |
| `preview.html` | 双栏参考页，四格式切换、复制与下载 |
| `design.json` / `evidence/` | 可编辑模型、观察、截图、原始CSS及覆盖记录 |

预览内嵌HTML/CSS/JS、展示字体与头像，无远程脚本或CDN依赖。
左侧为标题与源站链接、简介、Color Palette、Typography、Spacing & Shape、Guidelines；不展示采集截图。
四格式都有Compact/Extended。文档到Elevation/Surfaces结束，未确认项和证据保存在数据文件中。
单色导出为支持范围内的hex，透明色保留alpha；渐变标签显示Gradient，执行文件保留完整定义。
宽色域裁剪单独标记，未支持颜色保留原值并报告转换缺口。

## 采集与边界

![工作流程：采集证据、解释用途、统一导出与验证](assets/readme/workflow.svg)

**唯一采集方案是本地Chrome/Chromium＋CDP。** 一个批次复用一个隔离的无头浏览器，临时用户配置不包含个人登录态；完成后清理自己的浏览器与配置。

- **页数**：single仅输入页；standard通常3个代表页、最多5页；extended使用用户给定上限。没有新增信息可提前停止。
- **视口**：默认桌面1440×1000、窄屏390×844，按CSS视口测量；不宣称模拟真实手机硬件。
- **走查**：默认3个滚动检查点，窗口和内部滚动容器共用每个视口最多24步；容器发现和数量也有预算，未完整观察会记录缺口。
- **元素**：默认最多1200项，代表标题、导航、输入和行动入口优先；真实规则/字体默认采样80个代表元素，预算可调整。
- **状态**：支持default、滚动检查点，以及指定元素的hover/focus。指定目标优先进入采样，并核对实际状态；展开、登录和业务状态不自动执行，未观察状态保持未验证。
- **来源**：计算样式证明当时的数值；匹配规则是候选，不直接等于层叠获胜声明。字体栈与实际渲染字体分开记录。
- **覆盖**：Canvas/WebGL、Shadow DOM/iframe及未加载内容可能无法全面测量；不能因此声称恢复了完整官方设计系统。
- **数据**：证据留在本地，页面正常访问其资源服务器；不将观察发给额外的云端提取服务。原始CSS不被改写，字体文件默认不再分发。
- **恢复**：观察使用gzip和共享规则引用，截图/原始CSS内容寻址；配置改变自动重采，历史与当前有效范围分开。失败保留成功文件与任务归属，再次build产生候选，保留人工解释。

只采审核后的公开页面范围。截图为JPEG视觉证据，不作无损像素相等的判据。
macOS已实测；Windows/Linux的依赖发现已实现，端到端实机未验证。Tailwind文件需要用户已有构建环境，特定设计工具导入未验证。
详细命令见 [主流程](SKILL.md)、[本地浏览器](references/browser.md)、[交付规范](references/delivery.md) 与 [证据存储](references/storage.md)。

## 开发与来源

| 路径 | 职责 |
| --- | --- |
| `SKILL.md` / `references/` | 执行入口与按阶段读取的规范 |
| `scripts/design.py` | doctor、init、capture、build、export、verify统一入口 |
| `scripts/capture.py` | 计划、预算、恢复与证据提交 |
| `scripts/capture_browser.mjs` / `cdp.mjs` | 浏览器采集 / 隔离进程与协议传输 |
| `scripts/document_guard.mjs` | 当前主文档身份、就绪与导航恢复 |
| `scripts/scroll_walk.mjs` | 窗口和内部容器的有界走查及覆盖缺口 |
| `scripts/common.py` / `ledger.py` / `model.py` | 证据基础合同、当前范围/任务、候选归并与验证 |
| `scripts/storage.py` | 无损压缩/共享记录、旧数据迁移与引用保护清理 |
| `scripts/colors.py` / `reference.py` / `documents.py` / `exporter.py` | 颜色、展示摘要、文档与导出 |
| `scripts/css_safety.py` | CSS执行值资源校验，以及预览共用的资源函数策略 |
| `assets/probe.js` | 共用DOM与计算样式探针 |
| `assets/preview.html` / `preview.css` / `preview.js` | 预览源码；导出时内嵌 |
| `assets/readme/` | 仓库首页插图 |
| `tests/` / `evals/` | 核心/真实浏览器回归，以及固定效果评估请求 |

```bash
python3 -B -m unittest discover -s tests -v
```

浏览器测试只访问本地fixture；无Node/Chrome时明确skip，不冒充端到端验证。
`.DS_Store`、`__pycache__/`和临时运行缓存可清理；运行产物与评审报告位于Skill外部。

0.3版将错误主文档、失效页面/视口排除于当前模型，修正组件变体与来源继承，持久化采集配置与任务恢复，并支持无损存储和有界inspect。compact迁移旧观察，clean默认dry-run；历史清理需显式apply，JSON归档和自定义pins保护引用。

0.2版移除了旧版云端和宿主采集分支。旧证据与模型仍可读取，但新采集只走CDP；既存系统凭据不迁移、不删除。
Design Tokens自有扩展保留历史命名空间 `org.yoho-design-extractor`，以兼容已生成文件。

采用 [MIT许可](LICENSE)。取证、走查和验收方法参考 [website-rebuild](https://github.com/boyang-hu/website-rebuild-skill)，展示结构参考 [Refero](https://styles.refero.design/)。本地采集脚本为项目独立实现。
