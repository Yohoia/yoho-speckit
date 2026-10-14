# 交付规范

回到 [主流程](../SKILL.md)。导出和验收时读取。

## 文件

DESIGN.md 为完整参考，DESIGN.compact.md 限制基础 Token 展示数量。
tokens.css 为 CSS Variables；tailwind.css 为 Tailwind v4 主题及额外变量。
design-tokens.json 使用 $type/$value/$description 和自有扩展字段。
这是面向 CSS 的交换格式，不宣称已验证每个设计工具的导入合同。
渐变和 shadow 保留完整 CSS 字符串，排版组合保持关联。
Tailwind 文件需要用户已有构建环境，preview 无需 Tailwind 或 Node.js。
design.json 为编辑数据，evidence 保存观察、截图和覆盖。
export-manifest.json 与 verification.json 记录一致性检查。
截图使用本地路径，整个目录可搬移；字体文件默认不分发。

## 预览

桌面左视觉参考、右代码导出；移动为 Preview/Exports 切换。
左栏依次为截图/简介、Color Palette、Typography、Spacing & Shape、
Components、Guidelines、可选叙述章节、Coverage & Evidence。
右栏四种导出，其中 DESIGN.md 有 Compact/Extended；支持复制和下载。
预览容器中性，样本消耗实际变量；HTML 内嵌数据，可直接打开。
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
存在代表组件时补充说明并比较；不存在时说明原因。
未知分类保留缺口，不自动补造整套暗色、色阶或组件状态。

## 报告

交付 preview、目录、真实页数和状态覆盖。
分开报告程序验证、浏览器检查、人工视觉确认和未验证平台。
默认不安装为全局 Skill、不发布网站或改其他应用配置。
