# dsh-api-balance 技术文档

> 版本：v0.2.0 ｜ 最后更新：2026-09-10
> 子项目根：`E:\DSHarness_Project\repo-one\dsh-api-balance`
> 回滚与防崩方案见 [`ROLLBACK.md`](./ROLLBACK.md)；治理边界见项目根 [`../NOTICE.md`](../NOTICE.md)。

---

## 0. 三个最常被问的问题

**Q1：为什么界面上好像只看到余额？**
胶囊上刻意只放两个数字（余额 + 本进程累计花费），完整的「钱花在哪里」有三处入口：

| 入口 | 内容 |
| --- | --- |
| 会话标题右侧胶囊 | 余额 + 本进程累计花费（一眼可见，常驻不打扰） |
| **点胶囊** | 输入框下方展开**本对话消费**：本对话花费 / 调用次数 / 缓存命中率 / 输出 tokens + 三档分项条形 + 最近 8 次调用明细 |
| **设置 → API 余额与消耗** | 完整仪表盘：概览卡 + 分项 + 按模型 / 按用途 / 按最近 14 天 / 逐次明细 + 价格表与控制 |

**Q2：那个 `$0.051` 是什么？**
从插件启动（= 本次 DSH 进程启动）到现在，**所有模型调用**的估算累计花费，单位美元。算法是 `实际 token 数 × 官方标价`，按峰谷分别计价。它不是账单实扣值，但是同一口径的近似。

**Q3：这些实时统计要额外花钱 / 消耗 token 吗？**
**完全不要。** token 用量是 DSH 每次调用模型时**本来就会收到**的返回字段（`usage`），插件只是把它读下来做本地加法——不发额外请求、不消耗额外 token、不占用额外上下文。唯一的对外请求是余额查询本身（默认 60 秒一次，余额接口不计费也不消耗 token）。
**关掉这个插件并不会省下模型的任何费用**，它只是把已经花掉的钱显示出来。

---

## 1. 做了什么（一句话 + 验收标准）

**一句话**：一个 DSH 插件，在 DSH 自己的界面里实时显示 DeepSeek API 账户余额，并把每一次模型调用的花费按「缓存命中输入 / 缓存未命中输入 / 输出 / 图片」四类拆开归因，精确到「哪个对话、哪一次调用」。

**验收标准（可逐条核对）**：

| # | 目标 | 状态 |
| --- | --- | --- |
| A1 | 在 DSH 界面内直接看到余额，不需要另开网页或终端 | 已实现（会话标题右侧胶囊） |
| A2 | 余额自动刷新，可手动强刷，刷新间隔可调 | 已实现（默认 60s，可选 15s/30s/1min/5min） |
| A3 | 显示钱花在哪里：缓存命中 / 未命中 / 输出 / 图片 | 已实现（胶囊展开面板 + 设置页仪表盘） |
| A4 | 按官方峰谷价计费（含谷时半价） | 已实现 |
| A5 | 精确定位到「本对话花了多少」 | 已实现（Host 按 `sessionId` 记账，面板按当前会话过滤） |
| A6 | 一份源码同时支撑「临时动态插件」与「重启后常驻插件」 | 已实现（`tools/build.mjs`） |
| A7 | 出问题能一键停用/回滚，且不需要 DSH 还活着 | 已实现（桌面快捷方式 → 管理菜单 → 停用回滚） |
| A8 | 项目可读、可优化、框架可移植 | 见 §7、§8 |

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

### 3.2 运行形态差异被收敛成两处适配

两个平面真正的差异只有两点，代码里各用一个函数吸收掉：

```js
// Host 半：把 handler 暴露给 Client 的机制不同
installTransport(ctx, handlers)
  ├─ 动态平面：harness.handle(name, handler)      → 'dsh-package-rpc'
  └─ 常驻平面：webServer.register({kind:'exact', path:'/dsh-api-balance/<name>'})  → 'http-route'

// Client 半：调用 Host 的方式不同
callHost(method, args)
  ├─ 动态平面：host.call(method, args)            （Package 私有 JSON RPC）
  └─ 常驻平面：fetch('/dsh-api-balance/' + method)（同源 HTTP，无 CORS 问题）
```

判断用的是 `typeof harness !== 'undefined'` 与 `typeof host !== 'undefined'`——`typeof` 对未声明的标识符永远安全，因此同一份函数体在两个平面都能跑。

> **设计取舍**：常驻平面本来可以用 DSH 官方的 `@Remote` / typert 生成机制做跨端调用，但那需要装饰器、代码生成与额外的包依赖。本项目选择复用 DSH 自带的 `webServer` 注册一条只读 JSON 路由——更少的活动部件，也更容易被后来者读懂。

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
| `conversation.composer.dock` | **本对话消费**面板（默认折叠，`open === false` 时返回 `null`，零占位、零请求）：4 个小指标 + 三档分项条形 + 最近 8 次调用明细 | `{ id: 'dsh-api-balance', order: 30 }` |
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

## 6. 目录结构

```text
dsh-api-balance/
├── README.md                    子项目总览（入口）
├── NOTICE.md                    治理边界与来源声明（冻结头注）
├── package.json                 npm 元数据 + npm run build / probe
├── src/
│   ├── core/                    ★ 纯函数层：零依赖，三种运行形态共用
│   │   ├── pricing.js           价格表 + 峰谷判定 + 计费
│   │   ├── ledger.js            用量账本与多维聚合（含环形缓冲）
│   │   ├── deepseek.js          余额接口的构造与解析
│   │   └── format.js            展示格式（金额/Token/百分比/相对时间）
│   ├── host.body.js             Host 半：apply(ctx) 的函数体
│   └── client.body.js           Client 半：apply(ctx) 的函数体
├── config/pricing.json          外部价格覆盖表（官方调价时改这里）
├── tools/
│   ├── build.mjs                ★ 唯一构建步骤：合成两个平面的产物
│   ├── probe-balance.mjs        不依赖 DSH 的独立余额自检
│   ├── desktop-admin.ps1        桌面管理菜单（快捷方式的目标）
│   └── make-desktop-shortcut.ps1 创建桌面快捷方式
├── install/
│   ├── install.ps1              常驻安装（幂等，自动备份补丁）
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

标注 ★ 的是核心：`src/core/` 是纯函数层（可单测、可移植、可被任何运行形态复用），`tools/build.mjs` 是唯一的合成点。

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

## 8. 已知边界与未验证项（诚实清单）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 动态平面已运行 | ✅ 已验证 | 插件 `apibal-1` 状态 `running`，`currentPackageId = pkg-2`（v0.2.0）；Host 注册 `snapshot`/`refresh`/`setRefreshMs` 三个 handler，Client `running`，三个 Slot 均已挂载 |
| 构建脚本 | ✅ 已验证 | `node tools/build.mjs` 通过；两份载荷 `new Function(...)` 语法校验通过，返回 `{apply}` |
| 常驻平面 **host 插件** | ✅ 已验证（加载级） | `verify-artifacts.mjs`：`import dist/package/lib/index.js` 成功、导出 `apply`；**空 ctx 下 `apply()` 不抛异常**（直接验证了「不声明硬依赖、拿不到服务就降级」） |
| 常驻平面 **client 包** | ✅ 已验证（加载级） | `verify-artifacts.mjs`：手写 `__ModuleLoader__` 工厂包能注册、factory 能执行、导出 `{apply}` |
| 桌面快捷方式 | ✅ 已验证 | `C:\Users\han\OneDrive\桌面\DSH API 余额与消耗.lnk` 已创建；5 个 .ps1 全部通过 AST 语法检查 |
| 常驻安装脚本 | ✅ 已执行并通过回读自检 | 2026-09-10 安装到 `%APPDATA%\dsh-desktop\harness`；补丁块分行正确、两处 `node_modules` 就位 |
| 常驻平面 **Host 半** | ✅ **已实测跑通真实数据** | `GET /dsh-api-balance/snapshot → 200`，返回 `balance.ok = true`、`apiKey.configured = true (source: env)`、已记账 6 次调用。profile 的 `patchReload: live` 让宿主插件**无需重启就热加载**了 |
| 常驻平面 **Client 半** | ⚠️ 待重启确认 | 已修复「bundle 注册 id 用了插件显示名而非 npm 包名」的缺陷（附录三），并加了交叉校验；包已重装，需**完全重启 DSH** 后确认界面 |
| 花费展示币种 | ✅ 已实现 | 人民币（按 7.10 固定汇率折算），余额按接口原币种不折算（§5.7） |
| **真实余额数字** | ⚠️ 未验证 | 取决于 DSH 凭据库里是否已配置 `DEEPSEEK_API_KEY`。若界面显示「余额读取失败」，先跑 `install/verify.ps1` 看 `apiKey.configured` 与具体错误 |
| 计费精度 | ⚠️ 是**估算** | 只统计**本进程存活期间**的调用；DSH 重启后账本归零。这是 v0.1 的刻意取舍（见 §9） |
| 图片 token | ⚠️ 是**估算** | 见 §5.3，不参与费用求和 |
| `deepseek-v4-pro` 路由变更 | ⚠️ 注意 | 官方公告：2026-09-14 12:00(北京) 起 `deepseek-v4-pro` 请求全部路由到 V4.1-Flash 并按 Flash 价计费。若你的账号已生效，在 `config/pricing.json` 的 `aliases` 里加 `"deepseek-v4-pro": "deepseek-flash"` |
| `dist/` 不入库 | 设计如此 | `.gitignore` 排除，`node tools/build.mjs` 可随时重建 |

### 8.1 运行副本 ↔ 源码的对应关系（哈希台账）

`node tools/build.mjs` 每次都会把四个 SHA-256 前缀写进 `dist/manifest.json`，用于核对「跑着的插件 = 哪一份源码」。当前对照：

| 对象 | host 载荷哈希 | client 载荷哈希 | 状态 |
| --- | --- | --- | --- |
| `apibal-1/pkg-1`（v0.1.0） | `ca40d72232163544` | `a777a57db2be7b3b` | 首版；已下线，**作为回滚点保留** |
| `apibal-1/pkg-2`（v0.2.0） | `7e6119f497218e5e` | `0c3bc54f4daf21a1` | **当前运行版本**：新增本对话面板 + 渲染加固 + 按会话聚合 |

> 这次 v0.1 → v0.2 的切换是一份**真实的更新演练**：`cordis_define(existing)` 只记录新代码、不影响正在跑的 pkg-1；`cordis_run(update)` 先停旧 Run 再启 pkg-2；成功后 `currentPackageId` 才切到 pkg-2，而 pkg-1 原样保留。中途需要你点一次审批 —— 单勾授权只覆盖被点的那一个 Package。整个过程 DSH 没有中断、没有报错。

构建命令与校验：

```powershell
node tools\build.mjs             # 重新合成两个平面，写入 dist\manifest.json（含四个哈希）
node tools\verify-artifacts.mjs  # 6 项产物验证（两个平面）
```

把新版本推到运行中的插件（两步，任一步都不会破坏现有版本）：

```text
cordis_define (kind:'existing', pluginId:'apibal-1', 用 dist/cordis-define.json 的两个函数体)  → 得到新 packageId
cordis_run    (mode:'update', pluginId:'apibal-1', packageId:'<新版本>')
```

若更新失败或效果不好，一条命令退回上一个已知可用版本：

```text
cordis_run (mode:'run', pluginId:'apibal-1', packageId:'pkg-1')
```

**常驻平面不受这个差异影响**：`install.ps1` 安装的永远是 `dist/package/`，也就是当前源码构建出的最新版。

---

## 9. 下一步可优化点（按性价比排序）

1. **账本持久化**：把 `summarize()` 的结果定期落盘（`storage` 服务或 JSON 文件），让「今天/本周花了多少」跨重启保留。当前是进程内内存账本。
2. **改用官方 `@Remote`**：常驻平面可以放弃 HTTP 路由，改成 typert 生成的 Remote 命名空间，省掉一条 HTTP 端点（代价是引入装饰器与代码生成）。
3. **加一个模型工具**：`harness.registerTool` 注册 `dsh_api_balance`，让模型能在对话里直接回答「我花了多少钱」。
4. **缓存节省额**：把「因为命中缓存而省下的钱」算出来（`命中tokens × (未命中价 − 命中价)`），这是最有冲击力的一个数字。
5. **按会话归因**：`llm/stream` 的 `options.sessionId` 已经拿到了，账本里也已记录，只差 UI 加一张「按会话」表。
6. **单元测试**：`src/core/` 全是纯函数，补 `tools/pricing.test.mjs` 与 `tools/ledger.test.mjs` 即可获得真实覆盖率。
7. **订阅官方价格页**：把 `pricing.json` 的 `version` 与官方页对比，过期时在 UI 上提示。

---

## 10. 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-10 | v0.1.0 | 初版：core 纯函数层 + Host 余额/用量/计费 + Client 胶囊与仪表盘；构建脚本打通两个平面；常驻安装/卸载/验证脚本与桌面管理入口就位。动态平面已运行验证（`apibal-1/pkg-1`）。 |
| 2026-09-10 | v0.1.1 | ① 渲染加固：hook 与渲染分离、渲染全程 try/catch、全字段兜底（§5.6）；② **修复构建缺陷**：常驻包的 `lib/core/*.js` 曾被误做「去 export」处理，导致 ESM 具名导入失败——由 `tools/verify-artifacts.mjs` 当场抓出并修正；③ 新增 `tools/verify-artifacts.mjs`（`npm run verify`），把常驻平面从「未验证」提升到「加载级已验证」。 |
| 2026-09-10 | v0.2.0 | ① **新增「本对话消费」面板**：点标题栏胶囊即在输入框下方展开，Host 按 `sessionId` 精确归因（`ledger.bySession`），面板展示本对话花费 / 调用次数 / 缓存命中率 / 输出 tokens + 三档分项 + 最近 8 次调用明细；② 跨 Slot 状态用 `apply()` 作用域内的订阅表共享，折叠时零请求、零占位；③ `summarize()` 增加 `sessions` 维度与 `firstAt`/`lastAt` 时间范围；④ 已通过真实 `update` 流程上线（pkg-1 → pkg-2），DSH 全程未中断。 |
| 2026-09-10 | v0.3.0 | ① **花费改按人民币展示**：新增 `DEFAULT_MONEY`（CNY / 7.10）与 `fmtCost()`，账本仍以美元记账、只在展示层折算；余额保持接口原币种不折算（§5.7）；② **修复胶囊点击热区**：加覆盖整个胶囊的透明命中层 `.dab-hit`，并显式声明 `pointer-events:auto` / `-webkit-app-region:no-drag` / `user-select:none`，解决「只有移到边框才能点开」；③ 修复 `Bar()` 把「图片视觉 token」当钱显示的问题（改为按需传入格式化函数）；④ **常驻安装脚本修复会静默写坏组合补丁的换行缺陷**（见下方附录二），并加入回读自检 + 自动回滚；⑤ 已安装常驻版到 DSH home。 |

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
> 三次缺陷全部发生在「构建/安装」这一层，没有一次发生在核心逻辑里——而这三次都是自动校验抓出来的，不是靠肉眼。
