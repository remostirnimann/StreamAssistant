using StreamAssistant.Bridge.Hosting;

// Stream Assistant Bridge: offers control surfaces attached to this computer
// to Home Assistant (docs/bridge-protocol.md).
//
//   stream-assistant-bridge [--port 5390] [--name "Office PC"] [--config-dir <dir>]
//                           [--simulate 5x3[,4x2:4,neo...]] [--mdns false] [--usb false]
//                           [--unpair-all]

var app = BridgeHost.Build(args);
if (!BridgeHost.Prepare(app))
{
    return 1;
}
await app.RunAsync();
return 0;

/// <summary>Entry point, public for the tests.</summary>
public partial class Program;
