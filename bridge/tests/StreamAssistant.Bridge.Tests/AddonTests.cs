using System.Net;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Time.Testing;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Discovery;

namespace StreamAssistant.Bridge.Tests;

/// <summary>Records what the bridge sends to the Supervisor; fails the first <c>failures</c> calls.</summary>
internal sealed class FakeSupervisor(int failures = 0) : HttpMessageHandler
{
    private int _failures = failures;

    public List<(string Url, string? Auth, JsonObject Body)> Calls { get; } = [];

    public TaskCompletionSource Accepted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var body = (JsonObject)JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
        lock (Calls)
        {
            Calls.Add((request.RequestUri!.ToString(), request.Headers.Authorization?.ToString(), body));
        }
        if (Interlocked.Decrement(ref _failures) >= 0)
        {
            return new HttpResponseMessage(HttpStatusCode.ServiceUnavailable);
        }
        Accepted.TrySetResult();
        return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("""{"result":"ok","data":{"uuid":"abc"}}""") };
    }
}

/// <summary>The bridge as a Home Assistant add-on: options, discovery with a token, ingress.</summary>
public sealed class AddonTests
{
    private const int IngressPort = 8099;

    private static readonly Dictionary<string, string> AddonSettings = new()
    {
        ["install-kind"] = "addon",
        ["ingress-port"] = IngressPort.ToString(System.Globalization.CultureInfo.InvariantCulture),
        ["hid"] = "libusb",
        ["SUPERVISOR_TOKEN"] = "supervisor-secret",
        ["supervisor-url"] = "http://supervisor.test/",
    };

    private static TestBridge Addon(FakeSupervisor supervisor, TimeProvider? time = null) =>
        new(services =>
        {
            services.AddSingleton(new HttpClient(supervisor));
            if (time is not null)
            {
                services.AddSingleton(time);
            }
        }, settings: AddonSettings);

    [Fact]
    public void Options_of_the_addon()
    {
        var options = BridgeOptions.From(new ConfigurationBuilder().AddInMemoryCollection(AddonSettings!).Build());
        Assert.Equal(InstallKind.Addon, options.Install);
        Assert.Equal(IngressPort, options.IngressPort);
        Assert.Equal(HidAccess.Libusb, options.Hid);
        Assert.Equal("supervisor-secret", options.SupervisorToken);
        Assert.Equal("http://supervisor.test", options.SupervisorUrl);

        var plain = BridgeOptions.From(new ConfigurationBuilder().Build());
        Assert.Equal(InstallKind.Archive, plain.Install);
        Assert.Equal(0, plain.IngressPort);
        Assert.Equal(HidAccess.System, plain.Hid);
        Assert.Null(plain.SupervisorToken);
        Assert.Equal(BridgeOptions.DefaultSupervisorUrl, plain.SupervisorUrl);
    }

    [Fact]
    public async Task Discovery_sends_address_and_a_working_token()
    {
        var supervisor = new FakeSupervisor(failures: 1);
        var time = new FakeTimeProvider(DateTimeOffset.UtcNow);
        await using var bridge = Addon(supervisor, time);
        _ = bridge.Server;
        // The first call fails (Supervisor not ready yet); it is tried again after RetryDelay
        await WaitUntil(() => supervisor.Calls.Count == 1);
        await Task.Delay(100, TestContext.Current.CancellationToken);
        time.Advance(SupervisorDiscovery.RetryDelay);
        await supervisor.Accepted.Task.WaitAsync(TimeSpan.FromSeconds(10), TestContext.Current.CancellationToken);
        Assert.Equal(2, supervisor.Calls.Count);

        var (url, auth, body) = supervisor.Calls[^1];
        Assert.Equal("http://supervisor.test/discovery", url);
        Assert.Equal("Bearer supervisor-secret", auth);
        Assert.Equal("stream_assistant", (string?)body["service"]);
        var config = body["config"]!;
        Assert.Equal(Dns.GetHostName(), (string?)config["host"]);
        Assert.Equal(5390, (int)config["port"]!);
        Assert.Equal(bridge.Services.GetRequiredService<Protocol.BridgeServer>().Id, (string?)config["bridge_id"]);

        // Home Assistant connects with the token, without a pairing code
        var token = (string)config["token"]!;
        var (client, welcome, _) = await bridge.HelloAsync(token);
        await using (client)
        {
            // The Supervisor updates an add-on, not the bridge
            Assert.DoesNotContain("update", welcome["features"]!.AsArray().Select(f => (string?)f));
        }
        // The same token after every start; a new one once all clients were removed
        Assert.Equal(token, bridge.Pairing.DiscoveryToken());
        bridge.Pairing.RevokeAll();
        var fresh = bridge.Pairing.DiscoveryToken();
        Assert.NotEqual(token, fresh);
        Assert.True(bridge.Pairing.IsAuthorized(fresh));
        Assert.False(bridge.Pairing.IsAuthorized(token));
    }

    [Fact]
    public async Task No_discovery_outside_the_addon()
    {
        var supervisor = new FakeSupervisor();
        await using var bridge = new TestBridge(services => services.AddSingleton(new HttpClient(supervisor)));
        _ = bridge.Server;
        await Task.Delay(300, TestContext.Current.CancellationToken);
        Assert.Empty(supervisor.Calls);
        Assert.Null(bridge.Services.GetRequiredService<SettingsStore>().Settings.DiscoveryToken);
    }

    [Fact]
    public async Task Ingress_is_only_for_the_supervisor_and_counts_as_local()
    {
        await using var bridge = Addon(new FakeSupervisor());
        // Through ingress: the pairing code and the simulator are shown
        var status = await Get(bridge, "172.30.32.2", IngressPort, "/api/status");
        Assert.Equal(StatusCodes.Status200OK, status.Response.StatusCode);
        Assert.Equal(bridge.Pairing.Code, (string?)JsonNode.Parse(status.Response.Body)!["pairing_code"]);
        Assert.Equal(StatusCodes.Status200OK, (await Get(bridge, "172.30.32.2", IngressPort, "/sim")).Response.StatusCode);
        // Anyone else on the ingress port is refused, even from the add-on network
        Assert.Equal(StatusCodes.Status403Forbidden, (await Get(bridge, "172.30.33.5", IngressPort, "/")).Response.StatusCode);
        // The protocol port: the Supervisor's address is not special there
        var other = await Get(bridge, "172.30.32.2", 5390, "/api/status");
        Assert.Null((string?)JsonNode.Parse(other.Response.Body)!["pairing_code"]);
        Assert.Equal(StatusCodes.Status404NotFound, (await Get(bridge, "172.30.32.2", 5390, "/sim")).Response.StatusCode);
    }

    private static Task<HttpContext> Get(TestBridge bridge, string from, int port, string path) =>
        bridge.Server.SendAsync(c =>
        {
            c.Connection.RemoteIpAddress = IPAddress.Parse(from);
            c.Connection.LocalPort = port;
            c.Request.Method = "GET";
            c.Request.Path = path;
        }, TestContext.Current.CancellationToken);

    private static async Task WaitUntil(Func<bool> condition)
    {
        for (var i = 0; i < 100 && !condition(); i++)
        {
            await Task.Delay(50, TestContext.Current.CancellationToken);
        }
        Assert.True(condition());
    }
}
