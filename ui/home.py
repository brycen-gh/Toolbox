"""The desktop landing page, with local, read-only host capability checks."""
import platform
from queue import Empty, Queue
import threading
from tkinter import TclError

import customtkinter as ctk
from ui.scrolling import ScrollablePage

from execution_engines.capabilities import capability_snapshot
from execution_engines.network import detect_host_address, usable_address
from execution_engines.runtime import is_portable


class ToolboxHome(ScrollablePage):
    def __init__(self, parent, *, base_dir, navigate, open_folder, get_icon, guide):
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        self.grid_columnconfigure((0, 1), weight=1, uniform="home")
        self.base_dir = base_dir
        self.navigate = navigate
        self.get_icon = get_icon
        self.muted = ("#52647b", "#a5b4c8")
        self.surface = ("#ffffff", "#1c2533")
        self.tiles = []
        self._narrow = None
        self._host_address = None
        self._network_events = Queue()
        self._network_lookup_running = False
        self._network_poll_id = None
        self._network_closed = False

        hero = ctk.CTkFrame(self, fg_color="#142b45", corner_radius=18)
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 22))
        hero.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hero, text="TOOLBOX  /  YOUR LAB, WITH YOU", anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold"), text_color="#70d9cf").grid(
                         row=0, column=0, padx=26, pady=(24, 9), sticky="w")
        ctk.CTkLabel(hero, text="A familiar workspace.\nOn every machine.", anchor="w", justify="left",
                     font=ctk.CTkFont(size=30, weight="bold"), text_color="#f4f8ff").grid(
                         row=1, column=0, padx=26, sticky="w")
        ctk.CTkLabel(hero, text="Deploy services. Explore traffic. Keep work moving.",
                     font=ctk.CTkFont(size=13), text_color="#b9cbdf", anchor="w").grid(
                         row=2, column=0, padx=26, pady=(12, 18), sticky="w")
        mode = "PORTABLE" if is_portable(base_dir) else "SOURCE"
        ctk.CTkLabel(hero, text=f"  {mode}   /   {platform.system()} {platform.machine()}  ",
                     corner_radius=6, fg_color="#23425e", text_color="#d4e8f6",
                     font=ctk.CTkFont(size=11), height=28).grid(
                         row=3, column=0, padx=26, pady=(0, 24), sticky="w")

        network = ctk.CTkFrame(hero, fg_color="#1b3a55", corner_radius=12,
                               border_width=1, border_color="#2d506b")
        network.grid(row=4, column=0, padx=22, pady=(0, 22), sticky="ew")
        network.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(network, text="HOST IPv4", anchor="w", text_color="#8fcfcf",
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(12, 0), sticky="w")
        self.network_address_label = ctk.CTkLabel(
            network, text="Detecting…", anchor="w", text_color="#f4f8ff",
            font=ctk.CTkFont(family="Consolas", size=23, weight="bold"))
        self.network_address_label.grid(row=1, column=0, padx=16, sticky="w")
        self.network_source_label = ctk.CTkLabel(
            network, text="Checking this computer's network adapters.", anchor="w", justify="left",
            wraplength=560, text_color="#b9cbdf", font=ctk.CTkFont(size=11))
        self.network_source_label.grid(row=2, column=0, columnspan=2,
                                       padx=16, pady=(3, 13), sticky="w")
        self.network_controls = ctk.CTkFrame(network, fg_color="transparent")
        self.network_controls.grid(row=0, column=1, rowspan=2,
                                   padx=(4, 16), pady=(15, 0), sticky="e")
        self.copy_ip_button = ctk.CTkButton(
            self.network_controls, text="Copy IP", width=86, height=32, corner_radius=7,
            fg_color="#75dbca", hover_color="#94e6d8", text_color="#12373c",
            text_color_disabled="#77949c", font=ctk.CTkFont(size=11, weight="bold"),
            state="disabled", command=self._copy_ip)
        self.copy_ip_button.grid(row=0, column=0, padx=(0, 7))
        self.refresh_ip_button = ctk.CTkButton(
            self.network_controls, text="Refresh", width=80, height=32, corner_radius=7,
            fg_color="#2b4d69", hover_color="#3c627f", text_color="#e1edf8",
            text_color_disabled="#9db4c9", font=ctk.CTkFont(size=11),
            command=self._refresh_network)
        self.refresh_ip_button.grid(row=0, column=1)

        self._heading("Choose your next move", row=1)
        collections = (
            ("Deployment", "deployment", "Bring your lab services online.", "#3989db"),
            ("Training", "learning", "Replay traffic and run host exercises.", "#28a899"),
            ("Troubleshooting", "readiness", "Find answers on local and remote hosts.", "#c78f42"),
            ("Capture", "network", "Record traffic from available interfaces.", "#9c83da"),
            ("Tools", "folder", "Share files and reach for everyday utilities.", "#538ec7"),
        )
        for index, (title, icon, description, accent) in enumerate(collections):
            tile = ctk.CTkFrame(self, fg_color=self.surface, corner_radius=12,
                               border_width=1, border_color=("#dfe6ee", "#2c3a4e"))
            tile.grid(row=2 + index // 2, column=index % 2, sticky="nsew",
                      padx=(0, 7) if index % 2 == 0 else (7, 0), pady=(0, 12))
            tile.grid_columnconfigure(0, weight=1)
            self.tiles.append(tile)
            ctk.CTkButton(tile, text=title, image=get_icon(icon), anchor="w", compound="left",
                          fg_color="transparent", hover_color=("#edf3f9", "#27354a"),
                          text_color=("#1a314b", "#edf5ff"), height=42,
                          font=ctk.CTkFont(size=16, weight="bold"),
                          command=lambda value=title: navigate(value)).grid(
                              row=0, column=0, padx=12, pady=(10, 0), sticky="ew")
            ctk.CTkLabel(tile, text=description, anchor="w", justify="left", wraplength=235,
                         text_color=self.muted, font=ctk.CTkFont(size=12)).grid(
                             row=1, column=0, padx=20, pady=(0, 15), sticky="w")
            ctk.CTkFrame(tile, height=3, fg_color=accent, corner_radius=1).grid(
                row=2, column=0, padx=20, pady=(0, 12), sticky="ew")

        files = ctk.CTkFrame(self, fg_color=self.surface, corner_radius=12)
        self.tiles.append(files)
        files.grid(row=4, column=1, sticky="nsew", padx=(7, 0), pady=(0, 12))
        ctk.CTkLabel(files, text="Take your workspace along", text_color=self.muted,
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=20, pady=(18, 6))
        ctk.CTkButton(files, text="Open Toolbox folder", image=get_icon("folder"),
                      height=34, fg_color=("#e5eef7", "#293e56"),
                      text_color=("#1a314b", "#edf5ff"), command=open_folder).pack(
                          anchor="w", padx=20, pady=(0, 18))

        host_heading = self._heading("On this computer", row=5)
        host = ctk.CTkFrame(self, fg_color=self.surface, corner_radius=12)
        host.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        host.grid_columnconfigure((0, 1), weight=1, uniform="capabilities")
        by_key = {item.key: item for item in capability_snapshot()}
        self.status_labels = {}
        self.host_cells = []
        for index, key in enumerate(("docker", "powershell", "wsl", "tcpdump", "tcpreplay", "git")):
            item = by_key[key]
            cell = ctk.CTkFrame(host, fg_color="transparent")
            cell.grid(row=index // 2, column=index % 2, padx=18, pady=(12, 3), sticky="ew")
            cell.grid_columnconfigure(0, weight=1)
            self.host_cells.append(cell)
            ctk.CTkLabel(cell, text=item.label, anchor="w", font=ctk.CTkFont(size=13)).grid(
                row=0, column=0, sticky="w")
            status = ctk.CTkLabel(cell, text="Detected" if item.available else "Unavailable",
                                  text_color=("#167468", "#6ed4bc") if item.available else self.muted,
                                  font=ctk.CTkFont(size=11))
            status.grid(row=0, column=1, padx=(6, 0))
            self.status_labels[key] = status
        self.host_note = ctk.CTkLabel(host, text="Tool detection only. Connections and permissions are checked when you run an action.",
                     wraplength=560, justify="left", anchor="w", text_color=self.muted,
                     font=ctk.CTkFont(size=11))
        self.host_note.grid(row=3, column=0, columnspan=2, padx=18, pady=(10, 16), sticky="w")

        location_heading = self._heading("Workspace location", row=7)
        location = ctk.CTkTextbox(self, height=48, fg_color=self.surface, corner_radius=9,
                                 font=ctk.CTkFont(size=12), wrap="word")
        location.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        location.insert("1.0", str(base_dir))
        location.configure(state="disabled")
        guide_button = ctk.CTkButton(self, text="Getting started & lab guide", anchor="w", fg_color="transparent",
                      text_color=self.muted, hover_color=("#e5eef7", "#293e56"),
                      command=self._toggle_guide)
        guide_button.grid(row=9, column=0, columnspan=2, sticky="ew")
        self.guide = ctk.CTkTextbox(self, height=300, wrap="word", fg_color=self.surface,
                                    font=ctk.CTkFont(size=13))
        self.guide.insert("1.0", guide)
        self.guide.configure(state="disabled")
        self.following = ((host_heading, 5), (host, 6), (location_heading, 7), (location, 8), (guide_button, 9))
        self.bind("<Configure>", self._adapt_layout, add="+")
        self.bind("<Destroy>", self._stop_network_poll, add="+")
        self._refresh_network()

    def refresh(self, guide):
        for item in capability_snapshot():
            if item.key in self.status_labels:
                self.status_labels[item.key].configure(
                    text="Detected" if item.available else "Unavailable",
                    text_color=("#167468", "#6ed4bc") if item.available else self.muted)
        self.guide.configure(state="normal")
        self.guide.delete("1.0", "end")
        self.guide.insert("1.0", guide)
        self.guide.configure(state="disabled")
        self._refresh_network()

    def _refresh_network(self):
        """Start one lookup without holding up the Tk event loop."""
        if self._network_closed or self._network_lookup_running:
            return
        self._network_lookup_running = True
        self._host_address = None
        self.network_address_label.configure(text="Detecting…")
        self.network_source_label.configure(text="Checking this computer's network adapters.")
        self.copy_ip_button.configure(state="disabled", text="Copy IP")
        self.refresh_ip_button.configure(state="disabled", text="Checking…")
        threading.Thread(target=self._detect_network, args=(self._network_events,), daemon=True).start()
        self._network_poll_id = self.after(60, self._poll_network)

    @staticmethod
    def _detect_network(events):
        # Workers post data only. Even Tk's after() must stay on the UI thread.
        try:
            address, source = detect_host_address()
            if not isinstance(address, str) or not usable_address(address):
                address = None
            events.put((address, source))
        except Exception:
            events.put((None, "Address lookup failed. Refresh to try again."))

    def _poll_network(self):
        self._network_poll_id = None
        if self._network_closed:
            return
        try:
            address, source = self._network_events.get_nowait()
        except Empty:
            self._network_poll_id = self.after(60, self._poll_network)
            return
        self._network_lookup_running = False
        self._host_address = address
        self.network_address_label.configure(text=address or "No IPv4 detected")
        self.network_source_label.configure(
            text=f"{source} · Use for local lab connections." if address else source)
        self.copy_ip_button.configure(state="normal" if address else "disabled", text="Copy IP")
        self.refresh_ip_button.configure(state="normal", text="Refresh")

    def _copy_ip(self):
        if not self._host_address or not usable_address(self._host_address):
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._host_address)
        except TclError:
            self.network_source_label.configure(text="Clipboard unavailable on this computer.")
        else:
            self.copy_ip_button.configure(text="Copied")

    def _stop_network_poll(self, event):
        if event.widget is self:
            self._network_closed = True
            if self._network_poll_id is not None:
                self.after_cancel(self._network_poll_id)
                self._network_poll_id = None

    def _heading(self, title, *, row):
        label = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=15, weight="bold"), anchor="w")
        label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))
        return label

    def _adapt_layout(self, event):
        narrow = event.width < self._apply_widget_scaling(640)
        if narrow == self._narrow:
            return
        self._narrow = narrow
        for index, tile in enumerate(self.tiles):
            tile.grid_configure(row=2 + (index if narrow else index // 2),
                                column=0 if narrow else index % 2, columnspan=2 if narrow else 1,
                                padx=0 if narrow else ((0, 7) if index % 2 == 0 else (7, 0)))
        for widget, row in self.following:
            widget.grid_configure(row=row + (3 if narrow else 0))
        if self.guide.winfo_manager():
            self.guide.grid_configure(row=13 if narrow else 10)
        for index, cell in enumerate(self.host_cells):
            cell.grid_configure(row=index if narrow else index // 2,
                                column=0 if narrow else index % 2, columnspan=2 if narrow else 1)
        self.host_note.grid_configure(row=6 if narrow else 3)
        self.host_note.configure(wraplength=390 if narrow else 560)
        self.network_controls.grid_configure(
            row=3 if narrow else 0, column=0 if narrow else 1,
            columnspan=2 if narrow else 1, rowspan=1 if narrow else 2,
            padx=16 if narrow else (4, 16), pady=(0, 14) if narrow else (15, 0),
            sticky="w" if narrow else "e")
        self.network_source_label.configure(wraplength=390 if narrow else 560)

    def _toggle_guide(self):
        if self.guide.winfo_manager():
            self.guide.grid_remove()
        else:
            self.guide.grid(row=13 if self._narrow else 10, column=0, columnspan=2, sticky="ew", pady=(8, 16))
