from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Sequence, Tuple

from .model import Edge, Vertex


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


def geometry(a: Vertex, b: Vertex, edge: Edge, lane_offset: float = 0) -> Tuple[List[Tuple[float, float]], Sample]:
    is_loop = math.hypot(b.x - a.x, b.y - a.y) < 0.01

    def sample(t: float) -> Sample:
        if is_loop:
            point = self_loop(a, edge.loopSize, edge.loopAngle, t)
        elif edge.circular:
            point = circular_arc(a, b, edge.curvature or 1, t)
        else:
            point = curve(a, b, edge.curvature, t)
        offset = lane_offset * math.sin(math.pi * t)
        return Sample(point.x + point.nx * offset, point.y + point.ny * offset, point.tx, point.ty, point.nx, point.ny)

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
            taper = min(1, distance / 15)
        else:
            taper = min(1, index / 8, (count - index) / 8)
        normal = 5 * math.sin(phase) if edge.kind == "photon" else 7 * math.sin(phase) if edge.kind == "gluon" else 0
        along = 6 * (math.cos(phase) - 1) * taper if edge.kind == "gluon" else 0
        points.append((point.x + point.nx * normal * taper + point.tx * along, point.y + point.ny * normal * taper + point.ty * along))
    return points, sample(0.5)


def edge_label_position(middle: Sample, edge: Edge) -> Tuple[float, float]:
    return (
        middle.x + middle.nx * edge.labelOffset + edge.labelX,
        middle.y + middle.ny * edge.labelOffset + edge.labelY,
    )


def distance_to_polyline(x: float, y: float, points: Sequence[Tuple[float, float]]) -> float:
    best = float("inf")
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        t = 0 if not length_squared else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / length_squared))
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best
