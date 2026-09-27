"""Import common TikZ-Feynman graph syntax into editable studio objects."""

from __future__ import annotations

import re
from collections import deque

from .model import Diagram, DiagramError, Momentum, make_edge, make_vertex


_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_VERTEX = re.compile(
    rf"\\vertex\s*(?:\[([^\]]*)\]\s*)?\(([A-Za-z][A-Za-z0-9_]*)\)\s*"
    rf"(?:at\s*\(\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)\s*)?"
)
_COMMAND = re.compile(r"\\(?:feynmandiagram|diagram\*?)(?=\s|\[|\{)")


def _group(source: str, start: int, opening: str, closing: str) -> tuple[str, int]:
    if start >= len(source) or source[start] != opening:
        raise DiagramError("Expected '{}' in TikZ-Feynman source.".format(opening))
    depth = 0
    for index in range(start, len(source)):
        if source[index] == opening:
            depth += 1
        elif source[index] == closing:
            depth -= 1
            if depth == 0:
                return source[start + 1:index], index + 1
    raise DiagramError("Unclosed '{}' in TikZ-Feynman source.".format(opening))


def _split(source: str, separator: str) -> list[str]:
    parts, start = [], 0
    depths = {"[": 0, "{": 0, "(": 0}
    closing = {"]": "[", "}": "{", ")": "("}
    for index, char in enumerate(source):
        if char in depths:
            depths[char] += 1
        elif char in closing:
            depths[closing[char]] -= 1
        elif char == separator and all(depth == 0 for depth in depths.values()):
            parts.append(source[start:index].strip())
            start = index + 1
    parts.append(source[start:].strip())
    return [part for part in parts if part]


def _options(source: str) -> dict[str, str]:
    result = {}
    for part in _split(source, ","):
        key, _, value = part.partition("=")
        result[key.strip().lower()] = value.strip().strip("{}")
    return result


def _label(source: str) -> str:
    value = source.strip().strip("{}")
    return value[1:-1] if value.startswith("$") and value.endswith("$") else value


def _graph(body: str, names: dict[str, object], marked: set[str], links: list[tuple[str, str, dict[str, str]]]) -> None:
    for statement in _split(body, ";"):
        for chain in _split(statement, ","):
            position, previous = 0, None
            while position < len(chain):
                position = len(chain) - len(chain[position:].lstrip())
                if chain.startswith("--", position):
                    if previous is None:
                        raise DiagramError("An edge needs a vertex before '--'.")
                    position += 2
                    position += len(chain[position:]) - len(chain[position:].lstrip())
                    edge_options = {}
                    if position < len(chain) and chain[position] == "[":
                        raw, position = _group(chain, position, "[", "]")
                        edge_options = _options(raw)
                    position += len(chain[position:]) - len(chain[position:].lstrip())
                    match = re.match(r"\(([A-Za-z][A-Za-z0-9_]*)\)|([A-Za-z][A-Za-z0-9_]*)", chain[position:])
                    if not match:
                        raise DiagramError("Expected a named vertex after '--'.")
                    name = match.group(1) or match.group(2)
                    position += match.end()
                    names.setdefault(name, None)
                    position += len(chain[position:]) - len(chain[position:].lstrip())
                    if position < len(chain) and chain[position] == "[":
                        raw, position = _group(chain, position, "[", "]")
                        node_options = _options(raw)
                        label = node_options.get("particle", node_options.get("label", ""))
                        if label:
                            names[name] = _label(label)
                        if "dot" in node_options or "blob" in node_options:
                            marked.add(name)
                    links.append((previous, name, edge_options))
                    previous = name
                else:
                    match = re.match(r"\(([A-Za-z][A-Za-z0-9_]*)\)|([A-Za-z][A-Za-z0-9_]*)", chain[position:])
                    if not match:
                        raise DiagramError("Unsupported TikZ-Feynman graph syntax near '{}'".format(chain[position:position + 30]))
                    name = match.group(1) or match.group(2)
                    position += match.end()
                    names.setdefault(name, None)
                    position += len(chain[position:]) - len(chain[position:].lstrip())
                    if position < len(chain) and chain[position] == "[":
                        raw, position = _group(chain, position, "[", "]")
                        options = _options(raw)
                        label = options.get("particle", options.get("label", ""))
                        if label:
                            names[name] = _label(label)
                        if "dot" in options or "blob" in options:
                            marked.add(name)
                    previous = name
                position += len(chain[position:]) - len(chain[position:].lstrip())
                if position < len(chain) and not chain.startswith("--", position):
                    raise DiagramError("Unsupported TikZ-Feynman graph syntax near '{}'".format(chain[position:position + 30]))


def _positions(names: dict[str, object], links: list[tuple[str, str, dict[str, str]]], explicit: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    points = dict(explicit)
    adjacency: dict[str, list[tuple[str, int]]] = {name: [] for name in names}
    for start, end, _ in links:
        adjacency[start].append((end, 1))
        adjacency[end].append((start, -1))
    for root in names:
        if root in points:
            continue
        if not points:
            points[root] = (0.0, 0.0)
        else:
            neighbors = [(neighbor, sign) for neighbor, sign in adjacency[root] if neighbor in points]
            if neighbors:
                neighbor, sign = neighbors[0]
                x, y = points[neighbor]
                points[root] = (x - sign * 2, y)
            else:
                points[root] = (max(x for x, _ in points.values()) + 2, 0.0)
        queue = deque([root])
        while queue:
            current = queue.popleft()
            x, y = points[current]
            for neighbor, sign in adjacency[current]:
                if neighbor not in points:
                    points[neighbor] = (x + sign * 2, y)
                    queue.append(neighbor)
    # Separate branches that otherwise land on the same point.
    groups: dict[tuple[float, float], list[str]] = {}
    for name, point in points.items():
        groups.setdefault(point, []).append(name)
    for (x, y), group in groups.items():
        movable = [name for name in group if name not in explicit]
        if len(group) > 1 and movable:
            for index, name in enumerate(movable):
                points[name] = (x, y + (index - (len(movable) - 1) / 2) * 1.5)
    xs, ys = [point[0] for point in points.values()], [point[1] for point in points.values()]
    left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
    return {name: (100 + (x - left) / (right - left) * 520 if right > left else 360,
                   400 - (y - bottom) / (top - bottom) * 320 if top > bottom else 240)
            for name, (x, y) in points.items()}


def import_tikz_feynman(source: str) -> Diagram:
    """Read a TikZ-Feynman graph or snippet; reject syntax that loses topology."""
    if len(source.encode("utf-8")) > 1_000_000:
        raise DiagramError("LaTeX source must be smaller than 1 MB.")
    source = re.sub(r"(?<!\\)%[^\n]*", "", source)
    names: dict[str, object] = {}
    marked: set[str] = set()
    explicit: dict[str, tuple[float, float]] = {}
    for match in _VERTEX.finditer(source):
        vertex_options, name, x, y = match.groups()
        position = match.end()
        label = None
        if position < len(source) and source[position] == "{":
            label, position = _group(source, position, "{", "}")
        if not source[position:].lstrip().startswith(";"):
            raise DiagramError("Unsupported \\vertex declaration for '{}'".format(name))
        names[name] = _label(label) if label else None
        if vertex_options and ("dot" in _options(vertex_options) or "blob" in _options(vertex_options)):
            marked.add(name)
        if x is not None:
            explicit[name] = (float(x), float(y))
    links: list[tuple[str, str, dict[str, str]]] = []
    commands = list(_COMMAND.finditer(source))
    if not commands:
        raise DiagramError("No TikZ-Feynman \\feynmandiagram or \\diagram command found.")
    for match in commands:
        position = match.end()
        position += len(source[position:]) - len(source[position:].lstrip())
        if position < len(source) and source[position] == "[":
            _, position = _group(source, position, "[", "]")
        position += len(source[position:]) - len(source[position:].lstrip())
        body, _ = _group(source, position, "{", "}")
        _graph(body, names, marked, links)
    if not links:
        raise DiagramError("No supported edges found in the TikZ-Feynman graph.")
    if len(names) > 150 or len(links) > 300:
        raise DiagramError("The diagram exceeds the studio limit of 150 vertices or 300 edges.")
    positions = _positions(names, links, explicit)
    diagram = Diagram(title="Imported LaTeX diagram")
    vertices = {}
    for name, label in names.items():
        x, y = positions[name]
        vertex = make_vertex(x, y, str(label or ""), name in marked)
        vertices[name] = vertex
        diagram.vertices.append(vertex)
    for start, end, options in links:
        style = next((key for key in ("anti fermion", "fermion", "photon", "gluon", "charged scalar", "anti charged scalar", "scalar", "ghost") if key in options), "fermion")
        kind = style.replace("anti ", "").replace("charged ", "")
        edge = make_edge(vertices[start].id, vertices[end].id, kind)
        if style == "anti fermion":
            edge.arrow = "reverse"
        elif style in ("charged scalar", "anti charged scalar"):
            edge.arrow = "reverse" if style.startswith("anti") else "forward"
        elif "fermion" not in options:
            edge.arrow = "none"
        edge.label = _label(options.get("edge label", options.get("edge label'", "")))
        if "edge label'" in options:
            edge.labelOffset = 25
        if "half left" in options or "quarter left" in options:
            edge.curvature = -65 if "half left" in options else -35
        elif "half right" in options or "quarter right" in options:
            edge.curvature = 65 if "half right" in options else 35
        if "momentum" in options or "momentum'" in options:
            edge.momentum = Momentum(label=_label(options.get("momentum", options.get("momentum'", ""))))
            if "momentum'" in options:
                edge.momentum.side = "left"
        diagram.edges.append(edge)
    return Diagram.from_dict(diagram.to_dict())
