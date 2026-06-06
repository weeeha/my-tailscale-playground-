"""Architecture demo widget — static diagram of Tailscale control plane.

Shows three sites (Main Office, Remote User, Branch Office) each containing
Tailscale Clients, all connecting to a central Coordination Server, which
talks to an Auth Server, which auths against Active Directory.

Not data-driven; not animated. An educational static visualization.

Run standalone with: ``python -m tailtop.widgets.architecture_demo``
"""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widget import Widget

from tailtop.widgets.belt import CharCanvas


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
MAIN_OFFICE_H = 12    # tall: AD box + 2 client boxes + label + padding
REMOTE_USER_TOP = 15
REMOTE_USER_H = 6
BRANCH_OFFICE_TOP = 22
BRANCH_OFFICE_H = 9   # 2 client boxes

# Inner entry box dimensions
INNER_BOX_H = 3       # ┌─┐ + content + └─┘
INNER_BOX_LEFT_OFFSET = 2   # offset from site box left border
INNER_BOX_WIDTH = 24  # width including borders

# Coordination server box (center)
COORD_LEFT = 40
COORD_TOP = 7
COORD_WIDTH = 26
COORD_HEIGHT = 12

# Auth server box (right)
AUTH_LEFT = 80
AUTH_TOP = 4
AUTH_WIDTH = 22
AUTH_HEIGHT = 6

# Arrow merge column (where per-client lines merge before entering coord box)
ARROW_MERGE_X = 39

# Canvas dimensions
CANVAS_W = 110
CANVAS_H = 35


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
    # Corners
    c.set(left, top, "╭", style)
    c.set(right, top, "╮", style)
    c.set(left, bot, "╰", style)
    c.set(right, bot, "╯", style)
    # Top and bottom edges
    for x in range(left + 1, right):
        c.set(x, top, "─", style)
        c.set(x, bot, "─", style)
    # Left and right edges
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
    """Static Tailscale architecture diagram."""

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
    # Site boxes
    # ------------------------------------------------------------------

    def _draw_inner_entry(
        self,
        c: CharCanvas,
        box_top: int,
        label: str,
        has_bullet: bool = False,
    ) -> int:
        """Draw a single inner entry box. Returns the row of the right-edge bullet."""
        il = SITE_LEFT + INNER_BOX_LEFT_OFFSET
        iw = INNER_BOX_WIDTH
        _draw_square_box(c, il, box_top, iw, INNER_BOX_H, INNER_BORDER_STYLE)
        # Label text inside (leave 2 chars on each side for border + space)
        text_x = il + 2
        max_text = iw - 4
        c.write(text_x, box_top + 1, label[:max_text], COORD_FILL_STYLE)
        bullet_y = box_top + 1
        if has_bullet:
            # Place bullet just inside the right border
            c.set(il + iw - 2, bullet_y, "●", BULLET_STYLE)
        return bullet_y

    def _draw_main_office(self, c: CharCanvas) -> None:
        top = MAIN_OFFICE_TOP
        h = MAIN_OFFICE_H
        _draw_rounded_box(c, SITE_LEFT, top, SITE_WIDTH, h, SITE_BORDER_STYLE)
        # Active Directory (no bullet)
        self._draw_inner_entry(c, top + 1, "Active Directory", has_bullet=False)
        # Two Tailscale Clients
        self._draw_inner_entry(c, top + 4, "Tailscale Client", has_bullet=True)
        self._draw_inner_entry(c, top + 7, "Tailscale Client", has_bullet=True)
        # Label at bottom
        _center_text(c, SITE_LEFT + 1, top + h - 2, SITE_WIDTH - 2, "Main Office", SITE_LABEL_STYLE)

    def _draw_remote_user(self, c: CharCanvas) -> None:
        top = REMOTE_USER_TOP
        h = REMOTE_USER_H
        _draw_rounded_box(c, SITE_LEFT, top, SITE_WIDTH, h, SITE_BORDER_STYLE)
        self._draw_inner_entry(c, top + 1, "Tailscale Client", has_bullet=True)
        _center_text(c, SITE_LEFT + 1, top + h - 2, SITE_WIDTH - 2, "Remote User", SITE_LABEL_STYLE)

    def _draw_branch_office(self, c: CharCanvas) -> None:
        top = BRANCH_OFFICE_TOP
        h = BRANCH_OFFICE_H
        _draw_rounded_box(c, SITE_LEFT, top, SITE_WIDTH, h, SITE_BORDER_STYLE)
        self._draw_inner_entry(c, top + 1, "Tailscale Client", has_bullet=True)
        self._draw_inner_entry(c, top + 4, "Tailscale Client", has_bullet=True)
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
        _center_text(c, left + 1, top + 4, w - 2, "Tailscale", COORD_FILL_STYLE)
        _center_text(c, left + 1, top + 5, w - 2, "Coordination Server", COORD_FILL_STYLE)

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
    # Connection arrows: clients → Coordination Server
    # ------------------------------------------------------------------

    def _draw_connections(self, c: CharCanvas) -> None:
        """Draw horizontal arrows from each Tailscale Client bullet to the Coord box."""
        # Right edge of the inner box (bullet position x)
        bullet_x = SITE_LEFT + INNER_BOX_LEFT_OFFSET + INNER_BOX_WIDTH - 2
        # Right border of site box
        site_right = SITE_LEFT + SITE_WIDTH - 1
        # Entry point into coordination server (left edge)
        coord_entry_x = COORD_LEFT

        # The rows where each Tailscale Client bullet sits (content row = box_top + 1)
        # Main Office: clients at box_top 5 and 8 → rows 6 and 9
        # Remote User: client at box_top 16 → row 17
        # Branch Office: clients at box_top 23 and 26 → rows 24 and 27
        client_rows = [
            MAIN_OFFICE_TOP + 4 + 1,    # = 6
            MAIN_OFFICE_TOP + 7 + 1,    # = 9
            REMOTE_USER_TOP + 1 + 1,    # = 17
            BRANCH_OFFICE_TOP + 1 + 1,  # = 24
            BRANCH_OFFICE_TOP + 4 + 1,  # = 27
        ]

        # Coordination server left edge entry row: middle of coord box
        coord_mid_y = COORD_TOP + COORD_HEIGHT // 2

        # Merge column between site boxes and coord server
        merge_x = ARROW_MERGE_X

        for row in client_rows:
            # Horizontal line from bullet_x+1 to site_right
            for x in range(bullet_x + 1, site_right + 1):
                c.set(x, row, "─", ARROW_STYLE)
            # Continue horizontal to merge column
            for x in range(site_right + 1, merge_x + 1):
                c.set(x, row, "─", ARROW_STYLE)

        # Vertical merge line connecting all client rows to coord_mid_y
        min_row = min(client_rows)
        max_row = max(client_rows)
        for y in range(min_row, max_row + 1):
            if y not in client_rows:
                c.set(merge_x, y, "│", ARROW_STYLE)
            else:
                # T-junction or pass-through
                c.set(merge_x, y, "┤", ARROW_STYLE)

        # Horizontal line from merge column to coord box, at coord_mid_y
        for x in range(merge_x + 1, coord_entry_x):
            c.set(x, coord_mid_y, "─", ARROW_STYLE)
        # Arrowhead entering coord box
        c.set(coord_entry_x, coord_mid_y, "▶", ARROW_STYLE)

        # Corner connecting merge column to coord mid row
        if coord_mid_y > max_row:
            # Need to go down from max_row to coord_mid_y at merge_x
            for y in range(max_row + 1, coord_mid_y):
                c.set(merge_x, y, "│", ARROW_STYLE)
            c.set(merge_x, max_row, "╰", ARROW_STYLE)
            c.set(merge_x, coord_mid_y, "╭", ARROW_STYLE)
        elif coord_mid_y < min_row:
            for y in range(coord_mid_y + 1, min_row):
                c.set(merge_x, y, "│", ARROW_STYLE)
            c.set(merge_x, min_row, "╭", ARROW_STYLE)
            c.set(merge_x, coord_mid_y, "╰", ARROW_STYLE)
        # If coord_mid_y is within client_rows range, it's already connected

        # Horizontal line from coord right edge to auth server left edge
        coord_right = COORD_LEFT + COORD_WIDTH - 1
        auth_entry_y = AUTH_TOP + AUTH_HEIGHT // 2
        auth_left = AUTH_LEFT

        # The coord → auth arrow: go from coord box right edge to auth box left
        # Horizontal at the auth entry row
        for x in range(coord_right + 1, auth_left):
            c.set(x, auth_entry_y, "─", ARROW_STYLE)
        c.set(auth_left, auth_entry_y, "▶", ARROW_STYLE)

    # ------------------------------------------------------------------
    # Auth Server → Active Directory curved arrow
    # ------------------------------------------------------------------

    def _draw_auth_to_ad_arrow(self, c: CharCanvas) -> None:
        """Long curved arrow from Auth Server top, over the diagram, to Active Directory."""
        # Auth Server top-center
        auth_mid_x = AUTH_LEFT + AUTH_WIDTH // 2
        auth_top_y = AUTH_TOP

        # Active Directory entry: content row inside main office
        # AD box is at MAIN_OFFICE_TOP + 1, content row = MAIN_OFFICE_TOP + 2
        ad_y = MAIN_OFFICE_TOP + 2
        # AD box right border is at SITE_LEFT + INNER_BOX_LEFT_OFFSET + INNER_BOX_WIDTH - 1
        ad_right_x = SITE_LEFT + INNER_BOX_LEFT_OFFSET + INNER_BOX_WIDTH - 1

        # The arrow goes:
        # 1. Up from auth_top_y to row 0 (top of canvas)
        # 2. Left along row 0 from auth_mid_x to just past site right
        # 3. Down from row 0 to ad_y at a column near ad_right_x
        # 4. Left to ad_right_x with arrowhead ◀

        arc_y = 0   # top routing row
        arc_down_x = ad_right_x + 2  # column where we descend

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
        # Arrowhead pointing left into AD box right border area
        c.set(ad_right_x, ad_y, "◀", ARROW_STYLE)


if __name__ == "__main__":
    class _Demo(App):
        BINDINGS = [("q", "quit", "Quit")]
        CSS = "ArchitectureDemo { width: 1fr; height: 1fr; }"

        def compose(self) -> ComposeResult:
            yield ArchitectureDemo()

    _Demo().run()
