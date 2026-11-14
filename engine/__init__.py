"""Shared, registry-driven ingestion engine (one engine for every provider profile).

All provider differences live in config/provider_profiles.yaml. Nothing in this package may branch on a
provider name; tests enforce that. The engine is read-only: it has no device-command or write interface.
"""
ENGINE_VERSION = "1.0.0"
