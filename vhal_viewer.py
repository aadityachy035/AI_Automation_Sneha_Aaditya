"""
vhal_viewer.py  -  VHAL UCL Log Viewer
=======================================
Toolbar components:
  1. Search  – live search in signal_names.txt  (up to 10 results, checkboxes)
  2. Load logs – opens file dialog to load a UCL .log file
  3. Timestamp – MM-DD HH:MM:SS.mmm spinboxes + Go button
"""

import os
import sys
import math
import random
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
import threading
import subprocess
import urllib.request
import urllib.error
import json as _json
import vhal_analyzer
# ── No external dependencies (pure tkinter) ───────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
SIGNAL_FILE      = os.path.join(BASE_DIR, "signal_names.txt")
UCL_TEMP_PATH    = os.path.join(BASE_DIR, "ucl_90 1.log")   # temp storage target

# ─────────────────────────────────────────────────────────────────────────────
# COLOUR / FONT TOKENS
# ─────────────────────────────────────────────────────────────────────────────
BG_DARK      = "#0B1121"   # very dark navy/black
BG_PANEL     = "#0F172A"   # slate-900
BG_CARD      = "#1E293B"   # slate-800
ACCENT       = "#3b82f6"   # blue-500
ACCENT2      = "#8b5cf6"   # violet-500
TEXT_LIGHT   = "#f8fafc"   # slate-50
TEXT_DIM     = "#94a3b8"   # slate-400
BORDER       = "#334155"   # slate-700
HIGHLIGHT    = "#3b82f6"   # blue-500
BTN_BG       = "#1E293B"   # slate-800
BTN_HOVER    = "#334155"   # slate-700
BTN_ACTIVE   = "#3b82f6"   # blue-500
INPUT_BG     = "#0B1121"   # very dark navy/black
INPUT_FG     = "#f8fafc"   # slate-50
DROP_BG      = "#0F172A"   # slate-900
DROP_SEL     = "#1E293B"   # slate-800

FONT_UI      = ("Segoe UI", 10)
FONT_BOLD    = ("Segoe UI Semibold", 10)
FONT_SMALL   = ("Segoe UI", 9)
FONT_MONO    = ("Consolas", 9)
FONT_TITLE   = ("Segoe UI Semibold", 12)

# ── Smooth Scrolling Helpers ──────────────────────────────────────────────────
def handle_scroll(event, canvas):
    """Accumulates small scroll deltas (like from trackpads) to ensure smooth scrolling."""
    if not hasattr(canvas, "_scroll_accum"):
        canvas._scroll_accum = 0.0
    canvas._scroll_accum += event.delta
    
    # A standard mouse sends 120. Trackpads send small values (e.g. 5, 12).
    # Using 40 as a threshold gives trackpads responsiveness and makes a standard
    # mouse wheel scroll 3 units per click, which is generally a comfortable speed.
    if abs(canvas._scroll_accum) >= 40:
        steps = int(canvas._scroll_accum / 40)
        canvas.yview_scroll(-1 * steps, "units")
        canvas._scroll_accum -= (steps * 40)

def bind_mousewheel_recursive(widget, canvas):
    """Binds MouseWheel to the widget and all its children to prevent scroll blocking."""
    widget.bind("<MouseWheel>", lambda e: handle_scroll(e, canvas))
    for child in widget.winfo_children():
        bind_mousewheel_recursive(child, canvas)


# ─────────────────────────────────────────────────────────────────────────────
# LOAD SIGNAL LIST
# ─────────────────────────────────────────────────────────────────────────────
def load_signals(path: str) -> list[str]:
    if not os.path.exists(path):
        messagebox.showerror("Missing file", f"signal_names.txt not found:\n{path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH DROPDOWN  (in-window Frame, never steals focus)
# ─────────────────────────────────────────────────────────────────────────────
class SearchDropdown(tk.Frame):
    """
    Dropdown rendered as a place()-positioned Frame INSIDE the root window.
    Focus stays on the Entry at all times → smooth typing.
    """
    def __init__(self, root_window, entry_widget, on_select_cb):
        # Parent is root so place() coordinates are window-relative
        super().__init__(root_window, bg=BORDER)
        self._root       = root_window
        self._entry      = entry_widget
        self._on_select  = on_select_cb
        self._vars       = {}   # signal -> BooleanVar
        self._visible    = False

        # Build inner container once
        outer = tk.Frame(self, bg=DROP_BG)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        self._canvas = tk.Canvas(outer, bg=DROP_BG, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._container = tk.Frame(self._canvas, bg=DROP_BG)
        self._canvas_window = self._canvas.create_window((0, 0), window=self._container, anchor="nw")
        
        self._container.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._canvas_window, width=e.width))
        
        def on_mousewheel(e):
            handle_scroll(e, self._canvas)
        self._canvas.bind("<MouseWheel>", on_mousewheel)
        self._on_mousewheel = on_mousewheel

        # Dismiss on click outside
        root_window.bind("<Button-1>", self._on_root_click, add="+")

    # ── Public API ────────────────────────────────────────────────
    def show(self, results: list[str]):
        self._build_rows(results)
        self._reposition(len(results))
        self.lift()          # always on top of other widgets
        self._visible = True

    def hide(self):
        self.place_forget()
        self._visible = False

    def update_results(self, results: list[str]):
        self._build_rows(results)
        self._reposition(len(results))
        self.lift()

    # ── Internal ──────────────────────────────────────────────────
    def _reposition(self, num_results):
        # Convert entry widget coords → root-window coords
        ex = self._entry.winfo_rootx() - self._root.winfo_rootx()
        ey = self._entry.winfo_rooty() - self._root.winfo_rooty()
        ey += self._entry.winfo_height() + 2
        
        # approximate 28 pixels per row, max 250 pixels height
        h = min((num_results if num_results > 0 else 1) * 28 + 4, 250)
        
        self.place(x=ex, y=ey, width=max(self._entry.winfo_width(), 380), height=h)

    def _build_rows(self, results: list[str]):
        for w in self._container.winfo_children():
            w.destroy()
        self._vars.clear()

        if not results:
            tk.Label(self._container, text="  No matches found",
                     bg=DROP_BG, fg=TEXT_DIM, font=FONT_SMALL,
                     anchor="w", padx=8, pady=6).pack(fill="x")
            return

        for sig in results:
            var = tk.BooleanVar(value=False)
            self._vars[sig] = var

            row = tk.Frame(self._container, bg=DROP_BG, cursor="hand2")
            row.pack(fill="x")

            cb = tk.Checkbutton(
                row, variable=var,
                bg=DROP_BG, fg=TEXT_LIGHT,
                activebackground=DROP_SEL,
                selectcolor=BG_CARD,
                relief="flat", bd=0,
                # takefocus=0 keeps keyboard focus on Entry
                takefocus=0,
                command=lambda s=sig: self._toggle(s)
            )
            cb.pack(side="left", padx=(6, 2), pady=3)

            lbl = tk.Label(
                row, text=sig,
                bg=DROP_BG, fg=TEXT_LIGHT,
                font=FONT_MONO, anchor="w",
                padx=4, pady=3
            )
            lbl.pack(side="left", fill="x", expand=True)

            for widget in (row, lbl, cb):
                widget.bind("<Enter>",    lambda e, r=row, l=lbl: self._hover(r, l, True))
                widget.bind("<Leave>",    lambda e, r=row, l=lbl: self._hover(r, l, False))
                widget.bind("<MouseWheel>", self._on_mousewheel)
                if widget != cb:
                    widget.bind("<Button-1>", lambda e, c=cb: (c.invoke(), self._entry.focus_set()))

    def _toggle(self, sig: str):
        checked = self._vars[sig].get()
        self._on_select(sig, checked)
        # Return focus to entry after clicking checkbox
        self._entry.focus_set()

    def _hover(self, row, lbl, on: bool):
        colour = DROP_SEL if on else DROP_BG
        row.configure(bg=colour)
        lbl.configure(bg=colour)

    def _on_root_click(self, event):
        # Hide if click is outside both the entry and the dropdown
        widget = event.widget
        if widget not in (self._entry,) and not self._is_child(widget):
            self.hide()

    def _is_child(self, widget) -> bool:
        try:
            return str(widget).startswith(str(self))
        except Exception:
            return False


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH WIDGET
# ─────────────────────────────────────────────────────────────────────────────
class SearchWidget(tk.Frame):
    def __init__(self, parent, signals: list[str], on_signals_changed=None, **kwargs):
        super().__init__(parent, bg=BG_DARK, **kwargs)
        self._all_signals = signals
        self._selected    = {}   # signal -> bool
        self._on_changed  = on_signals_changed
        self._dropdown    = None   # created lazily after root exists
        self._build()

    def _build(self):
        # ── Label ─────────────────────────────────────────────────
        tk.Label(self, text="Search", bg=BG_DARK, fg=TEXT_DIM,
                 font=FONT_SMALL).pack(anchor="nw")

        # ── Entry box ─────────────────────────────────────────────
        entry_frame = tk.Frame(self, bg=BORDER, padx=1, pady=1)
        entry_frame.pack(fill="x", pady=(2, 0))

        inner = tk.Frame(entry_frame, bg=INPUT_BG)
        inner.pack(fill="x")

        tk.Label(inner, text="⌕", bg=INPUT_BG, fg=TEXT_DIM,
                 font=("Segoe UI", 12)).pack(side="left", padx=(6, 2))

        self._search_var = tk.StringVar()
        self._entry = tk.Entry(
            inner,
            textvariable=self._search_var,
            bg=INPUT_BG, fg=INPUT_FG,
            insertbackground=ACCENT,
            relief="flat",
            font=FONT_UI,
            width=28
        )
        self._entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))

        # Bind AFTER pack so winfo_* work correctly
        self._search_var.trace_add("write", self._on_type)
        self._entry.bind("<Escape>", lambda e: self._clear())
        self._entry.bind("<FocusIn>", self._on_focus_in)

        # Clear (X) button
        clear_btn = tk.Label(inner, text="x", bg=INPUT_BG, fg=TEXT_DIM,
                             font=FONT_SMALL, cursor="hand2", padx=6)
        clear_btn.pack(side="right")
        clear_btn.bind("<Button-1>", lambda e: self._clear())
        clear_btn.bind("<Enter>", lambda e: clear_btn.configure(fg=TEXT_LIGHT))
        clear_btn.bind("<Leave>", lambda e: clear_btn.configure(fg=TEXT_DIM))

    # ── Dropdown lifecycle ────────────────────────────────────────
    def _get_dropdown(self) -> "SearchDropdown":
        """Create dropdown once the root window exists."""
        if self._dropdown is None:
            root = self.winfo_toplevel()
            self._dropdown = SearchDropdown(
                root, self._entry,
                on_select_cb=self._on_signal_toggled
            )
        return self._dropdown

    def _on_type(self, *_args):
        query = self._search_var.get().strip().lower()
        if not query:
            self._get_dropdown().hide()
            return
        matches = [s for s in self._all_signals if query in s.lower()][:100]
        dd = self._get_dropdown()
        if matches or query:
            dd.update_results(matches)
            dd.show(matches)
        # Keep focus on entry (trace_add can sometimes lose it)
        self._entry.after_idle(self._entry.focus_set)

    def _on_focus_in(self, _event=None):
        # Re-show dropdown if there's already text
        if self._search_var.get().strip():
            self._on_type()

    def _on_signal_toggled(self, signal: str, checked: bool):
        self._selected[signal] = checked
        if self._on_changed:
            self._on_changed(self.get_selected())

    def _clear(self):
        self._search_var.set("")
        if self._dropdown:
            self._dropdown.hide()
        self._entry.focus_set()

    def get_selected(self) -> list[str]:
        return [s for s, v in self._selected.items() if v]

    def uncheck_signal(self, signal: str):
        if signal in self._selected:
            self._selected[signal] = False
            if self._dropdown and signal in self._dropdown._vars:
                self._dropdown._vars[signal].set(False)
            if self._on_changed:
                self._on_changed(self.get_selected())


# ─────────────────────────────────────────────────────────────────────────────
# LOAD LOGS WIDGET
# ─────────────────────────────────────────────────────────────────────────────
class LoadLogsWidget(tk.Frame):
    def __init__(self, parent, on_loaded=None, **kwargs):
        super().__init__(parent, bg=BG_DARK, **kwargs)
        self._on_loaded  = on_loaded
        self._loaded_path = None
        self._build()

    def _build(self):
        lbl = tk.Label(self, text="Load logs", bg=BG_DARK, fg=TEXT_DIM, font=FONT_SMALL)
        lbl.pack(anchor="nw")

        row = tk.Frame(self, bg=BG_DARK)
        row.pack(fill="x", pady=(2, 0))

        # ── Main button ───────────────────────────────────────────
        btn_frame = tk.Frame(row, bg=BORDER, padx=1, pady=1)
        btn_frame.pack(side="left")

        self._btn = tk.Button(
            btn_frame,
            text=" Select UCL Log File ",
            bg=BTN_BG, fg=TEXT_LIGHT,
            activebackground=ACCENT, activeforeground="white",
            font=FONT_BOLD, relief="flat",
            cursor="hand2",
            command=self._browse
        )
        self._btn.pack(ipady=4, ipadx=8)
        self._btn.bind("<Enter>", lambda e: self._btn.configure(bg=BTN_HOVER))
        self._btn.bind("<Leave>", lambda e: self._btn.configure(bg=BTN_BG))

        # Status label (removed redundancy)
        self._status = tk.Label(self, text="No file loaded",
                                bg=BG_DARK, fg=TEXT_DIM, font=FONT_SMALL,
                                anchor="w")
        self._status.pack(fill="x", pady=(3, 0))

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select UCL Log File",
            filetypes=[("UCL Log Files", "*.log"), ("All Files", "*.*")]
        )
        if not path:
            return
        try:
            self._loaded_path = path
            filename = os.path.basename(path)
            short    = filename if len(filename) <= 32 else filename[:29] + "..."
            self._status.configure(
                text=f"Loaded: {short}",
                fg=ACCENT
            )
            if self._on_loaded:
                self._on_loaded(path)
        except Exception as ex:
            messagebox.showerror("Load error", str(ex))

    def get_log_path(self) -> str | None:
        return self._loaded_path


# ─────────────────────────────────────────────────────────────────────────────
# TIMESTAMP WIDGET
# ─────────────────────────────────────────────────────────────────────────────
class TimestampWidget(tk.Frame):
    """
    Timestamp selector:  MM-DD HH:MM:SS.mmm   [Go]
    """
    def __init__(self, parent, on_go=None, **kwargs):
        super().__init__(parent, bg=BG_DARK, **kwargs)
        self._on_go   = on_go
        self._var     = tk.StringVar(value="01-01 00:00:00.000")
        self._build()

    def _build(self):
        lbl = tk.Label(self, text="Timestamp (MM-DD HH:MM:SS.mmm)",
                       bg=BG_DARK, fg=TEXT_DIM, font=FONT_SMALL)
        lbl.pack(anchor="nw")

        row = tk.Frame(self, bg=BG_DARK)
        row.pack(fill="x", pady=(2, 0))

        # Single Entry
        entry_frame = tk.Frame(row, bg=BORDER, padx=1, pady=1)
        entry_frame.pack(side="left")

        entry = tk.Entry(
            entry_frame,
            textvariable=self._var,
            width=24,
            bg=INPUT_BG, fg=INPUT_FG,
            insertbackground=ACCENT,
            relief="flat",
            font=FONT_BOLD,
            justify="center"
        )
        entry.pack(side="left", ipady=4, padx=2, pady=2)

        # ── Go button ─────────────────────────────────────────────
        go_frame = tk.Frame(row, bg=BORDER, padx=1, pady=1)
        go_frame.pack(side="left", padx=(10, 0))
        
        go_btn = tk.Button(
            go_frame, text=" Go ", bg=BTN_BG, fg=TEXT_LIGHT,
            activebackground=ACCENT, activeforeground="white",
            font=FONT_BOLD, relief="flat", cursor="hand2",
            command=self._on_go_click
        )
        go_btn.pack(ipady=4, ipadx=8)
        go_btn.bind("<Enter>", lambda e: go_btn.configure(bg=BTN_HOVER))
        go_btn.bind("<Leave>", lambda e: go_btn.configure(bg=BTN_BG))

    def _on_go_click(self):
        ts = self.get_timestamp()
        print(f"[Timestamp] Go clicked: {ts}")
        if self._on_go:
            self._on_go(ts)

    def get_timestamp(self) -> str:
        return self._var.get().strip()
# ─────────────────────────────────────────────────────────────────────────────
# SERVER STATUS WIDGET
# ─────────────────────────────────────────────────────────────────────────────
SERVER_URL      = "http://127.0.0.1:8765"
SERVER_SCRIPT   = os.path.join(BASE_DIR, "model_server.py")
POLL_INTERVAL   = 5000   # ms between health checks

# ── Resolve the venv Python (has torch/fastapi/uvicorn installed) ─────────────
_VENV_PY = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
VENV_PYTHON = _VENV_PY if os.path.exists(_VENV_PY) else sys.executable

# State constants
_SRV_OFFLINE  = "offline"
_SRV_LOADING  = "loading"   # server up but model not loaded yet
_SRV_ONLINE   = "online"


class ServerStatusWidget(tk.Frame):
    """
    A toolbar button that shows server health and can start the server.

    States
    ------
    offline  → red   dot + "Server Offline"   click → launches model_server.py
    loading  → amber dot + "Model Loading..."  (server up, model not ready)
    online   → green dot + "Server Online"     click does nothing extra
    """
    # colours per state
    _DOT   = {_SRV_OFFLINE: "#FF4757", _SRV_LOADING: "#FFA502", _SRV_ONLINE:  "#2ED573"}
    _RING  = {_SRV_OFFLINE: "#8B0000", _SRV_LOADING: "#7A4F00", _SRV_ONLINE:  "#145A32"}
    _LABEL = {_SRV_OFFLINE: "Server Offline",  _SRV_LOADING: "Model Loading...",
              _SRV_ONLINE:  "Server Online"}
    _BTNBG = {_SRV_OFFLINE: "#3D0000", _SRV_LOADING: "#2D1A00", _SRV_ONLINE:  "#0D2E1A"}

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG_DARK, **kwargs)
        self._state      = _SRV_OFFLINE
        self._pulse_dir  = 1
        self._pulse_val  = 0
        self._poll_id    = None
        self._pulse_id   = None
        self._server_proc = None   # Popen handle if we started the server

        self._build()
        # First check immediately, then poll
        self.after(100, self._do_poll)

    # ── UI ───────────────────────────────────────────────────────
    def _build(self):
        # tiny header label
        tk.Label(self, text="Model Server", bg=BG_DARK, fg=TEXT_DIM,
                 font=FONT_SMALL).pack(anchor="nw")

        # The button card
        self._btn_frame = tk.Frame(self, bg=BORDER, padx=1, pady=1,
                                   cursor="hand2")
        self._btn_frame.pack(pady=(2, 0))

        inner = tk.Frame(self._btn_frame, bg=self._BTNBG[_SRV_OFFLINE],
                         padx=10, pady=6)
        inner.pack(fill="both", expand=True)
        self._inner = inner

        # LED dot canvas
        self._dot_canvas = tk.Canvas(inner, width=14, height=14,
                                     bg=self._BTNBG[_SRV_OFFLINE],
                                     highlightthickness=0)
        self._dot_canvas.pack(side="left", padx=(0, 6))
        self._dot_ring = self._dot_canvas.create_oval(1, 1, 13, 13,
                             fill=self._RING[_SRV_OFFLINE],
                             outline="")
        self._dot_led  = self._dot_canvas.create_oval(3, 3, 11, 11,
                             fill=self._DOT[_SRV_OFFLINE],
                             outline="")

        # Status text
        self._lbl = tk.Label(inner, text=self._LABEL[_SRV_OFFLINE],
                             bg=self._BTNBG[_SRV_OFFLINE],
                             fg=self._DOT[_SRV_OFFLINE],
                             font=FONT_BOLD)
        self._lbl.pack(side="left")

        # Bind clicks to the whole button surface
        for w in (self._btn_frame, inner, self._dot_canvas, self._lbl):
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>",   self._on_hover_in)
            w.bind("<Leave>",   self._on_hover_out)

    def _apply_state(self, state: str):
        self._state = state
        dot   = self._DOT[state]
        ring  = self._RING[state]
        bg    = self._BTNBG[state]
        label = self._LABEL[state]

        self._inner.configure(bg=bg)
        self._dot_canvas.configure(bg=bg)
        self._dot_canvas.itemconfig(self._dot_ring, fill=ring)
        self._dot_canvas.itemconfig(self._dot_led,  fill=dot)
        self._lbl.configure(text=label, bg=bg, fg=dot)

        # Pulse animation: only when loading
        if state == _SRV_LOADING:
            self._start_pulse()
        else:
            self._stop_pulse()
            # Set LED to solid dot
            self._dot_canvas.itemconfig(self._dot_led, fill=dot)

    # ── Polling (runs in bg thread, result posted via after()) ─────────
    def _do_poll(self):
        self._poll_id = None
        t = threading.Thread(target=self._check_health, daemon=True)
        t.start()

    def _check_health(self):
        """Run in a background thread — no tkinter calls here."""
        try:
            with urllib.request.urlopen(f"{SERVER_URL}/health", timeout=2) as resp:
                data = _json.loads(resp.read().decode())
            if data.get("model_loaded"):
                new_state = _SRV_ONLINE
            else:
                new_state = _SRV_LOADING
        except Exception:
            new_state = _SRV_OFFLINE

        # Post back to main thread
        try:
            self.after(0, self._apply_state, new_state)
            self.after(0, self._schedule_next_poll)
        except Exception:
            pass   # widget destroyed

    def _schedule_next_poll(self):
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
        self._poll_id = self.after(POLL_INTERVAL, self._do_poll)

    # ── Pulse animation (for loading state) ────────────────────
    def _start_pulse(self):
        if self._pulse_id is None:
            self._pulse_step()

    def _stop_pulse(self):
        if self._pulse_id is not None:
            self.after_cancel(self._pulse_id)
            self._pulse_id = None
        self._pulse_val = 0

    def _pulse_step(self):
        self._pulse_val += self._pulse_dir * 15
        if self._pulse_val >= 255:
            self._pulse_val = 255
            self._pulse_dir = -1
        elif self._pulse_val <= 60:
            self._pulse_val = 60
            self._pulse_dir = 1
        # Interpolate between dim and bright amber
        v = int(self._pulse_val)
        colour = f"#{v:02X}{int(v * 0.6):02X}00"
        try:
            self._dot_canvas.itemconfig(self._dot_led, fill=colour)
            self._pulse_id = self.after(40, self._pulse_step)
        except Exception:
            self._pulse_id = None

    # ── Click handler ───────────────────────────────────────────
    def _on_click(self, _event=None):
        if self._state in (_SRV_ONLINE, _SRV_LOADING):
            return   # nothing to do

        # Launch model_server.py in a new visible terminal window
        if not os.path.exists(SERVER_SCRIPT):
            messagebox.showerror("Not found",
                                 f"model_server.py not found:\n{SERVER_SCRIPT}")
            return

        try:
            # Launch the server in a new console window directly using the specific python executable
            self._server_proc = subprocess.Popen(
                [VENV_PYTHON, SERVER_SCRIPT],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                cwd=BASE_DIR
            )
            # Immediately switch to loading state and start polling faster
            self._apply_state(_SRV_LOADING)
            self._lbl.configure(text="Starting...")
            if self._poll_id:
                self.after_cancel(self._poll_id)
            # Poll every 3 s while waiting for it to come up
            self._poll_id = self.after(3000, self._do_poll)
        except Exception as ex:
            messagebox.showerror("Launch failed", str(ex))

    # ── Hover highlight ────────────────────────────────────────
    def _on_hover_in(self, _e=None):
        if self._state == _SRV_OFFLINE:
            self._inner.configure(bg="#5A0000")
            self._lbl.configure(bg="#5A0000")
            self._dot_canvas.configure(bg="#5A0000")

    def _on_hover_out(self, _e=None):
        bg = self._BTNBG[self._state]
        self._inner.configure(bg=bg)
        self._lbl.configure(bg=bg)
        self._dot_canvas.configure(bg=bg)


# ─────────────────────────────────────────────────────────────────────────────
class FlowFrame(tk.Frame):
    """A truly responsive layout frame that wraps elements like CSS flex-wrap."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.bind("<Configure>", self._on_resize)
        self._items = []

    def add(self, widget, padx=0, pady=0):
        self._items.append((widget, padx, pady))
        widget.place(x=0, y=0)
        self.after(50, self._do_layout)

    def _on_resize(self, event=None):
        self._do_layout()

    def _do_layout(self):
        width = self.winfo_width()
        if width <= 1:
            return

        x, y = 0, 0
        row_height = 0

        for widget, px, py in self._items:
            req_w = widget.winfo_reqwidth()
            req_h = widget.winfo_reqheight()

            # Wrap to next row if it exceeds width
            if x + req_w + px * 2 > width and x > 0:
                x = 0
                y += row_height
                row_height = 0

            widget.place(x=x + px, y=y + py, width=req_w, height=req_h)
            x += req_w + px * 2
            row_height = max(row_height, req_h + py * 2)

        total_h = y + row_height
        if self.winfo_reqheight() != total_h:
            self.configure(height=total_h)

# ─────────────────────────────────────────────────────────────────────────────
class Toolbar(tk.Frame):
    def __init__(self, parent, signals, **callbacks):
        super().__init__(parent, bg=BG_DARK, pady=12, padx=16)
        self._build(signals, callbacks)

    def _build(self, signals, callbacks):
        # Gradient-like top border
        border = tk.Frame(self, bg=ACCENT, height=2)
        border.pack(fill="x", side="bottom")

        inner = FlowFrame(self, bg=BG_DARK)
        inner.pack(fill="x", expand=True)

        # ── 1. Search ─────────────────────────────────────────────
        self.search = SearchWidget(
            inner, signals,
            on_signals_changed=callbacks.get("on_signals_changed")
        )
        inner.add(self.search, padx=15, pady=5)

        # ── 2. Load logs ──────────────────────────────────────────
        self.load_logs = LoadLogsWidget(
            inner,
            on_loaded=callbacks.get("on_log_loaded")
        )
        inner.add(self.load_logs, padx=15, pady=5)

        # ── 3. Timestamp ──────────────────────────────────────────
        self.timestamp = TimestampWidget(
            inner,
            on_go=callbacks.get("on_go")
        )
        inner.add(self.timestamp, padx=15, pady=5)

        # ── 4. Server Status (far right) ─────────────────────────
        self.server_status = ServerStatusWidget(inner)
        inner.add(self.server_status, padx=15, pady=5)


# ─────────────────────────────────────────────────────────────────────────────
# PLACEHOLDER PANELS  (will be replaced in future steps)
# ─────────────────────────────────────────────────────────────────────────────
class SignalListPanel(tk.Frame):
    """Left panel – shows selected signals with mini-chart placeholder."""
    def __init__(self, parent, on_uncheck_signal=None, on_visibility_changed=None, **kwargs):
        super().__init__(parent, bg=BG_PANEL, **kwargs)
        self._signals = []
        self._signal_frames = {}
        self._vars = {}
        self._on_uncheck_signal = on_uncheck_signal
        self._on_visibility_changed = on_visibility_changed
        self._build_header()
        
        self._canvas = tk.Canvas(self, bg=BG_PANEL, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        
        self._container = tk.Frame(self._canvas, bg=BG_PANEL)
        self._canvas_window = self._canvas.create_window((0, 0), window=self._container, anchor="nw")
        
        self._container.bind("<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(self._canvas_window, width=e.width))
        self._canvas.bind("<MouseWheel>", lambda e: handle_scroll(e, self._canvas))

        self._empty_lbl = tk.Label(
            self._container,
            text="No signals selected.\nUse Search to add signals.",
            bg=BG_PANEL, fg=TEXT_DIM,
            font=FONT_SMALL, justify="center"
        )
        self._empty_lbl.pack(expand=True, pady=20)
        bind_mousewheel_recursive(self._empty_lbl, self._canvas)

    def _build_header(self):
        hdr = tk.Frame(self, bg=BG_CARD, pady=4, padx=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Signal List", bg=BG_CARD, fg=TEXT_LIGHT,
                 font=FONT_BOLD).pack(side="left")

    def update_signals(self, selected: list[str]):
        # Remove deselected
        to_remove = [s for s in self._signal_frames if s not in selected]
        for s in to_remove:
            self._signal_frames[s].destroy()
            del self._signal_frames[s]

        # Add new
        for sig in selected:
            if sig not in self._signal_frames:
                self._add_signal_row(sig)

        # Toggle empty label
        if self._signal_frames:
            self._empty_lbl.pack_forget()
        else:
            self._empty_lbl.pack(expand=True)

    def _add_signal_row(self, signal: str):
        card = tk.Frame(self._container, bg=BG_CARD,
                        relief="flat", pady=4, padx=6)
        card.pack(fill="x", pady=2)

        # Checkbox (already checked since user selected it)
        var = tk.BooleanVar(value=True)
        self._vars[signal] = var
        def on_toggle():
            if self._on_visibility_changed:
                self._on_visibility_changed(signal, var.get())
                
        cb = tk.Checkbutton(card, variable=var, bg=BG_CARD,
                            selectcolor=ACCENT2,
                            activebackground=BG_CARD,
                            command=on_toggle)
        cb.pack(side="left")

        # Signal name
        parts = signal.split("__", 1)
        ecu   = parts[0] if len(parts) == 2 else ""
        name  = parts[1] if len(parts) == 2 else signal

        col = tk.Frame(card, bg=BG_CARD)
        col.pack(side="left", fill="x", expand=True, padx=(4, 0))

        tk.Label(col, text=ecu, bg=BG_CARD, fg="#60a5fa",  # slightly lighter blue for better visibility
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 1))
        tk.Label(col, text=name, bg=BG_CARD, fg=TEXT_LIGHT,
                 font=FONT_SMALL, wraplength=160, justify="left").pack(anchor="w")

        self._signal_frames[signal] = card
        
        # Ensure hovering over any part of the row still allows scrolling
        bind_mousewheel_recursive(card, self._canvas)


class PlotPanel(tk.Frame):
    """
    Right panel – pure tkinter Canvas implementation of step-function plots.
    """
    _FIG_BG   = "#0B1121"
    _AX_BG    = "#0F172A"
    _GRID_COL = "#334155"
    _TEXT_COL = "#94a3b8"
    _TITLE_COL= "#f8fafc"
    _LINE_COLS= ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6",
                 "#ec4899", "#14b8a6", "#f43f5e", "#6366f1"]

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG_DARK, **kwargs)
        self._signals  = []
        self._hidden_signals = set()
        self._grouped_data = {}
        self._target_timestamp = ""
        self._subplots_info = []
        self._pinned_point = None
        self._build_ui()
        self.bind("<Configure>", self._on_resize)

    def set_signal_visible(self, signal: str, visible: bool):
        if visible:
            self._hidden_signals.discard(signal)
        else:
            self._hidden_signals.add(signal)
        self._redraw()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG_CARD, pady=4, padx=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Signal Plots  —  timeframe in secs",
                 bg=BG_CARD, fg=TEXT_DIM,
                 font=("Segoe UI", 9, "italic")).pack(side="left")

        self._canvas = tk.Canvas(self, bg=self._FIG_BG, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        
        self._canvas.bind("<MouseWheel>", lambda e: handle_scroll(e, self._canvas))
        self._canvas.bind("<Motion>", self._on_mouse_move)
        self._canvas.bind("<Leave>", self._on_mouse_leave)
        self._canvas.bind("<Button-1>", self._on_mouse_click)

    def update_signals(self, signals: list[str], grouped_data: dict = None, target_timestamp: str = ""):
        self._signals = list(signals)
        self._grouped_data = grouped_data or {}
        self._target_timestamp = target_timestamp
        self._redraw()

    def _on_resize(self, event=None):
        self._redraw()

    def _redraw(self):
        self._canvas.delete("all")
        self._subplots_info.clear()
        self._pinned_point = None
        
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        
        visible_signals = [s for s in self._signals if s not in self._hidden_signals]
        
        if not visible_signals:
            self._canvas.configure(scrollregion=(0, 0, w, h))
            if w > 0 and h > 0:
                self._canvas.create_text(
                    w // 2, h // 2,
                    text="Select signals using Search to view their plots here.",
                    fill=TEXT_DIM, font=FONT_SMALL
                )
            return

        if w < 50 or h < 50:
            return

        n = len(visible_signals)
        pad_top = 30
        pad_bot = 30
        pad_left = 120
        pad_right = 20

        plot_h = 150       # Height of the graph drawing area
        plot_spacing = 50  # Empty vertical space between graphs
        row_h = plot_h + plot_spacing
        total_h = pad_top + pad_bot + (n * row_h)
        
        # Enable scrolling region
        self._canvas.configure(scrollregion=(0, 0, w, max(h, total_h)))

        plot_w = w - pad_left - pad_right

        for idx, sig in enumerate(visible_signals):
            y_offset = pad_top + idx * row_h
            self._draw_subplot(sig, idx, pad_left, y_offset, plot_w, plot_h, is_last=(idx == n - 1))

    def _draw_subplot(self, sig: str, idx: int, x0: int, y0: int, pw: int, ph: int, is_last: bool = False):
        c = self._canvas
        
        # ── Parse target timestamp ──
        import datetime
        target_ts = 0.0
        if self._target_timestamp:
            try:
                dt = datetime.datetime.strptime(f"2026-{self._target_timestamp}", "%Y-%m-%d %H:%M:%S.%f")
                target_ts = dt.timestamp()
            except:
                pass
                
        start_time = target_ts - 5.0
        end_time = target_ts + 5.0

        records = self._grouped_data.get(sig, [])
        
        choices = {}
        has_choices = False
        minimum = 0.0
        maximum = 1.0

        if records:
            _ch = records[0].get("choices", {})
            if isinstance(_ch, dict) and _ch:
                choices = _ch
                has_choices = True
            elif _ch == "empty" or not _ch:
                minimum = records[0].get("minimum", 0.0)
                maximum = records[0].get("maximum", 1.0)
            
        choice_keys = []
        if has_choices:
            choice_keys = sorted([int(k) for k in choices.keys()])
        
        def parse_ts(ts_str):
            try:
                return datetime.datetime.strptime(f"2026-{ts_str}", "%Y-%m-%d %H:%M:%S.%f").timestamp()
            except:
                return 0.0
                
        pts_data = []
        for rec in records:
            t = parse_ts(rec.get("time", ""))
            if start_time <= t <= end_time:
                matched = rec.get("matched_choice", {})
                if isinstance(matched, dict) and matched:
                    try:
                        val_str = list(matched.keys())[0]
                        pts_data.append((t, float(val_str)))
                    except Exception:
                        pass
        pts_data.sort(key=lambda x: x[0])
        
        last_t = pts_data[-1][0] if pts_data else None
        
        # Deduplicate points to only show value changes
        if pts_data:
            filtered_pts = [pts_data[0]]
            for i in range(1, len(pts_data)):
                if pts_data[i][1] != filtered_pts[-1][1]:
                    filtered_pts.append(pts_data[i])
            pts_data = filtered_pts
        
        # ── Draw Background & Grid ───────────────────────────────────
        c.create_rectangle(x0, y0, x0 + pw, y0 + ph, fill=self._AX_BG, outline=self._GRID_COL)
        
        if has_choices:
            max_y_idx = len(choice_keys) - 1 if len(choice_keys) > 1 else 1
            # Y grid lines
            for i, val in enumerate(choice_keys):
                y_val = y0 + ph - (i / max_y_idx) * ph
                c.create_line(x0, y_val, x0 + pw, y_val, fill=self._GRID_COL, dash=(2, 4))
                lbl_text = choices.get(str(val), str(val))
                if len(lbl_text) > 18: lbl_text = lbl_text[:15] + "..."
                c.create_text(x0 - 5, y_val, text=f"{val}: {lbl_text}", fill=self._TEXT_COL, anchor="e", font=("Segoe UI", 7))
        else:
            y_ticks = 4
            for i in range(y_ticks + 1):
                y_val = y0 + ph - (i / y_ticks) * ph
                c.create_line(x0, y_val, x0 + pw, y_val, fill=self._GRID_COL, dash=(2, 4))
                val = minimum + (maximum - minimum) * (i / y_ticks)
                c.create_text(x0 - 5, y_val, text=f"{val:.1f}", fill=self._TEXT_COL, anchor="e", font=("Segoe UI", 7))
            
        # X grid lines (-5 to +5 seconds)
        for i in range(11):
            x_val = x0 + (i / 10.0) * pw
            c.create_line(x_val, y0, x_val, y0 + ph, fill=self._GRID_COL, dash=(2, 4))
            
            if is_last:
                # To prevent clutter, only draw text labels for Start (0), Target (5), and End (10)
                if i in (0, 5, 10):
                    tick_t = start_time + i
                    tick_dt = datetime.datetime.fromtimestamp(tick_t)
                    tick_lbl = tick_dt.strftime('%H:%M:%S') # Omit milliseconds to save space
                    
                    anchor_pos = "n"
                    if i == 0:
                        anchor_pos = "nw"
                        tick_lbl = f"Start: {tick_lbl}"
                    elif i == 5:
                        anchor_pos = "n"
                        tick_lbl = f"Target: {tick_lbl}"
                    elif i == 10:
                        anchor_pos = "ne"
                        tick_lbl = f"End: {tick_lbl}"
                        
                    c.create_text(x_val, y0 + ph + 8, text=tick_lbl, fill=self._TEXT_COL, font=("Segoe UI", 8, "bold"), anchor=anchor_pos)

        # ── Draw Title ───────────────────────────────────────────────
        parts = sig.split("__", 1)
        ecu = parts[0] + "  " if len(parts) == 2 else ""
        name = parts[1] if len(parts) == 2 else sig
        c.create_text(x0, y0 - 8, text=f"{ecu}{name}", 
                      fill=self._TITLE_COL, anchor="w", font=("Segoe UI", 8, "bold"))

        # ── Draw Step Line ───────────────────────────────────────────
        color = self._LINE_COLS[idx % len(self._LINE_COLS)]
        
        if not pts_data:
            c.create_text(x0 + pw//2, y0 + ph//2, text="No signal has matched in that timeframe", fill=self._TEXT_COL, font=("Segoe UI", 8))
            return

        poly_pts = []
        pt_info = []
        for i in range(len(pts_data)):
            t1, val1 = pts_data[i]
            if has_choices:
                try:
                    c_idx = choice_keys.index(int(val1))
                except:
                    c_idx = 0
                py1 = y0 + ph - (c_idx / max_y_idx) * ph
            else:
                norm = (val1 - minimum) / (maximum - minimum) if maximum > minimum else 0
                norm = max(0.0, min(1.0, norm))
                py1 = y0 + ph - norm * ph
                
            px1 = x0 + ((t1 - start_time) / 10.0) * pw
            
            # Create circular highlight
            r = 3
            c.create_oval(px1 - r, py1 - r, px1 + r, py1 + r, fill=color, outline=self._FIG_BG, width=1, tags=("data_point",))
            
            import datetime
            dt = datetime.datetime.fromtimestamp(t1)
            time_str = dt.strftime('%m-%d %H:%M:%S.%f')[:-3]
            
            if has_choices:
                try:
                    v_key = int(val1)
                    val_str = f"Value: {v_key}\n({choices.get(str(v_key), '')})"
                except:
                    val_str = f"Value: {val1}"
            else:
                val_str = f"Value: {val1:.2f}"
                
            text = f"Time: {time_str}\n{val_str}"
            pt_info.append({"cx": px1, "cy": py1, "text": text})
            
            if i == 0:
                poly_pts.extend([px1, y0 + ph])
            
            if i < len(pts_data) - 1:
                t2, val2 = pts_data[i+1]
                px2 = x0 + ((t2 - start_time) / 10.0) * pw
                
                c.create_line(px1, py1, px2, py1, fill=color, width=2)
                if has_choices:
                    try:
                        c_idx2 = choice_keys.index(int(val2))
                    except:
                        c_idx2 = 0
                    py2 = y0 + ph - (c_idx2 / max_y_idx) * ph
                else:
                    norm2 = (val2 - minimum) / (maximum - minimum) if maximum > minimum else 0
                    norm2 = max(0.0, min(1.0, norm2))
                    py2 = y0 + ph - norm2 * ph
                c.create_line(px2, py1, px2, py2, fill=color, width=2)
                poly_pts.extend([px1, py1, px2, py1])
            else:
                # Extend the final horizontal line to the last recorded time in the window
                px2 = px1
                if last_t is not None and last_t > t1:
                    px2 = x0 + ((last_t - start_time) / 10.0) * pw
                
                c.create_line(px1, py1, px2, py1, fill=color, width=2)
                poly_pts.extend([px1, py1, px2, py1])
                
        poly_pts.extend([x0 + pw, y0 + ph])
        if len(poly_pts) >= 6:
            c.create_polygon(poly_pts, fill=color, stipple="gray25", outline="")

        self._subplots_info.append({
            "x0": x0, "y0": y0, "pw": pw, "ph": ph,
            "has_choices": has_choices,
            "choice_keys": choice_keys,
            "choices": choices,
            "minimum": minimum,
            "maximum": maximum,
            "pts_data": pts_data,
            "start_time": start_time,
            "points": pt_info
        })

    def _draw_tooltip(self, x, y, text, tag, bg_color="#0F172A", outline_col="#f8fafc"):
        bg_id = self._canvas.create_rectangle(x + 10, y + 10, x + 10, y + 10, fill=bg_color, outline=outline_col, tags=tag)
        txt_id = self._canvas.create_text(x + 15, y + 15, text=text, fill="#E0E0E0", anchor="nw", font=("Segoe UI", 8), tags=tag)
        
        bbox = self._canvas.bbox(txt_id)
        if bbox:
            self._canvas.coords(bg_id, bbox[0]-4, bbox[1]-4, bbox[2]+4, bbox[3]+4)

    def _on_mouse_move(self, event):
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        
        self._canvas.delete("hover_elements")
        
        hovered_pt = None
        for info in self._subplots_info:
            for pt in info.get("points", []):
                if abs(cx - pt["cx"]) < 6 and abs(cy - pt["cy"]) < 6:
                    hovered_pt = pt
                    break
            if hovered_pt:
                break
                
        if hovered_pt:
            if self._pinned_point != hovered_pt:
                self._draw_tooltip(hovered_pt["cx"], hovered_pt["cy"], hovered_pt["text"], "hover_elements")
            return
        
        found = None
        for info in self._subplots_info:
            if info["x0"] <= cx <= info["x0"] + info["pw"] and info["y0"] <= cy <= info["y0"] + info["ph"]:
                found = info
                break
                
        if not found:
            return
            
        x0, y0, pw, ph = found["x0"], found["y0"], found["pw"], found["ph"]
        
        # Calculate X absolute time
        t_cursor = found["start_time"] + ((cx - x0) / pw) * 10.0
        
        # Find the value at t_cursor
        current_val = None
        for pt_t, pt_val in found["pts_data"]:
            if pt_t <= t_cursor:
                current_val = pt_val
            else:
                break
                
        if current_val is None:
            val_str = "Value: N/A"
        else:
            if found["has_choices"]:
                try:
                    val_key = int(current_val)
                    val_str = f"Value: {val_key}\n({found['choices'].get(str(val_key), '')})"
                except:
                    val_str = f"Value: {current_val}"
            else:
                val_str = f"Value: {current_val:.2f}"
            
        # Draw crosshairs
        self._canvas.create_line(cx, y0, cx, y0 + ph, fill=self._TEXT_COL, dash=(4, 4), tags="hover_elements")
        self._canvas.create_line(x0, cy, x0 + pw, cy, fill=self._TEXT_COL, dash=(4, 4), tags="hover_elements")
        
        # Draw text
        import datetime
        cursor_dt = datetime.datetime.fromtimestamp(t_cursor)
        cursor_time_str = cursor_dt.strftime('%m-%d %H:%M:%S.%f')[:-3]
        text = f"Time: {cursor_time_str}\n{val_str}"
        self._draw_tooltip(cx, cy, text, "hover_elements")
        
    def _on_mouse_click(self, event):
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        
        self._canvas.delete("pinned_elements")
        self._pinned_point = None
        
        for info in self._subplots_info:
            for pt in info.get("points", []):
                if abs(cx - pt["cx"]) < 6 and abs(cy - pt["cy"]) < 6:
                    self._pinned_point = pt
                    self._canvas.delete("hover_elements")
                    self._draw_tooltip(pt["cx"], pt["cy"], pt["text"], "pinned_elements", bg_color="#2D1A00", outline_col="#FFA502")
                    return
            
    def _on_mouse_leave(self, event):
        self._canvas.delete("hover_elements")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN APPLICATION WINDOW
# ─────────────────────────────────────────────────────────────────────────────
class ConsoleRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget
    def write(self, string):
        self.text_widget.after(0, self._insert, string)
    def _insert(self, string):
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
    def flush(self):
        pass

class VHALViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Automation - Log Analyzer")
        self.configure(bg=BG_DARK)
        self.geometry("1200x720")
        self.minsize(500, 400)

        self._signals = load_signals(SIGNAL_FILE)
        self._build_ui()

    def _build_ui(self):
        # ── Toolbar ───────────────────────────────────────────────
        self._toolbar = Toolbar(
            self,
            signals=self._signals,
            on_signals_changed=self._on_signals_changed,
            on_log_loaded=self._on_log_loaded,
            on_go=self._on_go
        )
        self._toolbar.pack(fill="x", side="top")

        # ── Main Vertical PanedWindow ─────────────────────────────
        main_pw = tk.PanedWindow(self, orient="vertical", bg=BORDER, sashwidth=4, sashrelief="flat")
        main_pw.pack(fill="both", expand=True)

        # ── Body (Horizontal) ─────────────────────────────────────
        body = tk.PanedWindow(main_pw, orient="horizontal",
                              bg=BORDER, sashwidth=4,
                              sashrelief="flat")
        main_pw.add(body, minsize=300)

        self._signal_panel = SignalListPanel(body, width=220, on_uncheck_signal=self._on_uncheck_signal, on_visibility_changed=self._on_visibility_changed)
        body.add(self._signal_panel, minsize=180)

        self._plot_panel = PlotPanel(body)
        body.add(self._plot_panel, minsize=400)

        # ── Console Panel ─────────────────────────────────────────
        self._console_frame = tk.Frame(main_pw, bg=BG_DARK)
        main_pw.add(self._console_frame, minsize=100)
        
        console_lbl = tk.Label(self._console_frame, text="Analyzer Console Output", bg=BG_CARD, fg=TEXT_DIM, font=FONT_SMALL, anchor="w", padx=8, pady=2)
        console_lbl.pack(fill="x")
        
        self._console_text = tk.Text(self._console_frame, bg="#000000", fg="#00FF00", font=("Consolas", 9), height=10)
        console_scrollbar = ttk.Scrollbar(self._console_frame, command=self._console_text.yview)
        self._console_text.configure(yscrollcommand=console_scrollbar.set)
        
        console_scrollbar.pack(side="right", fill="y")
        self._console_text.pack(side="left", fill="both", expand=True)

        sys.stdout = ConsoleRedirector(self._console_text)

        # ── Status bar ────────────────────────────────────────────
        self._statusbar = tk.Frame(self, bg=BG_CARD, pady=2)
        self._statusbar.pack(fill="x", side="bottom")

        self._status_lbl = tk.Label(
            self._statusbar,
            text=f"Ready  |  {len(self._signals)} signals loaded from signal_names.txt",
            bg=BG_CARD, fg=TEXT_DIM, font=FONT_SMALL, anchor="w", padx=8
        )
        self._status_lbl.pack(side="left")

    # ── Callbacks ────────────────────────────────────────────────
    def _on_visibility_changed(self, signal: str, visible: bool):
        self._plot_panel.set_signal_visible(signal, visible)

    def _on_uncheck_signal(self, sig: str):
        self._toolbar.search.uncheck_signal(sig)

    def _on_signals_changed(self, selected: list[str]):
        self._signal_panel.update_signals(selected)
        n = len(selected)
        self._set_status(f"{n} signal{'s' if n != 1 else ''} selected")

    def _on_log_loaded(self, path: str):
        self._set_status(f"Log loaded: {path}")

    def _on_go(self, timestamp: str):
        selected_signals = self._toolbar.search.get_selected()
        if not selected_signals:
            self._set_status("No signals selected. Search and check signals before analyzing.")
            return
            
        log_path = self._toolbar.load_logs.get_log_path()
        if not log_path:
            self._set_status("No log file loaded. Please select a UCL Log File first.")
            return
            
        self._set_status(f"Analyzing {len(selected_signals)} signal(s) for timestamp: {timestamp}...")
        
        def run_analysis():
            try:
                vhal_analyzer.run_pipeline(selected_signals, timestamp, log_path)
                self.after(0, lambda: self._set_status("Analysis complete! (Check JSON files)"))
                self.after(0, lambda: self._load_and_plot_results(timestamp))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda err=err_msg: self._set_status(f"Analysis failed: {err}"))

        threading.Thread(target=run_analysis, daemon=True).start()

    def _load_and_plot_results(self, target_timestamp: str):
        try:
            import json
            res3_path = os.path.join(BASE_DIR, "result3.json")
            if not os.path.isfile(res3_path):
                self._plot_panel.update_signals(self._toolbar.search.get_selected(), {}, target_timestamp)
                self._signal_panel.update_signals(self._toolbar.search.get_selected())
                return
                
            with open(res3_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            grouped = {}
            for item in data:
                sig = item.get("query_signal")
                if sig:
                    grouped.setdefault(sig, []).append(item)
                    
            self._plot_panel.update_signals(self._toolbar.search.get_selected(), grouped, target_timestamp)
            self._signal_panel.update_signals(self._toolbar.search.get_selected())
        except Exception as e:
            print(f"Error loading result3.json: {e}")

    def _set_status(self, msg: str):
        self._status_lbl.configure(text=msg)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = VHALViewer()
    app.mainloop()
