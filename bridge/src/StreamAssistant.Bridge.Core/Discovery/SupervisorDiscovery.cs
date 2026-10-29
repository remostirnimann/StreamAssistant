using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Protocol;

namespace StreamAssistant.Bridge.Discovery;

/// <summary>
/// As a Home Assistant add-on: tells Home Assistant through the Supervisor where the bridge
/// is, with a token, so the integration sets it up without a pairing code. Sent after every
/// start; Home Assistant updates an existing entry with the same bridge id.
/// </summary>
public sealed class SupervisorDiscovery(
    BridgeOptions options,
    BridgeServer server,
    PairingService pairing,
    HttpClient http,
    TimeProvider time,
    ILogger<SupervisorDiscovery> logger) : BackgroundService
{
    /// <summary>The integration's domain, as listed under discovery in the add-on's config.yaml.</summary>
    public const string Service = "stream_assistant";

    public static readonly TimeSpan RetryDelay = TimeSpan.FromSeconds(30);

    /// <summary>The message the Supervisor gets (also what Home Assistant receives as config).</summary>
    public JsonObject Message() => new()
    {
        ["service"] = Service,
        ["config"] = new JsonObject
        {
            // The add-on's name on the Supervisor network, which Home Assistant resolves
            ["host"] = Dns.GetHostName(),
            ["port"] = options.Port,
            ["bridge_id"] = server.Id,
            ["token"] = pairing.DiscoveryToken(),
        },
    };

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (options.Install != InstallKind.Addon || options.SupervisorToken is null)
        {
            return;
        }
        var warned = false;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, $"{options.SupervisorUrl}/discovery")
                {
                    Content = new StringContent(Message().ToJsonString(), Encoding.UTF8, "application/json"),
                };
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", options.SupervisorToken);
                using var response = await http.SendAsync(request, stoppingToken);
                if (response.IsSuccessStatusCode)
                {
                    logger.LogInformation("Home Assistant was told about this bridge (Supervisor discovery)");
                    return;
                }
                throw new HttpRequestException($"{(int)response.StatusCode} {await response.Content.ReadAsStringAsync(stoppingToken)}".Trim());
            }
            catch (Exception err) when (err is HttpRequestException or TaskCanceledException && !stoppingToken.IsCancellationRequested)
            {
                // The Supervisor may not be ready yet; keep trying, but warn only once
                logger.Log(warned ? LogLevel.Debug : LogLevel.Warning, "Supervisor discovery failed, retrying: {Error}", err.Message);
                warned = true;
            }
            try
            {
                await Task.Delay(RetryDelay, time, stoppingToken);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }
}
