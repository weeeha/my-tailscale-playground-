"""tailsnap: render primitives, client parsing, and command output."""

from __future__ import annotations

from tailsnap import client, commands
from tailsnap import render as R
from tailsnap.__main__ import main


# -- render primitives -------------------------------------------------------
def test_sparkline_monotonic_and_flat():
    assert R.sparkline([1, 2, 3, 4, 5, 6, 7, 8])[0] == "▁"
    assert R.sparkline([1, 2, 3, 4, 5, 6, 7, 8])[-1] == "█"
    assert set(R.sparkline([5, 5, 5])) == {"▁"}
    assert R.sparkline([]) == ""


def test_bar_clamps_and_fills():
    assert R.bar(5, 10, width=10) == "█████░░░░░"
    assert R.bar(0, 10, width=4) == "░░░░"
    assert R.bar(99, 10, width=4) == "████"      # clamped
    assert R.bar(1, 0, width=4) == "░░░░"        # zero max → empty


def test_human_bytes():
    assert R.human_bytes(512) == "512B"
    assert R.human_bytes(1024) == "1.0KB"
    assert R.human_bytes(5 * 1024 * 1024) == "5.0MB"


def test_visible_len_ignores_ansi():
    colored = R.color("hi", R.GREEN, True)
    assert colored != "hi"
    assert R.visible_len(colored) == 2


def test_table_aligns_with_colored_cells():
    rows = [[R.color("●", R.GREEN), "nas"], ["○", "old-tablet-with-long-name"]]
    out = R.table(["S", "PEER"], rows)
    # every rendered line spans the same visible width
    widths = {R.visible_len(line) for line in out.splitlines()}
    assert len(widths) == 1


# -- client parsing ----------------------------------------------------------
def test_from_json_parses_status():
    data = {
        "Self": {"HostName": "me"},
        "MagicDNSSuffix": "tail.ts.net",
        "Peer": {
            "k1": {"HostName": "nas", "OS": "linux", "TailscaleIPs": ["100.64.0.3"],
                   "Online": True, "ExitNode": True, "RxBytes": 100, "TxBytes": 50},
            "k2": {"HostName": "tab", "OS": "android", "TailscaleIPs": ["100.64.0.7"],
                   "Online": False},
        },
    }
    t = client.from_json(data)
    assert t.self_name == "me"
    assert {p.name for p in t.peers} == {"nas", "tab"}
    assert t.exit_node == "nas"
    assert len(t.online) == 1 and len(t.offline) == 1
    nas = next(p for p in t.peers if p.name == "nas")
    assert nas.traffic == 150 and nas.conn == "direct"


def test_relay_peer_conn():
    t = client.from_json({"Peer": {"k": {"HostName": "phone", "Online": True,
                                         "Relay": "fra", "TailscaleIPs": ["100.64.0.2"]}}})
    assert t.peers[0].conn == "DERP·fra"


# -- commands (against the demo fixture) -------------------------------------
def test_status_lists_all_peers():
    out = commands.status(client.demo(), color=False)
    for name in ("nas", "laptop", "phone", "pi-garage", "old-tablet"):
        assert name in out
    assert "⮐exit" in out          # exit node marked


def test_health_summary():
    out = commands.health(client.demo(), color=False)
    assert out == "tailnet ● 4/5 online · exit:nas · self:workstation"


def test_topology_groups():
    out = commands.topology(client.demo(), color=False)
    assert "exit-node ── nas" in out
    assert "old-tablet" in out      # appears under offline


def test_traffic_sorted_desc():
    out = commands.traffic(client.demo(), color=False)
    lines = out.splitlines()
    assert lines[0].startswith("nas")        # biggest talker first
    assert "old-tablet" not in out           # zero traffic excluded


# -- CLI entry ---------------------------------------------------------------
def test_main_demo_runs_all_views(capsys):
    for view in ("status", "health", "map", "traffic"):
        assert main([view, "--demo", "--color", "never"]) == 0
        assert capsys.readouterr().out.strip()
