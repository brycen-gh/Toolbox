import customtkinter as ctk
import yaml
import sys
import shutil
import subprocess
from pathlib import Path
import copy
import fnmatch
import base64
import os
import queue
import threading
import tempfile
import time
import faulthandler
import re
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageDraw, ImageOps

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    Fernet = None
    InvalidToken = Exception
    hashes = None
    PBKDF2HMAC = None

from execution_engines.main import ExecutionEngine
from execution_engines.capture import capture_interfaces
from execution_engines.image_catalog import image_size
from execution_engines.settings import CONTAINER_VARIABLE_FILES
from execution_engines.settings import container_variables_path, load_variables, save_variables as save_variable_files
from execution_engines.runtime import application_dir, restart_command
from execution_engines.capabilities import action_requirements
from ui.home import ToolboxHome
from ui.pages import CollectionPage
from ui.options import HomeOptions
from execution_engines.domains import normalize_domain, save_domain

WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 750
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 600
SIDEBAR_WIDTH = 350
SIDEBAR_COLLAPSED_WIDTH = 60
SEARCH_HEIGHT = 34
MENU_BUTTON_HEIGHT = 32

APP_DIR = application_dir()
MENUS_DIR = APP_DIR / "menus"
VARIABLES_DIR = APP_DIR / "variables"
UI_SETTINGS_FILE = VARIABLES_DIR / "ui.yaml"
HOME_YAML = MENUS_DIR / "home.yaml"
ICONS_DIR = APP_DIR / "assets" / "icons"
MENU_ICON_SIZE = (20, 20)
SEARCH_ICON_SIZE = (18, 18)
CONTROL_ICON_SIZE = (18, 18)
SURFACE = ("#ffffff", "#1c2533")
PANEL_BORDER = ("#dfe6ee", "#2c3a4e")
MUTED = ("#52647b", "#a5b4c8")

REMOTE_TROUBLESHOOTING_ACTIONS = {
    "troubleshoot_docker",
    "troubleshoot_security_onion",
}

THEME_CHOICES = {
    "Blue": "blue",
    "Green": "green",
    "Dark Blue": "dark-blue",
}
DEFAULT_UI_SETTINGS = {
    "theme": "Blue",
    "appearance": "Dark",
    "home_background": "",
    "hidden_menu_items": {},
}


# Hide selected paths and their descendants without modifying the source menu.
def visible_menu_items(items, hidden, parents=()):
    visible = []
    for item in items:
        path = (*parents, str(item.get("label", "Untitled")))
        protected = item.get("special") == "menu_visibility" or any(
            child.get("special") == "menu_visibility" for child in item.get("children", []))
        if " / ".join(path) in hidden and not protected:
            continue
        child = dict(item)
        if "children" in child:
            child["children"] = visible_menu_items(child["children"], hidden, path)
        visible.append(child)
    return visible


# Merge only this service's edits, refusing to overwrite concurrent changes.
def save_container_settings(path, service, original, updates):
    if set(updates) != set(original) or any(not key.startswith(service + "_") for key in updates):
        raise ValueError("Only the selected container's settings may be edited")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    values = document["Variables"]
    if any(values.get(key) != value for key, value in original.items()):
        raise ValueError("These settings changed on disk. Reopen the editor before saving.")
    values.update(updates)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(document, stream, sort_keys=False, allow_unicode=True)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


# Load saved appearance choices, falling back to supported defaults.
def load_ui_settings():
    settings = dict(DEFAULT_UI_SETTINGS)
    if UI_SETTINGS_FILE.is_file():
        try:
            loaded = yaml.safe_load(UI_SETTINGS_FILE.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                settings.update({key: loaded[key] for key in settings if key in loaded})
        except (OSError, yaml.YAMLError):
            pass
    if settings["theme"] not in THEME_CHOICES:
        settings["theme"] = DEFAULT_UI_SETTINGS["theme"]
    if settings["appearance"] not in {"Light", "Dark", "System"}:
        settings["appearance"] = DEFAULT_UI_SETTINGS["appearance"]
    hidden = settings.get("hidden_menu_items")
    settings["hidden_menu_items"] = {
        key: [label for label in labels if isinstance(label, str)]
        for key, labels in hidden.items() if isinstance(key, str) and isinstance(labels, list)
    } if isinstance(hidden, dict) else {}
    return settings


UI_SETTINGS = load_ui_settings()
ctk.set_appearance_mode(UI_SETTINGS["appearance"])
ctk.set_default_color_theme(THEME_CHOICES[UI_SETTINGS["theme"]])

class YamlMenuApp(ctk.CTk):
    # Initialize the application widgets and session state.
    def __init__(self):
        super().__init__()
        self.withdraw()

        self.title("Toolbox")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        MENUS_DIR.mkdir(exist_ok=True)
        VARIABLES_DIR.mkdir(exist_ok=True)

        self.yaml_map = self.find_yaml_files()
        self.available_titles = list(self.yaml_map.keys())

        self.current_title = None
        self.current_yaml = None          # full path to the currently loaded menu YAML
        self.current_variables_file = None
        self.menu_data = {"title": "Home", "menu": []}

        self.current_item = None
        self.sidebar_expanded = True
        self.sidebar_width = SIDEBAR_WIDTH
        self.expanded_items = set()
        self.execution_engine = ExecutionEngine(base_dir=APP_DIR)
        self.action_running = False
        self.action_events = queue.Queue()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.icon_cache = {}
        self.ui_settings = dict(UI_SETTINGS)
        self.home_background_image = None
        self.background_resize_job = None
        self.background_render_key = None
        self.background_source_key = None
        self.background_source = None

        # Variables that belong to the *currently loaded* YAML
        self.variables = {}
        self.default_variables = {}       # snapshot when the YAML was loaded

        # ==================== LAYOUT ====================
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---------- Sidebar ----------
        self.sidebar = ctk.CTkFrame(self, width=self.sidebar_width, corner_radius=0,
                                    fg_color=("#eaf0f6", "#17202d"))
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(4, weight=1)

        self.toggle_btn = ctk.CTkButton(
            self.sidebar, text="", image=self.get_icon("menu", CONTROL_ICON_SIZE),
            width=40, height=40,
            font=ctk.CTkFont(size=18), fg_color="transparent",
            hover_color=("gray70", "gray30"), command=self.toggle_sidebar
        )
        self.toggle_btn.grid(row=0, column=0, padx=10, pady=(15, 5), sticky="w")
        self.brand_label = ctk.CTkLabel(self.sidebar, text="TOOLBOX / WORKSPACE",
                                        font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED)
        self.brand_label.grid(row=0, column=0, padx=22, pady=(15, 5), sticky="e")

        self.home_btn = ctk.CTkButton(
            self.sidebar,
            text="Home",
            image=self.get_icon("home"),
            compound="left",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36,
            fg_color="#267e9b",
            hover_color="#1e667e",
            command=self.open_home
        )
        self.home_btn.grid(row=1, column=0, padx=15, pady=(5, 8), sticky="ew")

        self.yaml_dropdown = ctk.CTkOptionMenu(
            self.sidebar,
            values=self.available_titles or ["No YAML files found"],
            command=self.on_yaml_selected,
            font=ctk.CTkFont(size=13),
            width=240,
            height=32
        )

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self.on_search_changed)
        self.search_frame = ctk.CTkFrame(
            self.sidebar,
            height=SEARCH_HEIGHT,
            corner_radius=6,
            fg_color=("gray86", "gray24"),
        )
        self.search_frame.grid(row=3, column=0, padx=15, pady=(0, 4), sticky="ew")
        self.search_frame.grid_columnconfigure(1, weight=1)
        self.search_icon = ctk.CTkLabel(
            self.search_frame,
            text="Search",
            image=self.get_icon("search", SEARCH_ICON_SIZE),
            compound="left", font=ctk.CTkFont(size=12), text_color=MUTED,
            width=80,
        )
        self.search_icon.grid(row=0, column=0, padx=(6, 0), pady=2)
        self.search_entry = ctk.CTkEntry(
            self.search_frame,
            textvariable=self.search_var,
            height=SEARCH_HEIGHT,
            placeholder_text="Search tools (* and ? supported)",
            border_width=0,
            fg_color="transparent",
        )
        self.search_entry.grid(row=0, column=1, padx=(2, 6), pady=2, sticky="ew")

        self.menu_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.menu_frame.grid(row=4, column=0, sticky="nsew", padx=10, pady=10)
        self.menu_frame.grid_columnconfigure(0, weight=1)

        # ---------- Main content ----------
        self.content_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=("#f3f6fa", "#111923"))
        self.content_frame.grid(row=0, column=1, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

        self.normal_view = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.variables_view = ctk.CTkFrame(self.content_frame, fg_color="transparent")

        self.build_normal_view()
        self.build_variables_view()

        self.copy_output_button = ctk.CTkButton(
            self.content_frame, text="Copy Output", width=120, height=34,
            fg_color=("#e1ebf4", "#293e56"), text_color=("#1a314b", "#edf5ff"),
            command=self.copy_action_output,
        )
        self.copy_output_button.grid(row=1, column=0, padx=30, pady=(0, 15), sticky="e")

        self.show_normal_view()
        self.open_home()
        self.center_on_screen()
        # CustomTkinter applies the Windows titlebar at mainloop startup and
        # withdraws the window again. Reveal it after that initialization.
        self.after_idle(self.deiconify)
        self.bind("<Control-Shift-R>", self.resync_window, add="+")
        self.bind("<Control-Shift-r>", self.resync_window, add="+")
        if sys.platform.startswith("linux") and (os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP")):
            self.wsl_resize_job = None
            self.wsl_last_size = None
            self.wsl_normal_geometry = self.geometry()
            self.bind("<Configure>", self.schedule_wsl_resync, add="+")
        if os.environ.get("TOOLBOX_UI_DEBUG") == "1":
            self.start_ui_diagnostics()

    def start_ui_diagnostics(self):
        """Report event delivery and dump thread stacks if Tk stops processing."""
        last_tick = [time.monotonic()]
        closed = threading.Event()
        print(f"UI DEBUG: platform={sys.platform}, Tk={self.tk.call('info', 'patchlevel')}, "
              f"DISPLAY={os.environ.get('DISPLAY', '')}", flush=True)

        def tick():
            last_tick[0] = time.monotonic()
            print(f"UI heartbeat: geometry={self.geometry()} state={self.state()} "
                  f"grab={self.grab_current()}", flush=True)
            self.after(2000, tick)

        def watch():
            while not closed.wait(5):
                if time.monotonic() - last_tick[0] > 10:
                    print("UI DEBUG: event loop stalled; thread stacks follow", flush=True)
                    faulthandler.dump_traceback(all_threads=True)

        self.bind("<ButtonPress>", lambda event: print(
            f"UI click: widget={event.widget} screen=({event.x_root},{event.y_root})", flush=True), add="+")
        self.bind("<FocusIn>", lambda event: print(f"UI focus: {event.widget}", flush=True), add="+")
        self.bind("<Destroy>", lambda event: closed.set() if event.widget is self else None, add="+")
        self.after(1000, tick)
        threading.Thread(target=watch, name="ui-watchdog", daemon=True).start()

    def schedule_wsl_resync(self, event):
        """Refresh WSLg input mapping once after a window resize settles."""
        if event.widget is not self or getattr(self, "window_resync_pending", False):
            return
        if not self.attributes("-zoomed") and not self.attributes("-fullscreen") and self.state() == "normal":
            self.wsl_normal_geometry = self.geometry()
        size = (event.width, event.height)
        if self.wsl_last_size is None:
            self.wsl_last_size = size
            return
        if size == self.wsl_last_size:
            return
        if self.wsl_resize_job is not None:
            self.after_cancel(self.wsl_resize_job)
        self.wsl_resize_job = self.after(350, self.finish_wsl_resize)

    def finish_wsl_resize(self):
        self.wsl_resize_job = None
        size = (self.winfo_width(), self.winfo_height())
        if size == self.wsl_last_size:
            return
        self.wsl_last_size = size
        # Let the compositor finish maximize/fullscreen transitions without
        # remapping into a fitted normal window a moment later.
        if self.attributes("-zoomed") or self.attributes("-fullscreen"):
            return
        if self.grab_current() is not None:
            self.wsl_resize_job = self.after(350, self.finish_wsl_resize)
            self.wsl_last_size = None
            return
        self.resync_window()

    def resync_window(self, _event=None):
        """Remap the window to let the compositor refresh its input surface."""
        if getattr(self, "window_resync_pending", False) or self.grab_current() is not None:
            return
        self.window_resync_pending = True
        fullscreen = bool(self.attributes("-fullscreen"))
        state = self.state()
        zoomed = bool(self.attributes("-zoomed")) if sys.platform.startswith("linux") else state == "zoomed"
        placement = (getattr(self, "wsl_normal_geometry", None) or self.geometry()) if zoomed or fullscreen else self.geometry()
        fitted_wsl_window = False
        if (zoomed or fullscreen) and sys.platform.startswith("linux") and (os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP")):
            try:
                output = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=2, check=True).stdout
                monitors = []
                for line in output.splitlines():
                    match = re.search(r"(\d+)/\d+x(\d+)/\d+([+-]\d+)([+-]\d+)", line)
                    if match:
                        monitors.append(tuple(map(int, match.groups())))
                bounds = re.fullmatch(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", placement)
                if monitors and bounds:
                    width, height, x, y = map(int, bounds.groups())
                    cx, cy = x + width / 2, y + height / 2
                    def distance(monitor):
                        mw, mh, mx, my = monitor
                        return max(mx - cx, 0, cx - (mx + mw)) ** 2 + max(my - cy, 0, cy - (my + mh)) ** 2
                    mw, mh, mx, my = min(monitors, key=distance)
                    # Native WSLg maximization can apply the wrong monitor's
                    # dimensions. Fit a normal window to the selected output.
                    width, height = max(1, mw - 24), max(1, mh - 100)
                    self.minsize(min(MIN_WINDOW_WIDTH, width), min(MIN_WINDOW_HEIGHT, height))
                    placement = f"{width}x{height}{mx + 12:+d}{my + 40:+d}"
                    fitted_wsl_window = True
            except (OSError, subprocess.SubprocessError):
                pass
        self.withdraw()

        def restore():
            # WSLg may place a remapped window on its default monitor unless
            # its previous coordinates are supplied before showing it again.
            if sys.platform.startswith("linux"):
                if fullscreen:
                    self.attributes("-fullscreen", False)
                if zoomed:
                    self.attributes("-zoomed", False)
                self.geometry(placement)
            self.deiconify()
            def restore_state():
                if fitted_wsl_window:
                    # WSLg can discard the pre-map position and restore an
                    # old maximized origin. Apply the fitted coordinates after
                    # the normal window has actually been mapped as well.
                    self.geometry(placement)
                if fullscreen and not fitted_wsl_window:
                    self.attributes("-fullscreen", True)
                elif zoomed and not fitted_wsl_window:
                    if sys.platform.startswith("linux"):
                        self.attributes("-zoomed", True)
                    else:
                        self.state("zoomed")
                # Ignore Configure events emitted by remapping itself.
                def settled():
                    if hasattr(self, "wsl_last_size"):
                        self.wsl_last_size = (self.winfo_width(), self.winfo_height())
                    self.window_resync_pending = False
                self.after(350, settled)
            # Let WSLg place the normal window on the chosen monitor before
            # requesting maximization; an immediate request can use its default.
            self.after(150, restore_state)

        self.after(150, restore)

    # Set startup geometry before mapping, avoiding a second compositor resize.
    def center_on_screen(self):
        if self.state() not in {"normal", "withdrawn"} or self.attributes("-fullscreen"):
            return
        if sys.platform.startswith("linux") and self.attributes("-zoomed"):
            return
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        # Leave space for window decorations and the taskbar, particularly on WSLg.
        available_width = max(1, screen_width - 40)
        available_height = max(1, screen_height - 100)
        mapped = self.winfo_ismapped()
        width = min(self.winfo_width() if mapped else WINDOW_WIDTH, available_width)
        height = min(self.winfo_height() if mapped else WINDOW_HEIGHT, available_height)
        self.minsize(min(MIN_WINDOW_WIDTH, available_width), min(MIN_WINDOW_HEIGHT, available_height))
        x = max(20, (screen_width - width) // 2)
        y = max(40, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    # Load and cache a named PNG icon, with a safe default fallback.
    def get_icon(self, icon_name, size=MENU_ICON_SIZE):
        if not icon_name:
            return None

        cache_key = (str(icon_name), tuple(size))
        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]

        icon_path = ICONS_DIR / f"{icon_name}.png"
        if not icon_path.exists():
            icon_path = ICONS_DIR / "default.png"
        if not icon_path.exists():
            return None

        with Image.open(icon_path) as source:
            image = source.convert("RGBA").copy()
        icon = ctk.CTkImage(light_image=image, dark_image=image, size=size)
        self.icon_cache[cache_key] = icon
        return icon

    # ------------------------------------------------------------------
    # Home
    # ------------------------------------------------------------------
    # Clear the active menu and display the Home page.
    def open_home(self):
        if self.action_running:
            return
        self.current_title = None
        self.current_yaml = None
        self.current_variables_file = None
        self.menu_data = {"title": "Home", "menu": []}
        self.expanded_items.clear()
        self.current_item = None
        self.variables = {}
        self.default_variables = {}

        for widget in self.menu_frame.winfo_children():
            widget.destroy()

        self.show_normal_view()

        self.yaml_dropdown.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")
        self.yaml_dropdown.set("Choose a collection..." if self.available_titles else "No collections found")
        self.search_var.set("")

        if not HOME_YAML.exists():
            self.title("Home – File Missing")
            self.page_title.configure(text="Home")
            self.summary_text.configure(state="normal")
            self.summary_text.delete("1.0", "end")
            self.summary_text.insert(
                "1.0",
                f"ERROR: Could not find the home page file.\n\n"
                f"Expected location:\n{HOME_YAML.resolve()}\n\n"
                f"Please create menus/home.yaml to customize this page."
            )
            self.summary_text.configure(state="disabled")
        else:
            home_data = self.load_yaml(HOME_YAML)
            self.title(home_data.get("title", "Home"))

            items = home_data.get("menu", [])
            home_item = None
            for item in items:
                if item.get("label", "").lower() in ("home", "dashboard", "welcome"):
                    home_item = item
                    break
            if home_item is None and items:
                home_item = items[0]

            if home_item:
                label = home_item.get("label", "Home")
                content = home_item.get("content", "No content defined in home.yaml")
            else:
                label = "Home"
                content = (
                    "menus/home.yaml was found but it contains no menu items.\n\n"
                    "Add at least one item under the 'menu:' key."
                )

            self.page_title.configure(text=label)
            self.summary_text.configure(state="normal")
            self.summary_text.delete("1.0", "end")
            self.summary_text.insert("1.0", content)
            self.summary_text.configure(state="disabled")

        self.action_controls.grid_remove()
        self.output_label.grid_remove()
        self.output_text.grid_remove()
        self.normal_view.grid_rowconfigure(5, weight=0)

        self.summary_text.configure(height=350)
        self.normal_view.grid_rowconfigure(2, weight=1)
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 25), sticky="nsew")
        self.options_button.grid()
        self.show_home_background()
        guide = self.summary_text.get("1.0", "end-1c")
        if not hasattr(self, "home_dashboard"):
            self.home_dashboard = ToolboxHome(
                self.normal_view, base_dir=APP_DIR, navigate=self.open_collection,
                open_folder=self.open_workspace_folder, get_icon=self.get_icon, guide=guide,
            )
        else:
            self.home_dashboard.refresh(guide)
        self.summary_label.grid_remove()
        self.summary_text.grid_remove()
        self.home_dashboard.grid(row=2, column=0, padx=22, pady=(8, 20), sticky="nsew")
        self.copy_output_button.grid_remove()
        self.title("Toolbox")
        self.page_title.configure(text="Workspace")

    def open_collection(self, title):
        selected = next((name for name in self.available_titles if name.casefold() == title.casefold()), None)
        if selected:
            self.yaml_dropdown.set(selected)
            self.on_yaml_selected(selected)

    def open_workspace_folder(self):
        try:
            if sys.platform == "win32":
                os.startfile(str(APP_DIR))
            else:
                command = ["open" if sys.platform == "darwin" else "xdg-open", str(APP_DIR)]
                if sys.platform.startswith("linux") and (os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP")):
                    converted = subprocess.run(["wslpath", "-w", str(APP_DIR)], capture_output=True,
                                               text=True, check=True, timeout=10)
                    command = ["explorer.exe", converted.stdout.strip()]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                def check_opened():
                    if process.poll() is None:
                        self.after(100, check_opened)
                        return
                    stdout, stderr = process.communicate()
                    if process.returncode and command[0] != "explorer.exe":
                        messagebox.showerror("Open Toolbox folder", stderr.strip() or stdout.strip(), parent=self)

                self.after(100, check_opened)
        except (OSError, subprocess.SubprocessError) as exc:
            messagebox.showerror("Open Toolbox folder", str(exc), parent=self)

    # Resolve the optional background image relative to the project.
    def _home_background_path(self):
        configured = str(self.ui_settings.get("home_background", "")).strip()
        if not configured:
            return None
        path = Path(configured).expanduser()
        return path.resolve() if path.is_absolute() else (APP_DIR / path).resolve()

    # Show the background behind Home content and request a render.
    def show_home_background(self):
        path = self._home_background_path()
        if path is None or not path.is_file():
            self.home_background_label.place_forget()
            return
        self.home_background_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.home_background_label.lower()
        self.after_idle(self.render_home_background)

    # Debounce resize events before fitting the background image.
    def schedule_background_render(self, _event=None):
        if self.current_title is not None or not self.home_background_label.winfo_ismapped():
            return
        if self.background_resize_job is not None:
            self.after_cancel(self.background_resize_job)
        self.background_resize_job = self.after(120, self.render_home_background)

    # Fit the cached background to the current Home view dimensions.
    def render_home_background(self):
        self.background_resize_job = None
        if self.current_title is not None or not self.normal_view.winfo_ismapped():
            return
        path = self._home_background_path()
        if path is None or not path.is_file():
            self.home_background_label.place_forget()
            return
        width = max(self.normal_view.winfo_width(), 640)
        height = max(self.normal_view.winfo_height(), 480)
        try:
            source_key = (path, path.stat().st_mtime_ns, path.stat().st_size)
            render_key = (source_key, width, height)
            if self.background_render_key == render_key:
                return
            if self.background_source_key != source_key:
                with Image.open(path) as source:
                    self.background_source = source.convert("RGB")
                self.background_source_key = source_key
            fitted = ImageOps.fit(
                self.background_source, (width, height), method=Image.Resampling.LANCZOS,
            )
        except (OSError, ValueError) as exc:
            self.home_background_label.place_forget()
            print(f"Unable to load Home background: {exc}")
            return
        self.home_background_image = ctk.CTkImage(
            light_image=fitted,
            dark_image=fitted,
            size=(width, height),
        )
        self.home_background_label.configure(image=self.home_background_image)
        self.background_render_key = render_key
        self.home_background_label.lower()

    # Open or focus the appearance and background settings dialog.
    def open_options(self):
        existing = getattr(self, 'options_dialog', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        self.options_dialog = HomeOptions(self, THEME_CHOICES)

    # Persist appearance choices and copy external backgrounds into the project.
    def save_ui_options(self, dialog, theme, appearance, background, domain=None):
        if theme not in THEME_CHOICES or appearance not in {"Light", "Dark", "System"}:
            messagebox.showerror("Invalid options", "Choose a valid theme and appearance.", parent=dialog)
            return

        try:
            domain = normalize_domain(domain) if domain is not None else None
        except ValueError as exc:
            messagebox.showerror("Invalid domain", str(exc), parent=dialog)
            return

        stored_background = ""
        background = background.strip()
        if background:
            source = Path(background).expanduser()
            source = source.resolve() if source.is_absolute() else (APP_DIR / source).resolve()
            if not source.is_file():
                messagebox.showerror(
                    "Background not found", f"Could not find:\n{source}", parent=dialog
                )
                return
            try:
                stored_background = str(source.relative_to(APP_DIR))
            except ValueError:
                background_dir = APP_DIR / "assets" / "backgrounds"
                background_dir.mkdir(parents=True, exist_ok=True)
                suffix = source.suffix.lower() if source.suffix else ".png"
                destination = background_dir / f"home-background{suffix}"
                shutil.copy2(source, destination)
                stored_background = str(destination.relative_to(APP_DIR))

        old_theme = self.ui_settings["theme"]
        if domain is not None:
            try:
                save_domain(APP_DIR, domain)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                messagebox.showerror("Save domain", str(exc), parent=dialog)
                return
        self.ui_settings.update({
            "theme": theme,
            "appearance": appearance,
            "home_background": stored_background,
        })
        VARIABLES_DIR.mkdir(exist_ok=True)
        UI_SETTINGS_FILE.write_text(
            yaml.safe_dump(self.ui_settings, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        ctk.set_appearance_mode(appearance)
        dialog.destroy()
        self.show_home_background()
        if theme != old_theme:
            messagebox.showinfo(
                "Options saved",
                "The color theme will be applied the next time the application starts.",
                parent=self,
            )

    # ------------------------------------------------------------------
    # YAML discovery & loading
    # ------------------------------------------------------------------
    # Discover menu files and map their display titles to filenames.
    def find_yaml_files(self):
        result = {}
        if not MENUS_DIR.exists():
            return result

        for pattern in ("*.yaml", "*.yml"):
            for f in MENUS_DIR.glob(pattern):
                if f.name.lower() == "home.yaml":
                    continue
                try:
                    with open(f, "r", encoding="utf-8") as file:
                        data = yaml.safe_load(file) or {}
                    title = data.get("title", f.stem)
                    original = title
                    counter = 1
                    while title in result:
                        title = f"{original} ({counter})"
                        counter += 1
                    result[title] = str(f)
                except Exception:
                    result[f.stem] = str(f)
        return result

    # Load the selected menu and its variables, then reset navigation.
    def on_yaml_selected(self, selected_title: str):
        if self.action_running:
            self.yaml_dropdown.set(self.current_title)
            return
        if selected_title == "No YAML files found" or selected_title == self.current_title:
            return

        self.execution_engine.clear_session_credentials()
        self.current_title = selected_title
        self.current_yaml = self.yaml_map.get(selected_title)
        if not self.current_yaml:
            return

        data = self.load_yaml(self.current_yaml)
        self.menu_data = data
        self.title(f"{data.get('title', 'Collection')} | Toolbox")

        # Variables are stored separately from menu definitions.  Existing
        # inline Variables mappings remain a fallback for older menu files.
        variable_filename = data.get("VariablesFile") or f"{Path(self.current_yaml).stem}.yaml"
        self.current_variables_file = VARIABLES_DIR / Path(str(variable_filename)).name
        inline_variables = data.get("Variables", {}) or {}
        self.variables = copy.deepcopy(inline_variables)
        if self.current_variables_file.exists():
            self.variables.update(load_variables(self.current_variables_file))
        self.default_variables = copy.deepcopy(self.variables)

        self.expanded_items.clear()
        self.current_item = None
        self.search_var.set("")
        self.refresh_menu()
        self.show_yaml_home()

    # Show the selected YAML's first-class Home section without an output box.
    def show_yaml_home(self):
        if self.action_running:
            return
        home = self.menu_data.get("Home") or self.menu_data.get("home") or {}
        if not home:
            home = next((item for item in self.menu_data.get("menu", []) if item.get("home_screen")), {})
        self.collection_category = None
        self.show_collection_page(
            title=home.get("label", self.menu_data.get("title", "Collection")),
            content=home.get("content", "Choose a section to explore the available tools."),
            items=[item for item in self.visible_menu if not item.get("home_screen")],
        )

    def show_collection_page(self, *, title, content, items, category=False):
        if self.action_running:
            return
        self.show_normal_view()
        self.normal_view.grid_remove()
        self.copy_output_button.grid_remove()
        self.current_item = None
        self.set_play_button_enabled(False)
        if not hasattr(self, "collection_page"):
            self.collection_page = CollectionPage(self.content_frame, get_icon=self.get_icon)
        self.collection_page.show(
            title=title, content=content, items=items, collection=self.current_title or "Toolbox",
            on_select=self.open_page_item, guide=content,
            on_back=self.show_yaml_home if category else None,
        )
        self.collection_page.grid(row=0, column=0, sticky="nsew", padx=22, pady=22)

    def open_page_item(self, item):
        if self.action_running:
            return
        if self._item_children(item):
            self.show_category_page(item)
        else:
            self.on_item_click(item)

    def show_category_page(self, item):
        if self.action_running:
            return
        self.clear_action_output()
        self.collection_category = item
        self.show_collection_page(title=item.get("label", "Section"), content=item.get("content", ""),
                                  items=self._item_children(item), category=True)

    # Parse a YAML document and report loading errors to the interface.
    def load_yaml(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {"title": "Empty", "menu": []}
        except Exception as e:
            print(f"Error loading YAML: {e}")
            return {"title": "Error", "menu": []}

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    # Create the main content, action controls, and output widgets.
    def build_normal_view(self):
        self.normal_view.grid_columnconfigure(0, weight=1)
        self.normal_view.grid_rowconfigure(2, weight=1)

        self.home_background_label = ctk.CTkLabel(
            self.normal_view, text="", fg_color="transparent"
        )
        self.home_background_label.place_forget()
        self.normal_view.bind("<Configure>", self.schedule_background_render)

        self.page_title = ctk.CTkLabel(
            self.normal_view, text="Home",
            font=ctk.CTkFont(size=26, weight="bold"), wraplength=340, justify="left", anchor="w",
            text_color=("#1a314b", "#edf5ff"),
        )
        self.page_title.grid(row=0, column=0, padx=30, pady=(25, 5), sticky="w")

        self.options_button = ctk.CTkButton(
            self.normal_view,
            text="Options",
            image=self.get_icon("settings", CONTROL_ICON_SIZE),
            compound="left",
            width=110,
            command=self.open_options,
        )
        self.options_button.grid(row=0, column=0, padx=30, pady=(20, 5), sticky="e")
        self.options_button.grid_remove()
        self.collection_back_button = ctk.CTkButton(
            self.normal_view, text="Overview", image=self.get_icon("home", CONTROL_ICON_SIZE),
            width=115, height=32, fg_color=("#e1ebf4", "#293e56"),
            text_color=("#1a314b", "#edf5ff"), command=self.show_yaml_home,
        )
        self.collection_back_button.grid(row=0, column=0, padx=30, pady=(25, 5), sticky="e")
        self.collection_back_button.grid_remove()

        self.summary_label = ctk.CTkLabel(
            self.normal_view, text="ACTION DETAILS",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED,
        )
        self.summary_label.grid(row=1, column=0, padx=30, pady=(15, 0), sticky="w")

        self.summary_text = ctk.CTkTextbox(
            self.normal_view, height=110, font=ctk.CTkFont(size=14), wrap="word",
            fg_color=SURFACE, border_width=1, border_color=PANEL_BORDER, corner_radius=12,
            border_spacing=15,
        )
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 15), sticky="nsew")
        self.summary_text.insert("1.0", "Loading...")
        self.summary_text.configure(state="disabled")

        self.action_controls = ctk.CTkFrame(self.normal_view, fg_color="transparent")
        self.action_controls.grid(row=3, column=0, padx=30, pady=(0, 15), sticky="ew")
        self.action_controls.grid_columnconfigure(0, weight=1)
        self.play_button = ctk.CTkButton(
            self.action_controls, text="Run Action",
            image=self.get_icon("run", CONTROL_ICON_SIZE), compound="left",
            font=ctk.CTkFont(size=16, weight="bold"), height=45,
            command=self.on_play_clicked, state="disabled",
            fg_color=("gray70", "gray40"), hover_color=("gray60", "gray35"),
            text_color=("gray40", "gray80")
        )
        self.play_button.grid(row=0, column=0, sticky="ew")

        clear_image = Image.new("RGBA", (96, 96))
        drawing = ImageDraw.Draw(clear_image)
        drawing.polygon(((14, 57), (53, 18), (82, 47), (47, 82), (36, 82)),
                        fill="#e74c3c")
        drawing.polygon(((14, 57), (30, 41), (59, 70), (47, 82), (36, 82)),
                        fill="#f6b2aa")
        drawing.line((30, 41, 59, 70), fill="#b83228", width=5)
        drawing.line((35, 85, 84, 85), fill="#e74c3c", width=5)
        self.clear_output_icon = ctk.CTkImage(
            light_image=clear_image, dark_image=clear_image, size=(24, 24)
        )
        self.clear_output_button = ctk.CTkButton(
            self.action_controls, text="", image=self.clear_output_icon,
            width=45, height=45, fg_color="transparent",
            hover_color=("#f5d5d2", "#542a27"),
            command=self.clear_action_output,
        )
        self.clear_output_button.grid(row=0, column=1, padx=(8, 0))
        self.clear_output_tooltip = ctk.CTkLabel(
            self, text="Clear output", fg_color=("gray20", "gray15"),
            text_color="white", corner_radius=5, padx=8, pady=4,
        )
        self.clear_output_button.bind("<Enter>", self.show_clear_output_tooltip, add="+")
        for event in ("<Leave>", "<ButtonPress-1>", "<Unmap>"):
            self.clear_output_button.bind(event, self.hide_clear_output_tooltip, add="+")

        self.output_label = ctk.CTkLabel(
            self.normal_view, text="ACTIVITY & OUTPUT",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED,
        )
        self.output_label.grid(row=4, column=0, padx=30, pady=(5, 0), sticky="w")

        self.output_text = ctk.CTkTextbox(
            self.normal_view, font=ctk.CTkFont(size=13, family="Consolas"), wrap="word",
            fg_color=("#f9fbfd", "#0c131e"), border_width=1, border_color=PANEL_BORDER,
            corner_radius=12, border_spacing=15,
        )
        self.output_text.grid(row=5, column=0, padx=30, pady=(5, 25), sticky="nsew")
        self.output_text.insert("1.0", "")
        self.output_text.configure(state="disabled")

        self.normal_view.grid_rowconfigure(5, weight=1)

    # Create the variable editor and its save and reset controls.
    def build_variables_view(self):
        self.variables_view.grid_columnconfigure(0, weight=1)
        self.variables_view.grid_rowconfigure(3, weight=1)

        title = ctk.CTkLabel(
            self.variables_view, text="Variable Settings",
            font=ctk.CTkFont(size=26, weight="bold"), text_color=("#1a314b", "#edf5ff"),
        )
        title.grid(row=0, column=0, padx=30, pady=(25, 5), sticky="w")
        ctk.CTkButton(self.variables_view, text="Overview", width=115, height=32,
                      fg_color=("#e1ebf4", "#293e56"), text_color=("#1a314b", "#edf5ff"),
                      command=self.show_yaml_home).grid(row=0, column=0, padx=30, pady=(25, 5), sticky="e")
        ctk.CTkLabel(self.variables_view, text="Review your settings, then save before running an action.",
                     font=ctk.CTkFont(size=13), text_color=MUTED, wraplength=450, justify="left").grid(
                         row=1, column=0, padx=30, pady=(5, 10), sticky="w")

        btn_frame = ctk.CTkFrame(self.variables_view, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=30, pady=10, sticky="ew")

        self.add_variable_button = ctk.CTkButton(btn_frame, text="Add Variable", width=140,
                      image=self.get_icon("add", CONTROL_ICON_SIZE), compound="left",
                      command=self.add_variable)
        self.add_variable_button.pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Save", width=100,
                      image=self.get_icon("save", CONTROL_ICON_SIZE), compound="left", fg_color="#218c80",
                      hover_color="#18756c", command=self.save_variables).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Return to Default", width=160,
                      image=self.get_icon("reset", CONTROL_ICON_SIZE), compound="left",
                      fg_color=("#e1ebf4", "#293e56"), text_color=("#1a314b", "#edf5ff"),
                      command=self.reset_to_default).pack(side="left")

        self.vars_scroll = ctk.CTkScrollableFrame(self.variables_view, fg_color=SURFACE,
                                                corner_radius=12, border_width=1, border_color=PANEL_BORDER)
        self.vars_scroll.grid(row=3, column=0, padx=30, pady=(5, 25), sticky="nsew")
        self.vars_scroll.grid_columnconfigure(0, minsize=self.vars_scroll._apply_widget_scaling(190))
        self.vars_scroll.grid_columnconfigure(1, weight=1)
        self.vars_scroll.grid_columnconfigure(2, minsize=self.vars_scroll._apply_widget_scaling(50))

    # Switch from variable editing to the main content view.
    def show_normal_view(self):
        if hasattr(self, "collection_page"):
            self.collection_page.grid_remove()
        if hasattr(self, "home_dashboard"):
            self.home_dashboard.grid_remove()
        self.summary_label.grid()
        self.copy_output_button.grid()
        if hasattr(self, "images_view"):
            self.images_view.grid_remove()
        if hasattr(self, "share_folder_button"):
            self.share_folder_button.grid_remove()
        self.variables_view.grid_forget()
        self.normal_view.grid(row=0, column=0, sticky="nsew")
        if hasattr(self, "options_button"):
            self.options_button.grid_remove()
        if hasattr(self, "home_background_label"):
            self.home_background_label.place_forget()
        if self.current_title:
            self.collection_back_button.grid()
        else:
            self.collection_back_button.grid_remove()

    # Show all variables or just the keys assigned to a menu section.
    def show_variables_view(self, variable_keys=None):
        if hasattr(self, "collection_page"):
            self.collection_page.grid_remove()
        self.current_item = None
        self.set_play_button_enabled(False)
        self.copy_output_button.grid_remove()
        if hasattr(self, "images_view"):
            self.images_view.grid_remove()
        self.variable_keys = set(variable_keys) if variable_keys is not None else None
        self.add_variable_button.configure(state="disabled" if self.variable_keys is not None else "normal")
        self.normal_view.grid_forget()
        self.variables_view.grid(row=0, column=0, sticky="nsew")
        self.refresh_variables_list()

    # ------------------------------------------------------------------
    # Variables Modification (per-menu file in variables/)
    # ------------------------------------------------------------------
    # Save values to their owning YAML files and restrict credential-file access.
    def _persist_current_variables(self):
        if not self.current_variables_file:
            raise RuntimeError("No variable file is currently selected")
        self.current_variables_file.parent.mkdir(parents=True, exist_ok=True)
        save_variable_files(self.current_variables_file, self.variables)
        if any(
            str(self.variables.get(key, "")).strip()
            for key in ("REMOTE_USERNAME_ENCRYPTED", "REMOTE_PASSWORD_ENCRYPTED", "CREDENTIAL_SALT")
        ):
            try:
                os.chmod(self.current_variables_file, 0o600)
            except OSError:
                pass

    # Write current values to the selected menu's variables YAML file.
    def save_variables(self):
        if not self.current_variables_file:
            print("No variable file is currently selected – cannot save variables.")
            return

        scope = getattr(self, "variable_keys", None)
        new_vars = {key: value for key, value in self.variables.items()
                    if scope is not None and key not in scope}
        for child in self.vars_scroll.winfo_children():
            if hasattr(child, "key_entry") and hasattr(child, "value_entry"):
                key = child.key_entry.get().strip()
                value = child.value_entry.get().strip()
                if key:
                    if value.lower() in ("true", "false"):
                        value = value.lower() == "true"
                    else:
                        try:
                            if "." in value:
                                value = float(value)
                            else:
                                value = int(value)
                        except ValueError:
                            pass
                    new_vars[key] = value

        self.variables = new_vars

        try:
            self._persist_current_variables()
            self.default_variables = copy.deepcopy(self.variables)
            print(f"Variables saved into {self.current_variables_file}")
        except Exception as e:
            print(f"Error saving variables: {e}")

    # Restore the active editor's values from its saved defaults.
    def reset_to_default(self):
        scope = getattr(self, "variable_keys", None)
        if scope is None:
            self.variables = copy.deepcopy(self.default_variables)
        else:
            for key in scope:
                if key in self.default_variables:
                    self.variables[key] = copy.deepcopy(self.default_variables[key])
        self.refresh_variables_list()
        print("Reset to the values that were present when this YAML was loaded")

    # Add an empty setting to the general variable editor.
    def add_variable(self):
        self.variables[f"NEW_VAR_{len(self.variables)+1}"] = ""
        self.refresh_variables_list()

    # Remove a setting from the editor's in-memory values.
    def delete_variable(self, key):
        if key in self.variables:
            del self.variables[key]
            self.refresh_variables_list()

    # Rebuild editor rows for the currently visible variable keys.
    def refresh_variables_list(self):
        for widget in self.vars_scroll.winfo_children():
            widget.destroy()

        if not self.variables:
            lbl = ctk.CTkLabel(self.vars_scroll, text="No variables defined in this YAML.\nClick 'Add Variable' to create some.",
                               text_color="gray")
            lbl.grid(row=0, column=0, columnspan=3, pady=20)
            return

        ctk.CTkLabel(self.vars_scroll, text="Key", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=5, pady=5, sticky="w")
        ctk.CTkLabel(self.vars_scroll, text="Value", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=1, padx=5, pady=5, sticky="w")

        scope = getattr(self, "variable_keys", None)
        visible = {key: value for key, value in self.variables.items()
                   if scope is None or key in scope}
        for i, (key, value) in enumerate(visible.items(), start=1):
            row = ctk.CTkFrame(self.vars_scroll, fg_color="transparent")
            row.grid(row=i, column=0, columnspan=3, sticky="ew", pady=3)
            row.grid_columnconfigure(1, weight=1)

            key_entry = ctk.CTkEntry(row, width=180)
            key_entry.insert(0, key)
            if scope is not None:
                key_entry.configure(state="disabled")
            key_entry.grid(row=0, column=0, padx=(0, 10))

            value_entry = ctk.CTkEntry(row)
            value_entry.insert(0, str(value))
            value_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))

            del_btn = ctk.CTkButton(
                row, text="", image=self.get_icon("delete", CONTROL_ICON_SIZE),
                width=40, fg_color="transparent", hover_color=("#fde7e7", "#4f2930"),
                command=lambda k=key: self.delete_variable(k)
            )
            del_btn.grid(row=0, column=2)
            if scope is not None:
                del_btn.configure(state="disabled")

            row.key_entry = key_entry
            row.value_entry = value_entry

    # ------------------------------------------------------------------
    # Menu building
    # ------------------------------------------------------------------
    # Collapse or restore sidebar controls and menu space.
    def toggle_sidebar(self):
        if self.sidebar_expanded:
            self.sidebar.configure(width=SIDEBAR_COLLAPSED_WIDTH)
            self.home_btn.grid_remove()
            self.yaml_dropdown.grid_remove()
            self.search_frame.grid_remove()
            self.menu_frame.grid_remove()
            self.brand_label.grid_remove()
            self.toggle_btn.configure(text="", image=self.get_icon("expand", CONTROL_ICON_SIZE))
            self.sidebar_expanded = False
        else:
            self.sidebar.configure(width=self.sidebar_width)
            self.home_btn.grid()
            self.yaml_dropdown.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")
            self.search_frame.grid(row=3, column=0, padx=15, pady=(0, 4), sticky="ew")
            self.menu_frame.grid()
            self.brand_label.grid()
            self.toggle_btn.configure(text="", image=self.get_icon("menu", CONTROL_ICON_SIZE))
            self.sidebar_expanded = True

    # Rebuild the sidebar using the current search and expansion state.
    def refresh_menu(self):
        for widget in self.menu_frame.winfo_children():
            widget.destroy()
        query = self.search_var.get().strip()
        menu_key = Path(self.current_yaml).name if self.current_yaml else "home.yaml"
        hidden = self.ui_settings.get("hidden_menu_items", {}).get(menu_key, [])
        self.visible_menu = visible_menu_items(self.menu_data.get("menu", []), hidden)
        if query:
            self._build_search_results(query)
        else:
            self._build_menu_recursive(self.visible_menu, self.menu_frame, level=0)

    # Refresh sidebar results when the search text changes.
    def on_search_changed(self, *_args):
        if hasattr(self, "menu_frame"):
            self.refresh_menu()

    # Case-insensitive search; *, ?, and [] use shell-style wildcards.
    @staticmethod
    def _matches_search(query, item, breadcrumb):
        searchable = " ".join((
            breadcrumb,
            str(item.get("label", "")),
            str(item.get("content", "")),
            str(item.get("action_id", "")),
        )).casefold()
        pattern = query.casefold()
        if any(token in pattern for token in ("*", "?", "[")):
            return fnmatch.fnmatchcase(searchable, pattern) or any(
                fnmatch.fnmatchcase(part, pattern) for part in searchable.split()
            )
        return pattern in searchable

    # Yield menu items with their full category breadcrumb.
    def _flatten_menu(self, items, parents=()):
        for item in items:
            path = (*parents, str(item.get("label", "Untitled")))
            yield item, " / ".join(path)
            yield from self._flatten_menu(self._item_children(item), path)

    # Return static children or generate restore actions from backup archives.
    def _item_children(self, item):
        if item.get("special") != "backup_selector":
            return item.get("children", [])

        context = self.execution_engine._expand_context(self.variables)
        parameters = self.execution_engine._resolve(
            copy.deepcopy(item.get("parameters", {})), context
        )
        configured = Path(str(parameters.get("backup_directory", "./backups"))).expanduser()
        backup_dir = configured.resolve() if configured.is_absolute() else (APP_DIR / configured).resolve()
        if not configured.is_absolute():
            try:
                backup_dir.relative_to(APP_DIR)
            except ValueError:
                return [{
                    "label": "Invalid backup path",
                    "icon": "information",
                    "content": f"Backup directory escapes the project: {configured}",
                }]

        backups = []
        if backup_dir.is_dir():
            backups = sorted(
                (
                    path for path in backup_dir.iterdir()
                    if path.is_file()
                    and path.name.casefold().endswith((".tar", ".tar.gz", ".tgz"))
                ),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
        if not backups:
            return [{
                "label": "No backups found",
                "icon": "information",
                "content": f"Place backup archives in {backup_dir}",
            }]

        children = []
        for index, backup in enumerate(backups):
            child_parameters = copy.deepcopy(item.get("parameters", {}))
            child_parameters["archive_name"] = backup.name
            children.append({
                "label": backup.name + (" (Newest)" if index == 0 else ""),
                "icon": "document",
                "content": f"Load container data from {backup.name}.",
                "action_id": item.get("restore_action_id", "load_container_data"),
                "confirm": True,
                "confirm_message": f"Load container data from {backup.name}?",
                "parameters": child_parameters,
            })
        return children

    # Display matching items using their category breadcrumbs.
    def _build_search_results(self, query):
        matches = [
            (item, breadcrumb)
            for item, breadcrumb in self._flatten_menu(self.visible_menu)
            if self._matches_search(query, item, breadcrumb)
        ]
        if not matches:
            ctk.CTkLabel(
                self.menu_frame,
                text=f'No matches for “{query}”',
                text_color=("gray40", "gray60"),
                wraplength=SIDEBAR_WIDTH - 70,
            ).pack(fill="x", padx=8, pady=18)
            return

        for item, breadcrumb in matches:
            has_children = bool(self._item_children(item))
            command = (
                (lambda i=item: self.on_search_category_click(i))
                if has_children else (lambda i=item: self.on_item_click(i))
            )
            ctk.CTkButton(
                self.menu_frame,
                text=breadcrumb,
                image=self.get_icon(item.get("icon")),
                compound="left",
                anchor="w",
                height=MENU_BUTTON_HEIGHT,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"),
                command=command,
            ).pack(fill="x", pady=1)

    # Show a search result category without starting an action.
    def on_search_category_click(self, item):
        self.show_category_page(item)

    # Build indented sidebar rows for expanded menu categories.
    def _build_menu_recursive(self, items, parent, level=0, path=""):
        for index, item in enumerate(items):
            children = self._item_children(item)
            has_children = bool(children)
            item_id = f"{path}/{index}" if path else str(index)

            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=1)
            row.grid_columnconfigure(1, weight=1)

            if has_children:
                is_open = item_id in self.expanded_items
                arrow_icon = "collapse" if is_open else "expand"
                arrow_btn = ctk.CTkButton(
                    row, text="", image=self.get_icon(arrow_icon, (14, 14)),
                    width=28, height=MENU_BUTTON_HEIGHT, font=ctk.CTkFont(size=12),
                    fg_color="transparent", hover_color=("gray70", "gray30"),
                    text_color=("gray10", "gray90"),
                    command=lambda iid=item_id: self.toggle_item(iid)
                )
                arrow_btn.grid(row=0, column=0, padx=(8 + level * 14, 0))
            else:
                spacer = ctk.CTkLabel(row, text="", width=28)
                spacer.grid(row=0, column=0, padx=(8 + level * 14, 0))

            if has_children:
                btn = ctk.CTkButton(
                    row, text=item["label"],
                    image=self.get_icon(item.get("icon")), compound="left",
                    anchor="w", height=MENU_BUTTON_HEIGHT, fg_color="transparent",
                    text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                    font=ctk.CTkFont(size=14 if level == 0 else 13),
                    command=lambda i=item, iid=item_id: self.on_category_click(i, iid)
                )
            else:
                btn = ctk.CTkButton(
                    row, text=item["label"],
                    image=self.get_icon(item.get("icon")), compound="left",
                    anchor="w", height=MENU_BUTTON_HEIGHT, fg_color="transparent",
                    text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                    font=ctk.CTkFont(size=14 if level == 0 else 13),
                    command=lambda i=item: self.on_item_click(i)
                )
            btn.grid(row=0, column=1, sticky="ew", padx=(2, 8))

            if has_children and item_id in self.expanded_items:
                self._build_menu_recursive(children, parent, level + 1, item_id)

    # Toggle a category's expansion state and rebuild its rows.
    def toggle_item(self, item_id):
        if item_id in self.expanded_items:
            self.expanded_items.discard(item_id)
        else:
            self.expanded_items.add(item_id)
        self.refresh_menu()

    # Select a category and display its description and children.
    def on_category_click(self, item, item_id):
        if self.action_running:
            return
        self.toggle_item(item_id)
        self.show_category_page(item)

    # ------------------------------------------------------------------
    # Encrypted troubleshooting credentials
    # ------------------------------------------------------------------
    # Derive a Fernet encryption key from the vault passphrase and salt.
    @staticmethod
    def _credential_cipher(passphrase, salt, iterations):
        if Fernet is None or PBKDF2HMAC is None or hashes is None:
            raise RuntimeError(
                "Credential encryption requires cryptography. Update requirements.txt "
                "and run ./run-once/run-once again."
            )
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
        return Fernet(key)

    # Show the clear-output hint beside its button.
    def show_clear_output_tooltip(self, _event=None):
        button = self.clear_output_button
        self.clear_output_tooltip.place(
            x=button.winfo_rootx() - self.winfo_rootx() + button.winfo_width(),
            y=button.winfo_rooty() - self.winfo_rooty() + button.winfo_height() + 4,
            anchor="ne",
        )
        self.clear_output_tooltip.lift()

    # Hide the clear-output hint when the pointer leaves.
    def hide_clear_output_tooltip(self, _event=None):
        self.clear_output_tooltip.place_forget()

    # Copy the displayed log without changing output or interrupting an action.
    def copy_action_output(self):
        text = self.output_text.get("1.0", "end-1c")
        if not text:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception as exc:
            messagebox.showerror("Copy Output", f"Could not copy the output: {exc}", parent=self)
            return
        self.copy_output_button.configure(text="Copied!")
        self.after(1500, lambda: self.copy_output_button.configure(text="Copy Output")
                   if self.copy_output_button.winfo_exists() else None)

    # Clear displayed output without interrupting the active action.
    def clear_action_output(self):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")

    # Replace the output panel text with a status message.
    def _show_action_output(self, text):
        if not self.current_item:
            self.on_item_click({"label": "Workspace update", "content": "Status from your latest Toolbox operation."})
        else:
            self.show_normal_view()
        self.output_label.grid()
        self.output_text.grid()
        self.normal_view.grid_rowconfigure(5, weight=1)
        self.output_text.configure(state="normal")
        self.output_text.insert("end", "\n" + text + "\n")
        self.output_text.configure(state="disabled")

    # Encrypt SSH credentials using a separate vault passphrase.
    def configure_remote_credentials(self):
        if not self.current_variables_file:
            messagebox.showerror(
                "Credential setup", "Load Troubleshooting.yaml before configuring credentials.", parent=self
            )
            return False

        username = simpledialog.askstring(
            "Remote credentials", "Remote SSH username:", parent=self
        )
        if username is None:
            return False
        username = username.strip()
        if not username or "\n" in username:
            messagebox.showerror("Invalid username", "Enter a valid SSH username.", parent=self)
            return False

        password = simpledialog.askstring(
            "Remote credentials", "Remote SSH and sudo password:", show="*", parent=self
        )
        if password is None:
            return False
        if not password or "\n" in password:
            messagebox.showerror("Invalid password", "The password cannot be empty.", parent=self)
            return False

        passphrase = simpledialog.askstring(
            "Credential vault",
            "Create a vault passphrase (minimum 8 characters):",
            show="*",
            parent=self,
        )
        if passphrase is None:
            return False
        if len(passphrase) < 8:
            messagebox.showerror(
                "Weak passphrase", "The vault passphrase must be at least 8 characters.", parent=self
            )
            return False
        confirmation = simpledialog.askstring(
            "Credential vault", "Confirm the vault passphrase:", show="*", parent=self
        )
        if confirmation != passphrase:
            messagebox.showerror("Passphrases differ", "The passphrases did not match.", parent=self)
            return False

        try:
            iterations = int(self.variables.get("CREDENTIAL_KDF_ITERATIONS", 600000))
            if not 200000 <= iterations <= 5000000:
                raise ValueError("CREDENTIAL_KDF_ITERATIONS must be between 200000 and 5000000")
            salt = os.urandom(16)
            cipher = self._credential_cipher(passphrase, salt, iterations)
            self.variables.update({
                "CREDENTIAL_FORMAT": "fernet-pbkdf2-sha256-v1",
                "CREDENTIAL_SALT": base64.urlsafe_b64encode(salt).decode("ascii"),
                "REMOTE_USERNAME_ENCRYPTED": cipher.encrypt(
                    username.encode("utf-8")
                ).decode("ascii"),
                "REMOTE_PASSWORD_ENCRYPTED": cipher.encrypt(
                    password.encode("utf-8")
                ).decode("ascii"),
            })
            self.variables.pop("REMOTE_USERNAME", None)
            self.variables.pop("REMOTE_PASSWORD", None)
            self._persist_current_variables()
            self.default_variables = copy.deepcopy(self.variables)
            self.execution_engine.set_remote_credentials(username, password, self.remote_credential_target())
            return True
        except Exception as exc:
            messagebox.showerror("Credential setup failed", str(exc), parent=self)
            return False

    # Identify the host and variable file associated with the current credentials.
    def remote_credential_target(self):
        prefix = "SECURITY_ONION_REMOTE_" if "SECURITY_ONION_REMOTE_HOST" in self.variables else "REMOTE_"
        return (str(self.variables.get(prefix + "HOST", "")).strip().lower(),
                int(self.variables.get(prefix + "PORT", 22)), str(self.current_variables_file),
                str(self.variables.get("REMOTE_USERNAME_ENCRYPTED", "")),
                str(self.variables.get("REMOTE_PASSWORD_ENCRYPTED", "")))

    # Unlock saved SSH credentials for the selected remote target.
    def ensure_remote_credentials(self):
        self.execution_engine.bind_remote_target(self.remote_credential_target())
        if self.execution_engine.has_remote_credentials():
            return True

        encrypted_username = str(self.variables.get("REMOTE_USERNAME_ENCRYPTED", "")).strip()
        encrypted_password = str(self.variables.get("REMOTE_PASSWORD_ENCRYPTED", "")).strip()
        salt_text = str(self.variables.get("CREDENTIAL_SALT", "")).strip()
        if not encrypted_username or not encrypted_password or not salt_text:
            if not messagebox.askyesno(
                "Remote credentials",
                "No encrypted remote credentials are configured. Configure them now?",
                parent=self,
            ):
                return False
            return self.configure_remote_credentials()

        passphrase = simpledialog.askstring(
            "Unlock credentials",
            "Enter the troubleshooting vault passphrase for this session:",
            show="*",
            parent=self,
        )
        if passphrase is None:
            return False
        try:
            iterations = int(self.variables.get("CREDENTIAL_KDF_ITERATIONS", 600000))
            salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
            if len(salt) != 16:
                raise ValueError("The credential salt is invalid")
            cipher = self._credential_cipher(passphrase, salt, iterations)
            username = cipher.decrypt(encrypted_username.encode("ascii")).decode("utf-8")
            password = cipher.decrypt(encrypted_password.encode("ascii")).decode("utf-8")
            self.execution_engine.set_remote_credentials(username, password, self.remote_credential_target())
            return True
        except InvalidToken:
            messagebox.showerror(
                "Unlock failed", "Incorrect vault passphrase or damaged encrypted credentials.", parent=self
            )
        except Exception as exc:
            messagebox.showerror("Unlock failed", str(exc), parent=self)
        return False

    # Prompt for a local sudo password when the session needs one.
    def ensure_local_sudo_password(self):
        if self.execution_engine._is_root() or self.execution_engine.has_local_sudo_password():
            return True

        password = simpledialog.askstring(
            "Local sudo",
            "Enter the local sudo password for this application session:",
            show="*",
            parent=self,
        )
        if password is None:
            return False
        try:
            self.execution_engine.set_local_sudo_password(password)
            return True
        except ValueError as exc:
            messagebox.showerror("Local sudo", str(exc), parent=self)
            return False

    # Discard decrypted credentials retained by the current session.
    def lock_remote_credentials(self):
        self.execution_engine.clear_session_credentials()
        self._show_action_output(
            "Local sudo and remote SSH credentials were removed from memory. "
            "The encrypted YAML values were preserved."
        )

    # ------------------------------------------------------------------
    # Item handling
    # ------------------------------------------------------------------
    def confirm_action(self, message):
        """Place action confirmations over the app before taking modal focus."""
        dialog = ctk.CTkToplevel(self)
        dialog.withdraw()
        dialog.title("Confirm action")
        dialog.transient(self)
        dialog.resizable(False, False)
        accepted = False

        def close(value=False):
            nonlocal accepted
            accepted = value
            dialog.destroy()

        ctk.CTkLabel(dialog, text=message, wraplength=440, justify="left").pack(
            padx=24, pady=(24, 16))
        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(padx=24, pady=(0, 24), fill="x")
        cancel = ctk.CTkButton(buttons, text="Cancel", command=close)
        cancel.pack(side="right", padx=(8, 0))
        ctk.CTkButton(buttons, text="Run", command=lambda: close(True)).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", lambda event: close())
        dialog.update_idletasks()
        width = max(480, dialog.winfo_reqwidth())
        height = dialog.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        # Match Tk's dialog placement convention: '+' followed by the root
        # coordinate, including negative coordinates on secondary monitors.
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.deiconify()
        dialog.wait_visibility()
        dialog.lift()
        cancel.focus_set()
        dialog.grab_set()
        self.wait_window(dialog)
        return accepted

    # Update the Run Script button's enabled state and appearance.
    def set_play_button_enabled(self, enabled: bool):
        if enabled:
            self.play_button.configure(
                state="normal", text="Run Action",
                image=self.get_icon("run", CONTROL_ICON_SIZE), compound="left",
                fg_color="#218c80", hover_color="#18756c", text_color="white"
            )
        else:
            self.play_button.configure(
                state="disabled", text="Run Action",
                image=self.get_icon("run", CONTROL_ICON_SIZE), compound="left",
                fg_color=("gray70", "gray40"), hover_color=("gray60", "gray35"),
                text_color=("gray40", "gray80")
            )

    # Open the selected settings editor or display an action's details.
    def on_item_click(self, item):
        if self.action_running:
            return
        if item.get("special") == "image_selector":
            self.show_image_selector(item)
            return
        if item.get("special") == "open_share_folder":
            self.show_share_folder()
            return
        if item.get("special") == "moodle_admin_password":
            self.show_moodle_admin_password()
            return
        if item.get("special") == "capture_dialog":
            self.open_capture_dialog()
            return
        if item.get("special") == "menu_visibility":
            self.open_menu_visibility(self.current_yaml)
            return
        if item.get("special") == "container_settings":
            self.open_container_settings(item)
            return
        self.clear_action_output()
        if item.get("special") == "variables_editor":
            keys = item.get("variable_keys")
            if item.get("variable_prefixes"):
                keys = list(keys or []) + [key for key in self.variables
                    if key.startswith(tuple(item["variable_prefixes"]))]
            self.show_variables_view(keys)
            return

        self.show_normal_view()
        self.current_item = item

        label = item.get("label", "Untitled")
        content = item.get("content", "No description available.")
        has_action = bool(item.get("action_id"))

        # Actionless leaves are information pages (for example, About).  Give
        # them the same clean reading layout as a YAML Home page.
        if not has_action:
            self.page_title.configure(text=label)
            self.summary_text.configure(state="normal", height=350)
            self.summary_text.delete("1.0", "end")
            self.summary_text.insert("1.0", content)
            self.summary_text.configure(state="disabled")
            self.normal_view.grid_rowconfigure(2, weight=1)
            self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 25), sticky="nsew")
            self.action_controls.grid_remove()
            self.output_label.grid_remove()
            self.output_text.grid_remove()
            self.normal_view.grid_rowconfigure(5, weight=0)
            return

        self.page_title.configure(text=label)

        self.summary_text.configure(height=90)
        self.normal_view.grid_rowconfigure(2, weight=1)
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 15), sticky="nsew")

        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", content)
        self.summary_text.configure(state="disabled")

        self.action_controls.grid()
        self.output_label.grid()
        self.output_text.grid()
        self.normal_view.grid_rowconfigure(5, weight=1)

        self.set_play_button_enabled(True)

    def show_image_selector(self, item):
        self.current_item = None
        self.set_play_button_enabled(False)
        context = self.execution_engine._expand_context(self.variables)
        parameters = self.execution_engine._resolve(copy.deepcopy(item.get("parameters", {})), context)
        images = list(dict.fromkeys(parameters.get("images", [])))
        groups = {}
        for service in CONTAINER_VARIABLE_FILES:
            matches = [value for key, value in context.items()
                       if key.startswith(service + "_") and key.endswith("_IMAGE") and value in images]
            if matches:
                groups["nginx-proxy" if service == "PROXY" else service.title()] = list(dict.fromkeys(matches))
        grouped = {image for values in groups.values() for image in values}
        for image in images:
            if image not in grouped:
                groups[image] = [image]
        self.show_normal_view()
        self.normal_view.grid_remove()
        self.variables_view.grid_remove()
        self.copy_output_button.grid_remove()
        if hasattr(self, "images_view"):
            self.images_view.destroy()
        view = self.images_view = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        view.grid(row=0, column=0, sticky="nsew")
        view.grid_columnconfigure(0, weight=1)
        view.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(view, text="Save/Update Images", font=ctk.CTkFont(size=26, weight="bold"),
                     text_color=("#1a314b", "#edf5ff"), wraplength=330, justify="left").grid(
                         row=0, column=0, padx=30, pady=(25, 12), sticky="w")
        ctk.CTkButton(view, text="Overview", width=115, height=32, command=self.show_yaml_home,
                      fg_color=("#e1ebf4", "#293e56"), text_color=("#1a314b", "#edf5ff")).grid(
                          row=0, column=0, padx=30, pady=(25, 12), sticky="e")
        ctk.CTkLabel(view, text="Choose services for your offline image library. Required images are included automatically. Sizes are estimates; cached layers can reduce downloads.",
                     text_color=MUTED, font=ctk.CTkFont(size=13), wraplength=450, justify="left").grid(
                         row=1, column=0, padx=30, sticky="w")
        rows = ctk.CTkScrollableFrame(view, fg_color=SURFACE, corner_radius=12,
                                     border_width=1, border_color=PANEL_BORDER)
        rows.grid(row=2, column=0, padx=30, pady=15, sticky="nsew")
        rows.grid_columnconfigure(0, weight=1)
        selected, labels, sizes = {}, {}, {}
        total = ctk.CTkLabel(view, text="No services selected.", text_color=MUTED, wraplength=450,
                            justify="left", font=ctk.CTkFont(size=12))
        total.grid(row=3, column=0, padx=30, sticky="w")

        def chosen_images():
            return list(dict.fromkeys(image for service, values in groups.items() if selected[service].get() for image in values))

        def update_total():
            chosen = chosen_images()
            known = sum(sizes[image][0] for image in chosen if image in sizes and sizes[image][0] is not None)
            unknown = sum(image not in sizes or sizes[image][0] is None for image in chosen)
            total.configure(text=f"{len(chosen)} unique images selected — known size {known / 1024**2:,.1f} MiB" + (f"; {unknown} size(s) unavailable" if unknown else ""))

        for index, (service, values) in enumerate(groups.items()):
            selected[service] = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(rows, text=service, variable=selected[service], command=update_total).grid(row=index * 2, column=0, padx=10, pady=(12, 2), sticky="w")
            labels[service] = ctk.CTkLabel(rows, text="\n".join(f"{image} — checking size…" for image in values), justify="left", anchor="w", wraplength=700)
            labels[service].grid(row=index * 2 + 1, column=0, padx=40, pady=(0, 8), sticky="ew")

        def fit_image_labels(event):
            width = max(200, rows._reverse_widget_scaling(event.width) - 80)
            for label in labels.values():
                label.configure(wraplength=width)

        rows.bind("<Configure>", fit_image_labels, add="+")

        def download():
            chosen = chosen_images()
            if not chosen:
                messagebox.showinfo("Select services", "Choose at least one service to download.", parent=self)
                return
            action = copy.deepcopy(item)
            action.pop("special", None)
            action["parameters"] = {**parameters, "images": chosen, "preserve_archives": True}
            self.on_item_click(action)
            # Let Tk finish switching views before opening a modal confirmation.
            # In particular, WSLg can lose input when a grab starts mid-transition.
            self.after_idle(lambda: self.on_play_clicked()
                            if self.current_item is action and not self.action_running else None)

        buttons = ctk.CTkFrame(view, fg_color="transparent")
        buttons.grid(row=4, column=0, padx=30, pady=15, sticky="w")
        def set_all(value):
            for variable in selected.values():
                variable.set(value)
            update_total()
        ctk.CTkButton(buttons, text="Select All", command=lambda: set_all(True)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(buttons, text="Clear Selection", command=lambda: set_all(False)).pack(side="left", padx=8)
        ctk.CTkButton(buttons, text="Download Selected", command=download,
                      fg_color="#218c80", hover_color="#18756c").pack(side="left", padx=8)
        events = queue.Queue()
        def lookup():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            architecture = None
            try:
                info = subprocess.run(['docker', 'info', '--format', '{{.Architecture}}'], capture_output=True, text=True, timeout=3)
                if info.returncode == 0 and info.stdout.strip():
                    architecture = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(info.stdout.strip(), info.stdout.strip())
            except (OSError, subprocess.SubprocessError):
                pass
            with ThreadPoolExecutor(max_workers=4) as pool:
                pending = {pool.submit(image_size, image, architecture): image for image in images}
                for future in as_completed(pending):
                    image = pending[future]
                    try:
                        result = future.result()
                    except Exception:
                        result = (None, "Size unavailable")
                    events.put((image, result))
        def poll():
            if not view.winfo_exists() or view.winfo_manager() != "grid":
                return
            changed = set()
            while True:
                try:
                    image, result = events.get_nowait()
                except queue.Empty:
                    break
                sizes[image] = result
                changed.add(image)
            for service, values in groups.items():
                if not changed.intersection(values):
                    continue
                text = []
                for image in values:
                    size, source = sizes.get(image, (None, "checking size…"))
                    text.append(f"{image} — " + (f"{size / 1024**2:,.1f} MiB ({source})" if size is not None else source))
                labels[service].configure(text="\n".join(text))
            if changed:
                update_total()
            if len(sizes) < len(images):
                self.after(150, poll)
        threading.Thread(target=lookup, daemon=True).start()
        self.after(150, poll)

    def show_share_folder(self, *, launch=False):
        """Display the shared directory; launch its file manager only on request."""
        try:
            engine = self.execution_engine
            if engine._share_server is not None:
                directory = engine._share_directory
            else:
                context = engine._expand_context(self.variables)
                value = context.get("SHARE_DIRECTORY", "./share")
                if not value or "${" in value:
                    raise ValueError("Configure SHARE_DIRECTORY in Variable Settings first.")
                directory = Path(value).expanduser()
                if not directory.is_absolute():
                    directory = engine.base_dir / directory
                directory = directory.resolve()
            directory.mkdir(parents=True, exist_ok=True)
            entries = sorted(directory.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.casefold()))
            listing = "\n".join(
                f"{'[Folder] ' if entry.is_dir() else ''}{entry.name}" for entry in entries
            ) or "This folder is empty. Add files here to share them."
            self.on_item_click({
                "label": "Open Share Folder",
                "content": f"Shared folder: {directory}\n\n{listing}\n\nSelect Open Share Folder again to refresh this list.",
            })
            if not hasattr(self, "share_folder_button"):
                self.share_folder_button = ctk.CTkButton(
                    self.normal_view, text="Open Folder", image=self.get_icon("folder"),
                    command=self.open_share_folder,
                )
            self.share_folder_button.grid(row=3, column=0, padx=30, pady=(0, 15), sticky="w")
            if not launch:
                return
            if sys.platform == "win32":
                os.startfile(str(directory))
            else:
                command = ["open" if sys.platform == "darwin" else "xdg-open", str(directory)]
                if sys.platform.startswith("linux") and (
                    os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP")
                ):
                    converted = subprocess.run(
                        ["wslpath", "-w", str(directory)], capture_output=True, text=True, check=True,
                    )
                    command = ["explorer.exe", converted.stdout.strip()]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                def check_open_result():
                    if process.poll() is None:
                        self.after(100, check_open_result)
                        return
                    stdout, stderr = process.communicate()
                    # Explorer can return 1 even when it opens the folder successfully.
                    if process.returncode and command[0] != "explorer.exe":
                        detail = stderr.strip() or stdout.strip() or f"Exit status {process.returncode}"
                        messagebox.showerror("Open Share Folder", f"Could not open {directory}\n\n{detail}", parent=self)

                self.after(100, check_open_result)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            messagebox.showerror("Open Share Folder", str(exc), parent=self)

    def open_share_folder(self):
        self.show_share_folder(launch=True)

    def show_moodle_admin_password(self):
        """Reveal the explicitly requested local secret without logging it."""
        try:
            context = self.execution_engine._expand_context(self.variables)
            directory = context.get("MOODLE_DATA_VOLUME", "")
            if not directory or "${" in directory:
                raise ValueError("Configure MOODLE_DATA_VOLUME in Moodle Variable Settings first.")
            root = Path(directory).expanduser()
            if not root.is_absolute():
                root = APP_DIR / root
            path = root / "secrets" / "admin_password"
            password = path.read_text(encoding="utf-8").strip()
            if not password:
                raise ValueError(f"The saved password file is empty: {path}")
        except FileNotFoundError:
            messagebox.showerror("Moodle admin password", f"No saved password found at {path}. Install Moodle on this computer first.", parent=self)
            return
        except (OSError, ValueError) as exc:
            messagebox.showerror("Moodle admin password", str(exc), parent=self)
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Moodle admin password")
        dialog.geometry("580x300")
        dialog.transient(self)
        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=24, pady=20)
        ctk.CTkLabel(frame, text=f"Username: {context.get('MOODLE_ADMIN_USERNAME', 'admin')}").pack(pady=(0, 10))
        value = ctk.CTkEntry(frame, width=500)
        value.insert(0, password)
        value.configure(state="readonly")
        value.pack(fill="x")
        ctk.CTkLabel(frame, text=f"File: {path}", wraplength=510).pack(pady=12)
        status = ctk.CTkLabel(frame, text="")

        def copy_password():
            try:
                self.clipboard_clear()
                self.clipboard_append(password)
            except Exception as exc:
                messagebox.showerror("Copy password", str(exc), parent=dialog)
                return
            status.configure(text="Password copied")

        ctk.CTkButton(frame, text="Copy Password", command=copy_password).pack()
        status.pack()
        ctk.CTkButton(frame, text="Close", command=dialog.destroy).pack(pady=(5, 0))

    # Choose a local adapter and a new output file before starting capture.
    def open_capture_dialog(self):
        try:
            interfaces = capture_interfaces()
            if not interfaces:
                raise ValueError("No network interfaces are available.")
            if not shutil.which("tcpdump"):
                raise ValueError("tcpdump is missing. Rerun Linux run-once setup to install it.")
        except Exception as exc:
            messagebox.showerror("Capture unavailable", str(exc), parent=self)
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Capture Ethernet / Wi-Fi traffic")
        dialog.geometry("620x340")
        dialog.transient(self)
        ctk.CTkLabel(dialog, text="Network interface").pack(pady=(20, 5))
        adapter = ctk.CTkOptionMenu(dialog, values=interfaces, width=350)
        adapter.pack()
        ctk.CTkLabel(dialog, text="Wi-Fi: traffic visible to the adapter; monitor mode is not enabled.\n"
                     "WSL: only interfaces available inside Linux are listed.", wraplength=560).pack(pady=15)
        output = ctk.CTkEntry(dialog, width=550, placeholder_text="Choose a new .pcap file")
        output.pack()

        # Keep the capture filename explicit and never overwrite an existing file.
        def browse():
            filename = filedialog.asksaveasfilename(parent=dialog, defaultextension=".pcap",
                filetypes=[("Packet capture", "*.pcap")], initialdir=str(APP_DIR / "repos" / "pcap"))
            if filename:
                output.delete(0, "end")
                output.insert(0, filename)

        # Reuse the main worker and its cancellation controls for capture.
        def start():
            destination = Path(output.get()).expanduser()
            if not destination.is_absolute() or destination.suffix.lower() != ".pcap" or destination.exists():
                messagebox.showerror("Capture file", "Choose a new absolute .pcap filename. Existing files are not overwritten.", parent=dialog)
                return
            interface = adapter.get()
            dialog.destroy()
            self.on_item_click({"label": "Capture Traffic", "action_id": "capture_packets",
                "content": "Capture local adapter traffic. Stop Capture finishes and saves the PCAP file.",
                "parameters": {"interface": interface, "output": str(destination)}})
            self.on_play_clicked()

        ctk.CTkButton(dialog, text="Choose file...", command=browse).pack(pady=10)
        ctk.CTkButton(dialog, text="Start Capture", command=start).pack(pady=10)

        # Build and map the controls before taking focus on WSL/X11.
        def activate_capture_dialog():
            if not dialog.winfo_exists():
                return
            if not dialog.winfo_viewable():
                dialog.after(50, activate_capture_dialog)
                return
            x = max(0, self.winfo_rootx() + (self.winfo_width() - dialog.winfo_width()) // 2)
            y = max(0, self.winfo_rooty() + (self.winfo_height() - dialog.winfo_height()) // 2)
            dialog.geometry(f"+{x}+{y}")
            dialog.lift()
            dialog.focus_set()
            dialog.grab_set()

        dialog.after(100, activate_capture_dialog)

    # Save per-menu sidebar visibility while keeping every underlying action intact.
    def open_menu_visibility(self, menu_file):
        menu_key = Path(menu_file).name
        menu_document = self.load_yaml(menu_file)
        hidden = self.ui_settings.get("hidden_menu_items", {}).get(menu_key, [])
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Show / Hide Items — {menu_document.get('title', menu_key)}")
        dialog.geometry("700x550")
        dialog.transient(self)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(dialog, text="Uncheck an action or section to hide it from the sidebar and search.\n"
                     "Hiding a section also hides its children; check the section again to restore it.",
                     wraplength=650).grid(row=0, column=0, padx=20, pady=15)
        entries = ctk.CTkScrollableFrame(dialog)
        entries.grid(row=1, column=0, padx=20, pady=5, sticky="nsew")
        choices = {}
        # Use static menu paths so generated backup filenames are not saved as preferences.
        def menu_paths(items, parents=()):
            for child in items:
                path = (*parents, str(child.get("label", "Untitled")))
                if child.get("special") != "menu_visibility" and not any(
                        entry.get("special") == "menu_visibility" for entry in child.get("children", [])):
                    yield " / ".join(path)
                yield from menu_paths(child.get("children", []), path)

        for label in menu_paths(menu_document.get("menu", [])):
            choice = ctk.BooleanVar(value=label not in hidden)
            ctk.CTkCheckBox(entries, text=label, variable=choice).pack(anchor="w", padx=10, pady=8)
            choices[label] = choice

        # Persist preferences before applying the new sidebar layout.
        def save_visibility():
            updated = copy.deepcopy(self.ui_settings)
            updated.setdefault("hidden_menu_items", {})[menu_key] = [
                label for label, choice in choices.items() if not choice.get()]
            temporary = None
            try:
                UI_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                        dir=UI_SETTINGS_FILE.parent, suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    yaml.safe_dump(updated, stream, sort_keys=False, allow_unicode=True)
                os.replace(temporary, UI_SETTINGS_FILE)
            except (OSError, yaml.YAMLError) as exc:
                messagebox.showerror("Save Menu Visibility", str(exc), parent=dialog)
                return
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self.ui_settings = updated
            if self.current_yaml and Path(self.current_yaml).name == menu_key:
                self.current_item = None
                self.expanded_items.clear()
                self.set_play_button_enabled(False)
                self.refresh_menu()
                self.show_yaml_home()
            dialog.destroy()

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=20, pady=15, sticky="e")
        ctk.CTkButton(buttons, text="Cancel", width=100, command=dialog.destroy).pack(side="left", padx=5)
        ctk.CTkButton(buttons, text="Save", width=100, command=save_visibility).pack(side="left", padx=5)
        dialog.after(100, lambda: dialog.grab_set() if dialog.winfo_exists() else None)

    # Edit one local service's deployment variables without changing its container.
    def open_container_settings(self, item):
        if self.execution_engine._diagnostic_target({"host": self.variables.get("REMOTE_HOST", "")}) == "remote":
            messagebox.showinfo("Local deployment settings",
                "This editor changes local deployment settings. Set the target host to localhost to edit them. "
                "Read Logs inspects the remote container without modifying it.", parent=self)
            return
        service = str(item.get("service", ""))
        if service not in {"HOME", "OPENPROJECT", "ETHERPAD", "NEXTCLOUD", "CTFD", "PORTAINER", "ZULIP", "GUACAMOLE"}:
            messagebox.showerror("Container settings", "Unknown container service.", parent=self)
            return
        path = container_variables_path(APP_DIR, service)
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            values = document["Variables"]
            selected = {key: value for key, value in values.items() if key.startswith(service + "_")}
            if not selected:
                raise ValueError("No deployment settings found for this service")
        except Exception as exc:
            messagebox.showerror("Container settings", str(exc), parent=self)
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"{service.title()} — Container Settings")
        dialog.geometry("900x720")
        dialog.minsize(850, 650)
        dialog.transient(self)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            dialog, text="Saved local deployment settings ? not the running container configuration.\nSave does not modify a running container.\n"
            "To apply: check the ‘Recreate existing container’ box, save,\n"
            "then run this service under Deployment → Containers.\n"
            "Deployment runs on this computer; these settings do not edit a remote container.",
            justify="left", wraplength=820,
        ).grid(row=0, column=0, padx=20, pady=15, sticky="w")
        fields = ctk.CTkScrollableFrame(dialog)
        fields.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="nsew")
        fields.grid_columnconfigure(1, weight=1)
        entries = {}
        for row, (key, value) in enumerate(selected.items()):
            ctk.CTkLabel(fields, text=key.removeprefix(service + "_"), anchor="w").grid(
                row=row, column=0, padx=8, pady=6, sticky="w"
            )
            if key == service + "_RECREATE":
                entry = ctk.CTkCheckBox(fields, text="Recreate existing container")
                if self.execution_engine._as_bool(value, key):
                    entry.select()
            else:
                entry = ctk.CTkEntry(fields, show="*" if any(word in key for word in ("SECRET", "PASSWORD", "TOKEN")) else "")
                entry.insert(0, str(value).lower() if isinstance(value, bool) else str(value))
            entry.grid(row=row, column=1, padx=8, pady=6, sticky="ew")
            entries[key] = entry

        def save():
            try:
                updates = {}
                for key, entry in entries.items():
                    if key == service + "_RECREATE":
                        updates[key] = bool(entry.get())
                        continue
                    value = entry.get().strip()
                    if isinstance(selected[key], bool):
                        value = self.execution_engine._as_bool(value, key)
                    elif isinstance(selected[key], int):
                        value = int(value)
                        if "PORT" in key and not 1 <= value <= 65535:
                            raise ValueError(f"{key} must be between 1 and 65535")
                    elif not value:
                        raise ValueError(f"{key} cannot be blank")
                    updates[key] = value
                save_container_settings(path, service, selected, updates)
            except Exception as exc:
                messagebox.showerror("Container settings", str(exc), parent=dialog)
                return
            dialog.destroy()
            self._show_action_output(
                f"Saved {service.title()} deployment settings. Existing containers are unchanged. "
                "Use Deployment → Containers to recreate this service when ready."
            )

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="e")
        ctk.CTkButton(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=8)
        ctk.CTkButton(buttons, text="Save Settings", command=save).pack(side="left")
        dialog.after(100, lambda: dialog.grab_set() if dialog.winfo_exists() else None)

    # Confirm and start an action, or request cancellation of the running one.
    def on_play_clicked(self):
        if self.action_running:
            self.execution_engine.cancel_requested.set()
            self.play_button.configure(state="disabled", text="Cancelling; waiting for cleanup...")
            return
        if not self.current_item:
            return
        action = None
        action_id = self.current_item.get("action_id")
        if not action_id:
            return

        if action_id == "configure_remote_credentials":
            if self.configure_remote_credentials():
                self._show_action_output(
                    f"Remote username and password were encrypted in variables/"
                    f"{self.current_variables_file.name} and unlocked for this application session."
                )
            return
        if action_id == "lock_remote_credentials":
            self.lock_remote_credentials()
            return

        try:
            context = self.execution_engine._expand_context(self.variables)
            check_parameters = self.execution_engine._resolve(self.current_item.get("parameters", {}), context)
            missing = action_requirements(action_id, check_parameters)
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Action settings", str(exc), parent=self)
            return
        if missing:
            messagebox.showinfo("This action needs another tool", "\n\n".join(missing), parent=self)
            return

        if self.current_item.get("confirm") and not self.confirm_action(
            self.current_item.get("confirm_message", f"Run {self.current_item.get('label', 'this action')}?"),
        ):
            return

        resolved_parameters = None
        if action_id in REMOTE_TROUBLESHOOTING_ACTIONS or self.current_item.get("confirm_phrase"):
            try:
                context = self.execution_engine._expand_context(self.variables)
                resolved_parameters = self.execution_engine._resolve(
                    self.current_item.get("parameters", {}), context
                )
            except Exception as exc:
                messagebox.showerror("Troubleshooting settings", str(exc), parent=self)
                return

        confirm_phrase = self.current_item.get("confirm_phrase")
        if confirm_phrase:
            target_mode = self.execution_engine._diagnostic_target(resolved_parameters)
            target_name = (
                str(resolved_parameters.get("host", "")).strip()
                if target_mode == "remote"
                else "this computer"
            )
            if target_mode == "remote" and not target_name:
                messagebox.showerror(
                    "Missing remote target",
                    "Set the remote host in Variable Settings before running this action.",
                    parent=self,
                )
                return
            typed = simpledialog.askstring(
                "Confirm action on target",
                f"Target: {target_name}\n\nType {confirm_phrase} to continue:",
                parent=self,
            )
            if typed != confirm_phrase:
                self._show_action_output("Action cancelled; no changes were made.")
                return

        if action_id in REMOTE_TROUBLESHOOTING_ACTIONS:
            target_mode = self.execution_engine._diagnostic_target(resolved_parameters)
            if target_mode == "remote":
                if not self.ensure_remote_credentials():
                    return
            else:
                needs_sudo = action_id == "troubleshoot_security_onion"
                if action_id == "troubleshoot_docker":
                    use_sudo = str(resolved_parameters.get("use_sudo", False)).strip().casefold()
                    needs_sudo = use_sudo in {"1", "true", "yes", "on"}
                if needs_sudo and not self.ensure_local_sudo_password():
                    return

        docker_needs_sudo = (
            (action_id.startswith("deploy_") or action_id in {
                "run_container", "docker_status", "pull_images", "load_images",
                "zulip_create_organization", "zulip_organization_link",
            })
            and self.execution_engine._docker_access_command(["docker", "info"])[0] == "sudo"
        )
        if docker_needs_sudo or action_id in {"capture_packets", "replay_pcap", "install_docker", "backup_container_data", "load_container_data", "restore_zulip", "backup_ctfd", "restore_ctfd"}:
            if not self.ensure_local_sudo_password():
                return

        action_parameters = copy.deepcopy(self.current_item.get("parameters", {}))
        if action_id == "zulip_create_organization":
            password = simpledialog.askstring("Zulip owner password", "Enter the initial owner password:", show="*", parent=self)
            if not password:
                return
            confirmation = simpledialog.askstring("Confirm password", "Enter the password again:", show="*", parent=self)
            if password != confirmation:
                messagebox.showerror("Zulip owner password", "Passwords do not match.", parent=self)
                return
            action_parameters["initial_password"] = password

        self.action_running = True
        self.execution_engine.cancel_requested.clear()
        self.yaml_dropdown.configure(state="disabled")
        self.play_button.configure(state="normal", text="Cancel Action", fg_color="#f39c12")
        if action_id == "capture_packets":
            self.play_button.configure(text="Stop Capture")
        self.output_text.configure(state="normal")
        self.output_text.insert("end", f"\n--- Running {self.current_item.get('label', 'script')} ---\n")
        self.output_text.configure(state="disabled")
        threading.Thread(
            target=self.run_action,
            kwargs={"action": action, "action_id": action_id,
                    "parameters": action_parameters,
                    "variables": copy.deepcopy(self.variables)},
            daemon=True,
        ).start()
        self.after(50, self.poll_action_events)

    # Worker entry point: never access Tk widgets from this thread.
    def run_action(self, action=None, action_id=None, parameters=None, variables=None):
        self.execution_engine.output_callback = lambda text: self.action_events.put(("output", text))
        status = ""
        try:
            if not action_id or action:
                raise ValueError("Only registered action_id entries are supported")
            result = self.execution_engine.execute(
                action_id, variables=variables, parameters=parameters or {}
            )
            if result.returncode:
                status = f"\n[Action exited with code {result.returncode}]\n"
            elif action_id == "update_tool":
                self.action_events.put(("restart", "\nToolbox updated. Restarting...\n"))
                return
        except Exception as exc:
            status = "\nError running action: " + self.execution_engine._redact(str(exc)) + "\n"
        self.action_events.put(("done", status))

    # Batch queued output into UI updates and handle action completion.
    def poll_action_events(self):
        # Bound each UI update so a noisy command cannot starve the event loop.
        chunks = []
        finished = False
        restart = False
        for _ in range(200):
            try:
                event, text = self.action_events.get_nowait()
            except queue.Empty:
                break
            if text:
                chunks.append(text)
            if event in {"done", "restart"}:
                finished = True
                restart = event == "restart"
                break
        if chunks:
            self.output_text.configure(state="normal")
            self.output_text.insert("end", "".join(chunks))
            self.output_text.see("end")
            self.output_text.configure(state="disabled")
        if finished:
            self.action_running = False
            self.execution_engine.output_callback = None
            self.yaml_dropdown.configure(state="normal")
            self.set_play_button_enabled(True)
            if restart:
                self.restart_toolbox()
                return
            self.refresh_menu()
            return
        if self.action_running:
            self.after(50, self.poll_action_events)

    def restart_toolbox(self):
        self.execution_engine._stop_share({})
        stopped = self.execution_engine._stop_replay({})
        if stopped.returncode:
            self._show_action_output("Toolbox updated, but background replay could not stop. Stop replay before restarting manually.")
            return
        try:
            self.execution_engine.clear_session_credentials()
            os.chdir(APP_DIR)
            os.execv(sys.executable, restart_command(APP_DIR))
        except OSError as exc:
            self._show_action_output(f"Toolbox updated, but restart failed: {exc}. Reopen Toolbox manually.")

    # Close only after active work and its cleanup have finished.
    def on_close(self):
        if self.action_running:
            messagebox.showinfo(
                "Action running", "Cancel the action and wait for cleanup before closing.", parent=self
            )
            return
        stopped = self.execution_engine._stop_replay({})
        if stopped.returncode:
            messagebox.showinfo("Replay stopping", "Wait for background replay to stop before closing.", parent=self)
            return
        self.execution_engine._stop_share({})
        self.execution_engine.clear_session_credentials()
        self.destroy()

if __name__ == "__main__":
    if "--self-check" in sys.argv:
        from execution_engines.portable_check import run_self_check
        raise SystemExit(run_self_check(APP_DIR, sys.argv[1:]))
    app = YamlMenuApp()
    app.mainloop()
