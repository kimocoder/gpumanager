"""nvidia_manager package version and exports."""

__all__ = ["__version__", "gui_detect", "gui_parsers", "gui_widgets"]
__version__ = "0.1.0"
import importlib
gui_detect = importlib.import_module(".gui_detect", __name__)
gui_parsers = importlib.import_module(".gui_parsers", __name__)
gui_widgets = importlib.import_module(".gui_widgets", __name__)
