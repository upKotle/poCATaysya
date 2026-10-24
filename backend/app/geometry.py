"""Сравнение линий в метрах. Направление пути хранится в отдельных рёбрах."""
import math
from dataclasses import dataclass

from shapely import STRtree
from shapely.geometry import LineString, GeometryCollection
from shapely.ops import unary_union


def edges(line, max_length=None):
    for a, b in zip(line.coords, list(line.coords)[1:]):
        length = math.dist(a, b)
        count = max(1, math.ceil(length / max_length)) if max_length else 1
        if length < 1e-6:
            continue
        for i in range(count):
            start = tuple(a[k] + (b[k] - a[k]) * i / count for k in (0, 1))
            end = tuple(a[k] + (b[k] - a[k]) * (i + 1) / count for k in (0, 1))
            yield LineString([start, end])


def parallel(a, b, bidirectional=True):
    ax, ay = a.coords[-1][0] - a.coords[0][0], a.coords[-1][1] - a.coords[0][1]
    bx, by = b.coords[-1][0] - b.coords[0][0], b.coords[-1][1] - b.coords[0][1]
    cosine = (ax * bx + ay * by) / (a.length * b.length)
    return (abs(cosine) if bidirectional else cosine) >= math.cos(math.radians(30))


@dataclass
class RoadTrace:
    line: LineString

    def __post_init__(self):
        self.edges = list(edges(self.line))
        self.tree = STRtree(self.edges)
        self.unique = unary_union(self.edges)

    def coverage(self, reference, tolerance, bidirectional=True):
        """Длина reference, пройденная вдоль дороги, а не поперёк неё.

        Объединение совпадений не начисляет длину повторно за второй проезд.
        Плоские торцы буфера не превращают касание в прохождение участка.
        """
        pieces = []
        for edge in edges(reference):
            matches = [self.edges[int(i)] for i in self.tree.query(edge.buffer(tolerance))
                       if parallel(edge, self.edges[int(i)], bidirectional)]
            if matches:
                strip = unary_union([other.buffer(tolerance, cap_style=2) for other in matches])
                pieces.append(edge.intersection(strip))
        return unary_union(pieces) if pieces else GeometryCollection()


def repeated_distance(line, tolerance, sample_meters):
    pieces = list(edges(line, sample_meters))
    tree = STRtree(pieces)
    offsets, offset = [], 0.0
    for piece in pieces:
        offsets.append(offset)
        offset += piece.length
    repeated = 0.0
    for index, piece in enumerate(pieces):
        previous = [pieces[int(i)] for i in tree.query(piece.buffer(tolerance))
                    if int(i) < index and offsets[index] - offsets[int(i)] > 2 * sample_meters
                    and parallel(piece, pieces[int(i)])]
        if previous:
            strip = unary_union([other.buffer(tolerance, cap_style=2) for other in previous])
            repeated += piece.intersection(strip).length
    return min(line.length, repeated)


def route_similarity(a: RoadTrace, b: RoadTrace, tolerance):
    """Меньшая из двух долей общей геометрии; обратный ход тоже совпадение."""
    if min(a.unique.length, b.unique.length) <= 0:
        return 1.0 if max(a.unique.length, b.unique.length) <= 0 else 0.0
    # Работаем с уникальной линией, а не суммой повторных обходов.
    common_a = a.unique.intersection(b.unique.buffer(tolerance)).length / a.unique.length
    common_b = b.unique.intersection(a.unique.buffer(tolerance)).length / b.unique.length
    return min(1.0, common_a, common_b)
