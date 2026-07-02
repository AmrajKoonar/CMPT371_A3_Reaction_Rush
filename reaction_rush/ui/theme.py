"""
theme.py — Colour system and fonts for the Tkinter client.

Two palettes (dark + light) share the same set of semantic keys so the rest
of the UI never hard-codes a hex value. Switch themes by swapping the active
palette; every component reads colours from the palette dict it is given.

Semantic colour keys
--------------------
bg            window background
surface       card background
surface_alt   alternating row / secondary card
elevated      raised element background
stroke        subtle border colour
primary       main accent (buttons, highlights)
primary_dim   pressed/hover accent
success       positive state (ready, correct)
warning       caution (waiting, penalty-ish)
danger        negative (errors, quit)
text          primary text
text_muted    secondary text
gold          leaderboard / winner accent
red/green/orange  reaction-screen phase colours
"""

from __future__ import annotations

from typing import Dict

# ----------------------------------------------------------------------------
# Palettes
# ----------------------------------------------------------------------------

DARK: Dict[str, str] = {
    "bg":          "#0f1220",
    "surface":     "#171a2b",
    "surface_alt": "#1f2438",
    "elevated":    "#232a42",
    "stroke":      "#313a5c",
    "primary":     "#4f8cff",
    "primary_dim": "#3b6fd6",
    "success":     "#2ecc71",
    "warning":     "#f39c12",
    "danger":      "#e74c3c",
    "text":        "#f5f7ff",
    "text_muted":  "#9aa6c4",
    "gold":        "#f1c40f",
    "red":         "#e74c3c",
    "green":       "#27ae60",
    "orange":      "#e67e22",
}

LIGHT: Dict[str, str] = {
    "bg":          "#eef1f8",
    "surface":     "#ffffff",
    "surface_alt": "#f1f4fb",
    "elevated":    "#ffffff",
    "stroke":      "#cfd6e6",
    "primary":     "#2f6bff",
    "primary_dim": "#2455cc",
    "success":     "#1e9e57",
    "warning":     "#c77f0a",
    "danger":      "#d0392b",
    "text":        "#141a2e",
    "text_muted":  "#5b667f",
    "gold":        "#b8860b",
    "red":         "#e74c3c",
    "green":       "#27ae60",
    "orange":      "#e67e22",
}

_PALETTES = {"dark": DARK, "light": LIGHT}


def get_palette(theme_name: str) -> Dict[str, str]:
    """Return the palette dict for *theme_name* (defaults to dark)."""
    return dict(_PALETTES.get(theme_name, DARK))


# ----------------------------------------------------------------------------
# Fonts (family kept generic for cross-platform consistency)
# ----------------------------------------------------------------------------

FONT_FAMILY = "Helvetica"


def font(size: int, bold: bool = False) -> tuple:
    """Return a Tkinter font tuple with the app font family."""
    return (FONT_FAMILY, size, "bold" if bold else "normal")


# Common named sizes
TITLE      = font(30, True)
SUBTITLE   = font(14, False)
HEADING    = font(18, True)
BODY       = font(12, False)
BODY_BOLD  = font(12, True)
SMALL      = font(10, False)
HUGE       = font(52, True)
