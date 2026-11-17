using System.Diagnostics;
using System.Runtime.InteropServices;

namespace DormWifi;

internal static class SetupWindow
{
    public static int Show(LocalSettings settings)
    {
        ApplicationConfiguration.Initialize();
        using var wifi = new WindowsWifi();
        var adapters = wifi.Read();
        var selected = adapters.FirstOrDefault(w => w.Connected) ?? adapters.FirstOrDefault();
        if (selected is null) throw new IOException("No Wi-Fi adapter found");
        Credentials? existing = null;
        if (File.Exists(settings.CredentialsPath)) existing = settings.Load();
        using var form = new Form { Text = "寝室 Wi-Fi 自动恢复", ClientSize = new Size(480, 340), FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, StartPosition = FormStartPosition.CenterScreen, AutoScaleMode = AutoScaleMode.Dpi };
        var description = new Label { Text = "仅用于这台电脑的寝室 Wi-Fi 和网页认证。\n账号密码保存在本机，使用当前 Windows 用户加密保护。", Location = new(22, 18), Size = new(435, 44) };
        var ssid = new TextBox { Text = existing?.Ssid ?? selected.Ssid, Location = new(145, 78), Width = 305 };
        var profile = new TextBox { Text = existing?.Profile ?? selected.Profile, Location = new(145, 119), Width = 305 };
        var username = new TextBox { Text = existing?.Username ?? "", Location = new(145, 160), Width = 305 };
        var password = new TextBox { UseSystemPasswordChar = true, Location = new(145, 201), Width = 305 };
        string[] labels = ["Wi-Fi 名称", "已保存的无线配置", "网页认证账号", "网页认证密码"];
        for (int i = 0; i < labels.Length; i++) form.Controls.Add(new Label { Text = labels[i], Location = new(22, 81 + i * 41), Size = new(120, 24) });
        var note = new Label { Text = "这里填写网页认证密码，Wi-Fi 无线密码继续使用 Windows 已保存的配置。", Location = new(22, 242), Size = new(430, 35) };
        var save = new Button { Text = "保存并启动", Location = new(210, 288), Size = new(115, 32) };
        var cancel = new Button { Text = "取消", Location = new(337, 288), Size = new(115, 32), DialogResult = DialogResult.Cancel };
        save.Click += (_, _) =>
        {
            if (ssid.Text.Length == 0 || profile.Text.Length == 0 || username.Text.Trim().Length == 0 || password.Text.Length == 0)
            { MessageBox.Show(form, "请填写完整。密码不显示、不写入日志。", "尚未填写完整"); return; }
            try
            {
                if (Worker.Stop(settings.DirectoryPath) && !Worker.WaitUntilStopped(settings.DirectoryPath))
                {
                    MessageBox.Show(form, "旧后台进程尚未停止，请稍后重试。", "正在停止"); return;
                }
                settings.Save(new(ssid.Text, profile.Text, existing?.InterfaceId ?? selected.InterfaceId, username.Text.Trim(), password.Text));
                password.Clear(); Worker.Start(settings.DirectoryPath);
                MessageBox.Show(form, "设置已保存，后台恢复已启动。\n若认证被拒绝，工具会暂停认证，请检查账号后重新配置。", "已启动");
                form.DialogResult = DialogResult.OK; form.Close();
            }
            catch { MessageBox.Show(form, "保存或启动失败。请确认目录可写，并使用当前 Windows 用户运行。", "未完成"); }
        };
        form.Controls.AddRange([description, ssid, profile, username, password, note, save, cancel]);
        form.AcceptButton = save; form.CancelButton = cancel;
        form.ShowDialog(); return 0;
    }

    internal static string ShortcutPath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup), "DormWifiReconnect.lnk");
    public static void InstallStartup(string directory)
    {
        if (File.Exists(ShortcutPath)) throw new IOException("Startup shortcut already exists; review it before replacement");
        Type type = Type.GetTypeFromProgID("WScript.Shell") ?? throw new IOException("Windows shortcut service unavailable");
        dynamic shell = Activator.CreateInstance(type)!;
        try
        {
            dynamic shortcut = shell.CreateShortcut(ShortcutPath);
            try
            {
                shortcut.TargetPath = Environment.ProcessPath!;
                shortcut.Arguments = "--run --data-dir \"" + directory + "\"";
                shortcut.WorkingDirectory = AppContext.BaseDirectory; shortcut.WindowStyle = 7;
                shortcut.Description = "寝室 Wi-Fi 断线恢复与网页认证"; shortcut.Save();
            }
            finally { Marshal.FinalReleaseComObject(shortcut); }
        }
        finally { Marshal.FinalReleaseComObject(shell); }
    }
    public static void RemoveStartup()
    {
        if (!File.Exists(ShortcutPath)) return;
        dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell")!)!;
        try
        {
            dynamic shortcut = shell.CreateShortcut(ShortcutPath);
            try
            {
                if (!string.Equals(Path.GetFullPath((string)shortcut.TargetPath), Environment.ProcessPath, StringComparison.OrdinalIgnoreCase))
                    throw new IOException("Shortcut belongs to another installation; refusing removal");
            }
            finally { Marshal.FinalReleaseComObject(shortcut); }
        }
        finally { Marshal.FinalReleaseComObject(shell); }
        File.Delete(ShortcutPath);
    }
}
