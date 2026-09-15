import math
import tempfile
import unittest
from pathlib import Path

from feynman_studio.geometry import curve, geometry
from feynman_studio.latex import FORMATS, latex_source, standalone_source
from feynman_studio.model import Diagram, DiagramError, KINDS, blank_diagram, make_edge, make_vertex, templates
from feynman_studio.render import display_label, save_pdf, save_raster, svg_document

try:
    from PIL import Image
except ImportError:  # The source-only core remains testable without the optional encoder.
    Image = None


class ModelTests(unittest.TestCase):
    def test_templates_round_trip_through_project_json(self):
        for document in templates():
            self.assertEqual(Diagram.from_json(document.to_json()), document)
            self.assertIn('"from":', document.to_json())
            self.assertNotIn('"from_":', document.to_json())

    def test_invalid_projects_are_rejected(self):
        base = templates()[0].to_dict()
        cases = []
        missing = Diagram.from_dict(base).to_dict()
        missing["edges"][0]["from"] = "missing"
        cases.append(missing)
        duplicate = Diagram.from_dict(base).to_dict()
        duplicate["vertices"][1]["id"] = duplicate["vertices"][0]["id"]
        cases.append(duplicate)
        version = Diagram.from_dict(base).to_dict()
        version["version"] = 2
        cases.append(version)
        nonfinite = Diagram.from_dict(base).to_dict()
        nonfinite["vertices"][0]["x"] = math.inf
        cases.append(nonfinite)
        for value in cases:
            with self.assertRaises(DiagramError):
                Diagram.from_dict(value)

    def test_deleting_vertex_removes_connected_edges(self):
        document = templates()[0]
        document.remove("v3")
        self.assertEqual([edge.id for edge in document.edges], ["e4", "e5"])


class GeometryTests(unittest.TestCase):
    def test_curved_midpoint_matches_quadratic(self):
        a, b = make_vertex(0, 0), make_vertex(100, 0)
        point = curve(a, b, 80, 0.5)
        self.assertAlmostEqual(point.x, 50)
        self.assertAlmostEqual(point.y, 40)
        self.assertAlmostEqual(point.tx, 1)
        self.assertAlmostEqual(point.ny, 1)

    def test_every_line_type_attaches_to_endpoints(self):
        a, b = make_vertex(110, 100), make_vertex(600, 370)
        for kind in KINDS:
            for curvature in (-220, -65, 0, 80, 220):
                points, _ = geometry(a, b, make_edge(a.id, b.id, kind, curvature=curvature))
                self.assertAlmostEqual(points[0][0], a.x)
                self.assertAlmostEqual(points[0][1], a.y)
                self.assertAlmostEqual(points[-1][0], b.x)
                self.assertAlmostEqual(points[-1][1], b.y)

    def test_self_loop_is_finite_and_closed(self):
        point = make_vertex(360, 260)
        edge = make_edge(point.id, point.id)
        edge.loopSize = 100
        edge.loopAngle = -90
        points, middle = geometry(point, point, edge)
        self.assertAlmostEqual(points[0][0], points[-1][0])
        self.assertAlmostEqual(points[0][1], points[-1][1])
        self.assertLess(middle.y, 170)
        self.assertTrue(all(math.isfinite(value) for pair in points for value in pair))


class ExportTests(unittest.TestCase):
    def test_svg_has_physical_size_and_escapes_labels(self):
        document = templates()[0]
        document.title = '<script>alert("x")</script>'
        document.vertices[0].label = "<unsafe>"
        source = svg_document(document)
        self.assertIn('width="120.0mm" height="80.0mm"', source)
        self.assertNotIn("<script>", source)
        self.assertNotIn("<unsafe>", source)
        self.assertIn("&lt;unsafe&gt;", source)
        self.assertNotIn("<rect", svg_document(document, True))

    def test_all_markers_and_line_styles_render(self):
        document = blank_diagram()
        for index, marker in enumerate(("dot", "open", "filled", "hatched", "crosshatched", "dotted")):
            vertex = make_vertex(70 + index * 100, 100, visible=True)
            vertex.marker = marker
            document.vertices.append(vertex)
        left, right = make_vertex(100, 300), make_vertex(620, 300)
        document.vertices.extend((left, right))
        for index, kind in enumerate(KINDS):
            document.edges.append(make_edge(left.id, right.id, kind, kind, (index - 2) * 40))
        source = svg_document(document)
        self.assertIn('stroke-dasharray="9 7"', source)
        self.assertIn('stroke-dasharray="1 7"', source)
        self.assertGreater(source.count("<circle"), 8)

    def test_all_latex_dialects_include_labels_and_standalone_wrapper(self):
        document = templates()[0]
        for option in FORMATS:
            source = latex_source(document, option.value)
            self.assertIn("e^{-}", source)
            self.assertNotRegex(source, r"NaN|Infinity|undefined|null")
            standalone = standalone_source(document, option.value)
            self.assertIn(r"\documentclass{article}", standalone)
            self.assertIn(source, standalone)
            self.assertTrue(standalone.endswith(r"\end{document}"))

    def test_common_tex_labels_have_native_preview(self):
        self.assertEqual(display_label(r"\mu^{+}"), "μ⁺")
        self.assertEqual(display_label(r"p_1"), "p₁")
        self.assertEqual(display_label(r"\bar{q}"), "q̅")
        self.assertEqual(display_label(r"\frac{g^2}{4\pi}"), "(g²)⁄(4π)")

    @unittest.skipUnless(Image is not None, "Pillow is not installed")
    def test_png_jpeg_and_pdf_exports_are_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = templates()[0]
            save_raster(document, root / "diagram.png", 300, True)
            save_raster(document, root / "diagram.jpg", 300)
            save_pdf(document, root / "diagram.pdf", 300)
            with Image.open(root / "diagram.png") as image:
                self.assertEqual(image.size, (1417, 945))
                self.assertEqual(image.mode, "RGBA")
            with Image.open(root / "diagram.jpg") as image:
                self.assertEqual(image.size, (1417, 945))
                self.assertEqual(image.mode, "RGB")
            pdf = (root / "diagram.pdf").read_bytes()
            self.assertTrue(pdf.startswith(b"%PDF-"))
            self.assertNotIn(b"/Subtype /Image", pdf)


if __name__ == "__main__":
    unittest.main()
