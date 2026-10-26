"""Scrollable pages with support for Linux/X11 mouse wheels."""
import sys

import customtkinter as ctk


class ScrollablePage(ctk.CTkScrollableFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._wheel_bindings = []
        if sys.platform.startswith("linux"):
            window = self.winfo_toplevel()
            for sequence in ("<Button-4>", "<Button-5>"):
                binding = window.bind(sequence, self._linux_mouse_wheel, add="+")
                self._wheel_bindings.append((window, sequence, binding))

    def _linux_mouse_wheel(self, event):
        if not self.winfo_ismapped() or not self.check_if_master_is_canvas(event.widget):
            return
        if self._parent_canvas.yview() != (0.0, 1.0):
            self._parent_canvas.yview_scroll(-3 if event.num == 4 else 3, "units")

    def destroy(self):
        for window, sequence, binding in self._wheel_bindings:
            window.unbind(sequence, binding)
        super().destroy()
