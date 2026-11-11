"""
Channels → VS Code: serve the packaged extension (.vsix) for direct install.
═══════════════════════════════════════════════════════════════════════════════
The Marketplace listing isn't always available, so tenants install the extension
directly: download the .vsix here, then VS Code → Extensions → "Install from
VSIX…" (or `code --install-extension <file>.vsix`).

Ops drops the built artifact (`vsce package`) into AG_VSCODE_VSIX_DIR; we serve the
newest .vsix found. No per-tenant build is needed — the extension is the same for
everyone and carries the tenant via its `agent.tenantDomain` setting (mirroring the
Teams ?tenant= and widget ?tenant= mechanism).
"""
from __future__ import annotations

import glob
import io
import json
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

VSIX_DIR = os.environ.get("AG_VSCODE_VSIX_DIR", "")

MARKETPLACE_URL = os.environ.get(
    "AG_VSCODE_MARKETPLACE_URL",
    "https://marketplace.visualstudio.com/items?itemName=storeglance.antigravity-agent",
)

_CANDIDATE_DIRS = [
    VSIX_DIR,
    "/var/lib/storeglance-agent/vsix/vscode",
    str(Path(__file__).resolve().parents[3] / "agent.vscode-extension"),
]

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)?)")


def find_latest_vsix() -> Tuple[Optional[str], Optional[str]]:
    """Return (absolute_path, filename) of the newest .vsix, or (None, None)."""
    for d in _CANDIDATE_DIRS:
        if not d:
            continue
        files = glob.glob(os.path.join(d, "*.vsix"))
        if files:
            newest = max(files, key=os.path.getmtime)
            return newest, os.path.basename(newest)
    return None, None


def parse_version(filename: Optional[str]) -> str:
    """Best-effort semver pulled from the .vsix filename (e.g. agent-1.0.0.vsix)."""
    if not filename:
        return ""
    stem = filename[:-5] if filename.lower().endswith(".vsix") else filename
    m = _VERSION_RE.search(stem)
    return m.group(1) if m else ""


_PREFILL_KEYS = {"agent.tenantDomain": "tenant_domain", "agent.apiUrl": "api_url"}


def build_tenant_vsix(path: str, *, tenant_domain: str = "", api_url: str = "") -> bytes:
    """Return the .vsix bytes with the extension's config defaults pre-filled for
    this tenant. A .vsix is a zip; we rewrite only `extension/package.json`'s
    `contributes.configuration.properties[*].default` and copy every other entry
    verbatim. On any error we fall back to the untouched original (best-effort —
    a tenant-agnostic install still works, the user just sets the domain manually)."""
    values = {"agent.tenantDomain": (tenant_domain or "").strip().lower(),
              "agent.apiUrl": (api_url or "").strip()}
    try:
        with open(path, "rb") as f:
            raw = f.read()
        src = zipfile.ZipFile(io.BytesIO(raw))
        pkg_name = next((n for n in src.namelist()
                         if n.endswith("package.json") and "/" in n
                         and n.count("/") == 1), "extension/package.json")
        pkg = json.loads(src.read(pkg_name).decode("utf-8"))
        props = (pkg.get("contributes", {}).get("configuration", {}) or {})
        prop_dicts = []
        if isinstance(props, dict):
            prop_dicts = [props.get("properties", {})]
        elif isinstance(props, list):
            prop_dicts = [(c or {}).get("properties", {}) for c in props]
        changed = False
        for pd in prop_dicts:
            for key, val in values.items():
                if val and key in pd:
                    pd[key]["default"] = val
                    changed = True
        if not changed:
            return raw

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == pkg_name:
                    data = json.dumps(pkg, indent=2).encode("utf-8")
                dst.writestr(item, data)
        return out.getvalue()
    except Exception as e:
        logger.warning("vscode.vsix_prefill_failed (serving original): %s", e)
        with open(path, "rb") as f:
            return f.read()
