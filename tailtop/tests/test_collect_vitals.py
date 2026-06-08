"""collect_vitals: user resolution + parse of piped script output."""
from __future__ import annotations

from pathlib import Path


from tailtop.data.client import TailscaleClient, ssh_user_for

FIX = Path(__file__).parent / "fixtures"

USER_MAP = {
    "fastclock": "nickv2026", "slowclock": "nickv2026",
    "smallclock": "nickv2026", "squareclock": "nickv2026",
    "nickv-orangepizero2w": "nickv",
}


def test_ssh_user_for_known_hosts() -> None:
    assert ssh_user_for("fastclock", USER_MAP) == "nickv2026"
    assert ssh_user_for("nickv-orangepizero2w", USER_MAP) == "nickv"


def test_ssh_user_for_unknown_falls_back_to_default() -> None:
    assert ssh_user_for("dashboard-ink-bed", USER_MAP, default="pi") == "pi"


async def test_collect_vitals_parses_piped_output(monkeypatch) -> None:
    raw = (FIX / "vitals_fastclock.json").read_text()
    client = TailscaleClient()

    async def fake_ssh(self, dest, user):  # noqa: ANN001
        assert dest == "fastclock"  # tailscale transport → bare hostname (MagicDNS)
        assert user == "nickv2026"
        return raw

    monkeypatch.setattr(TailscaleClient, "_ssh_collect", fake_ssh, raising=True)
    v = await client.collect_vitals("fastclock", user_map=USER_MAP)
    assert v is not None
    # The fixture's "host" field is the Pi's actual hostname ("SuperClockFast"),
    # which differs from the Tailscale peer name ("fastclock"). Both are valid;
    # the fixture is ground truth.
    assert v.host == "SuperClockFast"
    assert v.vcgencmd_present is True


async def test_collect_vitals_tailscale_ignores_addr_map(monkeypatch) -> None:
    """With tailscale transport, addr_map is ignored — bare hostname is used."""
    raw = (FIX / "vitals_fastclock.json").read_text()
    client = TailscaleClient()
    client.ssh_transport = "tailscale"
    captured: list[str] = []

    async def fake_ssh(self, dest, user):  # noqa: ANN001
        captured.append(dest)
        return raw

    monkeypatch.setattr(TailscaleClient, "_ssh_collect", fake_ssh, raising=True)
    v = await client.collect_vitals(
        "fastclock", user_map=USER_MAP, addr_map={"fastclock": "100.78.29.28"}
    )
    assert v is not None
    # tailscale transport always uses the bare host, not the IP
    assert captured == ["fastclock"]


async def test_collect_vitals_openssh_uses_addr_map_ip(monkeypatch) -> None:
    """With openssh transport, addr_map IP is used as the SSH target."""
    raw = (FIX / "vitals_fastclock.json").read_text()
    client = TailscaleClient()
    client.ssh_transport = "openssh"
    captured: list[str] = []

    async def fake_ssh(self, dest, user):  # noqa: ANN001
        captured.append(dest)
        return raw

    monkeypatch.setattr(TailscaleClient, "_ssh_collect", fake_ssh, raising=True)
    v = await client.collect_vitals(
        "fastclock", user_map=USER_MAP, addr_map={"fastclock": "100.78.29.28"}
    )
    assert v is not None
    assert captured == ["100.78.29.28"]


async def test_transport_tailscale_builds_argv(monkeypatch) -> None:
    """tailscale transport builds: [binary, 'ssh', 'user@host', '--', 'sh', '-s']."""
    client = TailscaleClient()
    client.ssh_transport = "tailscale"
    captured_argv: list[list[str]] = []

    async def fake_run_pipe(self, argv, stdin_bytes):  # noqa: ANN001
        captured_argv.append(argv)
        return "{}"

    monkeypatch.setattr(TailscaleClient, "_run_pipe", fake_run_pipe, raising=True)
    # _run_pipe returning "{}" → Vitals.from_collect_json({}) may return None; that's fine
    try:
        await client.collect_vitals("fastclock", user_map=USER_MAP)
    except Exception:  # noqa: BLE001
        pass  # parse failure is OK; we only care about argv

    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert argv == [client._binary, "ssh", "nickv2026@fastclock", "--", "sh", "-s"]


async def test_transport_openssh_builds_argv(monkeypatch) -> None:
    """openssh transport builds: ['ssh', '-i', key, ..., 'user@host', 'sh', '-s']."""
    client = TailscaleClient()
    client.ssh_transport = "openssh"
    captured_argv: list[list[str]] = []

    async def fake_run_pipe(self, argv, stdin_bytes):  # noqa: ANN001
        captured_argv.append(argv)
        return "{}"

    monkeypatch.setattr(TailscaleClient, "_run_pipe", fake_run_pipe, raising=True)
    try:
        await client.collect_vitals("fastclock", user_map=USER_MAP)
    except Exception:  # noqa: BLE001
        pass

    assert len(captured_argv) == 1
    argv = captured_argv[0]
    # starts with ssh + key flag
    assert argv[0] == "ssh"
    assert argv[1] == "-i"
    import os
    assert argv[2] == os.path.expanduser("~/.ssh/id_ed25519")
    # ends with the target and remote command
    assert argv[-3:] == ["nickv2026@fastclock", "sh", "-s"]


def test_default_transport_is_tailscale(monkeypatch) -> None:
    """Default transport is tailscale (collects all 8 Pis); openssh is the opt-in fallback."""
    monkeypatch.delenv("TAILTOP_SSH_TRANSPORT", raising=False)
    assert TailscaleClient().ssh_transport == "tailscale"
