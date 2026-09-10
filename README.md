# dsh-api-balance

> DSH 插件：**在 DSH 界面里实时显示 DeepSeek API 余额**，并把每一次模型调用的花费按
> 「缓存命中输入 / 缓存未命中输入 / 输出 / 图片」四类拆开归因——回答「钱花在哪里」。

- 技术文档：[`docs/TECHNICAL.md`](docs/TECHNICAL.md)
- 回滚与防崩：[`docs/ROLLBACK.md`](docs/ROLLBACK.md)
- 边界声明：[`NOTICE.md`](NOTICE.md)

---

## 显示在哪里

| 位置 | 内容 | 特点 |
| --- | --- | --- |
| **会话标题右侧的胶囊** | 状态点 + 余额 + 本进程累计花费 + 展开箭头；hover 看详情 | 常驻但不打扰，一眼可见 |
| **点一下胶囊** | 输入框下方就地展开**本对话消费**：本对话花费 / 调用次数 / 缓存命中率 / 输出 tokens + 三档分项条形 + 最近 8 次调用明细（时间、模型、命中/未命中/输出、峰谷、花费） | 不跳页、看完点 × 收起；折叠时零请求零占位 |
| **设置 → API 余额与消耗** | 完整仪表盘：4 张概览卡 + 「钱花在哪里」分项 + 按模型 / 按用途 / 按最近 14 天 / 逐次调用四张表 + 价格表与刷新控制 | 按需展开，空间充裕 |

三个落点都是**追加式**的（`replaceRisk: none`），不会遮挡或替换任何原生界面；样式全部走 DSH 主题令牌，自动跟随明暗主题。

> **这些实时统计不额外花钱、不额外消耗 token。** token 用量是 DSH 调模型时本来就会收到的返回字段，插件只是把它读下来做本地加法；唯一的对外请求是余额查询本身（默认 60 秒一次，不计费）。关掉插件省不下模型的钱，它只是把已经花掉的钱显示出来。
>
> **币种**：花费按 **人民币（¥）** 展示——官方价格表以美元发布，插件按固定汇率 `1 USD = 7.10 CNY` 折算（改 `src/core/format.js` 的 `DEFAULT_MONEY` 可调）。**余额**按接口返回的币种原样显示，不参与折算。
>
> 胶囊上的 `¥0.36` 是**本进程**（= 本次 DSH 启动）以来的全部模型调用估算花费。

---

## 快速开始

### A. 立刻看效果（动态插件，重启后消失）

在 DSH 会话里让 agent 执行：先 `cordis_define` 载入 `dist/cordis-define.json`，再 `cordis_run`。
审批通过后界面立刻出现胶囊与设置页。

### B. 常驻使用（已安装，随 DSH 启动）

**本机已安装完成**，只需**完全退出并重启 DSH**，然后验证：

```powershell
pwsh -File E:\DSHarness_Project\repo-one\dsh-api-balance\install\verify.ps1
```

以后改了代码要更新常驻版：

```powershell
cd E:\DSHarness_Project\repo-one\dsh-api-balance
node tools\build.mjs                  # 1. 构建
node tools\verify-artifacts.mjs       # 2. 产物验证（务必跑）
pwsh -File install\install.ps1        # 3. 重装（幂等，自动备份补丁，带回读自检）
# 4. 完全退出并重启 DSH
pwsh -File install\verify.ps1         # 5. 验证
```

想先看看会改什么，不落盘：

```powershell
pwsh -File install\install.ps1 -DryRun
```

### C. 出问题时（不需要 DSH 还活着）

双击桌面 **`DSH API 余额与消耗`** → `[4] 停用 / 回滚常驻插件` → 重启 DSH。

---

## 开发

```powershell
node tools/build.mjs                  # 唯一的构建步骤：合成「动态」「常驻」两个平面的产物
node tools/verify-artifacts.mjs       # 不启动 DSH 的产物验证（两个平面共 6 项，含空 ctx 降级路径）
node tools/probe-balance.mjs          # 不依赖 DSH 的余额自检（只从环境变量读密钥）
```

改代码只改 `src/`，然后重新 `node tools/build.mjs`；**永远不要手改 `dist/`**（它是生成物，已 gitignore）。
**提交前务必跑一次 `node tools/verify-artifacts.mjs`**——它已经在 v0.1.0 抓到过一个会让常驻平面加载失败的构建缺陷（见技术文档 §10 附录）。

---

## 目录

```text
src/core/          ★ 纯函数层（零依赖）：价格表、账本聚合、余额解析、格式化
src/host.body.js   Host 半：余额抓取 + llm/stream 用量采集 + 计费
src/client.body.js Client 半：胶囊 + 仪表盘
config/pricing.json 外部价格覆盖表（官方调价时改这里，不动代码）
tools/build.mjs    ★ 唯一的构建点：把上面这些合成为两个平面的产物
tools/desktop-admin.ps1  桌面管理菜单（也是应急入口）
install/           常驻安装 / 卸载回滚 / 验证
docs/              技术文档 + 回滚方案
dist/              构建产物（gitignore）
```

---

## 设计要点（详见技术文档）

- **一份源码、两个平面**：`build.mjs` 把同一批源文件合成为「动态 Package 载荷」与「常驻 npm 包」，两个平面不可能漂移。两个平面唯一的差异（Host↔Client 通道）被收敛成 `installTransport()` / `callHost()` 两个函数。
- **零第三方运行依赖**：没有 `node_modules`，没有打包器。常驻平面的 client 包是手写的 `__ModuleLoader__` 工厂，只 `require('react')`。
- **用量采集不遗漏**：监听 `llm/stream`，DSH 的每一次模型调用（含子代理、上下文压缩、标题生成）都经过这里。
- **密钥不出进程**：由 DSH 官方 `credentials` 服务解析，只经 curl 的 **stdin** 传递，不进 argv / 环境变量 / 日志 / RPC。
- **失败必降级**：任何网络、解析、凭据错误都收敛成一行可读文本显示在界面上，绝不向上抛、绝不影响模型调用。

---

## 状态

| 能力 | 状态 |
| --- | --- |
| 常驻版 Host 半 | ✅ **已安装并跑通真实数据**（`/dsh-api-balance/snapshot` 返回 200，余额读取成功） |
| 常驻版 Client 半 | ⚠️ 刷新一次页面（或重启 DSH）即可看到界面 |
| 动态平面 | ✅ 已验证（`apibal-1` 的 pkg-1/pkg-2 均保留，当前为让位而 stopped） |
| 版本更新流程 | ✅ 已实测（pkg-1 → pkg-2，DSH 全程未中断） |
| 构建 / 产物验证 | ✅ `npm run build` + `npm run verify` 全 6 项通过 |
| 桌面快捷方式 | ✅ 已创建 |
| 计费口径 | ⚠️ 估算值（仅本进程存活期间，按官方标价 × 固定汇率，非账单实扣） |
