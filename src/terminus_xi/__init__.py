"""Terminus XI Protocol v1 - deterministic watchdog runtime.

XI identifies inputs, evaluates frozen check contracts, admits or rejects
artifacts at named boundaries, and emits canonical receipts.

XI contains no probabilistic component. Nothing in this package calls a model.
"""

from __future__ import annotations

PROTOCOL_VERSION = "terminus-xi/1.0.0"
RUNTIME_VERSION = "terminus-xi-runtime/1.0.0"
FROZEN_AT = "KSL-01"

__all__ = [
    "PROTOCOL_VERSION",
    "RUNTIME_VERSION",
    "FROZEN_AT",
]
