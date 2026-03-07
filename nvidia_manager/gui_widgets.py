"""UI widget factory helpers extracted from the GUI.

These functions expect a tkinter namespace (tk) to be available at call
time (they are called after tkinter is imported lazily in `gui.py`).
"""
from __future__ import annotations

from typing import Any


def make_section_header(tk, parent, text: str) -> None:
    """Create a simple section header label in *parent*.

    This is intentionally tiny — callers should pass colors/fonts from the
    calling module (where the theme constants are defined).
    """
    tk.Label(parent, text=text, font=("Helvetica", 14, "bold"), fg=None, bg=None).pack(anchor="w", pady=(0, 10))


def make_section_label(tk, parent, text: str) -> None:
    """Create a small monospace label used as section labels."""
    tk.Label(parent, text=text, font=("monospace", 8, "bold"), fg=None, bg=None, anchor="w").pack(
        fill="x", pady=(10, 4)
    )


def make_card(tk, parent, **kw: Any):
    """Create a framed card container.

    Expected kwargs: border_color, bg_card and any other Frame kwargs.
    """
    border_color = kw.pop("border_color", "#2a2d35")
    bg_card = kw.pop("bg_card", "#1a1c22")
    c = tk.Frame(parent, bg=bg_card, highlightbackground=border_color, highlightthickness=1, **kw)
    return c


def make_metric(tk, parent, label_text: str, default: str = "\u2014", **grid_kw) -> Any:
    """Create a small metric card and return the label widget used for the
    metric value.

    Supported grid kwargs: row, col; supported style kwargs: border_color, bg_card.
    """
    card = make_card(
        tk,
        parent,
        border_color=grid_kw.get("border_color", "#2a2d35"),
        bg_card=grid_kw.get("bg_card", "#1a1c22"),
    )
    row = grid_kw.get("row", 0)
    col = grid_kw.get("col", 0)
    card.grid(row=row, column=col, padx=3, pady=3, sticky="nsew")
    tk.Label(card, text=label_text.upper(), font=("monospace", 8), fg=None, bg=None, anchor="w").pack(fill="x")
    val = tk.Label(card, text=default, font=("monospace", 13, "bold"), fg=None, bg=None, anchor="w")
    val.pack(fill="x", pady=(2, 0))
    return val
