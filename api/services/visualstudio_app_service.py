"""
Channels → Visual Studio: serve the packaged extension (.vsix) for direct install.
═══════════════════════════════════════════════════════════════════════════════
The Visual Studio (full IDE) extension is a C#/VSIX built on Windows (MSBuild +
VS SDK). Tenants install it directly: download the .vsix here, then double-click
it (VSIX Installer) or Extensions → Manage Extensions.

Ops/CI drops the built artifact into AG_VS_VSIX_DIR; we serve the newest .vsix
found. Identical to the VS Code channel, the download is auto-resolved per tenant:
the .vsix bundles an `agent.tenant.json` (apiUrl + tenantDomain) and we rewrite it
at download time with THIS tenant's domain + env gateway, so the install is
pre-pointed — no manual setup. The WebView2 host reads that file and sends
X-Tenant-Domain on every call (so /Login resolves the right tenant DB).
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

VSIX_DIR = os.environ.get("AG_VS_VSIX_DIR", "")

MARKETPLACE_URL = os.environ.get(
    "AG_VS_MARKETPLACE_URL",
    "",  # set when the extension is listed on the Marketplace
)

_CANDIDATE_DIRS = [
    VSIX_DIR,
    "/var/lib/storeglance-agent/vsix/visualstudio",
    str(Path(__file__).resolve().parents[3] / "agent.vs-extension"),
]

_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?(?:[-.][A-Za-z0-9]+)?)")


def find_latest_vsix() -> Tuple[Optional[str], Optional[str]]:
    """Return (absolute_path, filename) of the newest .vsix, or (None, None)."""
    for d in _CANDIDATE_DIRS:
        if not d:
            continue
        files = glob.glob(os.path.join(d, "**", "*.vsix"), recursive=True)
        if files:
            newest = max(files, key=os.path.getmtime)
            return newest, os.path.basename(newest)
    return None, None


def parse_version(filename: Optional[str]) -> str:
    """Best-effort version pulled from the .vsix filename."""
    if not filename:
        return ""
    stem = filename[:-5] if filename.lower().endswith(".vsix") else filename
    m = _VERSION_RE.search(stem)
    return m.group(1) if m else ""


def build_tenant_vsix(path: str, *, tenant_domain: str = "", api_url: str = "") -> bytes:
    """Return the .vsix bytes with the bundled `agent.tenant.json` rewritten for
    this tenant. A .vsix is a zip; we replace only that one entry's content and
    copy every other entry verbatim (so the OPC package + [Content_Types].xml stay
    valid). On any error we fall back to the untouched original (a tenant-agnostic
    install still works; the C# host then uses its PROD default + empty tenant).

    Mirrors vscode_app_service.build_tenant_vsix (which patches package.json)."""
    values = {"apiUrl": (api_url or "").strip(),
              "tenantDomain": (tenant_domain or "").strip().lower()}
    try:
        with open(path, "rb") as f:
            raw = f.read()
        src = zipfile.ZipFile(io.BytesIO(raw))

        cfg_name = next(
            (n for n in src.namelist() if n.split("/")[-1] == "agent.tenant.json"),
            None)
        if not cfg_name:
            logger.warning("vs.vsix: agent.tenant.json not found — serving original")
            return raw

        try:
            cfg = json.loads(src.read(cfg_name).decode("utf-8"))
        except Exception:
            cfg = {}
        changed = False
        for key, val in values.items():
            if val:
                cfg[key] = val
                changed = True
        if not changed:
            return raw

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == cfg_name:
                    data = json.dumps(cfg, indent=2).encode("utf-8")
                dst.writestr(item, data)
        return out.getvalue()
    except Exception as e:
        logger.warning("vs.vsix_tenant_bake_failed (serving original): %s", e)
        with open(path, "rb") as f:
            return f.read()
