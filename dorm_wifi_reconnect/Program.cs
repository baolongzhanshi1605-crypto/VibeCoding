namespace DormWifi;
internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        string directory = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "runtime"));
        int dataIndex = Array.IndexOf(args, "--data-dir");
        if (dataIndex >= 0 && dataIndex + 1 < args.Length) directory = Path.GetFullPath(args[dataIndex + 1]);
        bool machine = args.Contains("--machine");
        var settings = new LocalSettings(directory, machine);
        try
        {
            if (args.Contains("--self-test")) return SelfTests.Run();
            int prepareIndex = Array.IndexOf(args, "--prepare-boot");
            if (prepareIndex >= 0)
            {
                if (prepareIndex + 1 >= args.Length) throw new ArgumentException("Missing staging directory");
                BootSupport.Prepare(settings, Path.GetFullPath(args[prepareIndex + 1])); return 0;
            }
            if (args.Contains("--diagnose"))
            {
                using var wifi = new WindowsWifi(); using var portal = new Portal();
                var p = portal.Probe().GetAwaiter().GetResult();
                var description = portal.Describe().GetAwaiter().GetResult();
                Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new {
                    wifi = wifi.Read().Select(w => new { w.InterfaceId, w.Connected, w.Profile, w.Ssid, savedConnectionMode = w.Profile.Length > 0 ? wifi.ConnectionMode(w.InterfaceId, w.Profile) : "unknown" }),
                    online = p.Online, portalDetected = p.Portal is not null,
                    portalConfigCode = description.Code, authType = description.Auth, authLogic = description.Logic,
                    startupShortcut = SetupWindow.ShortcutPath, startupInstalled = File.Exists(SetupWindow.ShortcutPath),
                    credentialsConfigured = File.Exists(settings.CredentialsPath)
                })); return 0;
            }
            int observeIndex = Array.IndexOf(args, "--observe");
            if (observeIndex >= 0)
            {
                int seconds = int.Parse(args[observeIndex + 1]);
                if (seconds < 1 || seconds > 3600) throw new ArgumentException("Observe duration out of range");
                return Worker.Run(settings, seconds).GetAwaiter().GetResult();
            }
            if (args.Contains("--stop")) { Console.WriteLine(Worker.Stop(directory, machine) ? "Stop requested" : "Worker is not running"); return 0; }
            if (args.Contains("--install-startup")) { SetupWindow.InstallStartup(directory); Console.WriteLine(SetupWindow.ShortcutPath); return 0; }
            if (args.Contains("--remove-startup")) { SetupWindow.RemoveStartup(); return 0; }
            if (args.Contains("--setup")) return SetupWindow.Show(settings);
            if (args.Contains("--run"))
            {
                if (machine && !BootSupport.CanRunMachineWorker(System.Security.Principal.WindowsIdentity.GetCurrent().User?.Value ?? ""))
                    throw new UnauthorizedAccessException("Machine worker requires the configured SYSTEM task");
                if (!File.Exists(settings.CredentialsPath)) { new StateLog(directory).Write("credentials-not-configured-run-setup"); return 2; }
                return Worker.Run(settings).GetAwaiter().GetResult();
            }
            Console.WriteLine("--setup | --run | --stop | --diagnose | --observe SECONDS | --self-test | --install-startup | --remove-startup; optional --data-dir DIRECTORY");
            return 0;
        }
        catch
        {
            // Network exceptions can contain request URIs with login parameters. Never print raw exceptions.
            Console.Error.WriteLine("Operation failed. Check local configuration; sensitive details were suppressed.");
            if (args.Contains("--setup")) MessageBox.Show("配置未完成。请检查无线网卡和本机保存的设置。", "寝室 Wi-Fi 自动恢复");
            return 1;
        }
    }
}
