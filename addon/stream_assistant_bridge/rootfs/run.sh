#!/usr/bin/with-contenv bashio
# Starts the bridge with the add-on's options. Settings and pairing live in /data.
set -e

args=(
    --config-dir /data
    --install-kind addon
    --port 5390
    --ingress-port 8099
    --hid libusb
    # Discovery goes through the Supervisor; mDNS would not leave the add-on network
    --mdns false
    --name "$(bashio::config 'name')"
)
if bashio::config.has_value 'simulate'; then
    args+=(--simulate "$(bashio::config 'simulate')")
fi
case "$(bashio::config 'log_level')" in
    debug) args+=(--Logging:LogLevel:Default=Debug) ;;
    warning) args+=(--Logging:LogLevel:Default=Warning) ;;
esac

bashio::log.info "Starting Stream Assistant Bridge"
exec /opt/bridge/stream-assistant-bridge "${args[@]}"
