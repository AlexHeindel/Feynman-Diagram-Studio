import tkinter as tk
import unittest
import sys

from feynman_studio.app import StudioApp, check_tk_version


class GuiSmokeTests(unittest.TestCase):
    def test_obsolete_tk_has_an_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, r"Tk 8\.6.*\/usr\/bin\/python3"):
            check_tk_version(8.5)
        check_tk_version(8.6)

    def test_editor_constructs_and_renders_native_widgets(self):
        if sys.platform == "darwin" and tk.TkVersion < 8.6:
            self.skipTest("macOS system Tk 8.5 is obsolete; release builds bundle modern Tk")
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


if __name__ == "__main__":
    unittest.main()
