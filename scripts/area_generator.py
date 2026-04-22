from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


Coordinate = Tuple[float, float]


def generate_provisional_areas(
    points: Sequence[dict],
    observations: Sequence[dict],
    manual_area_keys: Iterable[str],
) -> List[dict]:
    """Build provisional areas for full questions and their answer variants."""

    point_lookup = {
        point["point_id"]: point
        for point in points
        if point.get("latitude") is not None and point.get("longitude") is not None
    }
    manual_area_keys = set(manual_area_keys)
    grouped_by_feature: Dict[str, List[Coordinate]] = defaultdict(list)
    grouped_by_answer: Dict[Tuple[str, str], List[Coordinate]] = defaultdict(list)

    for observation in observations:
        point = point_lookup.get(observation.get("point_id"))
        if not point:
            continue
        feature_id = observation.get("feature_id") or ""
        if not feature_id:
            continue
        coordinate = (point["longitude"], point["latitude"])
        grouped_by_feature[feature_id].append(coordinate)

        raw_answers = observation.get("answers") or []
        answers = [str(answer).strip() for answer in raw_answers if str(answer).strip()]
        if not answers:
            fallback_answers = [
                str(observation.get("attested_value") or "").strip(),
                str(observation.get("secondary_value") or "").strip(),
                str(observation.get("tertiary_value") or "").strip(),
            ]
            answers = [answer for answer in fallback_answers if answer]
        for answer in dict.fromkeys(answers):
            grouped_by_answer[(feature_id, answer)].append(coordinate)

    provisional_features: List[dict] = []
    for feature_id, coordinates in sorted(grouped_by_feature.items()):
        feature_key = build_scope_key(feature_id, None)
        if feature_key in manual_area_keys:
            continue
        geometry = coordinates_to_geometry(coordinates)
        if geometry is None:
            continue
        provisional_features.append(
            build_geojson_feature(
                feature_id=feature_id,
                geometry=geometry,
                attested_value="",
                scope="feature",
            )
        )

    for (feature_id, attested_value), coordinates in sorted(grouped_by_answer.items()):
        feature_key = build_scope_key(feature_id, attested_value)
        if feature_key in manual_area_keys:
            continue
        geometry = coordinates_to_geometry(coordinates)
        if geometry is None:
            continue
        provisional_features.append(
            build_geojson_feature(
                feature_id=feature_id,
                geometry=geometry,
                attested_value=attested_value,
                scope="value",
            )
        )

    return provisional_features


def generate_provisional_isoglosses(
    points: Sequence[dict],
    observations: Sequence[dict],
    border_geojson: Optional[dict],
    manual_isogloss_keys: Iterable[str],
) -> List[dict]:
    point_lookup = {
        point["point_id"]: point
        for point in points
        if point.get("latitude") is not None and point.get("longitude") is not None
    }
    border_bounds = geometry_bounds(extract_primary_geometry(border_geojson))
    if border_bounds is None:
        border_bounds = infer_bounds_from_points(point_lookup.values())
    if border_bounds is None:
        return []

    manual_isogloss_keys = set(manual_isogloss_keys)
    feature_groups: Dict[str, List[Coordinate]] = defaultdict(list)

    for observation in observations:
        point = point_lookup.get(observation.get("point_id"))
        if not point:
            continue
        feature_id = observation.get("feature_id") or ""
        if not feature_id:
            continue
        feature_groups[feature_id].append((point["longitude"], point["latitude"]))

    provisional_isoglosses: List[dict] = []
    sorted_features = sorted(
        (
            (feature_id, list(dict.fromkeys(coordinates)))
            for feature_id, coordinates in feature_groups.items()
            if len(set(coordinates)) >= 2
        ),
        key=lambda item: item[0],
    )

    for left_index in range(len(sorted_features)):
        left_feature_id, left_coordinates = sorted_features[left_index]
        for right_index in range(left_index + 1, len(sorted_features)):
            right_feature_id, right_coordinates = sorted_features[right_index]
            pair_key = build_feature_pair_key(left_feature_id, right_feature_id)
            if pair_key in manual_isogloss_keys:
                continue
            line = build_separator_line(left_coordinates, right_coordinates, border_bounds)
            if line is None:
                continue
            provisional_isoglosses.append(
                {
                    "type": "Feature",
                    "properties": {
                        "feature_id": left_feature_id,
                        "feature_pair": [left_feature_id, right_feature_id],
                        "attested_value": "",
                        "geometry_type": "line",
                        "source": "auto",
                        "scope": "pair",
                        "style_code": "line_isogloss_minor",
                        "title": "Предварительная изоглосса между вопросами",
                        "status_note": (
                            "Предварительная линия построена автоматически между двумя "
                            "выбранными вопросами и служит только демонстрационной визуализацией."
                        ),
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in line],
                    },
                }
            )

    return provisional_isoglosses


def build_scope_key(feature_id: str, attested_value: Optional[str]) -> str:
    value = (attested_value or "").strip().lower()
    return f"{feature_id}::{value}"


def build_feature_pair_key(left_feature_id: str, right_feature_id: str) -> str:
    left, right = sorted([left_feature_id, right_feature_id])
    return f"{left}::{right}"


def coordinates_to_polygon(coordinates: Sequence[Coordinate]) -> Optional[List[List[float]]]:
    unique_coordinates = sorted(set(coordinates))
    if len(unique_coordinates) < 3:
        return None

    hull = convex_hull(unique_coordinates)
    if len(hull) < 3:
        return None

    expanded = expand_polygon(hull, scale=1.12 if len(unique_coordinates) > 4 else 1.08)
    dense_ring = densify_ring(expanded, segments=3)
    smooth_ring = chaikin_smoothing(dense_ring, iterations=2)
    rounded_ring = [[round(lon, 6), round(lat, 6)] for lon, lat in smooth_ring]
    rounded_ring.append(rounded_ring[0])
    return rounded_ring


def coordinates_to_geometry(coordinates: Sequence[Coordinate]) -> Optional[dict]:
    polygon = coordinates_to_polygon(coordinates)
    if polygon is None:
        return None
    return {
        "type": "Polygon",
        "coordinates": [polygon],
    }


def extract_primary_geometry(payload: Optional[dict]) -> Optional[dict]:
    if not payload:
        return None
    payload_type = payload.get("type")
    if payload_type == "FeatureCollection":
        features = payload.get("features") or []
        if not features:
            return None
        largest_feature = max(features, key=lambda item: geometry_area(item.get("geometry") or {}), default=None)
        return (largest_feature or {}).get("geometry")
    if payload_type == "Feature":
        return payload.get("geometry")
    return payload


def infer_bounds_from_points(points: Iterable[dict]) -> Optional[Tuple[float, float, float, float]]:
    coordinates = [
        (point.get("longitude"), point.get("latitude"))
        for point in points
        if point.get("longitude") is not None and point.get("latitude") is not None
    ]
    if not coordinates:
        return None
    longitudes = [longitude for longitude, _ in coordinates]
    latitudes = [latitude for _, latitude in coordinates]
    return (min(longitudes), min(latitudes), max(longitudes), max(latitudes))


def build_separator_line(
    left_coordinates: Sequence[Coordinate],
    right_coordinates: Sequence[Coordinate],
    bounds: Tuple[float, float, float, float],
) -> Optional[List[Coordinate]]:
    left_centroid = coordinates_centroid(left_coordinates)
    right_centroid = coordinates_centroid(right_coordinates)
    if left_centroid is None or right_centroid is None:
        return None

    vector_x = right_centroid[0] - left_centroid[0]
    vector_y = right_centroid[1] - left_centroid[1]
    if abs(vector_x) < 1e-9 and abs(vector_y) < 1e-9:
        return None

    midpoint = (
        (left_centroid[0] + right_centroid[0]) / 2.0,
        (left_centroid[1] + right_centroid[1]) / 2.0,
    )
    direction = (-vector_y, vector_x)
    intersections = line_rectangle_intersections(midpoint, direction, bounds)
    if len(intersections) < 2:
        return None
    if len(intersections) > 2:
        intersections = sorted(intersections, key=lambda item: distance_squared(item, midpoint))[-2:]
    intersections = sorted(intersections, key=lambda item: (item[0], item[1]))
    return intersections


def coordinates_centroid(coordinates: Sequence[Coordinate]) -> Optional[Coordinate]:
    unique_coordinates = list(dict.fromkeys(coordinates))
    if not unique_coordinates:
        return None
    centroid_lon = sum(point[0] for point in unique_coordinates) / len(unique_coordinates)
    centroid_lat = sum(point[1] for point in unique_coordinates) / len(unique_coordinates)
    return (centroid_lon, centroid_lat)


def line_rectangle_intersections(
    midpoint: Coordinate,
    direction: Coordinate,
    bounds: Tuple[float, float, float, float],
) -> List[Coordinate]:
    min_lon, min_lat, max_lon, max_lat = bounds
    point_x, point_y = midpoint
    direction_x, direction_y = direction
    intersections: List[Coordinate] = []

    if abs(direction_x) > 1e-9:
        for bound_x in (min_lon, max_lon):
            factor = (bound_x - point_x) / direction_x
            y = point_y + factor * direction_y
            if min_lat - 1e-9 <= y <= max_lat + 1e-9:
                intersections.append((bound_x, y))

    if abs(direction_y) > 1e-9:
        for bound_y in (min_lat, max_lat):
            factor = (bound_y - point_y) / direction_y
            x = point_x + factor * direction_x
            if min_lon - 1e-9 <= x <= max_lon + 1e-9:
                intersections.append((x, bound_y))

    unique_points: List[Coordinate] = []
    for candidate in intersections:
        if not any(distance_squared(candidate, existing) < 1e-12 for existing in unique_points):
            unique_points.append(candidate)
    return unique_points


def distance_squared(left: Coordinate, right: Coordinate) -> float:
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def geometry_area(geometry: dict) -> float:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        return sum(abs(ring_signed_area(ring)) for ring in coordinates[:1])
    if geometry_type == "MultiPolygon":
        return sum(sum(abs(ring_signed_area(ring)) for ring in polygon[:1]) for polygon in coordinates)
    return 0.0


def ring_signed_area(ring: Sequence[Sequence[float]]) -> float:
    area = 0.0
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def geometry_bounds(geometry: Optional[dict]) -> Optional[Tuple[float, float, float, float]]:
    if not geometry:
        return None
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    points: List[Coordinate] = []
    if geometry_type == "Polygon":
        for ring in coordinates:
            points.extend((point[0], point[1]) for point in ring)
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                points.extend((point[0], point[1]) for point in ring)
    if not points:
        return None
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return (min(longitudes), min(latitudes), max(longitudes), max(latitudes))


def convex_hull(coordinates: Sequence[Coordinate]) -> List[Coordinate]:
    points = sorted(set(coordinates))
    if len(points) <= 1:
        return list(points)

    def cross(origin: Coordinate, point_a: Coordinate, point_b: Coordinate) -> float:
        return (
            (point_a[0] - origin[0]) * (point_b[1] - origin[1])
            - (point_a[1] - origin[1]) * (point_b[0] - origin[0])
        )

    lower: List[Coordinate] = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: List[Coordinate] = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return lower[:-1] + upper[:-1]


def expand_polygon(coordinates: Sequence[Coordinate], scale: float) -> List[Coordinate]:
    centroid_lon = sum(point[0] for point in coordinates) / len(coordinates)
    centroid_lat = sum(point[1] for point in coordinates) / len(coordinates)
    expanded: List[Coordinate] = []

    for lon, lat in coordinates:
        expanded.append(
            (
                centroid_lon + (lon - centroid_lon) * scale,
                centroid_lat + (lat - centroid_lat) * scale,
            )
        )

    return expanded


def densify_ring(coordinates: Sequence[Coordinate], segments: int) -> List[Coordinate]:
    if len(coordinates) < 3:
        return list(coordinates)

    dense_ring: List[Coordinate] = []
    for index, point in enumerate(coordinates):
        next_point = coordinates[(index + 1) % len(coordinates)]
        dense_ring.append(point)
        for step in range(1, segments):
            ratio = step / segments
            dense_ring.append(
                (
                    point[0] + (next_point[0] - point[0]) * ratio,
                    point[1] + (next_point[1] - point[1]) * ratio,
                )
            )
    return dense_ring


def chaikin_smoothing(coordinates: Sequence[Coordinate], iterations: int) -> List[Coordinate]:
    smoothed = list(coordinates)
    for _ in range(iterations):
        next_ring: List[Coordinate] = []
        for index, point in enumerate(smoothed):
            next_point = smoothed[(index + 1) % len(smoothed)]
            next_ring.append(
                (
                    0.75 * point[0] + 0.25 * next_point[0],
                    0.75 * point[1] + 0.25 * next_point[1],
                )
            )
            next_ring.append(
                (
                    0.25 * point[0] + 0.75 * next_point[0],
                    0.25 * point[1] + 0.75 * next_point[1],
                )
            )
        smoothed = next_ring
    return smoothed


def build_geojson_feature(
    feature_id: str,
    geometry: dict,
    attested_value: str,
    scope: str,
) -> dict:
    is_feature_scope = scope == "feature"
    return {
        "type": "Feature",
        "properties": {
            "feature_id": feature_id,
            "attested_value": attested_value,
            "geometry_type": "polygon",
            "source": "auto",
            "scope": scope,
            "title": "Предварительный ареал вопроса" if is_feature_scope else "Предварительный ареал значения",
            "status_note": (
                "Предварительный ареал построен автоматически по группе точек "
                "и служит только учебной вспомогательной визуализацией."
            ),
        },
        "geometry": geometry,
    }
