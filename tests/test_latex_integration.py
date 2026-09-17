"""Compile and render every LaTeX dialect with a real local TeX toolchain."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

from feynman_studio.latex import FORMATS, latex_source, standalone_source
from feynman_studio.model import Diagram, Edge, FigureStyle, Vertex, templates
from feynman_studio.render import save_pdf, save_raster, svg_document

try:
    from PIL import Image
except ImportError:
    Image = None


ROOT = Path(__file__).resolve().parents[1]
LOCAL_TEX_BINS = tuple((ROOT / ".texlive" / "bin").glob("*"))
LOCAL_GS_BIN = ROOT / ".texlive" / "ghostscript" / "bin"


def _binary(name: str) -> str | None:
    candidates = [Path(os.environ["FDS_TEX_BIN"]) / name] if "FDS_TEX_BIN" in os.environ else []
    candidates += [directory / name for directory in LOCAL_TEX_BINS]
    if name == "gs":
        candidates.insert(0, LOCAL_GS_BIN / name)
    return next((str(path) for path in candidates if path.is_file()), shutil.which(name))


def _feature_diagrams() -> list[Diagram]:
    styles = Diagram(title="Styles, colors, markers, and bundles", style=FigureStyle(strokePt=1.2, fontPt=12))
    kinds = ("fermion", "photon", "gluon", "scalar", "ghost")
    colors = ("#D43F3F", "#2F7FBF", "#168A55", "#A03CCF", "#D98900")
    labels = (r"e^{-}", r"\gamma", "g", r"\phi", r"\bar{c}")
    markers = ("dot", "open", "filled", "hatched", "crosshatched", "dotted")
    for index, (kind, color, label) in enumerate(zip(kinds, colors, labels)):
        y = 70 + index * 84
        left = Vertex("v{}a".format(index), 90, y, marker=markers[index], visible=True)
        right = Vertex("v{}b".format(index), 630, y, marker=markers[(index + 1) % len(markers)], visible=True)
        styles.vertices.extend((left, right))
        styles.edges.append(Edge("e{}".format(index), left.id, right.id, kind=kind, label=label,
                                 arrow=("forward", "reverse", "none")[index % 3], color=color,
                                 bundle=3 if index == 0 else 1, labelOffset=-28 + index * 12,
                                 labelX=12 if index % 2 else -12, labelY=8 if index % 2 else -8))
    styles.vertices.append(Vertex("extra", 360, 450, marker="dotted", visible=True, markerSize=30))

    geometry = Diagram(title="Curves, arcs, bundles, and loops")
    for name, x, y in (("a", 100, 120), ("b", 620, 120), ("c", 100, 350),
                       ("d", 620, 350), ("e", 280, 230), ("f", 440, 230)):
        geometry.vertices.append(Vertex(name, x, y))
    geometry.edges.extend((
        Edge("up", "a", "b", kind="photon", curvature=-180, color="#2F7FBF", label=r"\gamma"),
        Edge("down", "c", "d", kind="gluon", curvature=180, color="#168A55", label="g"),
        Edge("arc1", "e", "f", circular=True, curvature=1, arrow="reverse", label="c_1"),
        Edge("arc2", "e", "f", circular=True, curvature=-1, arrow="forward", label="c_2"),
        Edge("bundle", "a", "e", bundle=2, bundleSpacing=22, arrow="forward"),
        Edge("loop1", "e", "e", kind="scalar", loopSize=80, loopAngle=-90, label="s"),
        Edge("loop2", "f", "f", kind="ghost", loopSize=80, loopAngle=90, label="c"),
    ))

    labels = Diagram(title="Math labels and independent offsets")
    labels.vertices.extend((
        Vertex("left", 100, 220, label=r"\bar{\nu}_{e}", labelX=-25, labelY=-45),
        Vertex("right", 620, 220, label=r"q_{1}^{+}", labelX=30, labelY=35),
    ))
    labels.edges.append(Edge("math", "left", "right", kind="scalar", label=r"\frac{g^2}{4\pi}",
                             curvature=100, labelOffset=-45, labelX=30, labelY=20,
                             color="#D43F3F", arrow="reverse"))
    return [styles, geometry, labels]


def _has_color(image, expected: tuple[int, int, int]) -> bool:
    pixels = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    return any(all(abs(actual - target) < 48 for actual, target in zip(pixel[:3], expected))
               for pixel in pixels)


def _text_diagram() -> Diagram:
    return Diagram(title="Rendered math labels", vertices=[
        Vertex("label_left", 100, 200, label=r"e^{-}", labelY=-40),
        Vertex("label_middle", 360, 200, label=r"\bar{\nu}_{e}", labelX=30, labelY=0),
        Vertex("label_right", 620, 200, label=r"\frac{g^2}{4\pi}", labelX=-20, labelY=40),
        Vertex("top_left", 100, 100),
        Vertex("top_right", 620, 100),
        Vertex("line_left", 100, 400),
        Vertex("line_right", 620, 400),
    ], edges=[Edge("top", "top_left", "top_right", arrow="none",
                  label=r"\alpha_{\mathrm{s}}", labelOffset=-65, labelX=35),
              Edge("baseline", "line_left", "line_right", arrow="none")])


class FeatureOutputTests(unittest.TestCase):
    def test_formatted_labels_and_offsets_in_every_latex_source(self):
        document = Diagram(vertices=[
            Vertex("left", 100, 220, label=r"\bar{\nu}_{e}", labelX=-25, labelY=-45),
            Vertex("right", 620, 220),
        ], edges=[Edge("math", "left", "right", label=r"\frac{g^2}{4\pi}",
                      labelOffset=-25, labelX=30, labelY=20, arrow="reverse")])
        sources = {option.value: latex_source(document, option.value) for option in FORMATS}
        for source in sources.values():
            self.assertIn(r"\frac{g^2}{4\pi}", source)
            self.assertIn(r"\bar{\nu}_{e}", source)
        for name in ("tikz-feynman", "tikz-feynhand"):
            self.assertIn("at (390,215)", sources[name])
            self.assertIn("at (75,175)", sources[name])
        for name in ("feynmp", "feynmf"):
            self.assertIn("(0.541667w,0.552083h)", sources[name])
            self.assertIn("(0.104167w,0.635417h)", sources[name])
        self.assertIn(r"\rput(390,265)", sources["pst-feyn"])
        self.assertIn(r"\rput(75,305)", sources["pst-feyn"])
        self.assertIn(r"\Text(184.9,125.7)", sources["axodraw2"])
        self.assertIn(r"\Text(35.6,144.6)", sources["axodraw2"])
        self.assertNotIn("reverse=true", sources["feynmp"])

    def test_exported_style_settings_reach_every_dialect(self):
        document = _feature_diagrams()[0]
        for option in FORMATS:
            source = latex_source(document, option.value)
            self.assertIn(r"\fontsize{12pt}{14.4pt}\selectfont", source)
            if option.value in ("feynmp", "feynmf"):
                self.assertIn(r"\fmfpen{1.2pt}", source)
                self.assertIn("decor.size=20.9pt", source)
                self.assertIn("decor.filled=shaded", source)
                self.assertIn("decor.filled=hatched", source)
                self.assertIn("decor.filled=gray10", source)
            elif option.value == "axodraw2":
                self.assertIn(r"\SetWidth{1.2}", source)
            else:
                self.assertIn("1.2pt", source)

    @unittest.skipUnless(Image is not None, "Pillow is required for raster export checks")
    def test_native_exports_render_feature_diagrams(self):
        with tempfile.TemporaryDirectory(prefix="fds-native-") as temporary:
            for index, document in enumerate(_feature_diagrams()):
                with self.subTest(diagram=document.title):
                    svg = ET.fromstring(svg_document(document))
                    self.assertGreater(len(svg.findall("{http://www.w3.org/2000/svg}polyline")), 0)
                    self.assertGreater(len(svg.findall("{http://www.w3.org/2000/svg}text")), 0)
                    pdf = Path(temporary) / "{}.pdf".format(index)
                    png = Path(temporary) / "{}.png".format(index)
                    jpeg = Path(temporary) / "{}.jpg".format(index)
                    save_pdf(document, pdf, 300)
                    save_raster(document, png, 300, True)
                    save_raster(document, jpeg, 300)
                    self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
                    for path in (png, jpeg):
                        with Image.open(path) as image:
                            self.assertEqual(image.size, (1417, 945))
                            self.assertLess(min(channel[0] for channel in image.convert("RGB").getextrema()), 200)
                            if index == 0:
                                self.assertTrue(_has_color(image.convert("RGB"), (212, 63, 63)), path)


class LatexRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        needed = ("pdflatex", "latex", "mpost", "mf", "gftopk", "dvipdfmx", "dvips", "axohelp", "gs", "pdftoppm")
        cls.binaries = {name: _binary(name) for name in needed}
        missing = [name for name, path in cls.binaries.items() if path is None]
        if missing:
            message = "LaTeX render tests need: " + ", ".join(missing)
            if os.environ.get("FDS_REQUIRE_LATEX") == "1":
                raise AssertionError(message)
            raise unittest.SkipTest(message + " (set FDS_REQUIRE_LATEX=1 to require them)")
        cls.environment = os.environ.copy()
        paths = [str(Path(path).parent) for path in cls.binaries.values() if path]
        cls.environment["PATH"] = os.pathsep.join(dict.fromkeys(paths)) + os.pathsep + cls.environment["PATH"]

    def _run(self, directory: Path, command: list[str], *, first_feynmf_pass: bool = False) -> None:
        result = subprocess.run(command, cwd=directory, env=self.environment,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=60)
        if first_feynmf_pass and (directory / "feynman-diagram.mf").is_file():
            return  # METAFONT's missing first-pass TFM can make LaTeX exit nonzero.
        self.assertEqual(result.returncode, 0, "{} failed:\n{}".format(" ".join(command), result.stdout[-3500:]))

    def _render(self, document: Diagram, format_name: str, directory: Path) -> Path:
        directory.mkdir()
        (directory / "diagram.tex").write_text(standalone_source(document, format_name), encoding="utf-8")
        tex_flags = ["-halt-on-error", "-interaction=nonstopmode", "diagram.tex"]
        if format_name in ("tikz-feynman", "tikz-feynhand"):
            self._run(directory, [self.binaries["pdflatex"], *tex_flags])
        elif format_name == "feynmp":
            self._run(directory, [self.binaries["pdflatex"], *tex_flags])
            self._run(directory, [self.binaries["mpost"], "-interaction=nonstopmode", "feynman-diagram.mp"])
            self._run(directory, [self.binaries["pdflatex"], *tex_flags])
        elif format_name == "feynmf":
            self._run(directory, [self.binaries["latex"], "-interaction=nonstopmode", "diagram.tex"], first_feynmf_pass=True)
            self._run(directory, [self.binaries["mf"], "-interaction=nonstopmode", r"\mode:=ljfour; input feynman-diagram"])
            glyphs = list(directory.glob("feynman-diagram.*gf"))
            self.assertEqual(len(glyphs), 1)
            self._run(directory, [self.binaries["gftopk"], glyphs[0].name])
            self._run(directory, [self.binaries["latex"], *tex_flags])
            self._run(directory, [self.binaries["dvipdfmx"], "-o", "diagram.pdf", "diagram.dvi"])
        elif format_name == "pst-feyn":
            self._run(directory, [self.binaries["latex"], *tex_flags])
            self._run(directory, [self.binaries["dvips"], "-o", "diagram.ps", "diagram.dvi"])
            self._run(directory, [self.binaries["gs"], "-q", "-dBATCH", "-dNOPAUSE",
                                  "-dALLOWPSTRANSPARENCY", "-sDEVICE=pdfwrite",
                                  "-sOutputFile=diagram.pdf", "diagram.ps"])
        else:
            self._run(directory, [self.binaries["pdflatex"], *tex_flags])
            self._run(directory, [self.binaries["axohelp"], "diagram"])
            self._run(directory, [self.binaries["pdflatex"], *tex_flags])
        pdf = directory / "diagram.pdf"
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
        return pdf

    def _assert_visible_and_inside_page(self, pdf: Path) -> None:
        result = subprocess.run([self.binaries["gs"], "-q", "-dBATCH", "-dNOPAUSE",
                                 "-sDEVICE=bbox", str(pdf)], env=self.environment,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout[-1500:])
        match = re.search(r"%%HiResBoundingBox: ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)", result.stdout)
        self.assertIsNotNone(match, result.stdout[-1500:])
        left, bottom, right, top = (float(value) for value in match.groups())
        self.assertGreater(right - left, 25)
        self.assertGreater(top - bottom, 15)
        self.assertGreater(left, 10)
        self.assertGreater(bottom, 10)
        self.assertLess(right, 600)  # Letter paper is 612 pt wide; catches clipped axodraw2 output.
        self.assertLess(top, 780)
        decoded = subprocess.run([self.binaries["pdftoppm"], "-f", "1", "-l", "1", "-r", "30", "-png", str(pdf)],
                                 env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(decoded.returncode, 0, decoded.stderr.decode(errors="replace")[-1500:])
        self.assertNotIn(b"Syntax Error", decoded.stderr)
        self.assertTrue(decoded.stdout.startswith(b"\x89PNG\r\n\x1a\n"))

    @unittest.skipUnless(Image is not None, "Pillow is required for color checks")
    def _assert_colors(self, pdf: Path) -> None:
        output = pdf.with_suffix(".png")
        self._run(pdf.parent, [self.binaries["gs"], "-q", "-dBATCH", "-dNOPAUSE",
                               "-sDEVICE=png16m", "-r110", "-sOutputFile=" + str(output), str(pdf)])
        with Image.open(output) as image:
            pixels = image.convert("RGB")
            for expected in ((212, 63, 63), (47, 127, 191), (22, 138, 85), (160, 60, 207), (217, 137, 0)):
                self.assertTrue(_has_color(pixels, expected), "Missing rendered color {} in {}".format(expected, pdf))

    def _check_format(self, format_name: str) -> None:
        documents = templates() + _feature_diagrams()
        with tempfile.TemporaryDirectory(prefix="fds-latex-") as temporary:
            for index, document in enumerate(documents):
                with self.subTest(format=format_name, diagram=document.title):
                    pdf = self._render(document, format_name, Path(temporary) / str(index))
                    self._assert_visible_and_inside_page(pdf)
                    if index == len(templates()) and format_name != "feynmf":
                        self._assert_colors(pdf)

    def _raster(self, pdf: Path):
        result = subprocess.run([self.binaries["pdftoppm"], "-f", "1", "-l", "1", "-r", "144", "-png", str(pdf)],
                                env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace")[-1500:])
        self.assertNotIn(b"Syntax Error", result.stderr)
        return Image.open(BytesIO(result.stdout)).convert("RGB")

    def _text_crops(self, image):
        gray = image.convert("L")
        pixels = gray.load()
        width, height = gray.size
        rows = [y for y in range(height)
                if sum(pixels[x, y] < 150 for x in range(width // 4, 3 * width // 4)) > 200]
        groups = []
        for y in rows:
            if not groups or y > groups[-1][-1] + 1:
                groups.append([y])
            else:
                groups[-1].append(y)
        self.assertEqual(len(groups), 2, "Expected two reference lines, found {}".format(groups))
        top_y, bottom_y = (round(sum(group) / len(group)) for group in groups)
        xs = [x for x in range(width) if pixels[x, bottom_y] < 150]
        self.assertGreater(len(xs), 200)
        left, right = min(xs), max(xs)
        crops = []
        for x, y in ((100, 160), (390, 200), (600, 240), (395, 35)):
            expected_x = left + (x - 100) * (right - left) / 520
            expected_y = top_y + (y - 100) * (bottom_y - top_y) / 300
            box = (round(expected_x - 45), round(expected_y - 30),
                   round(expected_x + 45), round(expected_y + 30))
            crops.append(gray.crop(box).point(lambda value: 255 if value < 150 else 0).getbbox())
        return crops

    @unittest.skipUnless(Image is not None, "Pillow is required for text pixel checks")
    def test_math_text_is_visible_at_requested_positions_in_all_formats(self):
        document = _text_diagram()
        bare = document.clone()
        for vertex in bare.vertices:
            vertex.label = ""
        for edge in bare.edges:
            edge.label = ""
        label_points = ((100, 160), (390, 200), (600, 240), (395, 35))
        with tempfile.TemporaryDirectory(prefix="fds-latex-text-") as temporary:
            for option in FORMATS:
                with self.subTest(format=option.value):
                    root = Path(temporary) / option.value
                    root.mkdir()
                    labelled_pdf = self._render(document, option.value, root / "labelled")
                    bare_pdf = self._render(bare, option.value, root / "bare")
                    labelled = self._raster(labelled_pdf)
                    baseline = self._raster(bare_pdf)
                    self.assertEqual(labelled.size, baseline.size)
                    labelled_crops = self._text_crops(labelled)
                    bare_crops = self._text_crops(baseline)
                    for point, labelled_ink, bare_ink in zip(label_points, labelled_crops, bare_crops):
                        self.assertIsNone(bare_ink, "Reference crop is not blank at {}".format(point))
                        self.assertIsNotNone(labelled_ink, "Missing text at {}".format(point))

    def test_tikz_feynman(self):
        self._check_format("tikz-feynman")

    def test_tikz_feynhand(self):
        self._check_format("tikz-feynhand")

    def test_feynmp(self):
        self._check_format("feynmp")

    def test_feynmf(self):
        self._check_format("feynmf")

    def test_pst_feyn(self):
        self._check_format("pst-feyn")

    def test_axodraw2(self):
        self._check_format("axodraw2")


if __name__ == "__main__":
    unittest.main()
