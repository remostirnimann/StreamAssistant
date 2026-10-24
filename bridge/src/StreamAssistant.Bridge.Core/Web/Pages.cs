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

    /// <summary>Request from this computer (loopback).</summary>
    public static bool IsLocal(HttpContext context) =>
        context.Connection.RemoteIpAddress is { } address ? IPAddress.IsLoopback(address) : true; // TestServer has no address
}
