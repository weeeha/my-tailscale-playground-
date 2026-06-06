"""ArchitectureDemo widget smoke tests."""

from __future__ import annotations

from tailtop.widgets.architecture_demo import ArchitectureDemo


def test_widget_instantiates() -> None:
    demo = ArchitectureDemo()
    assert demo is not None


def test_render_includes_all_major_labels() -> None:
    demo = ArchitectureDemo()
    rendered = demo.render()
    plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
    assert "Main Office" in plain
    assert "Remote User" in plain
    assert "Branch Office" in plain
    assert "Tailscale Client" in plain
    assert "Active Directory" in plain
    assert "Coordination Server" in plain
    assert "Auth Server" in plain
    assert "Office 365" in plain


def test_render_draws_site_box_borders() -> None:
    demo = ArchitectureDemo()
    plain = demo.render().plain
    # Should contain rounded-corner glyphs for site boxes.
    assert "╭" in plain
    assert "╮" in plain
    assert "╰" in plain
    assert "╯" in plain


def test_render_draws_inner_box_borders() -> None:
    demo = ArchitectureDemo()
    plain = demo.render().plain
    # Should contain square-corner glyphs for inner entry boxes.
    assert "┌" in plain
    assert "└" in plain


def test_render_includes_arrows() -> None:
    demo = ArchitectureDemo()
    plain = demo.render().plain
    # Right-pointing arrowhead for client→coord and coord→auth.
    assert "▶" in plain
    # Left-pointing for auth→AD.
    assert "◀" in plain
