using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace DormWifi;

internal record ProbeResult(bool Online, Uri? Portal);
internal record LoginResult(bool Accepted, bool Rejected, string State);

internal sealed class Portal : IDisposable
{
    internal static readonly Uri Origin = new("http://192.168.0.200:8080/");
    private readonly HttpClient http;
    private readonly CancellationToken stop;
    public Portal(CancellationToken stop = default) : this(new SocketsHttpHandler { UseProxy = false, AllowAutoRedirect = false, MaxConnectionsPerServer = 2, ConnectTimeout = TimeSpan.FromSeconds(3), PooledConnectionLifetime = TimeSpan.FromMinutes(3) }, stop) { }
    internal Portal(HttpMessageHandler handler, CancellationToken stop = default)
    {
        this.stop = stop;
        http = new(handler)
            { Timeout = TimeSpan.FromSeconds(4) };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("DormWifiReconnect/1.0");
        http.DefaultRequestHeaders.CacheControl = new() { NoCache = true, NoStore = true };
    }
    internal static bool IsPortal(Uri uri) => uri.Scheme == Origin.Scheme && uri.Host == Origin.Host && uri.Port == Origin.Port && string.IsNullOrEmpty(uri.UserInfo);
    internal static Uri? DetectPortal(Uri source, Uri? location, string body)
    {
        if (location is not null)
        {
            var absolute = location.IsAbsoluteUri ? location : new Uri(source, location);
            if (IsPortal(absolute)) return absolute;
        }
        var match = Regex.Match(body, @"http://192\.168\.0\.200:8080/(?:portal|ucenter)\.html[^\s""'<>]*", RegexOptions.IgnoreCase);
        if (match.Success && Uri.TryCreate(WebUtility.HtmlDecode(match.Value), UriKind.Absolute, out var u) && IsPortal(u)) return u;
        if (body.Contains("assert/portal.js", StringComparison.Ordinal) && body.Contains("user_login", StringComparison.Ordinal))
            return new Uri(Origin, "portal.html");
        return null;
    }
    public async Task<ProbeResult> Probe()
    {
        Uri? portal = null;
        (string Url, string Expected)[] probes = [
            ("http://www.msftconnecttest.com/connecttest.txt", "Microsoft Connect Test"),
            ("http://captive.apple.com/hotspot-detect.html", "<BODY>Success</BODY>"),
            // Discovery only: never use this response as proof of working internet.
            ("http://1.1.1.1/", "")
        ];
        foreach (var probe in probes)
        {
            try
            {
                using var response = await http.GetAsync(probe.Url, HttpCompletionOption.ResponseHeadersRead, stop);
                portal = DetectPortal(new Uri(probe.Url), response.Headers.Location, "");
                if (portal is not null) return new(false, portal);
                string body = await ReadBounded(response, 16384, prefixOnly: true);
                portal = DetectPortal(new Uri(probe.Url), null, body);
                if (portal is not null) return new(false, portal);
                bool valid = probe.Expected.Length > 0 && (probe.Expected == "Microsoft Connect Test" ? body.Trim() == probe.Expected : body.Contains(probe.Expected, StringComparison.OrdinalIgnoreCase));
                if (response.StatusCode == HttpStatusCode.OK && valid) return new(true, null);
            }
            catch (Exception e) when (e is HttpRequestException or TaskCanceledException or IOException) { stop.ThrowIfCancellationRequested(); }
        }
        return new(false, portal);
    }
    private async Task<string> ReadBounded(HttpResponseMessage response, int limit, bool prefixOnly = false)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(stop); timeout.CancelAfter(TimeSpan.FromSeconds(4));
        using var stream = await response.Content.ReadAsStreamAsync(timeout.Token);
        using var bytes = new MemoryStream(); byte[] buffer = new byte[4096];
        while (bytes.Length <= limit)
        {
            int read = await stream.ReadAsync(buffer.AsMemory(0, Math.Min(buffer.Length, limit + 1 - (int)bytes.Length)), timeout.Token);
            if (read == 0) return Encoding.UTF8.GetString(bytes.ToArray());
            bytes.Write(buffer, 0, read);
        }
        if (prefixOnly) return Encoding.UTF8.GetString(bytes.ToArray(), 0, limit);
        throw new IOException("Response exceeds configured size limit");
    }
    private async Task<JsonDocument> Api(Dictionary<string, string> data, string? username = null)
    {
        var url = new Uri(Origin, "api?" + string.Join("&", data.Select(kv => Uri.EscapeDataString(kv.Key) + "=" + Uri.EscapeDataString(kv.Value))));
        using var request = new HttpRequestMessage(HttpMethod.Post, url);
        request.Content = username is null ? new StringContent("") : new FormUrlEncodedContent(new Dictionary<string, string> { ["u8name"] = username });
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, stop);
        response.EnsureSuccessStatusCode();
        return JsonDocument.Parse(await ReadBounded(response, 1024 * 1024));
    }
    internal static string Text(JsonElement obj, string name) => obj.TryGetProperty(name, out var v) ? v.ToString() : "";
    private static Dictionary<string, string> Query(Uri uri)
    {
        var result = new Dictionary<string, string>();
        foreach (string entry in uri.Query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var p = entry.Split('=', 2); result[Uri.UnescapeDataString(p[0])] = p.Length == 2 ? Uri.UnescapeDataString(p[1]) : "";
        }
        return result;
    }
    public async Task<(string Code, string Auth, string Logic)> Describe()
    {
        using var d = await Api(new() { ["route"] = "portal", ["action"] = "load_portal_conf", ["device"] = "pc" });
        var root = d.RootElement;
        if (root.TryGetProperty("data", out var data) && data.TryGetProperty("policy", out var p))
            return (Text(root, "code"), Text(p, "auth1"), Text(p, "policy_logic"));
        return (Text(root, "code"), "", "");
    }
    public async Task<LoginResult> Login(Uri entry, WifiState wifi, Credentials credentials)
    {
        if (!IsPortal(entry) || !wifi.Connected || string.IsNullOrEmpty(wifi.Ip) || string.IsNullOrEmpty(wifi.Mac))
            return new(false, false, "waiting-for-current-wifi-address");
        // Only current redirect parameters are used. Never persist the captured VLAN/MAC URL.
        var q = Query(entry);
        using var config = await Api(new() {
            ["route"] = "portal", ["action"] = "load_portal_conf", ["device"] = "pc",
            ["ip"] = wifi.Ip, ["mac"] = wifi.Mac, ["vlan"] = q.GetValueOrDefault("vlan", "") });
        var root = config.RootElement;
        if (Text(root, "code") == "200") return new(true, false, "portal-already-authorized");
        if (Text(root, "code") != "0" || !root.TryGetProperty("data", out var data) || !data.TryGetProperty("policy", out var policy))
            return new(false, false, "portal-configuration-unavailable");
        string auth = Text(policy, "auth1");
        if (auth is not ("radius" or "local" or "user") || Text(policy, "policy_logic") != "1" ||
            Text(policy, "portal_type") != "local" || data.GetRawText().Contains("\"graphicInput\"", StringComparison.Ordinal))
            return new(false, true, "portal-requires-manual-authentication");
        // Recheck immediately before sending credentials: a disconnect/roam may occur while loading policy.
        using (var check = new WindowsWifi())
        {
            var current = check.Read().FirstOrDefault(w => w.InterfaceId == wifi.InterfaceId);
            if (current is null || !current.Connected || current.Ssid != credentials.Ssid || current.Ip != wifi.Ip || current.Mac != wifi.Mac)
                return new(false, false, "wifi-changed-before-authentication");
        }
        using var login = await Api(new() {
            ["route"] = "webauth", ["action"] = "user_login", ["auth_type"] = auth,
            ["ip"] = wifi.Ip, ["mac"] = wifi.Mac, ["code"] = "", ["username"] = credentials.Username,
            ["password"] = EncodePassword(credentials.Password), ["remember_me"] = "0"
        }, credentials.Username);
        bool ok = Text(login.RootElement, "code") == "0";
        return new(ok, !ok, ok ? "login-accepted-awaiting-network-check" : "authentication-rejected-paused");
    }
    internal static string EncodePassword(string password)
    {
        byte[] input = Encoding.UTF8.GetBytes(password);
        byte[] padded = new byte[(input.Length + 15) / 16 * 16]; input.CopyTo(padded, 0);
        using var aes = Aes.Create(); aes.Key = Encoding.UTF8.GetBytes("Panabit@1024_key");
        try { return Convert.ToHexString(aes.EncryptEcb(padded, PaddingMode.None)).ToLowerInvariant(); }
        finally { CryptographicOperations.ZeroMemory(input); CryptographicOperations.ZeroMemory(padded); }
    }
    public void Dispose() => http.Dispose();
}
