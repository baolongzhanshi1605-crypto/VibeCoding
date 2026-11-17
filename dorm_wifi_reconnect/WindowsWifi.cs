using System.ComponentModel;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Xml;
using System.Xml.Linq;

namespace DormWifi;

internal record WifiState(Guid InterfaceId, string Description, bool Connected, string Profile, string Ssid, string Ip, string Mac);

// Native WLAN API avoids localized netsh parsing, child processes, and reading Wi-Fi keys.
internal sealed class WindowsWifi : IDisposable
{
    internal static int InterfaceLayoutSize => Marshal.SizeOf<InterfaceInfo>();
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct InterfaceInfo
    {
        public Guid Id;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string Description;
        public int State;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ConnectionParameters
    {
        public int Mode;
        [MarshalAs(UnmanagedType.LPWStr)] public string Profile;
        public IntPtr Ssid, DesiredBssidList;
        public int BssType;
        public uint Flags;
    }
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    private delegate void NotificationCallback(IntPtr data, IntPtr context);
    [DllImport("wlanapi.dll")] private static extern uint WlanOpenHandle(uint version, IntPtr reserved, out uint negotiated, out IntPtr handle);
    [DllImport("wlanapi.dll")] private static extern uint WlanCloseHandle(IntPtr handle, IntPtr reserved);
    [DllImport("wlanapi.dll")] private static extern uint WlanEnumInterfaces(IntPtr handle, IntPtr reserved, out IntPtr list);
    [DllImport("wlanapi.dll")] private static extern void WlanFreeMemory(IntPtr memory);
    [DllImport("wlanapi.dll")] private static extern uint WlanQueryInterface(IntPtr handle, ref Guid id, uint opcode, IntPtr reserved, out uint size, out IntPtr data, out uint valueType);
    [DllImport("wlanapi.dll")] private static extern uint WlanConnect(IntPtr handle, ref Guid id, ref ConnectionParameters parameters, IntPtr reserved);
    [DllImport("wlanapi.dll", CharSet = CharSet.Unicode)] private static extern uint WlanGetProfile(IntPtr handle, ref Guid id, string profile, IntPtr reserved, out IntPtr xml, ref uint flags, out uint access);
    [DllImport("wlanapi.dll")] private static extern uint WlanRegisterNotification(IntPtr handle, uint source, [MarshalAs(UnmanagedType.Bool)] bool ignoreDuplicate, NotificationCallback? callback, IntPtr context, IntPtr reserved, out uint previous);
    private readonly IntPtr handle;
    private readonly NotificationCallback callback;
    public event System.Action? Changed;

    public WindowsWifi()
    {
        uint error = WlanOpenHandle(2, IntPtr.Zero, out _, out handle);
        if (error != 0) throw new Win32Exception((int)error);
        callback = (_, _) => { try { Changed?.Invoke(); } catch (ObjectDisposedException) { } };
        WlanRegisterNotification(handle, 8, true, callback, IntPtr.Zero, IntPtr.Zero, out _);
    }
    public List<WifiState> Read()
    {
        uint result = WlanEnumInterfaces(handle, IntPtr.Zero, out var list);
        if (result != 0) throw new Win32Exception((int)result);
        try
        {
            int count = Marshal.ReadInt32(list); var states = new List<WifiState>();
            for (int i = 0; i < count; i++)
            {
                var info = Marshal.PtrToStructure<InterfaceInfo>(IntPtr.Add(list, 8 + i * Marshal.SizeOf<InterfaceInfo>()));
                string profile = "", ssid = "";
                if (info.State == 1 && WlanQueryInterface(handle, ref info.Id, 7, IntPtr.Zero, out uint size, out var data, out _) == 0)
                {
                    try
                    {
                        // WLAN_CONNECTION_ATTRIBUTES: 8-byte header, WCHAR profile[256], DOT11_SSID.
                        if (size >= 556)
                        {
                            profile = Marshal.PtrToStringUni(IntPtr.Add(data, 8), 256)!.TrimEnd('\0');
                            int len = Marshal.ReadInt32(data, 520);
                            if (len is >= 0 and <= 32)
                            {
                                byte[] bytes = new byte[len]; Marshal.Copy(IntPtr.Add(data, 524), bytes, 0, len);
                                ssid = System.Text.Encoding.UTF8.GetString(bytes);
                            }
                        }
                    }
                    finally { WlanFreeMemory(data); }
                }
                var adapter = NetworkInterface.GetAllNetworkInterfaces().FirstOrDefault(n => Guid.TryParse(n.Id, out var id) && id == info.Id);
                var ip = adapter?.GetIPProperties().UnicastAddresses.FirstOrDefault(a => a.Address.AddressFamily == AddressFamily.InterNetwork)?.Address.ToString() ?? "";
                string mac = adapter is null ? "" : string.Join("-", adapter.GetPhysicalAddress().GetAddressBytes().Select(b => b.ToString("x2")));
                states.Add(new(info.Id, info.Description, info.State == 1, profile, ssid, ip, mac));
            }
            return states;
        }
        finally { WlanFreeMemory(list); }
    }
    public void Connect(Guid id, string profile)
    {
        var p = new ConnectionParameters { Mode = 0, Profile = profile, BssType = 1 };
        uint error = WlanConnect(handle, ref id, ref p, IntPtr.Zero);
        if (error != 0) throw new Win32Exception((int)error);
    }
    internal static string ReadConnectionMode(string xml)
    {
        using var input = new StringReader(xml);
        using var reader = XmlReader.Create(input, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, MaxCharactersInDocument = 65536 });
        var root = XDocument.Load(reader).Root;
        string? mode = root?.Element(root.Name.Namespace + "connectionMode")?.Value;
        return mode is "auto" or "manual" ? mode : "unknown";
    }
    public string ConnectionMode(Guid id, string profile)
    {
        uint flags = 0; // Never request WLAN_PROFILE_GET_PLAINTEXT_KEY.
        if (WlanGetProfile(handle, ref id, profile, IntPtr.Zero, out var xml, ref flags, out _) != 0) return "unknown";
        try { return ReadConnectionMode(Marshal.PtrToStringUni(xml) ?? ""); }
        catch (XmlException) { return "unknown"; }
        finally { WlanFreeMemory(xml); }
    }
    public void Dispose()
    {
        WlanRegisterNotification(handle, 0, true, null, IntPtr.Zero, IntPtr.Zero, out _);
        WlanCloseHandle(handle, IntPtr.Zero);
        GC.KeepAlive(callback);
    }
}
