# Chaoxing Homework Reminder

这是一个本地 Windows 作业提醒器。当前版本默认只做电脑弹窗提醒，不再使用微信推送。

## 当前状态

- 默认配置文件：`config.json`
- 默认作业数据：`data/manual_assignments.json`
- 默认提醒窗口：36 小时
- 默认提醒方式：控制台输出 + Windows 弹窗
- 开机自启方式：当前用户 Windows 启动文件夹快捷方式，登录后运行一次
- 桌面快捷方式：打开本项目文件夹，方便以后找到

## 提醒规则

- `URGENT`：1 小时内截止，最短 15 分钟重复一次。
- `STRONG`：6 小时内截止，登录/解锁/手动触发时更积极提醒。
- `PREVIEW`：36 小时内截止，每天最多提醒一次。
- `OVERDUE`：已过期未提交，每天最多提醒一次。

已提醒记录保存在 `data/state.json`，用于避免重复弹窗。

## 安全边界

当前项目不会：

- 自动登录学习通。
- 读取或保存学习通账号密码。
- 破解验证码或绕过风控。
- 自动提交、修改、点击学习通作业。
- 安装后台服务。
- 修改注册表。

已经提供的系统级操作只有一个当前用户启动文件夹快捷方式：`Chaoxing Homework Reminder Startup.lnk`。

## 常用命令

手动检查一次：

```powershell
.\run_check.ps1
```

打开学习通登录页：

```powershell
.\open_chaoxing_login.ps1
```

安装当前用户登录自启：

```powershell
.\install_startup_task.ps1
```

创建桌面快捷方式：

```powershell
.\create_desktop_shortcut.ps1
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 学习通接入下一步

你可以先用 `open_chaoxing_login.ps1` 打开学习通登录页，然后自己手动登录。后续真正接入时，应优先用浏览器开发者工具确认作业列表请求，只读取这些字段：

- 课程名
- 作业名
- 截止时间
- 提交状态
- 作业唯一 ID

接入时保持低频：登录/解锁检查一次，电脑开着时最多 30 分钟检查一次。登录态失效时停止请求并弹窗提醒重新登录。
