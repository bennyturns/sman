"""Tool definitions for the Claude agent."""

from __future__ import annotations

# Claude tool-use schema definitions
TOOL_DEFINITIONS = [
    {
        "name": "run_command",
        "description": "Execute a shell command on the system. Use this for any command not covered by a specific tool. Read-only commands run automatically; write commands require user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 60)",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "systemctl",
        "description": "Manage systemd services. Can start, stop, restart, enable, disable, reload, or check status of services. Can also list units or show service properties.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "status", "start", "stop", "restart", "reload",
                        "enable", "disable", "is-active", "is-enabled",
                        "list-units", "list-failed", "daemon-reload", "show", "logs",
                    ],
                    "description": "The systemctl action to perform",
                },
                "unit": {
                    "type": "string",
                    "description": "Service unit name (e.g., nginx.service). Not needed for list-units, list-failed, or daemon-reload.",
                },
                "now": {
                    "type": "boolean",
                    "description": "For enable/disable: also start/stop the service immediately",
                    "default": False,
                },
                "lines": {
                    "type": "integer",
                    "description": "For logs: number of log lines to show",
                    "default": 50,
                },
                "since": {
                    "type": "string",
                    "description": "For logs: show entries since this time (e.g., '1h ago', '2024-01-01')",
                },
                "state": {
                    "type": "string",
                    "description": "For list-units: filter by state (e.g., 'running', 'failed')",
                },
                "properties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For show: specific properties to display",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "dnf",
        "description": "Manage packages using dnf. Can install, remove, update, search, or get info about packages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["install", "remove", "update", "search", "info", "list-installed", "check-update", "history", "history-undo"],
                    "description": "The dnf action to perform",
                },
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Package name(s) to operate on",
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For update: packages to exclude",
                },
                "query": {
                    "type": "string",
                    "description": "For search: the search query",
                },
                "pattern": {
                    "type": "string",
                    "description": "For list-installed: filter pattern",
                },
                "transaction_id": {
                    "type": "integer",
                    "description": "For history-undo: the transaction ID to undo",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "firewall",
        "description": "Manage firewalld firewall rules. Can add/remove ports, services, and rich rules.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list-all", "list-ports", "list-services",
                        "add-port", "remove-port", "add-service", "remove-service",
                        "add-rich-rule", "remove-rich-rule",
                        "reload", "get-zones", "get-default-zone",
                    ],
                    "description": "The firewall action to perform",
                },
                "port": {
                    "type": "string",
                    "description": "Port number (e.g., '80', '8080-8090')",
                },
                "protocol": {
                    "type": "string",
                    "enum": ["tcp", "udp"],
                    "default": "tcp",
                },
                "service": {
                    "type": "string",
                    "description": "Service name (e.g., 'http', 'https', 'ssh')",
                },
                "rule": {
                    "type": "string",
                    "description": "Rich rule string for add/remove-rich-rule",
                },
                "permanent": {
                    "type": "boolean",
                    "default": True,
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "network",
        "description": "Manage network configuration. View connections, devices, set static/DHCP, check ports, DNS lookups.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "connections", "connection-details", "devices",
                        "set-static-ip", "set-dhcp",
                        "ip-addresses", "routes", "listening-ports", "all-connections",
                        "dns-lookup", "ping",
                    ],
                    "description": "The network action to perform",
                },
                "connection": {
                    "type": "string",
                    "description": "Connection/interface name for configuration",
                },
                "ip": {
                    "type": "string",
                    "description": "For set-static-ip: IP address with CIDR (e.g., '192.168.1.100/24')",
                },
                "gateway": {
                    "type": "string",
                    "description": "For set-static-ip: gateway address",
                },
                "dns": {
                    "type": "string",
                    "description": "For set-static-ip: DNS servers (comma-separated)",
                    "default": "8.8.8.8,8.8.4.4",
                },
                "host": {
                    "type": "string",
                    "description": "For dns-lookup or ping: hostname or IP",
                },
                "count": {
                    "type": "integer",
                    "description": "For ping: number of packets",
                    "default": 4,
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file. Safe operation, no approval needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute file path to read",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Automatically creates a backup of the existing file before writing. Requires user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute file path to write",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for text patterns in files or find files by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["grep", "find", "list", "disk-usage", "dir-size"],
                },
                "pattern": {
                    "type": "string",
                    "description": "For grep: text pattern. For find: filename pattern.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file path to search in",
                    "default": "/etc",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "users",
        "description": "Manage system users and groups.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "info", "create", "delete", "lock", "unlock",
                        "add-to-group", "set-ssh-key", "list-groups",
                        "who-logged-in", "last-logins",
                    ],
                },
                "username": {
                    "type": "string",
                    "description": "Username to operate on",
                },
                "groups": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For create: groups to add user to",
                },
                "shell": {
                    "type": "string",
                    "description": "For create: login shell",
                    "default": "/bin/bash",
                },
                "group": {
                    "type": "string",
                    "description": "For add-to-group: group name",
                },
                "ssh_key": {
                    "type": "string",
                    "description": "For set-ssh-key: public key content",
                },
                "remove_home": {
                    "type": "boolean",
                    "description": "For delete: also remove home directory",
                    "default": False,
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "diagnostics",
        "description": "System health checks and diagnostics. Check CPU, memory, disk, processes, SMART health, logs, SELinux, and more.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "overview", "top-processes", "memory", "cpu", "disk-space",
                        "disk-inodes", "smart-health", "smart-all", "journal-errors",
                        "failed-services", "selinux-denials", "network-connections",
                        "sensors", "swap", "auth-failures", "cert-check", "load",
                    ],
                },
                "device": {
                    "type": "string",
                    "description": "For smart-health: device path (e.g., /dev/sda)",
                },
                "since": {
                    "type": "string",
                    "description": "For journal-errors/selinux: time range (e.g., '1h ago')",
                    "default": "1h ago",
                },
                "priority": {
                    "type": "string",
                    "description": "For journal-errors: minimum priority (e.g., 'err', 'warning')",
                    "default": "err",
                },
                "count": {
                    "type": "integer",
                    "description": "For top-processes/auth-failures: number of entries",
                    "default": 10,
                },
                "path": {
                    "type": "string",
                    "description": "For cert-check: path to certificate file",
                },
            },
            "required": ["action"],
        },
    },
]
