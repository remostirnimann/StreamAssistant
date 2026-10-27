using System.Globalization;

namespace StreamAssistant.Bridge.Hosting;

/// <summary>
/// A small log file (bridge.log in the settings folder) for the Windows service, which has no
/// console. Keeps one older file (bridge.log.1) when it reaches 1 MB.
/// </summary>
public sealed class FileLoggerProvider(string path) : ILoggerProvider
{
    private const long MaxSize = 1024 * 1024;
    private readonly Lock _lock = new();

    public ILogger CreateLogger(string categoryName) => new FileLogger(this, categoryName);

    public void Dispose()
    {
    }

    private void Write(string line)
    {
        lock (_lock)
        {
            try
            {
                var file = new FileInfo(path);
                if (file.Exists && file.Length > MaxSize)
                {
                    File.Move(path, path + ".1", overwrite: true);
                }
                File.AppendAllText(path, line + Environment.NewLine);
            }
            catch (Exception err) when (err is IOException or UnauthorizedAccessException)
            {
                // Logging must never stop the bridge
            }
        }
    }

    private sealed class FileLogger(FileLoggerProvider provider, string category) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => logLevel >= LogLevel.Information;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel) || (category.StartsWith("Microsoft", StringComparison.Ordinal) && logLevel < LogLevel.Warning))
            {
                return;
            }
            var line = string.Create(CultureInfo.InvariantCulture, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {logLevel.ToString()[..4].ToLowerInvariant()}: {category} {formatter(state, exception)}");
            provider.Write(exception is null ? line : $"{line}{Environment.NewLine}{exception}");
        }
    }
}
