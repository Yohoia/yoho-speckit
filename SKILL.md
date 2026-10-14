---
name: speckit
description: 从网站网址提取有来源依据的设计规范，生成 DESIGN.md、CSS Variables、Tailwind v4、Design Tokens 和 Refero 式 preview.html。用于网站设计语言分析与设计文件交付；不用于整站复刻、普通内容抓取、网站开发或修改业务代码。单独提供网址但没有设计提取意图时不触发。
license: MIT
compatibility: Python 3.10+、Node.js 22+、本机 Chrome 或 Chromium；无需 npm 包和云端 API Key。采集固定使用隔离的本地 CDP 浏览器。macOS 已实测；Windows/Linux 依赖发现已实现，端到端未验证。
metadata:
  version: "0.2.0"
---

# SpecKit

把网站的实际设计语言整理为可复用文件和可浏览的样式参考页。
截图证明构图，计算样式证明观测条件下的数值；用途由 Agent 解释。
原始声明、匹配候选、实测数值与解释分开保存。
所有导出来自同一份审核过的 design.json。

## 1. 检查环境与初始化

`<python>` 是 Python 3.10+；`<skill>` 是本 Skill 目录。
macOS/Linux 通常用 python3；Windows 通常用 py -3。

```text
<python> <skill>/scripts/design.py doctor
<python> <skill>/scripts/design.py init <url> --out <run-directory>
```

doctor 为只读本地检查；ready=true 后继续。
缺少 Node 或 Chrome 时按 [本地浏览器](references/browser.md) 的环境说明处理。
依赖安装采用用户已有授权；未准备好时保留运行目录并停止采集。
唯一采集入口是 design.py capture；使用一次性浏览器配置，不复用个人登录态。
输出目录位于 Skill 外部，不覆盖其他网站或无关文件。
默认同源公开页面；用户明确指定跨源范围时更新 authorizedOrigins。

## 2. 确定代表页面

阅读 [采集规范](references/collection.md)，先采输入页，再检查导航候选。
默认 standard 通常3页、最多5页；不同模板优先，同模板不凑数量。
`init --mode single` 只采输入页；extended 需要用户给定 max-pages。
把审核过的 URL 写入 plan.pages 字符串数组，记录 selectionNotes。
没有新增设计信息时可提前停止，说明原因和未访问候选。
计划变动后重新 build 并合并解释，避免沿用旧覆盖信息。

```text
<python> <skill>/scripts/design.py check-plan --run <run-directory>
<python> <skill>/scripts/design.py capture --run <run-directory>
<python> <skill>/scripts/design.py coverage --run <run-directory>
```

采集默认逐页观察桌面与移动，各有顶部和滚动检查点。
截图、样式、URL、视口和状态按同一快照保存。
检查最终页面身份、字体/图片就绪、截断、浏览器错误和未读样式表。
挑战页或异常不能冒充成功目标；partial 时先读 failures，再局部恢复。

## 3. 补充状态与核对证据

需要 hover/focus 时选择实际代表元素，用同一入口采集。
详细预算和命令参数见 [本地浏览器](references/browser.md)。

```text
<python> <skill>/scripts/design.py capture --run <run-directory> --viewport desktop --state hover --selector <css-selector>
```

未观察的状态写入 plan.gaps，不用声明存在冒充行为验证。
滚动检查点不是交互状态；只测 hover 也不证明 focus 和展开状态。
来源是命中候选时保持该标记，不把候选直接说成最终获胜声明。
真实渲染字体与声明字体栈分别核对，缺少能力时记录 unknown。
普通重跑复用完成坐标；refresh 在验证新结果后更新账本。
旧截图和观察保持可追溯，失败时保留已有成功快照。

## 4. 整理设计规范

阅读 [数据与解释](references/model.md)，生成初始候选。

```text
<python> <skill>/scripts/design.py build --run <run-directory>
```

程序归并数值与排版组合，Agent 回看证据解释名称、用途和摘要。
observed 是与原始证据等值的实测；inferred 是附依据的解释。
proposed 是补充规则；无法验证的字段为 unknown。
整理代表组件、布局用途、表面层级与 Do/Don't，附 evidenceIds。
同值不同用途可保留不同角色；视口和状态差异保持证据上下文。
单个间距不证明基础网格，声明字体不证明真实字体已加载。
未支持的颜色编码保留原值与缺口，不宣称转换成功。
只整理交付需要的章节，不补已排除章节的占位内容。
解释完成后将 review.status 设为 reviewed。
再次 build 只写 design.candidate.json；审核新证据后合并至 design.json。

## 5. 导出与验证

阅读 [交付规范](references/delivery.md)，生成并验证九份文件。

```text
<python> <skill>/scripts/design.py export --run <run-directory>
<python> <skill>/scripts/design.py verify --run <run-directory>
```

四格式保留 Extended/Compact，预览保持既有四个视觉模块。
单色导出使用支持范围内的 hex；渐变标签为 Gradient，执行值完整保留。
在预览中核对桌面/移动、格式切换、复制和下载。
核对代表数值与来源文件；程序一致性通过不等于提取准确率。
文件内容有变化时回到模型修改，再统一导出。

## 完成与恢复

交付 preview、目录、实采页面与状态、检查结果和主要缺口。
说明候选来源、动态页面、未读取内容与字体回退等影响。
结果是已采范围的设计参考，不宣称恢复私有官方设计系统。
默认本地交付，不自动发布、安装其他 Skill 或改浏览器个人配置。
失败时报告保存位置、停止阶段和恢复命令，不自动换采集后端。
