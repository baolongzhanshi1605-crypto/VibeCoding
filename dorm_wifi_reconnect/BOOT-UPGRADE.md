# 实验选项：登录 Windows 前运行

此方案保留源码，尚未完成真实开机未登录及远控验收。默认工具仍是当前用户登录后启动。不要仅为恢复 Wi-Fi 就直接运行管理员部署脚本。

方案使用 `DormWifiReconnect-Boot` 系统启动任务，以 SYSTEM 在会话 0 运行；程序部署到受保护的 `C:\ProgramData\DormWifiReconnect\app`，机器级加密账号副本存放于仅管理员和 SYSTEM 可访问的 `runtime`。它无需保存 Windows 登录密码。

机器级 DPAPI 不能单独限制同机其他身份解密，严格的目录/文件 ACL 是必须的保护。安装程序会先校验哈希、创建权限受限的独立目录，验证会话 0 的身份、账号读取和联网成功后才由外层脚本停止旧用户进程、撤下已备份的登录自启项。现有系统任务或安装目录不会覆盖。

审核、明确接受系统改动并具备管理员权限后，才能考虑执行：

```powershell
./build-boot.ps1
./Test-Boot.ps1
$stage = ./Prepare-Boot.ps1
./Enable-Boot.ps1 -StageDirectory $stage
```

准备过程会读取当前用户已有的账号，生成私有的加密安装副本，并备份旧自启快捷方式，不在参数或控制台中显示密码。部署需要 UAC 确认。若 Windows 未允许管理员部署，不修改执行策略或安全设置来绕过。

要回退已部署的这一安装，审查目标后运行：

```powershell
./Enable-Boot.ps1 -StageDirectory $stage -Rollback
```

回退禁用并停止匹配的系统任务、恢复旧登录自启并启动旧用户进程。任务、程序目录、账号文件和备份均保留，不自动清理。
账号修改不会自动从当前用户配置同步到系统任务，更新或再次部署前需要单独审查。不要把 `runtime`、安装清单、账号副本、个人快捷方式或本机日志公开。
