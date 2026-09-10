# NOTICE · dsh-api-balance

> 本文件是本子项目的**边界声明**，与 `README_DSH_GOVERNANCE.md` 一并适用；冲突时以治理手册为准。

## 1. 来源与归属

| 项 | 说明 |
| --- | --- |
| 本子项目 | `E:\DSHarness_Project\repo-one\dsh-api-balance`，独立编写，非复制自其它仓库/子项目 |
| 是否复制了别处的代码 | **没有**。本项目全部代码为本子项目原创 |
| 引用的外部**事实** | DeepSeek 官方 API 文档（余额接口字段、价格表、峰谷时段、图片 token 计算规则）；这些是公开事实，已在 `src/core/pricing.js` 与 `docs/TECHNICAL.md` 中标注出处 URL |
| 引用的**机制** | DSH 自身的公开服务契约（`credentials` / `subprocess` / `llm` / `slots` / `webServer` / `timer`），通过 Cordis Inspect 只读查询获得，未复制其源码 |
| 同类社区项目 | 编写前调研过 GitHub 上若干同类插件（如 `feiyang-dev/dsh-usage-plugin`、`Angelyeye/dsh-cost-tracker`、`Bob-Bo1/dsh-deepseek-balance`）。**仅作需求与形态参考，未使用其任何代码**，本项目也未安装它们 |

## 2. 冻结头注（借鉴 `repo-one` 多项目守则）

- 本项目**不引用**其它子项目，也不被其它子项目引用；子项目之间保持独立。
- 需要别处的小段内容时，一律「一次性复制 + 本 NOTICE 记录」，不做实时引用、不做 submodule 指向兄弟目录。
- 若未来确实需要长期共享，只进 `repo-one/shared/`（只读依赖 + `DEPENDENTS.md` 登记），本子项目当前**不使用** `shared/`。

## 3. 写入边界（本子项目有权改动的路径）

**允许写入**：
```text
E:\DSHarness_Project\repo-one\dsh-api-balance\**      （本子项目目录）
```
包含其构建产物 `dist/`（已 gitignore）。

**允许经用户明确批准后写入（L3，管理员平面）**：
```text
<DSH home>\profiles\web\cordis.patch.yml               （仅追加一个带标记的 insert 块，写前必备份）
<DSH home>\profiles\web\node_modules\dsh-api-balance-local\
<DSH home>\profiles\node_modules\dsh-api-balance-local\
C:\Users\han\OneDrive\桌面\DSH API 余额与消耗.lnk        （一个可随时删除的快捷方式）
```
以上三处**只由 `install/` 下的脚本在用户终端执行**；agent 不会自行写入 DSH 控制面。

**只读，一律不改**：
```text
E:\DSHarness_Project\README_DSH_GOVERNANCE.md          与容器根其它历史手册
E:\DSHarness_Project\machine-guard\**
E:\DSHarness_Project\repo-one\chaoxing-homework-reminder\**
E:\DSHarness_Project\repo-one\governance\**、shared\**
E:\DSHarness_Project\repo-one\.git\**、README.md、.gitignore
C:\Users\han\.dsh\**、<DSH home>\settings.yaml / .credentials.yaml / sessions\**
运行中的 @deepseek-ai/dsh 安装目录
```

## 4. 秘密处理

- 本项目的 agent **没有读取** `.credentials.yaml` 或任何密钥文件，`docs/TECHNICAL.md` §5.4 有完整说明。
- 插件运行期由 **DSH 官方的 `credentials` 服务**在进程内解析 `DEEPSEEK_API_KEY`，密钥只经 curl 的 stdin 传递，不进 argv、不进环境变量、不落盘、不进日志、不跨 RPC。
- `tools/probe-balance.mjs` 只从**环境变量**读取，且只打印长度与前 6 位。

## 5. Git 与提交

- 本项目当前在 `repo-one` 中是**未跟踪状态**，尚未 `git add`。
- 任何 `git add` / `git commit` 之前，必须先在对话中展示 `git status --short --branch`、`git diff --stat`、待 add 的精确路径（只用 `dsh-api-balance/` 这一个路径，不用 `git add -A`）、提交消息前缀 `dsh-api-balance:`，并获得明确批准。
- 不 push、不改写历史、不做 `reset --hard` / `clean -fd`。
