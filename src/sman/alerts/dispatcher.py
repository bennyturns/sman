"""Alert dispatching — routes alerts to configured channels."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Awaitable

from sman.config import SmanConfig

log = logging.getLogger(__name__)


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class Alert:
    title: str
    message: str
    severity: Severity
    source: str  # e.g., "ssh_monitor", "disk_monitor"
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)
    details: dict = field(default_factory=dict)
    recommendation: str = ""

    @property
    def key(self) -> str:
        """Deduplication key — same source+title = same condition."""
        return f"{self.source}:{self.title}"


class AlertDispatcher:
    """Routes alerts to configured channels with deduplication."""

    def __init__(self, config: SmanConfig):
        self.config = config
        self.alert_log = config.data_dir / "alerts.log"
        self._cooldowns: dict[str, datetime.datetime] = {}
        self._handlers: list[Callable[[Alert], Awaitable[None]]] = []
        self.cooldown_seconds = config.alerts.cooldown_seconds

        # Register enabled handlers
        if config.alerts.ntfy_enabled:
            self._handlers.append(self._send_ntfy)
        if config.alerts.email_enabled:
            self._handlers.append(self._send_email)

        # Always log to file
        self._handlers.append(self._log_alert)

    async def dispatch(self, alert: Alert) -> bool:
        """Dispatch an alert if not in cooldown. Returns True if sent."""
        # Check cooldown
        last_sent = self._cooldowns.get(alert.key)
        if last_sent:
            elapsed = (datetime.datetime.now() - last_sent).total_seconds()
            if elapsed < self.cooldown_seconds:
                log.debug(f"Alert '{alert.key}' in cooldown ({elapsed:.0f}s < {self.cooldown_seconds}s)")
                return False

        # Update cooldown
        self._cooldowns[alert.key] = datetime.datetime.now()

        # Dispatch to all handlers
        for handler in self._handlers:
            try:
                await handler(alert)
            except Exception as e:
                log.error(f"Alert handler {handler.__name__} failed: {e}")

        return True

    async def _log_alert(self, alert: Alert) -> None:
        """Log alert to file."""
        self.alert_log.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": alert.timestamp.isoformat(),
            "severity": alert.severity.value,
            "source": alert.source,
            "title": alert.title,
            "message": alert.message,
            "recommendation": alert.recommendation,
            "details": alert.details,
        }
        with open(self.alert_log, "a") as f:
            f.write(json.dumps(entry) + "\n")
        log.warning(f"ALERT [{alert.severity.value.upper()}] {alert.title}: {alert.message}")

    async def _send_ntfy(self, alert: Alert) -> None:
        """Send alert via ntfy.sh."""
        import httpx

        severity_priority = {
            Severity.INFO: "low",
            Severity.WARNING: "default",
            Severity.CRITICAL: "high",
            Severity.EMERGENCY: "urgent",
        }
        severity_tags = {
            Severity.INFO: "information_source",
            Severity.WARNING: "warning",
            Severity.CRITICAL: "rotating_light",
            Severity.EMERGENCY: "skull",
        }

        url = f"{self.config.alerts.ntfy_server}/{self.config.alerts.ntfy_topic}"
        body = alert.message
        if alert.recommendation:
            body += f"\n\nRecommended: {alert.recommendation}"

        headers = {
            "Title": f"sman: {alert.title}",
            "Priority": severity_priority.get(alert.severity, "default"),
            "Tags": severity_tags.get(alert.severity, "bell"),
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, content=body, headers=headers)
            resp.raise_for_status()
            log.info(f"ntfy alert sent: {alert.title}")

    async def _send_email(self, alert: Alert) -> None:
        """Send alert via email."""
        import smtplib
        from email.mime.text import MIMEText

        cfg = self.config.alerts
        body = f"""
sman Alert: {alert.title}
Severity: {alert.severity.value.upper()}
Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
Source: {alert.source}

{alert.message}
"""
        if alert.recommendation:
            body += f"\nRecommended Action:\n{alert.recommendation}\n"

        if alert.details:
            body += f"\nDetails:\n{json.dumps(alert.details, indent=2)}\n"

        msg = MIMEText(body)
        msg["Subject"] = f"[sman {alert.severity.value.upper()}] {alert.title}"
        msg["From"] = cfg.smtp_user or "sman@localhost"
        msg["To"] = cfg.email_to

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_smtp, msg, cfg)

    def _send_smtp(self, msg, cfg) -> None:
        """Blocking SMTP send."""
        with smtplib.SMTP(cfg.smtp_server, cfg.smtp_port) as server:
            server.starttls()
            if cfg.smtp_user and cfg.smtp_password:
                server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)

    def get_recent_alerts(self, count: int = 20) -> list[dict]:
        """Read recent alerts from the log."""
        if not self.alert_log.exists():
            return []
        lines = self.alert_log.read_text().strip().split("\n")
        alerts = []
        for line in lines[-count:]:
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return alerts

    def clear_cooldown(self, key: str | None = None) -> None:
        """Clear cooldown for a specific alert or all alerts."""
        if key:
            self._cooldowns.pop(key, None)
        else:
            self._cooldowns.clear()
