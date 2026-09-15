from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from .geometry import distance_to_polyline, geometry
from .latex import FORMATS, latex_source, standalone_source
from .model import (
    HEIGHT,
    KINDS,
    MARKERS,
    WIDTH,
    Diagram,
    DiagramError,
    Edge,
    Vertex,
    blank_diagram,
    make_edge,
    make_vertex,
    templates,
)
from .render import draw_tk, save_pdf, save_raster, save_svg

APP_NAME = "Feynman Diagram Studio"
MINIMUM_TK = 8.6


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
        self.status = tk.StringVar(value="Local workspace")
        self.canvas_scale = 1.0
        self.canvas_offset = (0.0, 0.0)
        self.drag_kind: Optional[str] = None
        self.drag_id: Optional[str] = None
        self.drag_origin = (0.0, 0.0)
        self.drag_before: Optional[Diagram] = None
        self.drag_changed = False
        self.current_path: Optional[Path] = None
        self.autosave_job: Optional[str] = None

        self._configure_style()
        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self._restore_autosave()
        self.redraw()

    def _configure_style(self) -> None:
        style = ttk.Style()
        if sys.platform == "darwin":
            style.theme_use("aqua")
        elif "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Tool.TButton", padding=(9, 6))
        style.configure("Selected.Tool.TButton", padding=(9, 6), relief="sunken")
        style.configure("Heading.TLabel", font=("TkDefaultFont", 13, "bold"))
        style.configure("Eyebrow.TLabel", foreground="#64748b", font=("TkDefaultFont", 9, "bold"))

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self.new_document)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_document)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_document)
        file_menu.add_command(label="Save As…", accelerator="Ctrl+Shift+S", command=lambda: self.save_document(True))
        file_menu.add_separator()
        file_menu.add_command(label="Export…", accelerator="Ctrl+E", command=self.show_export_dialog)
        file_menu.add_command(label="LaTeX Source…", command=self.show_latex_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Shift+Z", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Delete Selection", accelerator="Delete", command=self.remove_selected)
        menu.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(label="Snap to Grid", variable=self.snap)
        view_menu.add_checkbutton(label="Show Page Grid", variable=self.show_grid, command=self.redraw)
        menu.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Keyboard Shortcuts", command=self._show_shortcuts)
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo("About", APP_NAME + "\nVersion 0.1\nOpen source under the MIT License"))
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="⚛  " + APP_NAME, style="Heading.TLabel").pack(side="left", padx=(2, 18))
        self.tool_buttons = {}
        for key, label in (("select", "Select (V)"), ("vertex", "Vertex (A)"), ("connect", "Connect (C)"), ("loop", "Loop (L)")):
            button = ttk.Button(toolbar, text=label, style="Tool.TButton", command=lambda value=key: self.set_tool(value))
            button.pack(side="left", padx=2)
            self.tool_buttons[key] = button
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="↶ Undo", command=self.undo).pack(side="left", padx=2)
        ttk.Button(toolbar, text="↷ Redo", command=self.redo).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Export…", command=self.show_export_dialog).pack(side="right", padx=2)
        ttk.Button(toolbar, text="LaTeX", command=self.show_latex_dialog).pack(side="right", padx=2)
        ttk.Button(toolbar, text="Save", command=self.save_document).pack(side="right", padx=2)
        ttk.Button(toolbar, text="Open", command=self.open_document).pack(side="right", padx=2)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True)
        self.library = ttk.Frame(body, padding=10, width=220)
        center = ttk.Frame(body, padding=(8, 8))
        inspector_host = ttk.Frame(body, width=270)
        body.add(self.library, weight=0)
        body.add(center, weight=1)
        body.add(inspector_host, weight=0)

        ttk.Label(self.library, text="STARTING POINTS", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Button(self.library, text="＋ New blank diagram", command=self.new_document).pack(fill="x", pady=(0, 8))
        self.template_list = tk.Listbox(self.library, exportselection=False, height=12, activestyle="dotbox")
        for document in templates():
            self.template_list.insert("end", document.title)
        self.template_list.pack(fill="both", expand=True)
        self.template_list.bind("<<ListboxSelect>>", self._load_selected_template)
        ttk.Label(self.library, text="Version 0.1 · Native prototype", foreground="#64748b").pack(anchor="w", pady=(8, 0))

        heading = ttk.Frame(center)
        heading.pack(fill="x", pady=(0, 6))
        ttk.Label(heading, text="FEYNMAN DIAGRAM", style="Eyebrow.TLabel").pack(anchor="w")
        self.title_label = ttk.Label(heading, text=self.document.title, style="Heading.TLabel")
        self.title_label.pack(anchor="w")
        self.canvas = tk.Canvas(center, background="#dfe5eb", highlightthickness=0, cursor="arrow")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self.redraw())
        self.canvas.bind("<Button-1>", self._canvas_down)
        self.canvas.bind("<B1-Motion>", self._canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._canvas_up)
        self.hint = ttk.Label(center, text="", foreground="#64748b")
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
                distance = 10 if event.state & 1 else 1
                if key == "left":
                    vertex.x = max(20, vertex.x - distance)
                elif key == "right":
                    vertex.x = min(700, vertex.x + distance)
                elif key == "up":
                    vertex.y = max(20, vertex.y - distance)
                else:
                    vertex.y = min(460, vertex.y + distance)
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
        cursor = {"select": "arrow", "vertex": "crosshair", "connect": "crosshair", "loop": "crosshair"}[self.tool]
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

    def undo(self) -> None:
        if not self.past:
            return
        self.future.insert(0, self.document)
        self.document = self.past.pop()
        self.selected = None
        self.connection_start = None
        self.status.set("Undid change")
        self._changed()

    def redo(self) -> None:
        if not self.future:
            return
        self.past.append(self.document)
        self.document = self.future.pop(0)
        self.selected = None
        self.connection_start = None
        self.status.set("Redid change")
        self._changed()

    def new_document(self) -> None:
        self._replace_document(blank_diagram(), "New diagram")

    def _replace_document(self, document: Diagram, status: str) -> None:
        before = self.document.clone()
        self.document = document.clone()
        self.selected = None
        self.connection_start = None
        self.current_path = None
        self._record(before, status)

    def _load_selected_template(self, _event) -> None:
        selection = self.template_list.curselection()
        if selection:
            self._replace_document(templates()[selection[0]], "Template loaded")

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
        offset = ((width - WIDTH * scale) / 2, (height - HEIGHT * scale) / 2)
        self.canvas_scale, self.canvas_offset = scale, offset
        ox, oy = offset
        self.canvas.create_rectangle(ox, oy, ox + WIDTH * scale, oy + HEIGHT * scale, fill="white", outline="#b8c1cc", width=1, tags="paper")
        draw_tk(self.canvas, self.document, scale, offset, self.show_grid.get())
        for vertex in self.document.vertices:
            x, y = self._screen(vertex.x, vertex.y)
            radius = 7 if vertex.id == self.selected or vertex.id == self.connection_start else 4
            color = "#2563eb" if vertex.id == self.selected else "#f59e0b" if vertex.id == self.connection_start else "#94a3b8"
            self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill="white", outline=color, width=2, tags="controls")
        edge = self.document.edge(self.selected or "")
        if edge:
            start, end = self.document.vertex(edge.from_), self.document.vertex(edge.to)
            if start and end:
                points, _ = geometry(start, end, edge)
                coordinates = [coordinate for point in points for coordinate in self._screen(*point)]
                self.canvas.create_line(*coordinates, fill="#2563eb", width=2, dash=(5, 4), tags="controls")
        self.count_label.configure(text="{} vertices · {} propagators".format(len(self.document.vertices), len(self.document.edges)))
        self.hint.configure(text=self._hint_text())

    def _hint_text(self) -> str:
        if self.tool == "vertex":
            return "Click the page to place a vertex."
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
                points, _ = geometry(start, end, edge)
                distance = distance_to_polyline(x, y, points)
                if distance < best[0]:
                    best = (distance, edge)
        return best[1]

    def _label_hit(self, x: float, y: float) -> Tuple[Optional[str], Optional[str]]:
        if self.selected:
            vertex = self.document.vertex(self.selected)
            if vertex and vertex.label and math.hypot(vertex.x + vertex.labelX - x, vertex.y + vertex.labelY - y) < 18:
                return "vertex_label", vertex.id
            edge = self.document.edge(self.selected)
            if edge and edge.label:
                start, end = self.document.vertex(edge.from_), self.document.vertex(edge.to)
                if start and end:
                    _, middle = geometry(start, end, edge)
                    lx, ly = middle.x + middle.nx * edge.labelOffset, middle.y + middle.ny * edge.labelOffset
                    if math.hypot(lx - x, ly - y) < 18:
                        return "edge_label", edge.id
        return None, None

    def _canvas_down(self, event) -> None:
        x, y = self._document_point(event)
        if not self._inside_page(x, y):
            return
        if self.tool == "vertex":
            if len(self.document.vertices) >= 150:
                messagebox.showerror("Vertex limit", "A project may contain at most 150 vertices.")
                return
            if self.snap.get():
                x, y = round(x / 10) * 10, round(y / 10) * 10
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
            self.drag_kind, self.drag_id = label_kind, label_id
        elif vertex:
            self.selected = vertex.id
            self.drag_kind, self.drag_id = "vertex", vertex.id
        else:
            edge = self._nearest_edge(x, y)
            self.selected = edge.id if edge else None
            self.drag_kind = self.drag_id = None
        if self.drag_id:
            self.drag_before = self.document.clone()
            self.drag_origin = (x, y)
            self.drag_changed = False
        self._rebuild_inspector()
        self.redraw()

    def _canvas_drag(self, event) -> None:
        if not self.drag_kind or not self.drag_id:
            return
        x, y = self._document_point(event)
        old_x, old_y = self.drag_origin
        dx, dy = x - old_x, y - old_y
        self.drag_origin = (x, y)
        if self.drag_kind == "vertex":
            vertex = self.document.vertex(self.drag_id)
            if vertex:
                nx, ny = vertex.x + dx, vertex.y + dy
                if self.snap.get():
                    nx, ny = round(nx / 10) * 10, round(ny / 10) * 10
                vertex.x, vertex.y = max(20, min(700, nx)), max(20, min(460, ny))
        elif self.drag_kind == "vertex_label":
            vertex = self.document.vertex(self.drag_id)
            if vertex:
                vertex.labelX = max(-150, min(150, vertex.labelX + dx))
                vertex.labelY = max(-150, min(150, vertex.labelY + dy))
        elif self.drag_kind == "edge_label":
            edge = self.document.edge(self.drag_id)
            if edge:
                start, end = self.document.vertex(edge.from_), self.document.vertex(edge.to)
                if start and end:
                    _, middle = geometry(start, end, edge)
                    edge.labelOffset = max(-120, min(120, edge.labelOffset + dx * middle.nx + dy * middle.ny))
        self.drag_changed = True
        self.redraw()

    def _canvas_up(self, _event) -> None:
        if self.drag_changed and self.drag_before:
            self._record(self.drag_before, "Object moved")
        self.drag_kind = self.drag_id = None
        self.drag_before = None
        self.drag_changed = False

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

    def _entry(self, label: str, value, callback: Callable[[str], None]) -> None:
        ttk.Label(self.inspector, text=label).pack(anchor="w", pady=(4, 1))
        variable = tk.StringVar(value=str(value))
        entry = ttk.Entry(self.inspector, textvariable=variable)
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
        for child in self.inspector.winfo_children():
            child.destroy()
        ttk.Label(self.inspector, text="Inspector", style="Heading.TLabel").pack(anchor="w")
        if self.tool in ("connect", "loop"):
            self._section("New " + ("propagator" if self.tool == "connect" else "loop"))
            self._choice("Line type", self.new_kind, [kind.title() for kind in KINDS], lambda value: setattr(self, "new_kind", value.lower()))
            if self.tool == "loop":
                self._choice("Loop type", "Single vertex" if self.loop_mode == "single" else "Two vertices", ("Single vertex", "Two vertices"), self._set_loop_mode)
        vertex = self.document.vertex(self.selected or "")
        edge = self.document.edge(self.selected or "")
        if vertex:
            self._section("Vertex")
            self._entry("Label (TeX)", vertex.label, lambda value: self.commit(lambda document: setattr(document.vertex(vertex.id), "label", value)))
            for label, attribute, minimum, maximum in (("X position", "x", 20, 700), ("Y position", "y", 20, 460), ("Label X", "labelX", -150, 150), ("Label Y", "labelY", -150, 150)):
                self._entry(label, _clean_number(getattr(vertex, attribute)), self._number_callback(lambda value, attr=attribute: self.commit(lambda document: setattr(document.vertex(vertex.id), attr, value)), minimum, maximum))
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
            ttk.Button(self.inspector, text="Line color…", command=lambda: self._choose_edge_color(edge.id)).pack(fill="x", pady=(6, 0))
            ttk.Button(self.inspector, text="Delete propagator", command=self.remove_selected).pack(fill="x", pady=(6, 0))
        else:
            self._section("Document")
            self._entry("Diagram name", self.document.title, lambda value: self.commit(lambda document: setattr(document, "title", value.strip()[:100] or "Untitled diagram")))

        self._section("Figure style")
        self._entry("Figure width (mm)", _clean_number(self.document.style.widthMm), self._number_callback(lambda value: self.commit(lambda document: setattr(document.style, "widthMm", value)), 60, 240))
        self._entry("Line width (pt)", _clean_number(self.document.style.strokePt), self._number_callback(lambda value: self.commit(lambda document: setattr(document.style, "strokePt", value)), 0.3, 2))
        self._entry("Text size (pt)", _clean_number(self.document.style.fontPt), self._number_callback(lambda value: self.commit(lambda document: setattr(document.style, "fontPt", value)), 5, 18))
        ttk.Checkbutton(self.inspector, text="Snap to grid", variable=self.snap).pack(anchor="w", pady=(7, 0))
        ttk.Checkbutton(self.inspector, text="Show page grid", variable=self.show_grid, command=self.redraw).pack(anchor="w")

        self._section("Objects")
        object_list = tk.Listbox(self.inspector, height=min(9, max(3, len(self.document.vertices) + len(self.document.edges))), exportselection=False)
        object_ids = []
        for index, item in enumerate(self.document.vertices, 1):
            object_list.insert("end", "Vertex {}{}".format(index, " · " + item.label if item.label else ""))
            object_ids.append(item.id)
        for index, item in enumerate(self.document.edges, 1):
            object_list.insert("end", "{} {}".format(item.kind.title(), index))
            object_ids.append(item.id)
        if self.selected in object_ids:
            object_list.selection_set(object_ids.index(self.selected))
            object_list.see(object_ids.index(self.selected))
        object_list.pack(fill="x")

        def select_object(_event):
            selection = object_list.curselection()
            if selection:
                self.selected = object_ids[selection[0]]
                self._rebuild_inspector()
                self.redraw()

        object_list.bind("<<ListboxSelect>>", select_object)

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
        labels = [item.label for item in FORMATS]
        format_var = tk.StringVar(value=labels[0])
        combo = ttk.Combobox(header, state="readonly", textvariable=format_var, values=labels, width=24)
        combo.pack(side="right")
        note = ttk.Label(frame, text="", foreground="#64748b")
        note.pack(fill="x", pady=(8, 4))
        source = tk.Text(frame, wrap="none", font=("TkFixedFont", 11), undo=False)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=source.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=source.xview)
        source.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        source.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")

        def selected_format():
            return FORMATS[labels.index(format_var.get())]

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
                self.status.set("Restored local draft")
                self.title_label.configure(text=self.document.title)
                self._rebuild_inspector()
        except (OSError, DiagramError):
            self.status.set("Could not restore the previous draft")

    def _show_shortcuts(self) -> None:
        messagebox.showinfo(
            "Keyboard shortcuts",
            "V  Select\nA  Add vertex\nC  Connect vertices\nL  Add loop\n\nCtrl+Z  Undo\nCtrl+Shift+Z  Redo\nDelete  Remove selection\nArrow keys  Nudge selected vertex\nShift+Arrow  Nudge by 10",
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
