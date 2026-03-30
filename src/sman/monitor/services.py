"""Service health monitoring."""

from __future__ import annotations

import asyncio
import logging
import re

from sman.config import SmanConfig
from sman.alerts.dispatcher import Alert, AlertDispatcher, Severity

log = logging.getLogger(__name__)


class ServiceMonitor:
    """Monitors systemd service health."""

    def __init__(self, config: SmanConfig, dispatcher: AlertDispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self._previous_states: dict[str, str] = {}

    async def check(self) -> list[dict]:
        """Check health of all watched services."""
        results = []

        for unit in self.config.monitor.watched_services:
            service = unit if unit.endswith(".service") else f"{unit}.service"
            state = await self._get_state(service)
            results.append(state)

            prev = self._previous_states.get(service)

            # Detect state transitions
            if prev and prev != state["active_state"]:
                if state["active_state"] == "failed":
                    # Get recent logs for context
                    logs = await self._get_logs(service, lines=10)
                    await self.dispatcher.dispatch(Alert(
                        title=f"Service failed: {unit}",
                        message=f"{service} has entered failed state.\nExit code: {state.get('exit_code', 'unknown')}\n\nRecent logs:\n{logs}",
                        severity=Severity.CRITICAL,
                        source="service_monitor",
                        details=state,
                        recommendation=f"Check logs: journalctl -u {service} -n 50 --no-pager\nRestart: systemctl restart {service}",
                    ))
                elif state["active_state"] == "inactive" and prev == "active":
                    await self.dispatcher.dispatch(Alert(
                        title=f"Service stopped: {unit}",
                        message=f"{service} has stopped (was previously active).",
                        severity=Severity.WARNING,
                        source="service_monitor",
                        details=state,
                    ))

            self._previous_states[service] = state["active_state"]

        # Also check for any failed units system-wide
        await self._check_failed_units()

        return results

    async def _get_state(self, service: str) -> dict:
        """Get current state of a service."""
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "show", service, "--no-pager",
            "--property=ActiveState,SubState,ExecMainStatus,MainPID,MemoryCurrent,CPUUsageNSec,NRestarts,ActiveEnterTimestamp",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        state = {"unit": service}
        for line in stdout.decode().strip().split("\n"):
            if "=" in line:
                key, val = line.split("=", 1)
                state[key] = val

        # Normalize
        state["active_state"] = state.get("ActiveState", "unknown")
        state["sub_state"] = state.get("SubState", "unknown")
        state["exit_code"] = state.get("ExecMainStatus", "")
        state["pid"] = state.get("MainPID", "0")

        # Memory in human-readable
        mem = state.get("MemoryCurrent", "")
        if mem and mem != "[not set]" and mem.isdigit():
            mem_mb = int(mem) / (1024 * 1024)
            state["memory_mb"] = f"{mem_mb:.1f}"

        # Restart count
        restarts = state.get("NRestarts", "0")
        state["restarts"] = int(restarts) if restarts.isdigit() else 0

        # Check for crash loop (many restarts)
        if state["restarts"] > 3:
            logs = await self._get_logs(service, lines=10)
            await self.dispatcher.dispatch(Alert(
                title=f"Service crash loop: {service}",
                message=f"{service} has restarted {state['restarts']} times.\n\nRecent logs:\n{logs}",
                severity=Severity.CRITICAL,
                source="service_monitor",
                details=state,
                recommendation=f"Investigate root cause: journalctl -u {service} -n 100 --no-pager",
            ))

        return state

    async def _get_logs(self, service: str, lines: int = 10) -> str:
        """Get recent journal logs for a service."""
        proc = await asyncio.create_subprocess_exec(
            "journalctl", "-u", service, "-n", str(lines), "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace").strip()

    async def _check_failed_units(self) -> None:
        """Check for any failed units system-wide."""
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "list-units", "--failed", "--no-pager", "--plain", "--no-legend",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode().strip()

        if output:
            for line in output.split("\n"):
                parts = line.split()
                if parts:
                    unit = parts[0]
                    if unit not in self._previous_states or self._previous_states.get(unit) != "failed":
                        await self.dispatcher.dispatch(Alert(
                            title=f"Failed unit detected: {unit}",
                            message=f"System unit {unit} is in failed state.",
                            severity=Severity.WARNING,
                            source="service_monitor",
                            recommendation=f"Check status: systemctl status {unit}\nView logs: journalctl -u {unit} -n 50",
                        ))
                        self._previous_states[unit] = "failed"
