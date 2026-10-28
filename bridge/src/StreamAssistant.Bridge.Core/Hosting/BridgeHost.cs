using System.Text.Json.Nodes;
using Microsoft.Extensions.Hosting.WindowsServices;
using Microsoft.Extensions.Logging.Console;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Devices;
using StreamAssistant.Bridge.Devices.Elgato;
using StreamAssistant.Bridge.Devices.Simulated;
using StreamAssistant.Bridge.Devices.Virtual;
using StreamAssistant.Bridge.Discovery;
using StreamAssistant.Bridge.Protocol;
using StreamAssistant.Bridge.Updates;
using StreamAssistant.Bridge.Web;

namespace StreamAssistant.Bridge.Hosting;

/// <summary>Builds and starts the bridge; used by the console program and the desktop app.</summary>
public static class BridgeHost
{
    /// <summary>The web application with all services and endpoints, not started yet.</summary>
    public static WebApplication Build(string[] args, Action<ILoggingBuilder>? logging = null)
    {
        var service = WindowsServiceHelpers.IsWindowsService();
        // Always next to the program, never the working directory: services start in System32
        // or in "/", and the configuration watcher would then watch the whole disk
        var builder = WebApplication.CreateSlimBuilder(new WebApplicationOptions
        {
            Args = args,
            ContentRootPath = AppContext.BaseDirectory,
        });
        builder.Logging.ClearProviders();
        builder.Logging.AddSimpleConsole(o =>
        {
            o.SingleLine = true;
            o.TimestampFormat = "HH:mm:ss ";
            o.ColorBehavior = LoggerColorBehavior.Default;
        });
        if (service)
        {
            // No console as a service: log to the settings folder
            var dir = BridgeOptions.From(builder.Configuration).ConfigDir;
            Directory.CreateDirectory(dir);
            builder.Logging.AddProvider(new FileLoggerProvider(Path.Combine(dir, "bridge.log")));
        }
        // Both do nothing unless the bridge runs as a Windows service or under systemd
        builder.Services.AddWindowsService(o => o.ServiceName = "StreamAssistantBridge");
        builder.Services.AddSystemd();
        builder.Logging.AddFilter("Microsoft", LogLevel.Warning);
        logging?.Invoke(builder.Logging);

        builder.Services.AddSingleton(TimeProvider.System);
        builder.Services.AddSingleton(sp => BridgeOptions.From(sp.GetRequiredService<IConfiguration>()));
        builder.Services.AddSingleton<SettingsStore>();
        builder.Services.AddSingleton<PairingService>();
        builder.Services.AddSingleton<DeviceManager>();
        builder.Services.AddSingleton<BridgeServer>();
        builder.Services.AddSingleton<Simulator>();
        builder.Services.AddSingleton<VirtualDecks>();
        builder.Services.AddSingleton<IUpdateInstaller, SelfInstaller>();
        builder.Services.AddSingleton(_ =>
        {
            var http = new HttpClient { Timeout = TimeSpan.FromMinutes(10) };
            http.DefaultRequestHeaders.UserAgent.ParseAdd($"stream-assistant-bridge/{BridgeServer.Version}");
            return http;
        });
        builder.Services.AddSingleton<UpdateService>();
        builder.Services.AddSingleton<IHidBackend, HidSharpBackend>();
        builder.Services.AddHostedService<ElgatoWatcher>();
        builder.Services.AddHostedService<MdnsAdvertiser>();
        // Read lazily: tests and the command line can set the port
        builder.WebHost.ConfigureKestrel((context, kestrel) =>
            kestrel.ListenAnyIP(context.Configuration.GetValue("port", BridgeOptions.DefaultPort)));

        var app = builder.Build();

        // Before everything else: the bridge is meant for the local network
        app.UseLocalNetworkOnly();

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

        return app;
    }

    /// <summary>
    /// Take the settings folder, attach devices and log the pairing code.
    /// Returns false when another bridge already uses the settings folder.
    /// </summary>
    public static bool Prepare(WebApplication app, bool virtualDecks = false)
    {
        var options = app.Services.GetRequiredService<BridgeOptions>();
        var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("StreamAssistant.Bridge");
        try
        {
            app.Services.GetRequiredService<SettingsStore>();
        }
        catch (AlreadyRunningException err)
        {
            logger.LogError("{Message}", err.Message);
            return false;
        }
        var pairing = app.Services.GetRequiredService<PairingService>();
        if (app.Configuration.GetValue("unpair-all", false))
        {
            pairing.RevokeAll();
        }
        var bridge = app.Services.GetRequiredService<BridgeServer>();
        logger.LogInformation("Stream Assistant Bridge {Version} \"{Name}\" (id {Id}), port {Port}", BridgeServer.Version, bridge.Name, bridge.Id, options.Port);
        logger.LogInformation("Settings: {Path}", app.Services.GetRequiredService<SettingsStore>().FilePath);
        SelfInstaller.CleanUp();
        // Update progress goes to Home Assistant
        app.Services.GetRequiredService<UpdateService>().Status += bridge.Broadcast;
        app.Services.GetRequiredService<Simulator>().Start();
        if (virtualDecks)
        {
            app.Services.GetRequiredService<VirtualDecks>().Start();
        }
        pairing.LogCode();
        if (options.Simulate.Count > 0)
        {
            logger.LogInformation("Simulator: http://localhost:{Port}/sim", options.Port);
        }
        return true;
    }
}
