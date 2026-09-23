import tkinter as tk
from tkinter import ttk
import unittest
import sys
import subprocess
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from feynman_studio.app import StudioApp, check_tk_version
from feynman_studio.model import KINDS, Momentum, blank_diagram, make_edge, make_vertex


class GuiSmokeTests(unittest.TestCase):
    def test_vertex_tool_switches_to_select_and_new_style_settings_apply(self):
        app = StudioApp.__new__(StudioApp)
        app.document = blank_diagram()
        app.past, app.future = [], []
        app.selected = app.connection_start = None
        app.tool = "vertex"
        app.new_marker, app.new_marker_size = "hatched", 30
        app.new_kind, app.new_arrow = "fermion", "reverse"
        app.snap = SimpleNamespace(get=lambda: False)
        app.grid_size = SimpleNamespace(get=lambda: 20)
        app.canvas_scale, app.canvas_offset = 1, (0, 0)
        app.status = SimpleNamespace(set=lambda _value: None)
        app._changed = app.redraw = app._update_tool_buttons = lambda: None
        point = lambda x, y: SimpleNamespace(x=x, y=y)
        app._canvas_down(point(100, 100))
        self.assertEqual(app.tool, "select")
        self.assertEqual(app.selected, app.document.vertices[0].id)
        app.tool = "vertex"
        app._canvas_down(point(200, 100))
        self.assertEqual(app.tool, "select")
        self.assertEqual(app.selected, app.document.vertices[1].id)
        self.assertEqual([(item.marker, item.markerSize) for item in app.document.vertices],
                         [("hatched", 30), ("hatched", 30)])
        app.tool = "connect"
        app.selected = None
        app._canvas_down(point(100, 100))
        app._canvas_down(point(200, 100))
        self.assertEqual(app.document.edges[0].arrow, "reverse")
        self.assertIsNone(app.selected)

    def test_local_project_list_restores_and_falls_back_to_latest_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autosave.json"
            first, second = blank_diagram(), blank_diagram()
            first.title, second.title = "First", "Second"
            app = StudioApp.__new__(StudioApp)
            app.document = second
            app.projects = [{"id": "first", "diagram": first, "path": None},
                            {"id": "second", "diagram": second, "path": None}]
            app.active_project_id = "second"
            app.current_path = None
            app.status = SimpleNamespace(set=lambda _value: None)
            app._autosave_path = lambda: path
            app._autosave()

            def restored_app():
                restored = StudioApp.__new__(StudioApp)
                restored.document = blank_diagram()
                restored.projects = [{"id": "initial", "diagram": restored.document, "path": None}]
                restored.active_project_id = "initial"
                restored.current_path = None
                restored.snap = SimpleNamespace(get=lambda: False)
                restored.status = SimpleNamespace(set=lambda _value: None)
                restored.title_label = SimpleNamespace(configure=lambda **_values: None)
                restored._autosave_path = lambda: path
                restored._rebuild_project_list = lambda: None
                restored._rebuild_inspector = lambda: None
                return restored

            restored = restored_app()
            restored._restore_autosave()
            self.assertEqual([item["diagram"].title for item in restored.projects], ["First", "Second"])
            self.assertEqual(restored.document.title, "Second")
            path.with_name("projects.json").write_text("{broken", encoding="utf-8")
            fallback = restored_app()
            fallback._restore_autosave()
            self.assertEqual(fallback.document.title, "Second")

    def test_obsolete_tk_has_an_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, r"Tk 8\.6.*\/usr\/bin\/python3"):
            check_tk_version(8.5)
        check_tk_version(8.6)

    def test_editor_constructs_and_renders_native_widgets(self):
        if sys.platform == "darwin" and tk.TkVersion < 8.6:
            self.skipTest("macOS system Tk 8.5 is obsolete; release builds bundle modern Tk")
        if sys.platform == "darwin":
            probe = subprocess.run(
                [sys.executable, "-c", "import tkinter as tk; root = tk.Tk(); root.destroy()"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if probe.returncode:
                self.skipTest("The macOS window server is unavailable")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest("A GUI display is unavailable: {}".format(exc))
        autosave = tempfile.TemporaryDirectory()
        self.addCleanup(autosave.cleanup)
        autosave_patch = patch.object(StudioApp, "_autosave_path", return_value=Path(autosave.name) / "autosave.json")
        autosave_patch.start()
        self.addCleanup(autosave_patch.stop)
        try:
            app = StudioApp(root)
            root.update_idletasks()
            root.update()
            self.assertEqual((app.app_icon.width(), app.app_icon.height()), (1024, 1024))
            self.assertGreater(root.winfo_width(), 900)
            self.assertGreater(app.canvas.winfo_width(), 300)
            self.assertEqual(len(app.tool_buttons), 4)
            self.assertEqual(list(app.menu_buttons), ["File", "Edit", "View", "Tools", "Help"])
            self.assertIs(app.menu_bar.master, app.file_controls.master)
            self.assertEqual(root.pack_slaves()[:2], [app.menu_bar.master, app.library.master])
            self.assertEqual(app.library.master.winfo_y(), app.menu_bar.master.winfo_y() + app.menu_bar.master.winfo_height())
            self.assertEqual(app.menu_buttons["View"].cget("text"), "View")
            self.assertEqual(app.theme_mode.get(), "automatic")
            self.assertEqual(app.grid_size.get(), 20)
            labels = [button.cget("text") for button in app.tool_buttons.values()]
            self.assertEqual(labels, ["Select", "Vertex", "Connect", "Loop"])
            self.assertTrue(all(button.master is app.diagram_tools for button in app.tool_buttons.values()))
            annotate = next(widget for widget in app.diagram_tools.winfo_children() if isinstance(widget, ttk.Menubutton))
            self.assertEqual(annotate.cget("style"), "Tool.TMenubutton")
            self.assertEqual(app.style.lookup("Tool.TMenubutton", "borderwidth"), 1)
            self.assertEqual(app.open_button.cget("text"), "Open")
            self.assertEqual(app.open_button.grid_info()["row"], 0)
            self.assertEqual(app.save_button.grid_info()["row"], 0)
            self.assertEqual(app.latex_button.grid_info()["row"], 0)
            self.assertEqual(app.export_button.grid_info()["row"], 0)
            self.assertIs(app.undo_button.master, app.history_controls)
            self.assertIs(app.redo_button.master, app.history_controls)
            self.assertEqual(app.undo_button.winfo_width(), app.redo_button.winfo_width())
            new_button = next(widget for widget in app.library.pack_slaves()
                              if isinstance(widget, ttk.Button) and widget.cget("text") == "＋ New blank diagram")
            projects_heading = next(widget for widget in app.library.pack_slaves()
                                    if isinstance(widget, ttk.Label) and widget.cget("text") == "MY DIAGRAMS")
            self.assertLess(new_button.winfo_y(), projects_heading.winfo_y())
            root.geometry("960x640")
            root.update()
            self.assertEqual(app.undo_button.winfo_width(), app.redo_button.winfo_width())
            self.assertLessEqual(app.menu_bar.winfo_x() + app.menu_bar.winfo_width(), app.file_controls.winfo_x())
            self.assertLess(app.menu_bar.winfo_y(), app.file_controls.winfo_y() + app.file_controls.winfo_height())
            self.assertLess(app.file_controls.winfo_y(), app.menu_bar.winfo_y() + app.menu_bar.winfo_height())
            self.assertIs(app.object_list.master, app.object_host)
            self.assertIs(app.object_scrollbar.master, app.object_host)
            self.assertGreaterEqual(app.object_scrollbar.winfo_width(), 10)
            self.assertEqual(app.object_list.size(), len(app.document.vertices) + len(app.document.edges))
            self.assertEqual(app.project_list.size(), 1)
            self.assertFalse(app.show_figure_panel.get())
            app.show_figure_panel.set(True)
            app._rebuild_inspector()
            self.assertIn("Figure style", [widget.cget("text") for widget in app.inspector.winfo_children() if isinstance(widget, ttk.Label)])
            app.show_figure_panel.set(False)
            app._rebuild_inspector()
            self.assertIsNotNone(app.canvas_preview)
            self.assertGreaterEqual(len(app.canvas.find_all()), len(app.document.vertices) + 2)
            for object_id in (app.document.vertices[0].id, app.document.edges[0].id):
                app.selected = object_id
                app._rebuild_inspector()
                labels = [widget.cget("text") for widget in app.inspector.winfo_children() if isinstance(widget, ttk.Label)]
                self.assertIn(labels[0], ("Selection",))
            edge = app.document.edges[0]
            edge.momentum = Momentum()
            app.show_figure_panel.set(True)
            app._rebuild_inspector()
            root.update()
            scrollbar = next(widget for widget in app.inspector_canvas.master.winfo_children()
                             if isinstance(widget, ttk.Scrollbar))
            self.assertTrue(scrollbar.winfo_ismapped())
            self.assertGreaterEqual(scrollbar.winfo_width(), 10)
            fine_button = next(widget for widget in app.inspector.winfo_children()
                               if isinstance(widget, ttk.Button) and widget.cget("text") == "Fine placement…")
            fine_button.invoke()
            root.update()
            self.assertTrue(app._fine_placement_frame.winfo_manager())
            delete_button = next(widget for widget in app.inspector.winfo_children()
                                 if isinstance(widget, ttk.Button) and widget.cget("text") == "Delete propagator")
            self.assertLess(fine_button.winfo_y(), app._fine_placement_frame.winfo_y())
            self.assertLess(app._fine_placement_frame.winfo_y(), delete_button.winfo_y())
            app.inspector_canvas.yview_moveto(0.5)
            root.update()
            scroll_before = app.inspector_canvas.canvasy(0)
            app._set_momentum_fraction(edge.id, "start", 25)
            root.update()
            self.assertAlmostEqual(app.inspector_canvas.canvasy(0), scroll_before, delta=2)
            self.assertTrue(app._fine_placement_frame.winfo_manager())
            app._set_momentum_fraction(edge.id, "end", 75)
            root.update()
            self.assertTrue(app._fine_placement_frame.winfo_manager())
            app.inspector_canvas.yview_moveto(0.5)
            root.update()
            start_entry = next(widget for widget in app._fine_placement_frame.winfo_children()
                               if isinstance(widget, ttk.Entry))
            start_entry.focus_force()
            root.update()
            scroll_before = app.inspector_canvas.canvasy(0)
            start_entry.delete(0, "end")
            start_entry.insert(0, "30")
            start_entry.event_generate("<Return>")
            root.update()
            self.assertAlmostEqual(app.document.edge(edge.id).momentum.start, 0.3)
            self.assertAlmostEqual(app.inspector_canvas.canvasy(0), scroll_before, delta=2)
            app.inspector_canvas.yview_moveto(0)
            root.update()
            app.object_list.event_generate("<MouseWheel>", delta=-120,
                                           rootx=app.inspector_canvas.winfo_rootx() + 20,
                                           rooty=app.inspector_canvas.winfo_rooty() + 20)
            root.update()
            self.assertGreater(app.inspector_canvas.yview()[0], 0)
            app.inspector_canvas.yview_moveto(0)
            root.update()
            app.project_list.event_generate("<MouseWheel>", delta=-120,
                                            rootx=app.inspector_canvas.winfo_rootx() + 20,
                                            rooty=app.inspector_canvas.winfo_rooty() + 20)
            root.update()
            self.assertGreater(app.inspector_canvas.yview()[0], 0)
            app.inspector_canvas.yview_moveto(0)
            root.update()
            root.event_generate("<MouseWheel>", delta=-120,
                                rootx=app.inspector_canvas.winfo_rootx() + 20,
                                rooty=app.inspector_canvas.winfo_rooty() + 20)
            root.update()
            self.assertGreater(app.inspector_canvas.yview()[0], 0)
            if tk.TkVersion >= 9:
                app.inspector_canvas.yview_moveto(0)
                root.update()
                heading = next(widget for widget in app.inspector.winfo_children()
                               if isinstance(widget, ttk.Label) and widget.cget("text") == "Selection")
                heading.event_generate("<TouchpadScroll>", delta=(-40 & 0xFFFF),
                                       rootx=0, rooty=0)
                root.update()
                self.assertGreater(app.inspector_canvas.yview()[0], 0)
                heading.event_generate("<TouchpadScroll>", delta=40,
                                       rootx=0, rooty=0)
                root.update()
                self.assertAlmostEqual(app.inspector_canvas.yview()[0], 0)
            app.selected = None
            app.set_tool("connect")
            self.assertEqual(app.tool, "connect")
            app.theme_mode.set("light")
            app._apply_theme()
            light_background = app.canvas.cget("background")
            app.theme_mode.set("dark")
            app._apply_theme()
            self.assertNotEqual(app.canvas.cget("background"), light_background)
            app.show_latex_dialog()
            dialog = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
            source = next(widget for widget in dialog.winfo_children()[0].winfo_children()
                          if isinstance(widget, tk.Text))
            self.assertEqual(source.cget("background"), "#ffffff")
            self.assertEqual(source.cget("foreground"), "#132238")
            dialog.destroy()
            app.theme_mode.set("automatic")
            app._apply_theme()
            app.grid_size.set(10)
            app._grid_spacing_changed()
            self.assertEqual(app._snap_coordinate(26, 20, 700), 30)
            app.grid_size.set(40)
            app._grid_spacing_changed()
            self.assertEqual(app._snap_coordinate(26, 20, 700), 40)
            app._load_template(10)
            root.update()
            self.assertEqual(app.document.title, "Four-point scalar vertex")
            app.new_document()
            root.update()
            self.assertEqual(app.project_list.size(), 3)
            self.assertFalse(app.document.vertices)
            inspector_labels = [widget.cget("text") for widget in app.inspector.winfo_children() if isinstance(widget, ttk.Label)]
            self.assertNotIn("Diagram name", inspector_labels)
            for tool in ("select", "vertex", "connect", "loop"):
                app.set_tool(tool)
                labels = [widget.cget("text") for widget in app.inspector.winfo_children() if isinstance(widget, ttk.Label)]
                self.assertEqual(labels[0], {"select": "Selection", "vertex": "Add vertex", "connect": "Connect vertices", "loop": "Add loop"}[tool])
                if tool in ("connect", "loop"):
                    for kind in KINDS:
                        app.new_kind = kind
                        app._rebuild_inspector()
                        children = app.inspector.winfo_children()
                        line_type_index = next(index for index, widget in enumerate(children)
                                               if isinstance(widget, ttk.Label) and widget.cget("text") == "Line type")
                        self.assertIsInstance(children[line_type_index + 1], ttk.Combobox)
                        self.assertEqual(children[line_type_index + 1].get(), kind.title())

            self.assertTrue(app.title_label.bind("<Button-1>"))
            app.rename_diagram()
            root.update()
            self.assertIsNotNone(app.title_entry)
            app.title_entry.delete(0, "end")
            app.title_entry.insert(0, "Renamed diagram")
            self.assertTrue(app.title_entry.bind("<Return>"))
            self.assertTrue(app.title_entry.bind("<FocusOut>"))
            app._finish_title_edit(True)
            self.assertIsNone(app.title_entry)
            self.assertEqual(app.document.title, "Renamed diagram")
            self.assertEqual(app.title_label.cget("text"), "Renamed diagram")
            app.undo()
            self.assertEqual(app.document.title, "Untitled diagram")

            edit_menu = app.visible_menus["Edit"]
            rename_index = next(index for index in range(edit_menu.index("end") + 1)
                                if edit_menu.type(index) == "command" and edit_menu.entrycget(index, "label") == "Rename Diagram…")
            edit_menu.invoke(rename_index)
            root.update()
            self.assertIsNotNone(app.title_entry)
            app.title_entry.delete(0, "end")
            app.title_entry.insert(0, "Discard this name")
            self.assertTrue(app.title_entry.bind("<Escape>"))
            app._finish_title_edit(False)
            self.assertIsNone(app.title_entry)
            self.assertEqual(app.document.title, "Untitled diagram")

        finally:
            root.destroy()

    def test_file_menu_quit_exits_without_popup_error(self):
        if sys.platform == "darwin":
            probe = subprocess.run([sys.executable, "-c", "import tkinter as tk; root = tk.Tk(); root.destroy()"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if probe.returncode:
                self.skipTest("The macOS window server is unavailable")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest("A GUI display is unavailable: {}".format(exc))
        try:
            with tempfile.TemporaryDirectory() as directory:
                with patch.object(StudioApp, "_autosave_path", return_value=Path(directory) / "autosave.json"):
                    app = StudioApp(root)
                    file_menu = app.visible_menus["File"]
                    quit_index = next(index for index in range(file_menu.index("end") + 1)
                                      if file_menu.type(index) == "command" and file_menu.entrycget(index, "label") == "Quit")
                    with patch.object(file_menu, "tk_popup", side_effect=lambda *_: file_menu.invoke(quit_index)) as popup:
                        app.menu_buttons["File"].invoke()
                        popup.assert_called_once()
                    self.assertTrue(root.winfo_exists())
        finally:
            root.destroy()

    def test_clicking_any_label_selects_and_propagator_label_drags_freely(self):
        app = StudioApp.__new__(StudioApp)
        start, end = make_vertex(100, 100, "a"), make_vertex(620, 100, "b")
        edge = make_edge(start.id, end.id, label="p")
        app.document = blank_diagram()
        app.document.vertices.extend((start, end))
        app.document.edges.append(edge)
        app.selected = None
        app.tool = "select"
        app.canvas_scale = 1
        app.canvas_offset = (0, 0)
        app.drag_kind = app.drag_id = app.drag_before = None
        app.drag_changed = False
        app.past, app.future = [], []
        app.status = SimpleNamespace(set=lambda value: None)
        app.redraw = lambda: None
        app._rebuild_inspector = lambda: None
        app._changed = lambda: None

        def event_at(x, y):
            return SimpleNamespace(x=x, y=y)

        app._canvas_down(event_at(100, 70))
        self.assertEqual(app.selected, start.id)
        app._canvas_up(None)
        app._canvas_down(event_at(360, 75))
        self.assertEqual(app.selected, edge.id)
        app._canvas_drag(event_at(400, 105))
        app._canvas_up(None)
        self.assertEqual((edge.labelX, edge.labelY), (40, 30))
        self.assertEqual(len(app.past), 1)
        app.undo()
        self.assertEqual((app.document.edges[0].labelX, app.document.edges[0].labelY), (0, 0))

    def test_free_annotations_create_drag_and_undo_without_a_window(self):
        app = StudioApp.__new__(StudioApp)
        app.document = blank_diagram()
        app.selected = None
        app.tool = "label"
        app.canvas_scale = 1
        app.canvas_offset = (0, 0)
        app.drag_kind = app.drag_id = app.drag_before = None
        app.drag_changed = False
        app.past, app.future = [], []
        app.status = SimpleNamespace(set=lambda value: None)
        app.redraw = lambda: None
        app._rebuild_inspector = lambda: None
        app._changed = lambda: None
        app.set_tool = lambda tool: setattr(app, "tool", tool)
        point = lambda x, y: SimpleNamespace(x=x, y=y)

        app._canvas_down(point(250, 80))
        self.assertEqual((app.tool, len(app.document.annotations)), ("select", 1))
        label_id = app.document.annotations[0].id
        app._canvas_down(point(250, 80))
        app._canvas_drag(point(280, 100))
        app._canvas_up(None)
        self.assertEqual((app.document.annotations[0].x, app.document.annotations[0].y), (280, 100))
        app.undo()
        self.assertEqual((app.document.annotations[0].x, app.document.annotations[0].y), (250, 80))
        app.tool = "arrow"
        app._canvas_down(point(100, 350))
        app._canvas_drag(point(200, 350))
        app._canvas_up(None)
        self.assertEqual((app.tool, len(app.document.annotations)), ("select", 2))
        self.assertEqual((app.document.annotations[1].x2, app.document.annotations[1].y2), (200, 350))
        app.undo()
        self.assertEqual([item.id for item in app.document.annotations], [label_id])


if __name__ == "__main__":
    unittest.main()
