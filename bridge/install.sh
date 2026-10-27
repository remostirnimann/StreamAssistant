#!/bin/sh
# Installs the Stream Assistant Bridge as a service on Linux (systemd) or macOS (launchd).
#
#   curl -fsSL https://raw.githubusercontent.com/remostirnimann/StreamAssistant/main/bridge/install.sh | sudo sh
#   curl -fsSL https://raw.githubusercontent.com/remostirnimann/StreamAssistant/main/bridge/install.sh | sh   # macOS, no sudo
#
# Options (after "sh -s --" when piped):
#   --version X.Y.Z   install this release instead of the newest one
#   --uninstall       remove the service and the program; the settings (pairing) stay
#   --purge           with --uninstall: remove the settings too
#
# Linux: program in /opt/stream-assistant-bridge, settings in /var/lib/stream-assistant-bridge,
# runs as the user stream-assistant, which may use the Stream Decks (udev rule).
# macOS: program and settings in ~/Library/Application Support/Stream Assistant Bridge,
# a LaunchAgent starts it at login.
# Updates are installed from Home Assistant; running this script again does the same.
set -eu

REPO="remostirnimann/StreamAssistant"
NAME="stream-assistant-bridge"
VERSION=""
ACTION="install"
PURGE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --version) VERSION="${2:?--version needs a value}"; shift 2 ;;
        --version=*) VERSION="${1#*=}"; shift ;;
        --uninstall) ACTION="uninstall"; shift ;;
        --purge) PURGE=1; shift ;;
        -h|--help) sed -n '2,17p' "$0" 2>/dev/null || true; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "Error: $*" >&2; exit 1; }
info() { echo "==> $*"; }

OS="$(uname -s)"
case "$OS" in
    Linux)
        [ "$(id -u)" -eq 0 ] || fail "run as root (sudo sh)"
        PREFIX="/opt/$NAME"
        DATA="/var/lib/$NAME"
        SERVICE_USER="stream-assistant"
        UNIT="/etc/systemd/system/$NAME.service"
        RULES="/etc/udev/rules.d/70-stream-assistant.rules"
        ;;
    Darwin)
        [ "$(id -u)" -ne 0 ] || fail "run as your own user on macOS, not with sudo"
        PREFIX="$HOME/Library/Application Support/Stream Assistant Bridge"
        DATA="$PREFIX"
        LABEL="ch.streamassistant.bridge"
        PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
        ;;
    *) fail "unsupported system $OS (on Windows use the .msi installer)" ;;
esac

uninstall() {
    if [ "$OS" = Linux ]; then
        if command -v systemctl >/dev/null 2>&1 && [ -f "$UNIT" ]; then
            systemctl disable --now "$NAME" >/dev/null 2>&1 || true
            rm -f "$UNIT"
            systemctl daemon-reload
        fi
        rm -f "$RULES"
        rm -rf "$PREFIX"
        if [ "$PURGE" -eq 1 ]; then
            rm -rf "$DATA"
            userdel "$SERVICE_USER" >/dev/null 2>&1 || true
        fi
    else
        launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
        rm -f "$PLIST"
        if [ "$PURGE" -eq 1 ]; then
            rm -rf "$PREFIX"
        else
            rm -f "$PREFIX/$NAME" "$PREFIX/LICENSE"
        fi
    fi
    info "Stream Assistant Bridge removed"
}

if [ "$ACTION" = uninstall ]; then
    uninstall
    exit 0
fi

# What to download
case "$(uname -m)" in
    x86_64|amd64) ARCH="x64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) fail "unsupported processor $(uname -m)" ;;
esac
if [ "$OS" = Darwin ]; then
    RID="osx-$ARCH"
elif ls /lib/ld-musl-* >/dev/null 2>&1; then
    RID="linux-musl-$ARCH"
else
    RID="linux-$ARCH"
fi

if command -v curl >/dev/null 2>&1; then
    fetch() { curl -fsSL -o "$2" "$1"; }
    fetch_text() { curl -fsSL "$1"; }
elif command -v wget >/dev/null 2>&1; then
    fetch() { wget -q -O "$2" "$1"; }
    fetch_text() { wget -q -O - "$1"; }
else
    fail "curl or wget is needed"
fi

if [ -z "$VERSION" ]; then
    # The newest release, pre-releases included
    VERSION="$(fetch_text "https://api.github.com/repos/$REPO/releases?per_page=1" \
        | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p' | head -n 1)"
    [ -n "$VERSION" ] || fail "could not find the newest release"
fi
VERSION="${VERSION#v}"

ASSET="$NAME-$VERSION-$RID.tar.gz"
# SAB_RELEASE_URL: another place with the same layout (tests, mirrors)
BASE="${SAB_RELEASE_URL:-https://github.com/$REPO/releases/download}/v$VERSION"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM

info "Downloading Stream Assistant Bridge $VERSION ($RID)"
fetch "$BASE/$ASSET" "$TMP/$ASSET" || fail "download of $ASSET failed"
fetch "$BASE/SHA256SUMS.txt" "$TMP/SHA256SUMS.txt" || fail "download of the checksums failed"
EXPECTED="$(awk -v f="$ASSET" '$2 == f || $2 == "*" f { print $1 }' "$TMP/SHA256SUMS.txt")"
[ -n "$EXPECTED" ] || fail "$ASSET is not in SHA256SUMS.txt"
if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL="$(sha256sum "$TMP/$ASSET" | awk '{ print $1 }')"
else
    ACTUAL="$(shasum -a 256 "$TMP/$ASSET" | awk '{ print $1 }')"
fi
[ "$EXPECTED" = "$ACTUAL" ] || fail "checksum of $ASSET does not match"
mkdir "$TMP/files"
tar -xzf "$TMP/$ASSET" -C "$TMP/files"
[ -f "$TMP/files/$NAME" ] || fail "$ASSET does not contain $NAME"

if [ "$OS" = Linux ]; then
    if ! id "$SERVICE_USER" >/dev/null 2>&1; then
        info "Creating the user $SERVICE_USER"
        if command -v useradd >/dev/null 2>&1; then
            useradd --system --no-create-home --home-dir "$DATA" --shell /usr/sbin/nologin "$SERVICE_USER" 2>/dev/null \
                || useradd --system --no-create-home --home-dir "$DATA" --shell /sbin/nologin "$SERVICE_USER"
        else
            # Alpine (BusyBox)
            addgroup -S "$SERVICE_USER" && adduser -S -D -H -h "$DATA" -s /sbin/nologin -G "$SERVICE_USER" "$SERVICE_USER"
        fi
    fi
    GROUP="$(id -gn "$SERVICE_USER")"

    command -v systemctl >/dev/null 2>&1 && systemctl stop "$NAME" >/dev/null 2>&1 || true
    mkdir -p "$PREFIX" "$DATA"
    cp "$TMP/files/$NAME" "$PREFIX/$NAME"
    [ -f "$TMP/files/LICENSE" ] && cp "$TMP/files/LICENSE" "$PREFIX/LICENSE"
    chmod 755 "$PREFIX/$NAME"
    # The bridge replaces its own program when Home Assistant updates it
    chown -R "$SERVICE_USER:$GROUP" "$PREFIX" "$DATA"
    chmod 750 "$DATA"

    info "Allowing $SERVICE_USER to use Stream Decks"
    cat > "$RULES" <<EOF
# Stream Assistant Bridge: Elgato Stream Decks for the service user and the logged-in user
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0fd9", MODE="0660", GROUP="$GROUP", TAG+="uaccess"
EOF
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules && udevadm trigger --subsystem-match=hidraw || true
    fi

    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        cat > "$UNIT" <<EOF
[Unit]
Description=Stream Assistant Bridge
Documentation=https://github.com/$REPO/blob/main/docs/bridge.md
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
User=$SERVICE_USER
Group=$GROUP
WorkingDirectory=$DATA
ExecStart=$PREFIX/$NAME --config-dir $DATA --service true
# Also after an update: the bridge exits and the new version starts
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        systemctl daemon-reload
        systemctl enable --now "$NAME" >/dev/null
        systemctl restart "$NAME"
        info "Stream Assistant Bridge $VERSION runs as the service $NAME"
        echo "    The pairing code is in the log:  journalctl -u $NAME | grep -i pairing"
        echo "    or on this computer:             http://localhost:5390"
    else
        info "Stream Assistant Bridge $VERSION is in $PREFIX"
        echo "    No systemd found: start it with your init system as user $SERVICE_USER:"
        echo "    $PREFIX/$NAME --config-dir $DATA --service true"
    fi
else
    launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
    mkdir -p "$PREFIX" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    cp "$TMP/files/$NAME" "$PREFIX/$NAME"
    [ -f "$TMP/files/LICENSE" ] && cp "$TMP/files/LICENSE" "$PREFIX/LICENSE"
    chmod 755 "$PREFIX/$NAME"
    xattr -d com.apple.quarantine "$PREFIX/$NAME" >/dev/null 2>&1 || true
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PREFIX/$NAME</string>
        <string>--config-dir</string><string>$DATA</string>
        <string>--service</string><string>true</string>
    </array>
    <key>RunAtLoad</key><true/>
    <!-- Also after an update: the bridge exits and the new version starts -->
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$HOME/Library/Logs/stream-assistant-bridge.log</string>
    <key>StandardErrorPath</key><string>$HOME/Library/Logs/stream-assistant-bridge.log</string>
</dict>
</plist>
EOF
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    info "Stream Assistant Bridge $VERSION starts with your login"
    echo "    Pairing code: http://localhost:5390"
fi
