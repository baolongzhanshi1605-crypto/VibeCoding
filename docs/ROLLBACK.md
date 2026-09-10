# dsh-api-balance · 回滚与防崩方案

> 版本：v0.1.0 ｜ 最后更新：2026-09-10
> 目标：**任何一次更新、任何一个 bug，都必须能在不重装 DSH 的前提下退回上一个已知可用状态。**
> 配套：技术实现见 [`TECHNICAL.md`](./TECHNICAL.md)。

---

## 0. 三十秒应急卡（出事时只看这一段）

| 症状 | 立刻做什么 |
| --- | --- |
| 界面某处显示异常，但 DSH 还能用 | 双击桌面 **`DSH API 余额与消耗`** → 选 `[4] 停用 / 回滚常驻插件` |
| 装完成常驻后 **DSH 起不来 / 白屏** | 完全退出 DSH → 双击桌面快捷方式（它是纯 PowerShell，不依赖 DSH）→ `[4]` → 重启 DSH |
| 只是动态插件在捣乱（没装常驻版） | 在对话里说「停用 apibal-1」，或直接**重启 DSH**——动态插件随进程消失 |
| 补丁文件被改坏 | 关闭 DSH → 把最近一个 `cordis.patch.yml.bak-*` 复制回 `cordis.patch.yml` → 重启 |
| **改了源码以后变坏了** | `git -C E:\DSHarness_Project\repo-one restore --source=dsh-api-balance-v0.3.0 -- dsh-api-balance` |
| 想确认到底坏在哪 | 双击桌面快捷方式 → `[2] 验证` → 看逐项 PASS/FAIL 与具体错误文本 |

**关键设计**：桌面快捷方式指向 `tools/desktop-admin.ps1`，它是一个**纯 PowerShell 菜单，不加载 DSH、不依赖插件**。这就是「DSH 已经起不来」时你仍然有入口的原因。

---

## 0.1 四层防线：哪一层管什么

「因为一次 bug 导致崩溃」这件事，需要四层来兜，任何一层单独都不够：

| 层 | 机制 | 管什么 | 恢复耗时 |
| --- | --- | --- | --- |
| L1 | 插件自身设计（不声明硬依赖、异常全收敛、副作用归 fiber） | 让崩溃**难以发生** | — |
| L2 | `install.ps1` 备份 + `uninstall.ps1` + 桌面菜单 | bug 发生后**救活 DSH**（不需要 DSH 活着） | ~30 秒 + 一次重启 |
| L3 | **本地 git 历史**（`repo-one` 的提交与标签） | 源码改坏了能**退回上一版** | 秒级，不需要网络 |
| L4 | **GitHub 远程分支**（`VibeCoding` 的 `dsh-api-balance` 分支） | 磁盘挂了 / 误删 / 换机器也能恢复 | 取决于网络 |

**L2 与 L3 是日常真正用得上的**：L2 救「装上去崩了」，L3 救「改代码改坏了」。L4 是兜底，平时用不到，但出事时是唯一的异地副本。

### L3 用法（本地，最快）

```powershell
$repo = 'E:\DSHarness_Project\repo-one'
git -C $repo tag -l 'dsh-api-balance-*'                              # 看有哪些回档点
git -C $repo restore --source=dsh-api-balance-v0.3.0 -- dsh-api-balance   # 整目录还原到某个标签
git -C $repo log --oneline -5 -- dsh-api-balance                     # 看这个子项目的改动历史
```

### L4 用法（异地，需要网络）

```powershell
pwsh -File E:\DSHarness_Project\repo-one\dsh-api-balance\tools\push-backup.ps1
# 该脚本只推本子项目、只写独立分支、绝不强推、绝不碰远程 main
```

恢复时：

```powershell
$repo = 'E:\DSHarness_Project\repo-one'
git -C $repo fetch vibecoding
git -C $repo diff refs/remotes/vibecoding/dsh-api-balance -- dsh-api-balance      # 看差异
git -C $repo checkout refs/remotes/vibecoding/dsh-api-balance -- dsh-api-balance  # 整目录还原
```

> **为什么单独抽一条分支**：`VibeCoding` 是一个公开仓库，里面本来就有你自己的 Python 项目。
> 直接推 `repo-one` 会把它和 `chaoxing-homework-reminder` 一起公开，而且两边历史无共同祖先、会被 git 拒绝。
> 所以 `push-backup.ps1` 用 `git commit-tree` 把 `dsh-api-balance/` 抽成**独立历史**推到新分支——远程 `main` 一个字节都不动。

---

## 1. 威胁模型：这个插件可能怎样把 DSH 弄崩

先诚实地把失败模式列全，再逐条说防线。

| # | 失败模式 | 后果 | 防线 |
| --- | --- | --- | --- |
| T1 | 常驻安装时**组合补丁写坏**（`cordis.patch.yml` YAML 非法） | **DSH 起不来**（最严重） | 写前自动备份；只追加一个带 BEGIN/END 标记的块；**写盘后回读自检（确认 `- insert:` 分行存在）**；自检失败自动用备份回滚并抛错；`uninstall.ps1` 可整块删除；备份可整份还原 |
| T2 | 常驻插件**加载期抛异常**（import 失败/语法错误） | DSH 启动报错，可能拒绝启动该 profile | 构建期 `new Function` 语法校验；包零第三方依赖；`verify.ps1` 可先静态检查再重启 |
| T3 | Client 半**渲染期抛异常** | 该 Slot 子树渲染失败（最坏：所在区域空白） | 两个组件都有完整错误态分支；所有数据访问有 `|| []` / `|| {}` 兜底；不动原生 DOM、不覆盖原生 Slot |
| T4 | Host 半**阻塞事件循环** | DSH 整个卡住 | 唯一的重活是 `await` 子进程，完全异步；无同步 IO、无死循环 |
| T5 | 子进程**泄漏**（curl 挂住） | 累积僵尸进程 | `--max-time 20` + `graceMs: 3000`；`subprocess` 服务在 fiber 释放时统一回收 |
| T6 | 定时器**泄漏** | 内存/CPU 缓慢增长 | 所有定时器都通过 `ctx.effect()` 交给 fiber 托管，插件停止/更新/移除时自动清理 |
| T7 | 事件监听**泄漏**或**改变模型调用行为** | 拦截链路越来越长；最坏改变推理结果 | `ctx.on('llm/stream')` 随 fiber 释放；包装器**逐 chunk 原样透传**，只在 `finally` 记账，且**不写 catch**（异常原样抛出） |
| T8 | 记账代码**抛异常** | 影响模型调用 | 记账整体包在 `try/finally` 里，`finally` 内再套一层 `try/catch` 并降级为一条 `console.error` |
| T9 | **密钥泄漏**到日志/进程列表 | 安全问题 | 密钥只走 stdin；不进 argv/env/日志/快照/RPC；`buildCurlConfig` 拒绝非法字符 |
| T10 | 内存无界增长 | 长时间运行后 OOM | 明细是 1000 条环形缓冲；聚合是定长计数器；账本不持有任何 DSH live 对象 |
| T11 | 与其它插件**抢 Slot / 抢服务** | 界面冲突 | 只注册两个 **additive list 槽**（`replaceRisk: none`），用 `id: 'dsh-api-balance'` 命名空间隔离；不注册任何服务、不 provide 任何 key |
| T12 | 更新时**新旧版本打架** | 半新半旧状态 | Package 不可变：新版是**新 Package**，旧版原样保留；`currentPackageId` 只在完全成功后才切换 |

---

## 2. 设计层防线：为什么它在结构上不太可能弄崩 DSH

1. **不声明硬依赖**。代码里没有 `inject: [...]`，全部用 `ctx.get(name)` 加 `undefined` 判断。因此**不存在**「服务没起来导致插件卡在 waiting 或启动失败」这条路径——拿不到服务就降级（余额显示不可用），DSH 照常跑。
2. **不改组合、不写盘、不联网**（Host 半唯一的外部动作是那一发 curl）。
3. **一切副作用都归 fiber 管**。样式、定时器、事件监听、HTTP 路由全部返回 disposer 并交给 `ctx.effect()`；插件一停，全部消失，不留痕迹。
4. **绝不持有 DSH 的 live 对象**。`llm/stream` 回调里只读 `options.provider/model/purpose/sessionId` 和 `chunk.usage` 的标量字段，然后立刻构造自己拥有的普通对象。因此不会出现「序列化 live 对象把页面搞崩」这类典型事故。
5. **失败一律降级，绝不向上抛**。余额网络失败、解析失败、凭据缺失、图片估算失败——全部收敛成 `{ok:false, error}` 并在 UI 上显示成一行可读文本。
6. **UI 落点是加成式的**。两个 slot 的 `replaceRisk` 都是 `none`，注册进去是并列追加，不会替换任何原生界面，也不会把原生 Slot 的后代一起干掉。

---

## 3. 恢复阶梯（从最轻到最重，逐级升级）

### L0 — 自愈（先等 15 秒）
Client 每 15 秒重新拉一次快照；Host 每 60 秒重试一次余额。**网络抖动、接口临时 5xx 都会自己恢复**，UI 上会看到红色状态点 + 具体错误文本，失败时保留上一次成功的数字（不闪成 `—`）。

### L1 — 停用动态插件（不重启 DSH）
对话里说一句即可，或由 agent 执行：

```
cordis_stop apibal-1        # 停用当前 Run，保留所有 Package 与授权
```

停用后：样式、定时器、事件监听、Handler、Slot 注册**全部随 fiber 释放**。想再开：`cordis_run apibal-1 pkg-1 run`。

### L2 — 卸载常驻插件（需要重启一次 DSH）
双击桌面快捷方式 → `[4]`，或命令行：

```powershell
pwsh -File E:\DSHarness_Project\repo-one\dsh-api-balance\install\uninstall.ps1
# 连 node_modules 里的包一起删：
pwsh -File E:\DSHarness_Project\repo-one\dsh-api-balance\install\uninstall.ps1 -RemovePackage
```

它做的事：
1. 把 `cordis.patch.yml` 里 `# >>> dsh-api-balance BEGIN` 到 `# <<< dsh-api-balance END` 之间的块删掉；
2. 删除前的补丁留档为 `cordis.patch.yml.uninstalled-<时间戳>`；
3. 只有加 `-RemovePackage` 才删 `node_modules` 里的包。

然后**完全退出并重启 DSH**。

### L3 — 用备份整份还原组合补丁（补丁被改坏时）
```powershell
$h = "$env:APPDATA\dsh-desktop\harness\profiles\web"
Get-ChildItem "$h\cordis.patch.yml.*" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name,LastWriteTime
Copy-Item "$h\cordis.patch.yml.bak-20260910-204523" "$h\cordis.patch.yml" -Force
```
（文件名以实际时间戳为准。）这一步会把补丁恢复到安装前的原样。

### L4 — 手工兜底（前三级都失败时）
组合补丁本身只是一个 YAML 数组，任何时刻都可以**手工编辑**：删掉 `- insert:` 那三行，保存，重启。若连文件都打不开，删除 `cordis.patch.yml` 的全部内容并只留注释行——DSH 能够以「只有内置 bundle、没有任何补丁」的状态启动。

---

## 4. 更新流程：版本不可变 + 一键回退

### 4.1 DSH 动态平面的版本语义

| 指针 | 含义 |
| --- | --- |
| `pluginId` = `apibal-1` | 插件身份，跨越所有版本 |
| `packageId` | **不可变的代码版本**。改代码 = 定义新 Package，绝不覆盖旧的 |
| `currentPackageId` | 最近一次**完全成功**的版本 |
| `nextPackageId` | 正在审批 / 激活中 / 最近失败的版本 |
| `pluginRunId` | 一次激活尝试，串联审批、加载、报错 |

### 4.2 标准更新动作

```
1. 改 src/**                      （改源码）
2. node tools/build.mjs           （重新合成两个平面，写入 dist/manifest.json 的新哈希）
3. cordis_define (kind:'existing', pluginId:'apibal-1')   → 得到 pkg-2
4. cordis_run  (mode:'update', pkg-2)                      → 旧 Run 先停，再启 pkg-2
```

**关键保证**：
- 第 3 步**只记录代码，不执行、不影响正在运行的 pkg-1**；
- 第 4 步失败时，`currentPackageId` 仍是 `pkg-1`——**旧版本指针不会丢**；
- 更新失败**不会**自动回滚物理 Run，需要显式执行：

```
cordis_run (mode:'run', pluginId:'apibal-1', packageId: currentPackageId)   # 回到 pkg-1
```

- 审批授权：单勾只授权当前 Package；**双勾**才授权该插件未来的版本。若你只想给一次，就每次更新都重新点一下——这本身也是一道防线。

### 4.3 常驻平面的更新动作

```powershell
cd E:\DSHarness_Project\repo-one\dsh-api-balance
node tools\build.mjs                       # 重新构建
pwsh -File install\install.ps1             # 幂等：覆盖包 + 补丁块已存在则跳过
# 完全退出并重启 DSH
pwsh -File install\verify.ps1              # 验证
```

`install.ps1` 每次都重新备份补丁，因此**每次更新都自动产生一个新的回滚点**。

### 4.4 出 bug 时的最小代价路径

1. 先 `cordis_stop`（动态）或桌面菜单 `[4]`（常驻）——**先把 DSH 救活**；
2. 看 `cordis_inspect_self apibal-1 pkg-N` 拿到失败版本的**精确源码与诊断栈**；
3. 改源码 → 重建 → 定义**新** Package（不要动旧的那份）；
4. 用 `update` 上；不行就 `run currentPackageId` 退回去。

---

## 5. 回滚点台账

| 回滚点 | 位置 | 产生时机 | 恢复方式 |
| --- | --- | --- | --- |
| 动态版本 pkg-1（v0.1.0） | DSH 进程内（Package 不可变） | 首次 `cordis_define` | `cordis_run apibal-1 pkg-1 run` |
| 动态版本 pkg-2（v0.2.0，当前） | 同上 | v0.2 更新 | 它就是当前版本，无需恢复 |
| 组合补丁备份 | `<DSH home>\profiles\web\cordis.patch.yml.bak-<时间戳>` | 每次 `install.ps1` | 覆盖回 `cordis.patch.yml` |
| 卸载前补丁留档 | `<DSH home>\profiles\web\cordis.patch.yml.uninstalled-<时间戳>` | 每次 `uninstall.ps1` | 同上 |
| 插件包旧副本 | `node_modules\dsh-api-balance-local`（被覆盖前由脚本重建） | 每次 `install.ps1` | 重新 `node tools/build.mjs` 后重装 |
| 源码 · 本地历史 | `repo-one` 提交 `82b61ee` + 标签 **`dsh-api-balance-v0.3.0`** | 2026-09-10 提交并打标签 | `git restore --source=dsh-api-balance-v0.3.0 -- dsh-api-balance` |
| 源码 · 异地副本 | `VibeCoding` 远程分支 `dsh-api-balance` | `tools\push-backup.ps1`（网络可达时） | `git fetch vibecoding` 后 `git checkout refs/remotes/vibecoding/dsh-api-balance -- dsh-api-balance` |
| 源码 · 本地分支副本 | `repo-one` 的 `dsh-api-balance` 分支（只含本子项目、根目录布局） | `push-backup.ps1` 每次运行重建 | `git checkout dsh-api-balance -- .`（在临时克隆里看更安全） |
| 构建产物 | `dist/manifest.json` 记录版本与 4 个 SHA-256 前缀 | 每次 build | 与 `cordis_inspect_self` 返回的源码逐段比对 |

---

## 6. 验证：每次更新后跑这一条

```powershell
pwsh -File E:\DSHarness_Project\repo-one\dsh-api-balance\install\verify.ps1
```

**A 段（静态，不需要 DSH 在跑）**：补丁块存在、两处 `node_modules` 包存在、包内 4 个关键文件存在。
**B 段（运行时，需要 DSH 在跑）**：直接请求插件自己注册的同源只读接口 `/dsh-api-balance/snapshot`，并打印 `apiKey.configured` / `balance.ok` / 已记账调用次数与累计花费。**B 段通了，界面就一定拿得到数据**（因为常驻平面的 Client 走的就是这条路径）。

---

## 7. 当前状态与残余风险

### 已就位的回滚点
- **常驻平面：已安装**（2026-09-10）。
  - 安装前补丁备份：`%APPDATA%\dsh-desktop\harness\profiles\web\cordis.patch.yml.bak-20260910-211652`
    （以及首次那次 `…-211518`，内容同为安装前状态）。
  - 插件包：`profiles\web\node_modules\dsh-api-balance-local\` 与 `profiles\node_modules\dsh-api-balance-local\`。
  - 补丁块：`cordis.patch.yml` 第 10–14 行，BEGIN/END 标记包裹，已通过回读自检。
  - **停用一条命令**：`pwsh -File install\uninstall.ps1` → 重启 DSH。
  - **注意：需重启 DSH 后才真正生效**；重启前补丁虽已写入，但不会加载。
- **动态平面**：`apibal-1` 当前为 **stopped**（为常驻安装让位，避免同 Slot 撞名）。
  - 版本 `pkg-1`（v0.1.0）与 `pkg-2`（v0.2.0）都还保留；`pkg-3`（v0.3.0）尚未定义。
  - 重新启用：`cordis_run apibal-1 pkg-2 run`；或按 §4.2 用最新源码定义 `pkg-3` 再 `update`。
- **桌面快捷方式**：`C:\Users\han\OneDrive\桌面\DSH API 余额与消耗.lnk`。删除它即可，无其它副作用。
- **工作区内改动**：`repo-one\dsh-api-balance\` 已于 2026-09-10 提交（`82b61ee`，21 个文件 / 3103 行），
  并打了回档标签 `dsh-api-balance-v0.3.0`；`repo-one` 分支 `main`，工作区干净。
- **远程备份**：`repo-one` 已配置远程 `vibecoding` → `https://github.com/baolongzhanshi1605-crypto/VibeCoding.git`。
  ⚠️ **推送当时未成功**：诊断显示 `github.com:443` 连不上（`git ls-remote` 一开始可通，
  随后读也超时、curl 两个端点均返回 `000`），本机 git 也未配置代理。
  网络恢复后运行 `pwsh -File tools\push-backup.ps1` 即可补上，脚本会重建分支并推送。
  远程目前只有 `main`（`c52ad8c`），**未被本次操作改动过任何字节**。

### 残余风险（诚实声明）
1. **常驻平面尚未在真实浏览器里跑过**。加载级验证已通过（`node tools/verify-artifacts.mjs`：bundle 能注册、
   factory 能执行、导出 `{apply}`；host 插件能 import、空 ctx 下 `apply()` 不抛）。但 DOM 渲染只能在装完之后看。
   因此**安装后第一件事就是跑 `verify.ps1` 的 B 段**；不通过就用 `uninstall.ps1` 退回，动态平面完全不受影响。
2. **T3 的兜底不是 100%**。组件内部做了完整兜底（hook 与渲染分离 + 全程 try/catch + 全字段 `|| {}`），但如果 React 自身在该 Slot 抛错，最坏结果是该 Slot 区域渲染失败——**影响范围限于该区域，不会让 DSH 进程崩溃**（进程崩溃只可能来自 Host 半，而 Host 半的全部外部调用都在 try/catch 内，且已用「空 ctx 调用 apply()」验证过降级路径）。
3. **`llm/stream` 拦截是全进程的**。如果插件的包装器有 bug，理论上会影响所有模型调用。当前包装器的设计是「逐 chunk 原样透传 + `finally` 记账 + 不写 `catch`」，即**不改变控制流、不吞异常**。这是本项目最需要保持克制的一段代码，任何改动都必须遵守这个约束。
4. **计费是估算**。只统计本进程存活期间的调用（重启归零），且按官方标价而非账单实扣。不要用它做财务对账。
5. **HTTP 路由的暴露面**。常驻平面会注册 `/dsh-api-balance/*` 只读接口，**返回余额与用量，不返回密钥**。它跟随 DSH 自身的监听地址（本机回环）；若你把 DSH 暴露到局域网，这些数字也会随之可读。

---

## 8. 禁止事项（本项目的红线，任何更新都不得越过）

- ❌ 不修改 `cordis.yml`、不改 DSH 的 bundle 列表、不动其它插件行；
- ❌ 不写 DSH 的 `settings.yaml` / `.credentials.yaml` / `sessions/`；
- ❌ 不使用 `git add -A` / `git reset --hard` / `git clean -fd` / 任何 push；
- ❌ 不为了「让它跑起来」而请求放宽沙箱或关闭审批；
- ❌ 不在 Host 半引入同步 IO、无界循环、或任何会阻塞事件循环的调用；
- ❌ 不在 `llm/stream` 包装器里吞掉异常或改变 chunk 顺序/内容。
