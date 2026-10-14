# Firecrawl 适配与首次配置

回到 [主流程](../SKILL.md)。选中云端路线时读取。

## 路线与依赖

已有连接器直接复用；不适配时用 [浏览器适配](browser.md) 的通用导入入口。
CLI 通过官方 CLI 已有登录态认证，不解析其配置文件提取 Key。
doctor 默认只做本地检测；--cloud-status 才查询云端账户。CLI 采集入口会显式核对认证。
HTTP 只用 Python 标准库并读取 FIRECRAWL_API_KEY，不需要 CLI 或 SDK。
运行时 Secret 管理和官方授权入口优先；Agent 只检查配置状态。
缺少凭据时使用本地浏览器；不会自动登录、安装或索取聊天中的 Key。
自动采集器要求认证，不依赖免 Key 层的能力与速率假设。

## 可选本地凭据页

用户希望配置 API 且没有安全入口时使用 scripts/credential-ui。
先读组件 [使用说明](../scripts/credential-ui/README.md)。
需要 Node.js 22.18+ 和系统后端；不可用时停止，不保存明文。
首次安装依赖按授权在组件目录执行 npm ci --ignore-scripts。
不会安装 Firecrawl CLI 或其他 Skill。

```text
node <skill>/scripts/credential-ui/src/profile.ts status firecrawl
node <skill>/scripts/credential-ui/src/profile.ts setup firecrawl
```

setup 返回本机链接，用户亲自填写保存；Agent 只核对脱敏状态。
缺失退出码 2，后端或配置失败退出码 1；超时先查状态，不反复覆盖。
凭据声明保留既有存储引用以兼容已保存的 Key，改名不触发迁移或删除。
业务通过 profile 仅绑定所需变量：

```text
node <skill>/scripts/credential-ui/src/profile.ts run firecrawl -- <python> <skill>/scripts/capture_firecrawl.py --run <run-directory> --transport api
```

macOS 为 Keychain，Windows 为 Credential Manager，Linux 为 Secret Service。
实测范围见 README；组件不是对同用户任意代码执行的强隔离。

## 实际采集

```text
<python> <skill>/scripts/capture_firecrawl.py --run <run-directory> --transport cli
<python> <skill>/scripts/capture_firecrawl.py --run <run-directory> --transport api
```

按 plan 逐页采桌面和移动 default 状态。
--url、--viewport 可恢复局部，--refresh 重新采，普通恢复跳过成功坐标。
--max-elements 调整采样上限；截断仍保留记录。
默认仅做 links 初采集，--branding 可追加品牌摘要，用量按服务规则。
branding 独立留存，不直接当实测 Token。
复用 scrapeId 经 Interact 跑探针，结束和异常都尝试停止会话。
大结果先压缩并分块取回；后续代码通过已创建 sessionId 执行，避免反复申请浏览器。
默认按低额度方案保守间隔请求，执行期间及时报告进度；限流时停止而不是重复扣费。
会话截图保存本地，不依赖临时远程链接。
maxAge=0 获取新鲜页面，记录最终 URL 和时间。
默认没有自然语言云端代理步骤，避免不可控的跨页操作和成本。
仅传目标 URL 和采集代码，不上传本地文件或浏览器登录态。
认证、额度或明确限流失败不自动重复扣费；保留阶段和 scrapeId。
清理失败写 coverage 并告知需处理会话，不能宣称清理完成。

## 官方依据

- [Scrape 与 branding](https://docs.firecrawl.dev/features/scrape)
- [Interact 与会话费用](https://docs.firecrawl.dev/features/interact)
- [CLI 安装与认证](https://docs.firecrawl.dev/sdks/cli)

服务合同变化时核对官方文档，不猜字段。
