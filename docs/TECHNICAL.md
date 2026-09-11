# dsh-api-balance 技术文档

> 版本：**v0.7.3** ｜ 最后更新：2026-09-11
> 子项目根：`E:\DSHarness_Project\repo-one\dsh-api-balance`
> 回滚与防崩方案见 [`ROLLBACK.md`](./ROLLBACK.md)；治理边界见项目根 [`../NOTICE.md`](../NOTICE.md)。

---

## 0. 维护约定：文档必须时刻是最新的

用户明确要求「文档更新是最重要的事」。所以这不靠自觉，而是**做成构建期检查**：

```powershell
node tools/verify-artifacts.mjs
```

第 8 节会拿 `package.json` 的版本号去本文档的变更记录里找；**找不到就是 FAIL**，验证不通过。
也就是说「改了代码忘了写文档」会当场被拦住。

每次改动的固定动作（顺序别调）：

| # | 动作 | 为什么 |
| --- | --- | --- |
| 1 | 改 `src/**` | 源码是唯一真相源 |
| 2 | `node tools/build.mjs` | 合成两个平面的产物 |
| 3 | **更新本文档**：变更记录 + 受影响章节 +（新缺陷就加附录） | 文档是本项目真正的交付物之一 |
| 4 | `node tools/verify-artifacts.mjs` | 25 项校验，含第 3 步的文档同步检查 |
| 5 | `powershell -File install\install.ps1` → 重启 DSH | 上线 |
| 6 | `git add dsh-api-balance` → commit（先按治理手册 §8 展示清单并获批） | 留回档点 |

---

## 0.1 三个最常被问的问题

**Q1：界面上能看到什么？**
只有两个入口，刻意的：

| 入口 | 内容 |
| --- | --- |
| 会话标题右侧胶囊 | 余额 + 累计花费；**点一下跳到设置里的本分区**（跳转失败则回落成刷新）；每 5 秒自动刷新 |
| **设置 → API 余额与消耗** | 完整仪表盘：顶部大号余额 + 概览卡 + 「钱花在哪里」堆叠条与图例 + 按模型 / 按用途 / 按最近 14 天 / 逐次明细 + 累计数据与控制 |

> v0.4.1 起回到这个**两入口**的简单模型：胶囊只负责「显示 + 刷新」，一切明细都在设置页。
> v0.2 曾在输入框下方加过一个可展开面板，实测难用且难维护，已移除。

**Q2：那个 `¥0.xx` 是什么？**
**累计**的估算花费：所有模型调用的 token 用量 × 官方标价（按峰谷分别计价）的累加。
**跨 DSH 重启保留**（v0.6.0 起，落盘见 §5.8）。它不是账单实扣值，但是同一口径的近似。
设置页里有 `重置累计` 可以清零。

**Q3：这些实时统计要额外花钱 / 消耗 token 吗？**
**完全不要。** token 用量是 DSH 每次调用模型时**本来就会收到**的返回字段（`usage`），插件只是把它读下来做本地加法——不发额外请求、不消耗额外 token、不占用额外上下文。
唯一的对外请求是余额查询本身（默认每 5 秒一次，余额接口不计费也不消耗 token）。
**关掉这个插件并不会省下模型的任何费用**，它只是把已经花掉的钱显示出来。

---

## 1. 做了什么（一句话 + 验收标准）

**一句话**：一个 DSH 插件，在 DSH 自己的界面里实时显示 DeepSeek API 账户余额，并把每一次模型调用的花费按「缓存命中输入 / 缓存未命中输入 / 输出 / 图片」四类拆开归因，累计数字跨重启保留。

**验收标准（可逐条核对）**：

| # | 目标 | 状态 |
| --- | --- | --- |
| A1 | 在 DSH 界面内直接看到余额，不需要另开网页或终端 | ✅ 会话标题右侧胶囊 |
| A2 | 余额自动刷新，间隔可调 | ✅ 默认 5s，可选 5s / 15s / 1min / 5min |
| A3 | 显示钱花在哪里：缓存命中 / 未命中 / 输出 / 图片 | ✅ 设置页仪表盘（堆叠条 + 图例 + 明细表） |
| A4 | 按官方峰谷价计费（含谷时半价） | ✅ |
| A5 | 按会话归因（Host 按 `sessionId` 记账） | ✅ 数据在 `usage.sessions`，UI 暂未展示（见 §9） |
| A6 | 一份源码同时支撑「动态插件」与「常驻插件」 | ✅ `tools/build.mjs` |
| A7 | 出问题能一键停用/回滚，且不需要 DSH 还活着 | ✅ 桌面快捷方式 → 管理菜单 |
| A8 | **累计数字跨重启保留，可重置** | ✅ v0.6.0，落盘到插件数据目录（§5.8） |
| A9 | 项目可读、可优化、框架可移植 | ✅ 见 §7、§8 |

---

## 2. 用了什么技术

| 层面 | 选型 | 为什么 |
| --- | --- | --- |
| 宿主运行时 | **DSH / Cordis 插件**（Host 半 + Client 半） | 直接复用 DSH 已装载的 `credentials` / `subprocess` / `llm` / `slots` 服务，不重复造轮子 |
| Host 语言 | 纯 JavaScript（无 TS/JSX/打包器） | 动态 Package 不做任何转译，源码即运行时；少一层构建 = 少一处升级 DSH 后炸掉的地方 |
| Client 语言 | 纯 JavaScript + `React.createElement` | Client 半同样不支持 JSX；用 6 行 `h()` 包装替代 |
| 计费模型 | 官方价格表 + UTC 峰谷判定 | 官方页把「缓存命中/未命中/输出」分开定价，且谷时半价——不拆开算就是错的 |
| 用量采集 | 监听 `llm/stream` 瀑布事件 | DSH 每一次模型调用（含子代理、上下文压缩、标题生成）都走这里，是唯一不漏的入口 |
| 余额获取 | `subprocess` 服务 + `curl.exe --config -` | Host 半**没有** `fetch` builtin；`web` 服务的 `WebFetchRequest` 只接受 `{url}`，无法带 `Authorization` 头，所以必须走子进程 |
| 凭据读取 | `credentials` 服务的 `resolve('DEEPSEEK_API_KEY')` | 官方凭据通道，自动覆盖「环境变量 / 托管存储 / .env」三种来源；**agent 全程不读密钥文件** |
| 样式 | `styles.insert(css)` + DSH 主题令牌 `--dsw-alias-*` | 跟随明暗主题，不硬编码颜色，不操作 `document.body` |
| 桌面入口 | `.lnk` → PowerShell 管理菜单 | 插件把 DSH 弄崩时，需要一个不依赖 DSH 的入口去停用回滚 |

**零第三方运行依赖**：没有 `node_modules`，没有 `package-lock`，没有构建工具链。唯一的构建步骤是 195 行纯 Node 标准库脚本。

---

## 3. 架构：一份源码，两个运行平面

### 3.1 为什么是两个平面

DSH 里存在两种让插件生效的方式，各有不可替代的价值：

| 平面 | 机制 | 生命周期 | 审批 | 适合 |
| --- | --- | --- | --- | --- |
| **动态** | `cordis_define` + `cordis_run` 定义一个进程内 Package | 仅当前进程，重启即消失 | 用户点一次允许 | 立刻看到效果、试错、演示 |
| **常驻** | profile 组合补丁新增一行插件 + 本地 npm 包 | 重启后依然在 | 管理员平面（需你批准） | 长期使用、随 DSH 一起启动 |

绝大多数项目会把这两条路写成两套代码，然后慢慢漂移。本项目用**构建期合成**避免这一点（见 §4）。

### 3.2 运行形态差异被收敛成三处适配

两个平面真正的差异只有三处，代码里各用一个机制吸收掉：

```js
// ① Host 半：把 handler 暴露给 Client 的机制不同
installTransport(ctx, handlers)
  ├─ 动态平面：harness.handle(name, handler)      → 'dsh-package-rpc'
  └─ 常驻平面：webServer.register({kind:'exact', path:'/dsh-api-balance/<name>'})  → 'http-route'

// ② Client 半：调用 Host 的方式不同
callHost(method, args)
  ├─ 动态平面：host.call(method, args)            （Package 私有 JSON RPC）
  └─ 常驻平面：fetch('/dsh-api-balance/' + method + '?data=…')（同源 HTTP，无 CORS 问题）

// ③ 能不能持久化：由包装层注入 __storage（共用函数体里不能 import）
__storage
  ├─ 动态平面：null                                （受限求值器没有模块系统 → 仅内存）
  └─ 常驻平面：node:fs/promises 异步存储桥          （累计跨重启保留）
```

判断用的是 `typeof harness !== 'undefined'`、`typeof host !== 'undefined'`、`typeof __storage !== 'undefined'`
——`typeof` 对未声明的标识符永远安全，因此同一份函数体在两个平面都能跑。

> **设计取舍**：常驻平面本来可以用 DSH 官方的 `@Remote` / typert 生成机制做跨端调用，但那需要装饰器、代码生成与额外的包依赖。本项目选择复用 DSH 自带的 `webServer` 注册一条只读 JSON 路由——更少的活动部件，也更容易被后来者读懂。

> ⚠️ **但「能拿到服务」不是理所当然的**：常驻插件 `apply` 得比服务注册更早。
> 第 ③ 处之所以放在包装层，也正是因为共用函数体里没有 `import`；
> 而哪些服务存在、哪些不存在、拿不到该怎么办，是另一个独立问题 ——
> **完整清单见 §5.9，新增任何服务依赖前必查。**

### 3.3 数据流

```text
                  ┌─────────────────────────── Host 半（Node 进程内）───────────────────────────┐
                  │                                                                             │
  DeepSeek 云 ──► │  subprocess.spawn(curl.exe, --config -)                                      │
  /user/balance   │      ▲ stdin 传入 "header = Authorization: Bearer <key>"                      │
                  │      │      （密钥不进 argv、不进 env、不落盘、不进日志）                        │
                  │  credentials.resolve('DEEPSEEK_API_KEY')  ◄── 官方凭据通道                    │
                  │                                                                             │
                  │  ctx.on('llm/stream')  ◄── DSH 每一次模型调用都经过这里                        │
                  │      └─ 透传每个 chunk 的同时，收下 {type:'usage'}                             │
                  │      └─ try/finally 记账：消费方 break / 抛错 / abort 也记账，且不吞异常         │
                  │                                                                             │
                  │  core/pricing.js  峰谷判定 + 三档单价 → core/ledger.js 分维度累加              │
                  │                                                                             │
                  │  buildSnapshot() → 纯 JSON（余额 / 用量 / 价格表元信息 / 记账次数）              │
                  └───────────────────────────────────┬─────────────────────────────────────────┘
                                                      │ dsh-package-rpc  或  /dsh-api-balance/snapshot
                  ┌───────────────────────────────────▼─────────────────────────────────────────┐
                  │  Client 半（浏览器）                                                          │
                  │  ① conversation.session.header.utilities → 余额胶囊（状态点 + 金额 + 花费，点击强刷）│
                  │  ② settings.section                      → 完整仪表盘（卡片/分项条形/四张表/控制项）│
                  └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 构建：把一份源码合成为两个平面

`node tools/build.mjs` 做四件事：

1. **收集** `src/core/*.js`（纯函数，零依赖）与 `src/host.body.js` / `src/client.body.js`（`apply(ctx)` 的函数体）。
2. **去模块语法**：删掉顶层 `import`，把 `export const/function` 的 `export ` 前缀去掉——这样纯函数就能与函数体拼进同一个函数作用域。
3. **产出动态平面载荷** `dist/cordis-define.json`：
   - 只保留 `code.host` / `code.client` 两个「返回 Cordis 插件的函数体」；
   - 额外删掉整行注释（`^\s*//`）并折叠连续空行，把 50KB 压到 41KB；
   - 该变换对字符串安全：行内块注释和 `https://` 这样的行内字符串都不匹配 `^\s*//`（见 `build.mjs` 中的说明注释）。
4. **产出常驻平面包** `dist/package/`：
   - `lib/index.js`：标准 ESM 插件，用 `import` 从 `lib/core/*.js` 取同一批纯函数，函数体逐字复用；
   - `lib/client.js`：**手写的** `window.__ModuleLoader__.load({id, factory})` 工厂包。因为 client 端只依赖 `react`（由 loader 提供），手写完全可行，**不需要 rollup/esbuild/vite**；
   - `package.json`（含 `dsh.client.platform = "web"`）与 `cordis.patch.yml`。

构建完成后 `dist/manifest.json` 记录版本、字节数与四个 SHA-256 前缀，用于核对「跑着的插件 = 仓库源码」。

> **为什么这件事重要**：两个平面的代码不可能漂移，因为常驻平面的函数体是从同一批源文件生成的；动态平面的载荷也是。改一处逻辑，`npm run build` 之后两边同时生效。

---

## 5. 关键技术点

### 5.1 TokenUsage 是「互斥计数」，不是「包含计数」

DSH 的 `TokenUsage` 与 DeepSeek 原始返回**口径不同**，这是本项目最容易算错的地方：

- DeepSeek 原始返回：`prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens`（**包含**关系）；
- DSH harness 约定：`inputTokens` 已经是**扣掉缓存命中之后**的部分（**互斥**关系），命中部分单独放在 `cacheReadTokens`。

证据在 `dsh-llm-deepseek` 的 `mapUsage()`：

```js
return {
  inputTokens: usage.prompt_tokens - (cacheRead ?? 0),   // ← 减掉了
  outputTokens: usage.completion_tokens,
  ...cacheRead !== undefined ? { cacheReadTokens: cacheRead } : {},
  ...reasoning !== undefined ? { reasoningTokens: reasoning } : {},
}
```

所以计费直接按三档各自乘：

```text
费用 = 未命中输入 × 未命中单价 + 命中输入 × 命中单价 + 输出 × 输出单价
         ↑ inputTokens              ↑ cacheReadTokens        ↑ outputTokens
```

如果误以为 `inputTokens` 是总量，会把缓存命中部分按未命中价重复计费——本机价格差是 **50 倍**（0.003 vs 0.15 USD/M），错得会非常离谱。

### 5.2 峰谷计价

官方口径（`api-docs.deepseek.com/quick_start/pricing`）：

- 峰时 = **UTC 周一至周五 01:00–04:00 与 06:00–10:00**，其余为谷时；
- 谷时单价 = 峰时单价 ÷ 2；
- 价格表按 `[谷时价, 峰时价]` 的数组存，`isPeakAt()` 用 UTC 判定，**不依赖本机时区**。

价格表内置在 `src/core/pricing.js`（单一真相源），外部 `config/pricing.json` 可整体覆盖——官方调价时改 JSON 即可，不必动代码。

### 5.3 图片消耗怎么算

DeepSeek 的视觉 token 由 provider 侧计算，DSH 把官方计算器移植进了 `dsh-llm-deepseek` 的 `image-tokens.js`，并通过 `llm.imageRequestPricing(provider, model)` 暴露为服务方法。

本插件的做法：从 `options.messages[].content[]` 里挑出 `type === 'image'` 的块，交给 `priceImages()` 估算视觉 token 数。

> **诚实声明**：这是**调用前**的估算值，用于归因展示；图片最终真正花的钱已经包含在那次调用的 `inputTokens`/`cacheReadTokens` 里，所以仪表盘上「图片消耗」一栏**不参与**费用求和，只回答「钱里有多少是图」。

### 5.4 密钥安全

- 密钥只由 `credentials.resolve()` 在 Host 进程内取出，**立即**写进 curl 的 config 文本，走 `subprocess` 的 **stdin**（`--config -`）；
- argv 里只有 `curl.exe --silent --show-error --max-time 20 --config -`，**进程列表看不到密钥**；
- 不写盘、不进日志、不进快照、不跨 RPC 边界——Client 侧只拿到 `{configured: true, source: 'stored'}`，永远拿不到密钥本身；
- `buildCurlConfig()` 会拒绝含空白/引号/反斜杠/换行的密钥，防止 config 注入。
- **本项目的 agent 从未读取 `.credentials.yaml`**（符合治理手册 §6）；`tools/probe-balance.mjs` 也坚持只从环境变量读，且只打印密钥长度与前 6 位。

### 5.5 UI 落点与主题
两个落点都是 **additive 的 `list` 槽**，`replaceRisk = none`，不会遮挡或替换任何原生界面：

| 槽位 | 内容 | 注册键 |
| --- | --- | --- |
| `conversation.session.header.utilities` | 余额胶囊：状态点 + 金额 + 累计花费 + 展开箭头；hover 显示详情，点击展开/收起明细面板 | `{ id: 'dsh-api-balance', order: 40 }` |
| `conversation.session.header.utilities` | 余额胶囊：状态点 + 余额 + 本进程累计花费；hover 显示详情，**点击立即刷新余额** | `{ id: 'dsh-api-balance', order: 40 }` |
| `settings.section` | 完整仪表盘页：4 张卡片 + 分项条形 + 按模型/按用途/按日期/逐次明细 + 价格表与刷新控制 | `{ id: 'dsh-api-balance', order: 60, label: 'API 余额与消耗' }` |

**跨 Slot 的状态共享**：胶囊在标题栏、面板在输入框下方，是两个互不相邻的 Slot。用一个 `apply()` 作用域内的小订阅表（`panelStore` + `usePanelOpen`）把它们连起来——插件停止时随之消失，不写全局变量、不注册服务。

**折叠即零成本**：面板的 `useSnapshot(ctx, timer, open)` 传 `enabled = open`，折叠状态下**不请求、不轮询**，只有一个返回 `null` 的空注册位。

样式全部走 DSH 主题令牌（`--dsw-alias-label-*`、`--dsw-alias-bg-layer-*`、`--dsw-alias-border-*`、`--dsw-alias-state-*`、`--dsw-alias-brand-primary`），因此自动跟随明暗主题与皮肤，**不覆盖全局主题**、不碰产品 DOM 选择器。

> 关于「显示在哪里」的落点决策：**胶囊**负责「一眼看到余额」（常驻、极小、不打扰），**点开胶囊**负责「这个对话花了多少」（就地展开、不跳页），**设置页**负责「钱花在哪里」（空间充裕、维度齐全）。三者共用同一份 Host 快照，口径完全一致。

### 5.6 渲染加固：任何数据异常都降级，不炸界面

Client 半的两个组件都刻意拆成**两段**：

```js
function Dashboard(props) {
  const [snap, load] = useSnapshot(props.ctx, props.timer)   // ① hook 无条件调用（React 规则）
  try {
    return dashboardBody(snap, load)                          // ② 纯渲染，无 hook
  } catch (error) {
    return h('div', { className: 'dab-page' }, /* 一行可读的降级提示 + 重试按钮 */)
  }
}
```

为什么必须这样拆：React 要求 hook 的调用顺序在每次渲染中保持一致，所以 `try` **不能**把 `useSnapshot` 包进去；把渲染部分抽成无 hook 的纯函数后，才能安全地整体 try/catch。

配套的数据兜底：`data.balance || {}`、`data.usage || {}`、`data.pricing || {}`、`data.apiKey || {}`、`(balance.infos || [])`、`usage.models || []`——**任何一层字段缺失都只会让对应的一小块显示为占位，而不是让整个组件抛错**。

对应威胁模型 T3；最坏结果被限制在「该 Slot 区域显示一行降级提示」。

### 5.7 币种：账本以美元记账，展示时折算

官方价格表以**美元**发布（USD / 百万 tokens），而余额接口返回的是**人民币**。两者不做隐式混算：

| 对象 | 口径 |
| --- | --- |
| 账本内部（`ledger`、`summarize()`） | **一律美元**，与汇率解耦，改汇率不会污染历史记账 |
| 花费展示（胶囊、面板、仪表盘全部费用数字） | `fmtCost(usdValue, money)` → 按 `money.rate` 折算成 `money.currency` |
| 余额展示 | `fmtBalance()` → 按**接口返回的币种**原样显示，**不参与折算** |

汇率与展示币种定义在 `src/core/format.js` 的 `DEFAULT_MONEY`（默认 `CNY` / `7.10`），Host 把它放进快照的 `money` 字段，Client 用它格式化。**改汇率只改这一处，然后 `node tools/build.mjs`。**

仪表盘底部的「价格表与控制」会显式写出当前折算关系（`1 USD = 7.10 CNY`），避免出现「这个 ¥ 是哪来的」的疑惑。

> 取舍说明：官方发布价是美元，账单和余额是人民币，两者之间**没有官方汇率接口**。本项目选择固定汇率 + 明示，而不是假装精确。要改成其他币种或换汇率，改 `DEFAULT_MONEY` 即可。

---

### 5.8 累计与持久化：让数字活过重启

**问题**：账本原本是纯内存的，DSH 一重启就归零。用户要求「改成累计的」。

**落点**：

```text
<DSH_HOME>/dsh-api-balance/usage-ledger.json
例：C:\Users\han\AppData\Roaming\dsh-desktop\harness\dsh-api-balance\usage-ledger.json
```

**为什么不放在插件包目录里**：`install.ps1` 每次更新都会**先删掉旧包目录再复制新的**，数据放那儿会被一次普通更新顺手抹掉。也刻意不碰 DSH 的设置/凭据/会话——只是一个插件私有的数据目录，删掉整个目录就等于清零。

**存什么**：只存**聚合计数器**（总花费、各类 token、按模型/按天/按用途/按会话的聚合），
**不存明细环形缓冲** `rows` —— 它只服务于「最近调用」表，而且是唯一会无界增长的部分。
导出时每个聚合维度按花费降序截断到 60 条，防止 `bySession` 随时间无限膨胀。

**写入策略**（三个关键设计）：

| 决策 | 做法 | 理由 |
| --- | --- | --- |
| 什么时候写 | 标脏 + 搭节拍：只在有改动时写，每 5 秒最多一次（余额刷新节拍 / 每次取快照顺带），卸载时收尾写一次 | 不会每次模型调用都写盘 |
| 怎么保证不写坏 | 先写 `*.tmp` 再 `rename` 覆盖 | 中途断电/被杀不会留下半截 JSON |
| 用同步还是异步 | **异步** `node:fs/promises` | 项目红线写着「不在 Host 半引入同步 IO」；文件才几 KB，异步完全够 |

**装载顺序很重要**：启动时 **先装载累计数据、再读余额**。反过来的话首次快照会先闪一次「0 元」再跳到真实值。

**跨平面的现实**：`__storage` 由 `build.mjs` 在包装层注入 —— 常驻平面是真实的 fs 桥，
动态平面注入 `null`（受限求值器没有模块系统），此时插件自动退化为「仅内存」。所以**只有常驻版会累计**。

**损坏处理**：版本号不认识、JSON 解析失败、字段类型不对 —— 一律忽略该字段并保持 0，**绝不抛**。
一个坏掉的账本文件不该让插件失效；而且**不覆盖原文件**，方便人工查看。

`verify-artifacts.mjs` 第 6 节把整条链路端到端跑了一遍（记账 → 落盘 → **用全新上下文重新 apply 模拟重启** → 确认恢复 → 重置 → 坏文件安全性）。

---

### 5.9 常驻插件的服务时序清单 ★ 最重要的一节

**这个项目连续五个缺陷都出在同一件事上**：常驻插件在组合启动过程中 `apply()`，
那时很多服务**还没注册**；而代码遇到「拿不到服务」时是静默降级 ——
于是表现为「装上了但没反应」，一条报错都没有。

下表是踩完之后总结的**权威清单**。任何新增的服务依赖，都必须先来这里查一行：

| 服务 | 桌面端 profile 里 | 用途 | 拿不到时的正确做法 |
| --- | --- | --- | --- |
| `webServer` | **存在，但晚于 apply** | 挂 HTTP 路由 | `ctx.inject(['webServer'], …)` 等它（**不能** `ctx.get` 后静默返回） |
| `slots` | **存在，但晚于 apply** | 注册 UI | `ctx.inject(['slots'], …)` + 导出 `inject` 声明 |
| `timer` | **存在，但晚于 apply** | 定时轮询 | **在 effect 里惰性解析**，不要用注册时捕获的引用 |
| `styles` | **不存在** | 注入 CSS | 自己插 `<style>` 元素（官方 35 个客户端插件同款） |
| `credentials` | **不存在** | 读 API key | 退到 `launchEnvironment` → `process.env`（官方 provider 同款三段式） |
| `launchEnvironment` | 存在（桌面端注入） | 启动环境快照 | 退到 `process.env` |
| `subprocess` | 存在 | 起 `curl.exe` 查余额 | 报错并降级成「余额不可用」 |
| `llm` | 存在 | 估算图片视觉 token | 返回 0（不影响计费主链路） |
| `sessionQuery` | 存在 | 回填历史消耗时读会话事件 | 回填按钮报错并说明原因；不影响实时记账 |
| `fs` | 存在 | —— | 本项目不用（改用包装层注入的 `node:fs/promises`） |

**判别口诀**：

> 常驻插件里，**「功能赖以存在」的服务拿不到时必须等（`inject`），只有「可选增强」才允许降级**。
> 把必须的当可选的，就会得到一个「加载成功但不干活」的插件 —— 而且没有任何报错。

**为什么 `ctx.get` 会拿不到而 `ctx.inject` 可以**：`inject` 是 Cordis 的依赖等待语义，
它会把插件挂起直到服务出现；`ctx.get` 只是当下查表，查不到就返回 `undefined`。
两者的差别在动态平面不存在（动态包是在系统完全启动后才求值的），**所以这个问题只在常驻平面出现**。

> 同样的道理，`ctx.inject` 在两个平面都能安全使用：动态平面的受限 `ctx` 没有这个方法，
> `typeof ctx.inject === 'function'` 判断会自动走「服务已就绪、直接用」那条路 ——
> **一份函数体仍然同时适配两个平面**。

### 5.10 整颗胶囊可点击：`pointer-events` 要反过来设

用户反馈「只有胶囊边缘能点，点文字没反应」。

**根因是我把方向搞反了**。为了让子元素也能响应，我写的是：

```css
.dab-pill *{pointer-events:auto}   /* ❌ 让每个子元素各自吃事件 */
```

正确做法是**反过来**：

```css
.dab-pill *{pointer-events:none}   /* ✅ 子元素全部不吃事件，全落到 button 自己身上 */
```

`pointer-events:none` 的子元素在命中测试里被跳过，事件直接命中底下的 `button`
——不依赖「子元素点击冒泡到父元素」这条链路，因此整颗胶囊（文字、状态点、留白）都是同一个目标。

顺便删掉了之前为此加的透明命中层 `.dab-hit`（不再需要，少一个绝对定位元素）。
另外保留 `-webkit-app-region:no-drag` 与 `user-select:none`（Electron 拖拽区与误选中文字）。

### 5.11 点胶囊跳到设置分区：一个没有官方入口的需求

**约束**：DSH **没有提供「打开设置」的服务**。settings 面板的 `open` 与 `activeId` 是
`dsh-client-ui-settings-general` 里的**组件局部 state**；唯一暴露 `openSection(id)` 的地方是
`settings.onboarding` 步骤的 props，而那只在 onboarding 期间存在
（渲染条件是 `onboardingStep !== undefined`）。已逐包确认，没有别的入口。

**折中方案**（`openSettingsSection()`，全程 try/catch，最坏情况只是「点了没跳转」）：

1. 用 **ARIA 语义**找设置触发器：`[aria-haspopup="dialog"]` —— 可访问性契约，比 CSS module 生成的类名稳定；
2. 面板异步渲染，轮询等待（最多 12×50ms）；
3. 点**我们自己注册的那一行**：按我们自己的 label 文本匹配（找的是自己贡献的内容，不是产品界面元素）；
4. 每一步都要求「恰好命中一个」才动手，否则立刻放弃；
5. 跳转失败 → 回落成「刷新余额」，保证点击永远有用。

**这是一个已知脆弱点，如实记录**：如果 DSH 改了设置触发器的 ARIA 属性，跳转会静默失效
（自动回落成刷新，不会有报错）。修复方式就是把 `openSettingsSection()` 里的选择器按新结构改一下。

### 5.12 回填历史消耗：先解压 zstd 的弯路与正解

**弯路**：最直觉的做法是直接读 `session.jsonl.zstd`。但它是 **append-only 的多帧 zstd**，
`zlib.zstdDecompressSync` 只解第一帧 —— 实测 15 个文件、30MB 压缩、解出来 **0 字节**且不报错。

**正解**：用官方的 **`sessionQuery`** 服务读结构化事件。三个方法的**真实契约**
（读自 `node_modules/@deepseek-ai/dsh-session-query/lib/index.js` 的实现，不是猜的）：

```js
sessionQuery.listSessions()        // → [{ header: { id, createdAt, … }, live, persisted }]，新→旧
sessionQuery.readSession(id)       // → { session: header, inheritedEventCount, events }
                                   //   events 是**完整原始事件流**（structuredClone + 冻结）
sessionQuery.readSurface(id)       // → 同上但只含当前 surface 事件（后备）
sessionQuery.listEvents(id)        // → [{ sessionId, seq, type, time, surface }] ⚠️ 轻量，**没有 data**
```

取用量的路径：

```js
event.data.usage                            // 这次调用的 token 用量
event.data.message.source.{provider,model}  // 哪条路由、哪个模型
event.time                                  // 发生时刻 → 峰谷判定
```

这些读取位置**与官方 `dsh-session-stats` 完全一致**（其 `assistant/message` 分支读的正是
`event.data.usage`），所以不是猜出来的结构，而是从官方实现里对照出来的 —— 这一点很重要：
会话事件是 live 数据，按官方已知路径读少数标量字段是允许的，盲搜整个对象树则违反
「不要递归枚举 live 数据」的约束。

#### 两条弯路（都真实发生过，且**互相独立**）

| # | 弯路 | 症状 | 正解 |
| --- | --- | --- | --- |
| 1 | 会话 id 读成 `record.id` | 15 个会话**全部**「缺 id」，一条日志都没进去读 | 记录形状是 `{ header, live, persisted }`，id 在 **`record.header.id`** |
| 2 | 事件流用 `listEvents(id)` | 即便 id 修对了也读不到用量 —— 该 API 返回的记录里**没有 `data`** | 用 `readSession(id)` 取完整事件流 |

两条弯路的共同教训：**「读不到数据」的报错必须把上游结构一起打出来**（这次就是靠
`firstSessionKeys` / `firstHeaderKeys` / `firstEventKeys` 三个探测字段定位到层级问题的）。
v0.7.3 之后这三个字段常驻在回填结果里。

**语义是重建而不是追加**：先**只收集**，确认收到至少一条带用量的记录之后才
`resetLedger()` → 按日志回放。因此
① 可以重复执行、结果一致；② 不会与当前进程已经记下的账重复计算；
③ **读不到任何东西时一个字节都不改**（v0.7.1 就是漏了这条，一次「0 命中」把用户已累计的
41 次调用 / $0.3806 清空了 —— 真实损失）。
一个副作用：回填会把「起止时间」改成日志里最早那次调用的时间，这正是想要的效果。

**时间分界线守卫**：只回放「清空那一刻之前」的事件（`event.time < resetAt`）。清空之后
新产生的调用由 `llm/stream` 实时记账，若日志里也已存在又被回放一次就会重复计算 ——
这个守卫把那个窗口关掉；被跳过的条数在结果里以 `skippedRecent` 报出。

UI 在设置页「累计数据与控制」里，按钮是 `回填历史消耗`，下方显示扫描了多少会话、命中多少次、
读事件失败的会话数、耗时；失败时把三个结构探测字段一并显示出来。首次运行（磁盘上没有
`backfilledAt` 标记）会自动跑一次，之后不再重复。

**坏章自愈（v0.7.3）**：事故版本在「读到 0 条」时也照样 reset + 盖章，留下的账本里
`backfilledAt === createdAt`（reset 瞬间新建账本，两个时间戳是**同一毫秒**盖的 ——
正常回填必须逐个 await `readSession`，绝无可能同毫秒完成）。启动时若发现这个指纹，
就把坏章清掉、自动重跑一次回填；两阶段守卫仍然兜底（读不到任何东西就一个字节都不改），
所以自愈**不会**再把账本清空。这是「缺陷要留指纹 + 修复要能认出指纹」的实践：修复的不只是
代码路径，还有已经落在用户磁盘上的坏数据。

---

## 6. 目录结构

```text
dsh-api-balance/
├── README.md                    子项目总览（入口）
├── NOTICE.md                    治理边界与来源声明（冻结头注）
├── package.json                 npm 元数据 + npm run build / probe
├── src/
│   ├── core/                    ★ 纯函数层：零依赖，三种运行形态共用
│   │   ├── pricing.js           价格表 + 峰谷判定 + 计费
│   │   ├── ledger.js            用量账本、多维聚合、持久化导入导出
│   │   ├── deepseek.js          余额接口的构造与解析
│   │   └── format.js            展示格式（金额/Token/百分比/相对时间/币种折算）
│   ├── host.body.js             Host 半：apply(ctx) 的函数体
│   └── client.body.js           Client 半：apply(ctx) 的函数体
├── config/pricing.json          外部价格覆盖表（官方调价时改这里）
├── tools/
│   ├── build.mjs                ★ 唯一构建步骤：合成两个平面的产物（并注入存储桥）
│   ├── verify-artifacts.mjs     ★ 38 项自动校验（含模拟重启、回填契约、凭据链路、文档同步）
│   ├── probe-balance.mjs        不依赖 DSH 的独立余额自检
│   ├── push-backup.ps1          把本子项目单独备份到 GitHub（只推独立分支、不强推）
│   ├── fix-ps1-bom.ps1          给所有 .ps1 补 UTF-8 BOM（5.1 会按 GBK 读，中文会乱）
│   ├── desktop-admin.ps1        桌面管理菜单（快捷方式的目标，也是应急入口）
│   └── make-desktop-shortcut.ps1 创建桌面快捷方式
├── install/
│   ├── install.ps1              常驻安装（幂等，自动备份补丁 + 回读自检 + 失败自动回滚）
│   ├── uninstall.ps1            停用/回滚（出问题的第一手段）
│   └── verify.ps1               静态 + 运行时双重验证
├── docs/
│   ├── TECHNICAL.md             本文件
│   └── ROLLBACK.md              回滚与防崩方案
└── dist/                        构建产物（gitignore，可随时重建）
    ├── cordis-define.json       动态平面载荷
    ├── package/                 常驻平面 npm 包
    └── manifest.json            版本与哈希
```

标注 ★ 的是核心：`src/core/` 是纯函数层（可单测、可移植、可被任何运行形态复用），
`tools/build.mjs` 是唯一的合成点，`tools/verify-artifacts.mjs` 是唯一的验收闸门。

---

## 7. 可移植性：换掉任何一块需要改哪里

| 想换什么 | 改哪里 | 不需要改 |
| --- | --- | --- |
| 换价格 / 官方调价 | `config/pricing.json`（或 `src/core/pricing.js` 的默认表） | 任何逻辑代码 |
| 换模型 id / 新模型 | `src/core/pricing.js` 的 `models` 与 `aliases` | 计费逻辑 |
| 换余额接口（别的厂商/自建中转） | `src/core/deepseek.js` 的 `BALANCE_URL` + `parseBalance()` | 账本、UI |
| 换凭据来源 | `src/host.body.js` 的 `readApiKey()` | 其余全部 |
| 换 UI 落点（侧边栏/悬浮层/工具卡） | `src/client.body.js` 末尾两个 `slots.register` 调用 | Host 半、计费 |
| 换主机（不用 subprocess 拿余额） | `src/host.body.js` 的 `fetchBalance()` | 解析、账本、UI |
| 移植到别的 harness / 纯 Node | 直接 `import src/core/*.js`，它们是零依赖纯函数 | — |

`src/core/` 三个文件（pricing / ledger / deepseek）**不含任何 DSH、Node、浏览器 API 调用**，只有纯函数与数据。这意味着它们可以：
- 在 Node 脚本里单测（`node --test tools/*.test.mjs`）；
- 被搬进别的 agent 框架；
- 在运行时被安全地重复调用（无副作用、无隐藏状态）。

---

## 8. 已知边界与验证清单（诚实清单）

> 结论先行：**v0.6.0 已全链路实测跑通** —— 后端返回真实数据、两个 Slot 都注册进界面、累计跨重启保留。
> 下表把「验证到什么程度」写清楚，避免把「加载级通过」误当成「功能可用」。

| 项 | 状态 | 依据 |
| --- | --- | --- |
| 构建脚本 + 两个平面的产物 | ✅ 25 项自动校验 | `node tools/verify-artifacts.mjs` |
| 常驻平面 **Host 半** | ✅ **实测跑通真实数据** | 直接 curl 运行中的实例：`GET /dsh-api-balance/snapshot → 200`，返回真实余额与用量；随机路径对照 404 |
| 常驻平面 **Client 半** | ✅ **实测注册进界面** | Slot 占用者确认：`conversation.session.header.utilities` 的 `dsh-api-balance`（order 40）与 `settings.section` 的 `dsh-api-balance`（order 60）均 `active: true` |
| 样式注入 | ✅ 行为级验证 | 第 2 节：模拟 `document` 跑 `apply`，断言 `<style>` 被插入（5934 字符） |
| 凭据解析（桌面端无 `credentials`） | ✅ 端到端验证 | 第 5 节：模拟桌面端环境，密钥经 `launchEnvironment` 取到、余额解析正确、pending 清除 |
| **累计跨重启保留** | ✅ 端到端验证 | 第 6 节：记账 → 落盘 → **全新上下文重新 apply（模拟重启）** → 恢复成功 → 重置生效 → 坏文件安全 |
| 文档同步 | ✅ 构建期强制 | 第 8 节：版本号不在变更记录里就 FAIL |
| **回填历史消耗** | ✅ 端到端验证 | 第 7 节：照抄上游**真实**返回形状（含「`listEvents` 没有 `data`」这个陷阱版本）→ 断言 id 从 `header.id` 取出、命中 4 次、缓存命中入账 24000；再加「坏章 → 启动自愈 → 重建账本」场景 |
| 桌面快捷方式 | ✅ 已创建 | `C:\Users\han\OneDrive\桌面\DSH API 余额与消耗.lnk`；7 个 .ps1 全部通过 AST 语法检查 |
| 计费精度 | ⚠️ 是**估算** | 按官方标价 × 固定汇率，不是账单实扣；只统计插件装载期间的调用 |
| 图片 token | ⚠️ 是**估算** | 见 §5.3，不参与费用求和 |
| `deepseek-v4-pro` 路由变更 | ⚠️ 注意 | 官方公告：2026-09-14 12:00(北京) 起 `deepseek-v4-pro` 请求全部路由到 V4.1-Flash 并按 Flash 价计费。若你的账号已生效，在 `config/pricing.json` 的 `aliases` 里加 `"deepseek-v4-pro": "deepseek-flash"` |
| 按会话的消费明细 | ⚠️ 数据有、UI 无 | Host 一直在按 `sessionId` 记账（`usage.sessions`），v0.4.1 移除展开面板后暂未展示（见 §9） |
| 余额接口频率 | ⚠️ 5 秒一次 | 用户要求的「实时感」。若担心接口压力可在设置页调到 1 分钟 |
| `dist/` 不入库 | 设计如此 | `.gitignore` 排除，`node tools/build.mjs` 可随时重建 |

### 8.1 运行副本 ↔ 源码的对应关系（哈希台账）

`node tools/build.mjs` 每次都会把四个 SHA-256 前缀写进 `dist/manifest.json`，用于核对「跑着的插件 = 哪一份源码」。
**以 `dist/manifest.json` 为唯一权威**（它会随每次构建更新），本文档不再抄写哈希，避免过期误导。

当前主用平面是**常驻插件**，源码对应关系很简单：`dist/package/` 就是 `src/` 的直接产物，
`install.ps1` 把它整目录复制进 DSH home；`git` 侧的回档点见 [§10 变更记录](#10-变更记录) 与 `ROLLBACK.md` §5。

两种平面的更新方式：

```powershell
# 常驻平面（当前主用）
node tools\build.mjs
node tools\verify-artifacts.mjs    # 38 项，含文档同步
powershell -File install\install.ps1
# 完全退出并重启 DSH Desktop
powershell -File install\verify.ps1
```

```text
# 动态平面（临时、进程内；重启即消失）
cordis_define (kind:'existing', pluginId:'apibal-1', 用 dist/cordis-define.json 的两个函数体) → 新 packageId
cordis_run    (mode:'update',  pluginId:'apibal-1', packageId:'<新版本>')   # 换版本用 update
cordis_run    (mode:'run',     pluginId:'apibal-1', packageId:'<已知可用版>') # 回退用 run
```

> 一份真实的更新演练（v0.1 → v0.2）：`cordis_define(existing)` 只记录新代码、不影响正在跑的旧版本；
> `cordis_run(update)` 先停旧 Run 再启新版；成功后 `currentPackageId` 才切换，旧 Package 原样保留。
> 中途需要用户点一次审批 —— 单勾授权只覆盖被点的那一个 Package。

**常驻平面不受这个差异影响**：`install.ps1` 安装的永远是 `dist/package/`，也就是当前源码构建出的最新版。

---

## 9. 下一步可优化点（按性价比排序）

1. **按会话归因的 UI**：Host 早就在按 `sessionId` 记账（`usage.sessions`），v0.4.1 删掉展开面板后一直没有地方展示 —— 设置页加一张「按会话」表即可，不用改交互。
2. **缓存节省额**：把「因为命中缓存而省下的钱」算出来（`命中tokens × (未命中价 − 命中价)`）。以本机 50 倍的价差，这是最有冲击力的一个数字。
3. **加一个模型工具**：`harness.registerTool` 注册 `dsh_api_balance`，让模型能在对话里直接回答「我花了多少钱」。
4. **价格表过期提示**：把 `pricing.json` 的 `version` 与官方页对比，过期时在 UI 上提示。
5. **单元测试**：`src/core/` 全是纯函数，补 `tools/pricing.test.mjs` 与 `tools/ledger.test.mjs` 即可获得真实覆盖率（现在的 38 项是集成级，不覆盖边界值）。
6. **改用官方 `@Remote`**：常驻平面可以放弃 HTTP 路由，改成 typert 生成的 Remote 命名空间，省掉一条端点（代价是引入装饰器与代码生成）。
7. **账本压缩**：目前 `byDay` 与 `bySession` 各留 60 条、只存聚合；若长期运行可再加一层「按月归档」。

> 已完成、从清单里划掉的：~~账本持久化~~（v0.6.0，§5.8）。

---

### 9.1 想改这个项目时，先读这三处

| 想做的事 | 先读 |
| --- | --- |
| 加任何依赖 DSH 服务的新功能 | **§5.9 服务时序清单**（不做这一步，大概率得到一个「装上了但没反应」的插件） |
| 改完准备上线 | §0 维护约定的六步 |
| 出问题了要回滚 | `ROLLBACK.md` §0 三十秒应急卡 |

---

## 10. 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-10 | v0.1.0 | 初版：core 纯函数层 + Host 余额/用量/计费 + Client 胶囊与仪表盘；构建脚本打通两个平面；常驻安装/卸载/验证脚本与桌面管理入口就位。动态平面已运行验证（`apibal-1/pkg-1`）。 |
| 2026-09-10 | v0.1.1 | ① 渲染加固：hook 与渲染分离、渲染全程 try/catch、全字段兜底（§5.6）；② **修复构建缺陷**：常驻包的 `lib/core/*.js` 曾被误做「去 export」处理，导致 ESM 具名导入失败——由 `tools/verify-artifacts.mjs` 当场抓出并修正；③ 新增 `tools/verify-artifacts.mjs`（`npm run verify`），把常驻平面从「未验证」提升到「加载级已验证」。 |
| 2026-09-10 | v0.2.0 | ① **新增「本对话消费」面板**：点标题栏胶囊即在输入框下方展开，Host 按 `sessionId` 精确归因（`ledger.bySession`），面板展示本对话花费 / 调用次数 / 缓存命中率 / 输出 tokens + 三档分项 + 最近 8 次调用明细；② 跨 Slot 状态用 `apply()` 作用域内的订阅表共享，折叠时零请求、零占位；③ `summarize()` 增加 `sessions` 维度与 `firstAt`/`lastAt` 时间范围；④ 已通过真实 `update` 流程上线（pkg-1 → pkg-2），DSH 全程未中断。 |
| 2026-09-10 | v0.3.0 | ① **花费改按人民币展示**：新增 `DEFAULT_MONEY`（CNY / 7.10）与 `fmtCost()`，账本仍以美元记账、只在展示层折算；余额保持接口原币种不折算（§5.7）；② **修复胶囊点击热区**：加覆盖整个胶囊的透明命中层 `.dab-hit`，并显式声明 `pointer-events:auto` / `-webkit-app-region:no-drag` / `user-select:none`，解决「只有移到边框才能点开」；③ 修复 `Bar()` 把「图片视觉 token」当钱显示的问题（改为按需传入格式化函数）；④ **常驻安装脚本修复会静默写坏组合补丁的换行缺陷**（见下方附录二），并加入回读自检 + 自动回滚；⑤ 已安装常驻版到 DSH home。 |
| 2026-09-10 | v0.4.0 | ① **修复常驻平面彻底不生效的根因**（附录四）：宿主 `ctx.inject(['webServer'], …)` 等路由载体就绪、客户端 `ctx.inject(['slots'], …)` 等 Slot 服务就绪，并分别导出 `inject` 声明；② `verify-artifacts.mjs` 增加两条 inject 契约断言；③ **修正全项目文档与脚本里的 `pwsh` 命令**：本机只有 Windows PowerShell 5.1，`pwsh` 不存在，全部改为 `powershell`，桌面菜单改为子脚本同进程执行；④ 新增 `tools/fix-ps1-bom.ps1`（防 .ps1 BOM 丢失导致中文乱码）。 |
| 2026-09-10 | v0.4.1 | ① **交互回退到最初的两入口模型**：删掉输入框下方的展开面板（`conversation.composer.dock`），胶囊点击恢复为「立即刷新余额」，明细只在设置页；② **修复胶囊的 `ReferenceError`**：`pillBody` 里用了 `money` 却没声明，每次渲染都抛异常并被 try/catch 吞掉，导致胶囊永远只显示「余额 —」（附录五）；③ **仪表盘视觉重做**：顶部大号余额 + 标签、卡片圆角与层级、把三条独立分项条改成**一条堆叠条 + 图例（带占比）**、表头分隔线与行 hover；④ `verify-artifacts.mjs` 新增第 4 节「宿主传输层模拟」（见附录四），现在**不重启 DSH 就能验证路由能否挂上**。 |
| 2026-09-11 | v0.4.2 | **修复常驻平面 CSS 完全没注入**（附录六）：客户端服务目录里**没有 `styles` 服务**，`insertStyles()` 两个分支都拿不到就返回空操作 —— 界面全是裸文本、胶囊退化成原生按钮方框，且完全静默。改用官方 35 个客户端插件同款的 `<style>` 元素注入，并加了「模拟 document 跑一遍 apply，断言样式表被插入」的行为级测试。 |
| 2026-09-11 | v0.4.3 | 新增**客户端自检行**（设置页顶部）与**诊断回传通道**：胶囊走到降级分支时把确切错误与调用栈回传宿主、存进快照 `clientDiag`，让「看不到浏览器」的一方也能直接读到真因。降级文案从 `余额 —` 改为 `余额 ✗`，明确区分「没数据」与「渲染失败」。 |
| 2026-09-11 | v0.4.4 | ① **修复启动竞态**：胶囊在宿主首次读余额尚未完成时挂载 → 显示降级；而 `timer` 在注册那一刻还没就绪，轮询压根没装上，于是**永久卡死**在启动瞬间的状态。改为在 effect 里惰性解析 timer，并把「首次还没读完」显式标为 `balance.pending`（显示 `余额 …` 而不是 `✗`）；② **修复诊断通道**：常驻客户端用 GET 却没把参数发出去，宿主 handler 永远只收到 `{}` → `clientDiag` 全是空字符串。参数改为 `?data=` 编码传递，并加端到端测试。 |
| 2026-09-11 | v0.5.0 | **修复余额永远读不出来**（附录七）：桌面端 profile 里**没有 `credentials` 服务**，而我只实现了官方 provider 三段式里的第一段。补齐为 `credentials` → `launchEnvironment` → `process.env`。同时按用户要求把刷新间隔从 60s 改为 **5s**（宿主与客户端轮询对齐）。新增第 5 节端到端测试：模拟「桌面端无 credentials 服务」，验证密钥能取到、余额能解析、pending 能清除。 |
| 2026-09-11 | v0.6.0 | ① **累计跨重启保留**（§5.8）：账本聚合落盘到 `<DSH_HOME>/dsh-api-balance/usage-ledger.json`，临时文件 + rename 原子写、异步 fs、只在有改动时每 5 秒最多写一次、卸载时收尾；装载顺序改为**先恢复累计再读余额**；② 新增 `重置累计` 按钮与存储状态显示；③ 文案从「本进程累计花费」改为「累计花费」，并显示累计起始时间与已运行次数；④ 新增第 6 节端到端测试：记账 → 落盘 → **用全新上下文重新 apply 模拟重启** → 确认恢复 → 重置 → 坏文件安全性；⑤ **把「文档必须同步」做成构建期检查**（§0 第 8 节）。 |
| 2026-09-11 | v0.6.1 | ① **界面明确标出累计状态**：设置页顶部固定显示 `[累计 · 已恢复]` 或 `[累计 · 首次记账]`。起因是一次真实误解 —— v0.6.0 首次上线时账本还没落过盘，重启后从 0 开始计数，而这与「功能没生效」在界面上长得**一模一样**，用户合理地以为坏了；② `importLedger` 改为**只在真的恢复出非空累计时**才置 `restored`（空文件不再谎报「已恢复」）；③ **文档同步检查首次实战生效**：升版本号却忘了写变更记录时，文档同步检查当场 FAIL。 |
| 2026-09-11 | v0.7.0 | ① **整颗胶囊可点击**（§5.10）：根因是我把子元素设成了 `pointer-events:auto`（各自吃事件），正确做法是**反过来** —— 子元素全部 `pointer-events:none`，事件全部落到 `button` 自己身上；顺带删掉不再需要的透明命中层；② **点胶囊跳转到设置里的本分区**（§5.11）：DSH 没有「打开设置」的服务，只能用 ARIA 语义找触发器 + 点我们自己注册的那一行，全程 guarded、失败回落成刷新余额；③ **从历史会话日志回填累计消耗**（§5.12）：走官方 `sessionQuery` 服务读 `event.data.usage`（与官方 `dsh-session-stats` 读同一位置），先清空再回放，可重复执行且不会重复计算；④ 新增 `回填历史消耗` 按钮与结果展示。 |
| 2026-09-11 | v0.7.1 | ① **回填改为自动**：v0.7.0 把它做成了按钮，但用户要的是「历史就在那儿」——现在首次运行（磁盘上没有 `backfilledAt` 标记）会自动从会话日志补齐，之后不再重复跑；手动按钮保留用于重新回填；② 回填增加**时间分界线守卫**：只回放「清空那一刻之前」的事件，彻底关掉「扫描期间新产生的调用被实时记账 + 又被日志回放」的重复计数窗口；③ **跳转逻辑更鲁棒**：页面上可能不止一个 dialog 触发器（实测 `triggers=2`），改为逐个尝试直到找到我们那一行；④ **新增胶囊命中测试诊断**：挂载后用 `elementFromPoint` 测胶囊中心实际命中哪个元素，并把 `styleTags / hasNone / triggers / centerHit` 回传宿主 —— 实测结果 `centerHit=BUTTON.dab-pill`，证明**点击热区其实已经修好了**，用户看到的「点了没反应」是跳转失败后被回落成刷新（刷新没有可见变化）。 |
| 2026-09-11 | v0.7.2 | ① **回填改为「先收集、后清空」两阶段**：v0.7.1 先 `resetLedger()` 再扫描，一次「扫描到 0 条」就把用户已累计的数据清空了（真实发生并造成损失）。现在读不到任何带用量的记录就**原样返回、绝不碰账本**；② **回填失败时把探测到的真实结构报出来**（`sessionCount` / `sessionsWithoutId` / `listEventsFailed` / `firstSessionKeys` / `firstEventKeys`），把「为什么读不到」变成可读的事实而不是猜测；③ 会话 id 兼容 `id` / `sessionId` / `sessionID` 三种字段名（**方向错了，见 v0.7.3**）；④ 结果展示同步更新。<br>**当时的错误判断**：以为「`listSessions()` 返回空」。v0.7.3 拿到真实诊断后发现它**返回了 15 条**，真正的原因是 id 在 `header.id` 里、而事件流用错了 API。 |
| 2026-09-11 | v0.7.3 | **回填真正跑通 —— 两个独立缺陷叠在一起**（详见 §5.12 的「两条弯路」）：① **会话 id 读错层级**：`listSessions()` 返回的记录形状是 `{ header, live, persisted }`，id 在 **`record.header.id`**，我却读 `record.id` —— 15 个会话**全部**判定为「缺 id」，一条日志都没进去读，而诊断只报「缺 id 15」不足以指向层级问题。现在读 `header.id` 并把 `firstHeaderKeys` 一并报出来；② **事件流用错了 API**：`listEvents(id)` 只返回轻量记录 `{ sessionId, seq, type, time, surface }`，**根本没有 `data` 字段**，`event.data.usage` 永远取不到 —— 就算 id 修对了也依然读不到用量。改用官方的 `readSession(id)`（返回**完整原始事件流**，含 `data.usage`；`readSurface` 作为后备），并新增探测字段 `firstEventKeys`；③ 字段名 `listEventsFailed` → `readEventsFailed`，`firstHeaderKeys` 新增，成功/失败两条展示同步更新；④ 源码注释补上 `sessionQuery` 三个方法的**真实契约**，避免第三次走同一条弯路；⑤ **坏章自愈**：v0.7.0/0.7.1 的事故版本在「读到 0 条」时也照样 reset + 盖章，留下的账本里 `backfilledAt === createdAt`（同一毫秒盖的两个章 —— 正常回填必须逐个 await 读会话，绝无可能同毫秒完成）。启动时认出这个指纹就清掉坏章、让自动回填重跑一次（两阶段守卫兜底，读不到任何东西仍一个字节都不改）；⑥ 第 7 节验证新增**两处契约守卫**：照抄上游真实返回形状（含「`listEvents` 没有 `data`」这个陷阱版本）跑端到端回填，以及「坏章 → 启动自愈 → 重建账本」的场景。 |

### 附录六：缺陷全景与守卫清单

十次真实缺陷，**没有一次出在核心计费逻辑里**，全部集中在「构建 / 装配 / 服务时序 / 变量作用域 / 上游 API 契约」这一层。
比缺陷本身更重要的是：每一次都补齐了一条**自动校验**（或一个常驻诊断字段），而不是只改掉那一行。

| # | 版本 | 缺陷 | 症状 | 守卫它的自动校验 |
| --- | --- | --- | --- | --- |
| 1 | v0.1.1 | 常驻包的 `lib/core/*.js` 被误做「去 export」处理 | 装上去**加载期就失败** | 第 3 节：import 常驻包并检查导出 |
| 2 | v0.3.0 | `install.ps1` 用 `+` 拼数组，PowerShell 按空格连接 → 补丁块塌成一行 | 是合法 YAML，**插件完全不加载**、无报错 | 第 4 节 + `install.ps1` 自带回读自检 |
| 3 | v0.3.1 | 客户端 bundle 的注册 id 写成了插件显示名而非 **npm 包名** | 加载器判定「注册了错误的 id」→ 客户端静默不加载 | 第 2 节：bundle id 与 `package.json` name 交叉校验 |
| 4 | v0.4.0 | 宿主 `ctx.get('webServer')` 拿不到就静默返回 | 后端 404、界面全空、无报错 | 第 4 节：模拟 ctx 跑 apply，断言 5 条路由真的挂上 |
| 5 | v0.4.1 | `pillBody` 用了未声明的 `money`，`ReferenceError` 被 try/catch 吞掉 | 胶囊永远显示「余额 —」 | 第 1 节 `new Function` 求值 + 第 2 节模拟 apply |
| 6 | v0.4.2 | 客户端**没有 `styles` 服务**，CSS 一行没注入 | 全是裸文本、胶囊退化成方框 | 第 2 节：模拟 `document` 跑 apply，断言 `<style>` 被插入 |
| 7 | v0.4.4 / v0.5.0 | `timer` 未就绪 → 轮询没装上；**没有 `credentials` 服务** → 余额读不出 | 首次降级后永久卡死 / 一直 pending | 第 5 节：模拟桌面端（无 credentials）跑完整取密钥 + 读余额链路 |
| 8 | v0.6.0 | 账本只在定时器节拍落盘，`refresh` 路径不落盘 | 手动刷新后立刻被杀会丢最后几秒数据 | 第 6 节：端到端持久化（含「重启」模拟）**当场抓出** |
| 9 | v0.7.1 | 回填**先清空再扫描**，且不检查是否扫到东西 | 一次「0 命中」把用户已累计的 41 次调用 / $0.3806 **清空**（真实损失），还留下 `backfilledAt === createdAt` 的**坏章**挡住自动回填 | v0.7.2 改为「先收集、后清空」，读不到就一个字节都不改；v0.7.3 启动时认出坏章指纹并自愈重跑（第 7 节有端到端场景守卫） |
| 10 | v0.7.0 → v0.7.3 | **上游服务契约读错两处**：id 读 `record.id`（实际在 `record.header.id`）；事件流用 `listEvents`（返回的轻量记录**没有 `data`**） | 15 个会话全部「缺 id」→ 回填永远 0 命中，且报错信息不指向真因 | 常驻诊断字段 `firstSessionKeys` / `firstHeaderKeys` / `firstEventKeys` + 源码注释写清三个方法的真实契约 |

> 第 8 条特别值得记：它**不是**事后补的校验，而是我先写了「模拟重启」的测试、
> 测试立刻变红、我才发现漏了落盘路径。这就是「先写守卫再交付」的价值。

### 附：一次真实的「验证救回一个 bug」

v0.1.0 的 `build.mjs` 里，把 core 文件写进常驻包时复用了 `stripModuleSyntax()`（那是**动态载荷**才需要的去 `export` 处理）。结果 `dist/package/lib/core/deepseek.js` 里 `API_KEY_REF` 不再是具名导出，而 `lib/index.js` 却用 ESM 具名导入引用它——**常驻平面一装上去就会在加载期失败**，而这恰恰是最贵的一类 bug（要装进 DSH 控制面、要重启、要看日志才能发现）。

`tools/verify-artifacts.mjs` 第 3 项在 import 阶段立刻报出：
`The requested module './core/deepseek.js' does not provide an export named 'API_KEY_REF'`。

修正只需一行（常驻包改为原样复制 core 文件），但**能提前发现它**才是这个脚本存在的理由。这也是本项目「两个平面必须共用一份源码、且必须有独立验证」这条原则的实证。

### 附二：第二个真实缺陷 —— PowerShell 静默吃掉换行

v0.3.0 首次安装时，`install.ps1` 把补丁块写成了**一整行**：

```yaml
# >>> dsh-api-balance BEGIN (由 install.ps1 写入；删掉本块并重启即可停用) - insert:     - id: dsh-api-balance       name: dsh-api-balance-local # <<< dsh-api-balance END
```

后果很隐蔽：它**是合法 YAML**（整行是一条注释），所以 DSH 不会报错、不会崩，只是**插件完全不加载**——最难排查的那一类失败。`verify.ps1` 的静态检查当时还判了 PASS，因为标记字符串确实存在于文件里。

根因：PowerShell 里 `"a" + $array + "b"` 会把数组元素用**单个空格**连接（不是换行），而 `$block` 恰好是数组而不是字符串。证据就藏在输出里：`- insert:` 与 `- id:` 之间正好是 1 个空格 + 原本的 4 个缩进空格 = 5 个空格。

修复（三件事，缺一不可）：
1. 用 `[string]::Join("`r`n", $lines)` 显式连接，再用 `[System.IO.File]::WriteAllText()` 写出，不再走字符串拼接与 `Set-Content`；
2. **加回读自检**：写盘后重新读文件，确认 `- insert:` 至少有 2 行、BEGIN/END 标记都在；
3. 自检失败**自动用备份回滚**并抛出，绝不留下半坏的补丁。

`uninstall.ps1` 的写回路径也一并改成同一套写法。这个坑已写进 `install.ps1` 的注释里，避免以后有人「顺手优化」回去。

### 附三：第三个真实缺陷 —— 客户端 bundle 的注册 id 必须是**包名**

常驻插件装上、Host 半也跑通了（HTTP 接口返回 200、余额读取成功），但**界面上什么都不出现**。

根因在 `dsh-client-modules`：boot graph 的每一行 id 取自 `package.json` 的 `name`
（`graphRow(packageName, rev, source.meta)`），客户端运行时再用这个 id 去核对自己收到的注册：

```js
if (!this.factories.has(id)) throw new Error(`client-modules: bundle ${url} loaded without registering "${id}" via __ModuleLoader__.load`)
```

而 `build.mjs` 里我写的是插件**显示名** `dsh-api-balance`，实际**包名**是 `dsh-api-balance-local`。
两者不等 → 加载器认为「这个 bundle 加载了却没有注册我期待的 id」→ 客户端静默不加载。
Host 侧一切正常，所以从后端完全看不出问题——又是最难查的那一类。

修复与加固：
1. `build.mjs` 提取 `const PACKAGE_NAME = 'dsh-api-balance-local'`，package.json 的 `name` 与 bundle 的 `id` 都从它取，物理上不可能再写歪；
2. `verify-artifacts.mjs` 增加**交叉校验**：解析 `dist/package/package.json` 的 `name`，断言 bundle 注册的 id 与之完全相等。

新增的检查立刻生效并锁死了这个契约：

```
[PASS] bundle 注册成功 — id = dsh-api-balance-local
[PASS] bundle id 与 package.json name 一致 — dsh-api-balance-local
```

> 三个附录连起来看是一条清晰的教训：**两个平面共用一份源码，就必须有独立验证**。
> 前三次缺陷全部发生在「构建/安装」这一层，没有一次发生在核心逻辑里——而这三次都是自动校验抓出来的，不是靠肉眼。

### 附四：第四个真实缺陷（最隐蔽的一个）——「服务还没就绪」被静默降级成「什么都不做」

**症状**：常驻插件装上、DSH 正常启动、插件行也确实进了插件树（启动图里能查到 `dsh-api-balance-local`，
客户端 bundle 也能正常下载且 id 正确），但：后端 `/dsh-api-balance/snapshot` 返回 **404**，
界面上**什么都没有**，而且**没有任何报错**。

**根因**：常驻插件的 `apply()` 在**组合启动过程中**执行，那时 `webServer`（宿主侧）与 `slots`（客户端侧）
这两个服务**还没注册**。而本项目为了「拿不到服务就降级、绝不阻塞启动」，通篇用的是：

```js
const webServer = ctx.get('webServer')
if (!webServer || typeof webServer.register !== 'function') return 'none'   // ← 静默什么都不做
```

这套「优雅降级」在**动态平面**完全正确（动态包在系统启动完成之后才求值，服务一定就绪），
但在**常驻平面**就变成灾难：降级路径被当成正常路径走，插件「活着但不干活」，且不留任何痕迹。

定位过程值得记住——每一步都用可证伪的观察排除掉一层：
1. 静态检查全部 PASS（补丁块在、包在、文件在）；
2. 用带令牌的真实请求验证探测方法本身有效（随机路径同样 404，排除鉴权干扰）；
3. 用 Node 直接 `import('dsh-api-balance-local')` → **OK**，模块与清单都没问题；
4. 从 `__DSH_BOOT__` 启动图里查到本插件的行 → **在树里**，bundle URL 可取、内容正确、id 正确；
5. 于是只剩一个解释：**apply 跑了，但服务是 undefined，降级路径吞掉了整个功能。**

**修复**（用 Cordis 官方语义，而不是自己发明兜底）：

```js
// 宿主侧：等 webServer 就绪再挂路由（同 dsh-client-connection 的 ctx.inject(["connection","webServer"], …)）
if (typeof ctx.inject === 'function') {
  ctx.inject(['webServer'], (svcCtx) => { state.transport = registerHttpRoutes(svcCtx, names, handlers) ? 'http-route' : 'none' })
  return 'http-route-pending'
}

// 客户端侧：等 slots 就绪再注册（官方插件同样导出 inject = ["sessions","slots"]）
if (!registerContributions(ctx) && typeof ctx.inject === 'function') {
  ctx.inject(['slots'], (svcCtx) => { registerContributions(svcCtx) })
}
```

并用**两层声明**把它钉死：
- 常驻宿主包导出 `export const inject = ['webServer']`；
- 常驻客户端 bundle 导出 `exports.inject = ['slots']`。

`ctx.inject` 在两个平面都能安全使用：动态平面的受限 `ctx` 没有这个方法，`typeof` 判断会自动走
「服务已就绪、直接注册」那条路——**一份函数体仍然同时适配两个平面**。

`verify-artifacts.mjs` 补上两条断言（`宿主已声明 inject 含 webServer`、`客户端已声明 inject 含 slots`），
把「必须等哪些服务」变成构建期可验证的契约，而不是靠人记住。

> **最值得记住的教训**：优雅降级只对「可选能力」成立。对**功能赖以存在**的服务，
> 拿不到就必须等（`inject`），而不是静默跳过——否则插件会以「加载成功」的假象彻底失效。

### 附五：第五个真实缺陷 —— try/catch 把 `ReferenceError` 变成了「永远显示 ——」

**症状**：胶囊渲染出来了、也注册进 Slot 了，但上面**永远只显示「余额 —」**，从不出现真实数字。

**根因**：给人民币折算加 `fmtCost(value, money)` 时，只改了调用处，**漏了在 `pillBody` 里声明 `money`**：

```js
function pillBody(snap, open, toggle) {
  const data = snap.data
  const usage = (data && data.usage) || null
  // ← 这里少了 const money = (data && data.money) || null
  const title = [
    usage ? `本次进程累计花费 ≈ ${fmtCost(usage.costTotal, money)}…` : '',   // ReferenceError！
  ]
```

而 §5.6 为了防止渲染把界面搞崩，给整个渲染包了 try/catch —— 于是这个 **ReferenceError 被吞掉**，
组件静默走到降级分支，返回一个写着「余额 —」的静态徽章。**兜底机制反而把 bug 藏了起来。**

**教训（比缺陷本身更重要）**：

1. **兜底不等于正确**。catch 里的降级 UI 必须让人能看出「这是降级」——所以 v0.4.1 把降级徽章的
   `title` 明确写成「余额面板渲染失败（已安全降级）：<具体错误>」，鼠标悬停就能看到真因。
2. **宽泛的 try/catch 会掩盖编码错误**。它该拦的是「数据形状不对」，不是「我自己写错了变量名」。
   这也是为什么 `verify-artifacts.mjs` 里的模拟测试要用**真实的 ctx 形状**跑一遍 apply，
   而不是只做语法检查。
3. 改动一个函数的**签名/依赖**时，必须回头确认函数体里用到的每个自由变量都已声明。
   本项目为此保留的机械手段是「构建后用 `new Function` 求值 + 模拟 ctx 调用 apply」两层检查。

> 至此五个缺陷全部发生在**构建 / 装配 / 服务时序 / 变量作用域**这一层，核心计费逻辑一次都没出错。
> 每一次都补齐了一条**自动校验**，而不是只改掉那一行——这才是「可维护」与「只在这次修好」的区别。
