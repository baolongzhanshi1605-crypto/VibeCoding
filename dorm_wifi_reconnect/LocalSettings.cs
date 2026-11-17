using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;

namespace DormWifi;

internal record Credentials(string Ssid, string Profile, Guid InterfaceId, string Username, string Password);

internal sealed class LocalSettings(string directory, bool machine = false)
{
    public bool Machine { get; } = machine;
    public string DirectoryPath { get; } = Path.GetFullPath(directory);
    public string CredentialsPath => Path.Combine(DirectoryPath, Machine ? "credentials.machine.dpapi" : "credentials.dpapi");
    public string PausePath => Path.Combine(DirectoryPath, "authentication-paused.txt");
    public Credentials Load()
    {
        if (Machine) BootSupport.EnsurePrivateDirectory(DirectoryPath);
        byte[] clear = Protect(File.ReadAllBytes(CredentialsPath), false);
        try { return JsonSerializer.Deserialize<Credentials>(clear) ?? throw new IOException("Invalid local settings"); }
        finally { CryptographicOperations.ZeroMemory(clear); }
    }
    public void Save(Credentials settings)
    {
        Directory.CreateDirectory(DirectoryPath);
        if (Machine) BootSupport.EnsurePrivateDirectory(DirectoryPath);
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(settings);
        try
        {
            string temp = CredentialsPath + ".new";
            File.WriteAllBytes(temp, Protect(bytes, true, Machine)); File.Move(temp, CredentialsPath, true);
            if (File.Exists(PausePath)) File.Delete(PausePath);
        }
        finally { CryptographicOperations.ZeroMemory(bytes); }
    }
    public void Pause(string state)
    {
        Directory.CreateDirectory(DirectoryPath); File.WriteAllText(PausePath, state);
    }
    [StructLayout(LayoutKind.Sequential)] private struct Blob { public int Length; public IntPtr Data; }
    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(ref Blob input, string? description, IntPtr entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DllImport("crypt32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(ref Blob input, IntPtr description, IntPtr entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr memory);
    internal static byte[] Protect(byte[] bytes, bool encrypt, bool machine = false)
    {
        var pinned = GCHandle.Alloc(bytes, GCHandleType.Pinned);
        try
        {
            var input = new Blob { Length = bytes.Length, Data = pinned.AddrOfPinnedObject() };
            Blob output;
            bool ok = encrypt ? CryptProtectData(ref input, "Dorm Wi-Fi account", IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, machine ? 5u : 1u, out output)
                : CryptUnprotectData(ref input, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output);
            if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error());
            try { byte[] result = new byte[output.Length]; Marshal.Copy(output.Data, result, 0, result.Length); return result; }
            finally
            {
                // Clear decrypted unmanaged memory before returning it to Windows.
                for (int i = 0; i < output.Length; i++) Marshal.WriteByte(output.Data, i, 0);
                LocalFree(output.Data);
            }
        }
        finally { pinned.Free(); }
    }
}

internal sealed class StateLog(string directory)
{
    private string previous = "";
    public void Write(string state)
    {
        if (state == previous) return;
        Directory.CreateDirectory(directory);
        string path = Path.Combine(directory, "status.log");
        if (File.Exists(path) && new FileInfo(path).Length >= 131072) File.Move(path, path + ".1", true);
        // Only fixed program states are logged; never URLs, raw server messages, credentials, or exception text.
        File.AppendAllText(path, $"{DateTimeOffset.Now:O} {state}{Environment.NewLine}"); previous = state;
    }
}
