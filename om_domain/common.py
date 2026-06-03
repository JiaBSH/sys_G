"""
共享工具函数 — 多边形几何处理与坐标变换。

单一职责：纯几何计算，不涉及图像 I/O 或业务逻辑。
"""

import math
from shapely.geometry import Polygon, box


def refine_polygons(polygons, width, height):
    """
    处理越界多边形，确保在图像边界处共线截断。

    对于完全在图像内的多边形直接保留；对于越界的多边形，
    使用 shapely 计算与图像边界的交集，生成裁剪后的顶点。

    Args:
        polygons: 多边形顶点列表 [[x, y], ...]
        width: 图像宽度
        height: 图像高度

    Returns:
        裁剪后的有效多边形列表（每个至少 3 个顶点）
    """
    refined_polygons = []
    img_boundary = box(0, 0, width, height)

    for poly_coords in polygons:
        if len(poly_coords) < 3:
            continue

        is_outside = any(
            x < 0 or x > width or y < 0 or y > height for x, y in poly_coords
        )

        if not is_outside:
            refined_polygons.append(poly_coords)
        else:
            try:
                poly_shape = Polygon(poly_coords)
                if not poly_shape.is_valid:
                    poly_shape = poly_shape.buffer(0)
                intersected = poly_shape.intersection(img_boundary)

                if intersected.geom_type == 'Polygon':
                    coords = list(intersected.exterior.coords)[:-1]
                    if len(coords) >= 3:
                        refined_polygons.append(coords)
                elif intersected.geom_type == 'MultiPolygon':
                    for p in intersected.geoms:
                        coords = list(p.exterior.coords)[:-1]
                        if len(coords) >= 3:
                            refined_polygons.append(coords)
            except Exception:
                continue

    return refined_polygons


def polygon_to_bbox(poly):
    """多边形转轴对齐边界框 [x_min, y_min, x_max, y_max]"""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def rotate_point(point, angle_rad, cx, cy):
    """绕点 (cx, cy) 旋转单个点（弧度）"""
    x, y = point
    x0 = x - cx
    y0 = y - cy
    xr = x0 * math.cos(angle_rad) - y0 * math.sin(angle_rad) + cx
    yr = x0 * math.sin(angle_rad) + y0 * math.cos(angle_rad) + cy
    return [xr, yr]


def rotate_polygon(poly, angle_deg, cx, cy):
    """绕点 (cx, cy) 旋转多边形（角度）"""
    rad = math.radians(angle_deg)
    return [rotate_point(p, rad, cx, cy) for p in poly]
