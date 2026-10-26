"""Home preferences and copyable client hosts-file instructions."""
import ipaddress
from tkinter import filedialog, messagebox

import customtkinter as ctk

from execution_engines.domains import hosts_entries, load_domain, normalize_domain


def _present(dialog, app):
    if not dialog.winfo_exists():
        return
    dialog.update_idletasks()
    width, height = dialog.winfo_width(), dialog.winfo_height()
    x = min(max(20, app.winfo_rootx() + (app.winfo_width() - width) // 2),
            max(20, dialog.winfo_screenwidth() - width - 20))
    y = min(max(40, app.winfo_rooty() + (app.winfo_height() - height) // 2),
            max(40, dialog.winfo_screenheight() - height - 60))
    dialog.geometry(f"+{x}+{y}")
    dialog.lift()


class HomeOptions(ctk.CTkToplevel):
    def __init__(self, app, theme_choices):
        super().__init__(app)
        self.title("Home Options")
        self.geometry("680x640")
        self.minsize(600, 600)
        self.transient(app)
        content = ctk.CTkFrame(self, corner_radius=14)
        content.pack(fill="both", expand=True, padx=18, pady=18)
        content.grid_columnconfigure(1, weight=1)
        theme = ctk.StringVar(value=app.ui_settings["theme"])
        appearance = ctk.StringVar(value=app.ui_settings["appearance"])
        background = ctk.StringVar(value=app.ui_settings.get("home_background", ""))
        try:
            saved_domain = load_domain(app.execution_engine.base_dir)
        except (ValueError, OSError) as exc:
            saved_domain = ""
            messagebox.showerror("Domain settings", str(exc), parent=self)
        domain = ctk.StringVar(value=saved_domain)
        ctk.CTkLabel(content, text="Make this workspace yours", font=ctk.CTkFont(size=23, weight="bold")).grid(
            row=0, column=0, columnspan=3, padx=20, pady=(22, 18), sticky="w")
        for row, label in ((1, "Theme"), (2, "Appearance"), (3, "Home background"), (5, "Optional domain")):
            ctk.CTkLabel(content, text=label, font=ctk.CTkFont(weight="bold")).grid(
                row=row, column=0, padx=(20, 12), pady=9, sticky="w")
        ctk.CTkOptionMenu(content, values=list(theme_choices), variable=theme, dynamic_resizing=False).grid(
            row=1, column=1, columnspan=2, padx=(8, 20), pady=9, sticky="ew")
        ctk.CTkOptionMenu(content, values=["System", "Dark", "Light"], variable=appearance).grid(
            row=2, column=1, columnspan=2, padx=(8, 20), pady=9, sticky="ew")
        ctk.CTkEntry(content, textvariable=background).grid(row=3, column=1, padx=(8, 8), pady=9, sticky="ew")

        def browse():
            path = filedialog.askopenfilename(parent=self, title="Choose Home background",
                                              filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")])
            if path:
                background.set(path)

        ctk.CTkButton(content, text="Browse", width=80, command=browse).grid(row=3, column=2, padx=(0, 20))
        ctk.CTkButton(content, text="Clear background", fg_color="transparent", width=150,
                      command=lambda: background.set("")).grid(row=4, column=1, padx=8, sticky="w")
        self.domain_entry = ctk.CTkEntry(content, textvariable=domain)
        self.domain_entry.grid(row=5, column=1, columnspan=2, padx=(8, 20), pady=9, sticky="ew")
        ctk.CTkLabel(content, text="Example: ggsec.org → openproject.ggsec.org, etherpad.ggsec.org.\n"
                     "Blank keeps direct IP-and-port access. Save, then deploy nginx-proxy\nand recreate the services to apply routing.",
                     justify="left", wraplength=570, text_color=("#52647b", "#a5b4c8"),
                     font=ctk.CTkFont(size=12)).grid(row=6, column=0, columnspan=3, padx=20, pady=(5, 12), sticky="w")

        def show_hosts():
            try:
                value = normalize_domain(domain.get())
                if not value:
                    raise ValueError("Enter a domain first, for example ggsec.org.")
            except ValueError as exc:
                messagebox.showerror("Domain", str(exc), parent=self)
                return
            HostsFileDialog(app, value)

        ctk.CTkButton(content, text="Client hosts-file entries", command=show_hosts,
                      fg_color=("#e1ebf4", "#293e56"), text_color=("#1a314b", "#edf5ff")).grid(
                          row=7, column=0, columnspan=3, padx=20, pady=(0, 12), sticky="ew")
        ctk.CTkLabel(content, text="Appearance updates now. Color themes apply next launch.",
                     font=ctk.CTkFont(size=11), text_color=("#52647b", "#a5b4c8")).grid(
                         row=8, column=0, columnspan=3, padx=20, pady=(0, 8), sticky="w")
        ctk.CTkButton(content, text="Save Options", height=38, fg_color="#218c80", hover_color="#18756c",
                      command=lambda: app.save_ui_options(self, theme.get(), appearance.get(), background.get(), domain.get())).grid(
                          row=9, column=0, columnspan=3, padx=20, pady=(0, 20), sticky="ew")
        self.after(100, lambda: _present(self, app))


class HostsFileDialog(ctk.CTkToplevel):
    def __init__(self, app, domain):
        super().__init__(app)
        self.title("Client hostname setup")
        self.geometry("730x600")
        self.minsize(600, 500)
        self.transient(app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(self, text="Point each client at your lab", font=ctk.CTkFont(size=23, weight="bold")).grid(
            row=0, column=0, padx=24, pady=(22, 10), sticky="w")
        ctk.CTkLabel(self, text="Windows: C:\\Windows\\System32\\drivers\\etc\\hosts   •   Linux/macOS: /etc/hosts\n"
                     "Add every hostname explicitly on each client. Hosts files have no wildcard entries.\n"
                     "Use the server's reachable LAN IP. This window only prepares text to copy.",
                     justify="left", wraplength=640, font=ctk.CTkFont(size=12)).grid(
                         row=1, column=0, padx=24, pady=(0, 14), sticky="w")
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=2, column=0, padx=24, sticky="ew")
        controls.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(controls, text="Server IP").grid(row=0, column=0, padx=(0, 12))
        address = getattr(getattr(app, "home_dashboard", None), "_host_address", None) or ""
        self.address_entry = ctk.CTkEntry(controls)
        self.address_entry.insert(0, address)
        self.address_entry.grid(row=0, column=1, sticky="ew")
        output = ctk.CTkTextbox(self, wrap="none", font=ctk.CTkFont(family="Consolas", size=13))
        output.grid(row=3, column=0, padx=24, pady=14, sticky="nsew")
        self.output = output
        self.domain = domain

        def refresh(show_error=True):
            try:
                value = self.address_entry.get().strip()
                ip = ipaddress.ip_address(value)
                if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
                    raise ValueError("Use a server LAN address clients can reach.")
                text = hosts_entries(value, domain)
            except ValueError as exc:
                if show_error:
                    messagebox.showerror("Server IP", str(exc), parent=self)
                return ""
            output.configure(state="normal")
            output.delete("1.0", "end")
            output.insert("1.0", text)
            output.configure(state="disabled")
            return text

        def copy():
            text = refresh()
            if text:
                self.clipboard_clear()
                self.clipboard_append(text)

        ctk.CTkButton(controls, text="Update", width=90, command=refresh).grid(row=0, column=2, padx=(10, 0))
        ctk.CTkLabel(self, text="Browse with http://, for example http://openproject." + domain + "/\n"
                     "HTTP port 80 and the proxy must be reachable. Zulip keeps its separate HTTPS endpoint.",
                     justify="left", wraplength=640, font=ctk.CTkFont(size=12), text_color=("#52647b", "#a5b4c8")).grid(
                         row=4, column=0, padx=24, pady=(0, 12), sticky="w")
        ctk.CTkButton(self, text="Copy hosts entries", command=copy, fg_color="#218c80", hover_color="#18756c").grid(
            row=5, column=0, padx=24, pady=(0, 24), sticky="e")
        refresh(False)
        self.after(100, lambda: _present(self, app))
