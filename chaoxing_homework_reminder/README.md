# Chaoxing Homework Reminder

这是一个本地 Windows 学习通作业提醒器。当前版本默认使用专用 Edge 登录态，只读获取作业列表，然后通过电脑弹窗提醒。

## 当前状态

- 默认配置文件：`config.json`
- 默认数据源：`provider = chaoxing`
- 专用 Edge 登录目录：`data/edge_profile`
- 课程缓存：`data/course_cards_attrs.json`
- 默认提醒窗口：36 小时
- 默认提醒方式：控制台输出 + Windows 弹窗
- 开机自启方式：当前用户 Windows 启动文件夹快捷方式，登录后运行一次
- 桌面快捷方式：打开本项目文件夹

## 只读边界

程序只做这些读取动作：

- 读取专用 Edge profile 里的学习通 cookie。
- GET 学习通课程页、作业列表页、作业详情页。
- 解析课程名、作业名、提交状态、截止时间。

程序不会：

- 读取或保存你的学习通账号密码。
- 破解验证码或绕过风控。
- 调用提交、保存、修改、删除类接口。
- 自动点击学习通页面上的提交按钮。
- 修改注册表或安装后台服务。

## 提醒规则

- `URGENT`：1 小时内截止，最短 15 分钟重复一次。
- `STRONG`：6 小时内截止。
- `PREVIEW`：36 小时内截止，每天最多提醒一次。
- `OVERDUE`：已过期未提交，每天最多提醒一次。
- 学习通未显示截止时间的未交作业：按 24 小时内预警处理，并在标题标注 `[未显示截止时间]`。

已提醒记录保存在 `data/state.json`。

## 常用命令

手动检查一次：

```powershell
.\run_check.ps1
```

打开专用学习通登录窗口：

```powershell
.\open_chaoxing_login.ps1
```

安装当前用户登录自启：

```powershell
.\install_startup_task.ps1
```

安装推荐触发器：登录后查一次、睡眠恢复查一次、每天 20:00 查一次：

```powershell
.\install_requested_triggers.ps1
```

创建桌面快捷方式：

```powershell
.\create_desktop_shortcut.ps1
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 注意

当前课程列表来自 `data/course_cards_attrs.json`。如果学习通课程有新增或删除，需要重新打开专用 Edge 登录窗口并刷新课程缓存。
