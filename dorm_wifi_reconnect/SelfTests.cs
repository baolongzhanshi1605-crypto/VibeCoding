using System.Security.Cryptography;

namespace DormWifi;

internal static class SelfTests
{
    public static int Run()
    {
        int count = 0;
        void Check(string name, System.Action body)
        {
            try { body(); count++; Console.WriteLine("PASS " + name); }
            catch { Console.Error.WriteLine("FAIL " + name); throw; }
        }
        static void Equal<T>(T expected, T actual)
        {
            if (!Equals(expected, actual)) throw new Exception($"Expected {expected}; got {actual}");
        }
        var now = DateTimeOffset.Parse("2026-10-25T12:00:00Z");
        var offline = new Observation(false, true, true, true);
        Check("healthy internet never reconnects or logs in", () =>
            Equal(ActionKind.Wait, new Recovery().Decide(new(true, false, false, false), now).Action));
        Check("transient outage requires confirmation", () =>
            Equal(ActionKind.ConfirmOffline, new Recovery().Decide(offline, now).Action));
        Check("early notifications cannot skip confirmation delay", () =>
        {
            var r = new Recovery(); r.Decide(offline, now);
            Equal(ActionKind.ConfirmOffline, r.Decide(offline, now.AddSeconds(1)).Action);
        });
        Check("confirmed portal on target wifi permits login", () =>
        {
            var r = new Recovery(); r.Decide(offline, now);
            Equal(ActionKind.Login, r.Decide(offline, now.AddSeconds(4)).Action);
        });
        Check("ordinary ISP outage never submits credentials", () =>
        {
            var r = new Recovery(); var o = offline with { PortalDetected = false }; r.Decide(o, now);
            Equal(ActionKind.Wait, r.Decide(o, now.AddSeconds(4)).Action);
        });
        Check("disconnected wifi reconnects saved profile after confirmation", () =>
        {
            var r = new Recovery(); var o = new Observation(false, false, false, false); r.Decide(o, now);
            Equal(ActionKind.ConnectWifi, r.Decide(o, now.AddSeconds(4)).Action);
        });
        Check("wifi retries are throttled even during notification storm", () =>
        {
            var r = new Recovery(); var o = new Observation(false, false, false, false); r.Decide(o, now);
            r.Decide(o, now.AddSeconds(4)); Equal(ActionKind.Wait, r.Decide(o, now.AddSeconds(5)).Action);
        });
        Check("other wifi connection is not hijacked", () =>
        {
            var r = new Recovery(); var o = new Observation(false, true, false, true); r.Decide(o, now);
            Equal(ActionKind.Wait, r.Decide(o, now.AddSeconds(4)).Action);
        });
        Check("rejected credentials pause instead of retrying", () =>
        {
            var r = new Recovery(); r.Decide(offline, now); r.LoginFinished(false, true, now.AddSeconds(4));
            Equal(ActionKind.Pause, r.Decide(offline, now.AddHours(1)).Action);
        });
        Check("persisted authentication pause survives restart", () =>
        {
            var r = new Recovery(); var o = offline with { AuthPaused = true }; r.Decide(o, now);
            Equal(ActionKind.Pause, r.Decide(o, now.AddSeconds(4)).Action);
        });
        Check("accepted login gets time to restore internet", () =>
        {
            var r = new Recovery(); r.Decide(offline, now); r.Decide(offline, now.AddSeconds(4));
            r.LoginFinished(true, false, now.AddSeconds(4));
            Equal(ActionKind.Wait, r.Decide(offline, now.AddSeconds(10)).Action);
        });
        Check("repeated displacement is limited to five attempts per 15 minutes", () =>
        {
            var r = new Recovery(); r.Decide(offline, now);
            for (int i = 0; i < 5; i++)
            {
                var t = now.AddSeconds(4 + i * 65);
                Equal(ActionKind.Login, r.Decide(offline, t).Action);
                r.LoginFinished(true, false, t);
                r.Decide(offline with { Online = true }, t.AddSeconds(1));
                r.Decide(offline, t.AddSeconds(2));
            }
            Equal(ActionKind.Wait, r.Decide(offline, now.AddSeconds(400)).Action);
        });
        Check("internet restoration resets outage confirmation", () =>
        {
            var r = new Recovery(); r.Decide(offline, now); r.Decide(offline with { Online = true }, now.AddSeconds(1));
            Equal(ActionKind.ConfirmOffline, r.Decide(offline, now.AddSeconds(5)).Action);
        });
        Check("Windows WLAN interface layout uses UTF-16 description", () => Equal(532, WindowsWifi.InterfaceLayoutSize));
        Check("portal password encoding matches independent AES implementation", () =>
        {
            Equal("28024ddd966836e71f949b9e2158a6ce", Portal.EncodePassword("test-password"));
            Equal("97641279b93b2ea78121f294e0d7a3d5", Portal.EncodePassword("1234567890123456"));
            Equal("f963d0f8b7e6487b7a942e12b464306c", Portal.EncodePassword("密码123"));
        });
        Check("credentials round-trip using current Windows user DPAPI", () =>
        {
            byte[] plain = System.Text.Encoding.UTF8.GetBytes("synthetic-test-only");
            byte[] encrypted = LocalSettings.Protect(plain, true);
            Equal(false, plain.SequenceEqual(encrypted));
            Equal(true, plain.SequenceEqual(LocalSettings.Protect(encrypted, false)));
        });
        Check("foreign redirects never receive credentials", () =>
        {
            Equal(false, Portal.IsPortal(new("http://192.168.0.200.evil.example:8080/portal.html")));
            Equal(false, Portal.IsPortal(new("http://192.168.0.200:8888/portal.html")));
            Equal(false, Portal.IsPortal(new("http://user@192.168.0.200:8080/portal.html")));
            Equal(true, Portal.IsPortal(new("http://192.168.0.200:8080/portal.html")));
        });
        Check("current portal redirect is recognized without persisting session URL", () =>
        {
            var source = new Uri("http://example.org/");
            var target = new Uri("http://192.168.0.200:8080/portal.html?vlan=test");
            Equal(target, Portal.DetectPortal(source, target, ""));
            Equal<Uri?>(null, Portal.DetectPortal(source, new Uri("http://example.org/portal.html"), ""));
        });
        Check("boot staging rejects a relative directory", () =>
        {
            bool rejected = false;
            try { BootSupport.ValidateStagePath("runtime/boot-staging-test"); }
            catch (ArgumentException) { rejected = true; }
            Equal(true, rejected);
        });
        Check("machine boot worker requires SYSTEM identity", () =>
            Equal(false, BootSupport.CanRunMachineWorker("S-1-5-21-1-2-3-1001")));
        Check("SYSTEM boot worker is allowed", () =>
            Equal(true, BootSupport.CanRunMachineWorker("S-1-5-18")));
        Check("boot staging refuses a directory not named for this export", () =>
        {
            bool rejected = false;
            try { BootSupport.ValidateStagePath(Path.Combine(Path.GetTempPath(), "ordinary-folder")); }
            catch (ArgumentException) { rejected = true; }
            Equal(true, rejected);
        });
        Check("machine DPAPI encrypts and decrypts synthetic account bytes", () =>
        {
            byte[] plain = System.Text.Encoding.UTF8.GetBytes("synthetic-machine-test-only");
            var encrypted = LocalSettings.Protect(plain, true, true);
            Equal(false, plain.SequenceEqual(encrypted)); Equal(true, plain.SequenceEqual(LocalSettings.Protect(encrypted, false)));
        });
        Check("machine credentials refuse inherited directory permissions", () =>
        {
            string directory = Path.Combine(AppContext.BaseDirectory, "test-output", "inherited-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory); bool rejected = false;
            try { BootSupport.EnsurePrivateDirectory(directory); } catch (UnauthorizedAccessException) { rejected = true; }
            Equal(true, rejected);
        });
        Check("private staging ACL permits machine credential round-trip", () =>
        {
            string directory = Path.Combine(AppContext.BaseDirectory, "test-output", "boot-staging-20261025-120000-" + Guid.NewGuid().ToString("N")[..8]);
            Directory.CreateDirectory(Path.GetDirectoryName(directory)!); BootSupport.CreatePrivateStage(directory);
            BootSupport.EnsurePrivateDirectory(directory);
            var settings = new LocalSettings(directory, true);
            var fixture = new Credentials("test-ssid", "test-profile", Guid.Empty, "synthetic-user", "synthetic-password");
            settings.Save(fixture); Equal(fixture, settings.Load());
            Equal("credentials.machine.dpapi", Path.GetFileName(settings.CredentialsPath));
            bool refused = false;
            try { BootSupport.CreatePrivateStage(directory); } catch (IOException) { refused = true; }
            Equal(true, refused);
        });
        Check("boot worker singleton is shared across login sessions", () =>
        { Equal(@"Global\", Worker.Scope(true)); Equal(@"Local\", Worker.Scope(false)); });
        Check("portal redirect survives an oversized response body", () =>
        {
            using var portal = new Portal(new FixtureHandler(_ => {
                var response = new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.Redirect) { Content = new System.Net.Http.StringContent(new string('x', 20000)) };
                response.Headers.Location = new Uri(Portal.Origin, "portal.html?vlan=fixture"); return response;
            }));
            Equal(new Uri(Portal.Origin, "portal.html?vlan=fixture"), portal.Probe().GetAwaiter().GetResult().Portal);
        });
        Check("large captive portal HTML is recognized from its bounded prefix", () =>
        {
            using var portal = new Portal(new FixtureHandler(_ => new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.OK) {
                Content = new System.Net.Http.StringContent("<script src='assert/portal.js'></script><script>user_login()</script>" + new string('x', 20000)) }));
            Equal(new Uri(Portal.Origin, "portal.html"), portal.Probe().GetAwaiter().GetResult().Portal);
        });
        Check("DNS failure can still reveal a portal using a numeric-IP discovery request", () =>
        {
            using var portal = new Portal(new FixtureHandler(request => {
                if (request.RequestUri!.Host != "1.1.1.1") throw new System.Net.Http.HttpRequestException("Synthetic DNS failure");
                var response = new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.Redirect) { Content = new System.Net.Http.StringContent("") };
                response.Headers.Location = new Uri(Portal.Origin, "portal.html"); return response;
            }));
            Equal(new Uri(Portal.Origin, "portal.html"), portal.Probe().GetAwaiter().GetResult().Portal);
        });
        Check("generic IP redirects and network outages never prove a captive portal", () =>
        {
            using var portal = new Portal(new FixtureHandler(_ => {
                var response = new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.Redirect) { Content = new System.Net.Http.StringContent("") };
                response.Headers.Location = new Uri("https://example.org/"); return response;
            }));
            var result = portal.Probe().GetAwaiter().GetResult(); Equal(false, result.Online); Equal<Uri?>(null, result.Portal);
        });
        Check("healthy internet finishes after a single lightweight request", () =>
        {
            int calls = 0;
            using var portal = new Portal(new FixtureHandler(_ => { calls++; return new(System.Net.HttpStatusCode.OK) { Content = new System.Net.Http.StringContent("Microsoft Connect Test") }; }));
            Equal(true, portal.Probe().GetAwaiter().GetResult().Online); Equal(1, calls);
        });
        Check("redirect headers are recognized before the body is read", () =>
        {
            using var portal = new Portal(new FixtureHandler(_ => {
                var response = new System.Net.Http.HttpResponseMessage(System.Net.HttpStatusCode.Redirect) { Content = new BrokenContent() };
                response.Headers.Location = new Uri(Portal.Origin, "portal.html"); return response;
            }));
            Equal(new Uri(Portal.Origin, "portal.html"), portal.Probe().GetAwaiter().GetResult().Portal);
        });
        Check("saved Wi-Fi automatic and manual modes are read independently of connection state", () =>
        {
            Equal("manual", WindowsWifi.ReadConnectionMode("<WLANProfile xmlns='urn:fixture'><connectionMode>manual</connectionMode></WLANProfile>"));
            Equal("auto", WindowsWifi.ReadConnectionMode("<WLANProfile><connectionMode>auto</connectionMode></WLANProfile>"));
            Equal("unknown", WindowsWifi.ReadConnectionMode("<WLANProfile/>"));
        });
        Check("Wi-Fi profile parsing refuses DTD and external entities", () =>
        {
            bool refused = false;
            try { WindowsWifi.ReadConnectionMode("<!DOCTYPE x [<!ENTITY test 'auto'>]><WLANProfile><connectionMode>&test;</connectionMode></WLANProfile>"); }
            catch (System.Xml.XmlException) { refused = true; }
            Equal(true, refused);
        });
        Console.WriteLine($"{count} tests passed"); return 0;
    }
    private sealed class FixtureHandler(Func<System.Net.Http.HttpRequestMessage, System.Net.Http.HttpResponseMessage> respond) : System.Net.Http.HttpMessageHandler
    {
        protected override Task<System.Net.Http.HttpResponseMessage> SendAsync(System.Net.Http.HttpRequestMessage request, CancellationToken cancellationToken)
            => Task.FromResult(respond(request));
    }
    private sealed class BrokenContent : System.Net.Http.HttpContent
    {
        protected override Task SerializeToStreamAsync(Stream stream, System.Net.TransportContext? context) => throw new IOException("Synthetic unreadable body");
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
    }
}
