"""Configuration management for sman."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG_PATHS = [
    Path("/etc/sman/sman.toml"),
    Path.home() / ".config" / "sman" / "sman.toml",
]


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    base_url: str | None = None

    # Local model (vLLM) settings
    local_provider: str | None = None
    local_model: str | None = None
    local_base_url: str = "http://localhost:8000/v1"

    # Routing
    auto_route: bool = True  # intelligent routing between local/cloud


@dataclass
class SafetyConfig:
    auto_approve_safe: bool = True
    require_approval: bool = True
    blocked_patterns: list[str] = field(default_factory=lambda: [
        "rm -rf /",
        "mkfs",
        "dd if=",
        "> /dev/sd",
        "chmod -R 777 /",
        ":(){ :|:& };:",
    ])


@dataclass
class MonitorConfig:
    enabled: bool = True
    watched_services: list[str] = field(default_factory=lambda: ["sshd"])
    disk_warn_percent: int = 80
    disk_critical_percent: int = 90
    disk_check_interval: int = 900  # seconds
    smart_check_interval: int = 21600  # 6 hours
    service_check_interval: int = 300  # 5 minutes
    ssh_brute_force_threshold: int = 10
    ssh_brute_force_window: int = 300  # 5 minutes


@dataclass
class AlertConfig:
    ntfy_enabled: bool = False
    ntfy_topic: str = "sman-alerts"
    ntfy_server: str = "https://ntfy.sh"
    email_enabled: bool = False
    email_to: str = ""
    smtp_server: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    cooldown_seconds: int = 300  # don't re-alert same condition within window


@dataclass
class DaemonConfig:
    socket_path: str = "/run/sman/sman.sock"
    host: str = "127.0.0.1"
    port: int = 9876
    enable_web: bool = True


@dataclass
class SmanConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    data_dir: Path = field(default_factory=lambda: Path.home() / ".local" / "share" / "sman")


def load_config(path: Path | None = None) -> SmanConfig:
    """Load configuration from TOML file, falling back to defaults."""
    config = SmanConfig()

    config_path = path
    if config_path is None:
        for p in reversed(DEFAULT_CONFIG_PATHS):
            if p.exists():
                config_path = p
                break

    if config_path and config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        _apply_toml(config, data)

    # API key from env takes precedence
    env_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if env_key:
        config.llm.api_key = env_key

    # Ensure data dir exists
    config.data_dir.mkdir(parents=True, exist_ok=True)

    return config


def _apply_toml(config: SmanConfig, data: dict) -> None:
    """Apply TOML data to config dataclass."""
    if "llm" in data:
        for k, v in data["llm"].items():
            if hasattr(config.llm, k):
                setattr(config.llm, k, v)
        # Resolve API key from env var reference
        if "api_key_env" in data["llm"]:
            config.llm.api_key = os.environ.get(data["llm"]["api_key_env"], "")

    if "safety" in data:
        for k, v in data["safety"].items():
            if hasattr(config.safety, k):
                setattr(config.safety, k, v)

    if "monitors" in data:
        for k, v in data["monitors"].items():
            if hasattr(config.monitor, k):
                setattr(config.monitor, k, v)

    if "alerts" in data:
        for k, v in data["alerts"].items():
            if hasattr(config.alerts, k):
                setattr(config.alerts, k, v)

    if "daemon" in data:
        for k, v in data["daemon"].items():
            if hasattr(config.daemon, k):
                setattr(config.daemon, k, v)

    if "data_dir" in data:
        config.data_dir = Path(data["data_dir"])
