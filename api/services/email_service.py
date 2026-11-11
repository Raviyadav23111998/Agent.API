"""
Email Service — system-level transactional email (OTP, notifications).
═══════════════════════════════════════════════════════════════════════

Thin SMTP sender for SYSTEM mail (password-reset OTPs), distinct from the
per-user `send_email_smtp` agent tool: this one resolves credentials from
system configuration, never from a user's vault.

SMTP is configured in ONE place: the credential vault (provider "smtp",
a system credential set under Connections → Org Credentials). It is NOT a
System Configuration setting.

Resolution order:
  1. CredentialRegistry — system "smtp" credential (the configuration home)
  2. smtp.* env/config — legacy/bootstrap escape hatch only (not surfaced in
     the UI); lets ops seed SMTP via environment before the vault is set.

Degrades gracefully: when nothing is configured, `available` is False and
callers return a clear "not configured" message instead of crashing.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("agent.email")


class EmailService:
    """System SMTP sender — credentials resolved (lazily) from the vault."""

    def __init__(self, credential_registry=None):
        self._registry = credential_registry

    def _config(self) -> dict:
        from core.config import app_config

        if self._registry is not None:
            try:
                cred = self._registry.resolve("smtp", user_id=None, app_id=None)
                vault = dict(cred.config)
                if vault.get("server") and vault.get("username") and cred.secret:
                    return {
                        "server": vault.get("server"),
                        "port": int(vault.get("port", 587)),
                        "username": vault.get("username"),
                        "password": cred.secret,
                        "use_tls": vault.get("use_tls", True),
                        "from": vault.get("from") or vault.get("username"),
                    }
            except Exception as e:
                logger.debug("email_service.vault_lookup_failed: %s", e)

        return {
            "server": app_config.get("smtp.server"),
            "port": app_config.get_int("smtp.port", 587),
            "username": app_config.get("smtp.username"),
            "password": app_config.get("smtp.password"),
            "use_tls": app_config.get_bool("smtp.use_tls", True),
            "from": app_config.get("smtp.from"),
        }

    @property
    def available(self) -> bool:
        cfg = self._config()
        return bool(cfg.get("server") and cfg.get("username") and cfg.get("password"))

    def send(self, to: str, subject: str, body: str, is_html: bool = False) -> bool:
        """Send one email. Returns True on success, False otherwise."""
        cfg = self._config()
        if not (cfg.get("server") and cfg.get("username") and cfg.get("password")):
            logger.warning("email_service.not_configured (set smtp.* configs)")
            return False
        try:
            msg = MIMEMultipart()
            msg["From"] = cfg.get("from") or cfg["username"]
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html" if is_html else "plain"))

            with smtplib.SMTP(cfg["server"], cfg["port"], timeout=15) as conn:
                if cfg.get("use_tls", True):
                    conn.starttls()
                conn.login(cfg["username"], cfg["password"])
                conn.send_message(msg)

            try:
                from core.telemetry import telemetry
                telemetry.incr("emails_sent_total", kind="system")
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error("email_service.send_failed: to=%s err=%s", to, e)
            return False

    def send_otp(self, to: str, otp: str, ttl_minutes: int = 10) -> bool:
        """Send a password-reset OTP."""
        return self.send(
            to,
            "Your password reset code",
            (f"Your one-time password reset code is: {otp}\n\n"
             f"It expires in {ttl_minutes} minutes. If you did not request "
             f"this, ignore this email — your password has not changed."),
        )
