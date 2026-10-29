using System.Net;

namespace StreamAssistant.Bridge.Web;

internal static class Pages
{
    public static IResult Html(string name)
    {
        using var stream = typeof(Pages).Assembly.GetManifestResourceStream($"StreamAssistant.Bridge.Web.{name}")
            ?? throw new InvalidOperationException($"Missing page {name}");
        using var reader = new StreamReader(stream);
        return Results.Content(reader.ReadToEnd(), "text/html; charset=utf-8");
    }

    /// <summary>Request from this computer (loopback), or from Home Assistant's ingress (add-on).</summary>
    public static bool IsLocal(HttpContext context) =>
        context.Connection.RemoteIpAddress is { } address ? IPAddress.IsLoopback(address) || Ingress.IsIngress(context) : true; // TestServer has no address
}
