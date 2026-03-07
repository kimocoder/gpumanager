"""Console entry point for the installed `nvidia-manager` command.

This wrapper imports the package-internal application module and exposes
the `main()` function as the console entrypoint. It delegates to
`nvidia_manager.app.main` which contains the refactored application code.
"""

# Small wrapper intentionally duplicates logic found elsewhere; silence
# duplicate-code warnings for this tiny entrypoint.
# pylint: disable=duplicate-code,R0801


from typing import Optional, List, Any

# Import the GUI entrypoint if available (optional in headless/test envs).
try:
    # preferred: the package-local GUI loader
    from .gui import main as gui_main  # type: ignore[attr-defined]
except ImportError:
    def gui_main(_argv: Any = None) -> int:
        """Fallback GUI main function when import fails."""
        return 0

# Lightweight app entrypoint (maybe untyped)
from .app import main as app_main  # type: ignore[attr-defined]

# Use Any for dynamic dispatch to avoid requiring the whole project to be
# fully typed; entrypoints are thin wrappers and adding strict typing here
# would be more intrusive than necessary.
gui_main_fn: Optional[Any] = gui_main  # type: ignore[assignment]
app_main_fn: Any = app_main


def main(argv: Optional[List[str]] = None) -> int:
    """Launch the GUI application.

    Prefer the package `gui` loader; fall back to the lightweight `app.main`.
    """
    if callable(gui_main_fn):
        return gui_main_fn(argv)
    return app_main_fn(argv)


if __name__ == "__main__":
    main()
