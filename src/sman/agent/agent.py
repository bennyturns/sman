"""Core agent loop with Claude tool-use."""

from __future__ import annotations

import json
from typing import AsyncGenerator, Callable, Awaitable

import anthropic
import httpx

from sman.config import SmanConfig
from sman.agent.prompts import build_system_prompt
from sman.agent.tools import TOOL_DEFINITIONS
from sman.agent.router import get_route, RouteTarget
from sman.tools.runner import ToolRunner, CommandRisk, CommandResult
from sman.tools.systemctl import SystemctlTool
from sman.tools.packages import PackageTool
from sman.tools.firewall import FirewallTool
from sman.tools.network import NetworkTool
from sman.tools.files import FileTool
from sman.tools.users import UserTool
from sman.tools.diagnostics import DiagnosticTool


class SmanAgent:
    """The core sman agent that processes requests via Claude tool-use."""

    def __init__(
        self,
        config: SmanConfig,
        approval_callback: Callable[[str, CommandRisk], Awaitable[bool]] | None = None,
    ):
        self.config = config
        self.runner = ToolRunner(config, approval_callback=approval_callback)
        self.system_prompt = build_system_prompt()
        self.messages: list[dict] = []

        # Initialize tools
        self.systemctl = SystemctlTool(self.runner)
        self.packages = PackageTool(self.runner)
        self.firewall = FirewallTool(self.runner)
        self.network = NetworkTool(self.runner)
        self.files = FileTool(self.runner)
        self.users = UserTool(self.runner)
        self.diagnostics = DiagnosticTool(self.runner)

    def _get_client(self, target: RouteTarget) -> tuple[anthropic.AsyncAnthropic | httpx.AsyncClient, str, bool]:
        """Get the appropriate client and model for the target.

        Returns: (client, model_name, is_anthropic)
        """
        if target == RouteTarget.LOCAL and self.config.llm.local_provider:
            # vLLM/OpenAI-compatible endpoint
            client = httpx.AsyncClient(base_url=self.config.llm.local_base_url)
            return client, self.config.llm.local_model or "", False
        else:
            client = anthropic.AsyncAnthropic(api_key=self.config.llm.api_key)
            return client, self.config.llm.model, True

    async def ask(
        self,
        user_input: str,
        force_route: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Process a user request and yield response text chunks.

        This is the main entry point for the agent. It:
        1. Routes the request to the appropriate model
        2. Sends the request with tool definitions
        3. Executes tool calls as needed
        4. Yields text responses as they come
        """
        route = get_route(user_input, self.config.llm, force=force_route)

        self.messages.append({"role": "user", "content": user_input})

        # Process until we get a final text response (no more tool calls)
        while True:
            response_text, tool_calls = await self._call_llm(route)

            if response_text:
                yield response_text

            if not tool_calls:
                break

            # Execute tool calls and add results
            tool_results = []
            for tool_call in tool_calls:
                result = await self._execute_tool(tool_call)
                tool_results.append(result)

                # Yield tool execution info
                tool_name = tool_call.get("name", "unknown")
                cmd_result = result.get("_command_result")
                if cmd_result and isinstance(cmd_result, CommandResult):
                    if cmd_result.risk == CommandRisk.NEEDS_APPROVAL and cmd_result.approved:
                        yield f"\n[executed: {cmd_result.command}]\n"
                    elif not cmd_result.approved:
                        yield f"\n[denied: {cmd_result.command}]\n"

            # Add assistant response with tool use to messages
            assistant_content = []
            if response_text:
                assistant_content.append({"type": "text", "text": response_text})
            for tc in tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            self.messages.append({"role": "assistant", "content": assistant_content})

            # Add tool results to messages
            tool_result_content = []
            for tc, tr in zip(tool_calls, tool_results):
                output = tr.get("output", "")
                tool_result_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": output,
                })
            self.messages.append({"role": "user", "content": tool_result_content})

    async def ask_oneshot(
        self,
        user_input: str,
        force_route: str | None = None,
    ) -> str:
        """Process a request and return the full response as a string."""
        parts = []
        async for chunk in self.ask(user_input, force_route=force_route):
            parts.append(chunk)
        return "".join(parts)

    def reset(self) -> None:
        """Clear conversation history."""
        self.messages = []

    async def _call_llm(self, route: RouteTarget) -> tuple[str, list[dict]]:
        """Call the LLM and return (text_response, tool_calls)."""
        client, model, is_anthropic = self._get_client(route)

        try:
            if is_anthropic:
                return await self._call_anthropic(client, model)
            else:
                return await self._call_openai_compat(client, model)
        finally:
            if not is_anthropic:
                await client.aclose()

    async def _call_anthropic(
        self, client: anthropic.AsyncAnthropic, model: str
    ) -> tuple[str, list[dict]]:
        """Call the Anthropic API with tool-use."""
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=self.system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=self.messages,
        )

        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        return "\n".join(text_parts), tool_calls

    async def _call_openai_compat(
        self, client: httpx.AsyncClient, model: str
    ) -> tuple[str, list[dict]]:
        """Call an OpenAI-compatible API (vLLM) with tool-use."""
        # Convert Anthropic tool format to OpenAI format
        openai_tools = []
        for tool in TOOL_DEFINITIONS:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            })

        # Convert messages to OpenAI format
        openai_messages = [{"role": "system", "content": self.system_prompt}]
        for msg in self.messages:
            if isinstance(msg["content"], str):
                openai_messages.append(msg)
            elif isinstance(msg["content"], list):
                # Handle tool results and mixed content
                for item in msg["content"]:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            openai_messages.append({"role": msg["role"], "content": item["text"]})
                        elif item.get("type") == "tool_result":
                            openai_messages.append({
                                "role": "tool",
                                "tool_call_id": item["tool_use_id"],
                                "content": item["content"],
                            })

        response = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": openai_messages,
                "tools": openai_tools,
                "max_tokens": 4096,
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        text = message.get("content", "") or ""

        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                tool_calls.append({
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "input": json.loads(tc["function"]["arguments"]),
                })

        return text, tool_calls

    async def _execute_tool(self, tool_call: dict) -> dict:
        """Execute a tool call and return the result."""
        name = tool_call["name"]
        params = tool_call["input"]

        try:
            result = await self._dispatch_tool(name, params)
            output = result.output if isinstance(result, CommandResult) else str(result)
            return {"output": output, "_command_result": result if isinstance(result, CommandResult) else None}
        except Exception as e:
            return {"output": f"Error: {e}", "_command_result": None}

    async def _dispatch_tool(self, name: str, params: dict) -> CommandResult:
        """Dispatch a tool call to the appropriate handler."""
        if name == "run_command":
            return await self.runner.execute(
                params["command"],
                timeout=params.get("timeout", 60),
            )

        elif name == "systemctl":
            action = params["action"]
            unit = params.get("unit", "")
            if action == "status":
                return await self.systemctl.status(unit)
            elif action == "start":
                return await self.systemctl.start(unit)
            elif action == "stop":
                return await self.systemctl.stop(unit)
            elif action == "restart":
                return await self.systemctl.restart(unit)
            elif action == "reload":
                return await self.systemctl.reload(unit)
            elif action == "enable":
                return await self.systemctl.enable(unit, now=params.get("now", False))
            elif action == "disable":
                return await self.systemctl.disable(unit, now=params.get("now", False))
            elif action == "is-active":
                return await self.systemctl.is_active(unit)
            elif action == "is-enabled":
                return await self.systemctl.is_enabled(unit)
            elif action == "list-units":
                return await self.systemctl.list_units(state=params.get("state"))
            elif action == "list-failed":
                return await self.systemctl.list_failed()
            elif action == "daemon-reload":
                return await self.systemctl.daemon_reload()
            elif action == "show":
                return await self.systemctl.show(unit, properties=params.get("properties"))
            elif action == "logs":
                return await self.systemctl.logs(unit, lines=params.get("lines", 50), since=params.get("since"))
            else:
                return CommandResult(command=f"systemctl {action}", exit_code=1, stdout="", stderr=f"Unknown action: {action}")

        elif name == "dnf":
            action = params["action"]
            if action == "install":
                return await self.packages.install(params.get("packages", []))
            elif action == "remove":
                return await self.packages.remove(params.get("packages", []))
            elif action == "update":
                return await self.packages.update(params.get("packages"), exclude=params.get("exclude"))
            elif action == "search":
                return await self.packages.search(params.get("query", ""))
            elif action == "info":
                pkgs = params.get("packages", [])
                return await self.packages.info(pkgs[0] if pkgs else "")
            elif action == "list-installed":
                return await self.packages.list_installed(params.get("pattern"))
            elif action == "check-update":
                return await self.packages.check_update()
            elif action == "history":
                return await self.packages.history()
            elif action == "history-undo":
                return await self.packages.history_undo(params.get("transaction_id", 0))
            else:
                return CommandResult(command=f"dnf {action}", exit_code=1, stdout="", stderr=f"Unknown action: {action}")

        elif name == "firewall":
            action = params["action"]
            permanent = params.get("permanent", True)
            if action == "list-all":
                return await self.firewall.list_all()
            elif action == "list-ports":
                return await self.firewall.list_ports()
            elif action == "list-services":
                return await self.firewall.list_services()
            elif action == "add-port":
                return await self.firewall.add_port(params["port"], params.get("protocol", "tcp"), permanent)
            elif action == "remove-port":
                return await self.firewall.remove_port(params["port"], params.get("protocol", "tcp"), permanent)
            elif action == "add-service":
                return await self.firewall.add_service(params["service"], permanent)
            elif action == "remove-service":
                return await self.firewall.remove_service(params["service"], permanent)
            elif action == "add-rich-rule":
                return await self.firewall.add_rich_rule(params["rule"], permanent)
            elif action == "remove-rich-rule":
                return await self.firewall.remove_rich_rule(params["rule"], permanent)
            elif action == "reload":
                return await self.firewall.reload()
            elif action == "get-zones":
                return await self.firewall.get_zones()
            elif action == "get-default-zone":
                return await self.firewall.get_default_zone()
            else:
                return CommandResult(command=f"firewall {action}", exit_code=1, stdout="", stderr=f"Unknown action: {action}")

        elif name == "network":
            action = params["action"]
            if action == "connections":
                return await self.network.connections()
            elif action == "connection-details":
                return await self.network.connection_details(params["connection"])
            elif action == "devices":
                return await self.network.devices()
            elif action == "set-static-ip":
                return await self.network.set_static_ip(
                    params["connection"], params["ip"], params["gateway"], params.get("dns", "8.8.8.8,8.8.4.4")
                )
            elif action == "set-dhcp":
                return await self.network.set_dhcp(params["connection"])
            elif action == "ip-addresses":
                return await self.network.ip_addresses()
            elif action == "routes":
                return await self.network.routes()
            elif action == "listening-ports":
                return await self.network.listening_ports()
            elif action == "all-connections":
                return await self.network.all_connections()
            elif action == "dns-lookup":
                return await self.network.dns_lookup(params["host"])
            elif action == "ping":
                return await self.network.ping(params["host"], params.get("count", 4))
            else:
                return CommandResult(command=f"network {action}", exit_code=1, stdout="", stderr=f"Unknown action: {action}")

        elif name == "read_file":
            return await self.files.read(params["path"])

        elif name == "write_file":
            return await self.files.write(params["path"], params["content"])

        elif name == "search_files":
            action = params["action"]
            path = params.get("path", "/etc")
            pattern = params.get("pattern", "")
            if action == "grep":
                return await self.files.search(pattern, path)
            elif action == "find":
                return await self.files.find(path, pattern)
            elif action == "list":
                return await self.files.list_dir(path)
            elif action == "disk-usage":
                return await self.files.disk_usage(path)
            elif action == "dir-size":
                return await self.files.dir_size(path)
            else:
                return CommandResult(command=f"search_files {action}", exit_code=1, stdout="", stderr=f"Unknown action: {action}")

        elif name == "users":
            action = params["action"]
            username = params.get("username", "")
            if action == "list":
                return await self.users.list_users()
            elif action == "info":
                return await self.users.user_info(username)
            elif action == "create":
                return await self.users.create_user(
                    username, groups=params.get("groups"), shell=params.get("shell", "/bin/bash")
                )
            elif action == "delete":
                return await self.users.delete_user(username, remove_home=params.get("remove_home", False))
            elif action == "lock":
                return await self.users.lock_user(username)
            elif action == "unlock":
                return await self.users.unlock_user(username)
            elif action == "add-to-group":
                return await self.users.add_to_group(username, params["group"])
            elif action == "set-ssh-key":
                return await self.users.set_ssh_key(username, params["ssh_key"])
            elif action == "list-groups":
                return await self.users.list_groups()
            elif action == "who-logged-in":
                return await self.users.who_logged_in()
            elif action == "last-logins":
                return await self.users.last_logins(params.get("count", 20))
            else:
                return CommandResult(command=f"users {action}", exit_code=1, stdout="", stderr=f"Unknown action: {action}")

        elif name == "diagnostics":
            action = params["action"]
            if action == "overview":
                return await self.diagnostics.system_overview()
            elif action == "top-processes":
                return await self.diagnostics.top_processes(params.get("count", 10))
            elif action == "memory":
                return await self.diagnostics.memory_usage()
            elif action == "cpu":
                return await self.diagnostics.cpu_usage()
            elif action == "disk-space":
                return await self.diagnostics.disk_space()
            elif action == "disk-inodes":
                return await self.diagnostics.disk_inodes()
            elif action == "smart-health":
                return await self.diagnostics.smart_health(params.get("device", "/dev/sda"))
            elif action == "smart-all":
                return await self.diagnostics.smart_all_drives()
            elif action == "journal-errors":
                return await self.diagnostics.journal_errors(
                    since=params.get("since", "1h ago"), priority=params.get("priority", "err")
                )
            elif action == "failed-services":
                return await self.diagnostics.failed_services()
            elif action == "selinux-denials":
                return await self.diagnostics.selinux_denials(since=params.get("since", "1h ago"))
            elif action == "network-connections":
                return await self.diagnostics.network_connections()
            elif action == "sensors":
                return await self.diagnostics.sensors()
            elif action == "swap":
                return await self.diagnostics.swap_usage()
            elif action == "auth-failures":
                return await self.diagnostics.recent_auth_failures(params.get("count", 30))
            elif action == "cert-check":
                return await self.diagnostics.certificate_check(params.get("path", ""))
            elif action == "load":
                return await self.diagnostics.load_average()
            else:
                return CommandResult(command=f"diagnostics {action}", exit_code=1, stdout="", stderr=f"Unknown action: {action}")

        else:
            return CommandResult(
                command=f"unknown_tool({name})",
                exit_code=1,
                stdout="",
                stderr=f"Unknown tool: {name}",
            )
