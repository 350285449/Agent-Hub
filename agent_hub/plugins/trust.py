from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    status: str = "untrusted"
    manifest_hash: str = ""
    granted_scopes: list[str] = field(default_factory=list)
    publisher_id: str = ""
    publisher_name: str = ""
    verified_publisher: bool = False
    issued_at: str = ""
    expires_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trusted": self.trusted,
            "signed": self.signed,
            "source": self.source,
            "reason": self.reason,
            "status": self.status,
            "manifest_hash": self.manifest_hash,
            "granted_scopes": list(self.granted_scopes),
            "publisher_id": self.publisher_id,
            "publisher_name": self.publisher_name,
            "verified_publisher": self.verified_publisher,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
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
        trusted, reason, status = _registry_entry_valid(
            config,
            manifest,
            registry_entry,
            manifest_hash,
            signature_valid,
        )
        scopes = normalize_capability_scopes(
            [
                *_list_value(registry_entry.get("capability_scopes")),
                *_list_value(registry_entry.get("scopes")),
                *config_scopes,
            ]
        )
        publisher = _publisher_metadata(registry_entry)
        return PluginTrustDecision(
            trusted=trusted,
            signed=signature_valid or bool(registry_entry.get("signature")),
            source="trust_registry",
            reason=reason,
            status=status,
            manifest_hash=manifest_hash,
            granted_scopes=scopes if trusted else [],
            issued_at=_safe_timestamp_text(registry_entry.get("issued_at")),
            expires_at=_safe_timestamp_text(registry_entry.get("expires_at")),
            **publisher,
        )

    if signature_valid:
        return PluginTrustDecision(
            trusted=True,
            signed=True,
            source="manifest_signature",
            reason="manifest_signature_verified",
            status="trusted",
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
            status="trusted",
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
) -> tuple[bool, str, str]:
    status = _registry_entry_status(entry)
    if status == "disabled":
        return False, "plugin_trust_registry_entry_disabled", status
    if status == "revoked":
        return False, "plugin_trust_registry_entry_revoked", status
    if status == "expired":
        return False, "plugin_trust_registry_entry_expired", status
    if str(entry.get("id") or manifest.id) != manifest.id:
        return False, "plugin_trust_registry_id_mismatch", "disabled"
    expected_version = entry.get("version")
    if expected_version is not None and str(expected_version) != str(manifest.version):
        return False, "plugin_trust_registry_version_mismatch", "disabled"
    expected_hash = entry.get("manifest_hash")
    if expected_hash is not None and str(expected_hash) != manifest_hash:
        return False, "plugin_trust_registry_hash_mismatch", "disabled"
    expected_signature = entry.get("signature")
    if expected_signature is not None and str(expected_signature) != str(getattr(manifest, "signature", "")):
        return False, "plugin_trust_registry_signature_mismatch", "disabled"
    timing_valid, timing_reason, timing_status = _registry_entry_timing_valid(entry)
    if not timing_valid:
        return False, timing_reason, timing_status
    if expected_hash is None and not signature_valid and not bool(getattr(config, "plugin_allow_unsigned", False)):
        return False, "unsigned_plugin_requires_manifest_hash_or_signature", "disabled"
    return True, "trusted_manifest_metadata_registered", "trusted"


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


def _registry_entry_status(entry: dict[str, Any]) -> str:
    if _entry_bool(entry, "revoked", False):
        return "revoked"
    if _entry_bool(entry, "disabled", False):
        return "disabled"
    raw = (
        entry.get("status")
        or entry.get("state")
        or entry.get("trust_status")
        or entry.get("lifecycle")
    )
    status = str(raw or "").strip().lower().replace("-", "_")
    if status in {"trusted", "disabled", "revoked", "expired"}:
        return status
    if not _entry_bool(entry, "trusted", True):
        return "disabled"
    return "trusted"


def _registry_entry_timing_valid(entry: dict[str, Any]) -> tuple[bool, str, str]:
    now = datetime.now(timezone.utc).timestamp()
    issued_at_raw = entry.get("issued_at")
    if _has_value(issued_at_raw):
        issued_at = _parse_timestamp(issued_at_raw)
        if issued_at is None:
            return False, "plugin_trust_registry_invalid_issued_at", "disabled"
        if issued_at > now + 300:
            return False, "plugin_trust_registry_entry_not_yet_valid", "disabled"
    expires_at_raw = entry.get("expires_at")
    if _has_value(expires_at_raw):
        expires_at = _parse_timestamp(expires_at_raw)
        if expires_at is None:
            return False, "plugin_trust_registry_invalid_expires_at", "disabled"
        if expires_at <= now:
            return False, "plugin_trust_registry_entry_expired", "expired"
    return True, "", "trusted"


def _publisher_metadata(entry: dict[str, Any]) -> dict[str, Any]:
    publisher = entry.get("publisher") if isinstance(entry.get("publisher"), dict) else {}
    source = publisher if publisher else entry
    publisher_id = _safe_text(source.get("publisher_id"))
    publisher_name = _safe_text(source.get("publisher_name"))
    verified = source.get("verified_publisher") is True and bool(publisher_id)
    return {
        "publisher_id": publisher_id,
        "publisher_name": publisher_name,
        "verified_publisher": verified,
    }


def _parse_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _entry_bool(entry: dict[str, Any], key: str, default: bool) -> bool:
    value = entry.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}
    return bool(value)


def _safe_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:200]


def _safe_timestamp_text(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    return _safe_text(value)


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


__all__ = [
    "CAPABILITY_SCOPES",
    "PluginTrustDecision",
    "canonical_manifest_bytes",
    "evaluate_plugin_trust",
    "manifest_hash_from_data",
    "manifest_manifest_hash",
    "normalize_capability_scopes",
]
