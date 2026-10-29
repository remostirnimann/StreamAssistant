using System.Net;
using StreamAssistant.Bridge.Configuration;

namespace StreamAssistant.Bridge.Web;

/// <summary>
/// As a Home Assistant add-on, the local pages are shown inside Home Assistant (ingress):
/// Home Assistant checks the login and the Supervisor forwards the requests to a port of
/// their own. Only the Supervisor may use that port; its requests count as local.
/// </summary>
public static class Ingress
{
    /// <summary>Where ingress requests always come from.</summary>
    public static readonly IPAddress Supervisor = IPAddress.Parse("172.30.32.2");

    /// <summary>A request on the ingress port (any sender).</summary>
    public static bool OnIngressPort(HttpContext context) =>
        context.RequestServices.GetRequiredService<BridgeOptions>().IngressPort is > 0 and var port
        && context.Connection.LocalPort == port;

    /// <summary>A request the Supervisor forwarded from a logged-in Home Assistant user.</summary>
    public static bool IsIngress(HttpContext context) =>
        OnIngressPort(context)
        && context.Connection.RemoteIpAddress is { } address
        && (address.IsIPv4MappedToIPv6 ? address.MapToIPv4() : address).Equals(Supervisor);

    /// <summary>Answers 403 to anyone but the Supervisor on the ingress port.</summary>
    public static void UseIngress(this WebApplication app) => app.Use(async (context, next) =>
    {
        if (OnIngressPort(context) && !IsIngress(context))
        {
            context.Response.StatusCode = StatusCodes.Status403Forbidden;
            return;
        }
        await next(context);
    });
}
