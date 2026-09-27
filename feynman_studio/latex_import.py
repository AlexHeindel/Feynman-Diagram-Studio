"""Import common TikZ-Feynman graph syntax into editable studio objects."""

from __future__ import annotations

import base64
import binascii
import re
from collections import deque

from .model import Diagram, DiagramError, Momentum, make_edge, make_vertex


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_HORIZONTAL = re.compile(r"\bhorizontal\s*=\s*([A-Za-z][A-Za-z0-9_]*)\s+to\s+([A-Za-z][A-Za-z0-9_]*)")
_VERTEX = re.compile(
    rf"\\vertex\s*(?:\[([^\]]*)\]\s*)?\(([A-Za-z][A-Za-z0-9_]*)\)\s*"
    rf"(?:at\s*\(\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)\s*)?"
)
_COMMAND = re.compile(r"\\(?:feynmandiagram|diagram\*?)(?=\s|\[|\{)")
_COLORS = {"black": "#000000", "white": "#FFFFFF", "red": "#FF0000", "blue": "#0000FF",
           "green": "#008000", "cyan": "#00FFFF", "magenta": "#FF00FF", "yellow": "#FFFF00",
           "gray": "#808080", "grey": "#808080", "orange": "#FFA500"}


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
    if value.startswith("$") and value.endswith("$"):
        value = value[1:-1]
    elif value.startswith(r"\(") and value.endswith(r"\)"):
        value = value[2:-2]
    return re.sub(r"\\(?:bar|overline)\s+(\\[A-Za-z]+|[A-Za-z])", lambda match: r"\overline{" + match.group(1) + "}", value)


def _color(options: dict[str, str], default: str = "#000000") -> str:
    value = options.get("draw", options.get("color", ""))
    if not value:
        value = next((name for name in _COLORS if name in options), "")
    value = value.lower()
    if value in _COLORS:
        return _COLORS[value]
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return value.upper()
    return default


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


def _horizontal_tree(names: dict[str, object], links: list[tuple[str, str, dict[str, str]]], anchors: tuple[str, str]) -> dict[str, tuple[float, float]] | None:
    if len(links) != len(names) - 1 or any(name not in names for name in anchors):
        return None
    adjacency: dict[str, list[str]] = {name: [] for name in names}
    for start, end, _ in links:
        adjacency[start].append(end)
        adjacency[end].append(start)
    parents = {anchors[0]: None}
    queue = deque([anchors[0]])
    while queue and anchors[1] not in parents:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor not in parents:
                parents[neighbor] = current
                queue.append(neighbor)
    if anchors[1] not in parents:
        return None
    path = [anchors[1]]
    while path[-1] != anchors[0]:
        path.append(parents[path[-1]])
    path.reverse()
    points = {name: (float(index), 0.0) for index, name in enumerate(path)}
    path_names = set(path)
    for index, name in enumerate(path):
        direction = -1 if index < (len(path) - 1) / 2 else 1
        children = [neighbor for neighbor in adjacency[name] if neighbor not in path_names]
        for child_index, child in enumerate(children):
            points[child] = (index + direction * 1.5, (len(children) - 1) / 2 - child_index)
            queue = deque([(child, name)])
            while queue:
                current, previous = queue.popleft()
                descendants = [neighbor for neighbor in adjacency[current] if neighbor != previous and neighbor not in points]
                for next_index, neighbor in enumerate(descendants):
                    x, y = points[current]
                    points[neighbor] = (x + direction * 1.5, y + (len(descendants) - 1) / 2 - next_index)
                    queue.append((neighbor, current))
    return points if len(points) == len(names) else None


def _triangle_loop(names: dict[str, object], links: list[tuple[str, str, dict[str, str]]], anchors: tuple[str, str]) -> dict[str, tuple[float, float]] | None:
    # ponytail: common anchored triangle only; use a graph layout engine for arbitrary cycles.
    if len(names) != 6 or len(links) not in (6, 7):
        return None
    left, center = anchors
    pairs = {frozenset((start, end)) for start, end, _ in links}
    pair = lambda first, second: frozenset((first, second))
    if pair(left, center) not in pairs or len(pairs) != len(links):
        return None
    neighbors = [end if start == center else start for start, end, _ in links
                 if center in (start, end) and left not in (start, end)]
    if len(neighbors) != 2 or pair(*neighbors) not in pairs:
        return None
    upper, lower = neighbors

    def photon_end(name: str) -> str | None:
        matches = [end if start == name else start for start, end, options in links
                   if name in (start, end) and "photon" in options]
        return matches[0] if len(matches) == 1 else None

    upper_end, lower_end = photon_end(upper), photon_end(lower)
    if not upper_end or not lower_end or len({left, center, upper, lower, upper_end, lower_end}) != 6:
        return None
    required = {pair(left, center), pair(center, upper), pair(upper, lower), pair(lower, center),
                pair(upper, upper_end), pair(lower, lower_end)}
    connector = pair(upper_end, lower_end)
    if not required <= pairs or pairs - required not in (set(), {connector}):
        return None
    tied = connector in pairs
    return {left: (0, 0), center: (1, 0), upper: (2, 1), lower: (2, -1),
            upper_end: (3 if tied else 2.2, 1 if tied else 2),
            lower_end: (3 if tied else 2.2, -1 if tied else -2)}


def _layered_tree(names: dict[str, object], links: list[tuple[str, str, dict[str, str]]], root: str) -> dict[str, tuple[float, float]] | None:
    if root not in names or len(links) != len(names) - 1:
        return None
    adjacency: dict[str, list[str]] = {name: [] for name in names}
    for start, end, _ in links:
        adjacency[start].append(end)
        adjacency[end].append(start)
    points: dict[str, tuple[float, float]] = {}
    seen: set[str] = set()
    leaf = 0

    def place(name: str, depth: int) -> float:
        nonlocal leaf
        seen.add(name)
        children = [neighbor for neighbor in adjacency[name] if neighbor not in seen]
        levels = [place(child, depth + 1) for child in children]
        if levels:
            y = sum(levels) / len(levels)
        else:
            y = -float(leaf)
            leaf += 1
        points[name] = (float(depth), y)
        return y

    place(root, 0)
    return points if len(points) == len(names) else None


def _positions(names: dict[str, object], links: list[tuple[str, str, dict[str, str]]], explicit: dict[str, tuple[float, float]], horizontal: tuple[str, str] | None, layered: bool) -> dict[str, tuple[float, float]]:
    anchored = None
    if horizontal and not explicit:
        anchored = (_layered_tree(names, links, horizontal[0]) if layered else
                    _triangle_loop(names, links, horizontal) or _horizontal_tree(names, links, horizontal))
    if anchored is not None:
        points = anchored
    else:
        points = _inferred_positions(names, links, explicit)
    xs, ys = [point[0] for point in points.values()], [point[1] for point in points.values()]
    left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
    return {name: (100 + (x - left) / (right - left) * 520 if right > left else 360,
                   400 - (y - bottom) / (top - bottom) * 320 if top > bottom else 240)
            for name, (x, y) in points.items()}


def _inferred_positions(names: dict[str, object], links: list[tuple[str, str, dict[str, str]]], explicit: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
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
    return points


def import_tikz_feynman(source: str) -> Diagram:
    """Read a TikZ-Feynman graph or snippet; reject syntax that loses topology."""
    if len(source.encode("utf-8")) > 1_000_000:
        raise DiagramError("LaTeX source must be smaller than 1 MB.")
    embedded = re.findall(r"(?m)^% FDS_DIAGRAM_JSON: ([A-Za-z0-9+/=]+)$", source)
    if embedded:
        try:
            return Diagram.from_json(base64.b64decode("".join(embedded), validate=True).decode("utf-8"))
        except (binascii.Error, UnicodeError) as exc:
            raise DiagramError("Invalid embedded studio diagram in LaTeX source.") from exc
    source = re.sub(r"(?<!\\)%[^\n]*", "", source)
    names: dict[str, object] = {}
    marked: set[str] = set()
    explicit: dict[str, tuple[float, float]] = {}
    relative: dict[str, tuple[str, float, float]] = {}
    for match in _VERTEX.finditer(source):
        vertex_options, name, x, y = match.groups()
        position = match.end()
        label = None
        if position < len(source) and source[position] == "{":
            label, position = _group(source, position, "{", "}")
        if not source[position:].lstrip().startswith(";"):
            raise DiagramError("Unsupported \\vertex declaration for '{}'".format(name))
        names[name] = _label(label) if label else None
        if vertex_options:
            options = _options(vertex_options)
            if "dot" in options or "blob" in options:
                marked.add(name)
            for direction in ("above right", "above left", "below right", "below left", "right", "left", "above", "below"):
                if direction in options:
                    reference = re.fullmatch(r"of\s+([A-Za-z][A-Za-z0-9_]*)", options[direction])
                    if not reference:
                        raise DiagramError("Unsupported relative position for '{}'".format(name))
                    relative[name] = (reference.group(1), 2.0 * (("right" in direction) - ("left" in direction)),
                                      2.0 * (("above" in direction) - ("below" in direction)))
                    break
        if x is not None:
            explicit[name] = (float(x), float(y))
    if relative:
        for index, name in enumerate(item for item in names if item not in relative and item not in explicit):
            explicit[name] = (index * 3.0, 0.0)
        pending = dict(relative)
        while pending:
            ready = [name for name, (reference, _, _) in pending.items() if reference in explicit]
            if not ready:
                raise DiagramError("Relative vertex positions contain an unknown or circular reference.")
            for name in ready:
                reference, dx, dy = pending.pop(name)
                x, y = explicit[reference]
                explicit[name] = (x + dx, y + dy)
    links: list[tuple[str, str, dict[str, str]]] = []
    horizontal = None
    layered = False
    commands = list(_COMMAND.finditer(source))
    if not commands:
        raise DiagramError("No TikZ-Feynman \\feynmandiagram or \\diagram command found.")
    for match in commands:
        position = match.end()
        position += len(source[position:]) - len(source[position:].lstrip())
        if position < len(source) and source[position] == "[":
            options, position = _group(source, position, "[", "]")
            match_horizontal = _HORIZONTAL.search(options)
            if match_horizontal:
                horizontal = match_horizontal.groups()
            layered = layered or "layered layout" in options.lower()
        position += len(source[position:]) - len(source[position:].lstrip())
        body, _ = _group(source, position, "{", "}")
        _graph(body, names, marked, links)
    if not links:
        raise DiagramError("No supported edges found in the TikZ-Feynman graph.")
    if len(names) > 150 or len(links) > 300:
        raise DiagramError("The diagram exceeds the studio limit of 150 vertices or 300 edges.")
    positions = _positions(names, links, explicit, horizontal, layered)
    diagram = Diagram(title="Imported LaTeX diagram")
    vertices = {}
    for name, label in names.items():
        x, y = positions[name]
        vertex = make_vertex(x, y, str(label or ""), name in marked)
        vertices[name] = vertex
        diagram.vertices.append(vertex)
    for start, end, options in links:
        if options.get("draw") == "none":
            continue
        style = next((key for key in ("anti fermion", "fermion", "photon", "boson", "gluon", "charged scalar", "anti charged scalar", "scalar", "ghost") if key in options), "fermion")
        kind = "photon" if style == "boson" else style.replace("anti ", "").replace("charged ", "")
        edge = make_edge(vertices[start].id, vertices[end].id, kind)
        edge.color = _color(options)
        if "opacity" in options:
            try:
                opacity = float(options["opacity"])
            except ValueError as exc:
                raise DiagramError("Opacity must be a number between 0 and 1.") from exc
            if not 0 <= opacity <= 1:
                raise DiagramError("Opacity must be a number between 0 and 1.")
            rgb = tuple(int(edge.color[index:index + 2], 16) for index in (1, 3, 5))
            edge.color = "#" + "".join("{:02X}".format(round(255 * (1 - opacity) + value * opacity)) for value in rgb)
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
            value = options.get("momentum", options.get("momentum'", ""))
            color = edge.color
            if value.startswith("["):
                styling, position = _group(value, 0, "[", "]")
                color = _color({"draw": _options(styling).get("arrow style", "")}, color)
                value = value[position:].strip()
            edge.momentum = Momentum(label=_label(value), side="right" if "momentum'" in options else "left", color=color)
        diagram.edges.append(edge)
    return Diagram.from_dict(diagram.to_dict())
