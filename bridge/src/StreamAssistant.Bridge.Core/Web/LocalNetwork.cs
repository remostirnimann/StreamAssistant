using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using StreamAssistant.Bridge.Configuration;

namespace StreamAssistant.Bridge.Web;

/// <summary>
/// The bridge is meant for the local network (see docs/terms.md): unless <c>--allow-public true</c>,
/// it refuses connections from addresses that can come from the internet.
/// </summary>
public static class LocalNetwork
{
    private const int MaxLoggedAddresses = 100;

    private static readonly ConcurrentDictionary<string, bool> Logged = new();

    /// <summary>Loopback, private, link-local and carrier-grade NAT addresses (VPNs such as Tailscale).</summary>
    public static bool IsPrivate(IPAddress address)
    {
        if (address.IsIPv4MappedToIPv6)
        {
            address = address.MapToIPv4();
        }
        if (IPAddress.IsLoopback(address))
        {
            return true;
        }
        if (address.AddressFamily == AddressFamily.InterNetworkV6)
        {
            // fc00::/7 (unique local) and fe80::/10 (link-local)
            var first = address.GetAddressBytes();
            return (first[0] & 0xfe) == 0xfc || address.IsIPv6LinkLocal;
        }
        var b = address.GetAddressBytes();
        return b[0] == 10
            || (b[0] == 172 && (b[1] & 0xf0) == 16)
            || (b[0] == 192 && b[1] == 168)
            || (b[0] == 169 && b[1] == 254)
            || (b[0] == 100 && (b[1] & 0xc0) == 64);
    }

    /// <summary>Answers 403 to requests from public addresses, unless they are allowed.</summary>
    public static void UseLocalNetworkOnly(this WebApplication app)
    {
        var options = app.Services.GetRequiredService<BridgeOptions>();
        if (options.AllowPublic)
        {
            return;
        }
        var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger(typeof(LocalNetwork));
        app.Use(async (context, next) =>
        {
            // TestServer has no address
            if (context.Connection.RemoteIpAddress is { } address && !IsPrivate(address))
            {
                var text = address.ToString();
                if (Logged.Count < MaxLoggedAddresses && Logged.TryAdd(text, true))
                {
                    logger.LogWarning(
                        "Refused a connection from {Address}: the bridge only accepts the local network (--allow-public true allows others)",
                        text);
                }
                context.Response.StatusCode = StatusCodes.Status403Forbidden;
                await context.Response.WriteAsync("The bridge only accepts connections from the local network.");
                return;
            }
            await next(context);
        });
    }
}
