# 本地 Chrome/CDP 采集

回到 [主流程](../SKILL.md)。环境检查、采集或恢复时读取。

## 环境

需要 Python 3.10+、Node.js 22+、本机 Chrome/Chromium。
只有本地 CDP 这一条采集路线；没有 npm、SDK 或 API Key 配置。
运行 doctor 检查版本与浏览器路径；检查不启动浏览器或访问网站。
Chrome 非默认位置时设置 SPECKIT_CHROME_PATH 为可执行文件路径。
安装依赖按用户授权和平台官方安装方式进行，不自动安装或降级后端。

采集器启动独立 headless 浏览器，用随机调试端口和临时用户配置。
只连接自己启动的 about:blank 页面，不连接已有浏览器或个人会话。
临时调试入口绑定本机；结束/取消清理自己的进程和临时配置。
每次采集批次复用一个浏览器，页面之间重新导航。

## 采集入口

```text
<python> <skill>/scripts/design.py capture --run <run-directory>
```

--url 从已有 plan.pages 中选择一页；--viewport 选择已有视口名。
默认最多1200个可见布局元素，标题/导航/输入/行动入口优先。
--max-elements 允许1–5000；--max-matched 为实际规则/字体采样数量，默认80、允许0–500。
--checkpoints 为1–4，默认3：顶部及分段滚动状态。
每个视口的窗口与内部容器共用24次滚动预算，首次复位也计入其中；重要资源有有限等待。
容器发现最多检查10000个DOM节点，最多跟踪4个具有可测布局的垂直滚动容器，优先当前视口中的大容器；不走查表单控件内容。
首次可见时核对窗口和容器的起点，初始已滚动则尝试一次复位。scrollWalk记录坐标、startedAtTop、coveredTo、rangeComplete及预算；只有从起点连续覆盖到末尾才算走完。复位失败、跳过区间、超预算、横向区域、不可达或停滞均保留缺口。
配置一致的已完成坐标复用；宽高、检查点或预算改变时自动更新对应坐标。
当前coverage核对所请求的检查点，旧检查点与历史数据不冒充当前覆盖。

## 交互状态

```text
<python> <skill>/scripts/design.py capture --run <run-directory> --viewport desktop --state hover --selector <selector>
<python> <skill>/scripts/design.py capture --run <run-directory> --viewport desktop --state focus --selector <selector>
```

只支持明确的 default/hover/focus，不执行表单提交、交易或任意点击脚本。
hover 移动鼠标到目标中心；focus 请求目标焦点。采集后的样式是观测状态。
选择器必须匹配本次页面中的元素；选不到时失败，不替换成别的目标。
目标必入元素样本，并优先占用规则/字体采样名额；interaction记录实际元素ID与唯一坐标。
目标无法测量时采集失败。max-matched=0只测计算样式，明确记录目标来源/字体未采样。
展开、登录或业务状态不在当前自动采集范围，记录未验证。

## 证据与恢复

Node 将快照暂存，Python 验证来源、视口、图片及样式表摘要后提交。
JPEG 截图用于视觉核对，不能作为无损像素相等的裁判。
观察使用gzip信封与共享规则引用，截图和原始CSS按内容哈希存储；index原子更新。
查看或维护运行目录见 [证据存储](storage.md)，旧JSON仍可读取。
主文档4xx/5xx不作为目标证据；图片等子资源错误只记录缺口。
有明确Document状态时以其身份为准，同URL的失败Fetch不代替主文档状态；缺少身份的旧观察采用保守兼容检查。
每检查点按当前主框架/loader核对Document，观察保存documentIdentity。滚动、交互、来源与截图采样前后核对身份；文档切换丢弃该次未提交结果，最多重试两次，错误文档或越界来源不交付。history同文档路由可保留。
页面/状态失败时保存已成功结果，记录failures与attempt/任务归属；退出码2表示需要恢复。
重跑完成同配置失败任务后转入已解决历史；配置或范围取代的失败标为superseded。
浏览器被取消或超时时尝试先终止并清理自己的进程。

```text
<python> <skill>/scripts/design.py capture --run <run-directory> --url <planned-url> --viewport mobile
<python> <skill>/scripts/design.py capture --run <run-directory> --refresh
```

refresh 更新成功坐标，仍保留旧内容文件；旧模型随后需重新 build 并合并解释。
更改计划、状态或页面后，不用旧 coverage 冒充当前覆盖。
旧版运行数据仍可读，但不保留旧版云端/宿主采集入口；系统中既存凭据不操作。
