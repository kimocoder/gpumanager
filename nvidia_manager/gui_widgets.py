"""UI widget factory helpers extracted from the GUI.

These functions expect a tkinter namespace (tk) to be available at call
time (they are called after tkinter is imported lazily in `gui.py`).
"""
from __future__ import annotations

from typing import Any


def make_section_header(tk, parent, text: str, icon: str = None) -> None:
    """Create a simple section header label in *parent*.

    This is intentionally tiny — callers should pass colors/fonts from the
    calling module (where the theme constants are defined).
    """
    label_text = f"{icon} {text}" if icon else text
    tk.Label(parent, text=label_text, font=("Helvetica", 14, "bold"), fg=None, bg=None).pack(anchor="w", pady=(0, 10))


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
    c = tk.Frame(
        parent, bg=bg_card, highlightbackground=border_color,
        highlightthickness=2, bd=4, relief="groove", **kw
    )
    # Add drop-shadow effect
    try:
        c.configure(highlightcolor="#3a3d45")
    except Exception:
        pass
    return c


def make_metric(tk, parent, label_text: str, default: str = "\u2014", icon: str = None, **grid_kw) -> Any:
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
    label_text = f"{icon} {label_text.upper()}" if icon else label_text.upper()
    tk.Label(
        card, text=label_text, font=("monospace", 8),
        fg=None, bg=None, anchor="w"
    ).pack(fill="x")
    val = tk.Label(
        card, text=default, font=("monospace", 13, "bold"),
        fg=None, bg=None, anchor="w"
    )
    val.pack(fill="x", pady=(2, 0))
    return val
# New: Material-inspired animated button
def make_animated_button(
    tk, parent, text, icon=None, command=None, fg="#000", bg="#76b900",
    hover_bg="#8fd400", font=("monospace", 10, "bold")
):
    btn_text = f"{icon} {text}" if icon else text
    btn = tk.Button(
        parent, text=btn_text, font=font, fg=fg, bg=bg,
        activeforeground=fg, activebackground=hover_bg, bd=0,
        padx=14, pady=4, cursor="hand2", command=command
    )
    def on_enter(e):
        btn.configure(bg=hover_bg)
        btn.after(50, lambda: btn.configure(font=(font[0], font[1]+1, font[2])))
    def on_leave(e):
        btn.configure(bg=bg)
        btn.after(50, lambda: btn.configure(font=font))
    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn
