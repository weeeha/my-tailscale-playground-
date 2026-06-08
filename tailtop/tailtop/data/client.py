"""The only CLI-aware code in tailtop.

``TailscaleClient`` shells out to the ``tailscale`` binary for status, netcheck,
ping, and whois calls. ``collect_vitals`` uses SSH to pipe the fleet_collect.sh
agent script to a remote host. The transport is selected by ``self.ssh_transport``
(default ``"openssh"``; set env ``TAILTOP_SSH_TRANSPORT=tailscale`` to switch):

- ``"openssh"`` (default): ``ssh -i ~/.ssh/id_ed25519 <user>@<host> sh -s`` —
  key-based, reaches the Pi's native sshd (e.g. via a ``.local`` ssh-config
  entry on the LAN). Works today for hosts with a key + reachable sshd.
- ``"tailscale"``: ``tailscale ssh <user>@<host> -- sh -s`` — the intended
  off-LAN path for nodes running Tailscale SSH. Requires a tailnet ACL SSH rule
  with ``action: "accept"`` (not ``check``) so unattended polling isn't blocked
  by an interactive browser auth prompt.

Every call applies timeouts and normalizes failures into typed exceptions.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from tailtop.data.models import Status
from tailtop.data.vitals import Vitals

_AGENT_SCRIPT = Path(__file__).parents[2] / "agent" / "fleet_collect.sh"


def ssh_user_for(host: str, user_map: dict[str, str], default: str = "") -> str:
    """Resolve the SSH login user for a Pi host (explicit map wins)."""
    return user_map.get(host, default)


class TailscaleError(Exception):
    """A tailscale command failed (non-zero exit)."""

    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.args = args
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"`tailscale {' '.join(args)}` failed: {self.stderr}")


class TailscaleNotFound(Exception):
    """The tailscale binary is not on PATH."""


class TailscaleTimeout(Exception):
    """A tailscale command exceeded its timeout."""


class TailscaleClient:
    """Async wrapper around the tailscale CLI."""

    def __init__(self, binary: str | None = None, default_timeout: float = 10.0) -> None:
        self._binary = binary or shutil.which("tailscale") or "tailscale"
        self.default_timeout = default_timeout
        self.ssh_transport: str = os.environ.get("TAILTOP_SSH_TRANSPORT", "openssh")

    @property
    def available(self) -> bool:
        return shutil.which(self._binary) is not None or self._binary == "tailscale"

    # ---- low-level runner --------------------------------------------------

    async def run(
        self, *args: str, timeout: float | None = None, check: bool = True
    ) -> str:
        """Run ``tailscale <args>`` and return stdout.

        Raises TailscaleNotFound / TailscaleTimeout / TailscaleError.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise TailscaleNotFound(self._binary) from exc

        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or self.default_timeout
            )
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise TailscaleTimeout(" ".join(args)) from exc

        stdout = out.decode("utf-8", "replace")
        if check and proc.returncode != 0:
            raise TailscaleError(list(args), proc.returncode or -1, err.decode("utf-8", "replace"))
        return stdout

    # ---- reads -------------------------------------------------------------

    async def status(self) -> Status:
        raw = await self.run("status", "--json", timeout=8.0)
        return Status.from_json(json.loads(raw))

    async def netcheck(self) -> dict:
        raw = await self.run("netcheck", "--format=json", timeout=20.0)
        return json.loads(raw)

    async def whois(self, ip: str) -> str:
        return await self.run("whois", ip, timeout=8.0)

    async def ping_once(self, host: str) -> str:
        """One ping; stdout carries 'via DERP(region)' or 'direct ... in Nms'."""
        return await self.run("ping", "--c", "1", "--timeout", "3s", host, timeout=6.0, check=False)

    async def _run_pipe(self, argv: list[str], stdin_bytes: bytes) -> str:
        """Spawn *argv*, pipe *stdin_bytes* in, return stdout.

        Raises ``TailscaleTimeout`` (20 s hard cap) or ``TailscaleError`` on
        non-zero exit.  Used by both SSH transports.
        """
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        cmd = argv[1:] if argv and argv[0] == self._binary else argv
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin_bytes), timeout=20.0)
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise TailscaleTimeout(f"collect {' '.join(cmd)}") from exc
        if proc.returncode != 0:
            raise TailscaleError(cmd, proc.returncode or -1, err.decode("utf-8", "replace"))
        return out.decode("utf-8", "replace")

    async def _ssh_collect(self, dest: str, user: str) -> str:
        """Run the collect script on *dest* over SSH, return stdout.

        The transport (``tailscale ssh`` or ``openssh``) is chosen by
        ``self.ssh_transport``.
        """
        target = f"{user}@{dest}" if user else dest
        script_bytes = _AGENT_SCRIPT.read_bytes()

        if self.ssh_transport == "tailscale":
            argv: list[str] = [self._binary, "ssh", target, "--", "sh", "-s"]
        else:
            key = os.path.expanduser("~/.ssh/id_ed25519")
            argv = [
                "ssh",
                "-i", key,
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=15",
                target,
                "sh", "-s",
            ]

        return await self._run_pipe(argv, script_bytes)

    async def collect_vitals(
        self,
        host: str,
        user_map: dict[str, str],
        addr_map: dict[str, str] | None = None,
    ) -> Vitals | None:
        """Collect + parse vitals for one Pi host (raises on SSH/transport failure;
        VitalsPoller turns that into a dropped host).

        For the ``tailscale`` transport, MagicDNS resolves the bare host name
        so ``dest = host`` (addr_map is ignored).  For the ``openssh`` transport,
        ``addr_map`` maps hostname → reachable address (Tailscale IP or LAN
        address); falls back to bare hostname when the host is not in the map.
        """
        user = ssh_user_for(host, user_map)
        if self.ssh_transport == "tailscale":
            dest = host  # MagicDNS handles resolution
        else:
            dest = (addr_map or {}).get(host, host)
        raw = await self._ssh_collect(dest, user)
        return Vitals.from_collect_json(json.loads(raw))
