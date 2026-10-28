using System.Net;
using Microsoft.AspNetCore.Http;
using StreamAssistant.Bridge.Web;

namespace StreamAssistant.Bridge.Tests;

/// <summary>The bridge only accepts the local network unless --allow-public true.</summary>
public sealed class LocalNetworkTests
{
    [Theory]
    [InlineData("127.0.0.1")]
    [InlineData("10.1.2.3")]
    [InlineData("172.16.254.2")]
    [InlineData("172.31.0.1")]
    [InlineData("192.168.1.10")]
    [InlineData("169.254.3.4")]
    [InlineData("100.101.102.103")]
    [InlineData("::1")]
    [InlineData("fe80::1")]
    [InlineData("fd12:3456::1")]
    [InlineData("::ffff:192.168.1.10")]
    public void Local_addresses(string address) => Assert.True(LocalNetwork.IsPrivate(IPAddress.Parse(address)));

    [Theory]
    [InlineData("8.8.8.8")]
    [InlineData("172.32.0.1")]
    [InlineData("172.15.255.255")]
    [InlineData("100.128.0.1")]
    [InlineData("193.168.1.1")]
    [InlineData("2001:4860:4860::8888")]
    [InlineData("::ffff:8.8.8.8")]
    public void Public_addresses(string address) => Assert.False(LocalNetwork.IsPrivate(IPAddress.Parse(address)));

    [Fact]
    public async Task Requests_from_the_internet_are_refused()
    {
        await using var bridge = new TestBridge();
        var refused = await bridge.Server.SendAsync(c => From(c, "203.0.113.7", "/api/status"), TestContext.Current.CancellationToken);
        Assert.Equal(StatusCodes.Status403Forbidden, refused.Response.StatusCode);
        // Again from the same address: still refused (logged only once)
        refused = await bridge.Server.SendAsync(c => From(c, "203.0.113.7", "/ws"), TestContext.Current.CancellationToken);
        Assert.Equal(StatusCodes.Status403Forbidden, refused.Response.StatusCode);
        var local = await bridge.Server.SendAsync(c => From(c, "192.168.1.20", "/api/status"), TestContext.Current.CancellationToken);
        Assert.Equal(StatusCodes.Status200OK, local.Response.StatusCode);
    }

    [Fact]
    public async Task Public_addresses_can_be_allowed()
    {
        await using var bridge = new TestBridge(allowPublic: true);
        var allowed = await bridge.Server.SendAsync(c => From(c, "203.0.113.7", "/api/status"), TestContext.Current.CancellationToken);
        Assert.Equal(StatusCodes.Status200OK, allowed.Response.StatusCode);
    }

    private static void From(HttpContext context, string address, string path)
    {
        context.Connection.RemoteIpAddress = IPAddress.Parse(address);
        context.Request.Method = "GET";
        context.Request.Path = path;
    }
}
