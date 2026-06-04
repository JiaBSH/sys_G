"""
六边形畴区生成器 — 纯合成数据。

通过随机放置带角度扰动的六边形生成畴区图像。
使用 OverlapController 控制畴区之间的重叠。
"""

import random
import math
import numpy as np
from PIL import Image, ImageDraw

from .base_generator import BaseDomainGenerator
from .overlap_controller import OverlapController


class HexagonGenerator(BaseDomainGenerator):
    """
    合成六边形畴区生成器。

    生成策略：
    1. 以 bg_mean 为均值、bg_noise_std 为标准差生成带噪背景
    2. 随机放置顶点经 shape_jitter 扰动的六边形畴区
    3. 在畴区边缘叠加生长毛刺（边缘细分 + 法向随机游走扰动）
    4. 每个畴区在 color_mean 基础上叠加 color_std 颜色偏差 + texture_std 逐像素纹理
    5. 通过 OverlapController 控制重叠与包含关系
    6. 以 supersample_ratio 倍率超采样渲染后 Lanczos 降采样到目标尺寸

    参数分组：
    - 颜色/纹理: color_mean, bg_mean, color_std, texture_std, bg_noise_std
    - 几何/尺寸: base_r_range, base_num_range, size_std, mag_factor, shape_jitter, orientation_std
    - 边缘毛刺: edge_burr_amplitude, edge_burr_subdivisions
    - 重叠控制: max_overlap_ratio, max_overlap_count, contain_threshold, min_area_factor
    - 渲染:     supersample_ratio
    """

    def __init__(self,
                 # --- 颜色 / 纹理 ---
                 color_mean=(163, 138, 127),   # 畴区颜色的 RGB 均值
                 bg_mean=(153, 115, 85),       # 背景颜色的 RGB 均值
                 color_std=12,                  # 畴区间颜色标准差，越大各畴区色差越大
                 texture_std=8,                 # 畴区内部纹理噪声标准差，越大纹理越粗糙
                 bg_noise_std=3,                # 背景噪声标准差，越大背景越粗糙
                 # --- 几何 / 尺寸 ---
                 base_r_range=(60, 90),         # 基础半径范围 (min, max)，最终半径受 mag_factor、image_scale 和 supersample_ratio 联合缩放
                 base_num_range=(4, 6),         # 基础数量范围 (min, max)，最终数量按 1/(mag_factor²) 缩放
                 size_std=None,                 # 畴区半径的标准差；None=均匀分布，设为数值=正态分布（均值取自 base_r_range 中点）
                 mag_factor=1.0,               # 畴区缩放倍率（>1 放大畴区使其显得"更近"，<1 缩小畴区使其显得"更远"）
                 shape_jitter=0.05,             # 顶点径向扰动比例（0=正六边形，越大形状越不规则）
                 orientation_std=0,            # 畴区取向标准差（度），0=所有畴区同向；值越大取向越随机
                 image_scale=1.0,              # 画布缩放因子，半径 ∝ image_scale；改变画布尺寸时可设为 new_W/ref_W 以保持视觉一致
                 # --- 边缘毛刺（生长粗糙度）---
                 edge_burr_amplitude=0.0,       # 边缘毛刺振幅，相对边长比例；0=光滑边缘，0.05=明显毛刺
                 edge_burr_subdivisions=3,       # 每条边的细分点数（≥2）；越大毛刺越细密
                 # --- 重叠控制 ---
                 max_overlap_ratio=0.2,         # 单个畴区允许的最大重叠比例 [0,1]
                 max_overlap_count=3,           # 单个像素允许被覆盖的最大畴区数
                 contain_threshold=0.85,        # 包含判定阈值；新畴区覆盖某旧畴区超过此比例则拒绝放置
                 min_area_factor=10,           # 最小有效面积因子，实际 min_area = min_area_factor × supersample_ratio
                 # --- 渲染 ---
                 supersample_ratio=1,           # 超采样倍率（抗锯齿，>1 以更高分辨率渲染后降采样）
                 ):
        """
        Args:
            color_mean: 畴区颜色的 RGB 均值，每个畴区在此基础上叠加 color_std 噪声
            bg_mean: 背景颜色的 RGB 均值，每个像素在此基础上叠加 bg_noise_std 噪声
            color_std: 畴区间颜色差异的标准差（RGB 各通道独立采样）
            texture_std: 畴区内部逐像素纹理噪声的标准差
            bg_noise_std: 背景逐像素高斯噪声的标准差
            base_r_range: 未缩放时的畴区半径范围 (min, max)
            base_num_range: 未缩放时的畴区数量范围 (min, max)
            size_std: 畴区半径的标准差；None 时半径在范围内均匀采样，设置后在范围内正态采样
            mag_factor: 畴区缩放倍率；影响半径（线性）和数量（平方反比），不改画布尺寸
            shape_jitter: 顶点径向扰动比例；0 得到正六边形，0.1 产生明显不规则形状
            orientation_std: 畴区取向的标准差（度）；0=所有畴区同向不旋转，值越大取向越随机
            edge_burr_amplitude: 边缘毛刺振幅（相对边长）；0=光滑，0.05=明显毛刺
            edge_burr_subdivisions: 每条边的细分点数（≥2）；越大毛刺越细密
            max_overlap_ratio: 新畴区与已有畴区的最大允许重叠面积比 [0,1]
            max_overlap_count: 任一像素最多允许被多少个畴区覆盖
            contain_threshold: 若新畴区覆盖某旧畴区超过该比例，视为包含并拒绝放置
            min_area_factor: 最小有效面积系数，与 supersample_ratio 相乘得到实际最小面积（像素）
            supersample_ratio: 超采样倍率；内部以 N× 尺寸渲染后 Lanczos 降采样到目标尺寸
        """
        # 颜色 / 纹理
        self.color_mean = color_mean
        self.bg_mean = bg_mean
        self.color_std = color_std
        self.texture_std = texture_std
        self.bg_noise_std = bg_noise_std
        # 几何 / 尺寸
        self.base_r_range = base_r_range
        self.base_num_range = base_num_range
        self.size_std = size_std
        self.mag_factor = mag_factor
        self.shape_jitter = shape_jitter
        self.orientation_std = orientation_std
        self.image_scale = image_scale
        # 边缘毛刺
        self.edge_burr_amplitude = edge_burr_amplitude
        self.edge_burr_subdivisions = edge_burr_subdivisions
        # 重叠控制
        self.max_overlap_ratio = max_overlap_ratio
        self.max_overlap_count = max_overlap_count
        self.contain_threshold = contain_threshold
        self.min_area_factor = min_area_factor
        # 渲染
        self.supersample_ratio = supersample_ratio

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _random_hexagon(self, cx, cy, r):
        """
        生成带扰动的六边形顶点。

        畴区取向从 N(0, orientation_std°) 采样，orientation_std=0 时所有畴区同向。
        每个顶点半径有 ±shape_jitter 的均匀扰动。
        """
        if self.orientation_std > 0:
            start_angle = np.random.normal(0, math.radians(self.orientation_std))
        else:
            start_angle = 0.0

        angles = np.linspace(0, 2 * math.pi, 6, endpoint=False) + start_angle

        poly = []
        for a in angles:
            rr = r * (1 + np.random.uniform(-self.shape_jitter, self.shape_jitter))
            poly.append([
                float(cx + rr * math.cos(a)),
                float(cy + rr * math.sin(a))
            ])
        return poly

    @staticmethod
    def _make_mask(polygon, width, height):
        """从多边形顶点创建布尔掩码。"""
        mask_img = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask_img).polygon(
            [(int(x), int(y)) for x, y in polygon], fill=1
        )
        return np.array(mask_img) == 1

    def _apply_edge_burrs(self, poly):
        """
        在六边形边缘叠加生长毛刺。

        将每条边细分为 edge_burr_subdivisions 段，在内部细分点处
        沿法向施加随机游走扰动。随机游走保证相邻点扰动连续，
        端点处扰动归零以保持顶点位置不变。

        Args:
            poly: 原始多边形顶点列表 [[x, y], ...]

        Returns:
            细分并扰动后的多边形顶点列表
        """
        amp = self.edge_burr_amplitude
        n_sub = self.edge_burr_subdivisions

        if amp <= 0 or n_sub < 2:
            return poly

        n_verts = len(poly)
        result = []

        for i in range(n_verts):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n_verts]

            dx = x2 - x1
            dy = y2 - y1
            edge_len = math.sqrt(dx * dx + dy * dy)

            if edge_len < 1e-6:
                result.append([x1, y1])
                continue

            # 单位法向量（逆时针旋转 90°）
            nx = -dy / edge_len
            ny = dx / edge_len

            # 沿边的随机游走 → 连续且不重复的毛刺形态
            max_disp = amp * edge_len
            steps = np.random.randn(n_sub + 1) * max_disp / math.sqrt(n_sub)
            walk = np.cumsum(steps)
            # 去除线性漂移，确保端点处扰动 → 0
            walk -= np.linspace(walk[0], walk[-1], n_sub + 1)

            # 起始顶点（不扰动）
            result.append([x1, y1])

            # 内部细分点（施加法向扰动）
            for j in range(1, n_sub):
                t = j / n_sub
                x = x1 + t * dx + nx * walk[j]
                y = y1 + t * dy + ny * walk[j]
                result.append([float(x), float(y)])

        return result

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def generate(self, image_size):
        """
        生成一张合成畴区图像。

        Args:
            image_size: (width, height) 目标输出尺寸

        Returns:
            (PIL.Image, list of polygons): 图像为 RGB 模式，
            多边形坐标为输出图像坐标系下的绝对坐标。
        """
        W_orig, H_orig = image_size
        W = W_orig * self.supersample_ratio
        H = H_orig * self.supersample_ratio

        # 根据倍率和画布缩放调整半径和数量
        # 半径 ∝ mag_factor × image_scale（线性）
        # 数量 ∝ 1/mag_factor²（面积反比，与 image_scale 无关——resize 不改变物体数量）
        r_min = int(self.base_r_range[0] * self.mag_factor * self.supersample_ratio * self.image_scale)
        r_max = int(self.base_r_range[1] * self.mag_factor * self.supersample_ratio * self.image_scale)

        count_min = max(1, int(self.base_num_range[0] / (self.mag_factor ** 2)))
        count_max = max(count_min + 1, int(self.base_num_range[1] / (self.mag_factor ** 2)))
        num_domains = (count_min, count_max)

        # 带噪背景
        bg = np.zeros((H, W, 3), dtype=np.uint8)
        for c, m in enumerate(self.bg_mean):
            bg[:, :, c] = np.clip(
                np.random.normal(m, self.bg_noise_std, (H, W)), 0, 255)
        image = Image.fromarray(bg)

        # 重叠控制器（将 HexagonGenerator 参数透传至 OverlapController）
        min_area = self.min_area_factor * self.supersample_ratio
        oc = OverlapController(
            W, H,
            max_overlap_ratio=self.max_overlap_ratio,
            max_overlap_count=self.max_overlap_count,
            contain_threshold=self.contain_threshold,
            min_area=min_area,
        )

        polygons = []
        target_count = random.randint(*num_domains)
        attempts = 0
        max_attempts = target_count * 20

        while len(polygons) < target_count and attempts < max_attempts:
            attempts += 1

            margin = int(r_max)
            cx = random.randint(-margin, W + margin)
            cy = random.randint(-margin, H + margin)

            # 大小分布：size_std=None → 均匀分布；否则正态分布
            if self.size_std is not None:
                r_mean = (r_min + r_max) / 2.0
                r = int(np.clip(np.random.normal(r_mean, self.size_std),
                                r_min, r_max))
            else:
                r = random.randint(r_min, r_max)

            poly = self._random_hexagon(cx, cy, r)
            poly = self._apply_edge_burrs(poly)  # 叠加生长毛刺
            mask_bool = self._make_mask(poly, W, H)

            is_valid, _ = oc.check(mask_bool)
            if not is_valid:
                continue

            # 确认放置
            oc.commit(mask_bool)

            # 绘制畴区颜色（每个畴区有独立的颜色偏差 + 内部纹理噪声）
            domain_color = np.array([
                np.clip(np.random.normal(c, self.color_std), 0, 255)
                for c in self.color_mean
            ], dtype=np.float32)

            img_arr = np.array(image, dtype=np.float32)
            n_pixels = mask_bool.sum()

            for c in range(3):
                # 基础色 + 逐像素纹理噪声
                pixel_noise = np.random.normal(0, self.texture_std, n_pixels).astype(np.float32)
                textured = np.clip(domain_color[c] + pixel_noise, 0, 255)
                img_arr[mask_bool, c] = textured

            image = Image.fromarray(img_arr.astype(np.uint8))

            # 记录多边形（坐标还原到输出尺寸）
            polygons.append([
                [p[0] / self.supersample_ratio, p[1] / self.supersample_ratio]
                for p in poly
            ])

        # 抗锯齿缩放
        final_image = image.resize((W_orig, H_orig), resample=Image.LANCZOS)

        return final_image, polygons
