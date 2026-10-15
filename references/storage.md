# 证据存储与维护

回到 [主流程](../SKILL.md)。首次核对任何观察前读“有界查看”；迁移或清理时再读对应维护章节。

## 存储合同

新观察为 `.json.gz`：压缩信封保存本次元素/条件，sourceRules、sourceVariables和等值匹配规则表使用 `evidence/records/` 的内容哈希引用。
节点保留匹配顺序及引用，规则中的继承、祖先、伪元素、条件与来源身份不会丢失。
样式表和截图沿用内容寻址。压缩不减少元素/规则采样预算。
index.sha256为完整逻辑观察的摘要；共享记录另有逻辑摘要。读取时验证引用和摘要，损坏不能作为成功证据。
新格式和旧JSON都通过scripts/common.py的read_json读取，不直接把gzip文件交给文本读取器。
当前范围只使用有效的页面、视口、配置和检查点；历史文件仍可回溯。
refresh将旧坐标放入index.history，不覆盖其内容文件。没有自动删除或静默历史过期。

## 有界查看

首次核对新旧观察都从此处开始；先用coverage中的snapshot ID查看摘要，再按selector或sourceRuleIndex缩小范围。

```text
<python> <skill>/scripts/design.py inspect --run <run-directory> --snapshot <id>
<python> <skill>/scripts/design.py inspect --run <run-directory> --snapshot <id> --selector <css-selector> --limit 10
<python> <skill>/scripts/design.py inspect --run <run-directory> --snapshot <id> --field sourceRules --offset <sourceRuleIndex> --limit 1
```

默认输出摘要；列表/匹配规则有界截取，完整数据未删。需要历史版本时加 --sha256 <逻辑摘要>。
先看摘要、具体坐标和来源，不把整份大型观察灌入Agent上下文。

## 旧数据迁移

```text
<python> <skill>/scripts/design.py compact --run <run-directory>
```

验证旧观察后压缩，并更新index和JSON模型的文件路径。测量值与人工解释保持原样，旧文件保留。
再次运行幂等；遇到损坏或无法安全处理的符号链接模型停止，不自动删除。
路径变化会使旧export-manifest过期；对已审核模型重新export、verify。
compact只改变存储，不能把失效页面/视口或错误页变成有效证据。

## 引用检查与清理

```text
<python> <skill>/scripts/design.py clean --run <run-directory>
<python> <skill>/scripts/design.py clean --run <run-directory> --keep-history 3
<python> <skill>/scripts/design.py clean --run <run-directory> --keep-history 3 --apply
```

默认dry-run，只列文件和字节数；apply才删除已列出的未使用证据。
不指定keep-history时保留全部历史；指定时按每个坐标保留最近N份历史，当前有效快照始终保护。
失效/已移出范围的当前行会按历史处理。JSON模型、候选与子目录JSON归档引用会额外保护文件，即使超出N。
清理只作用于observations、screenshots、stylesheets、records四个托管目录，持有与采集提交相同的账本锁。
自定义非JSON产物需用evidence/pins.json字符串数组登记要保留的相对证据路径；保留观察即可自动保留其共享依赖。
引用先按运行目录解析，evidence/...与./evidence/...等价，按文件身份保护；pins中的缺失、越界或非证据文件会在删除前报错。
未知压缩归档或符号链接归档会阻止清理，避免猜测它是否仍引用证据。
符号链接检查包含文件、目录和断链；不跟随链接读取外部归档。阻断时index及证据保持原样。
build、export、verify与采集提交、compact、clean使用同一证据锁，避免维护过程抢先删除尚未保存模型引用的证据；锁忙时稍后重试。手工编辑文件应与维护操作串行。
先核对dry-run，按用户已有删除授权使用apply；没有授权时只报告建议。历史解释仍需保留时不要仅按当前index删除文件。
