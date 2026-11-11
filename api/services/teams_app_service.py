"""
Per-tenant Microsoft Teams app package builder.
═══════════════════════════════════════════════════════════════════════════════
Generates a Teams app .zip (manifest.json + color.png + outline.png) configured
for ONE tenant:

  • Bot identity   = the tenant's OWN M365 app registration (client_id) — BYO bot,
                     no shared platform bot.
  • Branding       = tenant display name + tenant logo (derived into both icons).
  • Inbound routing= carried on the messaging-endpoint URL (?tenant=<domain>), the
                     SAME per-tenant pattern as the web chatbot widget and VS Code.
                     No global AAD registry, no cross-service writes.

The tenant points their Azure Bot's messaging endpoint at messaging_endpoint(domain),
uploads this zip to Teams, and the agent resolves their tenant from the URL.
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
import uuid
import zipfile
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

WEBHOOK_BASE = os.environ.get(
    "AG_TEAMS_WEBHOOK_BASE", "https://api.storeglance.com/api/agent/webhook/teams"
)
GATEWAY_API = os.environ.get("AG_PUBLIC_API_BASE", "https://api.storeglance.com")
DEFAULT_ACCENT = "#6D28D9"

_MANIFEST_NS = uuid.UUID("6d6f6e74-7465-616d-7300-000000000001")

_SCHEMA = "https://developer.microsoft.com/en-us/json-schemas/teams/v1.16/MicrosoftTeams.schema.json"

_VERSION_EPOCH = 1735689600


def _build_version() -> str:
    return f"1.0.{max(0, int(time.time()) - _VERSION_EPOCH)}"


def messaging_endpoint(tenant_domain: str) -> str:
    """The per-tenant Bot Framework messaging endpoint (tenant baked into the URL)."""
    return f"{WEBHOOK_BASE}?tenant={tenant_domain}"


def _clamp(s: str, n: int) -> str:
    return (s or "").strip()[:n]


def build_manifest(*, tenant_domain: str, display_name: str,
                   client_id: str, accent: str = DEFAULT_ACCENT) -> dict:
    """Build a per-tenant Teams manifest. botId/webApplicationInfo.id = the tenant's
    own M365 app client_id; validDomains include the tenant + API host."""
    name = (display_name or tenant_domain).strip()
    short = _clamp(name, 30)
    full = _clamp(f"{name} Assistant" if display_name else name, 100)
    app_id = str(uuid.uuid5(_MANIFEST_NS, f"{tenant_domain}|{client_id}"))
    safe_pkg = "".join(c for c in tenant_domain.lower() if c.isalnum() or c == ".").strip(".")
    return {
        "$schema": _SCHEMA,
        "manifestVersion": "1.16",
        "version": _build_version(),
        "id": app_id,
        "packageName": f"com.storeglance.agent.{safe_pkg or 'tenant'}",
        "developer": {
            "name": "Storeglance",
            "websiteUrl": "https://storeglanceai.com",
            "privacyUrl": "https://storeglanceai.com/privacy",
            "termsOfUseUrl": "https://storeglanceai.com/terms",
        },
        "name": {"short": short, "full": full},
        "description": {
            "short": _clamp(f"{short} AI assistant", 80),
            "full": _clamp(
                f"AI assistant for {full}. Chat, automate workflows, and query your "
                f"organisation's knowledge directly inside Microsoft Teams.", 4000),
        },
        "icons": {"outline": "outline.png", "color": "color.png"},
        "accentColor": accent if accent.startswith("#") else DEFAULT_ACCENT,
        "bots": [{
            "botId": client_id,
            "scopes": ["personal", "groupChat", "team"],
            "isNotificationOnly": False,
            "supportsCalling": False,
            "supportsVideo": False,
            "supportsFiles": True,
        }],
        "permissions": ["identity", "messageTeamMembers"],
        "validDomains": sorted({"api.storeglance.com", tenant_domain, "*.storeglanceai.com"}),
        "webApplicationInfo": {
            "id": client_id,
            "resource": f"api://{GATEWAY_API.split('://')[-1]}/{client_id}",
        },
    }


def _png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_icons(logo_bytes: Optional[bytes], display_name: str,
                accent: str = DEFAULT_ACCENT) -> Tuple[bytes, bytes]:
    """Derive Teams icons from the tenant logo (preferred) or a branded initial.
       color.png  = 192×192 full-colour app icon.
       outline.png= 32×32 transparent white silhouette (Teams requirement)."""
    from PIL import Image, ImageDraw, ImageFont

    initial = (display_name or "A").strip()[:1].upper() or "A"

    color = Image.new("RGBA", (192, 192), accent if accent.startswith("#") else DEFAULT_ACCENT)
    logo_img = None
    if logo_bytes:
        try:
            logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        except Exception as e:
            logger.info("teams_icons.logo_decode_failed: %s", e)
            logo_img = None

    if logo_img is not None:
        color = Image.new("RGBA", (192, 192), "#FFFFFF")
        logo_img.thumbnail((150, 150), Image.LANCZOS)
        color.alpha_composite(logo_img, ((192 - logo_img.width) // 2, (192 - logo_img.height) // 2))
    else:
        d = ImageDraw.Draw(color)
        try:
            font = ImageFont.load_default(size=110)
        except TypeError:
            font = ImageFont.load_default()
        d.text((96, 92), initial, fill="#FFFFFF", anchor="mm", font=font)

    outline = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    if logo_img is not None:
        small = logo_img.copy()
        small.thumbnail((30, 30), Image.LANCZOS)
        alpha = small.split()[-1]
        white = Image.new("RGBA", small.size, (255, 255, 255, 255))
        white.putalpha(alpha)
        outline.alpha_composite(white, ((32 - small.width) // 2, (32 - small.height) // 2))
    else:
        d2 = ImageDraw.Draw(outline)
        try:
            font2 = ImageFont.load_default(size=22)
        except TypeError:
            font2 = ImageFont.load_default()
        d2.text((16, 15), initial, fill=(255, 255, 255, 255), anchor="mm", font=font2)

    return _png_bytes(color), _png_bytes(outline)


def build_zip(*, tenant_domain: str, display_name: str, client_id: str,
              logo_bytes: Optional[bytes] = None, accent: str = DEFAULT_ACCENT) -> bytes:
    """Assemble the complete Teams app package (.zip) for one tenant."""
    manifest = build_manifest(
        tenant_domain=tenant_domain, display_name=display_name,
        client_id=client_id, accent=accent)
    color_png, outline_png = build_icons(logo_bytes, display_name, accent)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("color.png", color_png)
        z.writestr("outline.png", outline_png)
    return buf.getvalue()
