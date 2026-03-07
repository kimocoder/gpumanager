import importlib.util
import sys
import types
from pathlib import Path


def _make_fake_tk():
    """Create a fake tkinter module that records created widget types.

    The real GUI lazily imports ``tkinter`` inside ``get_app_class()``; we
    insert this fake module into sys.modules before loading to ensure the
    GUI defines its local helper wrappers in a deterministic, headless-safe
    way.
    """
    fake = types.ModuleType("tkinter")
    created = []

    class Label:
        def __init__(self, parent=None, **kw):
            self.parent = parent
            self.kw = kw
            created.append(("Label", parent, kw))

        def pack(self, **_):
            return None

        def grid(self, **_):
            return None

        def configure(self, **_):
            return None

        def cget(self, key):
            return self.kw.get(key)

    class Frame:
        def __init__(self, parent=None, **kw):
            self.parent = parent
            self.kw = kw
            created.append(("Frame", parent, kw))

        def pack(self, **_):
            return None

        def grid(self, **_):
            return None

        def configure(self, **_):
            return None

        def cget(self, key):
            return self.kw.get(key)

    class Button:
        def __init__(self, parent=None, **kw):
            self.parent = parent
            self.kw = kw
            created.append(("Button", parent, kw))

        def pack(self, **_):
            return None

        def cget(self, key):
            return self.kw.get(key)

    class Checkbutton:
        def __init__(self, parent=None, **kw):
            self.parent = parent
            self.kw = kw
            created.append(("Checkbutton", parent, kw))

        def pack(self, **_):
            return None

        def cget(self, key):
            return self.kw.get(key)

    # Minimal Tk base class so GUI can define subclass tk.Tk
    class Tk:
        def __init__(self, *args, **kwargs):
            pass

        def mainloop(self):
            pass

        def after(self, ms, func):
            return None

        def after_cancel(self, id_):
            return None

        def protocol(self, *args, **kwargs):
            return None

    fake.Label = Label
    fake.Frame = Frame
    fake.Button = Button
    fake.Checkbutton = Checkbutton
    fake.Tk = Tk
    # names imported by gui.py
    fake.ttk = types.SimpleNamespace()
    fake.messagebox = types.SimpleNamespace()
    fake.scrolledtext = types.SimpleNamespace()
    fake.filedialog = types.SimpleNamespace()
    fake._created = created
    return fake


def _extract_helper_from_class(cls, helper_name):
    """Scan the function objects on *cls* to find a closure cell that
    contains the helper named *helper_name* and return that object.
    """
    for obj in cls.__dict__.values():
        if not callable(obj):
            continue
        # functions defined in the class keep references to outer helpers
        closure = getattr(obj, "__closure__", None)
        if not closure:
            continue
        for cell in closure:
            content = cell.cell_contents
            if getattr(content, "__name__", None) == helper_name:
                return content
    return None


def test_local_wrappers_match_gui_widgets():
    # Ensure project root is on PYTHONPATH
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    # Prepare a fake tkinter module so GUI builds its helpers without a real X
    fake_tk = _make_fake_tk()
    # Overwrite any existing tkinter entry so the GUI module's lazy import
    # uses our headless-safe fake implementation.
    sys.modules["tkinter"] = fake_tk

    # Load the workspace copy of nvidia_manager/gui.py
    gui_path = root / "nvidia_manager" / "gui.py"
    spec = importlib.util.spec_from_file_location("nvidia_manager.gui", str(gui_path))
    gui = types.ModuleType(spec.name)
    loader = spec.loader
    assert loader is not None
    loader.exec_module(gui)

    # Ensure the GUI class is created (this defines the local helpers)
    cls = gui.get_app_class()
    assert cls is not None

    import nvidia_manager.gui_widgets as gw  # use the workspace module

    # Create mock parent widgets with cget() support
    def make_mock_parent():
        return fake_tk.Frame(bg="#1a1c22")

    # Helpers to check
    helpers = [
        ("_make_section_header", (make_mock_parent(), "section"), False),
        ("_make_section_label", (make_mock_parent(), "label"), False),
        ("_make_card", (make_mock_parent(),), True),
        ("_make_metric", (make_mock_parent(), "metric"), True),
        ("_make_toggle_row", (make_mock_parent(), "toggle", object()), False),
    ]

    for name, args, returns_widget in helpers:
        helper = _extract_helper_from_class(cls, name)
        assert helper is not None, f"Could not find helper {name} in class closures"

        # Clear recorded creations
        fake_tk._created.clear()

        # Call the helper (these wrappers call gw.* under the hood)
        res_helper = helper(*args)

        created_by_helper = list(fake_tk._created)

        # Clear and call the underlying gui_widgets implementation directly
        fake_tk._created.clear()
        if name == "_make_section_header":
            res_direct = gw.make_section_header(fake_tk, *args)
        elif name == "_make_section_label":
            res_direct = gw.make_section_label(fake_tk, *args)
        elif name == "_make_card":
            res_direct = gw.make_card(fake_tk, *args)
        elif name == "_make_metric":
            # gw.make_metric returns the value label; match that
            res_direct = gw.make_metric(fake_tk, *args)
        elif name == "_make_toggle_row":
            # toggle row is a small inline builder in gui.py — emulate the
            # effect by creating similar widgets via fake tk directly to
            # compare created types
            parent, label, var = args
            # Build what the helper builds using fake tk primitives
            # A Frame, Label and a Checkbutton should be produced.
            fake_frame = fake_tk.Frame(parent)
            fake_label = fake_tk.Label(fake_frame, text=label)
            fake_cb = fake_tk.Checkbutton(fake_frame, variable=var)
            res_direct = None
        else:
            res_direct = None

        created_by_direct = list(fake_tk._created)

        # Basic asserts: both approaches should record widget creations of
        # the same kinds in the same order (we don't assert exact kw args
        # for everything), but for card/metric/toggle helpers assert that
        # key styling kwargs are forwarded correctly.
        assert len(created_by_helper) > 0, f"helper {name} did not create widgets"
        assert len(created_by_direct) > 0, f"direct gw call for {name} did not create widgets"
        # Compare the sequence of widget types
        types_helper = [t for (t, *_ ) in created_by_helper]
        types_direct = [t for (t, *_ ) in created_by_direct]
        assert types_helper == types_direct, f"Widget types differ for {name}: {types_helper} != {types_direct}"

        # Additional strict checks for styling kwargs
        import nvidia_manager.gui_helpers as gui_helpers
        if name == "_make_card":
            # The card helper should create a Frame whose 'bg' kw is gui.BG_CARD
            # and whose highlightbackground equals gui.BORDER (border_color).
            frame_entries = [e for e in created_by_helper if e[0] == "Frame"]
            assert frame_entries, "_make_card did not create a Frame"
            _, _, kw = frame_entries[0]
            assert kw.get("bg") == gui_helpers.BG_CARD, (
                f"bg for card Frame expected {gui_helpers.BG_CARD}, "
                f"got {kw.get('bg')}"
            )
            assert kw.get("highlightbackground") == gui_helpers.BORDER, (
                f"card Frame highlightbackground expected {gui_helpers.BORDER}, "
                f"got {kw.get('highlightbackground')}"
            )
        if name == "_make_metric":
            # Metric delegates to make_card internally — verify the card Frame
            # used the configured BG_CARD and BORDER.
            frame_entries = [e for e in created_by_helper if e[0] == "Frame"]
            assert frame_entries, "_make_metric did not create a Frame card"
            _, _, kw = frame_entries[0]
            assert kw.get("bg") == gui_helpers.BG_CARD, (
                f"metric card bg expected {gui_helpers.BG_CARD}, "
                f"got {kw.get('bg')}"
            )
            assert kw.get("highlightbackground") == gui_helpers.BORDER, (
                f"metric card highlightbackground expected {gui_helpers.BORDER}, "
                f"got {kw.get('highlightbackground')}"
            )
        if name == "_make_toggle_row":
            # Toggle should create a Checkbutton with bg=BG_CARD and fg=NVIDIA_GREEN
            cb_entries = [e for e in created_by_helper if e[0] == "Checkbutton"]
            assert cb_entries, "_make_toggle_row did not create a Checkbutton"
            _, _, kw = cb_entries[0]
            assert kw.get("bg") == gui_helpers.BG_CARD, (
                f"toggle Checkbutton bg expected {gui_helpers.BG_CARD}, "
                f"got {kw.get('bg')}"
            )
            assert kw.get("fg") == gui_helpers.NVIDIA_GREEN, (
                f"toggle Checkbutton fg expected {gui_helpers.NVIDIA_GREEN}, "
                f"got {kw.get('fg')}"
            )
            assert kw.get("selectcolor") == gui_helpers.BG_INPUT, (
                f"toggle Checkbutton selectcolor expected {gui_helpers.BG_INPUT}, got {kw.get('selectcolor')}"
            )

        # If a widget object is returned, ensure both sides return the same
        # widget class (fake classes are identical), or both return None.
        # Note: GUI helpers may return widgets even when gui_widgets returns None
        if returns_widget:
            assert type(res_helper) == type(res_direct)
        else:
            # For non-widget-returning helpers, we just verify the widgets were created
            # The GUI helper may return a widget while gui_widgets returns None
            pass

    # Cleanup our fake tkinter insertion
    try:
        del sys.modules["tkinter"]
    except Exception:
        pass
