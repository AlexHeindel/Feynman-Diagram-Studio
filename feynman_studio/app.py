from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from . import __version__
from .geometry import connected_geometry, distance_to_polyline, edge_label_position, geometry, momentum_geometry
from .latex import FORMATS, latex_source, standalone_source, unsupported_features
from .model import (
    GRID_SIZE,
    HEIGHT,
    KINDS,
    MARKERS,
    WIDTH,
    Diagram,
    DiagramError,
    Edge,
    FreeLabel,
    FreeArrow,
    Momentum,
    Vertex,
    blank_diagram,
    bundle_offsets,
    make_edge,
    make_annotation,
    make_vertex,
    snap_value,
    templates,
)
from .render import display_label, render_preview, save_pdf, save_raster, save_svg

APP_NAME = "Feynman Diagram Studio"
MINIMUM_TK = 8.6


def _system_theme() -> str:
    if sys.platform == "darwin":
        try:
            result = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, check=False, timeout=1)
            return "dark" if result.stdout.strip().lower() == "dark" else "light"
        except (OSError, subprocess.TimeoutExpired):
            return "light"
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
        except OSError:
            return "light"
    if "dark" in os.environ.get("GTK_THEME", "").lower():
        return "dark"
    try:
        result = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], capture_output=True, text=True, check=False, timeout=1)
        return "dark" if "prefer-dark" in result.stdout else "light"
    except (OSError, subprocess.TimeoutExpired):
        return "light"


def check_tk_version(version: float = tk.TkVersion) -> None:
    if version < MINIMUM_TK:
        raise RuntimeError(
            "Feynman Diagram Studio requires Tk 8.6 or newer, but this Python "
            "uses Tk {:.1f}. On macOS, do not use /usr/bin/python3; install a "
            "current Python from https://www.python.org/downloads/macos/ and "
            "recreate the virtual environment.".format(version)
        )


def _filename(title: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9-]+", "-", title).strip("-").lower()
    return name or "diagram"


class StudioApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.app_icon = tk.PhotoImage(file=str(Path(__file__).resolve().parent / "assets" / "app-icon.png"))
        self.root.iconphoto(True, self.app_icon)
        self.root.geometry("1280x800")
        self.root.minsize(960, 640)
        self.document = templates()[0]
        self.past: List[Diagram] = []
        self.future: List[Diagram] = []
        self.selected: Optional[str] = None
        self.tool = "select"
        self.connection_start: Optional[str] = None
        self.new_kind = "fermion"
        self.loop_mode = "single"
        self.snap = tk.BooleanVar(value=True)
        self.show_grid = tk.BooleanVar(value=False)
        self.grid_size = tk.IntVar(value=int(GRID_SIZE))
        self.theme_mode = tk.StringVar(value="automatic")
        self.active_theme: Optional[str] = None
        self.status = tk.StringVar(value="Local workspace")
        self.canvas_scale = 1.0
        self.canvas_offset = (0.0, 0.0)
        self.drag_kind: Optional[str] = None
        self.drag_id: Optional[str] = None
        self.drag_origin = (0.0, 0.0)
        self.drag_vertex_offset = (0.0, 0.0)
        self.drag_before: Optional[Diagram] = None
        self.drag_changed = False
        self.current_path: Optional[Path] = None
        self.autosave_job: Optional[str] = None
        self.canvas_preview = None
        self.title_entry: Optional[ttk.Entry] = None

        self._configure_style()
        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self._restore_autosave()
        self.redraw()
        self.root.after(5000, self._follow_system_theme)

    def _configure_style(self) -> None:
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._apply_theme()

    def _apply_theme(self, force: bool = False) -> None:
        theme = _system_theme() if self.theme_mode.get() == "automatic" else self.theme_mode.get()
        if theme == self.active_theme and not force:
            return
        self.active_theme = theme
        colors = {
            "light": ("#f3f5f8", "#ffffff", "#e7edf4", "#1f2937", "#64748b", "#e4e9f0", "#bdc7d1", "#2563eb"),
            "dark": ("#22262e", "#2b303a", "#343c49", "#ecf1f7", "#a8b4c5", "#3a4351", "#566273", "#3b82f6"),
        }
        background, field, canvas, foreground, muted, button, border, accent = colors[theme]
        self.root.tk_setPalette(background=background, foreground=foreground, activeBackground=button,
                                activeForeground=foreground, selectBackground=accent, selectForeground="#ffffff")
        self.root.configure(background=background)
        style = self.style
        style.configure(".", background=background, foreground=foreground, fieldbackground=field)
        style.configure("TFrame", background=background)
        style.configure("TLabel", background=background, foreground=foreground)
        style.configure("Heading.TLabel", background=background, foreground=foreground, font=("TkDefaultFont", 13, "bold"))
        style.configure("Eyebrow.TLabel", background=background, foreground=muted, font=("TkDefaultFont", 9, "bold"))
        style.configure("Muted.TLabel", background=background, foreground=muted)
        style.configure("TButton", background=button, foreground=foreground, bordercolor=border, padding=(9, 6))
        style.map("TButton", background=[("active", border)], foreground=[("disabled", muted)])
        style.configure("Tool.TButton", background=button, foreground=foreground, bordercolor=border, padding=(9, 6))
        style.map("Tool.TButton", background=[("active", border)])
        style.configure("Selected.Tool.TButton", background=accent, foreground="#ffffff", bordercolor=accent, padding=(9, 6))
        style.map("Selected.Tool.TButton", background=[("active", accent)])
        style.configure("Menu.TButton", background=background, foreground=foreground, bordercolor=background, padding=(10, 5))
        style.map("Menu.TButton", background=[("active", button)])
        style.configure("TEntry", fieldbackground=field, foreground=foreground, insertcolor=foreground, bordercolor=border)
        style.configure("TCombobox", fieldbackground=field, foreground=foreground, bordercolor=border)
        style.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", foreground)])
        style.configure("TCheckbutton", background=background, foreground=foreground)
        style.map("TCheckbutton", background=[("active", background)], foreground=[("active", foreground)])
        style.configure("TRadiobutton", background=background, foreground=foreground)
        style.configure("TScrollbar", background=button, troughcolor=background, bordercolor=border)
        style.configure("TSeparator", background=border)
        if hasattr(self, "template_list"):
            for widget in (self.template_list, self.object_list):
                widget.configure(background=field, foreground=foreground, selectbackground=accent,
                                 selectforeground="#ffffff", highlightbackground=border)
            self.canvas.configure(background=canvas)
            self.inspector_canvas.configure(background=background)

    def _follow_system_theme(self) -> None:
        if self.theme_mode.get() == "automatic":
            self._apply_theme()
        self.root.after(5000, self._follow_system_theme)

    def _build_menu(self) -> None:
        self.native_menu = tk.Menu(self.root)
        for name in ("File", "Edit", "View", "Tools", "Help"):
            submenu = tk.Menu(self.native_menu, tearoff=False)
            self._fill_menu(name, submenu)
            self.native_menu.add_cascade(label=name, menu=submenu)
        self.root.configure(menu=self.native_menu)

    def _fill_menu(self, name: str, menu: tk.Menu) -> None:
        shortcut = "Cmd" if sys.platform == "darwin" else "Ctrl"
        if name == "File":
            menu.add_command(label="New Blank Diagram", accelerator=shortcut + "+N", command=self.new_document)
            menu.add_command(label="Open…", accelerator=shortcut + "+O", command=self.open_document)
            menu.add_command(label="Save", accelerator=shortcut + "+S", command=self.save_document)
            menu.add_command(label="Save As…", accelerator=shortcut + "+Shift+S", command=lambda: self.save_document(True))
            menu.add_separator()
            menu.add_command(label="Export…", accelerator=shortcut + "+E", command=self.show_export_dialog)
            menu.add_command(label="LaTeX Source…", command=self.show_latex_dialog)
            menu.add_separator()
            menu.add_command(label="Quit", command=self.root.quit)
        elif name == "Edit":
            menu.add_command(label="Undo", accelerator=shortcut + "+Z", command=self.undo)
            menu.add_command(label="Redo", accelerator=shortcut + "+Shift+Z", command=self.redo)
            menu.add_separator()
            menu.add_command(label="Rename Diagram…", command=self.rename_diagram)
            menu.add_command(label="Delete Selection", accelerator="Delete", command=self.remove_selected)
        elif name == "View":
            menu.add_checkbutton(label="Snap to Grid", variable=self.snap, command=self._snap_setting_changed)
            menu.add_checkbutton(label="Show Page Grid", variable=self.show_grid, command=self.redraw)
            spacing_menu = tk.Menu(menu, tearoff=False)
            for label, spacing in (("Fine · 10 units", 10), ("Standard · 20 units", 20), ("Coarse · 40 units", 40)):
                spacing_menu.add_radiobutton(label=label, variable=self.grid_size, value=spacing, command=self._grid_spacing_changed)
            menu.add_cascade(label="Grid Spacing", menu=spacing_menu)
            theme_menu = tk.Menu(menu, tearoff=False)
            for label, value in (("Automatic", "automatic"), ("Light", "light"), ("Dark", "dark")):
                theme_menu.add_radiobutton(label=label, variable=self.theme_mode, value=value, command=self._apply_theme)
            menu.add_cascade(label="Theme", menu=theme_menu)
        elif name == "Tools":
            for label, tool in (("Select", "select"), ("Add Vertex", "vertex"), ("Connect Vertices", "connect"), ("Add Loop", "loop")):
                menu.add_command(label=label, command=lambda value=tool: self.set_tool(value))
            annotation_menu = tk.Menu(menu, tearoff=False)
            annotation_menu.add_command(label="Label", command=lambda: self.set_tool("label"))
            annotation_menu.add_command(label="Arrow", command=lambda: self.set_tool("arrow"))
            menu.add_cascade(label="Annotate", menu=annotation_menu)
        else:
            menu.add_command(label="Keyboard Shortcuts", command=self._show_shortcuts)
            menu.add_command(label="About", command=lambda: messagebox.showinfo("About", APP_NAME + "\nVersion " + __version__ + "\nOpen source under the MIT License"))

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(fill="x")
        self.file_controls = ttk.Frame(toolbar)
        self.file_controls.pack(side="right")
        self.open_button = ttk.Button(self.file_controls, text="Open", command=self.open_document)
        self.save_button = ttk.Button(self.file_controls, text="Save", command=self.save_document)
        self.latex_button = ttk.Button(self.file_controls, text="LaTeX", command=self.show_latex_dialog)
        self.export_button = ttk.Button(self.file_controls, text="Export…", command=self.show_export_dialog)
        self.open_button.grid(row=0, column=0, sticky="ew", padx=2)
        self.save_button.grid(row=0, column=1, sticky="ew", padx=2)
        self.latex_button.grid(row=0, column=2, sticky="ew", padx=2)
        self.export_button.grid(row=0, column=3, sticky="ew", padx=2)
        self.file_controls.columnconfigure((0, 1, 2, 3), weight=1)

        self.menu_bar = ttk.Frame(toolbar)
        self.menu_bar.pack(side="left")
        self.menu_buttons = {}
        self.visible_menus = {}
        for name in ("File", "Edit", "View", "Tools", "Help"):
            button = ttk.Button(self.menu_bar, text=name, style="Menu.TButton")
            submenu = tk.Menu(button, tearoff=False)
            self._fill_menu(name, submenu)
            button.configure(command=lambda menu=submenu, widget=button: menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height()))
            button.pack(side="left")
            self.menu_buttons[name] = button
            self.visible_menus[name] = submenu

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True)
        self.library = ttk.Frame(body, padding=10, width=220)
        center = ttk.Frame(body, padding=(8, 8))
        inspector_host = ttk.Frame(body, width=270)
        body.add(self.library, weight=0)
        body.add(center, weight=1)
        body.add(inspector_host, weight=0)

        self.history_controls = ttk.Frame(self.library)
        self.history_controls.pack(fill="x", pady=(0, 10))
        self.history_controls.columnconfigure((0, 1), weight=1, uniform="history")
        self.undo_button = ttk.Button(self.history_controls, text="↶ Undo", command=self.undo)
        self.undo_button.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.redo_button = ttk.Button(self.history_controls, text="↷ Redo", command=self.redo)
        self.redo_button.grid(row=0, column=1, sticky="ew", padx=(2, 0))
        ttk.Button(self.library, text="＋ New blank diagram", command=self.new_document).pack(fill="x", pady=(0, 8))
        ttk.Label(self.library, text="STARTING POINTS", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 6))
        self.template_list = tk.Listbox(self.library, exportselection=False, height=12, activestyle="dotbox")
        for document in templates():
            self.template_list.insert("end", document.title)
        self.template_list.pack(fill="x")
        self.template_list.bind("<<ListboxSelect>>", self._load_selected_template)
        ttk.Separator(self.library).pack(fill="x", pady=(12, 8))
        ttk.Label(self.library, text="OBJECTS", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 6))
        self.object_list = tk.Listbox(self.library, exportselection=False, activestyle="dotbox")
        self.object_list.pack(fill="both", expand=True)
        self.object_list.bind("<<ListboxSelect>>", self._select_object)
        ttk.Label(self.library, text="Version " + __version__ + " · Native prototype", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        heading = ttk.Frame(center)
        heading.pack(fill="x", pady=(0, 6))
        title_block = ttk.Frame(heading)
        title_block.pack(fill="x")
        ttk.Label(title_block, text="FEYNMAN DIAGRAM", style="Eyebrow.TLabel").pack(anchor="w")
        self.title_label = ttk.Label(title_block, text=self.document.title, style="Heading.TLabel", cursor="hand2")
        self.title_label.pack(anchor="w")
        self.title_label.bind("<Double-Button-1>", lambda _event: self.rename_diagram())
        self.diagram_tools = ttk.Frame(center)
        self.diagram_tools.pack(fill="x", pady=(0, 6))
        self.tool_buttons = {}
        for key, label in (("select", "Select"), ("vertex", "Vertex"), ("connect", "Connect"), ("loop", "Loop")):
            button = ttk.Button(self.diagram_tools, text=label, style="Tool.TButton", command=lambda value=key: self.set_tool(value))
            button.pack(side="left", fill="x", expand=True, padx=2)
            self.tool_buttons[key] = button
        annotate = ttk.Menubutton(self.diagram_tools, text="Annotate")
        annotation_menu = tk.Menu(annotate, tearoff=False)
        annotation_menu.add_command(label="Label", command=lambda: self.set_tool("label"))
        annotation_menu.add_command(label="Arrow", command=lambda: self.set_tool("arrow"))
        annotate.configure(menu=annotation_menu)
        annotate.pack(side="left", fill="x", expand=True, padx=2)
        self.canvas = tk.Canvas(center, background="#dfe5eb", highlightthickness=0, cursor="arrow")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self.redraw())
        self.canvas.bind("<Button-1>", self._canvas_down)
        self.canvas.bind("<B1-Motion>", self._canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._canvas_up)
        self.hint = ttk.Label(center, text="", style="Muted.TLabel")
        self.hint.pack(fill="x", pady=(6, 0))

        self.inspector_canvas = tk.Canvas(inspector_host, highlightthickness=0, width=280)
        scroll = ttk.Scrollbar(inspector_host, orient="vertical", command=self.inspector_canvas.yview)
        self.inspector = ttk.Frame(self.inspector_canvas, padding=12)
        self.inspector_window = self.inspector_canvas.create_window((0, 0), window=self.inspector, anchor="nw")
        self.inspector_canvas.configure(yscrollcommand=scroll.set)
        self.inspector_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.inspector.bind("<Configure>", self._sync_inspector_scroll)
        self.inspector_canvas.bind("<Configure>", self._size_inspector_window)

        status_bar = ttk.Frame(self.root, padding=(10, 4))
        status_bar.pack(fill="x")
        self.count_label = ttk.Label(status_bar, text="")
        self.count_label.pack(side="left")
        ttk.Label(status_bar, textvariable=self.status).pack(side="right")
        self._update_tool_buttons()
        self._rebuild_inspector()
        self._apply_theme(force=True)

    def _sync_inspector_scroll(self, _event=None) -> None:
        bounds = self.inspector_canvas.bbox("all")
        if bounds and tuple(map(int, self.inspector_canvas.cget("scrollregion").split())) != bounds:
            self.inspector_canvas.configure(scrollregion=bounds)

    def _size_inspector_window(self, event) -> None:
        current = int(float(self.inspector_canvas.itemcget(self.inspector_window, "width") or 0))
        if current != event.width:
            self.inspector_canvas.itemconfigure(self.inspector_window, width=event.width)

    def _bind_keys(self) -> None:
        self.root.bind_all("<Control-n>", lambda event: self.new_document())
        self.root.bind_all("<Control-o>", lambda event: self.open_document())
        self.root.bind_all("<Control-s>", lambda event: self.save_document(bool(event.state & 1)))
        self.root.bind_all("<Control-e>", lambda event: self.show_export_dialog())
        self.root.bind_all("<Control-z>", lambda event: self.redo() if event.state & 1 else self.undo())
        self.root.bind_all("<Control-Z>", lambda event: self.redo())
        if sys.platform == "darwin":
            self.root.bind_all("<Command-n>", lambda event: self.new_document())
            self.root.bind_all("<Command-o>", lambda event: self.open_document())
            self.root.bind_all("<Command-s>", lambda event: self.save_document(bool(event.state & 1)))
            self.root.bind_all("<Command-e>", lambda event: self.show_export_dialog())
            self.root.bind_all("<Command-z>", lambda event: self.redo() if event.state & 1 else self.undo())
            self.root.bind_all("<Command-Z>", lambda event: self.redo())
        self.root.bind_all("<Delete>", lambda event: self._key_delete(event))
        self.root.bind_all("<BackSpace>", lambda event: self._key_delete(event))
        self.root.bind_all("<Escape>", lambda event: self._escape())
        self.root.bind_all("<KeyPress>", self._tool_hotkey, add=True)

    def _editing_text(self) -> bool:
        widget = self.root.focus_get()
        return bool(widget and widget.winfo_class() in ("Entry", "TEntry", "Text", "Spinbox", "TSpinbox", "TCombobox"))

    def _tool_hotkey(self, event) -> None:
        if self._editing_text() or event.state & 0x4:
            return
        key = event.keysym.lower()
        if key in {"v": "select", "a": "vertex", "c": "connect", "l": "loop"}:
            self.set_tool({"v": "select", "a": "vertex", "c": "connect", "l": "loop"}[key])
        if key in ("left", "right", "up", "down"):
            vertex = self.document.vertex(self.selected or "")
            if vertex:
                before = self.document.clone()
                distance = (self.grid_size.get() * (2 if event.state & 1 else 1)) if self.snap.get() else (10 if event.state & 1 else 1)
                if key == "left":
                    value = vertex.x - distance
                    vertex.x = self._snap_coordinate(value, 20, 700) if self.snap.get() else max(20, value)
                elif key == "right":
                    value = vertex.x + distance
                    vertex.x = self._snap_coordinate(value, 20, 700) if self.snap.get() else min(700, value)
                elif key == "up":
                    value = vertex.y - distance
                    vertex.y = self._snap_coordinate(value, 20, 460) if self.snap.get() else max(20, value)
                else:
                    value = vertex.y + distance
                    vertex.y = self._snap_coordinate(value, 20, 460) if self.snap.get() else min(460, value)
                self._record(before)

    def _key_delete(self, _event) -> None:
        if not self._editing_text():
            self.remove_selected()

    def _escape(self) -> None:
        self.selected = None
        self.connection_start = None
        self.set_tool("select")

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self.connection_start = None
        self._update_tool_buttons()
        self._rebuild_inspector()
        self.redraw()

    def _update_tool_buttons(self) -> None:
        for key, button in self.tool_buttons.items():
            button.configure(style="Selected.Tool.TButton" if key == self.tool else "Tool.TButton")
        cursor = {"select": "arrow", "vertex": "crosshair", "connect": "crosshair", "loop": "crosshair", "label": "crosshair", "arrow": "crosshair"}[self.tool]
        if hasattr(self, "canvas"):
            self.canvas.configure(cursor=cursor)

    def commit(self, change: Callable[[Diagram], None], status: str = "Modified") -> None:
        before = self.document.clone()
        change(self.document)
        if self.document == before:
            return
        self._record(before, status)

    def _record(self, before: Diagram, status: str = "Modified") -> None:
        self.past = (self.past + [before])[-60:]
        self.future.clear()
        self.status.set(status)
        self._changed()

    def _changed(self) -> None:
        self.title_label.configure(text=self.document.title)
        self._schedule_autosave()
        self._rebuild_inspector()
        self.redraw()

    def rename_diagram(self) -> None:
        if self.title_entry is not None:
            self.title_entry.focus_set()
            return
        self.title_label.pack_forget()
        entry = ttk.Entry(self.title_label.master)
        self.title_entry = entry
        entry.insert(0, self.document.title)
        entry.pack(fill="x")
        entry.bind("<Return>", lambda _event: self._finish_title_edit(True))
        entry.bind("<Escape>", lambda _event: self._finish_title_edit(False))
        entry.bind("<FocusOut>", lambda _event: self._finish_title_edit(True))
        entry.focus_set()
        entry.selection_range(0, "end")

    def _finish_title_edit(self, save: bool) -> str:
        entry = self.title_entry
        if entry is None:
            return "break"
        title = entry.get().strip()[:100] or "Untitled diagram"
        self.title_entry = None
        entry.destroy()
        self.title_label.pack(anchor="w")
        if save:
            self.commit(lambda document: setattr(document, "title", title), "Diagram renamed")
        return "break"

    def undo(self) -> None:
        if not self.past:
            return
        if getattr(self, "title_entry", None) is not None:
            self._finish_title_edit(False)
        self.future.insert(0, self.document)
        self.document = self.past.pop()
        self.selected = None
        self.connection_start = None
        self.status.set("Undid change")
        self._changed()

    def redo(self) -> None:
        if not self.future:
            return
        if getattr(self, "title_entry", None) is not None:
            self._finish_title_edit(False)
        self.past.append(self.document)
        self.document = self.future.pop(0)
        self.selected = None
        self.connection_start = None
        self.status.set("Redid change")
        self._changed()

    def new_document(self) -> None:
        self._replace_document(blank_diagram(), "New diagram")

    def _replace_document(self, document: Diagram, status: str, from_template: bool = False) -> None:
        if self.title_entry is not None:
            self._finish_title_edit(False)
        if not from_template:
            self.template_list.selection_clear(0, "end")
        before = self.document.clone()
        self.document = document.clone()
        self.selected = None
        self.connection_start = None
        self.current_path = None
        self._record(before, status)

    def _load_selected_template(self, _event) -> None:
        selection = self.template_list.curselection()
        if selection:
            self._replace_document(templates()[selection[0]], "Template loaded", True)

    def _select_object(self, _event=None) -> None:
        selection = self.object_list.curselection()
        if selection and selection[0] < len(self.object_ids):
            self.selected = self.object_ids[selection[0]]
            self._rebuild_inspector()
            self.redraw()

    def _rebuild_object_list(self) -> None:
        self.object_list.delete(0, "end")
        self.object_ids = []
        for index, item in enumerate(self.document.vertices, 1):
            label = display_label(item.label)
            self.object_list.insert("end", "Vertex {}{}".format(index, " · " + label if label else ""))
            self.object_ids.append(item.id)
        for index, item in enumerate(self.document.edges, 1):
            self.object_list.insert("end", "{} {}".format(item.kind.title(), index))
            self.object_ids.append(item.id)
        for index, item in enumerate(self.document.annotations, 1):
            self.object_list.insert("end", "Label {} · {}".format(index, display_label(item.text)) if isinstance(item, FreeLabel) else "Arrow {}".format(index))
            self.object_ids.append(item.id)
        if self.selected in self.object_ids:
            selected_index = self.object_ids.index(self.selected)
            self.object_list.selection_set(selected_index)
            self.object_list.see(selected_index)

    def open_document(self) -> None:
        path = filedialog.askopenfilename(title="Open diagram", filetypes=(("Feynman Diagram Studio project", "*.feynman.json"), ("JSON files", "*.json"), ("All files", "*.*")))
        if not path:
            return
        try:
            source = Path(path).read_text(encoding="utf-8")
            if len(source.encode("utf-8")) > 1_000_000:
                raise DiagramError("Project files must be smaller than 1 MB.")
            self._replace_document(Diagram.from_json(source), "Project opened")
            self.current_path = Path(path)
        except (OSError, DiagramError) as exc:
            messagebox.showerror("Could not open project", str(exc))

    def save_document(self, save_as: bool = False) -> None:
        path = self.current_path
        if save_as or path is None:
            chosen = filedialog.asksaveasfilename(
                title="Save editable project",
                defaultextension=".feynman.json",
                initialfile=_filename(self.document.title) + ".feynman.json",
                filetypes=(("Feynman Diagram Studio project", "*.feynman.json"), ("JSON files", "*.json")),
            )
            if not chosen:
                return
            path = Path(chosen)
        try:
            path.write_text(self.document.to_json(), encoding="utf-8")
            self.current_path = path
            self.status.set("Project saved")
        except OSError as exc:
            messagebox.showerror("Could not save project", str(exc))

    def remove_selected(self) -> None:
        if not self.selected:
            return
        object_id = self.selected
        self.commit(lambda document: document.remove(object_id), "Object deleted")
        self.selected = None
        self.connection_start = None
        self._changed()

    def redraw(self) -> None:
        if not hasattr(self, "canvas"):
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            return
        self.canvas.delete("all")
        scale = min((width - 40) / WIDTH, (height - 40) / HEIGHT)
        scale = max(0.2, scale)
        page_width = max(1, round(WIDTH * scale))
        scale = page_width / WIDTH
        page_height = round(HEIGHT * scale)
        offset = ((width - WIDTH * scale) / 2, (height - HEIGHT * scale) / 2)
        self.canvas_scale, self.canvas_offset = scale, offset
        ox, oy = offset
        from PIL import ImageTk

        self.canvas_preview = ImageTk.PhotoImage(render_preview(self.document, page_width, page_height, self.show_grid.get(), grid_size=self.grid_size.get()))
        self.canvas.create_image(ox, oy, image=self.canvas_preview, anchor="nw", tags="paper")
        self.canvas.create_rectangle(ox, oy, ox + page_width, oy + page_height, fill="", outline="#b8c1cc", width=1, tags="paper")
        for vertex in self.document.vertices:
            x, y = self._screen(vertex.x, vertex.y)
            radius = 7 if vertex.id == self.selected or vertex.id == self.connection_start else 4
            color = "#2563eb" if vertex.id == self.selected else "#f59e0b" if vertex.id == self.connection_start else "#94a3b8"
            self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill="white", outline=color, width=2, tags="controls")
        edge = self.document.edge(self.selected or "")
        if edge:
            for offset in bundle_offsets(edge):
                points, _ = connected_geometry(self.document, edge, offset)
                coordinates = [coordinate for point in points for coordinate in self._screen(*point)]
                self.canvas.create_line(*coordinates, fill="#2563eb", width=2, dash=(5, 4), tags="controls")
        annotation = self.document.annotation(self.selected or "")
        if annotation:
            x, y = (annotation.x, annotation.y) if isinstance(annotation, FreeLabel) else ((annotation.x1 + annotation.x2) / 2, (annotation.y1 + annotation.y2) / 2)
            sx, sy = self._screen(x, y)
            self.canvas.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, fill="white", outline="#2563eb", width=2, tags="controls")
        self.count_label.configure(text="{} vertices · {} propagators · {} annotations".format(len(self.document.vertices), len(self.document.edges), len(self.document.annotations)))
        self.hint.configure(text=self._hint_text())

    def _hint_text(self) -> str:
        if self.tool == "vertex":
            return "Click the page to place a vertex."
        if self.tool == "label":
            return "Click the page to place a free label."
        if self.tool == "arrow":
            return "Drag on the page to draw a free arrow."
        if self.tool == "connect":
            return "Choose the second vertex." if self.connection_start else "Choose two vertices to connect, in the direction of particle flow."
        if self.tool == "loop":
            if self.loop_mode == "single":
                return "Choose one vertex to attach a loop."
            return "Choose the second vertex to complete the loop." if self.connection_start else "Choose two vertices for the loop."
        return "Drag vertices or their labels. Select a propagator to customize it."

    def _screen(self, x: float, y: float) -> Tuple[float, float]:
        return self.canvas_offset[0] + x * self.canvas_scale, self.canvas_offset[1] + y * self.canvas_scale

    def _document_point(self, event) -> Tuple[float, float]:
        return (event.x - self.canvas_offset[0]) / self.canvas_scale, (event.y - self.canvas_offset[1]) / self.canvas_scale

    def _inside_page(self, x: float, y: float) -> bool:
        return 0 <= x <= WIDTH and 0 <= y <= HEIGHT

    def _snap_coordinate(self, value: float, minimum: int, maximum: int) -> float:
        spacing = self.grid_size.get()
        return max(math.ceil(minimum / spacing) * spacing,
                   min(math.floor(maximum / spacing) * spacing, snap_value(value, spacing)))

    def _snap_document(self, document: Diagram) -> None:
        for vertex in document.vertices:
            vertex.x = self._snap_coordinate(vertex.x, 20, 700)
            vertex.y = self._snap_coordinate(vertex.y, 20, 460)

    def _grid_spacing_changed(self) -> None:
        self.status.set("Grid spacing: {} units".format(self.grid_size.get()))
        self.redraw()

    def _snap_setting_changed(self) -> None:
        if not self.snap.get():
            self.status.set("Grid snapping off")
            return
        before = self.document.clone()
        self._snap_document(self.document)
        if self.document != before:
            self._record(before, "Vertices aligned to grid")
        else:
            self.status.set("Grid snapping on")
            self.redraw()

    def _set_vertex_coordinate(self, vertex: Optional[Vertex], attribute: str, value: float) -> None:
        if vertex is None:
            return
        if self.snap.get():
            value = self._snap_coordinate(value, 20, 700 if attribute == "x" else 460)
        minimum, maximum = (20, 700) if attribute == "x" else (20, 460)
        setattr(vertex, attribute, max(minimum, min(maximum, value)))

    def _nearest_vertex(self, x: float, y: float) -> Optional[Vertex]:
        candidates = [(math.hypot(item.x - x, item.y - y), item) for item in self.document.vertices]
        if not candidates:
            return None
        distance, item = min(candidates, key=lambda pair: pair[0])
        return item if distance <= 12 / self.canvas_scale else None

    def _nearest_edge(self, x: float, y: float) -> Optional[Edge]:
        best = (12 / self.canvas_scale, None)
        for edge in self.document.edges:
            start, end = self.document.vertex(edge.from_), self.document.vertex(edge.to)
            if start and end:
                for offset in bundle_offsets(edge):
                    points, _ = connected_geometry(self.document, edge, offset)
                    distance = distance_to_polyline(x, y, points)
                    if distance < best[0]:
                        best = (distance, edge)
                if edge.momentum:
                    momentum_points, _, _ = momentum_geometry(start, end, edge)
                    distance = distance_to_polyline(x, y, momentum_points)
                    if distance < best[0]:
                        best = (distance, edge)
        return best[1]

    def _nearest_annotation_arrow(self, x: float, y: float):
        for item in reversed(self.document.annotations):
            if isinstance(item, FreeArrow) and distance_to_polyline(x, y, ((item.x1, item.y1), (item.x2, item.y2))) <= 12 / self.canvas_scale:
                return item
        return None

    def _label_hit(self, x: float, y: float) -> Tuple[Optional[str], Optional[str]]:
        font = self.document.style.fontPt * WIDTH / (self.document.style.widthMm * 72 / 25.4)
        hits = []
        for vertex in self.document.vertices:
            if vertex.label:
                hits.append(("vertex_label", vertex.id, vertex.label, vertex.x + vertex.labelX, vertex.y + vertex.labelY))
        for edge in self.document.edges:
            if edge.label:
                start, end = self.document.vertex(edge.from_), self.document.vertex(edge.to)
                if start and end:
                    _, middle = geometry(start, end, edge)
                    lx, ly = edge_label_position(middle, edge)
                    hits.append(("edge_label", edge.id, edge.label, lx, ly))
            if edge.momentum and edge.momentum.label:
                start, end = self.document.vertex(edge.from_), self.document.vertex(edge.to)
                if start and end:
                    _, _, (lx, ly) = momentum_geometry(start, end, edge)
                    hits.append(("edge", edge.id, edge.momentum.label, lx, ly))
        for item in self.document.annotations:
            if isinstance(item, FreeLabel) and item.text:
                hits.append(("annotation_label", item.id, item.text, item.x, item.y))
        nearest = (float("inf"), None, None)
        for kind, object_id, label, lx, ly in hits:
            half_width = max(18, font * len(display_label(label)) * 0.32)
            half_height = max(12, font * 0.7)
            if abs(x - lx) <= half_width and abs(y - ly) <= half_height:
                distance = math.hypot(x - lx, y - ly)
                if distance < nearest[0]:
                    nearest = (distance, kind, object_id)
        return nearest[1], nearest[2]

    def _canvas_down(self, event) -> None:
        x, y = self._document_point(event)
        if not self._inside_page(x, y):
            return
        if self.tool in ("label", "arrow"):
            if len(self.document.annotations) >= 300:
                messagebox.showerror("Annotation limit", "A project may contain at most 300 annotations.")
                return
            item = make_annotation(self.tool, x, y)
            if self.tool == "label":
                self.commit(lambda document: document.annotations.append(item), "Label added")
                self.selected = item.id
                self.set_tool("select")
            else:
                self.drag_before = self.document.clone()
                self.document.annotations.append(item)
                self.selected = item.id
                self.drag_kind, self.drag_id = "new_arrow", item.id
                self.drag_origin = (x, y)
                self.drag_changed = True
                self.redraw()
            return
        if self.tool == "vertex":
            if len(self.document.vertices) >= 150:
                messagebox.showerror("Vertex limit", "A project may contain at most 150 vertices.")
                return
            if self.snap.get():
                x = self._snap_coordinate(x, 20, 700)
                y = self._snap_coordinate(y, 20, 460)
            item = make_vertex(max(20, min(700, x)), max(20, min(460, y)), visible=True)
            self.commit(lambda document: document.vertices.append(item), "Vertex added")
            self.selected = item.id
            self.set_tool("select")
            return
        vertex = self._nearest_vertex(x, y)
        if self.tool == "connect" and vertex:
            self._connect_vertex(vertex)
            return
        if self.tool == "loop" and vertex:
            self._loop_vertex(vertex)
            return
        if self.tool != "select":
            return
        label_kind, label_id = self._label_hit(x, y)
        if label_kind:
            self.selected = label_id
            self.drag_kind, self.drag_id = label_kind, label_id
        elif vertex:
            self.selected = vertex.id
            self.drag_kind, self.drag_id = "vertex", vertex.id
        else:
            arrow = self._nearest_annotation_arrow(x, y)
            if arrow:
                self.selected = arrow.id
                self.drag_kind, self.drag_id = "annotation_arrow", arrow.id
            else:
                edge = self._nearest_edge(x, y)
                self.selected = edge.id if edge else None
                self.drag_kind = self.drag_id = None
        if self.drag_id:
            self.drag_before = self.document.clone()
            self.drag_origin = (x, y)
            if self.drag_kind == "vertex" and vertex:
                self.drag_vertex_offset = (vertex.x - x, vertex.y - y)
            self.drag_changed = False
        self._rebuild_inspector()
        self.redraw()

    def _canvas_drag(self, event) -> None:
        if not self.drag_kind or not self.drag_id:
            return
        x, y = self._document_point(event)
        old_x, old_y = self.drag_origin
        dx, dy = x - old_x, y - old_y
        if self.drag_kind == "vertex":
            vertex = self.document.vertex(self.drag_id)
            if vertex:
                nx, ny = x + self.drag_vertex_offset[0], y + self.drag_vertex_offset[1]
                if self.snap.get():
                    nx = self._snap_coordinate(nx, 20, 700)
                    ny = self._snap_coordinate(ny, 20, 460)
                vertex.x, vertex.y = max(20, min(700, nx)), max(20, min(460, ny))
        elif self.drag_kind == "vertex_label":
            vertex = self.document.vertex(self.drag_id)
            if vertex:
                vertex.labelX = max(-150, min(150, vertex.labelX + dx))
                vertex.labelY = max(-150, min(150, vertex.labelY + dy))
        elif self.drag_kind == "edge_label":
            edge = self.document.edge(self.drag_id)
            if edge:
                edge.labelX = max(-150, min(150, edge.labelX + dx))
                edge.labelY = max(-150, min(150, edge.labelY + dy))
        elif self.drag_kind == "annotation_label":
            item = self.document.annotation(self.drag_id)
            if isinstance(item, FreeLabel):
                item.x = max(0, min(720, item.x + dx))
                item.y = max(0, min(480, item.y + dy))
        elif self.drag_kind == "annotation_arrow":
            item = self.document.annotation(self.drag_id)
            if isinstance(item, FreeArrow):
                dx = max(-min(item.x1, item.x2), min(720 - max(item.x1, item.x2), dx))
                dy = max(-min(item.y1, item.y2), min(480 - max(item.y1, item.y2), dy))
                item.x1 += dx; item.x2 += dx; item.y1 += dy; item.y2 += dy
        elif self.drag_kind == "new_arrow":
            item = self.document.annotation(self.drag_id)
            if isinstance(item, FreeArrow):
                item.x2 = max(0, min(720, x))
                item.y2 = max(0, min(480, y))
        self.drag_origin = (x, y)
        self.drag_changed = True
        self.redraw()

    def _canvas_up(self, _event) -> None:
        new_arrow = self.drag_kind == "new_arrow"
        if self.drag_changed and self.drag_before:
            self._record(self.drag_before, "Object moved")
        self.drag_kind = self.drag_id = None
        self.drag_before = None
        self.drag_changed = False
        if new_arrow:
            self.set_tool("select")

    def _connect_vertex(self, vertex: Vertex) -> None:
        if self.connection_start is None:
            self.connection_start = vertex.id
            self.selected = vertex.id
            self.redraw()
            return
        if self.connection_start == vertex.id:
            self.status.set("Choose a different endpoint, or use the Loop tool.")
            return
        if len(self.document.edges) >= 300:
            messagebox.showerror("Propagator limit", "A project may contain at most 300 propagators.")
            return
        item = make_edge(self.connection_start, vertex.id, self.new_kind)
        self.commit(lambda document: document.edges.append(item), "Propagator added")
        self.selected = item.id
        self.connection_start = None
        self.redraw()

    def _loop_vertex(self, vertex: Vertex) -> None:
        if self.loop_mode == "single":
            item = make_edge(vertex.id, vertex.id, self.new_kind)
            spaces = ((0, 700 - vertex.x), (90, 460 - vertex.y), (180, vertex.x - 20), (-90, vertex.y - 20))
            item.loopAngle = max(spaces, key=lambda pair: pair[1])[0]
            self.commit(lambda document: document.edges.append(item), "Loop added")
            self.selected = item.id
            self.redraw()
            return
        if self.connection_start is None:
            self.connection_start = vertex.id
            self.selected = vertex.id
            self.redraw()
            return
        if self.connection_start == vertex.id:
            self.status.set("Choose a different vertex for a two-vertex loop.")
            return
        start = self.document.vertex(self.connection_start)
        if not start:
            return
        bend = min(180, max(70, math.hypot(vertex.x - start.x, vertex.y - start.y) * 0.32))
        first = make_edge(start.id, vertex.id, self.new_kind, curvature=bend)
        second = make_edge(start.id, vertex.id, self.new_kind, curvature=-bend)
        first.circular = second.circular = True
        if self.new_kind == "fermion":
            second.arrow = "reverse"
        self.commit(lambda document: document.edges.extend((first, second)), "Two-vertex loop added")
        self.selected = first.id
        self.connection_start = None
        self.redraw()

    def _section(self, title: str) -> None:
        ttk.Separator(self.inspector).pack(fill="x", pady=(10, 8))
        ttk.Label(self.inspector, text=title, style="Heading.TLabel").pack(anchor="w", pady=(0, 5))

    def _entry(self, label: str, value, callback: Callable[[str], None], parent=None) -> None:
        parent = parent or self.inspector
        ttk.Label(parent, text=label).pack(anchor="w", pady=(4, 1))
        variable = tk.StringVar(value=str(value))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.pack(fill="x")
        applied = {"value": str(value)}

        def apply(_event=None):
            if variable.get() != applied["value"]:
                callback(variable.get())
                applied["value"] = variable.get()

        entry.bind("<Return>", apply)
        entry.bind("<FocusOut>", apply)

    def _choice(self, label: str, value: str, values, callback: Callable[[str], None]) -> None:
        ttk.Label(self.inspector, text=label).pack(anchor="w", pady=(4, 1))
        variable = tk.StringVar(value=value)
        combo = ttk.Combobox(self.inspector, state="readonly", textvariable=variable, values=values)
        combo.pack(fill="x")
        combo.bind("<<ComboboxSelected>>", lambda event: callback(variable.get()))

    def _number_callback(self, setter: Callable[[float], None], minimum: float, maximum: float) -> Callable[[str], None]:
        def apply(source: str) -> None:
            try:
                value = float(source)
            except ValueError:
                self.status.set("Enter a number between {} and {}".format(minimum, maximum))
                return
            setter(max(minimum, min(maximum, value)))

        return apply

    def _rebuild_inspector(self) -> None:
        if not hasattr(self, "inspector"):
            return
        fine = getattr(self, "_fine_placement_frame", None)
        fine_open = (fine is not None and fine.winfo_exists() and fine.winfo_manager()
                     and getattr(self, "_fine_placement_edge_id", None) == self.selected)
        for child in self.inspector.winfo_children():
            child.destroy()
        self._fine_placement_frame = None
        ttk.Label(self.inspector, text="Inspector", style="Heading.TLabel").pack(anchor="w")
        self._section("Figure style")
        self._entry("Figure width (mm)", _clean_number(self.document.style.widthMm), self._number_callback(lambda value: self.commit(lambda document: setattr(document.style, "widthMm", value)), 60, 240))
        self._entry("Line width (pt)", _clean_number(self.document.style.strokePt), self._number_callback(lambda value: self.commit(lambda document: setattr(document.style, "strokePt", value)), 0.3, 2))
        self._entry("Text size (pt)", _clean_number(self.document.style.fontPt), self._number_callback(lambda value: self.commit(lambda document: setattr(document.style, "fontPt", value)), 5, 18))
        ttk.Checkbutton(self.inspector, text="Snap to grid", variable=self.snap, command=self._snap_setting_changed).pack(anchor="w", pady=(7, 0))
        ttk.Checkbutton(self.inspector, text="Show page grid", variable=self.show_grid, command=self.redraw).pack(anchor="w")
        if self.tool in ("connect", "loop"):
            self._section("New " + ("propagator" if self.tool == "connect" else "loop"))
            self._choice("Line type", self.new_kind.title(), [kind.title() for kind in KINDS], lambda value: setattr(self, "new_kind", value.lower()))
            if self.tool == "loop":
                self._choice("Loop type", "Single vertex" if self.loop_mode == "single" else "Two vertices", ("Single vertex", "Two vertices"), self._set_loop_mode)
        vertex = self.document.vertex(self.selected or "")
        edge = self.document.edge(self.selected or "")
        annotation = self.document.annotation(self.selected or "")
        if vertex:
            self._section("Vertex")
            self._entry("Label (TeX)", vertex.label, lambda value: self.commit(lambda document: setattr(document.vertex(vertex.id), "label", value)))
            for label, attribute, minimum, maximum in (("X position", "x", 20, 700), ("Y position", "y", 20, 460)):
                self._entry(label, _clean_number(getattr(vertex, attribute)), self._number_callback(lambda value, attr=attribute: self.commit(lambda document: self._set_vertex_coordinate(document.vertex(vertex.id), attr, value)), minimum, maximum))
            for label, attribute in (("Label X", "labelX"), ("Label Y", "labelY")):
                self._entry(label, _clean_number(getattr(vertex, attribute)), self._number_callback(lambda value, attr=attribute: self.commit(lambda document: setattr(document.vertex(vertex.id), attr, value)), -150, 150))
            marker_names = ("None", "Dot", "Open", "Filled", "Hatched", "Crosshatched", "Dotted")
            self._choice("Vertex style", vertex.marker.title(), marker_names, lambda value: self.commit(lambda document: self._set_marker(document.vertex(vertex.id), value.lower())))
            if vertex.marker not in ("none", "dot"):
                self._entry("Circle radius", _clean_number(vertex.markerSize), self._number_callback(lambda value: self.commit(lambda document: setattr(document.vertex(vertex.id), "markerSize", value)), 6, 60))
            ttk.Button(self.inspector, text="Delete vertex", command=self.remove_selected).pack(fill="x", pady=(8, 0))
        elif edge:
            self._section("Propagator")
            self._choice("Particle style", edge.kind.title(), [kind.title() for kind in KINDS], lambda value: self.commit(lambda document: setattr(document.edge(edge.id), "kind", value.lower())))
            self._entry("Label (TeX)", edge.label, lambda value: self.commit(lambda document: setattr(document.edge(edge.id), "label", value)))
            arrow_labels = {"forward": "Start → end", "reverse": "End → start", "none": "No arrow"}
            reverse_arrow_labels = {value: key for key, value in arrow_labels.items()}
            self._choice("Arrow direction", arrow_labels[edge.arrow], tuple(reverse_arrow_labels), lambda value: self.commit(lambda document: setattr(document.edge(edge.id), "arrow", reverse_arrow_labels[value])))
            if edge.kind == "fermion" and edge.from_ != edge.to:
                self._choice("Quark bundle", str(edge.bundle), ("1", "2", "3"), lambda value: self.commit(lambda document: setattr(document.edge(edge.id), "bundle", int(value))))
                if edge.bundle > 1:
                    self._entry("Quark spacing", _clean_number(edge.bundleSpacing), self._number_callback(lambda value: self.commit(lambda document: setattr(document.edge(edge.id), "bundleSpacing", value)), 4, 40))
            if edge.from_ == edge.to:
                self._entry("Loop size", _clean_number(edge.loopSize), self._number_callback(lambda value: self.commit(lambda document: setattr(document.edge(edge.id), "loopSize", value)), 30, 180))
                self._entry("Loop angle", _clean_number(edge.loopAngle), self._number_callback(lambda value: self.commit(lambda document: setattr(document.edge(edge.id), "loopAngle", value)), -180, 180))
            elif not edge.circular:
                self._entry("Curvature", _clean_number(edge.curvature), self._number_callback(lambda value: self.commit(lambda document: setattr(document.edge(edge.id), "curvature", value)), -220, 220))
            self._entry("Label offset", _clean_number(edge.labelOffset), self._number_callback(lambda value: self.commit(lambda document: setattr(document.edge(edge.id), "labelOffset", value)), -120, 120))
            for label, attribute in (("Label X", "labelX"), ("Label Y", "labelY")):
                self._entry(label, _clean_number(getattr(edge, attribute)), self._number_callback(lambda value, attr=attribute: self.commit(lambda document: setattr(document.edge(edge.id), attr, value)), -150, 150))
            ttk.Button(self.inspector, text="Line color…", command=lambda: self._choose_edge_color(edge.id)).pack(fill="x", pady=(6, 0))
            enabled = tk.BooleanVar(value=edge.momentum is not None)
            ttk.Checkbutton(self.inspector, text="Momentum arrow", variable=enabled, command=lambda: self.commit(lambda document: setattr(document.edge(edge.id), "momentum", Momentum(color=edge.color, side="right" if edge.labelOffset < 0 else "left") if enabled.get() else None), "Momentum arrow updated")).pack(anchor="w", pady=(7, 0))
            if edge.momentum:
                momentum = edge.momentum
                self._entry("Momentum label (TeX)", momentum.label, lambda value: self.commit(lambda document: setattr(document.edge(edge.id).momentum, "label", value[:200])))
                self._choice("Momentum direction", momentum.direction.title(), ("Forward", "Reverse"), lambda value: self.commit(lambda document: setattr(document.edge(edge.id).momentum, "direction", value.lower())))
                self._choice("Momentum side", momentum.side.title(), ("Left", "Right"), lambda value: self.commit(lambda document: setattr(document.edge(edge.id).momentum, "side", value.lower())))
                fine = ttk.Frame(self.inspector)
                self._fine_placement_frame = fine
                self._fine_placement_edge_id = edge.id
                def toggle_fine():
                    if fine.winfo_manager():
                        fine.pack_forget()
                    else:
                        fine.pack(fill="x")
                ttk.Button(self.inspector, text="Fine placement…", command=toggle_fine).pack(fill="x", pady=(5, 0))
                for label, attribute, minimum, maximum in (("Start (%)", "start", 0, 95), ("End (%)", "end", 5, 100)):
                    self._entry(label, _clean_number(getattr(momentum, attribute) * 100), self._number_callback(lambda value, attr=attribute: self._set_momentum_fraction(edge.id, attr, value), minimum, maximum), fine)
                ttk.Button(fine, text="Arrow color…", command=lambda: self._choose_color("momentum", edge.id)).pack(fill="x", pady=(5, 0))
                if fine_open:
                    fine.pack(fill="x")
            ttk.Button(self.inspector, text="Delete propagator", command=self.remove_selected).pack(fill="x", pady=(6, 0))
        elif annotation:
            self._section("Free label" if isinstance(annotation, FreeLabel) else "Free arrow")
            if isinstance(annotation, FreeLabel):
                self._entry("Label (TeX)", annotation.text, lambda value: self.commit(lambda document: setattr(document.annotation(annotation.id), "text", value[:200])))
                fields = (("X position", "x", 720), ("Y position", "y", 480))
            else:
                fields = (("X1", "x1", 720), ("Y1", "y1", 480), ("X2", "x2", 720), ("Y2", "y2", 480))
            for label, attribute, maximum in fields:
                self._entry(label, _clean_number(getattr(annotation, attribute)), self._number_callback(lambda value, attr=attribute: self.commit(lambda document: setattr(document.annotation(annotation.id), attr, value)), 0, maximum))
            ttk.Button(self.inspector, text="Color…", command=lambda: self._choose_color("annotation", annotation.id)).pack(fill="x", pady=(6, 0))
            ttk.Button(self.inspector, text="Delete annotation", command=self.remove_selected).pack(fill="x", pady=(6, 0))
        self._rebuild_object_list()

    def _set_loop_mode(self, value: str) -> None:
        self.loop_mode = "single" if value == "Single vertex" else "double"
        self.connection_start = None
        self.redraw()

    @staticmethod
    def _set_marker(vertex: Vertex, marker: str) -> None:
        vertex.marker = marker
        vertex.visible = marker != "none"

    def _choose_edge_color(self, edge_id: str) -> None:
        edge = self.document.edge(edge_id)
        if not edge:
            return
        color = colorchooser.askcolor(edge.color, title="Choose line color")[1]
        if color:
            self.commit(lambda document: setattr(document.edge(edge_id), "color", color))

    def _choose_color(self, kind: str, object_id: str) -> None:
        target = self.document.edge(object_id).momentum if kind == "momentum" else self.document.annotation(object_id)
        if target is None:
            return
        color = colorchooser.askcolor(target.color, title="Choose color")[1]
        if color:
            self.commit(lambda document: setattr(document.edge(object_id).momentum if kind == "momentum" else document.annotation(object_id), "color", color))

    def _set_momentum_fraction(self, edge_id: str, attribute: str, percentage: float) -> None:
        def change(document):
            momentum = document.edge(edge_id).momentum
            value = percentage / 100
            setattr(momentum, attribute, min(value, momentum.end - 0.05) if attribute == "start" else max(value, momentum.start + 0.05))
        self.commit(change, "Momentum arrow updated")

    def show_export_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Export diagram")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Export your diagram", style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        format_var = tk.StringVar(value="svg")
        ppi_var = tk.StringVar(value="600")
        transparent_var = tk.BooleanVar(value=False)
        ttk.Label(frame, text="Format").pack(anchor="w")
        format_combo = ttk.Combobox(frame, state="readonly", textvariable=format_var, values=("svg", "pdf", "png", "jpg"))
        format_combo.pack(fill="x")
        ppi_label = ttk.Label(frame, text="Raster resolution")
        ppi_label.pack(anchor="w", pady=(8, 0))
        ppi_combo = ttk.Combobox(frame, state="readonly", textvariable=ppi_var, values=("300", "600", "1200"))
        ppi_combo.pack(fill="x")
        transparent_check = ttk.Checkbutton(frame, text="Transparent background (SVG/PNG)", variable=transparent_var)
        transparent_check.pack(anchor="w", pady=8)
        ttk.Label(frame, text="Page: {} × {:.1f} mm".format(_clean_number(self.document.style.widthMm), self.document.style.widthMm * 2 / 3), foreground="#64748b").pack(anchor="w")

        def update_options(_event=None) -> None:
            raster = format_var.get() in ("png", "jpg")
            ppi_combo.configure(state="readonly" if raster else "disabled")
            ppi_label.configure(foreground="" if raster else "#9ca3af")
            transparent_check.configure(state="normal" if format_var.get() in ("svg", "png") else "disabled")

        format_combo.bind("<<ComboboxSelected>>", update_options)
        update_options()

        def export() -> None:
            file_format = format_var.get()
            path = filedialog.asksaveasfilename(
                parent=dialog,
                title="Export diagram",
                defaultextension="." + file_format,
                initialfile=_filename(self.document.title) + "." + file_format,
                filetypes=((file_format.upper() + " file", "*." + file_format),),
            )
            if not path:
                return
            try:
                if file_format == "svg":
                    save_svg(self.document, path, transparent_var.get())
                elif file_format == "pdf":
                    save_pdf(self.document, path, int(ppi_var.get()))
                else:
                    save_raster(self.document, path, int(ppi_var.get()), transparent_var.get())
                self.status.set(file_format.upper() + " exported")
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("Export failed", str(exc), parent=dialog)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Export", command=export).pack(side="right", padx=(0, 6))

    def show_latex_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("LaTeX source")
        dialog.transient(self.root)
        dialog.geometry("820x650")
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        header = ttk.Frame(frame)
        header.pack(fill="x")
        ttk.Label(header, text="LaTeX source", style="Heading.TLabel").pack(side="left")
        available = [item for item in FORMATS if not unsupported_features(self.document, item.value)]
        blocked = ["{}: {}".format(item.label, "; ".join(unsupported_features(self.document, item.value))) for item in FORMATS if unsupported_features(self.document, item.value)]
        labels = [item.label for item in available]
        format_var = tk.StringVar(value=labels[0])
        combo = ttk.Combobox(header, state="readonly", textvariable=format_var, values=labels, width=24)
        combo.pack(side="right")
        note = ttk.Label(frame, text="", foreground="#64748b")
        note.pack(fill="x", pady=(8, 4))
        ttk.Label(frame, text="Unavailable for this diagram: " + " · ".join(blocked) if blocked else "All six formats are available for this diagram.", wraplength=780, foreground="#64748b").pack(fill="x", pady=(0, 4))
        source = tk.Text(frame, wrap="none", font=("TkFixedFont", 11), undo=False)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=source.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=source.xview)
        source.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        source.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")

        def selected_format():
            return available[labels.index(format_var.get())]

        def refresh(_event=None):
            option = selected_format()
            note.configure(text=option.description + "  Compile: " + option.compiler)
            source.configure(state="normal")
            source.delete("1.0", "end")
            source.insert("1.0", latex_source(self.document, option.value))
            source.configure(state="disabled")

        combo.bind("<<ComboboxSelected>>", refresh)
        refresh()

        actions = ttk.Frame(dialog, padding=(14, 0, 14, 14))
        actions.pack(fill="x")

        def copy(standalone: bool = False):
            option = selected_format()
            value = standalone_source(self.document, option.value) if standalone else latex_source(self.document, option.value)
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.status.set("Standalone LaTeX copied" if standalone else "LaTeX copied")

        ttk.Button(actions, text="Close", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Copy LaTeX", command=copy).pack(side="right", padx=5)
        ttk.Button(actions, text="Copy test document", command=lambda: copy(True)).pack(side="right")

    def _schedule_autosave(self) -> None:
        if self.autosave_job:
            self.root.after_cancel(self.autosave_job)
        self.autosave_job = self.root.after(500, self._autosave)

    def _autosave_path(self) -> Path:
        if sys.platform == "win32":
            import os

            root = Path(os.environ.get("APPDATA", Path.home()))
        elif sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support"
        else:
            import os

            root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return root / "FeynmanDiagramStudio" / "autosave.json"

    def _autosave(self) -> None:
        self.autosave_job = None
        try:
            path = self._autosave_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.document.to_json(), encoding="utf-8")
            self.status.set("Autosaved locally")
        except OSError:
            self.status.set("Autosave unavailable; use Save")

    def _restore_autosave(self) -> None:
        try:
            path = self._autosave_path()
            if path.exists():
                self.document = Diagram.from_json(path.read_text(encoding="utf-8"))
                if self.snap.get():
                    self._snap_document(self.document)
                self.status.set("Restored local draft")
                self.title_label.configure(text=self.document.title)
                self._rebuild_inspector()
        except (OSError, DiagramError):
            self.status.set("Could not restore the previous draft")

    def _show_shortcuts(self) -> None:
        messagebox.showinfo(
            "Keyboard shortcuts",
            "V  Select\nA  Add vertex\nC  Connect vertices\nL  Add loop\n\nCtrl+Z  Undo\nCtrl+Shift+Z  Redo\nDelete  Remove selection\nArrow keys  Nudge selected vertex\nShift+Arrow  Nudge farther",
        )


def _clean_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else "{:g}".format(value)


def main() -> None:
    try:
        check_tk_version()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    root = tk.Tk()
    StudioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
