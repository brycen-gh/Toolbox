import customtkinter as ctk
import yaml
import sys
import shutil
from pathlib import Path
import copy
import fnmatch
import base64
import os
import queue
import threading
import tempfile
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

WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 750
MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 600
SIDEBAR_WIDTH = 300
SIDEBAR_COLLAPSED_WIDTH = 60
SEARCH_HEIGHT = 34
MENU_BUTTON_HEIGHT = 32

APP_DIR = Path(__file__).resolve().parent
MENUS_DIR = APP_DIR / "menus"
VARIABLES_DIR = APP_DIR / "variables"
UI_SETTINGS_FILE = VARIABLES_DIR / "ui.yaml"
HOME_YAML = MENUS_DIR / "home.yaml"
ICONS_DIR = APP_DIR / "assets" / "icons"
MENU_ICON_SIZE = (20, 20)
SEARCH_ICON_SIZE = (18, 18)
CONTROL_ICON_SIZE = (18, 18)

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
}


def save_container_settings(path, service, original, updates):
    """Merge only this service's edits, refusing to overwrite concurrent changes."""
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
    return settings


UI_SETTINGS = load_ui_settings()
ctk.set_appearance_mode(UI_SETTINGS["appearance"])
ctk.set_default_color_theme(THEME_CHOICES[UI_SETTINGS["theme"]])

class YamlMenuApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("YAML Menu")
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

        # Variables that belong to the *currently loaded* YAML
        self.variables = {}
        self.default_variables = {}       # snapshot when the YAML was loaded

        # ==================== LAYOUT ====================
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---------- Sidebar ----------
        self.sidebar = ctk.CTkFrame(self, width=self.sidebar_width, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(4, weight=1)

        self.toggle_btn = ctk.CTkButton(
            self.sidebar, text="", image=self.get_icon("menu", CONTROL_ICON_SIZE),
            width=40, height=40,
            font=ctk.CTkFont(size=18), fg_color="transparent",
            hover_color=("gray70", "gray30"), command=self.toggle_sidebar
        )
        self.toggle_btn.grid(row=0, column=0, padx=10, pady=(15, 5), sticky="w")

        self.home_btn = ctk.CTkButton(
            self.sidebar,
            text="Home",
            image=self.get_icon("home"),
            compound="left",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36,
            fg_color="#3498db",
            hover_color="#2980b9",
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
            text="",
            image=self.get_icon("search", SEARCH_ICON_SIZE),
            width=28,
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
        self.content_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray95", "gray13"))
        self.content_frame.grid(row=0, column=1, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

        self.normal_view = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.variables_view = ctk.CTkFrame(self.content_frame, fg_color="transparent")

        self.build_normal_view()
        self.build_variables_view()

        self.show_normal_view()
        self.open_home()

    def get_icon(self, icon_name, size=MENU_ICON_SIZE):
        """Load and cache a named PNG icon, with a safe default fallback."""
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
        self.yaml_dropdown.set("Select YAML..." if self.available_titles else "No YAML files found")
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

        self.summary_text.configure(height=350)
        self.normal_view.grid_rowconfigure(2, weight=1)
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 25), sticky="nsew")
        self.options_button.grid()
        self.show_home_background()

    def _home_background_path(self):
        configured = str(self.ui_settings.get("home_background", "")).strip()
        if not configured:
            return None
        path = Path(configured).expanduser()
        return path.resolve() if path.is_absolute() else (APP_DIR / path).resolve()

    def show_home_background(self):
        path = self._home_background_path()
        if path is None or not path.is_file():
            self.home_background_label.grid_remove()
            return
        self.home_background_label.grid(row=0, column=0, rowspan=6, sticky="nsew")
        self.home_background_label.lower()
        self.after_idle(self.render_home_background)

    def schedule_background_render(self, _event=None):
        if self.current_title is not None or not self.home_background_label.winfo_ismapped():
            return
        if self.background_resize_job is not None:
            self.after_cancel(self.background_resize_job)
        self.background_resize_job = self.after(120, self.render_home_background)

    def render_home_background(self):
        self.background_resize_job = None
        path = self._home_background_path()
        if path is None or not path.is_file():
            self.home_background_label.grid_remove()
            return
        width = max(self.normal_view.winfo_width(), 640)
        height = max(self.normal_view.winfo_height(), 480)
        try:
            with Image.open(path) as source:
                fitted = ImageOps.fit(
                    source.convert("RGB"),
                    (width, height),
                    method=Image.Resampling.LANCZOS,
                )
        except (OSError, ValueError) as exc:
            self.home_background_label.grid_remove()
            print(f"Unable to load Home background: {exc}")
            return
        self.home_background_image = ctk.CTkImage(
            light_image=fitted,
            dark_image=fitted,
            size=(width, height),
        )
        self.home_background_label.configure(image=self.home_background_image)
        self.home_background_label.lower()

    def open_options(self):
        existing = getattr(self, "options_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        dialog = ctk.CTkToplevel(self)
        self.options_dialog = dialog
        dialog.title("Home Options")
        dialog.geometry("640x380")
        dialog.resizable(False, False)
        dialog.transient(self)

        # Building the controls inside a packed frame avoids a blank CTkToplevel
        # on some Linux/WSL window managers. Do not use grab_set() here: some WSL
        # display servers reject grabs for newly opened windows as "not viewable".
        content = ctk.CTkFrame(dialog, corner_radius=12)
        content.pack(fill="both", expand=True, padx=18, pady=18)
        content.grid_columnconfigure(1, weight=1)

        theme_var = ctk.StringVar(value=self.ui_settings["theme"])
        appearance_var = ctk.StringVar(value=self.ui_settings["appearance"])
        background_var = ctk.StringVar(value=self.ui_settings.get("home_background", ""))

        ctk.CTkLabel(
            content, text="Customize Home", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, columnspan=3, padx=20, pady=(20, 14), sticky="w")

        ctk.CTkLabel(content, text="Theme", font=ctk.CTkFont(weight="bold")).grid(
            row=1, column=0, padx=(20, 12), pady=10, sticky="w"
        )
        theme_dropdown = ctk.CTkOptionMenu(
            content,
            values=list(THEME_CHOICES.keys()),
            variable=theme_var,
            dynamic_resizing=False,
            width=220,
        )
        theme_dropdown.grid(row=1, column=1, columnspan=2, padx=(12, 20), pady=10, sticky="ew")

        ctk.CTkLabel(content, text="Appearance", font=ctk.CTkFont(weight="bold")).grid(
            row=2, column=0, padx=(20, 12), pady=10, sticky="w"
        )
        ctk.CTkOptionMenu(
            content,
            values=["System", "Dark", "Light"],
            variable=appearance_var,
            dynamic_resizing=False,
        ).grid(row=2, column=1, columnspan=2, padx=(12, 20), pady=10, sticky="ew")

        ctk.CTkLabel(content, text="Home Background", font=ctk.CTkFont(weight="bold")).grid(
            row=3, column=0, padx=(20, 12), pady=10, sticky="w"
        )
        background_entry = ctk.CTkEntry(content, textvariable=background_var)
        background_entry.grid(row=3, column=1, padx=(12, 8), pady=10, sticky="ew")

        def browse_background():
            selected = filedialog.askopenfilename(
                parent=dialog,
                title="Choose Home background",
                filetypes=[
                    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
                    ("All files", "*.*"),
                ],
            )
            if selected:
                background_var.set(selected)

        ctk.CTkButton(content, text="Browse", width=80, command=browse_background).grid(
            row=3, column=2, padx=(0, 20), pady=10
        )
        ctk.CTkButton(
            content,
            text="Clear Background",
            fg_color="#e67e22",
            hover_color="#d35400",
            command=lambda: background_var.set(""),
        ).grid(row=4, column=1, padx=(12, 8), pady=(2, 8), sticky="w")
        ctk.CTkLabel(
            content,
            text="Appearance and background update immediately. Color themes apply next launch.",
            text_color=("gray40", "gray65"),
        ).grid(row=5, column=0, columnspan=3, padx=20, pady=(8, 12))
        ctk.CTkButton(
            content,
            text="Save Options",
            image=self.get_icon("save", CONTROL_ICON_SIZE),
            compound="left",
            height=38,
            command=lambda: self.save_ui_options(
                dialog, theme_var.get(), appearance_var.get(), background_var.get()
            ),
        ).grid(row=6, column=0, columnspan=3, padx=20, pady=(0, 20), sticky="ew")

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.update_idletasks()
        x = self.winfo_rootx() + max((self.winfo_width() - dialog.winfo_width()) // 2, 0)
        y = self.winfo_rooty() + max((self.winfo_height() - dialog.winfo_height()) // 2, 0)
        dialog.geometry(f"+{x}+{y}")

        def activate_dialog():
            if dialog.winfo_exists():
                dialog.lift()
                dialog.focus_force()

        dialog.after(100, activate_dialog)

    def save_ui_options(self, dialog, theme, appearance, background):
        if theme not in THEME_CHOICES or appearance not in {"Light", "Dark", "System"}:
            messagebox.showerror("Invalid options", "Choose a valid theme and appearance.", parent=dialog)
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
        self.ui_settings = {
            "theme": theme,
            "appearance": appearance,
            "home_background": stored_background,
        }
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
        self.title(data.get("title", "YAML Menu"))

        # Variables are stored separately from menu definitions.  Existing
        # inline Variables mappings remain a fallback for older menu files.
        variable_filename = data.get("VariablesFile") or f"{Path(self.current_yaml).stem}.yaml"
        self.current_variables_file = VARIABLES_DIR / Path(str(variable_filename)).name
        inline_variables = data.get("Variables", {}) or {}
        self.variables = copy.deepcopy(inline_variables)
        if self.current_variables_file.exists():
            variable_data = self.load_yaml(self.current_variables_file)
            file_variables = variable_data.get("Variables", variable_data)
            if not isinstance(file_variables, dict):
                raise ValueError(
                    f"Variable file must contain a mapping: {self.current_variables_file}"
                )
            self.variables.update(file_variables)
        self.default_variables = copy.deepcopy(self.variables)

        self.expanded_items.clear()
        self.current_item = None
        self.search_var.set("")
        self.refresh_menu()
        self.show_yaml_home()

    def show_yaml_home(self):
        """Show the selected YAML's first-class Home section without an output box."""
        home = self.menu_data.get("Home") or self.menu_data.get("home") or {}
        if not home:
            return

        self.show_normal_view()
        self.page_title.configure(text=home.get("label", self.menu_data.get("title", "Home")))
        self.summary_text.configure(state="normal", height=350)
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", home.get("content", ""))
        self.summary_text.configure(state="disabled")
        self.normal_view.grid_rowconfigure(2, weight=1)
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 25), sticky="nsew")
        self.action_controls.grid_remove()
        self.output_label.grid_remove()
        self.output_text.grid_remove()

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
    def build_normal_view(self):
        self.normal_view.grid_columnconfigure(0, weight=1)

        self.home_background_label = ctk.CTkLabel(
            self.normal_view, text="", fg_color="transparent"
        )
        self.home_background_label.grid_remove()
        self.normal_view.bind("<Configure>", self.schedule_background_render)

        self.page_title = ctk.CTkLabel(
            self.normal_view, text="Home",
            font=ctk.CTkFont(size=22, weight="bold")
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

        self.summary_label = ctk.CTkLabel(
            self.normal_view, text="Summary",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=("gray40", "gray60")
        )
        self.summary_label.grid(row=1, column=0, padx=30, pady=(15, 0), sticky="w")

        self.summary_text = ctk.CTkTextbox(
            self.normal_view, height=90, font=ctk.CTkFont(size=14), wrap="word"
        )
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 15), sticky="ew")
        self.summary_text.insert("1.0", "Loading...")
        self.summary_text.configure(state="disabled")

        self.action_controls = ctk.CTkFrame(self.normal_view, fg_color="transparent")
        self.action_controls.grid(row=3, column=0, padx=30, pady=(0, 15), sticky="ew")
        self.action_controls.grid_columnconfigure(0, weight=1)
        self.play_button = ctk.CTkButton(
            self.action_controls, text="Run Script",
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
            self.normal_view, text="Output",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=("gray40", "gray60")
        )
        self.output_label.grid(row=4, column=0, padx=30, pady=(5, 0), sticky="w")

        self.output_text = ctk.CTkTextbox(
            self.normal_view, font=ctk.CTkFont(size=13, family="Consolas"), wrap="word"
        )
        self.output_text.grid(row=5, column=0, padx=30, pady=(5, 25), sticky="nsew")
        self.output_text.insert("1.0", "")
        self.output_text.configure(state="disabled")

        self.normal_view.grid_rowconfigure(5, weight=1)

    def build_variables_view(self):
        self.variables_view.grid_columnconfigure(0, weight=1)
        self.variables_view.grid_rowconfigure(2, weight=1)

        title = ctk.CTkLabel(
            self.variables_view, text="Variable Settings",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        title.grid(row=0, column=0, padx=30, pady=(25, 5), sticky="w")

        btn_frame = ctk.CTkFrame(self.variables_view, fg_color="transparent")
        btn_frame.grid(row=1, column=0, padx=30, pady=10, sticky="ew")

        ctk.CTkButton(btn_frame, text="Add Variable", width=140,
                      image=self.get_icon("add", CONTROL_ICON_SIZE), compound="left",
                      command=self.add_variable).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Save", width=100,
                      image=self.get_icon("save", CONTROL_ICON_SIZE), compound="left", fg_color="#2ecc71",
                      hover_color="#27ae60", command=self.save_variables).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Return to Default", width=160,
                      image=self.get_icon("reset", CONTROL_ICON_SIZE), compound="left",
                      fg_color="#e67e22", hover_color="#d35400",
                      command=self.reset_to_default).pack(side="left")

        self.vars_scroll = ctk.CTkScrollableFrame(self.variables_view)
        self.vars_scroll.grid(row=2, column=0, padx=30, pady=(5, 25), sticky="nsew")
        self.vars_scroll.grid_columnconfigure(1, weight=1)

    def show_normal_view(self):
        self.variables_view.grid_forget()
        self.normal_view.grid(row=0, column=0, sticky="nsew")
        if hasattr(self, "options_button"):
            self.options_button.grid_remove()
        if hasattr(self, "home_background_label"):
            self.home_background_label.grid_remove()

    def show_variables_view(self):
        self.normal_view.grid_forget()
        self.variables_view.grid(row=0, column=0, sticky="nsew")
        self.refresh_variables_list()

    # ------------------------------------------------------------------
    # Variables Modification (per-menu file in variables/)
    # ------------------------------------------------------------------
    def _persist_current_variables(self):
        if not self.current_variables_file:
            raise RuntimeError("No variable file is currently selected")
        self.current_variables_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.current_variables_file, "w", encoding="utf-8") as stream:
            yaml.safe_dump(
                {"Variables": self.variables},
                stream,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        if any(
            str(self.variables.get(key, "")).strip()
            for key in ("REMOTE_USERNAME_ENCRYPTED", "REMOTE_PASSWORD_ENCRYPTED", "CREDENTIAL_SALT")
        ):
            try:
                os.chmod(self.current_variables_file, 0o600)
            except OSError:
                pass

    def save_variables(self):
        """Write current values to the selected menu's variables YAML file."""
        if not self.current_variables_file:
            print("No variable file is currently selected – cannot save variables.")
            return

        new_vars = {}
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

    def reset_to_default(self):
        self.variables = copy.deepcopy(self.default_variables)
        self.refresh_variables_list()
        print("Reset to the values that were present when this YAML was loaded")

    def add_variable(self):
        self.variables[f"NEW_VAR_{len(self.variables)+1}"] = ""
        self.refresh_variables_list()

    def delete_variable(self, key):
        if key in self.variables:
            del self.variables[key]
            self.refresh_variables_list()

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

        for i, (key, value) in enumerate(self.variables.items(), start=1):
            row = ctk.CTkFrame(self.vars_scroll, fg_color="transparent")
            row.grid(row=i, column=0, columnspan=3, sticky="ew", pady=3)
            row.grid_columnconfigure(1, weight=1)

            key_entry = ctk.CTkEntry(row, width=180)
            key_entry.insert(0, key)
            key_entry.grid(row=0, column=0, padx=(0, 10))

            value_entry = ctk.CTkEntry(row)
            value_entry.insert(0, str(value))
            value_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))

            del_btn = ctk.CTkButton(
                row, text="", image=self.get_icon("delete", CONTROL_ICON_SIZE),
                width=40, fg_color="#e74c3c", hover_color="#c0392b",
                command=lambda k=key: self.delete_variable(k)
            )
            del_btn.grid(row=0, column=2)

            row.key_entry = key_entry
            row.value_entry = value_entry

    # ------------------------------------------------------------------
    # Menu building
    # ------------------------------------------------------------------
    def toggle_sidebar(self):
        if self.sidebar_expanded:
            self.sidebar.configure(width=SIDEBAR_COLLAPSED_WIDTH)
            self.home_btn.grid_remove()
            self.yaml_dropdown.grid_remove()
            self.search_frame.grid_remove()
            self.menu_frame.grid_remove()
            self.toggle_btn.configure(text="", image=self.get_icon("expand", CONTROL_ICON_SIZE))
            self.sidebar_expanded = False
        else:
            self.sidebar.configure(width=self.sidebar_width)
            self.home_btn.grid()
            self.yaml_dropdown.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")
            self.search_frame.grid(row=3, column=0, padx=15, pady=(0, 4), sticky="ew")
            self.menu_frame.grid()
            self.toggle_btn.configure(text="", image=self.get_icon("menu", CONTROL_ICON_SIZE))
            self.sidebar_expanded = True

    def refresh_menu(self):
        for widget in self.menu_frame.winfo_children():
            widget.destroy()
        query = self.search_var.get().strip()
        if query:
            self._build_search_results(query)
        else:
            self._build_menu_recursive(self.menu_data.get("menu", []), self.menu_frame, level=0)

    def on_search_changed(self, *_args):
        if hasattr(self, "menu_frame"):
            self.refresh_menu()

    @staticmethod
    def _matches_search(query, item, breadcrumb):
        """Case-insensitive search; *, ?, and [] use shell-style wildcards."""
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

    def _flatten_menu(self, items, parents=()):
        for item in items:
            path = (*parents, str(item.get("label", "Untitled")))
            yield item, " / ".join(path)
            yield from self._flatten_menu(self._item_children(item), path)

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
                "action_id": "load_container_data",
                "confirm": True,
                "confirm_message": f"Load container data from {backup.name}?",
                "parameters": child_parameters,
            })
        return children

    def _build_search_results(self, query):
        matches = [
            (item, breadcrumb)
            for item, breadcrumb in self._flatten_menu(self.menu_data.get("menu", []))
            if self._matches_search(query, item, breadcrumb)
        ]
        if not matches:
            ctk.CTkLabel(
                self.menu_frame,
                text=f'No matches for “{query}”',
                text_color=("gray40", "gray60"),
                wraplength=230,
            ).pack(fill="x", padx=8, pady=18)
            return

        for item, breadcrumb in matches:
            has_children = bool(item.get("children"))
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

    def on_search_category_click(self, item):
        if self.action_running:
            return
        self.clear_action_output()
        self.show_normal_view()
        self.current_item = item
        self.page_title.configure(text=item.get("label", "Untitled"))
        self.summary_text.configure(state="normal", height=90)
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", item.get("content", "No description available."))
        self.summary_text.configure(state="disabled")
        self.action_controls.grid()
        self.output_label.grid()
        self.output_text.grid()
        self.set_play_button_enabled(False)

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

    def toggle_item(self, item_id):
        if item_id in self.expanded_items:
            self.expanded_items.discard(item_id)
        else:
            self.expanded_items.add(item_id)
        self.refresh_menu()

    def on_category_click(self, item, item_id):
        if self.action_running:
            return
        self.clear_action_output()
        self.show_normal_view()
        self.current_item = item

        label = item.get("label", "Untitled")
        content = item.get("content", "No description available for this category.")

        self.page_title.configure(text=label)

        self.summary_text.configure(height=90)
        self.normal_view.grid_rowconfigure(2, weight=0)
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 15), sticky="ew")

        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", content)
        self.summary_text.configure(state="disabled")

        self.action_controls.grid()
        self.output_label.grid()
        self.output_text.grid()

        self.set_play_button_enabled(False)

        self.toggle_item(item_id)

    # ------------------------------------------------------------------
    # Encrypted troubleshooting credentials
    # ------------------------------------------------------------------
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

    def show_clear_output_tooltip(self, _event=None):
        button = self.clear_output_button
        self.clear_output_tooltip.place(
            x=button.winfo_rootx() - self.winfo_rootx() + button.winfo_width(),
            y=button.winfo_rooty() - self.winfo_rooty() + button.winfo_height() + 4,
            anchor="ne",
        )
        self.clear_output_tooltip.lift()

    def hide_clear_output_tooltip(self, _event=None):
        self.clear_output_tooltip.place_forget()

    def clear_action_output(self):
        """Clear displayed output without interrupting the active action."""
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")

    def _show_action_output(self, text):
        self.output_label.grid()
        self.output_text.grid()
        self.output_text.configure(state="normal")
        self.output_text.insert("end", "\n" + text + "\n")
        self.output_text.configure(state="disabled")

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

    def remote_credential_target(self):
        prefix = "SECURITY_ONION_REMOTE_" if "SECURITY_ONION_REMOTE_HOST" in self.variables else "REMOTE_"
        return (str(self.variables.get(prefix + "HOST", "")).strip().lower(),
                int(self.variables.get(prefix + "PORT", 22)), str(self.current_variables_file),
                str(self.variables.get("REMOTE_USERNAME_ENCRYPTED", "")),
                str(self.variables.get("REMOTE_PASSWORD_ENCRYPTED", "")))

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

    def lock_remote_credentials(self):
        self.execution_engine.clear_session_credentials()
        self._show_action_output(
            "Local sudo and remote SSH credentials were removed from memory. "
            "The encrypted YAML values were preserved."
        )

    # ------------------------------------------------------------------
    # Item handling
    # ------------------------------------------------------------------
    def set_play_button_enabled(self, enabled: bool):
        if enabled:
            self.play_button.configure(
                state="normal", text="Run Script",
                image=self.get_icon("run", CONTROL_ICON_SIZE), compound="left",
                fg_color="#2ecc71", hover_color="#27ae60", text_color="white"
            )
        else:
            self.play_button.configure(
                state="disabled", text="Run Script",
                image=self.get_icon("run", CONTROL_ICON_SIZE), compound="left",
                fg_color=("gray70", "gray40"), hover_color=("gray60", "gray35"),
                text_color=("gray40", "gray80")
            )

    def on_item_click(self, item):
        if self.action_running:
            return
        if item.get("special") == "container_settings":
            self.open_container_settings(item)
            return
        self.clear_action_output()
        if item.get("special") == "variables_editor":
            self.show_variables_view()
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
            return

        self.page_title.configure(text=label)

        self.summary_text.configure(height=90)
        self.normal_view.grid_rowconfigure(2, weight=0)
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 15), sticky="ew")

        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", content)
        self.summary_text.configure(state="disabled")

        self.action_controls.grid()
        self.output_label.grid()
        self.output_text.grid()

        self.set_play_button_enabled(True)

    def open_container_settings(self, item):
        if str(self.variables.get("TARGET_MODE", "local")).lower() == "remote":
            messagebox.showinfo("Local deployment settings",
                "This editor changes local deployment settings. Switch TARGET_MODE to local to edit them. "
                "Read Logs inspects the remote container without modifying it.", parent=self)
            return
        service = str(item.get("service", ""))
        if service not in {"OPENPROJECT", "ETHERPAD", "NEXTCLOUD", "CTFD", "PORTAINER"}:
            messagebox.showerror("Container settings", "Unknown container service.", parent=self)
            return
        path = VARIABLES_DIR / "deployment-variables.yaml"
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

        if self.current_item.get("confirm") and not messagebox.askyesno(
            "Confirm action",
            self.current_item.get("confirm_message", f"Run {self.current_item.get('label', 'this action')}?"),
            parent=self,
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
            target_mode = str(resolved_parameters.get("target", "local")).strip().casefold()
            target_name = (
                str(resolved_parameters.get("host", "")).strip()
                if target_mode == "remote"
                else "this computer"
            )
            if target_mode == "remote" and not target_name:
                messagebox.showerror(
                    "Missing remote target",
                    "Set the Security Onion remote host in Variable Settings before clearing data.",
                    parent=self,
                )
                return
            typed = simpledialog.askstring(
                "Permanent data deletion",
                f"Target: {target_name}\n\nType {confirm_phrase} to continue:",
                parent=self,
            )
            if typed != confirm_phrase:
                self._show_action_output("Clear operation cancelled; no Security Onion data was deleted.")
                return

        if action_id in REMOTE_TROUBLESHOOTING_ACTIONS:
            target_mode = str(resolved_parameters.get("target", "local")).strip().casefold()
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

        if action_id in {"replay_pcap", "install_docker", "backup_container_data", "load_container_data"}:
            if not self.ensure_local_sudo_password():
                return

        self.action_running = True
        self.execution_engine.cancel_requested.clear()
        self.yaml_dropdown.configure(state="disabled")
        self.play_button.configure(state="normal", text="Cancel Action", fg_color="#f39c12")
        self.output_text.configure(state="normal")
        self.output_text.insert("end", f"\n--- Running {self.current_item.get('label', 'script')} ---\n")
        self.output_text.configure(state="disabled")
        threading.Thread(
            target=self.run_action,
            kwargs={"action": action, "action_id": action_id,
                    "parameters": copy.deepcopy(self.current_item.get("parameters", {})),
                    "variables": copy.deepcopy(self.variables)},
            daemon=True,
        ).start()
        self.after(50, self.poll_action_events)

    def run_action(self, action=None, action_id=None, parameters=None, variables=None):
        """Worker entry point: never access Tk widgets from this thread."""
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
        except Exception as exc:
            status = "\nError running action: " + self.execution_engine._redact(str(exc)) + "\n"
        self.action_events.put(("done", status))

    def poll_action_events(self):
        # Bound each UI update so a noisy command cannot starve the event loop.
        for _ in range(200):
            try:
                event, text = self.action_events.get_nowait()
            except queue.Empty:
                break
            self.output_text.configure(state="normal")
            if text:
                self.output_text.insert("end", text)
            self.output_text.see("end")
            self.output_text.configure(state="disabled")
            if event == "done":
                self.action_running = False
                self.execution_engine.output_callback = None
                self.yaml_dropdown.configure(state="normal")
                self.set_play_button_enabled(True)
                self.refresh_menu()
                return
        if self.action_running:
            self.after(50, self.poll_action_events)

    def on_close(self):
        if self.action_running:
            messagebox.showinfo(
                "Action running", "Cancel the action and wait for cleanup before closing.", parent=self
            )
            return
        self.execution_engine.clear_session_credentials()
        self.destroy()

if __name__ == "__main__":
    app = YamlMenuApp()
    app.mainloop()
