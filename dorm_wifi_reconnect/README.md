# Windows 寝室 Wi-Fi 自动恢复

轻量 Windows 后台工具：登录 Windows 后自动运行，断网时使用已保存的无线配置重新连接，需要时完成 Panabit 兼容的网页账号认证。无需常驻浏览器。

## 支持范围

- 正式使用方式为**登录 Windows、进入桌面后启动**；之后锁屏仍运行。关机、休眠和未登录期间不工作。
- 无线密码使用 Windows 已保存的配置；网页认证账号在本机窗口输入，用当前用户 DPAPI 加密保存。
- 默认兼容认证网关 `http://192.168.0.200:8080/` 的单步 radius/local/user 账号认证，不是通用校园网登录器。其他网关需要在 `Portal.cs` 中适配，不能通过临时跳转链接永久写死设备参数。
- 只恢复选定网卡和 SSID，已连接其他 Wi-Fi 或电脑通过其他接口联网时不抢切；不擅自打开用户关闭的无线总开关。
- 目前构建目标为 `net9.0-windows`。需要 Windows、.NET 9 Desktop Runtime；构建需要 .NET 9 SDK。运行环境版本请按自己的维护要求管理。

## 构建与首次使用

```powershell
Set-Location ./dorm_wifi_reconnect
./build.ps1
./Configure.cmd
```

在本机配置窗口确认 Wi-Fi 名称和已保存的配置名称，输入**网页认证**账号密码，点击“保存并启动”。无线密码无需重复填写。配置默认优先采用当前已连接的无线网络，请确认它确实是目标网络。

- `Start.cmd`：启动后台恢复；同一配置目录只允许一个实例。
- `Stop.cmd`：请求停止后台恢复。
- `Enable-Startup.ps1`：明确执行后创建当前用户的 `DormWifiReconnect.lnk` 登录自启项，拒绝覆盖同名现有项。安装目录移动后要重新配置自启。
- `dist/DormWifiReconnect.exe --remove-startup`：仅删除指向当前安装的启动项，不删除账号和日志。

工具不自动安装自启。不要把认证密码、设备绑定 URL、日志或 `runtime` 目录上传到 GitHub。

## 手动断开后没有重连

先区分“无线断开”和“无线连着但网页认证失效”。在配置目录查看 `runtime/status.json` 和 `runtime/status.log`，也可运行：

```powershell
dotnet ./dist/DormWifiReconnect.dll --diagnose --data-dir "$PWD/runtime"
```

诊断中的 `savedConnectionMode` 才是 Windows 保存的自动/手动连接设置。事件查看器里某次连接显示“使用配置文件手动连接”，也可能是程序调用 API 发出的请求，不能据此判断是谁点了连接。

若保存的配置为 `manual`，Windows 不会按自动配置主动连接；工具启动后仍会在断网时主动请求连接。可以在 Windows 无线设置勾选“自动连接”，或明确执行下面的辅助脚本：

```powershell
./Set-AutoConnect.ps1 -ProfileName '你的无线配置名称' -InterfaceName 'WLAN'
```

该脚本先把单个配置备份到私有 `runtime/wifi-profile-backup-*` 目录，再修改其连接模式，不导出明文无线密码，不断开当前连接。脚本不会被启动恢复流程自动调用。若要回退模式，使用 `netsh wlan set profileparameter name="配置名称" interface="WLAN" connectionmode=manual`；备份保留，完整配置导入应先核对目标。

## 检测与重试

正常每 30 秒进行一次轻量联网检查，第一个有效响应成功即结束；网络事件会唤醒检查。连续异常至少 3 秒后再恢复，避免瞬时波动触发登录。

需要恢复时：已断开就使用原有配置请求重连；只在目标网络上识别到固定网关的认证证据时提交网页认证。`connecting-wifi` 只表示请求已发出，Windows 的异步连接结果还要由下一次状态读取或 WLAN 系统事件确认。

认证检测优先读取跳转头，正文过大只取有限前缀；失败时额外尝试数字 IP 的 HTTP 请求来发现认证跳转，不把该请求本身当作“已联网”的证据。普通宽带故障不盲目反复提交账号。

每次认证至少间隔 60 秒；传输失败延长至最长 300 秒，每 15 分钟最多 5 次。认证被拒绝或遇到验证码等不支持的流程时暂停认证，重新配置后解除。无线重连最多每 30 秒请求一次。

## 账号与日志

`runtime/credentials.dpapi` 使用当前 Windows 用户保护；它不能抵御已控制该 Windows 用户或机器管理员的程序。不要向别人提供该文件。原认证站使用 HTTP，页面现有 AES 兼容编码不等于 HTTPS，工具无法修复网站的传输安全限制。

日志只写固定状态和必要的 Windows 数值错误码，不写账号、密码、认证请求 URL、服务端原文或异常原文。日志约 128 KiB 轮换一次，只保留一个历史文件；状态快照固定大小覆盖，避免无限积累。

## 验证与限制

```powershell
./build.ps1
./Test-Boot.ps1   # 只构造任务对象并校验脚本，不注册任务
dotnet ./dist/DormWifiReconnect.dll --observe 60 --data-dir "$PWD/test-output"
```

当前 34 项程序测试涵盖恢复状态机、次数限制、DPAPI、WLAN 布局、受限目录、认证加密兼容、跳转先于正文、超长页面、DNS 失败及 profile XML 安全解析。
`--observe` 禁用实际无线重连和认证提交，只测检测循环。模拟和短时只读测试不能证明重启、真实手动断开、被挤下线或现场网络下的长期恢复效果，需要另行验收。

源码保留[实验性的登录前运行方案](BOOT-UPGRADE.md)，它不属于默认部署，不应把其构建通过视为已通过登录前远控验收。
