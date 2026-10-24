using System.Text.Json.Nodes;
using Microsoft.Extensions.Logging.Console;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Devices;
using StreamAssistant.Bridge.Discovery;
using StreamAssistant.Bridge.Devices.Simulated;
using StreamAssistant.Bridge.Protocol;
using StreamAssistant.Bridge.Web;

// Stream Assistant Bridge: offers control surfaces attached to this computer
// to Home Assistant (docs/bridge-protocol.md).
//
//   stream-assistant-bridge [--port 5390] [--name "Office PC"] [--config-dir <dir>]
//                           [--simulate 5x3[,8x4...]] [--mdns false] [--unpair-all]

var builder = WebApplication.CreateSlimBuilder(args);
builder.Logging.ClearProviders();
builder.Logging.AddSimpleConsole(o =>
{
    o.SingleLine = true;
    o.TimestampFormat = "HH:mm:ss ";
    o.ColorBehavior = LoggerColorBehavior.Default;
});
builder.Logging.AddFilter("Microsoft", LogLevel.Warning);

builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton(sp => BridgeOptions.From(sp.GetRequiredService<IConfiguration>()));
builder.Services.AddSingleton<SettingsStore>();
builder.Services.AddSingleton<PairingService>();
builder.Services.AddSingleton<DeviceManager>();
builder.Services.AddSingleton<BridgeServer>();
builder.Services.AddSingleton<Simulator>();
builder.Services.AddHostedService<MdnsAdvertiser>();
// Read lazily: tests and the command line can set the port
builder.WebHost.ConfigureKestrel((context, kestrel) =>
    kestrel.ListenAnyIP(context.Configuration.GetValue("port", BridgeOptions.DefaultPort)));

var app = builder.Build();

app.UseWebSockets(new WebSocketOptions
{
    KeepAliveInterval = TimeSpan.FromSeconds(10),
    KeepAliveTimeout = TimeSpan.FromSeconds(30),
});

// Protocol endpoint for Home Assistant
app.Map("/ws", async (HttpContext context, BridgeServer server, IHostApplicationLifetime lifetime) =>
{
    if (!context.WebSockets.IsWebSocketRequest)
    {
        context.Response.StatusCode = StatusCodes.Status426UpgradeRequired;
        return;
    }
    using var socket = await context.WebSockets.AcceptWebSocketAsync();
    // End sessions on shutdown instead of letting the host wait for them
    using var stop = CancellationTokenSource.CreateLinkedTokenSource(context.RequestAborted, lifetime.ApplicationStopping);
    await server.RunSessionAsync(socket, context.Connection.RemoteIpAddress?.ToString() ?? "?", stop.Token);
});

// Local pages: status (with the pairing code) and the simulator
app.MapGet("/", () => Pages.Html("status.html"));
app.MapGet("/api/status", (HttpContext context, BridgeServer server, BridgeOptions options, PairingService pairing) =>
{
    var local = Pages.IsLocal(context);
    var status = new JsonObject
    {
        ["bridge"] = server.BridgeJson(),
        ["port"] = options.Port,
        ["client"] = server.ActiveClient,
        ["devices"] = new JsonArray(server.Devices.All.Select(d => (JsonNode)new JsonObject
        {
            ["id"] = d.Info.Id,
            ["name"] = d.Info.Name,
            ["model"] = d.Info.Model,
            ["virtual"] = d.Info.Virtual,
        }).ToArray()),
        // Only shown on this computer: whoever knows the code can pair
        ["pairing_code"] = local ? pairing.Code : null,
        ["config_dir"] = local ? options.ConfigDir : null,
    };
    return Results.Text(status.ToJsonString(), "application/json");
});
app.MapGet("/sim", (HttpContext context) => Pages.IsLocal(context) ? Pages.Html("simulator.html") : Results.NotFound());
app.Map("/sim/ws", async (HttpContext context, Simulator simulator, IHostApplicationLifetime lifetime) =>
{
    if (!Pages.IsLocal(context) || !context.WebSockets.IsWebSocketRequest)
    {
        context.Response.StatusCode = StatusCodes.Status404NotFound;
        return;
    }
    using var socket = await context.WebSockets.AcceptWebSocketAsync();
    using var stop = CancellationTokenSource.CreateLinkedTokenSource(context.RequestAborted, lifetime.ApplicationStopping);
    await simulator.RunPageAsync(socket, stop.Token);
});

var options = app.Services.GetRequiredService<BridgeOptions>();
var logger = app.Services.GetRequiredService<ILogger<Program>>();
try
{
    app.Services.GetRequiredService<SettingsStore>();
}
catch (AlreadyRunningException err)
{
    logger.LogError("{Message}", err.Message);
    return 1;
}
var pairing = app.Services.GetRequiredService<PairingService>();
if (app.Configuration.GetValue("unpair-all", false))
{
    pairing.RevokeAll();
}
var bridge = app.Services.GetRequiredService<BridgeServer>();
logger.LogInformation("Stream Assistant Bridge {Version} \"{Name}\" (id {Id}), port {Port}", BridgeServer.Version, bridge.Name, bridge.Id, options.Port);
logger.LogInformation("Settings: {Path}", app.Services.GetRequiredService<SettingsStore>().FilePath);
app.Services.GetRequiredService<Simulator>().Start();
pairing.LogCode();
if (options.Simulate.Count > 0)
{
    logger.LogInformation("Simulator: http://localhost:{Port}/sim", options.Port);
}

await app.RunAsync();
return 0;

/// <summary>Entry point, public for the tests.</summary>
public partial class Program;
