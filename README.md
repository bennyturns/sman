# sman

**AI-powered sysadmin agent for Fedora/RHEL systems.**

sman (short for "shadow man") is your AI sysadmin partner. It lets you manage, configure, troubleshoot, and monitor Linux services using natural language — from the terminal, a web UI, or as a background daemon watching your system for problems.

## Features

- **Natural language sysadmin** — `sman ask "configure nginx as a reverse proxy for port 3000"`
- **Interactive chat** — `sman chat` for multi-turn conversations with context
- **Service management** — Install, configure, and operate any RHEL/Fedora service
- **Safe execution** — Commands classified by risk, write operations require approval, config files backed up automatically
- **System diagnostics** — `sman status` for a quick health overview
- **Intelligent routing** — Automatically routes simple requests to a local model and complex ones to Claude
- **Audit trail** — Every command logged for review and rollback
- **Daemon mode** — `smand` runs as a systemd service with REST + WebSocket API

### Planned

- Proactive monitoring — Watch logs, detect SSH brute force, failing disks, service crashes
- Alerting — Push notifications via ntfy, email
- Web UI — Browser-based dashboard with chat + terminal
- Local model support — Run with vLLM for offline/air-gapped use

## Quick Start

### Prerequisites

- Fedora or RHEL system
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Anthropic API key

### Install

```bash
git clone https://github.com/bennyturns/sman.git
cd sman
uv sync
```

### Configure

```bash
# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Or create a config file
mkdir -p ~/.config/sman
cp config/sman.toml.example ~/.config/sman/sman.toml
# Edit with your API key
```

### Use

```bash
# One-shot request
uv run sman ask "what services are running?"

# Interactive chat
uv run sman chat

# System status
uv run sman status

# Force local or cloud model
uv run sman ask --local "restart nginx"
uv run sman ask --cloud "configure postfix as a gmail relay"
```

### Daemon

```bash
# Run the daemon
uv run smand

# Or install as a systemd service
sudo cp systemd/smand.service /etc/systemd/system/
sudo systemctl enable --now smand
```

## Architecture

```
                    +------------------+
                    |   Claude API     |
                    |   (or vLLM)      |
                    +--------+---------+
                             |
+--------+    HTTP/WS   +----+----------+    subprocess
| Web UI | <----------> |    smand      | <------------> system commands
+--------+              | (FastAPI)     |
                        |               |
+--------+   HTTP       | - Agent       |
| sman   | <----------> | - Tool Runner |
| (CLI)  |              | - Router      |
+--------+              +---------------+
```

### Tool Modules

| Module | Capabilities |
|--------|-------------|
| `systemctl` | Start, stop, restart, enable, disable, status, logs |
| `dnf` | Install, remove, update, search, history, rollback |
| `firewall` | Ports, services, rich rules, zones |
| `network` | nmcli, static/DHCP, DNS, ping, listening ports |
| `files` | Read, write (with backup), search, find |
| `users` | Create, delete, lock, groups, SSH keys, logins |
| `diagnostics` | CPU, memory, disk, SMART, SELinux, sensors, certs |
| `run_command` | Arbitrary shell commands with safety classification |

### Safety Model

Commands are classified into three risk levels:

- **Safe** (auto-execute): Read-only operations — `systemctl status`, `df`, `journalctl`, etc.
- **Needs Approval** (prompt user): Write operations — service restarts, config changes, package installs
- **Dangerous** (blocked): Destructive operations — `rm -rf /`, `mkfs`, `dd`

Config files are automatically backed up before modification. All commands are logged to `~/.local/share/sman/audit.log`.

## Configuration

See [`config/sman.toml.example`](config/sman.toml.example) for all options.

Key settings:

```toml
[llm]
provider = "anthropic"
model = "claude-sonnet-4-20250514"

# Optional: local model for simple requests
# local_provider = "vllm"
# local_model = "meta-llama/Llama-3.1-8B-Instruct"
# local_base_url = "http://localhost:8000/v1"
# auto_route = true

[safety]
auto_approve_safe = true
require_approval = true

[monitors]
watched_services = ["sshd", "nginx", "postgresql"]
```

## License

MIT
