# 宿主浏览器适配

回到 [主流程](../SKILL.md)。宿主提供浏览器时读取。

## 共用探针

先阅读宿主浏览器文档，使用其支持的接口与权限。
读取 assets/probe.js，把函数文本传入只读页面求值能力。
文件是函数表达式，不需要在源站插入 script 标签或安装软件包。
完整 Playwright 调用形式为：

```javascript
const observation = await page.evaluate(probeFunction, { maxElements: 600 });
```

字符串接口使用宿主文档支持的函数文本调用方式。
先滚动走查并等待字体，再在指定状态采集。
探针不自动改变视口、滚动或状态；由宿主控制这些条件。

## 保存并导入

保存 observation 为运行目录 incoming 下的 JSON。
它必须包含探针的 url、viewport、elements 等字段，不能只存截图分析。
能保存截图时写入运行目录 evidence/screenshots。

```text
<python> <skill>/scripts/design.py ingest --run <run-directory> --input <observation-file> --backend browser --state default --viewport-name desktop --screenshot <optional-local-file>
```

移动视口使用 mobile 标签，实际改变状态后使用对应 state 标签。
截图路径必须在运行目录内；缺失时 coverage 显式标注。
重复坐标默认不覆盖；查看结果后可用 --replace 更新该快照。

## Firecrawl 连接器

连接器遵循实际工具合同，不猜工具名和字段。
branding 为初提取；实测通过 executeJavascript、Interact 或 Browser 跑共用探针。
保存 observation 后用同一 ingest 命令，backend 设 firecrawl-connector。
连接器缺少浏览器代码能力时，保留品牌摘要，改用宿主浏览器补齐。
Markdown 或 branding 不能伪装成探针输出。
