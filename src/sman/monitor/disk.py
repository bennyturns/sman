"""Disk space and SMART health monitoring."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from sman.config import SmanConfig
from sman.alerts.dispatcher import Alert, AlertDispatcher, Severity

log = logging.getLogger(__name__)


class DiskMonitor:
    """Monitors disk space and SMART health."""

    def __init__(self, config: SmanConfig, dispatcher: AlertDispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self.warn_pct = config.monitor.disk_warn_percent
        self.critical_pct = config.monitor.disk_critical_percent

    async def check_space(self) -> list[dict]:
        """Check disk space on all mounted filesystems."""
        proc = await asyncio.create_subprocess_exec(
            "df", "-h", "--output=source,fstype,size,used,avail,pcent,target",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().strip().split("\n")

        results = []
        for line in lines[1:]:  # skip header
            parts = line.split()
            if len(parts) < 7:
                continue
            # Skip pseudo filesystems
            if parts[1] in ("tmpfs", "devtmpfs", "efivarfs", "overlay"):
                continue
            if parts[0].startswith("/dev/") or parts[0].startswith("/dev/mapper/"):
                pct = int(parts[5].rstrip("%"))
                entry = {
                    "device": parts[0],
                    "fstype": parts[1],
                    "size": parts[2],
                    "used": parts[3],
                    "avail": parts[4],
                    "use_percent": pct,
                    "mount": parts[6],
                }
                results.append(entry)

                # Alert on thresholds
                if pct >= 95:
                    await self.dispatcher.dispatch(Alert(
                        title=f"Disk EMERGENCY: {parts[6]} at {pct}%",
                        message=f"{parts[0]} mounted at {parts[6]} is {pct}% full ({parts[3]} used of {parts[2]}, {parts[4]} remaining)",
                        severity=Severity.EMERGENCY,
                        source="disk_monitor",
                        details=entry,
                        recommendation=f"Immediately free space: check large files with 'du -sh {parts[6]}/* | sort -rh | head -20' and clean old logs/caches",
                    ))
                elif pct >= self.critical_pct:
                    await self.dispatcher.dispatch(Alert(
                        title=f"Disk CRITICAL: {parts[6]} at {pct}%",
                        message=f"{parts[0]} mounted at {parts[6]} is {pct}% full ({parts[4]} remaining)",
                        severity=Severity.CRITICAL,
                        source="disk_monitor",
                        details=entry,
                        recommendation=f"Free disk space soon. Check large files: du -sh {parts[6]}/* | sort -rh | head -20",
                    ))
                elif pct >= self.warn_pct:
                    await self.dispatcher.dispatch(Alert(
                        title=f"Disk WARNING: {parts[6]} at {pct}%",
                        message=f"{parts[0]} mounted at {parts[6]} is {pct}% full ({parts[4]} remaining)",
                        severity=Severity.WARNING,
                        source="disk_monitor",
                        details=entry,
                    ))

        return results

    async def check_smart(self) -> list[dict]:
        """Check SMART health on all drives."""
        # Get list of drives
        proc = await asyncio.create_subprocess_exec(
            "lsblk", "-dno", "NAME,TYPE",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        results = []
        for line in stdout.decode().strip().split("\n"):
            parts = line.split()
            if len(parts) < 2:
                continue
            name, dtype = parts[0], parts[1]
            if dtype != "disk":
                continue

            device = f"/dev/{name}"
            smart_data = await self._check_drive(device)
            if smart_data:
                results.append(smart_data)

        return results

    async def _check_drive(self, device: str) -> dict | None:
        """Check SMART data for a single drive."""
        proc = await asyncio.create_subprocess_exec(
            "smartctl", "-a", "--json", device,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        try:
            data = json.loads(stdout.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

        result = {
            "device": device,
            "model": data.get("model_name", "Unknown"),
            "serial": data.get("serial_number", "Unknown"),
            "health": "UNKNOWN",
            "temperature": None,
            "issues": [],
        }

        # Overall health
        health = data.get("smart_status", {})
        if health.get("passed") is True:
            result["health"] = "PASSED"
        elif health.get("passed") is False:
            result["health"] = "FAILED"
            await self.dispatcher.dispatch(Alert(
                title=f"SMART FAILURE: {device}",
                message=f"Drive {device} ({result['model']}, S/N: {result['serial']}) has FAILED SMART health check. Drive failure may be imminent.",
                severity=Severity.EMERGENCY,
                source="disk_monitor",
                details=result,
                recommendation=f"IMMEDIATELY back up all data from {device}. Plan drive replacement.",
            ))

        # Check specific attributes
        attrs = data.get("ata_smart_attributes", {}).get("table", [])
        for attr in attrs:
            attr_name = attr.get("name", "")
            raw_value = attr.get("raw", {}).get("value", 0)

            # Reallocated sectors
            if attr_name == "Reallocated_Sector_Ct" and raw_value > 0:
                issue = f"Reallocated sectors: {raw_value}"
                result["issues"].append(issue)
                await self.dispatcher.dispatch(Alert(
                    title=f"Disk degradation: {device}",
                    message=f"{device} ({result['model']}) has {raw_value} reallocated sectors. Drive may be failing.",
                    severity=Severity.WARNING if raw_value < 10 else Severity.CRITICAL,
                    source="disk_monitor",
                    details={"device": device, "attribute": attr_name, "value": raw_value},
                    recommendation="Monitor closely. Plan backup and drive replacement if count increases.",
                ))

            # Pending sectors
            if attr_name == "Current_Pending_Sector" and raw_value > 0:
                issue = f"Pending sectors: {raw_value}"
                result["issues"].append(issue)
                await self.dispatcher.dispatch(Alert(
                    title=f"Disk pending sectors: {device}",
                    message=f"{device} has {raw_value} pending sectors awaiting reallocation.",
                    severity=Severity.WARNING,
                    source="disk_monitor",
                    details={"device": device, "attribute": attr_name, "value": raw_value},
                ))

            # Temperature
            if attr_name == "Temperature_Celsius":
                result["temperature"] = raw_value
                if raw_value > 55:
                    await self.dispatcher.dispatch(Alert(
                        title=f"Disk temperature high: {device}",
                        message=f"{device} temperature is {raw_value}C (threshold: 55C)",
                        severity=Severity.WARNING if raw_value < 65 else Severity.CRITICAL,
                        source="disk_monitor",
                        details={"device": device, "temperature": raw_value},
                        recommendation="Check airflow and cooling. Sustained high temps reduce drive lifespan.",
                    ))

        # NVMe health
        nvme_health = data.get("nvme_smart_health_information_log", {})
        if nvme_health:
            pct_used = nvme_health.get("percentage_used", 0)
            result["temperature"] = nvme_health.get("temperature", None)

            if pct_used > 90:
                await self.dispatcher.dispatch(Alert(
                    title=f"NVMe endurance warning: {device}",
                    message=f"{device} ({result['model']}) has used {pct_used}% of its rated endurance.",
                    severity=Severity.WARNING if pct_used < 100 else Severity.CRITICAL,
                    source="disk_monitor",
                    recommendation="Plan drive replacement. NVMe endurance is nearly exhausted.",
                ))

        return result
