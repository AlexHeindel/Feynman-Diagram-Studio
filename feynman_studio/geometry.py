from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Sequence, Tuple

from .model import Diagram, Edge, Vertex, bundle_offsets


@dataclass(frozen=True)
class Sample:
    x: float
    y: float
    tx: float
    ty: float
    nx: float
    ny: float


def curve(a: Vertex, b: Vertex, curvature: float, t: float) -> Sample:
    dx, dy = b.x - a.x, b.y - a.y
    length = math.hypot(dx, dy) or 1.0
    cx = (a.x + b.x) / 2 - dy / length * curvature
    cy = (a.y + b.y) / 2 + dx / length * curvature
    x = (1 - t) ** 2 * a.x + 2 * (1 - t) * t * cx + t**2 * b.x
    y = (1 - t) ** 2 * a.y + 2 * (1 - t) * t * cy + t**2 * b.y
    tx = 2 * (1 - t) * (cx - a.x) + 2 * t * (b.x - cx)
    ty = 2 * (1 - t) * (cy - a.y) + 2 * t * (b.y - cy)
    magnitude = math.hypot(tx, ty) or 1.0
    return Sample(x, y, tx / magnitude, ty / magnitude, -ty / magnitude, tx / magnitude)


def _cubic(points: Sequence[Tuple[float, float]], t: float) -> Sample:
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = points
    x = (1 - t) ** 3 * ax + 3 * (1 - t) ** 2 * t * bx + 3 * (1 - t) * t**2 * cx + t**3 * dx
    y = (1 - t) ** 3 * ay + 3 * (1 - t) ** 2 * t * by + 3 * (1 - t) * t**2 * cy + t**3 * dy
    tx = 3 * (1 - t) ** 2 * (bx - ax) + 6 * (1 - t) * t * (cx - bx) + 3 * t**2 * (dx - cx)
    ty = 3 * (1 - t) ** 2 * (by - ay) + 6 * (1 - t) * t * (cy - by) + 3 * t**2 * (dy - cy)
    magnitude = math.hypot(tx, ty) or 1.0
    return Sample(x, y, tx / magnitude, ty / magnitude, -ty / magnitude, tx / magnitude)


def self_loop(point: Vertex, size: float, angle_degrees: float, t: float) -> Sample:
    angle = math.radians(angle_degrees)
    direction = (math.cos(angle), math.sin(angle))
    normal = (-direction[1], direction[0])
    width = size * 0.58
    origin = (point.x, point.y)
    far = (point.x + direction[0] * size, point.y + direction[1] * size)
    first = (point.x + normal[0] * width, point.y + normal[1] * width)
    second = (far[0] + normal[0] * width, far[1] + normal[1] * width)
    third = (far[0] - normal[0] * width, far[1] - normal[1] * width)
    fourth = (point.x - normal[0] * width, point.y - normal[1] * width)
    if t <= 0.5:
        return _cubic((origin, first, second, far), t * 2)
    return _cubic((far, third, fourth, origin), (t - 0.5) * 2)


def circular_arc(a: Vertex, b: Vertex, side: float, t: float) -> Sample:
    center_x, center_y = (a.x + b.x) / 2, (a.y + b.y) / 2
    radius = math.hypot(b.x - a.x, b.y - a.y) / 2
    start = math.atan2(a.y - center_y, a.x - center_x)
    sweep = -(1 if side >= 0 else -1) * math.pi
    angle = start + sweep * t
    sign = 1 if sweep >= 0 else -1
    tx, ty = -math.sin(angle) * sign, math.cos(angle) * sign
    return Sample(
        center_x + radius * math.cos(angle),
        center_y + radius * math.sin(angle),
        tx,
        ty,
        -ty,
        tx,
    )


def edge_sample(a: Vertex, b: Vertex, edge: Edge, t: float) -> Sample:
    is_loop = math.hypot(b.x - a.x, b.y - a.y) < 0.01
    if is_loop:
        return self_loop(a, edge.loopSize, edge.loopAngle, t)
    if edge.circular:
        return circular_arc(a, b, edge.curvature or 1, t)
    return curve(a, b, edge.curvature, t)


def geometry(a: Vertex, b: Vertex, edge: Edge, lane_offset: float = 0) -> Tuple[List[Tuple[float, float]], Sample]:
    def sample(t: float) -> Sample:
        point = edge_sample(a, b, edge, t)
        return Sample(point.x + point.nx * lane_offset, point.y + point.ny * lane_offset, point.tx, point.ty, point.nx, point.ny)

    center = [sample(index / 200) for index in range(201)]
    lengths = [0.0]
    for previous, current in zip(center, center[1:]):
        lengths.append(lengths[-1] + math.hypot(current.x - previous.x, current.y - previous.y))
    length = lengths[-1]
    cycles = max(2, round(length / (17 if edge.kind == "gluon" else 20)))
    count = cycles * 24
    points: List[Tuple[float, float]] = []
    for index in range(count + 1):
        distance = length * index / count
        cursor = 1
        while cursor < 200 and lengths[cursor] < distance:
            cursor += 1
        segment = lengths[cursor] - lengths[cursor - 1]
        fraction = (distance - lengths[cursor - 1]) / (segment or 1)
        point = sample((cursor - 1 + fraction) / 200)
        phase = 2 * math.pi * cycles * index / count
        if edge.kind == "gluon":
            normal = 7 * (1 - math.cos(phase))
            along = 6 * math.sin(phase)
        else:
            taper = min(1, index / 8, (count - index) / 8)
            normal = 5 * math.sin(phase) * taper if edge.kind == "photon" else 0
            along = 0
        points.append((point.x + point.nx * normal + point.tx * along, point.y + point.ny * normal + point.ty * along))
    return points, sample(0.5)


def connect_endpoint(points: List[Tuple[float, float]], join: Tuple[float, float], tangent: Sample,
                     at_start: bool) -> List[Tuple[float, float]]:
    endpoint = points[0] if at_start else points[-1]
    longitudinal = (join[0] - endpoint[0]) * tangent.tx + (join[1] - endpoint[1]) * tangent.ty
    if at_start:
        index = 0
        while longitudinal > 0 and index < len(points) - 2 and (
            (points[index][0] - endpoint[0]) * tangent.tx +
            (points[index][1] - endpoint[1]) * tangent.ty < longitudinal
        ):
            index += 1
        return [join] + points[index:]
    index = len(points) - 1
    while longitudinal < 0 and index > 1 and (
        (points[index][0] - endpoint[0]) * tangent.tx +
        (points[index][1] - endpoint[1]) * tangent.ty > longitudinal
    ):
        index -= 1
    return points[:index + 1] + [join]


def connected_geometry(document: Diagram, edge: Edge, lane_offset: float) -> Tuple[List[Tuple[float, float]], Sample]:
    a, b = document.vertex(edge.from_), document.vertex(edge.to)
    if a is None or b is None:
        raise ValueError("This propagator has a missing endpoint.")
    if edge.kind != "fermion" or edge.bundle < 2 or edge.from_ == edge.to:
        return geometry(a, b, edge, lane_offset)
    lane = bundle_offsets(edge).index(lane_offset)

    def join(vertex: Vertex, t: int) -> Tuple[float, float] | None:
        incident = [item for item in document.edges if item.kind == "fermion" and item.bundle == edge.bundle
                    and item.from_ != item.to and (item.from_ == vertex.id or item.to == vertex.id)]
        if len(incident) != 2 or all(item.id != edge.id for item in incident):
            return None
        other = next(item for item in incident if item.id != edge.id)
        other_a, other_b = document.vertex(other.from_), document.vertex(other.to)
        if other_a is None or other_b is None:
            return None
        other_t = 0 if other.from_ == vertex.id else 1
        normal = edge_sample(a, b, edge, t)
        other_normal = edge_sample(other_a, other_b, other, other_t)
        aligned = (edge.from_ == vertex.id) != (other.from_ == vertex.id)
        other_lane = bundle_offsets(other)[lane if aligned else edge.bundle - 1 - lane]
        p = (vertex.x + normal.nx * lane_offset, vertex.y + normal.ny * lane_offset)
        q = (vertex.x + other_normal.nx * other_lane, vertex.y + other_normal.ny * other_lane)
        cross = normal.tx * other_normal.ty - normal.ty * other_normal.tx
        if abs(cross) > 1e-6:
            along = ((q[0] - p[0]) * other_normal.ty - (q[1] - p[1]) * other_normal.tx) / cross
            miter = (p[0] + normal.tx * along, p[1] + normal.ty * along)
            if math.hypot(miter[0] - vertex.x, miter[1] - vertex.y) <= max(8, 2 * max(abs(lane_offset), abs(other_lane))):
                return miter
        return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)

    points, middle = geometry(a, b, edge, lane_offset)
    start, end = join(a, 0), join(b, 1)
    if start:
        points = connect_endpoint(points, start, edge_sample(a, b, edge, 0), True)
    if end:
        points = connect_endpoint(points, end, edge_sample(a, b, edge, 1), False)
    return points, middle


def edge_label_position(middle: Sample, edge: Edge) -> Tuple[float, float]:
    return (
        middle.x + middle.nx * edge.labelOffset + edge.labelX,
        middle.y + middle.ny * edge.labelOffset + edge.labelY,
    )


def momentum_geometry(a: Vertex, b: Vertex, edge: Edge):
    momentum = edge.momentum
    if momentum is None:
        raise ValueError("This propagator has no momentum annotation.")
    side = -1 if momentum.side == "left" else 1
    def sample(t: float) -> Sample:
        if math.hypot(b.x - a.x, b.y - a.y) < 0.01:
            return self_loop(a, edge.loopSize, edge.loopAngle, t)
        if edge.circular:
            return circular_arc(a, b, edge.curvature or 1, t)
        return curve(a, b, edge.curvature, t)
    samples = [sample(i / 200) for i in range(201)]
    lengths = [0.0]
    for previous, current in zip(samples, samples[1:]):
        lengths.append(lengths[-1] + math.hypot(current.x - previous.x, current.y - previous.y))
    total = lengths[-1]
    def at(fraction: float) -> Sample:
        distance = fraction * total
        i = 1
        while i < 200 and lengths[i] < distance:
            i += 1
        t = (distance - lengths[i - 1]) / (lengths[i] - lengths[i - 1] or 1)
        previous, current = samples[i - 1], samples[i]
        x = previous.x + (current.x - previous.x) * t
        y = previous.y + (current.y - previous.y) * t
        dx, dy = current.x - previous.x, current.y - previous.y
        size = math.hypot(dx, dy) or 1
        tx, ty = dx / size, dy / size
        nx, ny = -ty, tx
        return Sample(x + side * nx * 18, y + side * ny * 18, tx, ty, nx, ny)
    count = max(2, math.ceil((momentum.end - momentum.start) * total / 5))
    points = [at(momentum.start + (momentum.end - momentum.start) * i / count) for i in range(count + 1)]
    tip = points[-1] if momentum.direction == "forward" else points[0]
    sign = 1 if momentum.direction == "forward" else -1
    arrow = [(tip.x, tip.y),
             (tip.x - sign * tip.tx * 12 + tip.nx * 5, tip.y - sign * tip.ty * 12 + tip.ny * 5),
             (tip.x - sign * tip.tx * 12 - tip.nx * 5, tip.y - sign * tip.ty * 12 - tip.ny * 5)]
    middle = at((momentum.start + momentum.end) / 2)
    label = (middle.x + side * middle.nx * 30 + momentum.labelX,
             middle.y + side * middle.ny * 30 + momentum.labelY)
    return [(p.x, p.y) for p in points], arrow, label


def distance_to_polyline(x: float, y: float, points: Sequence[Tuple[float, float]]) -> float:
    best = float("inf")
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        t = 0 if not length_squared else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / length_squared))
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best
