"""
Copy-Paste 畴区生成器 — 从真实标注数据提取实例并合成新图像。

工作流程：
1. 从真实 JSON+图像对中提取畴区实例（DomainInstance）
2. 以统一主题色重建每个实例的纹理
3. 通过缩放、旋转、形状扰动将实例粘贴到新背景上
4. 使用 OverlapController 控制放置质量
"""

import os
import json
import random
import math
import numpy as np
from PIL import Image, ImageDraw

from .base_generator import BaseDomainGenerator
from .common import rotate_point
from .overlap_controller import OverlapController


# ------------------------------------------------------------------
# 数据类：畴区实例
# ------------------------------------------------------------------

class DomainInstance:
    """从真实图像中提取的畴区实例。"""

    def __init__(self, image, polygon, area, color):
        """
        Args:
            image: RGBA PIL Image（背景透明，Alpha 通道即 mask）
            polygon: 相对坐标下的多边形顶点
            area: 多边形面积
            color: 平均 RGB 颜色
        """
        self.image = image
        self.polygon = polygon
        self.area = area
        self.color = color


# ------------------------------------------------------------------
# 生成器
# ------------------------------------------------------------------

class CopyPasteGenerator(BaseDomainGenerator):
    """
    基于真实数据的 Copy-Paste 生成器。

    从标注数据中提取畴区实例，通过颜色统一化、缩放、旋转、
    形状扰动后随机放置到新背景上。
    """

    def __init__(self, json_dir, img_dir, margin=20,
                 color_std=12, texture_std=10,
                 bg_noise_std=5, max_overlap_ratio=0.3,
                 max_overlap_count=None, min_area=50,
                 size_std=None,
                 num_range=(15, 22), size_scale_range=(0.3, 0.6),
                 shape_jitter=0):
        """
        Args:
            json_dir: 源 JSON 标注目录
            img_dir: 源图像目录
            margin: 边缘剔除边距（像素），靠近图像边缘的实例被丢弃
            color_std: 畴区间颜色标准差（越大畴区间色差越大）
            texture_std: 畴区内部纹理噪声标准差（越大纹理越粗糙）
            bg_noise_std: 背景噪声标准差（越大背景越粗糙）
            max_overlap_ratio: 单个畴区允许的最大重叠比例 (0~1)
            max_overlap_count: 单个像素允许的最大重叠次数（None 则不限制）
            min_area: 畴区最小有效面积（像素）
            size_std: 畴区缩放的标准差。None=均匀分布；设置后为正态分布
            num_range: 每张图畴区数量范围 (min, max)
            size_scale_range: 实例缩放范围 (min, max)
            shape_jitter: 顶点形状扰动的高斯噪声标准差（0 则不扰动）
        """
        self.color_std = color_std
        self.texture_std = texture_std
        self.bg_noise_std = bg_noise_std
        self.max_overlap_ratio = max_overlap_ratio
        self.max_overlap_count = max_overlap_count
        self.min_area = min_area
        self.size_std = size_std
        self.num_range = num_range
        self.size_scale_range = size_scale_range
        self.shape_jitter = shape_jitter
        self.instances, self.bg_mean = self._extract_instances(
            json_dir, img_dir, margin
        )

    # ------------------------------------------------------------------
    # 实例提取（私有）
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_instances(json_dir, img_dir, margin=20):
        """
        从标注数据中提取畴区实例。

        处理流程：
        1. 遍历 JSON 文件，匹配对应图像
        2. 对每个标注对象：裁剪、生成 mask、计算平均颜色
        3. 过滤边缘截断的物体
        4. 2-Sigma 颜色异常过滤

        Returns:
            (instances, global_bg): 实例列表和全局背景色均值
        """
        instances = []
        instance_colors = []
        bg_colors = []

        if not os.path.exists(json_dir):
            print(f"Error: JSON directory not found: {json_dir}")
            return [], [155, 115, 85]

        json_files = [f for f in os.listdir(json_dir) if f.lower().endswith('.json')]

        filtered_edge_count = 0

        for j_file in json_files:
            try:
                with open(os.path.join(json_dir, j_file), 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)

                target_name = os.path.splitext(j_file)[0]
                img_path = None
                for ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tif']:
                    temp_path = os.path.join(img_dir, target_name + ext)
                    if os.path.exists(temp_path):
                        img_path = temp_path
                        break

                if not img_path:
                    continue

                full_img = Image.open(img_path).convert("RGBA")
                W, H = full_img.size
                full_img_np = np.array(full_img)
                bg_mask = np.ones((H, W), dtype=bool)

                for obj in data.get('objects', []):
                    poly = obj.get('segmentation', [])
                    if len(poly) < 3:
                        continue

                    min_x, min_y = int(min(p[0] for p in poly)), int(min(p[1] for p in poly))
                    max_x, max_y = int(max(p[0] for p in poly)) + 1, int(max(p[1] for p in poly)) + 1

                    # 边缘检查
                    if (min_x < margin or min_y < margin or
                            max_x > W - margin or max_y > H - margin):
                        filtered_edge_count += 1
                        continue

                    min_x = max(0, min_x)
                    min_y = max(0, min_y)
                    max_x = min(W, max_x)
                    max_y = min(H, max_y)

                    if max_x - min_x < 5 or max_y - min_y < 5:
                        continue

                    # 裁剪
                    patch = full_img.crop((min_x, min_y, max_x, max_y))
                    rel_poly = [[p[0] - min_x, p[1] - min_y] for p in poly]

                    # 生成 mask
                    mask = Image.new("L", patch.size, 0)
                    ImageDraw.Draw(mask).polygon(
                        [(x, y) for x, y in rel_poly], fill=255
                    )

                    patch_arr = np.array(patch)
                    mask_arr = np.array(mask)

                    # 计算平均颜色
                    valid_pixels = patch_arr[mask_arr > 0]
                    if len(valid_pixels) == 0:
                        continue
                    mean_color = np.mean(valid_pixels[:, :3], axis=0)

                    # 保存实例（用 mask 更新 Alpha 通道）
                    patch_arr[:, :, 3] = mask_arr
                    final_patch = Image.fromarray(patch_arr)

                    instances.append(
                        DomainInstance(final_patch, rel_poly,
                                       obj.get('area', 0), mean_color)
                    )
                    instance_colors.append(mean_color)

                    bg_mask[min_y:max_y, min_x:max_x] = False

                # 统计背景
                bg_pixels = full_img_np[bg_mask]
                if len(bg_pixels) > 0:
                    bg_colors.append(np.mean(bg_pixels[:, :3], axis=0))

            except Exception as e:
                print(f"[Warning] Error in {j_file}: {e}")

        # 2-Sigma 异常颜色过滤
        filtered_outlier_count = 0
        if len(instances) > 5:
            colors_np = np.array(instance_colors)
            global_mean = np.mean(colors_np, axis=0)
            dists = np.linalg.norm(colors_np - global_mean, axis=1)
            threshold = np.mean(dists) + 2 * np.std(dists)

            valid_instances = []
            for i, dist in enumerate(dists):
                if dist <= threshold:
                    valid_instances.append(instances[i])
                else:
                    filtered_outlier_count += 1
            instances = valid_instances

        global_bg = np.mean(bg_colors, axis=0) if bg_colors else [155, 115, 85]

        print(f"[Init] Extracted {len(instances)} valid instances.")
        print(f"       - Filtered {filtered_edge_count} edge objects.")
        print(f"       - Filtered {filtered_outlier_count} color outliers.")

        return instances, global_bg

    # ------------------------------------------------------------------
    # 单张生成（私有核心逻辑）
    # ------------------------------------------------------------------

    def _generate_one(self, image_size):
        """生成单张 copy-paste 图像。"""
        W, H = image_size

        # 带噪背景
        bg_array = np.zeros((H, W, 3), dtype=np.uint8)
        for c in range(3):
            noise = np.random.normal(self.bg_mean[c], self.bg_noise_std, (H, W))
            bg_array[:, :, c] = np.clip(noise, 0, 255)
        image = Image.fromarray(bg_array).convert("RGBA")

        # 基准主题色：从素材库中随机选取（作为全图色调参考）
        if self.instances:
            base_theme_color = np.array(random.choice(self.instances).color,
                                        dtype=np.float32)
        else:
            base_theme_color = np.array([120, 120, 120], dtype=np.float32)

        # 重叠控制器
        oc = OverlapController(
            W, H,
            max_overlap_ratio=self.max_overlap_ratio,
            max_overlap_count=self.max_overlap_count,
            min_area=self.min_area
        )

        final_polygons = []
        target_count = random.randint(*self.num_range)
        attempts = 0

        while len(final_polygons) < target_count and attempts < target_count * 20:
            attempts += 1
            if not self.instances:
                break

            inst = random.choice(self.instances)

            # ---- 1. 颜色重建：每实例独立色偏 + 内部纹理 ----
            instance_color = np.array([
                np.clip(np.random.normal(c, self.color_std), 0, 255)
                for c in base_theme_color
            ], dtype=np.float32)

            mask_img = inst.image.split()[3]
            H_patch, W_patch = inst.image.height, inst.image.width

            # 基础色 + 逐像素纹理噪声
            patch_arr = np.zeros((H_patch, W_patch, 3), dtype=np.float32)
            for c in range(3):
                pixel_noise = np.random.normal(0, self.texture_std, (H_patch, W_patch))
                patch_arr[:, :, c] = np.clip(instance_color[c] + pixel_noise, 0, 255)
            patch_arr = patch_arr.astype(np.uint8)

            patch_colored = Image.fromarray(patch_arr).convert("RGBA")
            patch_colored.putalpha(mask_img)

            # ---- 2. 缩放 ----
            if isinstance(self.size_scale_range, (tuple, list)) and len(self.size_scale_range) == 2:
                s_min, s_max = self.size_scale_range
                # 大小分布：size_std=None → 均匀分布；否则正态分布
                if self.size_std is not None:
                    s_mean = (s_min + s_max) / 2.0
                    scale = float(np.clip(
                        np.random.normal(s_mean, self.size_std), s_min, s_max))
                else:
                    scale = random.uniform(s_min, s_max)
            else:
                try:
                    scale = float(self.size_scale_range)
                except (TypeError, ValueError):
                    scale = 1.0

            if abs(scale - 1.0) > 1e-6:
                new_w = max(1, int(patch_colored.width * scale))
                new_h = max(1, int(patch_colored.height * scale))
                patch_scaled = patch_colored.resize((new_w, new_h), resample=Image.BICUBIC)
                scaled_polygon = [[p[0] * scale, p[1] * scale] for p in inst.polygon]
            else:
                patch_scaled = patch_colored
                scaled_polygon = [p[:] for p in inst.polygon]

            # ---- 3. 旋转（小幅，0~5°）----
            angle = random.uniform(0, 5)
            patch_rot = patch_scaled.rotate(angle, resample=Image.BICUBIC, expand=True)

            cx_old = patch_scaled.width / 2
            cy_old = patch_scaled.height / 2
            cx_new = patch_rot.width / 2
            cy_new = patch_rot.height / 2
            rad = math.radians(-angle)

            # ---- 4. 形状扰动 ----
            if self.shape_jitter and self.shape_jitter > 1e-6:
                jittered_polygon = []
                for x, y in scaled_polygon:
                    jx = x + random.gauss(0, self.shape_jitter)
                    jy = y + random.gauss(0, self.shape_jitter)
                    jittered_polygon.append([jx, jy])
            else:
                jittered_polygon = scaled_polygon

            # 旋转多边形顶点
            new_poly_rel = []
            for p in jittered_polygon:
                pr = rotate_point(p, rad, cx_old, cy_old)
                pr[0] += (cx_new - cx_old)
                pr[1] += (cy_new - cy_old)
                new_poly_rel.append(pr)

            # ---- 5. 随机放置 ----
            paste_x = random.randint(-int(patch_rot.width / 2),
                                     W - int(patch_rot.width / 2))
            paste_y = random.randint(-int(patch_rot.height / 2),
                                     H - int(patch_rot.height / 2))

            abs_poly = [[x + paste_x, y + paste_y] for x, y in new_poly_rel]

            # 创建掩码并检查重叠
            try:
                temp_mask = Image.new("L", (W, H), 0)
                draw_poly = [(int(x), int(y)) for x, y in abs_poly]
                ImageDraw.Draw(temp_mask).polygon(draw_poly, fill=1)
            except Exception:
                continue

            mask_bool = np.array(temp_mask) == 1
            is_valid, _ = oc.check(mask_bool)
            if not is_valid:
                continue

            # ---- 6. 确认放置 ----
            oc.commit(mask_bool)
            image.paste(patch_rot, (paste_x, paste_y), patch_rot)
            final_polygons.append(abs_poly)

        return image.convert("RGB"), final_polygons

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def generate(self, image_size):
        """
        生成一张 copy-paste 畴区图像。

        Args:
            image_size: (width, height) 目标图像尺寸

        Returns:
            (PIL.Image, list of polygons)
        """
        return self._generate_one(image_size)
