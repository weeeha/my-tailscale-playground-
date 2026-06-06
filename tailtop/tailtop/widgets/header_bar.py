"""Top header bar — brand, mode tabs, identity chip, connection, count.

Owns the chrome above every mode. Mode tabs are clickable; the status segment,
identity chip, and active-tab state are pushed in by the app via ``set_state``.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from tailtop.data.models import Status

# Display order of the tabs (matches the official-app-style header).
_TABS = [("cockpit", "Cockpit"), ("list", "List"), ("observatory", "Observatory")]


class ModeTab(Static):
    """A single clickable mode tab."""

    def __init__(self, mode_id: str, label: str) -> None:
        super().__init__(label)
        self.mode_id = mode_id

    def on_click(self) -> None:
        action = getattr(self.app, "action_set_mode", None)
        if action:
            action(self.mode_id)


class HeaderBar(Horizontal):
    """Persistent top bar: brand · tabs · identity chip · spacer · status."""

    def compose(self) -> ComposeResult:
        yield Static("TailTop", id="brand")
        with Horizontal(id="tabs"):
            for tab_id, label in _TABS:
                yield ModeTab(tab_id, label)
        yield Static(id="identity")
        yield Static(id="spacer")
        yield Static(id="status")

    def set_state(self, status: Status | None, mode: str, error: str = "") -> None:
        for tab in self.query(ModeTab):
            tab.set_class(tab.mode_id == mode, "-active")

        identity = self.query_one("#identity", Static)
        if status is not None:
            me = status.self_peer
            chip = Text()
            chip.append("● ", style="#8bb6ff")
            chip.append("YOU", style="bold #8bb6ff")
            chip.append("  ")
            chip.append(me.name or "you", style="#cfd3da")
            chip.append("  ")
            chip.append(me.ipv4 or "—", style="#6b6f78")
            identity.update(chip)
        else:
            identity.update(Text("● YOU  …", style="dim"))

        segment = self.query_one("#status", Static)
        line = Text()
        if error:
            line.append("● ", style="#ff7e88")
            line.append(error, style="#ff7e88")
        elif status is None:
            line.append("◌ ", style="#6b6f78")
            line.append("connecting…", style="#6b6f78")
        else:
            if status.connected:
                line.append("● ", style="#7be39b")
                line.append("Connected", style="#7be39b")
            else:
                line.append("○ ", style="#6b6f78")
                line.append(status.backend_state or "offline", style="#6b6f78")
            line.append("    ")
            line.append(status.user_display or "—", style="#cfd3da")
            line.append("    ")
            line.append(
                f"{status.online_count}/{status.total_count} online",
                style="#7be39b" if status.connected else "#6b6f78",
            )
        segment.update(line)
