"""Home Assistant independent client for the Elgato Stream Deck Network Dock."""

from .cora import CoraError
from .dock import ChildInfo, DeckInfo, DockClient, DockInfo, probe
from .models import MODELS, NETWORK_DOCK_DEVICE_TYPE, DeckModel, find_model, find_model_by_id

__all__ = [
    "MODELS",
    "NETWORK_DOCK_DEVICE_TYPE",
    "ChildInfo",
    "CoraError",
    "DeckInfo",
    "DeckModel",
    "DockClient",
    "DockInfo",
    "find_model",
    "find_model_by_id",
    "probe",
]
