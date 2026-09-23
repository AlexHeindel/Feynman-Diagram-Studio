import math
import json
import tempfile
import unittest
from pathlib import Path

from feynman_studio.geometry import curve, geometry, momentum_geometry
from feynman_studio.latex import FORMATS, latex_source, standalone_source, unsupported_features
from feynman_studio.model import GRID_SIZE, Diagram, DiagramError, KINDS, blank_diagram, bundle_offsets, make_edge, make_vertex, snap_value, templates
from feynman_studio.render import Text, _label_runs, display_label, make_scene, render_preview, save_pdf, save_raster, svg_document

try:
    from PIL import Image
except ImportError:  # The source-only core remains testable without the optional encoder.
    Image = None


class ModelTests(unittest.TestCase):
    def test_version_two_annotations_round_trip_and_capabilities(self):
        source = json.loads((Path(__file__).parent / "fixtures" / "annotations-v2.json").read_text())
        diagram = Diagram.from_dict(source)
        self.assertEqual(Diagram.from_json(diagram.to_json()), diagram)
        self.assertEqual(len(diagram.annotations), 2)
        self.assertTrue(any(item.source == "p" for item in make_scene(diagram) if isinstance(item, Text)))
        for option in FORMATS:
            self.assertEqual(unsupported_features(diagram, option.value), [])
            self.assertIn("Gamma", latex_source(diagram, option.value))
        for change in (
            lambda raw: raw["annotations"][0].update(id="left"),
            lambda raw: raw["annotations"][0].update(x=721),
            lambda raw: raw["annotations"][0].update(text="a" * 201),
            lambda raw: raw["annotations"][1].update(color="red"),
            lambda raw: raw["edges"][0]["momentum"].update(start=0.8),
        ):
            invalid = json.loads(json.dumps(source))
            change(invalid)
            with self.assertRaises(DiagramError):
                Diagram.from_dict(invalid)
        diagram.annotations[0].color = "#FF0000"
        self.assertIn("Custom colors", unsupported_features(diagram, "feynmf")[0])
        with self.assertRaises(ValueError):
            latex_source(diagram, "feynmf")
        diagram.edges[0].bundle = 3
        self.assertIn("Quark bundle", unsupported_features(diagram, "feynmp")[0])

    def test_momentum_short_reversed_and_curved(self):
        raw = json.loads((Path(__file__).parent / "fixtures" / "annotations-v2.json").read_text())
        diagram = Diagram.from_dict(raw)
        edge = diagram.edges[0]
        edge.momentum.start, edge.momentum.end = 0.42, 0.58
        for curvature in (0, 100, -100):
            edge.curvature = curvature
            for direction in ("forward", "reverse"):
                edge.momentum.direction = direction
                points, arrow, label = momentum_geometry(diagram.vertices[0], diagram.vertices[1], edge)
                self.assertGreaterEqual(len(points), 3)
                self.assertTrue(all(math.isfinite(v) for point in (*points, *arrow, label) for v in point))
                self.assertEqual(arrow[0], points[-1] if direction == "forward" else points[0])
        edge.to = edge.from_
        edge.curvature = 0
        points, arrow, label = momentum_geometry(diagram.vertices[0], diagram.vertices[0], edge)
        self.assertGreater(len(points), 3)
        self.assertTrue(all(math.isfinite(v) for point in (*points, *arrow, label) for v in point))

    def test_templates_round_trip_through_project_json(self):
        for document in templates():
            self.assertEqual(Diagram.from_json(document.to_json()), document)
            self.assertIn('"from":', document.to_json())
            self.assertNotIn('"from_":', document.to_json())

    def test_old_projects_load_and_new_label_coordinates_round_trip(self):
        source = templates()[0].to_dict()
        for edge in source["edges"]:
            edge.pop("labelX")
            edge.pop("labelY")
        document = Diagram.from_dict(source)
        self.assertTrue(all(edge.labelX == edge.labelY == 0 for edge in document.edges))
        document.edges[0].labelX = 35
        document.edges[0].labelY = -18
        self.assertEqual(Diagram.from_json(document.to_json()), document)
        source["edges"][0]["labelX"] = float("inf")
        with self.assertRaises(DiagramError):
            Diagram.from_dict(source)

    def test_template_library_includes_reference_and_common_examples(self):
        documents = templates()
        titles = {document.title for document in documents}
        self.assertEqual(len(documents), 10)
        self.assertTrue(
            {
                "Top-pair Higgs production",
                "Penguin diagram",
                "Kaon decay to three pions",
                "Compton scattering",
                "Muon decay",
                "Vacuum polarization",
            }.issubset(titles)
        )

    def test_reference_templates_use_ordered_textbook_layouts(self):
        documents = {document.title: document for document in templates()}
        compton = documents["Compton scattering"]
        self.assertEqual({vertex.y for vertex in compton.vertices[:4]}, {240})
        muon = documents["Muon decay"]
        self.assertEqual([vertex.y for vertex in muon.vertices[:4]], [160, 160, 320, 160])
        kaon = documents["Kaon decay to three pions"]
        self.assertEqual([vertex.y for vertex in kaon.vertices[6:]], [60, 140, 220, 300, 380, 440])

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
        version["version"] = 3
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

    def test_grid_snapping_matches_the_visible_grid(self):
        self.assertEqual(snap_value(570), 580)
        self.assertEqual(snap_value(230), 240)
        self.assertEqual(snap_value(26, 10), 30)
        self.assertEqual(snap_value(26, 40), 40)
        for document in templates():
            for vertex in document.vertices:
                self.assertEqual(vertex.x % GRID_SIZE, 0)
                self.assertEqual(vertex.y % GRID_SIZE, 0)


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

    def test_quark_bundle_lanes_remain_parallel_at_the_endpoints(self):
        left, right = make_vertex(100, 240), make_vertex(620, 240)
        edge = make_edge(left.id, right.id)
        edge.bundle, edge.bundleSpacing = 3, 20
        lanes = [geometry(left, right, edge, offset)[0] for offset in bundle_offsets(edge)]
        for points, expected_y in zip(lanes, (220, 240, 260)):
            self.assertTrue(all(abs(y - expected_y) < 1e-9 for _, y in points))

    def test_gluon_curls_stay_between_straight_line_endpoints(self):
        top, bottom = make_vertex(360, 100), make_vertex(360, 380)
        points, _ = geometry(top, bottom, make_edge(top.id, bottom.id, "gluon"))
        self.assertTrue(all(top.y <= y <= bottom.y for _, y in points))
        self.assertGreater(max(abs(x - top.x) for x, _ in points[-24:]), 6.5)


class ExportTests(unittest.TestCase):
    @unittest.skipUnless(Image is not None, "Pillow is not installed")
    def test_preview_grid_spacing_changes_visible_lines(self):
        document = blank_diagram()
        fine = render_preview(document, 720, 480, True, oversample=1, grid_size=10)
        standard = render_preview(document, 720, 480, True, oversample=1, grid_size=20)
        coarse = render_preview(document, 720, 480, True, oversample=1, grid_size=40)
        self.assertNotEqual(fine.getpixel((10, 100)), standard.getpixel((10, 100)))
        self.assertNotEqual(standard.getpixel((20, 100)), coarse.getpixel((20, 100)))

    def test_moved_propagator_label_appears_at_same_position_in_exports(self):
        document = blank_diagram()
        start, end = make_vertex(100, 200), make_vertex(620, 200)
        edge = make_edge(start.id, end.id, label="p")
        edge.labelX, edge.labelY = 40, 30
        document.vertices.extend((start, end))
        document.edges.append(edge)
        self.assertIn((400, 205), [item.point for item in make_scene(document) if isinstance(item, Text)])
        self.assertIn('x="400.000" y="205.000"', svg_document(document))
        self.assertIn("at (400,205)", latex_source(document, "tikz-feynman"))
        for format_name in ("feynmp", "feynmf"):
            source = latex_source(document, format_name)
            self.assertIn(r"\begin{fmfgraph*}", source)
            self.assertIn(r"\fmfiv{l=$p$,l.a=0,l.d=0}{(0.555556w,0.572917h)}", source)
        self.assertIn(r"\rput(400,275)", latex_source(document, "pst-feyn"))
        self.assertIn(r"\Text(189.7,130.4)", latex_source(document, "axodraw2"))

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
        self.assertEqual(display_label(r"\bar{q}"), "q̄")
        self.assertEqual(display_label(r"\nu_{\mu}"), "ν_μ")
        self.assertEqual(display_label(r"\bar{\nu}_{e}"), "ν̄_e")
        self.assertEqual([(run.text, run.script, run.overbar) for run in _label_runs(r"\nu_{\mu}", "")], [("ν", 0, False), ("μ", 1, False)])
        self.assertEqual([(run.text, run.script, run.overbar) for run in _label_runs(r"\bar{d}", "")], [("d", 0, True)])
        self.assertEqual(display_label(r"\frac{g^2}{4\pi}"), "(g²)⁄(4π)")

    @unittest.skipUnless(Image is not None, "Pillow is not installed")
    def test_preview_is_supersampled_and_antialiased(self):
        document = blank_diagram()
        start, end = make_vertex(100, 100), make_vertex(620, 380)
        document.vertices.extend((start, end))
        document.edges.append(make_edge(start.id, end.id))
        image = render_preview(document, 360, 240)
        self.assertEqual(image.size, (360, 240))
        colors = {color for _, color in image.getcolors(maxcolors=360 * 240)}
        self.assertTrue(any(color not in ((255, 255, 255, 255), (23, 35, 51, 255)) for color in colors))

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
