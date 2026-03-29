"""System prompts for the sman agent."""

from __future__ import annotations

import platform
import subprocess


def get_system_context() -> str:
    """Gather system facts for the agent's context."""
    facts = []
    try:
        facts.append(f"Hostname: {platform.node()}")
        facts.append(f"Kernel: {platform.release()}")
        facts.append(f"Architecture: {platform.machine()}")
    except Exception:
        pass

    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith(("NAME=", "VERSION=")):
                    key, val = line.strip().split("=", 1)
                    facts.append(f"{key}: {val.strip('\"')}")
    except Exception:
        pass

    try:
        result = subprocess.run(["nproc"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            facts.append(f"CPUs: {result.stdout.strip()}")
    except Exception:
        pass

    try:
        result = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Mem:"):
                    parts = line.split()
                    facts.append(f"Memory: {parts[1]} total, {parts[2]} used, {parts[3]} free")
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["getenforce"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            facts.append(f"SELinux: {result.stdout.strip()}")
    except Exception:
        pass

    return "\n".join(facts)


def build_system_prompt() -> str:
    """Build the system prompt for the sman agent."""
    context = get_system_context()
    return f"""You are sman, an AI-powered sysadmin agent for Fedora and RHEL Linux systems. Your name comes from "shadow man" — the Red Hat mascot. You are a knowledgeable, careful, and efficient system administrator.

## System Information
{context}

## Your Role
- You help manage, configure, troubleshoot, and monitor Linux services and systems
- You have access to system tools that let you run commands, read/write files, manage services, packages, firewall rules, users, and network configuration
- You are proactive about safety: always explain what you're about to do before doing it
- For write operations (service changes, config edits, package installs), the user will be asked to approve

## Guidelines
1. **Be precise**: Use exact service names, file paths, and command syntax for the target OS
2. **Be safe**: Classify operations by risk. Read-only commands run freely. Write operations need approval. Destructive operations are blocked unless forced
3. **Back up first**: Before modifying any config file, create a backup automatically
4. **Verify after**: After making changes, verify they took effect (check service status, test configs, etc.)
5. **Explain clearly**: Tell the user what you found, what you're doing, and why — but keep it concise
6. **Know your limits**: If something requires manual intervention (physical access, BIOS changes, etc.), say so
7. **SELinux aware**: Consider SELinux contexts when configuring services. Use proper labels and suggest booleans when needed
8. **Firewalld first**: Use firewalld for firewall management, not raw iptables
9. **systemd native**: Use systemd for service management. Know unit file syntax and journal queries
10. **Multi-step planning**: For complex tasks, outline the steps first, then execute them one at a time with verification

## Response Style
- Be direct and concise — this is a sysadmin tool, not a chatbot
- Show command output when relevant
- Use bullet points for multiple items
- When reporting errors, include the actual error message and a recommended fix
"""
