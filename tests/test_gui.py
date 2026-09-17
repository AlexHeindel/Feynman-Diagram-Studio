import tkinter as tk
import unittest
import sys
import subprocess
from types import SimpleNamespace

from feynman_studio.app import StudioApp, check_tk_version
from feynman_studio.model import blank_diagram, make_edge, make_vertex


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
        try:
            app = StudioApp(root)
            root.update_idletasks()
            root.update()
            self.assertGreater(root.winfo_width(), 900)
            self.assertGreater(app.canvas.winfo_width(), 300)
            self.assertEqual(len(app.tool_buttons), 4)
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
            self.assertIs(app.object_list.master, app.library)
            self.assertEqual(app.object_list.size(), len(app.document.vertices) + len(app.document.edges))
            self.assertEqual(app.template_list.size(), 10)
            self.assertIsNotNone(app.canvas_preview)
            self.assertGreaterEqual(len(app.canvas.find_all()), len(app.document.vertices) + 2)
            app.set_tool("connect")
            self.assertEqual(app.tool, "connect")
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
