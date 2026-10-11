"""Standalone entry point for the bundled deterministic demonstration model."""
from custom_components.openwrt_vpn.demo.engine import (
    CHECKS, PROTECTED, READ_METHODS, WRITE_METHODS, Controller, ModelError,
    exact, number, require, utc_now,
)

__all__ = ["CHECKS", "PROTECTED", "READ_METHODS", "WRITE_METHODS", "Controller", "ModelError",
           "exact", "number", "require", "utc_now"]
