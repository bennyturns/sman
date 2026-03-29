"""User and permission management tools."""

from __future__ import annotations

from sman.tools.runner import ToolRunner, CommandResult


class UserTool:
    """Manage system users and groups."""

    def __init__(self, runner: ToolRunner):
        self.runner = runner

    async def list_users(self, shell_only: bool = True) -> CommandResult:
        if shell_only:
            return await self.runner.execute(
                "getent passwd | grep -v nologin | grep -v /bin/false | grep -v /sbin/nologin"
            )
        return await self.runner.execute("getent passwd")

    async def user_info(self, username: str) -> CommandResult:
        return await self.runner.execute(f"id {username}")

    async def create_user(
        self,
        username: str,
        groups: list[str] | None = None,
        shell: str = "/bin/bash",
        create_home: bool = True,
    ) -> CommandResult:
        cmd = f"useradd -s {shell}"
        if create_home:
            cmd += " -m"
        if groups:
            cmd += f" -G {','.join(groups)}"
        cmd += f" {username}"
        return await self.runner.execute(cmd)

    async def delete_user(self, username: str, remove_home: bool = False) -> CommandResult:
        cmd = f"userdel {username}"
        if remove_home:
            cmd += " -r"
        return await self.runner.execute(cmd)

    async def lock_user(self, username: str) -> CommandResult:
        return await self.runner.execute(f"usermod -L {username}")

    async def unlock_user(self, username: str) -> CommandResult:
        return await self.runner.execute(f"usermod -U {username}")

    async def add_to_group(self, username: str, group: str) -> CommandResult:
        return await self.runner.execute(f"usermod -aG {group} {username}")

    async def set_ssh_key(self, username: str, key: str) -> CommandResult:
        """Set an SSH authorized key for a user."""
        cmds = [
            f"mkdir -p /home/{username}/.ssh",
            f"echo '{key}' >> /home/{username}/.ssh/authorized_keys",
            f"chmod 700 /home/{username}/.ssh",
            f"chmod 600 /home/{username}/.ssh/authorized_keys",
            f"chown -R {username}:{username} /home/{username}/.ssh",
        ]
        return await self.runner.execute(" && ".join(cmds))

    async def list_groups(self) -> CommandResult:
        return await self.runner.execute("getent group")

    async def who_logged_in(self) -> CommandResult:
        return await self.runner.execute("who")

    async def last_logins(self, count: int = 20) -> CommandResult:
        return await self.runner.execute(f"last -n {count}")
