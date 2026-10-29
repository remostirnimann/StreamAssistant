FROM ghcr.io/home-assistant/base:3.24

ARG BUILD_ARCH
ARG BUILD_VERSION

# hidapi over libusb for the decks; the bridge itself is self-contained .NET
RUN apk add --no-cache hidapi libgcc libstdc++

COPY rootfs /

# The bridge of the same release, checked against its SHA256SUMS.txt. A bridge already in
# rootfs/opt/bridge (local test builds, see addon/README.md) is used instead.
RUN set -eu; \
    if [ ! -f /opt/bridge/stream-assistant-bridge ]; then \
        case "${BUILD_ARCH}" in \
            aarch64) rid=linux-musl-arm64 ;; \
            amd64) rid=linux-musl-x64 ;; \
            *) echo "Unsupported architecture ${BUILD_ARCH}"; exit 1 ;; \
        esac; \
        file="stream-assistant-bridge-${BUILD_VERSION}-${rid}.tar.gz"; \
        base="https://github.com/remostirnimann/StreamAssistant/releases/download/v${BUILD_VERSION}"; \
        cd /tmp; \
        curl -fsSL -o "${file}" "${base}/${file}"; \
        curl -fsSL -o SHA256SUMS.txt "${base}/SHA256SUMS.txt"; \
        grep "  ${file}\$" SHA256SUMS.txt | sha256sum -c -; \
        mkdir -p /opt/bridge; \
        tar -xzf "${file}" -C /opt/bridge; \
        rm -f "${file}" SHA256SUMS.txt; \
    fi; \
    chmod +x /opt/bridge/stream-assistant-bridge /run.sh

CMD ["/run.sh"]
