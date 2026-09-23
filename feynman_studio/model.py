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
ANNOTATION_TYPES = ("label", "arrow")


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
class Momentum:
    label: str = ""
    labelX: float = 0.0
    labelY: float = 0.0
    direction: str = "forward"
    side: str = "right"
    color: str = "#172333"
    start: float = 0.2
    end: float = 0.8


@dataclass
class FreeLabel:
    id: str
    x: float
    y: float
    text: str = "label"
    color: str = "#172333"
    type: str = "label"


@dataclass
class FreeArrow:
    id: str
    x1: float
    y1: float
    x2: float
    y2: float
    color: str = "#172333"
    type: str = "arrow"


Annotation = FreeLabel | FreeArrow


@dataclass
class Edge:
    id: str
    from_: str
    to: str
    kind: str = "fermion"
    label: str = ""
    curvature: float = 0.0
    labelOffset: float = -25.0
    labelX: float = 0.0
    labelY: float = 0.0
    arrow: str = "forward"
    color: str = "#172333"
    bundle: int = 1
    bundleSpacing: float = 14.0
    loopSize: float = 90.0
    loopAngle: float = -90.0
    circular: bool = False
    momentum: Momentum | None = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["from"] = data.pop("from_")
        if data["momentum"] is None:
            data.pop("momentum")
        return data


@dataclass
class FigureStyle:
    widthMm: float = 120.0
    strokePt: float = 0.8
    fontPt: float = 10.0


@dataclass
class Diagram:
    version: int = 2
    title: str = "Untitled diagram"
    vertices: List[Vertex] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    style: FigureStyle = field(default_factory=FigureStyle)
    annotations: List[Annotation] = field(default_factory=list)

    def clone(self) -> "Diagram":
        return copy.deepcopy(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "title": self.title,
            "vertices": [asdict(vertex) for vertex in self.vertices],
            "edges": [edge.to_dict() for edge in self.edges],
            "annotations": [asdict(item) for item in self.annotations],
            "style": asdict(self.style),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Diagram":
        if not isinstance(data, dict) or data.get("version") not in (1, 2):
            raise DiagramError("This is not a valid Feynman Diagram Studio version 1 or 2 project.")
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
        raw_annotations = [] if data["version"] == 1 else data.get("annotations")
        if not isinstance(raw_annotations, list) or len(raw_annotations) > 300:
            raise DiagramError("A project may contain at most 300 annotations.")
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
                labelX=_number(raw, "labelX", -720, 720),
                labelY=_number(raw, "labelY", -480, 480),
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
                labelX=_number(raw, "labelX", -150, 150, 0),
                labelY=_number(raw, "labelY", -150, 150, 0),
                arrow=raw.get("arrow", "none"),
                color=raw.get("color", ""),
                bundle=int(_number(raw, "bundle", 1, 3, 1)),
                bundleSpacing=_number(raw, "bundleSpacing", 4, 40, 14),
                loopSize=_number(raw, "loopSize", 30, 180, 90),
                loopAngle=_number(raw, "loopAngle", -180, 180, -90),
                circular=raw.get("circular", False),
                momentum=_parse_momentum(raw["momentum"]) if data["version"] == 2 and "momentum" in raw else None,
            )
            if edge.kind not in KINDS or edge.arrow not in ARROWS:
                raise DiagramError("A propagator uses an unsupported style.")
            if not _valid_color(edge.color) or edge.bundle not in (1, 2, 3):
                raise DiagramError("A propagator has invalid appearance settings.")
            if not isinstance(edge.circular, bool):
                raise DiagramError("A propagator has invalid loop settings.")
            edges.append(edge)

        annotations: List[Annotation] = []
        for raw in raw_annotations:
            if not isinstance(raw, dict):
                raise DiagramError("Every annotation must be an object.")
            annotation_id = _text(raw, "id", 1, 80)
            color = raw.get("color")
            if not _valid_color(color):
                raise DiagramError("An annotation has an invalid color.")
            if raw.get("type") == "label":
                annotations.append(FreeLabel(annotation_id, _number(raw, "x", 0, 720), _number(raw, "y", 0, 480), _text(raw, "text", 0, 200), color))
            elif raw.get("type") == "arrow":
                annotations.append(FreeArrow(annotation_id, _number(raw, "x1", 0, 720), _number(raw, "y1", 0, 480), _number(raw, "x2", 0, 720), _number(raw, "y2", 0, 480), color))
            else:
                raise DiagramError("An annotation uses an unsupported type.")

        style = FigureStyle(
            widthMm=_number(raw_style, "widthMm", 60, 240),
            strokePt=_number(raw_style, "strokePt", 0.3, 2),
            fontPt=_number(raw_style, "fontPt", 5, 18),
        )
        ids = [item.id for item in vertices] + [item.id for item in edges] + [item.id for item in annotations]
        if len(ids) != len(set(ids)):
            raise DiagramError("Object IDs must be unique.")
        vertex_ids = {item.id for item in vertices}
        if any(item.from_ not in vertex_ids or item.to not in vertex_ids for item in edges):
            raise DiagramError("Every propagator must connect existing vertices.")

        document = cls(2, title, vertices, edges, style, annotations)
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

    def annotation(self, object_id: str) -> Annotation | None:
        return next((item for item in self.annotations if item.id == object_id), None)

    def remove(self, object_id: str) -> None:
        self.vertices = [item for item in self.vertices if item.id != object_id]
        self.edges = [
            item
            for item in self.edges
            if item.id != object_id and item.from_ != object_id and item.to != object_id
        ]
        self.annotations = [item for item in self.annotations if item.id != object_id]


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


def _parse_momentum(raw: Any) -> Momentum:
    if not isinstance(raw, dict):
        raise DiagramError("Invalid momentum annotation.")
    item = Momentum(
        label=_text(raw, "label", 0, 200),
        labelX=_number(raw, "labelX", -720, 720, 0),
        labelY=_number(raw, "labelY", -480, 480, 0),
        direction=raw.get("direction", ""),
        side=raw.get("side", ""),
        color=raw.get("color", ""),
        start=_number(raw, "start", 0, 0.95),
        end=_number(raw, "end", 0.05, 1),
    )
    if item.direction not in ("forward", "reverse") or item.side not in ("left", "right") or not _valid_color(item.color) or item.end - item.start < 0.05:
        raise DiagramError("Invalid momentum annotation.")
    return item


def make_annotation(kind: str, x: float, y: float) -> Annotation:
    return FreeLabel(str(uuid.uuid4()), x, y) if kind == "label" else FreeArrow(str(uuid.uuid4()), x, y, min(700, x + 80), y)


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


def snap_value(value: float, grid_size: float = GRID_SIZE) -> float:
    return math.floor(value / grid_size + 0.5) * grid_size


def blank_diagram() -> Diagram:
    return Diagram()


def templates() -> List[Diagram]:
    from importlib.resources import files

    source = files("feynman_studio").joinpath("templates.json").read_text(encoding="utf-8")
    return [Diagram.from_dict(item) for item in json.loads(source)]


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
