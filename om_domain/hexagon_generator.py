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

    生成策略：在带噪背景上随机放置有角度扰动的六边形畴区，
    通过 OverlapController 控制重叠和包含关系。
    支持超采样抗锯齿和放大倍率调节。
    """

    def __init__(self, base_r_range=(60, 90), base_num_range=(4, 6),
                 color_mean=(163, 138, 127), bg_mean=(153, 115, 85),
                 color_std=12, texture_std=8,
                 bg_noise_std=3, max_overlap_ratio=0.2, max_overlap_count=3,
                 size_std=None, mag_factor=1.0, supersample_ratio=1,
                 shape_jitter=0.05):
        """
        Args:
            base_r_range: 基础半径范围 (min, max)
            base_num_range: 基础数量范围 (min, max)
            color_mean: 畴区颜色的 RGB 均值
            bg_mean: 背景颜色的 RGB 均值
            color_std: 畴区间颜色标准差（越大畴区间色差越大）
            texture_std: 畴区内部纹理噪声标准差（越大纹理越粗糙）
            bg_noise_std: 背景噪声标准差（越大背景越粗糙）
            max_overlap_ratio: 单个畴区允许的最大重叠比例 (0~1)
            max_overlap_count: 单个像素允许的最大重叠次数
            size_std: 畴区大小的标准差。None=均匀分布；设置后为正态分布
            mag_factor: 放大倍率（>1 放大畴区，<1 缩小畴区）
            supersample_ratio: 超采样倍率（用于抗锯齿）
            shape_jitter: 顶点径向扰动比例（0=正六边形，越大形状越不规则）
        """
        self.base_r_range = base_r_range
        self.base_num_range = base_num_range
        self.color_mean = color_mean
        self.bg_mean = bg_mean
        self.color_std = color_std
        self.texture_std = texture_std
        self.bg_noise_std = bg_noise_std
        self.max_overlap_ratio = max_overlap_ratio
        self.max_overlap_count = max_overlap_count
        self.size_std = size_std
        self.mag_factor = mag_factor
        self.supersample_ratio = supersample_ratio
        self.shape_jitter = shape_jitter

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _random_hexagon(self, cx, cy, r):
        """
        生成带扰动的六边形顶点。

        95% 概率取向接近 0°（正态分布 std=1°），
        5% 概率取向有更大随机性（std=15°）。
        每个顶点半径有 ±shape_jitter 的均匀扰动。
        """
        if random.random() < 0.95:
            start_angle = np.random.normal(0, math.radians(1))
        else:
            start_angle = np.random.normal(0, math.radians(15))

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

        # 根据倍率调整半径和数量
        r_min = int(self.base_r_range[0] * self.mag_factor * self.supersample_ratio)
        r_max = int(self.base_r_range[1] * self.mag_factor * self.supersample_ratio)

        avg_num = (self.base_num_range[0] + self.base_num_range[1]) / 2
        count_scaled = max(2, int(avg_num / (self.mag_factor ** 2)))
        num_domains = (max(1, count_scaled - 2), count_scaled + 2)

        # 带噪背景
        bg = np.zeros((H, W, 3), dtype=np.uint8)
        for c, m in enumerate(self.bg_mean):
            bg[:, :, c] = np.clip(
                np.random.normal(m, self.bg_noise_std, (H, W)), 0, 255)
        image = Image.fromarray(bg)

        # 重叠控制器
        min_area = 10 * self.supersample_ratio
        oc = OverlapController(
            W, H,
            max_overlap_ratio=self.max_overlap_ratio,
            max_overlap_count=self.max_overlap_count,
            min_area=min_area
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
