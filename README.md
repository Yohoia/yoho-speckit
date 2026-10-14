# yoho-design-extractor

输入网站网址，得到有来源依据的设计参考：DESIGN.md、CSS、Tailwind v4、Design Tokens 和 Refero 式双栏预览。

它解决两类常见问题：只看截图猜数值，以及不同导出格式互相矛盾。元素样式与原始证据保留，所有导出共用一份可编辑数据。

## 安装

可以直接让 Agent 安装，复制这句话：

```text
请帮我安装这个 Skill：https://github.com/Yohoia/yoho-design-extractor
```

也可通过 Skills CLI 安装：

```bash
npx skills add Yohoia/yoho-design-extractor --skill yoho-design-extractor
```

命令安装需要 Node.js；Skill 核心运行只需要 Python 3.10+ 和可用的采集能力。本仓库根层就是完整 Skill，手动安装时将本目录复制到你的 Agent 支持的 Skill 目录，并将安装文件夹命名为 yoho-design-extractor；也可在支持本地路径的环境中直接引用根层 SKILL.md。无需提前安装 Firecrawl Skill。

## 使用

示例请求：
- “提取这个网站的设计规范，生成 DESIGN.md 和可预览的样式文件：<网址>。”
- “只分析这一个页面。”
- “扩展分析最多 8 页，包含产品和文档。”

默认通常 3 个代表页、最多 5 页；只有不同结构提供新设计信息时才增加页面。单页站可以提前停止。每页默认观察桌面与移动，实际交互状态另计。

## 首次配置

优先复用宿主浏览器、已连接的 Firecrawl 或已有 CLI。HTTP API 适配器只用 Python 标准库，不需要安装 Firecrawl CLI/SDK。

云端 API 可复用运行时 FIRECRAWL_API_KEY。没有安全入口时，随附可选凭据页把用户亲自填写的 Key 保存到系统凭据服务；不会要求把 Key 贴进聊天。

凭据页要求 Node.js 22.18+，首次在 scripts/credential-ui 目录安装依赖：

```text
npm ci --ignore-scripts
node src/profile.ts setup firecrawl
```

无需云端服务时可使用宿主浏览器，凭据页和 Node.js 都不是核心运行前提。云端采集按 Firecrawl 的服务额度与收费规则执行，不自动购买额度。

系统凭据引用保留原有存储标识以兼容此前保存的 Key；Skill 改名不会迁移或删除凭据。

## 输出与修改

产物保存到 Skill 外部的新目录，包含六个交付文件、design.json 和 evidence。preview.html 可直接打开，切换文档/代码、复制或下载。

修改 design.json 后重新生成导出；再次采集不会覆盖人工解释，build 会生成候选供合并。采集失败保留已完成快照。

## 兼容范围

核心需要 Python 3.10+。macOS/Linux 通常用 python3，Windows 通常用 py -3；须先核对解释器。

采集至少需要一种可读 DOM 与计算样式的浏览器能力。随附 Firecrawl 批采集器只自动采默认状态；hover/focus/展开由 Agent 使用浏览器或连接器补充，并记录缺口。

当前开发平台 macOS。其他操作系统未实机验证；凭据组件的 Windows/Linux 适配不代表本 Skill 已在这些平台通过端到端测试。浏览器界面与工具合同依宿主环境，核心文档不绑定某个宿主。

## 数据边界

本地浏览器路线保留本地证据；云端路线将目标 URL 与采集代码发送给 Firecrawl 并由其处理网页。不上传本地文件或浏览器登录态。

默认分析公开页面，扩展同源范围；登录或跨源需要用户明确指定。输出留在本地，不自动发布或全局安装。不恢复私有源码、不承诺全站完整，也不生成未观察到的官方规范。

字体栈不等于字体文件已分发；JSON 是 CSS 导向交换格式，特定设计工具的导入兼容性未验证。

## 开发检查

```text
python3 -m unittest discover -s tests -v
```

可选凭据组件的 check/build/test/test:native 命令在组件 README 中说明。原生测试使用随机假凭据并清理，不使用用户业务 Key。

静态检查、真实采集与行为评估分别报告；静态通过不证明自动触发准确率或审美质量。

## 方法与来源

参考 [website-rebuild](https://github.com/boyang-hu/website-rebuild-skill) 的证据留存思路、[Refero](https://styles.refero.design/) 的展示结构；未移植完整复刻管线或其源站内容。

可选 credential-ui 组件来自 oil-skill-creator，保留随附源代码、测试与 MIT 许可。Firecrawl 与 Tailwind 的服务/构建能力属于各自项目。
