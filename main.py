import customtkinter as ctk
import yaml
import subprocess
import sys
from pathlib import Path
from io import StringIO
import contextlib
import copy

# Appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

MENUS_DIR = Path("menus")
HOME_YAML = MENUS_DIR / "home.yaml"

class YamlMenuApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("YAML Menu")
        self.geometry("1100x750")
        self.minsize(900, 600)

        MENUS_DIR.mkdir(exist_ok=True)

        self.yaml_map = self.find_yaml_files()
        self.available_titles = list(self.yaml_map.keys())

        self.current_title = None
        self.current_yaml = None          # full path to the currently loaded menu YAML
        self.menu_data = {"title": "Home", "menu": []}

        self.current_item = None
        self.sidebar_expanded = True
        self.sidebar_width = 260
        self.expanded_items = set()

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
        self.sidebar.grid_rowconfigure(3, weight=1)

        self.toggle_btn = ctk.CTkButton(
            self.sidebar, text="☰", width=40, height=40,
            font=ctk.CTkFont(size=18), fg_color="transparent",
            hover_color=("gray70", "gray30"), command=self.toggle_sidebar
        )
        self.toggle_btn.grid(row=0, column=0, padx=10, pady=(15, 5), sticky="w")

        self.home_btn = ctk.CTkButton(
            self.sidebar,
            text="🏠  Home",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36,
            fg_color="#3498db",
            hover_color="#2980b9",
            command=self.open_home
        )
        self.home_btn.grid(row=1, column=0, padx=15, pady=(5, 8), sticky="ew")

        self.yaml_dropdown = ctk.CTkOptionMenu(
            self.sidebar,
            values=["Select file ⬇️"] + (self.available_titles or []),
            command=self.on_yaml_selected,
            font=ctk.CTkFont(size=13),
            width=200,
            height=32
        )
        # only shown on Home

        self.menu_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.menu_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
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

    # ------------------------------------------------------------------
    # Home
    # ------------------------------------------------------------------
    def open_home(self):
        self.current_title = None
        self.current_yaml = None
        self.expanded_items.clear()
        self.current_item = None
        self.variables = {}
        self.default_variables = {}

        for widget in self.menu_frame.winfo_children():
            widget.destroy()

        self.show_normal_view()

        self.yaml_dropdown.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")
        self.yaml_dropdown.set("Select file ⬇️")

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

        self.play_button.grid_remove()
        self.output_label.grid_remove()
        self.output_text.grid_remove()

        self.summary_text.configure(height=350)
        self.normal_view.grid_rowconfigure(2, weight=1)
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 25), sticky="nsew")

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
        if selected_title == "Select file ⬇️" or selected_title == self.current_title:
            return

        self.current_title = selected_title
        self.current_yaml = self.yaml_map.get(selected_title)
        if not self.current_yaml:
            return

        self.yaml_dropdown.grid_remove()

        data = self.load_yaml(self.current_yaml)
        self.menu_data = data
        self.title(data.get("title", "YAML Menu"))

        # Load Variables that belong to THIS yaml
        self.variables = data.get("Variables", {}) or {}
        self.default_variables = copy.deepcopy(self.variables)

        self.expanded_items.clear()
        self.current_item = None
        self.refresh_menu()

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

        self.page_title = ctk.CTkLabel(
            self.normal_view, text="Home",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        self.page_title.grid(row=0, column=0, padx=30, pady=(25, 5), sticky="w")

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

        self.play_button = ctk.CTkButton(
            self.normal_view, text="▶  Run Script",
            font=ctk.CTkFont(size=16, weight="bold"), height=45,
            command=self.on_play_clicked, state="disabled",
            fg_color=("gray70", "gray40"), hover_color=("gray60", "gray35"),
            text_color=("gray40", "gray80")
        )
        self.play_button.grid(row=3, column=0, padx=30, pady=(0, 15), sticky="ew")

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

        ctk.CTkButton(btn_frame, text="➕  Add Variable", width=140,
                      command=self.add_variable).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="💾  Save", width=100, fg_color="#2ecc71",
                      hover_color="#27ae60", command=self.save_variables).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="↩  Return to Default", width=160,
                      fg_color="#e67e22", hover_color="#d35400",
                      command=self.reset_to_default).pack(side="left")

        self.vars_scroll = ctk.CTkScrollableFrame(self.variables_view)
        self.vars_scroll.grid(row=2, column=0, padx=30, pady=(5, 25), sticky="nsew")
        self.vars_scroll.grid_columnconfigure(1, weight=1)

    def show_normal_view(self):
        self.variables_view.grid_forget()
        self.normal_view.grid(row=0, column=0, sticky="nsew")

    def show_variables_view(self):
        self.normal_view.grid_forget()
        self.variables_view.grid(row=0, column=0, sticky="nsew")
        self.refresh_variables_list()

    # ------------------------------------------------------------------
    # Variables Modification (per-YAML)
    # ------------------------------------------------------------------
    def save_variables(self):
        """Write the current variables back into the loaded YAML under the Variables: key."""
        if not self.current_yaml:
            print("No YAML file is currently loaded – cannot save variables.")
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

        # Re-load the whole file, update Variables, write it back
        try:
            with open(self.current_yaml, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            data["Variables"] = self.variables

            with open(self.current_yaml, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

            self.default_variables = copy.deepcopy(self.variables)
            print(f"Variables saved into {self.current_yaml}")
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
                row, text="🗑", width=40, fg_color="#e74c3c", hover_color="#c0392b",
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
            self.sidebar.configure(width=60)
            self.home_btn.grid_remove()
            self.yaml_dropdown.grid_remove()
            self.menu_frame.grid_remove()
            self.toggle_btn.configure(text="»")
            self.sidebar_expanded = False
        else:
            self.sidebar.configure(width=self.sidebar_width)
            self.home_btn.grid()
            if self.current_title is None:
                self.yaml_dropdown.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")
            self.menu_frame.grid()
            self.toggle_btn.configure(text="☰")
            self.sidebar_expanded = True

    def refresh_menu(self):
        for widget in self.menu_frame.winfo_children():
            widget.destroy()
        self._build_menu_recursive(self.menu_data.get("menu", []), self.menu_frame, level=0)

    def _build_menu_recursive(self, items, parent, level=0, path=""):
        for index, item in enumerate(items):
            has_children = bool(item.get("children"))
            item_id = f"{path}/{index}" if path else str(index)

            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=1)
            row.grid_columnconfigure(1, weight=1)

            if has_children:
                is_open = item_id in self.expanded_items
                arrow = "▼" if is_open else "▶"
                arrow_btn = ctk.CTkButton(
                    row, text=arrow, width=28, height=32, font=ctk.CTkFont(size=12),
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
                    row, text=f"{item.get('icon', '')}  {item['label']}".strip(),
                    anchor="w", height=32, fg_color="transparent",
                    text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                    font=ctk.CTkFont(size=14 if level == 0 else 13),
                    command=lambda i=item, iid=item_id: self.on_category_click(i, iid)
                )
            else:
                btn = ctk.CTkButton(
                    row, text=f"{item.get('icon', '')}  {item['label']}".strip(),
                    anchor="w", height=32, fg_color="transparent",
                    text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                    font=ctk.CTkFont(size=14 if level == 0 else 13),
                    command=lambda i=item: self.on_item_click(i)
                )
            btn.grid(row=0, column=1, sticky="ew", padx=(2, 8))

            if has_children and item_id in self.expanded_items:
                self._build_menu_recursive(item["children"], parent, level + 1, item_id)

    def toggle_item(self, item_id):
        if item_id in self.expanded_items:
            self.expanded_items.discard(item_id)
        else:
            self.expanded_items.add(item_id)
        self.refresh_menu()

    def on_category_click(self, item, item_id):
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

        self.play_button.grid()
        self.output_label.grid()
        self.output_text.grid()

        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", "This is a category. Expand it to see scripts.")
        self.output_text.configure(state="disabled")
        self.set_play_button_enabled(False)

        self.toggle_item(item_id)

    # ------------------------------------------------------------------
    # Item handling
    # ------------------------------------------------------------------
    def set_play_button_enabled(self, enabled: bool):
        if enabled:
            self.play_button.configure(
                state="normal", text="▶  Run Script",
                fg_color="#2ecc71", hover_color="#27ae60", text_color="white"
            )
        else:
            self.play_button.configure(
                state="disabled", text="▶  Run Script",
                fg_color=("gray70", "gray40"), hover_color=("gray60", "gray35"),
                text_color=("gray40", "gray80")
            )

    def on_item_click(self, item):
        if item.get("special") == "variables_editor":
            self.show_variables_view()
            return

        self.show_normal_view()
        self.current_item = item

        label = item.get("label", "Untitled")
        content = item.get("content", "No description available.")
        has_action = bool(item.get("action"))

        self.page_title.configure(text=label)

        self.summary_text.configure(height=90)
        self.normal_view.grid_rowconfigure(2, weight=0)
        self.summary_text.grid(row=2, column=0, padx=30, pady=(5, 15), sticky="ew")

        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", content)
        self.summary_text.configure(state="disabled")

        self.play_button.grid()
        self.output_label.grid()
        self.output_text.grid()

        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")

        if has_action:
            self.output_text.insert("1.0", "Press the green button to run this script.")
            self.set_play_button_enabled(True)
        else:
            self.output_text.insert("1.0", "This item has no script to run.")
            self.set_play_button_enabled(False)

        self.output_text.configure(state="disabled")

    def on_play_clicked(self):
        if not self.current_item:
            return
        action = self.current_item.get("action")
        if not action:
            return

        self.play_button.configure(state="disabled", text="Running...", fg_color="#f39c12")
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", "Running script...\n")
        self.output_text.configure(state="disabled")
        self.update()

        self.run_action(action)
        self.set_play_button_enabled(True)

    def run_action(self, action):
        action = action.strip()
        output = []
        try:
            if action.endswith(".py") and Path(action).exists():
                result = subprocess.run(
                    [sys.executable, action], capture_output=True, text=True, cwd=Path.cwd()
                )
                if result.stdout:
                    output.append(result.stdout)
                if result.stderr:
                    output.append("STDERR:\n" + result.stderr)
                if result.returncode != 0:
                    output.append(f"\n[Process exited with code {result.returncode}]")
            else:
                buffer = StringIO()
                with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                    # Make the current Variables available to the executed code
                    exec(action, {"__name__": "__main__", "Variables": self.variables})
                captured = buffer.getvalue()
                output.append(captured if captured else "(Code ran successfully – no output)")
        except Exception as e:
            output.append(f"Error running action:\n{e}")

        final_text = "\n".join(output).strip() or "(No output)"
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", final_text)
        self.output_text.configure(state="disabled")

if __name__ == "__main__":
    app = YamlMenuApp()
    app.mainloop()