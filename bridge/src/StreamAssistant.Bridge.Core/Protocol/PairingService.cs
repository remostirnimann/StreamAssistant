using System.Security.Cryptography;
using System.Text;
using StreamAssistant.Bridge.Configuration;

namespace StreamAssistant.Bridge.Protocol;

public enum PairingResult
{
    Paired,
    InvalidCode,
    LockedOut,
}

/// <summary>
/// Pairing codes and client tokens (protocol section 3.2).
/// The current code is shown in the log and on the local status page; it
/// changes after every successful pairing.
/// </summary>
public sealed class PairingService
{
    public const int MaxFailures = 5;
    public static readonly TimeSpan LockoutTime = TimeSpan.FromMinutes(1);

    private readonly Lock _lock = new();
    private readonly SettingsStore _store;
    private readonly ILogger<PairingService> _logger;
    private readonly TimeProvider _time;
    private int _failures;
    private DateTimeOffset _lockedUntil = DateTimeOffset.MinValue;

    public PairingService(SettingsStore store, ILogger<PairingService> logger, TimeProvider time)
    {
        _store = store;
        _logger = logger;
        _time = time;
        Code = NewCode();
    }

    public string Code { get; private set; }

    /// <summary>Raised (from any thread) when the pairing code or the paired clients change.</summary>
    public event Action? Changed;

    public int PairedClients => _store.Settings.Clients.Count;

    public void LogCode() => _logger.LogWarning("Pairing code for Home Assistant: {Code}", Code);

    public bool IsAuthorized(string? token)
    {
        if (string.IsNullOrEmpty(token))
        {
            return false;
        }
        var hash = Hash(token);
        lock (_lock)
        {
            return _store.Settings.Clients.Any(c => CryptographicOperations.FixedTimeEquals(
                Encoding.ASCII.GetBytes(c.TokenHash), Encoding.ASCII.GetBytes(hash)));
        }
    }

    public PairingResult TryPair(string? code, string clientName, out string token)
    {
        token = "";
        lock (_lock)
        {
            var now = _time.GetUtcNow();
            if (now < _lockedUntil)
            {
                return PairingResult.LockedOut;
            }
            var ok = code is { Length: 6 } && CryptographicOperations.FixedTimeEquals(
                Encoding.ASCII.GetBytes(code), Encoding.ASCII.GetBytes(Code));
            if (!ok)
            {
                if (++_failures >= MaxFailures)
                {
                    _failures = 0;
                    _lockedUntil = now + LockoutTime;
                    _logger.LogWarning("Too many wrong pairing codes, pairing locked for {Seconds} s", LockoutTime.TotalSeconds);
                }
                return PairingResult.InvalidCode;
            }
            _failures = 0;
            token = Base64Url(RandomNumberGenerator.GetBytes(32));
            var hash = Hash(token);
            _store.Update(s => s.Clients.Add(new PairedClient { Name = clientName, TokenHash = hash, Paired = now }));
            Code = NewCode();
        }
        _logger.LogInformation("Paired with {Client}", clientName);
        LogCode();
        Changed?.Invoke();
        return PairingResult.Paired;
    }

    /// <summary>Forget all paired clients; they must pair again.</summary>
    public void RevokeAll()
    {
        lock (_lock)
        {
            _store.Update(s => s.Clients.Clear());
        }
        _logger.LogWarning("All paired clients were removed");
        Changed?.Invoke();
    }

    private static string NewCode() => RandomNumberGenerator.GetInt32(0, 1_000_000).ToString("D6");

    private static string Hash(string token) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(token)));

    private static string Base64Url(byte[] bytes) => Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
}
