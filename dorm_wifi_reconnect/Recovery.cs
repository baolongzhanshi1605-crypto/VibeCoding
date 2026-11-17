namespace DormWifi;

internal enum ActionKind { Wait, ConfirmOffline, ConnectWifi, Login, Pause }
internal record Observation(bool Online, bool Connected, bool TargetWifi, bool PortalDetected, bool AuthPaused = false);
internal record Decision(ActionKind Action, int Seconds, string State);

internal sealed class Recovery
{
    private DateTimeOffset? offlineSince;
    private DateTimeOffset nextConnect, nextLogin;
    private readonly Queue<DateTimeOffset> attempts = new();
    private bool paused;
    private int failures;

    public Decision Decide(Observation o, DateTimeOffset now)
    {
        if (o.Online)
        {
            offlineSince = null; failures = 0;
            return new(ActionKind.Wait, 30, "online");
        }
        offlineSince ??= now;
        if (now - offlineSince < TimeSpan.FromSeconds(3))
            return new(ActionKind.ConfirmOffline, 3, "confirming-offline");
        if (!o.Connected)
        {
            if (now < nextConnect) return new(ActionKind.Wait, 30, "waiting-for-wifi");
            nextConnect = now.AddSeconds(30);
            return new(ActionKind.ConnectWifi, 10, "connecting-wifi");
        }
        if (!o.TargetWifi) return new(ActionKind.Wait, 60, "other-wifi-left-unchanged");
        if (paused || o.AuthPaused) return new(ActionKind.Pause, 60, "authentication-paused");
        if (!o.PortalDetected) return new(ActionKind.Wait, 60, "offline-without-portal-evidence");
        while (attempts.TryPeek(out var time) && now - time >= TimeSpan.FromMinutes(15)) attempts.Dequeue();
        if (now < nextLogin || attempts.Count >= 5) return new(ActionKind.Wait, 30, "authentication-cooldown");
        attempts.Enqueue(now); nextLogin = now.AddSeconds(60);
        return new(ActionKind.Login, 5, "authenticating");
    }

    public void LoginFinished(bool accepted, bool rejected, DateTimeOffset now)
    {
        if (rejected) { paused = true; return; }
        failures = accepted ? 0 : failures + 1;
        nextLogin = now.AddSeconds(accepted ? 60 : Math.Min(300, 30 * Math.Pow(2, Math.Min(4, failures))));
    }
}
