using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Runtime.InteropServices;

namespace DormWifi;

internal static class BootSupport
{
    internal static readonly string[] PayloadNames = ["DormWifiReconnect.exe", "DormWifiReconnect.dll", "DormWifiReconnect.deps.json", "DormWifiReconnect.runtimeconfig.json"];
    internal static void ValidateStagePath(string path)
    {
        if (!Path.IsPathFullyQualified(path) || !Regex.IsMatch(Path.GetFileName(path.TrimEnd('\\', '/')), @"^boot-staging-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$"))
            throw new ArgumentException("Expected a new absolute boot-staging directory");
        for (var p = new DirectoryInfo(path); p is not null; p = p.Parent)
            if (p.Exists && (p.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("Reparse points are not accepted");
    }
    internal static bool CanRunMachineWorker(string sid) => sid == "S-1-5-18";
    internal static void CreatePrivateStage(string stage)
    {
        ValidateStagePath(stage);
        if (Directory.Exists(stage) || File.Exists(stage)) throw new IOException("Private staging directory must be new");
        var user = WindowsIdentity.GetCurrent().User ?? throw new IOException("Current identity unavailable");
        var acl = new DirectorySecurity(); acl.SetAccessRuleProtection(true, false); acl.SetOwner(user);
        var inherit = InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit;
        foreach (var sid in new[] { user, new SecurityIdentifier("S-1-5-18"), new SecurityIdentifier("S-1-5-32-544") })
            acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, inherit, PropagationFlags.None, AccessControlType.Allow));
        new DirectoryInfo(stage).Create(acl);
    }
    internal static void EnsurePrivateDirectory(string directory)
    {
        var allowed = new HashSet<string> { WindowsIdentity.GetCurrent().User!.Value, "S-1-5-18", "S-1-5-32-544" };
        var info = new DirectoryInfo(directory);
        if (!info.Exists) throw new IOException("Protected directory does not exist");
        for (var p = info; p is not null; p = p.Parent)
            if ((p.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("Reparse points are not accepted");
        var acl = info.GetAccessControl();
        if (!acl.AreAccessRulesProtected) throw new UnauthorizedAccessException("Machine credential directory inherits access rules");
        foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
            if (rule.AccessControlType == AccessControlType.Allow && !allowed.Contains(rule.IdentityReference.Value))
                throw new UnauthorizedAccessException("Machine credential directory grants access to another identity");
    }
    internal static string HashFile(string path) { using var input = File.OpenRead(path); return Convert.ToHexString(SHA256.HashData(input)); }
    public static void Prepare(LocalSettings source, string stage)
    {
        ValidateStagePath(stage);
        if (source.Machine || Directory.Exists(stage) || File.Exists(stage)) throw new IOException("Staging directory must be new");
        if (!string.Equals(Path.GetDirectoryName(Path.GetFullPath(stage)), source.DirectoryPath, StringComparison.OrdinalIgnoreCase))
            throw new IOException("Staging must remain within this project's local runtime directory");
        var user = WindowsIdentity.GetCurrent().User ?? throw new IOException("Current identity unavailable");
        // Create the private directory with its final ACL, before any encrypted account data is written.
        CreatePrivateStage(stage);
        var staged = new LocalSettings(stage, true);
        var account = source.Load(); staged.Save(account);
        if (staged.Load() != account) throw new IOException("Prepared account verification failed");
        string payload = Path.Combine(stage, "payload"); Directory.CreateDirectory(payload);
        var hashes = new Dictionary<string, string>();
        foreach (string name in PayloadNames)
        {
            string from = Path.Combine(AppContext.BaseDirectory, name); string to = Path.Combine(payload, name);
            File.Copy(from, to, false); hashes[name] = HashFile(to);
            if (hashes[name] != HashFile(from)) throw new IOException("Payload verification failed");
        }
        string legacyExe = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "dist", "DormWifiReconnect.exe"));
        string shortcutHash = "";
        if (File.Exists(SetupWindow.ShortcutPath))
        {
            dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell")!)!;
            try
            {
                dynamic link = shell.CreateShortcut(SetupWindow.ShortcutPath);
                try
                {
                    if (!string.Equals(Path.GetFullPath((string)link.TargetPath), legacyExe, StringComparison.OrdinalIgnoreCase) ||
                        !string.Equals((string)link.Arguments, "--run --data-dir \"" + source.DirectoryPath + "\"", StringComparison.OrdinalIgnoreCase))
                        throw new IOException("Existing login startup belongs to another installation");
                }
                finally { Marshal.FinalReleaseComObject(link); }
            }
            finally { Marshal.FinalReleaseComObject(shell); }
            shortcutHash = HashFile(SetupWindow.ShortcutPath);
            File.Copy(SetupWindow.ShortcutPath, Path.Combine(stage, "previous-login-startup.lnk"), false);
            if (HashFile(Path.Combine(stage, "previous-login-startup.lnk")) != shortcutHash) throw new IOException("Shortcut backup verification failed");
        }
        var manifest = new {
            version = 1, preparedAt = DateTimeOffset.Now, sourceUserSid = user.Value,
            sourceDataDirectory = source.DirectoryPath, legacyExecutable = legacyExe,
            legacyShortcut = SetupWindow.ShortcutPath, legacyShortcutHash = shortcutHash,
            machineCredentialHash = HashFile(staged.CredentialsPath), payloadHashes = hashes
        };
        File.WriteAllText(Path.Combine(stage, "manifest.json"), JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true }));
        Console.WriteLine("Prepared encrypted boot installation; credentials were not printed.");
    }
}
