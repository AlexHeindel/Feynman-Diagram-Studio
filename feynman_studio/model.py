from __future__ import annotations

import copy
import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List

WIDTH = 720.0
HEIGHT = 480.0
GRID_SIZE = 20.0
KINDS = ("fermion", "photon", "gluon", "scalar", "ghost")
MARKERS = ("none", "dot", "open", "filled", "hatched", "crosshatched", "dotted")
ARROWS = ("forward", "reverse", "none")


class DiagramError(ValueError):
    pass


@dataclass
class Vertex:
    id: str
    x: float
    y: float
    label: str = ""
    labelX: float = 0.0
    labelY: float = 32.0
    visible: bool = False
    marker: str = "none"
    markerSize: float = 22.0


@dataclass
class Edge:
    id: str
    from_: str
    to: str
    kind: str = "fermion"
    label: str = ""
    curvature: float = 0.0
    labelOffset: float = -25.0
    arrow: str = "forward"
    color: str = "#172333"
    bundle: int = 1
    bundleSpacing: float = 14.0
    loopSize: float = 90.0
    loopAngle: float = -90.0
    circular: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["from"] = data.pop("from_")
        return data


@dataclass
class FigureStyle:
    widthMm: float = 120.0
    strokePt: float = 0.8
    fontPt: float = 10.0


@dataclass
class Diagram:
    version: int = 1
    title: str = "Untitled diagram"
    vertices: List[Vertex] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    style: FigureStyle = field(default_factory=FigureStyle)

    def clone(self) -> "Diagram":
        return copy.deepcopy(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "title": self.title,
            "vertices": [asdict(vertex) for vertex in self.vertices],
            "edges": [edge.to_dict() for edge in self.edges],
            "style": asdict(self.style),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Diagram":
        if not isinstance(data, dict) or data.get("version") != 1:
            raise DiagramError("This is not a valid Feynman Diagram Studio version 1 project.")
        title = data.get("title")
        if not isinstance(title, str) or not 1 <= len(title) <= 100:
            raise DiagramError("The diagram title must contain 1–100 characters.")
        raw_vertices = data.get("vertices")
        raw_edges = data.get("edges")
        raw_style = data.get("style")
        if not isinstance(raw_vertices, list) or len(raw_vertices) > 150:
            raise DiagramError("A project may contain at most 150 vertices.")
        if not isinstance(raw_edges, list) or len(raw_edges) > 300:
            raise DiagramError("A project may contain at most 300 propagators.")
        if not isinstance(raw_style, dict):
            raise DiagramError("The figure style is missing.")

        vertices: List[Vertex] = []
        for raw in raw_vertices:
            if not isinstance(raw, dict):
                raise DiagramError("Every vertex must be an object.")
            vertex = Vertex(
                id=_text(raw, "id", 1, 80),
                x=_number(raw, "x", 20, 700),
                y=_number(raw, "y", 20, 460),
                label=_text(raw, "label", 0, 200),
                labelX=_number(raw, "labelX", -150, 150),
                labelY=_number(raw, "labelY", -150, 150),
                visible=_boolean(raw, "visible"),
                marker=raw.get("marker", "dot" if raw.get("visible") else "none"),
                markerSize=_number(raw, "markerSize", 6, 60, 22),
            )
            if vertex.marker not in MARKERS:
                raise DiagramError("A vertex uses an unsupported marker.")
            vertices.append(vertex)

        edges: List[Edge] = []
        for raw in raw_edges:
            if not isinstance(raw, dict):
                raise DiagramError("Every propagator must be an object.")
            edge = Edge(
                id=_text(raw, "id", 1, 80),
                from_=_text(raw, "from", 0, 80),
                to=_text(raw, "to", 0, 80),
                kind=raw.get("kind", ""),
                label=_text(raw, "label", 0, 200),
                curvature=_number(raw, "curvature", -220, 220),
                labelOffset=_number(raw, "labelOffset", -120, 120),
                arrow=raw.get("arrow", "none"),
                color=raw.get("color", ""),
                bundle=int(_number(raw, "bundle", 1, 3, 1)),
                bundleSpacing=_number(raw, "bundleSpacing", 4, 40, 14),
                loopSize=_number(raw, "loopSize", 30, 180, 90),
                loopAngle=_number(raw, "loopAngle", -180, 180, -90),
                circular=raw.get("circular", False),
            )
            if edge.kind not in KINDS or edge.arrow not in ARROWS:
                raise DiagramError("A propagator uses an unsupported style.")
            if not _valid_color(edge.color) or edge.bundle not in (1, 2, 3):
                raise DiagramError("A propagator has invalid appearance settings.")
            if not isinstance(edge.circular, bool):
                raise DiagramError("A propagator has invalid loop settings.")
            edges.append(edge)

        style = FigureStyle(
            widthMm=_number(raw_style, "widthMm", 60, 240),
            strokePt=_number(raw_style, "strokePt", 0.3, 2),
            fontPt=_number(raw_style, "fontPt", 5, 18),
        )
        ids = [item.id for item in vertices] + [item.id for item in edges]
        if len(ids) != len(set(ids)):
            raise DiagramError("Object IDs must be unique.")
        vertex_ids = {item.id for item in vertices}
        if any(item.from_ not in vertex_ids or item.to not in vertex_ids for item in edges):
            raise DiagramError("Every propagator must connect existing vertices.")

        document = cls(1, title, vertices, edges, style)
        _migrate_circular_loops(document)
        return document

    @classmethod
    def from_json(cls, source: str) -> "Diagram":
        try:
            value = json.loads(source)
        except (TypeError, json.JSONDecodeError) as exc:
            raise DiagramError("The project is not valid JSON.") from exc
        return cls.from_dict(value)

    def vertex(self, object_id: str) -> Vertex | None:
        return next((item for item in self.vertices if item.id == object_id), None)

    def edge(self, object_id: str) -> Edge | None:
        return next((item for item in self.edges if item.id == object_id), None)

    def remove(self, object_id: str) -> None:
        self.vertices = [item for item in self.vertices if item.id != object_id]
        self.edges = [
            item
            for item in self.edges
            if item.id != object_id and item.from_ != object_id and item.to != object_id
        ]


def _text(data: Dict[str, Any], key: str, minimum: int, maximum: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise DiagramError("Invalid {}.".format(key))
    return value


def _number(
    data: Dict[str, Any], key: str, minimum: float, maximum: float, default: Any = None
) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiagramError("Invalid {}.".format(key))
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise DiagramError("Invalid {}.".format(key))
    return value


def _boolean(data: Dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise DiagramError("Invalid {}.".format(key))
    return value


def _valid_color(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        return False
    return all(character in "0123456789abcdefABCDEF" for character in value[1:])


def make_vertex(x: float, y: float, label: str = "", visible: bool = False) -> Vertex:
    return Vertex(
        id=str(uuid.uuid4()),
        x=x,
        y=y,
        label=label,
        labelY=-30 if y < HEIGHT / 2 else 32,
        visible=visible,
        marker="dot" if visible else "none",
    )


def make_edge(
    from_id: str,
    to_id: str,
    kind: str = "fermion",
    label: str = "",
    curvature: float = 0,
) -> Edge:
    return Edge(
        id=str(uuid.uuid4()),
        from_=from_id,
        to=to_id,
        kind=kind,
        label=label,
        curvature=curvature,
        arrow="forward" if kind == "fermion" else "none",
    )


def bundle_offsets(edge: Edge) -> Iterable[float]:
    count = edge.bundle if edge.kind == "fermion" else 1
    return tuple((index - (count - 1) / 2) * edge.bundleSpacing for index in range(count))


def snap_value(value: float) -> float:
    return math.floor(value / GRID_SIZE + 0.5) * GRID_SIZE


def blank_diagram() -> Diagram:
    return Diagram()


def _vertex(name: str, x: float, y: float, label: str = "", visible: bool = False) -> Vertex:
    item = make_vertex(x, y, label, visible)
    item.id = name
    return item


def _edge(
    name: str,
    start: str,
    end: str,
    kind: str = "fermion",
    label: str = "",
    curvature: float = 0,
    *,
    arrow: str | None = None,
    color: str = "#172333",
    circular: bool = False,
) -> Edge:
    item = make_edge(start, end, kind, label, curvature)
    item.id = name
    if arrow is not None:
        item.arrow = arrow
    item.color = color
    item.circular = circular
    return item


def templates() -> List[Diagram]:
    return [
        Diagram(
            title="Electron–positron annihilation",
            vertices=[
                _vertex("v1", 100, 100, "e^{-}"),
                _vertex("v2", 100, 380, "e^{+}"),
                _vertex("v3", 280, 240, visible=True),
                _vertex("v4", 440, 240, visible=True),
                _vertex("v5", 620, 100, r"\mu^{-}"),
                _vertex("v6", 620, 380, r"\mu^{+}"),
            ],
            edges=[
                _edge("e1", "v1", "v3"),
                _edge("e2", "v3", "v2"),
                _edge("e3", "v3", "v4", "photon", r"\gamma"),
                _edge("e4", "v4", "v5"),
                _edge("e5", "v6", "v4"),
            ],
        ),
        Diagram(
            title="Electron scattering",
            vertices=[
                _vertex("v1", 100, 100, "e^{-}"),
                _vertex("v2", 100, 380, "e^{-}"),
                _vertex("v3", 360, 100, visible=True),
                _vertex("v4", 360, 380, visible=True),
                _vertex("v5", 620, 100, "e^{-}"),
                _vertex("v6", 620, 380, "e^{-}"),
            ],
            edges=[
                _edge("e1", "v1", "v3"),
                _edge("e2", "v3", "v5"),
                _edge("e3", "v2", "v4"),
                _edge("e4", "v4", "v6"),
                _edge("e5", "v3", "v4", "photon", r"\gamma"),
            ],
        ),
        Diagram(
            title="One-loop self-energy",
            vertices=[
                _vertex("v1", 100, 300, "e^{-}"),
                _vertex("v2", 260, 300, visible=True),
                _vertex("v3", 460, 300, visible=True),
                _vertex("v4", 620, 300, "e^{-}"),
            ],
            edges=[
                _edge("e1", "v1", "v2"),
                _edge("e2", "v2", "v3"),
                _edge("e3", "v3", "v4"),
                _edge("e4", "v2", "v3", "photon", r"\gamma", -210),
            ],
        ),
        Diagram(
            title="Quark scattering",
            vertices=[
                _vertex("v1", 100, 100, "q"),
                _vertex("v2", 100, 380, "q"),
                _vertex("v3", 360, 100, visible=True),
                _vertex("v4", 360, 380, visible=True),
                _vertex("v5", 620, 100, "q"),
                _vertex("v6", 620, 380, "q"),
            ],
            edges=[
                _edge("e1", "v1", "v3"),
                _edge("e2", "v3", "v5"),
                _edge("e3", "v2", "v4"),
                _edge("e4", "v4", "v6"),
                _edge("e5", "v3", "v4", "gluon", "g"),
            ],
        ),
        Diagram(
            title="Top-pair Higgs production",
            vertices=[
                _vertex("v1", 80, 120, "g"),
                _vertex("v2", 80, 360, "g"),
                _vertex("v3", 240, 140, visible=True),
                _vertex("v4", 240, 340, visible=True),
                _vertex("v5", 440, 240, visible=True),
                _vertex("v6", 640, 80, "t"),
                _vertex("v7", 640, 400, r"\bar{t}"),
                _vertex("v8", 640, 240, "H"),
            ],
            edges=[
                _edge("e1", "v1", "v3", "gluon", color="#059669"),
                _edge("e2", "v2", "v4", "gluon", color="#059669"),
                _edge("e3", "v3", "v6"),
                _edge("e4", "v5", "v3"),
                _edge("e5", "v4", "v5"),
                _edge("e6", "v7", "v4"),
                _edge("e7", "v5", "v8", "scalar"),
            ],
        ),
        Diagram(
            title="Penguin diagram",
            vertices=[
                _vertex("v1", 60, 120, "b"),
                _vertex("v2", 220, 120, visible=True),
                _vertex("v3", 500, 120, visible=True),
                _vertex("v4", 660, 120, "s"),
                _vertex("v5", 360, 300, visible=True),
                _vertex("v6", 360, 380, visible=True),
                _vertex("v7", 120, 420, "q"),
                _vertex("v8", 600, 420, r"\bar{q}"),
            ],
            edges=[
                _edge("e1", "v1", "v2"),
                _edge("e2", "v2", "v3", "photon", "W"),
                _edge("e3", "v3", "v4"),
                _edge("e4", "v2", "v5", label="t", curvature=60),
                _edge("e5", "v5", "v3", label="t", curvature=60),
                _edge("e6", "v5", "v6", "gluon", "g"),
                _edge("e7", "v7", "v6"),
                _edge("e8", "v6", "v8"),
            ],
        ),
        Diagram(
            title="Kaon decay to three pions",
            vertices=[
                _vertex("v1", 60, 100, "u"),
                _vertex("v2", 220, 100, visible=True),
                _vertex("v3", 60, 340, r"\bar{s}"),
                _vertex("v4", 220, 340, visible=True),
                _vertex("v5", 400, 220, visible=True),
                _vertex("v6", 500, 340, visible=True),
                _vertex("v7", 660, 60, "u"),
                _vertex("v8", 660, 140, r"\bar{d}"),
                _vertex("v9", 660, 220, "u"),
                _vertex("v10", 660, 300, r"\bar{d}"),
                _vertex("v11", 660, 380, "d"),
                _vertex("v12", 660, 440, r"\bar{u}"),
            ],
            edges=[
                _edge("e1", "v1", "v2"),
                _edge("e2", "v2", "v7"),
                _edge("e3", "v3", "v4", arrow="reverse"),
                _edge("e4", "v12", "v4"),
                _edge("e5", "v4", "v5", "photon", r"W^{+}"),
                _edge("e6", "v8", "v5"),
                _edge("e7", "v5", "v9"),
                _edge("e8", "v5", "v6", "gluon", "g"),
                _edge("e9", "v10", "v6"),
                _edge("e10", "v6", "v11"),
            ],
        ),
        Diagram(
            title="Compton scattering",
            vertices=[
                _vertex("v1", 80, 240, "e^{-}"),
                _vertex("v2", 280, 240, visible=True),
                _vertex("v3", 440, 240, visible=True),
                _vertex("v4", 640, 240, "e^{-}"),
                _vertex("v5", 80, 400, r"\gamma"),
                _vertex("v6", 640, 80, r"\gamma"),
            ],
            edges=[
                _edge("e1", "v1", "v2"),
                _edge("e2", "v2", "v3"),
                _edge("e3", "v3", "v4"),
                _edge("e4", "v5", "v2", "photon"),
                _edge("e5", "v3", "v6", "photon"),
            ],
        ),
        Diagram(
            title="Muon decay",
            vertices=[
                _vertex("v1", 80, 160, r"\mu^{-}"),
                _vertex("v2", 280, 160, visible=True),
                _vertex("v3", 440, 320, visible=True),
                _vertex("v4", 640, 160, r"\nu_{\mu}"),
                _vertex("v5", 640, 280, "e^{-}"),
                _vertex("v6", 640, 420, r"\bar{\nu}_{e}"),
            ],
            edges=[
                _edge("e1", "v1", "v2"),
                _edge("e2", "v2", "v4"),
                _edge("e3", "v2", "v3", "photon", r"W^{-}"),
                _edge("e4", "v3", "v5"),
                _edge("e5", "v6", "v3"),
            ],
        ),
        Diagram(
            title="Vacuum polarization",
            vertices=[
                _vertex("v1", 80, 240, r"\gamma"),
                _vertex("v2", 240, 240, visible=True),
                _vertex("v3", 480, 240, visible=True),
                _vertex("v4", 640, 240, r"\gamma"),
            ],
            edges=[
                _edge("e1", "v1", "v2", "photon"),
                _edge("e2", "v3", "v4", "photon"),
                _edge("e3", "v2", "v3", label="e^{-}", curvature=100, circular=True),
                _edge("e4", "v2", "v3", label="e^{+}", curvature=-100, arrow="reverse", circular=True),
            ],
        ),
    ]


def _migrate_circular_loops(document: Diagram) -> None:
    for index, first in enumerate(document.edges):
        if first.from_ == first.to or first.circular or not first.curvature:
            continue
        for second in document.edges[index + 1 :]:
            if (
                not second.circular
                and second.from_ == first.from_
                and second.to == first.to
                and second.kind == first.kind
                and abs(second.curvature + first.curvature) < 0.001
            ):
                first.circular = second.circular = True
                break
