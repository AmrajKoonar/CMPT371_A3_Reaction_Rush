"""
components.py — Reusable, theme-aware Tkinter widgets.

Every factory takes a *palette* dict (see :mod:`theme`) so widgets pick up the
active theme's colours. Buttons include hover states for a modern feel.

These helpers keep the screen builders in :mod:`screens` short and consistent.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict, Optional

from . import theme as T


# ----------------------------------------------------------------------------
# Buttons
# ----------------------------------------------------------------------------

def button(
    parent: tk.Widget,
    text: str,
    command: Callable,
    palette: Dict[str, str],
    kind: str = "primary",
    width: int = 18,
) -> tk.Button:
    """
    Create a styled button with a hover state.

    *kind* selects the colour role: ``primary``, ``success``, ``danger``,
    or ``ghost`` (subtle/secondary).
    """
    role = {
        "primary": (palette["primary"], palette["primary_dim"], "#ffffff"),
        "success": (palette["success"], palette["primary_dim"], "#ffffff"),
        "danger":  (palette["danger"],  "#b23327", "#ffffff"),
        "ghost":   (palette["surface_alt"], palette["elevated"], palette["text"]),
    }.get(kind, (palette["primary"], palette["primary_dim"], "#ffffff"))

    base, hover, fg = role

    btn = tk.Button(
        parent, text=text, command=command,
        font=T.font(13, True), width=width,
        bg=base, fg=fg,
        activebackground=hover, activeforeground=fg,
        relief="flat", bd=0, padx=10, pady=8,
        cursor="hand2", highlightthickness=0,
    )

    # Hover states (skip while disabled).
    def _enter(_e: object) -> None:
        if str(btn["state"]) != "disabled":
            btn.config(bg=hover)

    def _leave(_e: object) -> None:
        if str(btn["state"]) != "disabled":
            btn.config(bg=base)

    btn.bind("<Enter>", _enter)
    btn.bind("<Leave>", _leave)
    return btn


# ----------------------------------------------------------------------------
# Cards / panels
# ----------------------------------------------------------------------------

def card(
    parent: tk.Widget,
    palette: Dict[str, str],
    bg: Optional[str] = None,
    padx: int = 22,
    pady: int = 22,
) -> tk.Frame:
    """
    Create a bordered card frame. The returned frame has an ``inner``
    attribute (a padded child frame) for placing content.
    """
    bg = bg or palette["surface"]
    outer = tk.Frame(parent, bg=bg, bd=0,
                     highlightthickness=1, highlightbackground=palette["stroke"])
    inner = tk.Frame(outer, bg=bg)
    inner.pack(fill=tk.BOTH, expand=True, padx=padx, pady=pady)
    outer.inner = inner  # type: ignore[attr-defined]
    return outer


def inner_of(frame: tk.Frame) -> tk.Frame:
    """Return a card's padded inner frame (or the frame itself)."""
    return getattr(frame, "inner", frame)


# ----------------------------------------------------------------------------
# Labels
# ----------------------------------------------------------------------------

def label(
    parent: tk.Widget,
    text: str,
    palette: Dict[str, str],
    size: int = 12,
    bold: bool = False,
    muted: bool = False,
    fg: Optional[str] = None,
    bg: Optional[str] = None,
) -> tk.Label:
    """Create a themed label."""
    colour = fg or (palette["text_muted"] if muted else palette["text"])
    return tk.Label(
        parent, text=text, font=T.font(size, bold),
        fg=colour, bg=bg or parent.cget("bg"),
    )


def title(parent: tk.Widget, text: str, palette: Dict[str, str],
          bg: Optional[str] = None) -> tk.Label:
    return label(parent, text, palette, size=28, bold=True, bg=bg)


def heading(parent: tk.Widget, text: str, palette: Dict[str, str],
            bg: Optional[str] = None) -> tk.Label:
    return label(parent, text, palette, size=16, bold=True, bg=bg)


# ----------------------------------------------------------------------------
# Entries
# ----------------------------------------------------------------------------

def entry(
    parent: tk.Widget,
    palette: Dict[str, str],
    show: Optional[str] = None,
    width: int = 24,
) -> tk.Entry:
    """Create a themed text entry."""
    e = tk.Entry(
        parent, font=T.font(13), width=width,
        bg="#f8fafc" if palette is T.LIGHT else "#eef1fb",
        fg="#0f172a", insertbackground="#0f172a",
        relief="flat", bd=0,
        highlightthickness=2, highlightbackground=palette["stroke"],
        highlightcolor=palette["primary"],
    )
    if show:
        e.config(show=show)
    return e


def option_menu(
    parent: tk.Widget,
    variable: tk.StringVar,
    options: list,
    palette: Dict[str, str],
) -> tk.OptionMenu:
    """Create a themed dropdown menu."""
    om = tk.OptionMenu(parent, variable, *options)
    om.config(
        font=T.font(12), bg=palette["surface_alt"], fg=palette["text"],
        activebackground=palette["elevated"], activeforeground=palette["text"],
        relief="flat", highlightthickness=1,
        highlightbackground=palette["stroke"], bd=0, cursor="hand2",
    )
    menu = om["menu"]
    menu.config(bg=palette["surface"], fg=palette["text"],
                activebackground=palette["primary"], activeforeground="#ffffff")
    return om


# ----------------------------------------------------------------------------
# Badges / pills
# ----------------------------------------------------------------------------

def pill(
    parent: tk.Widget,
    text: str,
    palette: Dict[str, str],
    colour: Optional[str] = None,
) -> tk.Label:
    """A small rounded-ish status label (pill)."""
    return tk.Label(
        parent, text=text, font=T.font(10, True),
        fg="#ffffff", bg=colour or palette["primary"],
        padx=8, pady=2,
    )


def latency_colour(palette: Dict[str, str], latency_ms: float) -> str:
    """Pick a colour representing connection quality."""
    if latency_ms <= 0:
        return palette["text_muted"]
    if latency_ms < 60:
        return palette["success"]
    if latency_ms < 150:
        return palette["warning"]
    return palette["danger"]
