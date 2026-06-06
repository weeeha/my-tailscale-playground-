"""Architecture demo widget — animated diagram of Tailscale control plane.

Shows three sites (Main Office / Remote User / Branch Office) each containing
Tailscale Clients rendered as device cards, all connecting to a central
Coordination Server via animated chevron-stripe belts.  The Coordination
Server talks to an Auth Server; the Auth Server auths against Active Directory
via a static curved arrow.

Run standalone with: ``python -m tailtop.widgets.architecture_demo``
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widget import Widget

from tailtop.data.models import ConnType
from tailtop.widgets.belt import (
    BeltRenderer,
    BeltState,
    CharCanvas,
    LaneState,
    TIER_STYLE,
    TreadAnimator,
)


# ---- Demo data ----

@dataclass
class DemoPeer:
    host_name: str
    rx_bps: float
    tx_bps: float
    site: str  # "main", "remote", "branch"


DEMO_PEERS: list[DemoPeer] = [
    DemoPeer("prod-server",   rx_bps=8_500_000,  tx_bps=210_000,    site="main"),
    DemoPeer("dev-laptop",    rx_bps=42_000,     tx_bps=180_000,    site="main"),
    DemoPeer("alice-mbp",     rx_bps=1_500_000,  tx_bps=320_000,    site="remote"),
    DemoPeer("warehouse-pi",  rx_bps=0,          tx_bps=0,          site="branch"),
    DemoPeer("branch-nas",    rx_bps=4_500_000,  tx_bps=12_000_000, site="branch"),
]


# ---- Style constants ----
SITE_BORDER_STYLE = "#cfd3da"
SITE_LABEL_STYLE = "dim #8a8f99"
INNER_BORDER_STYLE = "#8a8f99"
COORD_BORDER_STYLE = "bold #cfd3da"
COORD_FILL_STYLE = "bold white"
AUTH_BORDER_STYLE = "#cfd3da"
ARROW_STYLE = "#8bb6ff"
BULLET_STYLE = "#8bb6ff"

# ---- Layout constants ----

# Site boxes (outer rounded corners)
SITE_LEFT = 2
SITE_WIDTH = 28       # total width of site box including borders
SITE_INNER_WIDTH = 24  # width of inner entry boxes

# Vertical positions of the three site boxes (top row of each)
MAIN_OFFICE_TOP = 1
MAIN_OFFICE_H = 14    # AD box (h=3) + 2 client boxes (h=4 each) + label + padding
REMOTE_USER_TOP = 17
REMOTE_USER_H = 7
BRANCH_OFFICE_TOP = 25
BRANCH_OFFICE_H = 11  # 2 client boxes (h=4 each) + label + padding

# Inner AD entry box dimensions (3 rows tall: border + content + border)
INNER_BOX_H = 3
# Inner client card dimensions (4 rows tall: border + hostname + rate + border)
CLIENT_CARD_H = 4
INNER_BOX_LEFT_OFFSET = 2   # offset from site box left border
INNER_BOX_WIDTH = 24  # width including borders

# Coordination server box (center)
COORD_LEFT = 40
COORD_TOP = 7
COORD_WIDTH = 26
COORD_HEIGHT = 14

# Auth server box (right)
AUTH_LEFT = 80
AUTH_TOP = 4
AUTH_WIDTH = 22
AUTH_HEIGHT = 6

# Arrow merge column (where per-client lines merge before entering coord box)
ARROW_MERGE_X = 39

# Canvas dimensions
CANVAS_W = 110
CANVAS_H = 38

# Animation interval (10 Hz)
_ANIMATION_INTERVAL = 1 / 10


def _draw_rounded_box(
    c: CharCanvas,
    left: int,
    top: int,
    width: int,
    height: int,
    style: str,
) -> None:
    """Draw a box with rounded corners (╭╮╰╯) and single lines."""
    right = left + width - 1
    bot = top + height - 1
    c.set(left, top, "╭", style)
    c.set(right, top, "╮", style)
    c.set(left, bot, "╰", style)
    c.set(right, bot, "╯", style)
    for x in range(left + 1, right):
        c.set(x, top, "─", style)
        c.set(x, bot, "─", style)
    for y in range(top + 1, bot):
        c.set(left, y, "│", style)
        c.set(right, y, "│", style)


def _draw_square_box(
    c: CharCanvas,
    left: int,
    top: int,
    width: int,
    height: int,
    style: str,
) -> None:
    """Draw a box with square corners (┌┐└┘) and single lines."""
    right = left + width - 1
    bot = top + height - 1
    c.set(left, top, "┌", style)
    c.set(right, top, "┐", style)
    c.set(left, bot, "└", style)
    c.set(right, bot, "┘", style)
    for x in range(left + 1, right):
        c.set(x, top, "─", style)
        c.set(x, bot, "─", style)
    for y in range(top + 1, bot):
        c.set(left, y, "│", style)
        c.set(right, y, "│", style)


def _center_text(
    c: CharCanvas,
    left: int,
    y: int,
    width: int,
    text: str,
    style: str,
) -> None:
    """Write text centered within a horizontal span."""
    pad = max(0, (width - len(text)) // 2)
    c.write(left + pad, y, text, style)


class ArchitectureDemo(Widget):
    """Animated Tailscale architecture diagram."""

    DEFAULT_CSS = """
    ArchitectureDemo {
        background: #0d0d12;
        color: #cfd3da;
        width: 1fr;
        height: 1fr;
    }
    """

    CANVAS_W = CANVAS_W
    CANVAS_H = CANVAS_H

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._renderer = BeltRenderer()
        self._last_tick: float | None = None

        # Per-peer belt states keyed by hostname
        self._belt_states: dict[str, BeltState] = {
            p.host_name: BeltState(
                peer_id=p.host_name,
                conn_type=ConnType.DIRECT,
                in_lane=LaneState(cells_per_second=TreadAnimator.speed_for(p.rx_bps)),
                out_lane=LaneState(cells_per_second=TreadAnimator.speed_for(p.tx_bps)),
                in_tier=TreadAnimator.tier_for(p.rx_bps),
                out_tier=TreadAnimator.tier_for(p.tx_bps),
                rx_bps=p.rx_bps,
                tx_bps=p.tx_bps,
            )
            for p in DEMO_PEERS
        }

        # Coord→auth belt: aggregate tx as proxy for auth chatter
        sum_tx = sum(p.tx_bps for p in DEMO_PEERS)
        self._coord_to_auth_state = LaneState(
            cells_per_second=TreadAnimator.speed_for(sum_tx)
        )
        self._coord_to_auth_tier = TreadAnimator.tier_for(sum_tx)

    def on_mount(self) -> None:
        self._last_tick = None
        self._anim_timer = self.set_interval(_ANIMATION_INTERVAL, self._on_tick)

    def _on_tick(self) -> None:
        now = time.monotonic()
        dt = (now - self._last_tick) if self._last_tick is not None else _ANIMATION_INTERVAL
        self._last_tick = now
        for state in self._belt_states.values():
            state.in_lane.advance(dt=dt)
            state.out_lane.advance(dt=dt)
        self._coord_to_auth_state.advance(dt=dt)
        self.refresh()

    def render(self) -> Text:
        c = CharCanvas(width=self.CANVAS_W, height=self.CANVAS_H)
        self._draw_main_office(c)
        self._draw_remote_user(c)
        self._draw_branch_office(c)
        self._draw_coordination_server(c)
        self._draw_auth_server(c)
        self._draw_connections(c)
        self._draw_auth_to_ad_arrow(c)
        return c.to_text()

    # ------------------------------------------------------------------
    # Inner box / card helpers
    # ------------------------------------------------------------------

    def _draw_inner_ad_entry(self, c: CharCanvas, box_top: int) -> None:
        """Draw a 3-row AD entry box (no rate, no bullet — just the label)."""
        il = SITE_LEFT + INNER_BOX_LEFT_OFFSET
        iw = INNER_BOX_WIDTH
        _draw_square_box(c, il, box_top, iw, INNER_BOX_H, INNER_BORDER_STYLE)
        text_x = il + 2
        max_text = iw - 4
        c.write(text_x, box_top + 1, "Active Directory"[:max_text], COORD_FILL_STYLE)

    def _draw_client_card(self, c: CharCanvas, box_top: int, peer: DemoPeer) -> None:
        """Draw a 4-row device card with hostname, rate row, and tier bullet."""
        il = SITE_LEFT + INNER_BOX_LEFT_OFFSET
        iw = INNER_BOX_WIDTH
        state = self._belt_states.get(peer.host_name)

        # Border style based on in_tier
        in_tier = state.in_tier if state else "idle"
        border_style = TIER_STYLE.get(in_tier, INNER_BORDER_STYLE)

        _draw_square_box(c, il, box_top, iw, CLIENT_CARD_H, border_style)

        text_x = il + 2
        max_text = iw - 5  # leave room for bullet (2 chars) + border

        # Line 1: hostname
        hostname = peer.host_name[:max_text]
        c.write(text_x, box_top + 1, hostname, COORD_FILL_STYLE)

        # Line 2: compact rate
        if state:
            rate_str = (
                f"↑{self._renderer._compact_rate(state.tx_bps)} "
                f"↓{self._renderer._compact_rate(state.rx_bps)}"
            )[:max_text]
        else:
            rate_str = "↑0 ↓0"
        c.write(text_x, box_top + 2, rate_str, "dim")

        # Bullet colored by tier (uses in_tier)
        bullet_style = TIER_STYLE.get(in_tier, BULLET_STYLE)
        c.set(il + iw - 2, box_top + 1, "●", bullet_style)

    # ------------------------------------------------------------------
    # Site boxes
    # ------------------------------------------------------------------

    def _draw_main_office(self, c: CharCanvas) -> None:
        top = MAIN_OFFICE_TOP
        h = MAIN_OFFICE_H
        _draw_rounded_box(c, SITE_LEFT, top, SITE_WIDTH, h, SITE_BORDER_STYLE)
        # Active Directory (no rate, no bullet)
        self._draw_inner_ad_entry(c, top + 1)
        # Two Tailscale Clients (device cards, 4 rows each)
        main_peers = [p for p in DEMO_PEERS if p.site == "main"]
        self._draw_client_card(c, top + 4, main_peers[0])
        self._draw_client_card(c, top + 8, main_peers[1])
        # Label at bottom
        _center_text(c, SITE_LEFT + 1, top + h - 2, SITE_WIDTH - 2, "Main Office", SITE_LABEL_STYLE)

    def _draw_remote_user(self, c: CharCanvas) -> None:
        top = REMOTE_USER_TOP
        h = REMOTE_USER_H
        _draw_rounded_box(c, SITE_LEFT, top, SITE_WIDTH, h, SITE_BORDER_STYLE)
        remote_peers = [p for p in DEMO_PEERS if p.site == "remote"]
        self._draw_client_card(c, top + 1, remote_peers[0])
        _center_text(c, SITE_LEFT + 1, top + h - 2, SITE_WIDTH - 2, "Remote User", SITE_LABEL_STYLE)

    def _draw_branch_office(self, c: CharCanvas) -> None:
        top = BRANCH_OFFICE_TOP
        h = BRANCH_OFFICE_H
        _draw_rounded_box(c, SITE_LEFT, top, SITE_WIDTH, h, SITE_BORDER_STYLE)
        branch_peers = [p for p in DEMO_PEERS if p.site == "branch"]
        self._draw_client_card(c, top + 1, branch_peers[0])
        self._draw_client_card(c, top + 5, branch_peers[1])
        _center_text(c, SITE_LEFT + 1, top + h - 2, SITE_WIDTH - 2, "Branch Office", SITE_LABEL_STYLE)

    # ------------------------------------------------------------------
    # Coordination Server
    # ------------------------------------------------------------------

    def _draw_coordination_server(self, c: CharCanvas) -> None:
        left = COORD_LEFT
        top = COORD_TOP
        w = COORD_WIDTH
        h = COORD_HEIGHT
        _draw_square_box(c, left, top, w, h, COORD_BORDER_STYLE)
        # Small circle at top-left interior
        c.set(left + 2, top + 1, "○", ARROW_STYLE)
        # Title lines
        _center_text(c, left + 1, top + 5, w - 2, "Tailscale", COORD_FILL_STYLE)
        _center_text(c, left + 1, top + 6, w - 2, "Coordination Server", COORD_FILL_STYLE)

    # ------------------------------------------------------------------
    # Auth Server
    # ------------------------------------------------------------------

    def _draw_auth_server(self, c: CharCanvas) -> None:
        left = AUTH_LEFT
        top = AUTH_TOP
        w = AUTH_WIDTH
        h = AUTH_HEIGHT
        _draw_square_box(c, left, top, w, h, AUTH_BORDER_STYLE)
        _center_text(c, left + 1, top + 1, w - 2, "Auth Server", COORD_FILL_STYLE)
        _center_text(c, left + 1, top + 2, w - 2, "eg. Office 365", SITE_LABEL_STYLE)

    # ------------------------------------------------------------------
    # Animated connection belts: clients → Coordination Server
    # ------------------------------------------------------------------

    def _draw_connections(self, c: CharCanvas) -> None:
        """Draw animated chevron-stripe belts from each client to the Coord box,
        plus a 2-row belt from Coord to Auth Server."""

        # x-range for belts: right border of inner box + 1 → left border of coord box - 1
        # Right border of inner client card
        card_right = SITE_LEFT + INNER_BOX_LEFT_OFFSET + INNER_BOX_WIDTH - 1
        belt_x_start = card_right + 1
        belt_x_end = COORD_LEFT - 1

        # Map each DemoPeer to the two rows used for its belt.
        # Each client card top row → the card's two content rows are +1 (hostname) and +2 (rate).
        # We use those same two rows as the belt rows so the belt aligns with the card.
        #
        # Main Office clients: top+4 and top+8
        main_top = MAIN_OFFICE_TOP
        remote_top = REMOTE_USER_TOP
        branch_top = BRANCH_OFFICE_TOP

        # (peer, belt_top_row)  — top_row is the hostname row, top_row+1 is the rate row
        peer_belt_rows: list[tuple[DemoPeer, int]] = []
        main_peers = [p for p in DEMO_PEERS if p.site == "main"]
        peer_belt_rows.append((main_peers[0], main_top + 4 + 1))    # hostname row
        peer_belt_rows.append((main_peers[1], main_top + 8 + 1))

        remote_peers = [p for p in DEMO_PEERS if p.site == "remote"]
        peer_belt_rows.append((remote_peers[0], remote_top + 1 + 1))

        branch_peers = [p for p in DEMO_PEERS if p.site == "branch"]
        peer_belt_rows.append((branch_peers[0], branch_top + 1 + 1))
        peer_belt_rows.append((branch_peers[1], branch_top + 5 + 1))

        for peer, y_top in peer_belt_rows:
            y_bot = y_top + 1
            state = self._belt_states.get(peer.host_name)
            if state is None:
                continue
            # Top row: peer→coord (going right, ▶)
            self._renderer._draw_hlane(
                c, y_top, belt_x_start, belt_x_end,
                going_left=False,
                phase=state.in_lane.phase,
                tier=state.in_tier,
                dim=False,
            )
            # Bottom row: coord→peer (going left, ◀)
            self._renderer._draw_hlane(
                c, y_bot, belt_x_start, belt_x_end,
                going_left=True,
                phase=state.out_lane.phase,
                tier=state.out_tier,
                dim=False,
            )

        # Coord → Auth Server belt (2 rows)
        coord_right = COORD_LEFT + COORD_WIDTH - 1
        auth_entry_y = AUTH_TOP + AUTH_HEIGHT // 2
        auth_left = AUTH_LEFT

        coord_to_auth_top = auth_entry_y
        coord_to_auth_bot = auth_entry_y + 1

        ca_tier = self._coord_to_auth_tier
        ca_phase = self._coord_to_auth_state.phase

        # top row: going right (coord→auth)
        self._renderer._draw_hlane(
            c, coord_to_auth_top, coord_right + 1, auth_left - 1,
            going_left=False,
            phase=ca_phase,
            tier=ca_tier,
            dim=False,
        )
        # bottom row: going left (auth→coord)
        self._renderer._draw_hlane(
            c, coord_to_auth_bot, coord_right + 1, auth_left - 1,
            going_left=True,
            phase=ca_phase,
            tier=ca_tier,
            dim=False,
        )

    # ------------------------------------------------------------------
    # Auth Server → Active Directory curved arrow (static)
    # ------------------------------------------------------------------

    def _draw_auth_to_ad_arrow(self, c: CharCanvas) -> None:
        """Long curved arrow from Auth Server top, over the diagram, to Active Directory."""
        auth_mid_x = AUTH_LEFT + AUTH_WIDTH // 2
        auth_top_y = AUTH_TOP

        # AD box is at MAIN_OFFICE_TOP + 1, content row = MAIN_OFFICE_TOP + 2
        ad_y = MAIN_OFFICE_TOP + 2
        ad_right_x = SITE_LEFT + INNER_BOX_LEFT_OFFSET + INNER_BOX_WIDTH - 1

        arc_y = 0
        arc_down_x = ad_right_x + 2

        # 1. Vertical segment going up from auth top
        for y in range(arc_y + 1, auth_top_y):
            c.set(auth_mid_x, y, "│", ARROW_STYLE)
        # Corner at top of auth ascent
        c.set(auth_mid_x, arc_y, "╭", ARROW_STYLE)

        # 2. Horizontal segment at arc_y from arc_down_x to auth_mid_x
        for x in range(arc_down_x + 1, auth_mid_x):
            c.set(x, arc_y, "─", ARROW_STYLE)
        # Corner at left turn-down
        c.set(arc_down_x, arc_y, "╮", ARROW_STYLE)

        # 3. Vertical segment going down from arc_y+1 to ad_y
        for y in range(arc_y + 1, ad_y):
            c.set(arc_down_x, y, "│", ARROW_STYLE)

        # 4. Horizontal run left from arc_down_x to ad_right_x+1 with arrowhead
        for x in range(ad_right_x + 1, arc_down_x):
            c.set(x, ad_y, "─", ARROW_STYLE)
        c.set(ad_right_x, ad_y, "◀", ARROW_STYLE)


if __name__ == "__main__":
    class _Demo(App):
        BINDINGS = [("q", "quit", "Quit")]
        CSS = "ArchitectureDemo { width: 1fr; height: 1fr; }"

        def compose(self) -> ComposeResult:
            yield ArchitectureDemo()

    _Demo().run()
