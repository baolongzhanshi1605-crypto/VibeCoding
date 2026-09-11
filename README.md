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
| **会话标题右侧的胶囊** | 状态点 + 余额 + 累计花费；hover 看详情，**点一下跳到设置里的明细页**（跳转失败则回落成刷新） | 常驻但不打扰；每 5 秒自动刷新；**整颗胶囊都可点击** |
| **设置 → API 余额与消耗** | 完整仪表盘：顶部大号余额 + 4 张概览卡 + 「钱花在哪里」堆叠条与图例 + 按模型 / 按用途 / 按最近 14 天 / 逐次调用四张表 + **累计数据与控制**（含 `重置累计` 与 `回填历史消耗`） | 按需展开，空间充裕 |

两个落点都是**追加式**的（`replaceRisk: none`），不会遮挡或替换任何原生界面；样式全部走 DSH 主题令牌，自动跟随明暗主题。

> 交互模型刻意保持简单：**胶囊只负责「显示 + 刷新」，一切明细都在设置页**。
> v0.2 曾在输入框下方加过一个可展开面板，实测难用又难维护，v0.4.1 已移除。

> **这些实时统计不额外花钱、不额外消耗 token。** token 用量是 DSH 调模型时本来就会收到的返回字段，插件只是把它读下来做本地加法；唯一的对外请求是余额查询本身（默认每 5 秒一次，不计费）。关掉插件省不下模型的钱，它只是把已经花掉的钱显示出来。
>
> **币种**：花费按 **人民币（¥）** 展示——官方价格表以美元发布，插件按固定汇率 `1 USD = 7.10 CNY` 折算（改 `src/core/format.js` 的 `DEFAULT_MONEY` 可调）。**余额**按接口返回的币种原样显示，不参与折算。
>
> **累计**：胶囊上的 `¥0.36` 是**从第一次运行至今**的全部模型调用估算花费，**跨 DSH 重启保留**。
> 数据存在 `%APPDATA%\dsh-desktop\harness\dsh-api-balance\usage-ledger.json`；设置页可 `重置累计`，或直接删掉整个 `dsh-api-balance` 目录。

---

## 快速开始

### A. 立刻看效果（动态插件，重启后消失）

在 DSH 会话里让 agent 执行：先 `cordis_define` 载入 `dist/cordis-define.json`，再 `cordis_run`。
审批通过后界面立刻出现胶囊与设置页。

### B. 常驻使用（已安装，随 DSH 启动）

**本机已安装完成**，只需**完全退出并重启 DSH**，然后验证：

```powershell
powershell -File E:\DSHarness_Project\repo-one\dsh-api-balance\install\verify.ps1
```

以后改了代码要更新常驻版：

```powershell
cd E:\DSHarness_Project\repo-one\dsh-api-balance
node tools\build.mjs                  # 1. 构建
node tools\verify-artifacts.mjs       # 2. 产物验证（务必跑）
powershell -File install\install.ps1        # 3. 重装（幂等，自动备份补丁，带回读自检）
# 4. 完全退出并重启 DSH
powershell -File install\verify.ps1         # 5. 验证
```

想先看看会改什么，不落盘：

```powershell
powershell -File install\install.ps1 -DryRun
```

### C. 出问题时（不需要 DSH 还活着）

双击桌面 **`DSH API 余额与消耗`** → `[4] 停用 / 回滚常驻插件` → 重启 DSH。

---

## 开发

```powershell
node tools/build.mjs                  # 唯一的构建步骤：合成「动态」「常驻」两个平面的产物
node tools/verify-artifacts.mjs       # 不启动 DSH 的全量验证（39 项，含端到端持久化与文档同步）
node tools/probe-balance.mjs          # 不依赖 DSH 的余额自检（只从环境变量读密钥）
```

改代码只改 `src/`，然后重新 `node tools/build.mjs`；**永远不要手改 `dist/`**（它是生成物，已 gitignore）。

**每次改动按这个顺序走**（技术文档 §0 有完整说明）：

1. 改 `src/**`
2. `node tools/build.mjs`
3. **同步更新 `docs/TECHNICAL.md`**（变更记录 + 受影响章节）
4. `node tools/verify-artifacts.mjs`
5. `powershell -File install\install.ps1` → 重启 DSH
6. 按治理手册 §8 展示清单并获批后提交

> 第 3 步**不是靠自觉**：验证脚本的第 8 节会拿 `package.json` 的版本号去变更记录里找，
> 找不到就 FAIL。忘了写文档，验证当场变红。

---

## 目录

```text
src/core/            ★ 纯函数层（零依赖）：价格表、账本聚合与持久化、余额解析、格式化
src/host.body.js     Host 半：余额抓取 + llm/stream 用量采集 + 计费 + 账本落盘
src/client.body.js   Client 半：胶囊 + 设置页仪表盘
config/pricing.json  外部价格覆盖表（官方调价时改这里，不动代码）
tools/build.mjs      ★ 唯一的构建点：把上面这些合成为两个平面的产物
tools/verify-artifacts.mjs  ★ 39 项自动校验（含模拟重启、回填契约、文档同步）
tools/desktop-admin.ps1     桌面管理菜单（也是应急入口）
install/             常驻安装 / 卸载回滚 / 验证
docs/                技术文档 + 回滚方案
dist/                构建产物（gitignore）
```

---

## 设计要点（详见技术文档）

- **一份源码、两个平面**：`build.mjs` 把同一批源文件合成为「动态 Package 载荷」与「常驻 npm 包」，两个平面不可能漂移。两个平面唯一的差异（Host↔Client 通道、能否持久化）被收敛成包装层注入 + `installTransport()` / `callHost()` 两个函数。
- **零第三方运行依赖**：没有 `node_modules`，没有打包器。常驻平面的 client 包是手写的 `__ModuleLoader__` 工厂，只 `require('react')`；CSS 也是自己插 `<style>`（官方插件同款）。
- **用量采集不遗漏**：监听 `llm/stream`，DSH 的每一次模型调用（含子代理、上下文压缩、标题生成）都经过这里。
- **密钥不出进程**：优先走官方凭据服务，桌面端退到启动环境；只经 curl 的 **stdin** 传递，不进 argv / 日志 / RPC。
- **累计跨重启**：账本聚合落盘到插件数据目录，临时文件 + rename 原子写、异步 fs、有改动才写。
- **失败必降级**：任何网络、解析、凭据错误都收敛成一行可读文本显示在界面上，绝不向上抛、绝不影响模型调用。
- **服务时序是最容易踩的坑**：常驻插件 `apply` 得比服务注册更早，所以「功能赖以存在的服务」必须 `inject` 等待。完整清单见技术文档 §5.9。

---

## 状态（v0.6.0）

| 能力 | 状态 |
| --- | --- |
| 常驻版 Host 半 | ✅ 已跑通真实数据（`/dsh-api-balance/snapshot` 返回真实余额） |
| 常驻版 Client 半 | ✅ 已注册进界面（胶囊 + 设置页均 `active: true`） |
| 样式 | ✅ 已修复并行为级验证（`<style>` 注入） |
| 凭据解析 | ✅ 已修复并端到端验证（桌面端经 `launchEnvironment`） |
| **累计跨重启保留** | ✅ 已修复并端到端验证（模拟重启后恢复成功） |
| 自动校验 | ✅ 39 项全通过（`node tools/verify-artifacts.mjs`） |
| 桌面快捷方式 | ✅ 已创建 |
| GitHub 异地备份 | ✅ 远程分支 `dsh-api-balance`（`tools\push-backup.ps1` 刷新） |
| 计费口径 | ⚠️ 估算值（按官方标价 × 固定汇率，非账单实扣） |
