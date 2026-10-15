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
超出 sRGB 色域的颜色按通道裁剪并在 $extensions.normalization 中标记；8 位量化和裁剪可能改变宽色域颜色，不能称为无损进制转换。
无法解析的颜色保留原值并说明缺口，不冒充已转换成功。
未解析的color-mix、相对色或其他颜色运算即使含hex操作数，也不能标为已转换；渐变/阴影按其内部颜色的解析结果报告。
这是面向 CSS 的交换格式，不宣称已验证每个设计工具的导入合同。
渐变在文档表格与预览标签中统一显示 Gradient，包括使用 in oklab 插值的渐变。
CSS、Tailwind 和 JSON 的 $value 保留可执行的完整渐变函数，其色标转换为 hex；不能把 Gradient 当作 CSS 值。
shadow 中的颜色也转换为 hex，其他阴影参数与排版组合保持关联。
Tailwind 文件需要用户已有构建环境，preview 无需 Tailwind 或 Node.js。
design.json 为编辑数据，evidence 保存观察、截图和覆盖。
export-manifest.json 与 verification.json 记录一致性检查。
采集截图保存在 evidence 的本地路径中，供核对使用，不在 preview.html 展示；整个目录可搬移，字体文件默认不分发。

## 证据元数据

证据状态按 [数据与解释](model.md#证据与状态) 判断；这里统一定义JSON交换字段，均位于$extensions.org.yoho-design-extractor中。
design.json、evidence保留原值。observed Token含计算样式证据时，computedValue保留原始计算值。
其余Token使用modelValue保留模型值、evidenceValues逐坐标保留依据及method；仅声明证据不生成computedValue。
sourceDeclarations保留可匹配的源声明，其computedValue来自对应证据的实际计算值；显式声明证据不含该字段。
排版组合逐属性记录computedProperty/computedValue，每个属性最多保留3份来源候选。
normalization描述模型值的颜色转换与裁剪；展示和执行值的规则见上方文件说明。

## 预览

桌面左视觉参考、右代码导出；移动为 Preview 加四种格式的五个入口。
左栏只含标题与简介、Color Palette、Typography、Spacing & Shape、Guidelines。源站链接只出现一次，放在标题行右侧原标识位置，保留 https:// 等协议，文字右侧显示跳转图标，点击在新标签页打开源站。
Color Palette 按有依据的 Brand/Accent/Neutrals 分组；Typography 先 Type Scale 后 Fonts。
Spacing 为 Density、可选 Base unit、Max width、Section gap、Card padding、Element gap 的用途表；随后 Border Radius 与 Elevation。
不存在独立 Components、Surfaces 或额外叙述、证据区；未知用途值标未确认，不把完整 px 候选列表放到用途表中。
右栏四种导出都支持 Compact/Extended、复制和对应文件下载。
预览容器中性，样本消耗实际变量；标签使用displayValue，复制使用exportValue：单色复制hex，渐变复制完整定义。原值和依据按上方证据元数据区分保存。HTML内嵌数据，可直接打开。
没有远程脚本、CDN 或 fetch 依赖，源站文本通过 textContent 展示。
导出预览的CSP只允许内嵌脚本/样式及data字体/图片；CSS执行值与原始声明分开校验，源站链接仍可由用户点击打开。
代码区固定使用与浅色容器匹配的高亮；窄屏工具栏可换行，色块、数值和阴影复制均使用可聚焦控件。

## 验收

verify 检查摘要、实测等值、类型、引用、新鲜度及衍生文件一致性。
同一模型重导出应字节一致；修改模型后先 export，再 verify。
程序通过不替代视觉检查，浏览器还需检查：
- 桌面与移动没有页面横向溢出；代码区域可自身滚动。
- 四格式、两种文档、键盘导航、复制和实际下载。
- 色块、字体、组件与相同源视口证据一致。
- 超长名称、缺失截图/字体、空章节和大量候选的表现。
- 未观测状态与采样限制可见。

导出前按 [审核完成条件](model.md#审核完成条件) 完成语义审核。未知分类按其证据状态保留缺口。
交付时verify.status须为passed；上述浏览器检查逐项记录结果，能力受限的项目列为未验证，并说明对交付的影响。

## 报告

交付 preview、目录、真实页数和状态覆盖。
分开报告程序验证、浏览器检查、人工视觉确认和未验证平台。
默认不安装为全局 Skill、不发布网站或改其他应用配置。
