"""Stream Deck model definitions (devices that can sit on a Network Dock)."""

from __future__ import annotations

from dataclasses import dataclass

ELGATO_VENDOR_ID = 0x0FD9
NETWORK_DOCK_PRODUCT_ID = 0xFFFF
# mDNS TXT "dt" value the Network Dock advertises
NETWORK_DOCK_DEVICE_TYPE = 215


@dataclass(frozen=True, slots=True)
class DeckModel:
    """Static properties of a Stream Deck model."""

    name: str
    product_ids: tuple[int, ...]
    cols: int
    rows: int
    key_size: int
    # Gen2 panels are mounted upside down, images must be rotated 180°
    rotate_180: bool = True
    # Offset of the first key state in a button input report
    key_data_offset: int = 3
    tested: bool = False

    @property
    def key_count(self) -> int:
        """Return the number of LCD keys."""
        return self.cols * self.rows

    def build_image_reports(self, key: int, jpeg: bytes) -> list[bytes]:
        """Split a JPEG into Gen2 'set key image' output reports."""
        packet_size = 1024
        header_size = 8
        reports: list[bytes] = []
        offset = 0
        part = 0
        while offset < len(jpeg) or part == 0:
            chunk = jpeg[offset : offset + packet_size - header_size]
            offset += len(chunk)
            report = bytearray(packet_size)
            report[0] = 0x02
            report[1] = 0x07
            report[2] = key
            report[3] = 1 if offset >= len(jpeg) else 0
            report[4:6] = len(chunk).to_bytes(2, "little")
            report[6:8] = part.to_bytes(2, "little")
            report[header_size : header_size + len(chunk)] = chunk
            reports.append(bytes(report))
            part += 1
        return reports


MODELS: tuple[DeckModel, ...] = (
    DeckModel("Stream Deck MK.2", (0x0080, 0x00A5, 0x00B9), 5, 3, 72, tested=True),
    DeckModel("Stream Deck Original v2", (0x006D,), 5, 3, 72),
    DeckModel("Stream Deck XL", (0x006C, 0x008F), 8, 4, 96),
)


def find_model(product_id: int) -> DeckModel | None:
    """Return the model for a USB product id, if supported."""
    for model in MODELS:
        if product_id in model.product_ids:
            return model
    return None


def brightness_report(percent: int) -> bytes:
    """Gen2 feature report that sets the panel brightness."""
    report = bytearray(32)
    report[0] = 0x03
    report[1] = 0x08
    report[2] = max(0, min(100, percent))
    return bytes(report)


def reset_report() -> bytes:
    """Gen2 feature report that shows the Elgato logo again."""
    report = bytearray(32)
    report[0] = 0x03
    report[1] = 0x02
    return bytes(report)
