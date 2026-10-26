"""Collection and section landing pages for the native desktop toolbox."""

import re
from collections import Counter

import customtkinter as ctk
from ui.scrolling import ScrollablePage


COLLECTION_STYLES = {
    "deployment": ("deployment", "#3989db", "Bring your lab services online."),
    "training": ("learning", "#28a899", "Replay traffic and explore hands-on host exercises."),
    "troubleshooting": ("readiness", "#c78f42", "Find answers on local and remote hosts."),
    "capture": ("network", "#9c83da", "Record network traffic from this computer."),
    "tools": ("folder", "#538ec7", "Share files and reach for everyday utilities."),
}


def plain_text(value):
    """Make short Markdown descriptions readable without changing the full guide."""
    text = str(value or "").strip()
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return " ".join(text.split())


def content_summary(content, fallback="", limit=230):
    """Use the first body paragraph, skipping a leading Markdown title."""
    lines = str(content or "").strip().splitlines()
    while lines and (not lines[0].strip() or re.match(r"^\s*#{1,6}\s", lines[0])):
        lines.pop(0)
    paragraphs = re.split(r"\n\s*\n", "\n".join(lines).strip())
    summary = plain_text(paragraphs[0]) if paragraphs else ""
    summary = summary or fallback
    if len(summary) > limit:
        # Keep words intact even when YAML contains a long first paragraph.
        shortened = summary[:max(1, limit - 1)].rsplit(" ", 1)[0]
        summary = (shortened or summary[:max(1, limit - 1)]).rstrip(" ,;:") + "…"
    return summary


def item_kind(item):
    """Classify destinations for accurate counts and non-executing card labels."""
    special = item.get("special")
    if special in {"variables_editor", "container_settings", "menu_visibility"}:
        return "settings page"
    if special == "backup_selector":
        return "section"
    if "children" in item and not item.get("action_id") and not special:
        return "section"
    if item.get("action_id") or special in {"capture_dialog", "image_selector"}:
        return "action"
    if special in {"open_share_folder", "moodle_admin_password"}:
        return "tool"
    return "page"


def destination_counts(items):
    counts = Counter(item_kind(item) for item in items)
    parts = []
    for kind in ("section", "action", "settings page", "tool", "page"):
        count = counts[kind]
        if count:
            parts.append(f"{count} {kind if count == 1 else kind + 's'}")
    return " · ".join(parts) or "No visible items"


def card_description(item):
    kind = item_kind(item)
    if kind == "section":
        children = item.get("children") or []
        if item.get("special") == "backup_selector":
            fallback = "Browse saved backups and review the available restore actions."
        else:
            fallback = (f"Explore {destination_counts(children).lower()} in this section."
                        if children else "Open this section to see its available items.")
    else:
        fallback = {
            "settings page": "Review and adjust the settings for this workspace.",
            "action": "Open the action to review its details and available options.",
            "tool": "Open this tool and review the available options.",
            "page": "Read more about this part of the toolbox.",
        }[kind]
    return content_summary(item.get("content"), fallback, limit=170)


class CollectionPage(ScrollablePage):
    """A reusable landing page; every destination is opened through the app."""

    def __init__(self, parent, *, get_icon):
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.get_icon = get_icon
        self.surface = ("#ffffff", "#1c2533")
        self.muted = ("#52647b", "#a5b4c8")
        self.ink = ("#1a314b", "#edf5ff")
        self.border = ("#dfe6ee", "#2c3a4e")
        self.body = None
        self.cards = []
        self._narrow = None
        self._layout_width = 700
        self.bind("<Configure>", self._adapt_layout, add="+")

    def show(self, title, content, items, collection, on_select, guide="", on_back=None):
        # Reuse the scroll frame itself: CTk binds its canvas to global wheel events.
        if self.body is not None:
            self.body.destroy()
        self.cards = []
        self._narrow = None
        self.body = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.body.grid(row=0, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        self._parent_canvas.yview_moveto(0)
        items = list(items)
        collection = str(collection or "Toolbox")
        title = plain_text(title) or collection
        icon, accent, fallback = COLLECTION_STYLES.get(
            collection.casefold(), ("folder", "#538ec7", "Choose a section or explore the available tools."))

        if on_back is not None:
            ctk.CTkButton(
                self.body, text=f"← All {collection}", anchor="w", width=150, height=32,
                fg_color="transparent", hover_color=("#e5eef7", "#293e56"),
                text_color=self.muted, command=on_back,
            ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        hero = ctk.CTkFrame(self.body, fg_color="#142b45", corner_radius=18)
        hero.grid(row=1, column=0, sticky="ew", pady=(0, 24))
        hero.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hero, text=f"  {collection.upper()}  /  WORKSPACE", anchor="w",
            image=self.get_icon(icon), compound="left",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#70d9cf",
        ).grid(row=0, column=0, padx=26, pady=(24, 9), sticky="w")
        self.hero_title = ctk.CTkLabel(
            hero, text=title, anchor="w", justify="left", wraplength=540,
            font=ctk.CTkFont(size=30, weight="bold"), text_color="#f4f8ff",
        )
        self.hero_title.grid(row=1, column=0, padx=26, sticky="w")
        self.hero_summary = ctk.CTkLabel(
            hero, text=content_summary(content, fallback), anchor="w", justify="left",
            wraplength=560, font=ctk.CTkFont(size=13), text_color="#b9cbdf",
        )
        self.hero_summary.grid(row=2, column=0, padx=26, pady=(12, 18), sticky="w")
        self.hero_stats = ctk.CTkLabel(
            hero, text=f"  {destination_counts(items)}  ", anchor="w", height=28,
            corner_radius=6, fg_color="#23425e", text_color="#d4e8f6",
            font=ctk.CTkFont(size=11), wraplength=560,
        )
        self.hero_stats.grid(row=3, column=0, padx=26, pady=(0, 24), sticky="w")
        ctk.CTkFrame(hero, fg_color=accent, height=3, corner_radius=1).grid(
            row=4, column=0, padx=26, pady=(0, 18), sticky="ew")

        ctk.CTkLabel(
            self.body, text="Explore this workspace", anchor="w", text_color=self.ink,
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=2, column=0, sticky="w", pady=(0, 12))
        self.cards_frame = ctk.CTkFrame(self.body, fg_color="transparent", corner_radius=0)
        self.cards_frame.grid(row=3, column=0, sticky="ew")
        self.cards_frame.grid_columnconfigure((0, 1), weight=1, uniform="destinations")
        for item in items:
            self._card(item, icon, accent, on_select)
        if not items:
            empty = ctk.CTkFrame(self.cards_frame, fg_color=self.surface, corner_radius=12,
                                 border_width=1, border_color=self.border)
            empty.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
            ctk.CTkLabel(
                empty, text="No items to show", anchor="w", text_color=self.ink,
                font=ctk.CTkFont(size=17, weight="bold"),
            ).pack(anchor="w", padx=22, pady=(22, 6))
            ctk.CTkLabel(
                empty, text="Items in this section may be hidden. Use Show / Hide Items in the collection menu to adjust visibility.",
                wraplength=450, anchor="w", justify="left", text_color=self.muted,
                font=ctk.CTkFont(size=13),
            ).pack(anchor="w", padx=22, pady=(0, 22))

        full_content = str(content or "").strip()
        if guide and str(guide).strip() != full_content:
            full_content = "\n\n".join(part for part in (full_content, str(guide).strip()) if part)
        self.guide = None
        if full_content:
            self.guide_button = ctk.CTkButton(
                self.body, text="Read full guide  ›", anchor="w", fg_color="transparent",
                hover_color=("#e5eef7", "#293e56"), text_color=self.muted,
                height=36, command=self._toggle_guide,
            )
            self.guide_button.grid(row=4, column=0, sticky="ew", pady=(4, 0))
            self.guide = ctk.CTkTextbox(
                self.body, height=300, wrap="word", fg_color=self.surface,
                border_width=1, border_color=self.border, corner_radius=10,
                font=ctk.CTkFont(size=13),
            )
            self.guide.insert("1.0", full_content)
            self.guide.configure(state="disabled")
        self._layout(self._layout_width)

    def _card(self, item, fallback_icon, accent, on_select):
        card = ctk.CTkFrame(self.cards_frame, fg_color=self.surface, corner_radius=12,
                            border_width=1, border_color=self.border, cursor="hand2")
        card.grid_columnconfigure(1, weight=1)
        card.grid_rowconfigure(1, weight=1)
        callback = lambda event=None: on_select(item)
        image = ctk.CTkLabel(card, text="", image=self.get_icon(item.get("icon") or fallback_icon),
                             width=32, height=32, cursor="hand2")
        image.grid(row=0, column=0, padx=(18, 8), pady=(17, 8), sticky="nw")
        title = ctk.CTkLabel(
            card, text=plain_text(item.get("label")) or "Untitled", text_color=self.ink,
            anchor="w", justify="left", wraplength=210, cursor="hand2",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        title.grid(row=0, column=1, padx=(0, 20), pady=(18, 9), sticky="w")
        description = ctk.CTkLabel(
            card, text=card_description(item), anchor="nw", justify="left", wraplength=255,
            text_color=self.muted, font=ctk.CTkFont(size=12), cursor="hand2",
        )
        description.grid(row=1, column=0, columnspan=2, padx=20, pady=(0, 16), sticky="nw")
        footer = ctk.CTkFrame(card, fg_color="transparent", cursor="hand2")
        footer.grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 17), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        kind = item_kind(item)
        detail = destination_counts(item.get("children") or []) if kind == "section" else {
            "settings page": "Settings", "action": "Action details", "tool": "Utility", "page": "Guide",
        }[kind]
        if item.get("special") == "backup_selector" and not item.get("children"):
            detail = "Saved backups"
        badge = ctk.CTkLabel(footer, text=detail, anchor="w", text_color=self.muted,
                             font=ctk.CTkFont(size=10), cursor="hand2")
        badge.grid(row=0, column=0, sticky="w")
        button_text = {"section": "Explore", "settings page": "Open settings", "action": "View action",
                       "tool": "Open tool", "page": "Read more"}[kind]
        ctk.CTkButton(
            footer, text=button_text, width=100, height=30, corner_radius=7,
            fg_color=("#e5eef7", "#293e56"), hover_color=("#d6e5f2", "#35516e"),
            text_color=self.ink, font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: on_select(item),
        ).grid(row=0, column=1, padx=(8, 0), sticky="e")
        ctk.CTkFrame(card, height=3, fg_color=accent, corner_radius=1).grid(
            row=3, column=0, columnspan=2, padx=20, pady=(0, 12), sticky="ew")
        for widget in (card, image, title, description, footer, badge):
            widget.bind("<Button-1>", callback, add="+")
        self.cards.append((card, title, description, badge))

    def _adapt_layout(self, event):
        self._layout(self._reverse_widget_scaling(event.width))

    def _layout(self, width):
        self._layout_width = width
        if self.body is None:
            return
        narrow = width < 680
        if narrow != self._narrow:
            self._narrow = narrow
            for index, (card, _, _, _) in enumerate(self.cards):
                card.grid(row=index if narrow else index // 2,
                          column=0 if narrow else index % 2, columnspan=2 if narrow else 1,
                          padx=0 if narrow else ((0, 7) if index % 2 == 0 else (7, 0)),
                          pady=(0, 12), sticky="nsew")
        self.hero_title.configure(wraplength=max(200, width - 66))
        self.hero_summary.configure(wraplength=max(200, width - 66))
        self.hero_stats.configure(wraplength=max(200, width - 66))
        card_width = width if narrow else (width - 14) / 2
        for _, title, description, badge in self.cards:
            title.configure(wraplength=max(120, card_width - 86))
            description.configure(wraplength=max(150, card_width - 46))
            badge.configure(wraplength=max(85, card_width - 170))

    def _toggle_guide(self):
        if self.guide is None:
            return
        if self.guide.winfo_manager():
            self.guide.grid_remove()
            self.guide_button.configure(text="Read full guide  ›")
        else:
            self.guide.grid(row=5, column=0, sticky="ew", pady=(8, 18))
            self.guide_button.configure(text="Hide full guide  ⌄")
