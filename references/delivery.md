# 交付规范

回到 [主流程](../SKILL.md)。导出和验收时读取。

## 文件

DESIGN.md 为 Extended：简介、Tokens — Colors、Tokens — Typography、Tokens — Spacing & Shapes、Components、Do's and Don'ts、Surfaces、Elevation。
DESIGN.compact.md 为 Compact：简介、Colors、Typography、Spacing & Layout、Components、Do's and Don'ts、Elevation、Surfaces。
两版都不输出 Imagery 及后续叙述、Coverage & Evidence 或 Quick Start。
Extended 的字体摘要、Type Scale、间距尺度、圆角与可选阴影按小节分组；组件用 Role 和自然语言样式说明。
Compact 精简表格列与间距说明，保留所有已审核条目，不简单截取前12条。
tokens.css / tailwind.css / design-tokens.json 为 Extended；对应 .compact.css / .compact.json 文件为 Compact。
Compact 的可执行格式只含颜色（含渐变）和字体；Extended 含全部分类与合法布局变量。
详细证据、覆盖缺口与原始样式在 design.json、evidence 与 JSON 扩展中查看。
design-tokens.json 使用 $type/$value/$description 和自有扩展字段。
单色在文档、CSS、Tailwind、JSON 的 $value 和预览中统一为小写 hex：
不透明色使用 #rrggbb，透明色使用 #rrggbbaa；RGB、HSL、Lab、Oklab、Oklch 等支持的颜色空间均先转换为 sRGB。
design.json、evidence 和 $extensions.computedValue 保留实测原值，sourceDeclarations 保留可匹配的源声明。
超出 sRGB 色域的颜色按通道裁剪并在 $extensions.normalization 中标记；8 位量化和裁剪可能改变宽色域颜色，不能称为无损进制转换。
无法解析的颜色保留原值并说明缺口，不冒充已转换成功。
这是面向 CSS 的交换格式，不宣称已验证每个设计工具的导入合同。
渐变在文档表格与预览标签中统一显示 Gradient，包括使用 in oklab 插值的渐变。
CSS、Tailwind 和 JSON 的 $value 保留可执行的完整渐变函数，其色标转换为 hex；不能把 Gradient 当作 CSS 值。
shadow 中的颜色也转换为 hex，其他阴影参数与排版组合保持关联。
Tailwind 文件需要用户已有构建环境，preview 无需 Tailwind 或 Node.js。
design.json 为编辑数据，evidence 保存观察、截图和覆盖。
export-manifest.json 与 verification.json 记录一致性检查。
采集截图保存在 evidence 的本地路径中，供核对使用，不在 preview.html 展示；整个目录可搬移，字体文件默认不分发。

## 预览

桌面左视觉参考、右代码导出；移动为 Preview 加四种格式的五个入口。
左栏只含标题与简介、Color Palette、Typography、Spacing & Shape、Guidelines。源站链接只出现一次，放在标题行右侧原标识位置，保留 https:// 等协议，文字右侧显示跳转图标，点击在新标签页打开源站。
Color Palette 按有依据的 Brand/Accent/Neutrals 分组；Typography 先 Type Scale 后 Fonts。
Spacing 为 Density、可选 Base unit、Max width、Section gap、Card padding、Element gap 的用途表；随后 Border Radius 与 Elevation。
不存在独立 Components、Surfaces 或额外叙述、证据区；未知用途值标未确认，不把完整 px 候选列表放到用途表中。
右栏四种导出都支持 Compact/Extended、复制和对应文件下载。
预览容器中性，样本消耗实际变量；标签使用 displayValue，复制使用 exportValue：单色复制 hex，渐变复制完整定义。底层证据仍保留 computedValue。HTML 内嵌数据，可直接打开。
没有远程脚本、CDN 或 fetch 依赖，源站文本通过 textContent 展示。

## 验收

verify 检查摘要、实测等值、类型、引用、新鲜度及衍生文件一致性。
同一模型重导出应字节一致；修改模型后先 export，再 verify。
程序通过不替代视觉检查，浏览器还需检查：
- 桌面与移动没有页面横向溢出；代码区域可自身滚动。
- 四格式、两种文档、键盘导航、复制和实际下载。
- 色块、字体、组件与相同源视口证据一致。
- 超长名称、缺失截图/字体、空章节和大量候选的表现。
- 未观测状态与采样限制可见。

达到计划目标或有合理停止说明后，完成主要命名、用途与摘要。
导出前确认布局用途、表面角色与组件说明，不强制整理已排除的额外叙述章节。
存在代表组件时补充说明并比较；不存在时说明原因。
未知分类保留缺口，不自动补造整套暗色、色阶或组件状态。

## 报告

交付 preview、目录、真实页数和状态覆盖。
分开报告程序验证、浏览器检查、人工视觉确认和未验证平台。
默认不安装为全局 Skill、不发布网站或改其他应用配置。
