from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple, Union

from .geometry import geometry
from .model import GRID_SIZE, HEIGHT, WIDTH, Diagram, Edge, Vertex, bundle_offsets

Point = Tuple[float, float]


@dataclass
class Polyline:
    points: List[Point]
    color: str
    width: float
    dash: Tuple[float, ...] = ()


@dataclass
class Polygon:
    points: List[Point]
    color: str


@dataclass
class Circle:
    center: Point
    radius: float
    fill: str | None
    outline: str | None
    width: float = 1.0


@dataclass
class Text:
    point: Point
    value: str
    color: str
    size: float
    source: str = ""


@dataclass(frozen=True)
class LabelRun:
    text: str
    script: int = 0  # -1 superscript, +1 subscript
    overbar: bool = False


Primitive = Union[Polyline, Polygon, Circle, Text]

_TEX_WORDS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    "bar": "",
}
_SUPERSCRIPT = str.maketrans("0123456789+-=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾")
_SUBSCRIPT = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def _script_approximation(value: str, table, marker: str) -> str:
    translated = value.translate(table)
    return translated if translated != value else marker + value


def display_label(source: str) -> str:
    """Turn common TeX labels into a readable native-canvas approximation."""
    value = re.sub(r"\\(?:bar|overline)\{([^{}]+)\}", lambda m: m.group(1) + "\u0304", source)
    value = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", lambda m: "({})⁄({})".format(m.group(1), m.group(2)), value)
    value = re.sub(r"\\(?:mathrm|mathbf|mathit|text)\{([^{}]+)\}", r"\1", value)
    value = re.sub(r"\\([A-Za-z]+)", lambda m: _TEX_WORDS.get(m.group(1), m.group(0)), value)
    value = re.sub(r"\^\{([^{}]+)\}", lambda m: _script_approximation(m.group(1), _SUPERSCRIPT, "^"), value)
    value = re.sub(r"_\{([^{}]+)\}", lambda m: _script_approximation(m.group(1), _SUBSCRIPT, "_"), value)
    value = re.sub(r"\^([A-Za-z0-9+\-=])", lambda m: _script_approximation(m.group(1), _SUPERSCRIPT, "^"), value)
    value = re.sub(r"_([A-Za-z0-9+\-=])", lambda m: _script_approximation(m.group(1), _SUBSCRIPT, "_"), value)
    return value.replace("{", "").replace("}", "")


def _plain_tex_atom(value: str) -> str:
    return re.sub(r"\\([A-Za-z]+)", lambda m: _TEX_WORDS.get(m.group(1), m.group(0)), value).replace("{", "").replace("}", "")


def _label_runs(source: str, fallback: str) -> List[LabelRun]:
    if not source or re.search(r"\\(?:frac|mathrm|mathbf|mathit|text)\b", source):
        return [LabelRun(fallback)]
    token = re.compile(
        r"\\(?:bar|overline)\{((?:\\[A-Za-z]+|[^{}])+)\}"
        r"|([_^])\{([^{}]+)\}"
        r"|([_^])([A-Za-z0-9+\-=])"
        r"|\\([A-Za-z]+)"
        r"|([^{}])"
    )
    runs: List[LabelRun] = []
    for match in token.finditer(source):
        overbar, grouped_script, grouped_value, single_script, single_value, command, literal = match.groups()
        if overbar is not None:
            runs.append(LabelRun(_plain_tex_atom(overbar), overbar=True))
        elif grouped_script is not None:
            runs.append(LabelRun(_plain_tex_atom(grouped_value), -1 if grouped_script == "^" else 1))
        elif single_script is not None:
            runs.append(LabelRun(single_value, -1 if single_script == "^" else 1))
        elif command is not None:
            runs.append(LabelRun(_TEX_WORDS.get(command, "\\" + command)))
        elif literal:
            runs.append(LabelRun(literal))
    return runs or [LabelRun(fallback)]


def _circle_segments(vertex: Vertex, radius: float, angle_degrees: float) -> List[Tuple[Point, Point]]:
    angle = math.radians(angle_degrees)
    direction = (math.cos(angle), math.sin(angle))
    normal = (-direction[1], direction[0])
    result = []
    offset = -radius + 4
    while offset <= radius - 4:
        half = math.sqrt(max(0, radius * radius - offset * offset))
        result.append(
            (
                (vertex.x + normal[0] * offset - direction[0] * half, vertex.y + normal[1] * offset - direction[1] * half),
                (vertex.x + normal[0] * offset + direction[0] * half, vertex.y + normal[1] * offset + direction[1] * half),
            )
        )
        offset += 7
    return result


def _marker(scene: List[Primitive], vertex: Vertex, stroke: float) -> None:
    marker = vertex.marker if vertex.marker else ("dot" if vertex.visible else "none")
    if marker == "none":
        return
    if marker == "dot":
        scene.append(Circle((vertex.x, vertex.y), stroke * 1.9, "#172333", None))
        return
    radius = vertex.markerSize
    fill = "#172333" if marker == "filled" else "#ffffff"
    scene.append(Circle((vertex.x, vertex.y), radius, fill, "#172333", stroke))
    if marker in ("hatched", "crosshatched"):
        for start, end in _circle_segments(vertex, radius, 45):
            scene.append(Polyline([start, end], "#172333", max(1, stroke * 0.65)))
        if marker == "crosshatched":
            for start, end in _circle_segments(vertex, radius, -45):
                scene.append(Polyline([start, end], "#172333", max(1, stroke * 0.65)))
    elif marker == "dotted":
        x = -radius + 4
        while x <= radius - 4:
            y = -radius + 4
            while y <= radius - 4:
                if x * x + y * y <= (radius - 3) ** 2:
                    scene.append(Circle((vertex.x + x, vertex.y + y), 1.35, "#172333", None))
                y += 7
            x += 7


def make_scene(document: Diagram) -> List[Primitive]:
    unit = WIDTH / ((document.style.widthMm * 72) / 25.4)
    stroke = document.style.strokePt * unit
    font = document.style.fontPt * unit
    vertices = {item.id: item for item in document.vertices}
    scene: List[Primitive] = []
    for edge in document.edges:
        start, end = vertices.get(edge.from_), vertices.get(edge.to)
        if start is None or end is None:
            continue
        dash = (9, 7) if edge.kind == "scalar" else (1, 7) if edge.kind == "ghost" else ()
        for offset in bundle_offsets(edge):
            points, middle = geometry(start, end, edge, offset)
            scene.append(Polyline(points, edge.color, stroke, dash))
            if edge.arrow != "none":
                sign = 1 if edge.arrow == "forward" else -1
                size = stroke * 4.2
                tip = (middle.x + middle.tx * size * sign, middle.y + middle.ty * size * sign)
                base_x = middle.x - middle.tx * size * 0.65 * sign
                base_y = middle.y - middle.ty * size * 0.65 * sign
                scene.append(
                    Polygon(
                        [
                            tip,
                            (base_x + middle.nx * size * 0.5, base_y + middle.ny * size * 0.5),
                            (base_x - middle.nx * size * 0.5, base_y - middle.ny * size * 0.5),
                        ],
                        edge.color,
                    )
                )
        _, middle = geometry(start, end, edge)
        if edge.label:
            scene.append(
                Text(
                    (middle.x + middle.nx * edge.labelOffset, middle.y + middle.ny * edge.labelOffset),
                    display_label(edge.label),
                    edge.color,
                    font,
                    edge.label,
                )
            )
    for vertex in document.vertices:
        _marker(scene, vertex, stroke)
        if vertex.label:
            scene.append(Text((vertex.x + vertex.labelX, vertex.y + vertex.labelY), display_label(vertex.label), "#172333", font, vertex.label))
    return scene


def svg_document(document: Diagram, transparent: bool = False) -> str:
    body: List[str] = []
    if not transparent:
        body.append('<rect width="720" height="480" fill="white"/>')
    for primitive in make_scene(document):
        if isinstance(primitive, Polyline):
            points = " ".join("{:.3f},{:.3f}".format(x, y) for x, y in primitive.points)
            dash = ' stroke-dasharray="{}"'.format(" ".join(str(value) for value in primitive.dash)) if primitive.dash else ""
            body.append('<polyline points="{}" fill="none" stroke="{}" stroke-width="{:.3f}" stroke-linecap="round" stroke-linejoin="round"{}/>'.format(points, primitive.color, primitive.width, dash))
        elif isinstance(primitive, Polygon):
            points = " ".join("{:.3f},{:.3f}".format(x, y) for x, y in primitive.points)
            body.append('<polygon points="{}" fill="{}"/>'.format(points, primitive.color))
        elif isinstance(primitive, Circle):
            fill = primitive.fill or "none"
            outline = '' if primitive.outline is None else ' stroke="{}" stroke-width="{:.3f}"'.format(primitive.outline, primitive.width)
            body.append('<circle cx="{:.3f}" cy="{:.3f}" r="{:.3f}" fill="{}"{}/>'.format(primitive.center[0], primitive.center[1], primitive.radius, fill, outline))
        else:
            body.append('<text x="{:.3f}" y="{:.3f}" text-anchor="middle" dominant-baseline="central" font-family="serif" font-size="{:.3f}" fill="{}">{}</text>'.format(primitive.point[0], primitive.point[1], primitive.size, primitive.color, html.escape(primitive.value)))
    return '<svg xmlns="http://www.w3.org/2000/svg" width="{}mm" height="{}mm" viewBox="0 0 720 480"><title>{}</title>{}</svg>'.format(
        document.style.widthMm,
        document.style.widthMm * 2 / 3,
        html.escape(document.title),
        "".join(body),
    )


def save_svg(document: Diagram, path: str | Path, transparent: bool = False) -> None:
    Path(path).write_text(svg_document(document, transparent), encoding="utf-8")


def _font(size: int):
    from PIL import ImageFont

    for candidate in _font_candidates():
        try:
            return ImageFont.truetype(candidate, max(8, size))
        except OSError:
            pass
    return ImageFont.load_default()


def _font_candidates() -> Tuple[str, ...]:
    return (
        "/System/Library/Fonts/Supplemental/STIXTwoText.ttf",
        "/System/Library/Fonts/Supplemental/STIXTwoMath.otf",
        "/System/Library/Fonts/Supplemental/STIXGeneral.otf",
        "C:/Windows/Fonts/cambria.ttc",
        "C:/Windows/Fonts/times.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "DejaVuSerif.ttf",
        "/System/Library/Fonts/Times.ttc",
    )


def _draw_dashed(draw, points: Sequence[Point], fill: str, width: int, dash: Sequence[float], scale: float) -> None:
    pattern = [value * scale for value in dash]
    pattern_index, remaining, painting = 0, pattern[0], True
    for start, end in zip(points, points[1:]):
        ax, ay = start[0] * scale, start[1] * scale
        bx, by = end[0] * scale, end[1] * scale
        dx, dy = bx - ax, by - ay
        distance = math.hypot(dx, dy)
        consumed = 0.0
        while consumed < distance:
            step = min(remaining, distance - consumed)
            if painting:
                t0, t1 = consumed / distance, (consumed + step) / distance
                draw.line((ax + dx * t0, ay + dy * t0, ax + dx * t1, ay + dy * t1), fill=fill, width=width)
            consumed += step
            remaining -= step
            if remaining <= 1e-6:
                pattern_index = (pattern_index + 1) % len(pattern)
                remaining = pattern[pattern_index]
                painting = not painting


def _draw_label(draw, primitive: Text, scale: float) -> None:
    main_size = max(8, round(primitive.size * scale))
    runs = _label_runs(primitive.source, primitive.value)
    prepared = []
    total_width = 0.0
    for run in runs:
        font = _font(round(main_size * 0.68) if run.script else main_size)
        width = draw.textlength(run.text, font=font)
        prepared.append((run, font, width))
        total_width += width
    x = primitive.point[0] * scale - total_width / 2
    baseline = primitive.point[1] * scale + main_size * 0.32
    for run, font, width in prepared:
        y = baseline - main_size * 0.38 if run.script < 0 else baseline + main_size * 0.22 if run.script > 0 else baseline
        draw.text((x, y), run.text, fill=primitive.color, font=font, anchor="ls")
        if run.overbar:
            bar_y = baseline - main_size * 0.78
            draw.line((x, bar_y, x + width, bar_y), fill=primitive.color, width=max(1, round(main_size * 0.055)))
        x += width


def _render_at_size(
    document: Diagram,
    width: int,
    height: int,
    transparent: bool = False,
    show_grid: bool = False,
):
    from PIL import Image, ImageDraw

    scale = width / WIDTH
    background = (255, 255, 255, 0 if transparent else 255)
    image = Image.new("RGBA", (width, height), background)
    draw = ImageDraw.Draw(image)
    if show_grid:
        grid_width = max(1, round(scale))
        for x in range(int(GRID_SIZE), int(WIDTH), int(GRID_SIZE)):
            draw.line(
                (x * scale, GRID_SIZE * scale, x * scale, (HEIGHT - GRID_SIZE) * scale),
                fill="#e8edf2",
                width=grid_width,
            )
        for y in range(int(GRID_SIZE), int(HEIGHT), int(GRID_SIZE)):
            draw.line(
                (GRID_SIZE * scale, y * scale, (WIDTH - GRID_SIZE) * scale, y * scale),
                fill="#e8edf2",
                width=grid_width,
            )
    for primitive in make_scene(document):
        if isinstance(primitive, Polyline):
            points = [(round(x * scale), round(y * scale)) for x, y in primitive.points]
            line_width = max(1, round(primitive.width * scale))
            if primitive.dash:
                _draw_dashed(draw, primitive.points, primitive.color, line_width, primitive.dash, scale)
            else:
                draw.line(points, fill=primitive.color, width=line_width, joint="curve")
        elif isinstance(primitive, Polygon):
            draw.polygon([(x * scale, y * scale) for x, y in primitive.points], fill=primitive.color)
        elif isinstance(primitive, Circle):
            x, y = primitive.center
            radius = primitive.radius
            box = ((x - radius) * scale, (y - radius) * scale, (x + radius) * scale, (y + radius) * scale)
            draw.ellipse(box, fill=primitive.fill, outline=primitive.outline, width=max(1, round(primitive.width * scale)))
        else:
            _draw_label(draw, primitive, scale)
    return image


def render_image(document: Diagram, ppi: int = 600, transparent: bool = False):
    width = round(document.style.widthMm / 25.4 * ppi)
    height = round(width * 2 / 3)
    if width * height > 40_000_000:
        raise ValueError("Choose a smaller page or resolution (40 megapixel limit).")
    return _render_at_size(document, width, height, transparent)


def render_preview(document: Diagram, width: int, height: int, show_grid: bool = False, oversample: int = 3):
    """Render an antialiased canvas preview at exactly ``width`` by ``height`` pixels."""
    from PIL import Image

    width, height = max(1, int(width)), max(1, int(height))
    oversample = max(1, int(oversample))
    image = _render_at_size(document, width * oversample, height * oversample, False, show_grid)
    if oversample == 1:
        return image
    return image.resize((width, height), Image.Resampling.LANCZOS)


def save_raster(document: Diagram, path: str | Path, ppi: int = 600, transparent: bool = False) -> None:
    path = Path(path)
    image = render_image(document, ppi, transparent and path.suffix.lower() == ".png")
    if path.suffix.lower() in (".jpg", ".jpeg"):
        flattened = image.convert("RGB")
        flattened.save(path, quality=96, dpi=(ppi, ppi))
    else:
        image.save(path, dpi=(ppi, ppi))


def save_pdf(document: Diagram, path: str | Path, ppi: int = 600) -> None:
    """Write a one-page vector PDF; ``ppi`` remains accepted for API compatibility."""
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas

    del ppi
    points_per_mm = 72 / 25.4
    page_width = document.style.widthMm * points_per_mm
    page_height = document.style.widthMm * 2 / 3 * points_per_mm
    scale = page_width / WIDTH
    pdf = Canvas(str(path), pagesize=(page_width, page_height), pageCompression=1)
    pdf.setTitle(document.title)
    pdf.setAuthor("Feynman Diagram Studio")
    pdf.setCreator("Feynman Diagram Studio")
    pdf.setLineCap(1)
    pdf.setLineJoin(1)
    font_name = "Times-Roman"
    for candidate in _font_candidates():
        if Path(candidate).is_file():
            try:
                pdfmetrics.registerFont(TTFont("FDSUnicode", candidate))
                font_name = "FDSUnicode"
                break
            except Exception:
                continue

    def point(value: Point) -> Point:
        return value[0] * scale, page_height - value[1] * scale

    for primitive in make_scene(document):
        if isinstance(primitive, Polyline):
            pdf.setStrokeColor(HexColor(primitive.color))
            pdf.setLineWidth(max(0.1, primitive.width * scale))
            pdf.setDash([value * scale for value in primitive.dash] if primitive.dash else [])
            shape = pdf.beginPath()
            first_x, first_y = point(primitive.points[0])
            shape.moveTo(first_x, first_y)
            for item in primitive.points[1:]:
                shape.lineTo(*point(item))
            pdf.drawPath(shape, stroke=1, fill=0)
        elif isinstance(primitive, Polygon):
            pdf.setFillColor(HexColor(primitive.color))
            shape = pdf.beginPath()
            shape.moveTo(*point(primitive.points[0]))
            for item in primitive.points[1:]:
                shape.lineTo(*point(item))
            shape.close()
            pdf.drawPath(shape, stroke=0, fill=1)
        elif isinstance(primitive, Circle):
            x, y = point(primitive.center)
            if primitive.fill:
                pdf.setFillColor(HexColor(primitive.fill))
            if primitive.outline:
                pdf.setStrokeColor(HexColor(primitive.outline))
                pdf.setLineWidth(max(0.1, primitive.width * scale))
            pdf.circle(x, y, primitive.radius * scale, stroke=int(primitive.outline is not None), fill=int(primitive.fill is not None))
        else:
            pdf.setFillColor(HexColor(primitive.color))
            pdf.setFont(font_name, max(1, primitive.size * scale))
            x, y = point(primitive.point)
            value = primitive.value if font_name == "FDSUnicode" else primitive.value.encode("ascii", "replace").decode("ascii")
            pdf.drawCentredString(x, y - primitive.size * scale * 0.32, value)
    pdf.showPage()
    pdf.save()
