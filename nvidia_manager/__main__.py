"""Allow the package to be run directly with ``python3 -m nvidia_manager``."""

from .cli import main as _main


if __name__ == "__main__":
    # Entrypoint wrapper: keep the small bootstrap file unintrusive for
    # packaging while delegating to the typed cli.main implementation.
    raise SystemExit(_main())
