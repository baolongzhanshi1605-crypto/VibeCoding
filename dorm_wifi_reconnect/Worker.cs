using System.Diagnostics;
using System.Net.NetworkInformation;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace DormWifi;

internal static class Worker
{
    internal static string Identity(string directory) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Path.GetFullPath(directory).TrimEnd('\\').ToUpperInvariant())))[..20];
    internal static string Scope(bool machine) => machine ? @"Global\" : @"Local\";
    public static bool Stop(string directory, bool machine = false)
    {
        if (!EventWaitHandle.TryOpenExisting(Scope(machine) + "DormWifiStop-" + Identity(directory), out var handle)) return false;
        using (handle) handle.Set(); return true;
    }
    public static bool WaitUntilStopped(string directory)
    {
        using var singleton = new Semaphore(1, 1, @"Local\DormWifiWorker-" + Identity(directory));
        if (!singleton.WaitOne(TimeSpan.FromSeconds(25))) return false;
        singleton.Release(); return true;
    }
    public static void Start(string directory)
    {
        Process.Start(new ProcessStartInfo(Environment.ProcessPath!) {
            UseShellExecute = false, CreateNoWindow = true,
            ArgumentList = { "--run", "--data-dir", directory }
        });
    }
    public static async Task<int> Run(LocalSettings settings, int observeSeconds = 0)
    {
        bool observe = observeSeconds > 0;
        using var singleton = new Semaphore(1, 1, Scope(settings.Machine) + "DormWifiWorker-" + Identity(settings.DirectoryPath) + (observe ? "-observe" : ""));
        if (!singleton.WaitOne(0)) return 0;
        using var stopped = new EventWaitHandle(false, EventResetMode.ManualReset, Scope(settings.Machine) + "DormWifiStop-" + Identity(settings.DirectoryPath) + (observe ? "-observe" : ""));
        using var changed = new AutoResetEvent(false);
        using var cancellation = new CancellationTokenSource();
        using var wifi = new WindowsWifi();
        using var portal = new Portal(cancellation.Token);
        var log = new StateLog(settings.DirectoryPath);
        var recovery = new Recovery();
        Credentials? credentials = observe ? null : settings.Load();
        var timer = Stopwatch.StartNew(); var proc = Process.GetCurrentProcess();
        var initialCpu = proc.TotalProcessorTime;
        long peakWorking = 0, peakPrivate = 0; int checks = 0, notifications = 0;
        wifi.Changed += Wake;
        NetworkAvailabilityChangedEventHandler availability = (_, _) => Wake();
        NetworkAddressChangedEventHandler address = (_, _) => Wake();
        NetworkChange.NetworkAvailabilityChanged += availability; NetworkChange.NetworkAddressChanged += address;
        void Wake() { Interlocked.Increment(ref notifications); changed.Set(); }
        log.Write(observe ? "observation-started-no-network-mutations" : "worker-started");
        try
        {
            while (!stopped.WaitOne(0) && (!observe || timer.Elapsed.TotalSeconds < observeSeconds))
            {
                int delay = 30;
                try
                {
                    var probe = await portal.Probe(); checks++;
                    var adapters = wifi.Read();
                    var current = credentials is null ? adapters.FirstOrDefault() : adapters.FirstOrDefault(a => a.InterfaceId == credentials.InterfaceId);
                    var observation = new Observation(probe.Online, current?.Connected == true,
                        current?.Ssid == credentials?.Ssid, probe.Portal is not null, File.Exists(settings.PausePath));
                    var decision = recovery.Decide(observation, DateTimeOffset.UtcNow);
                    log.Write(decision.State); delay = decision.Seconds;
                    if (!observe)
                    {
                        // A fixed-size status report proves session-0 execution and successful credential loading without exposing account data.
                        string executionReport = JsonSerializer.Serialize(new {
                            updatedAt = DateTimeOffset.Now, processId = proc.Id, sessionId = proc.SessionId,
                            identitySid = System.Security.Principal.WindowsIdentity.GetCurrent().User?.Value,
                            credentialsLoaded = credentials is not null, online = probe.Online, state = decision.State,
                            wifiAdapterPresent = current is not null, wifiConnected = current?.Connected == true,
                            targetWifiConnected = observation.TargetWifi, portalDetected = observation.PortalDetected
                        });
                        string destination = Path.Combine(settings.DirectoryPath, settings.Machine ? "execution.json" : "status.json");
                        File.WriteAllText(destination + ".new", executionReport); File.Move(destination + ".new", destination, true);
                    }
                    if (!observe && credentials is not null && current is not null)
                    {
                        if (decision.Action == ActionKind.ConnectWifi) wifi.Connect(current.InterfaceId, credentials.Profile);
                        else if (decision.Action == ActionKind.Login && probe.Portal is not null)
                        {
                            var result = await portal.Login(probe.Portal, current, credentials);
                            recovery.LoginFinished(result.Accepted, result.Rejected, DateTimeOffset.UtcNow);
                            if (result.Rejected) settings.Pause(result.State);
                            log.Write(result.State);
                        }
                    }
                }
                catch (Exception e) when (e is not OutOfMemoryException)
                {
                    log.Write(e is System.ComponentModel.Win32Exception win32 ? "wifi-api-error-" + win32.NativeErrorCode.ToString(System.Globalization.CultureInfo.InvariantCulture) : "temporary-error-retry-in-60-seconds"); delay = 60;
                    recovery.LoginFinished(false, false, DateTimeOffset.UtcNow);
                }
                proc.Refresh(); peakWorking = Math.Max(peakWorking, proc.WorkingSet64); peakPrivate = Math.Max(peakPrivate, proc.PrivateMemorySize64);
                // Event storms cannot produce a busy loop or skip action cooldowns.
                int remaining = observe ? Math.Max(0, observeSeconds - (int)timer.Elapsed.TotalSeconds) : delay;
                int seconds = Math.Min(delay, remaining);
                int signal = WaitHandle.WaitAny([stopped, changed], TimeSpan.FromSeconds(seconds));
                if (signal == 0) break;
                if (signal == 1 && stopped.WaitOne(TimeSpan.FromSeconds(3))) break;
            }
        }
        finally
        {
            NetworkChange.NetworkAvailabilityChanged -= availability; NetworkChange.NetworkAddressChanged -= address;
            wifi.Changed -= Wake; cancellation.Cancel(); log.Write(observe ? "observation-finished" : "worker-stopped");
            singleton.Release();
        }
        proc.Refresh();
        var report = new {
            readOnly = observe, elapsedSeconds = Math.Round(timer.Elapsed.TotalSeconds, 1), checks, notifications,
            workingSetMiB = Math.Round(proc.WorkingSet64 / 1048576d, 2), peakSampledWorkingSetMiB = Math.Round(peakWorking / 1048576d, 2),
            privateMiB = Math.Round(proc.PrivateMemorySize64 / 1048576d, 2), peakSampledPrivateMiB = Math.Round(peakPrivate / 1048576d, 2),
            cpuSeconds = Math.Round((proc.TotalProcessorTime - initialCpu).TotalSeconds, 3)
        };
        Console.WriteLine(JsonSerializer.Serialize(report));
        if (observe) File.WriteAllText(Path.Combine(settings.DirectoryPath, "observation.json"), JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
        return 0;
    }
}
