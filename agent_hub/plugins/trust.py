from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CAPABILITY_SCOPES = {
    "provider.read",
    "provider.call",
    "tool.register",
    "workflow.register",
    "memory.read",
    "memory.write",
    "filesystem.read",
    "filesystem.write",
    "network.call",
}


@dataclass(slots=True)
class PluginTrustDecision:
    trusted: bool = False
    signed: bool = False
    source: str = "untrusted"
    reason: str = "plugin_untrusted"
    manifest_hash: str = ""
    granted_scopes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trusted": self.trusted,
            "signed": self.signed,
            "source": self.source,
            "reason": self.reason,
            "manifest_hash": self.manifest_hash,
            "granted_scopes": list(self.granted_scopes),
        }


def evaluate_plugin_trust(config: Any, manifest: Any) -> PluginTrustDecision:
    manifest_hash = manifest_manifest_hash(manifest)
    registry_path = getattr(config, "plugin_trust_registry", None)
    registry_entry = _registry_entry(registry_path, manifest.id) if registry_path else None
    signature_valid = _signature_valid(config, manifest)
    config_scopes = _configured_scopes(config, manifest.id)

    if registry_path and registry_entry is None and not signature_valid:
        return PluginTrustDecision(
            source="trust_registry",
            reason="plugin_missing_from_trust_registry",
            manifest_hash=manifest_hash,
            granted_scopes=config_scopes,
        )

    if registry_entry is not None:
        trusted, reason = _registry_entry_valid(config, manifest, registry_entry, manifest_hash, signature_valid)
        scopes = normalize_capability_scopes(
            [
                *_list_value(registry_entry.get("capability_scopes")),
                *_list_value(registry_entry.get("scopes")),
                *config_scopes,
            ]
        )
        return PluginTrustDecision(
            trusted=trusted,
            signed=signature_valid or bool(registry_entry.get("signature")),
            source="trust_registry",
            reason=reason,
            manifest_hash=manifest_hash,
            granted_scopes=scopes,
        )

    if signature_valid:
        return PluginTrustDecision(
            trusted=True,
            signed=True,
            source="manifest_signature",
            reason="manifest_signature_verified",
            manifest_hash=manifest_hash,
            granted_scopes=config_scopes,
        )

    trusted_plugins = {str(item) for item in getattr(config, "trusted_plugins", []) or []}
    if manifest.id in trusted_plugins:
        return PluginTrustDecision(
            trusted=True,
            signed=False,
            source="trusted_plugins",
            reason="explicit_unsigned_plugin_allowlist",
            manifest_hash=manifest_hash,
            granted_scopes=config_scopes,
        )

    return PluginTrustDecision(
        source="untrusted",
        reason="plugin_untrusted",
        manifest_hash=manifest_hash,
        granted_scopes=config_scopes,
    )


def manifest_hash_from_data(data: dict[str, Any]) -> str:
    payload = canonical_manifest_bytes(data)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def manifest_manifest_hash(manifest: Any) -> str:
    existing = getattr(manifest, "manifest_hash", "")
    if isinstance(existing, str) and existing:
        return existing
    data = manifest.to_dict()
    data.pop("path", None)
    return manifest_hash_from_data(data)


def canonical_manifest_bytes(data: dict[str, Any]) -> bytes:
    clean = {
        str(key): value
        for key, value in data.items()
        if key not in {"signature", "path", "manifest_hash"}
    }
    return json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def normalize_capability_scopes(values: list[str]) -> list[str]:
    scopes: list[str] = []
    for value in values:
        scope = str(value or "").strip()
        if scope in CAPABILITY_SCOPES and scope not in scopes:
            scopes.append(scope)
    return scopes


def _registry_entry(path: Any, plugin_id: str) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    entries = data.get("plugins") if isinstance(data, dict) else data
    if isinstance(entries, dict):
        entry = entries.get(plugin_id)
        if isinstance(entry, dict):
            merged = dict(entry)
            merged.setdefault("id", plugin_id)
            return merged
    if isinstance(entries, list):
        for item in entries:
            if isinstance(item, dict) and str(item.get("id") or "") == plugin_id:
                return dict(item)
    return None


def _registry_entry_valid(
    config: Any,
    manifest: Any,
    entry: dict[str, Any],
    manifest_hash: str,
    signature_valid: bool,
) -> tuple[bool, str]:
    if not bool(entry.get("trusted", True)):
        return False, "plugin_trust_registry_entry_disabled"
    if str(entry.get("id") or manifest.id) != manifest.id:
        return False, "plugin_trust_registry_id_mismatch"
    expected_version = entry.get("version")
    if expected_version is not None and str(expected_version) != str(manifest.version):
        return False, "plugin_trust_registry_version_mismatch"
    expected_hash = entry.get("manifest_hash")
    if expected_hash is not None and str(expected_hash) != manifest_hash:
        return False, "plugin_trust_registry_hash_mismatch"
    expected_signature = entry.get("signature")
    if expected_signature is not None and str(expected_signature) != str(getattr(manifest, "signature", "")):
        return False, "plugin_trust_registry_signature_mismatch"
    if expected_hash is None and not signature_valid and not bool(getattr(config, "plugin_allow_unsigned", False)):
        return False, "unsigned_plugin_requires_manifest_hash_or_signature"
    return True, "trusted_manifest_metadata_registered"


def _signature_valid(config: Any, manifest: Any) -> bool:
    signature = str(getattr(manifest, "signature", "") or "").strip()
    env_name = getattr(config, "plugin_signature_key_env", None)
    key = os.environ.get(env_name, "") if isinstance(env_name, str) and env_name else ""
    if not signature or not key:
        return False
    digest = hmac.new(key.encode("utf-8"), canonical_manifest_bytes(manifest.to_dict()), hashlib.sha256).hexdigest()
    accepted = {digest, f"hmac-sha256:{digest}", f"sha256={digest}"}
    return signature in accepted


def _configured_scopes(config: Any, plugin_id: str) -> list[str]:
    grants = getattr(config, "plugin_capability_grants", {}) or {}
    if not isinstance(grants, dict):
        return []
    return normalize_capability_scopes(_list_value(grants.get(plugin_id)))


def _list_value(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


__all__ = [
    "CAPABILITY_SCOPES",
    "PluginTrustDecision",
    "canonical_manifest_bytes",
    "evaluate_plugin_trust",
    "manifest_hash_from_data",
    "manifest_manifest_hash",
    "normalize_capability_scopes",
]
