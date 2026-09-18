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
from feynman_studio.model import KINDS, blank_diagram, make_edge, make_vertex


class GuiSmokeTests(unittest.TestCase):
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
            self.assertGreater(root.winfo_width(), 900)
            self.assertGreater(app.canvas.winfo_width(), 300)
            self.assertEqual(len(app.tool_buttons), 4)
            self.assertEqual(list(app.menu_buttons), ["File", "Edit", "View", "Tools", "Help"])
            self.assertIs(app.menu_bar.master, app.file_controls.master)
            self.assertEqual(root.pack_slaves()[:2], [app.menu_bar.master, app.library.master])
            self.assertEqual(app.library.master.winfo_y(), app.menu_bar.master.winfo_y() + app.menu_bar.master.winfo_height())
            app.menu_buttons["View"].invoke()
            app.visible_menus["View"].unpost()
            self.assertEqual(app.theme_mode.get(), "automatic")
            self.assertEqual(app.grid_size.get(), 20)
            labels = [button.cget("text") for button in app.tool_buttons.values()]
            self.assertEqual(labels, ["Select", "Vertex", "Connect", "Loop"])
            self.assertTrue(all(button.master is app.diagram_tools for button in app.tool_buttons.values()))
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
            starting_points = next(widget for widget in app.library.pack_slaves()
                                   if isinstance(widget, ttk.Label) and widget.cget("text") == "STARTING POINTS")
            self.assertLess(new_button.winfo_y(), starting_points.winfo_y())
            root.geometry("960x640")
            root.update()
            self.assertEqual(app.undo_button.winfo_width(), app.redo_button.winfo_width())
            self.assertLessEqual(app.menu_bar.winfo_x() + app.menu_bar.winfo_width(), app.file_controls.winfo_x())
            self.assertLess(app.menu_bar.winfo_y(), app.file_controls.winfo_y() + app.file_controls.winfo_height())
            self.assertLess(app.file_controls.winfo_y(), app.menu_bar.winfo_y() + app.menu_bar.winfo_height())
            self.assertIs(app.object_list.master, app.library)
            self.assertEqual(app.object_list.size(), len(app.document.vertices) + len(app.document.edges))
            self.assertEqual(app.template_list.size(), 10)
            self.assertIsNotNone(app.canvas_preview)
            self.assertGreaterEqual(len(app.canvas.find_all()), len(app.document.vertices) + 2)
            for object_id in (app.document.vertices[0].id, app.document.edges[0].id):
                app.selected = object_id
                app._rebuild_inspector()
                labels = [widget.cget("text") for widget in app.inspector.winfo_children() if isinstance(widget, ttk.Label)]
                self.assertEqual(labels[:2], ["Inspector", "Figure style"])
            app.selected = None
            app.set_tool("connect")
            self.assertEqual(app.tool, "connect")
            app.theme_mode.set("light")
            app._apply_theme()
            light_background = app.canvas.cget("background")
            app.theme_mode.set("dark")
            app._apply_theme()
            self.assertNotEqual(app.canvas.cget("background"), light_background)
            app.theme_mode.set("automatic")
            app._apply_theme()
            app.grid_size.set(10)
            app._grid_spacing_changed()
            self.assertEqual(app._snap_coordinate(26, 20, 700), 30)
            app.grid_size.set(40)
            app._grid_spacing_changed()
            self.assertEqual(app._snap_coordinate(26, 20, 700), 40)
            app.template_list.selection_set(0)
            app.template_list.event_generate("<<ListboxSelect>>")
            root.update()
            self.assertTrue(app.template_list.curselection())
            app.new_document()
            root.update()
            self.assertFalse(app.template_list.curselection())
            self.assertFalse(app.document.vertices)
            inspector_labels = [widget.cget("text") for widget in app.inspector.winfo_children() if isinstance(widget, ttk.Label)]
            self.assertNotIn("Diagram name", inspector_labels)
            for tool in ("select", "vertex", "connect", "loop"):
                app.set_tool(tool)
                labels = [widget.cget("text") for widget in app.inspector.winfo_children() if isinstance(widget, ttk.Label)]
                self.assertEqual(labels[:2], ["Inspector", "Figure style"])
                if tool in ("connect", "loop"):
                    for kind in KINDS:
                        app.new_kind = kind
                        app._rebuild_inspector()
                        children = app.inspector.winfo_children()
                        line_type_index = next(index for index, widget in enumerate(children)
                                               if isinstance(widget, ttk.Label) and widget.cget("text") == "Line type")
                        self.assertIsInstance(children[line_type_index + 1], ttk.Combobox)
                        self.assertEqual(children[line_type_index + 1].get(), kind.title())

            self.assertTrue(app.title_label.bind("<Double-Button-1>"))
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


if __name__ == "__main__":
    unittest.main()
