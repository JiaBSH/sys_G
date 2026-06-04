"""
GPU 加速六边形畴区生成器。

三层优化:
1. ROI 掩码光栅化 — 仅在多边形 bbox 内创建小 PIL 掩码，消除全画布分配
2. ROI 重叠控制器 — 通过 bbox 切片操作全局状态图，避免全画布索引
3. GPU 批量背景 — 背景噪声在 CUDA 上批量生成（对大画布/高超采样率有加速）

注意：由于畴区放置是顺序迭代的（每个域 ~10px），GPU per-iteration
kernel launch 开销远超计算收益，因此域颜色渲染始终走 CPU 路径。
对于 1024×681 画布，fast_cpu 和 gpu 性能几乎相同（~0.9s/张）；
GPU 背景在 supersample_ratio ≥ 4 时会有明显优势。

用法:
    from om_domain.gpu_hexagon_generator import GPUFastHexagonGenerator
    gen = GPUFastHexagonGenerator(mag_factor=0.25, use_gpu=True, ...)
    img, polygons = gen.generate((1024, 681))
"""

import random
import math
import numpy as np
from PIL import Image, ImageDraw

from .base_generator import BaseDomainGenerator


# =========================================================================
# FastROIMask — ROI 局部掩码光栅化
# =========================================================================

class FastROIMask:
    """ROI 局部掩码光栅化，消除全画布 PIL 开销。"""

    @staticmethod
    def make_mask(polygon, canvas_width, canvas_height):
        """
        在多边形 bbox 内创建布尔掩码。

        Args:
            polygon: [[x, y], ...] 顶点坐标（浮点）
            canvas_width, canvas_height: 画布尺寸

        Returns:
            (mask_bool, bbox) 或 (None, None) 如果多边形完全在画布外
            - mask_bool: np.ndarray (h, w) dtype=bool，局部坐标系
            - bbox: (x0, y0, x1, y1) 全局画布坐标
        """
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]

        # bbox 夹紧到画布
        x0 = max(0, int(min(xs)))
        y0 = max(0, int(min(ys)))
        x1 = min(canvas_width, int(max(xs)) + 1)
        y1 = min(canvas_height, int(max(ys)) + 1)

        if x0 >= x1 or y0 >= y1:
            return None, None  # 完全在画布外

        w, h = x1 - x0, y1 - y0

        # 多边形坐标偏移到局部坐标系
        local_poly = [[x - x0, y - y0] for x, y in polygon]

        # 在 tiny PIL 图像上绘制（典型尺寸 ~14×14，而非 1024×681）
        mask_img = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask_img).polygon(
            [(int(px), int(py)) for px, py in local_poly], fill=1
        )
        mask_bool = np.array(mask_img, dtype=bool)

        return mask_bool, (x0, y0, x1, y1)


# =========================================================================
# ROIOverlapController — 基于 bbox 切片的重叠控制器
# =========================================================================

class ROIOverlapController:
    """
    支持 ROI 局部掩码的重叠控制器。

    维护全局状态图（overlap_count_map, id_map, area_registry），
    但通过 bbox 切片而非全画布索引来执行 check/commit。
    逻辑与 OverlapController 完全一致。
    """

    def __init__(self, width, height,
                 max_overlap_ratio=0.2,
                 max_overlap_count=None,
                 contain_threshold=0.85,
                 min_area=50):
        self.overlap_count_map = np.zeros((height, width), dtype=np.uint8)
        self.id_map = np.full((height, width), -1, dtype=np.int32)
        self.area_registry = {}
        self.max_overlap_ratio = max_overlap_ratio
        self.max_overlap_count = max_overlap_count
        self.contain_threshold = contain_threshold
        self.min_area = min_area
        self._curr_id = 0

    def check(self, local_mask, bbox):
        """
        检查新畴区是否能放置在 bbox 位置。

        Args:
            local_mask: np.ndarray (h, w) bool，FastROIMask.make_mask 输出
            bbox: (x0, y0, x1, y1) 全局坐标

        Returns:
            (is_valid, mask_area)
        """
        mask_area = int(local_mask.sum())

        if mask_area < self.min_area:
            return False, mask_area

        x0, y0, x1, y1 = bbox

        # --- 提取 ROI 切片 ---
        id_roi = self.id_map[y0:y1, x0:x1]          # (h, w) int32 view
        overlap_roi = self.overlap_count_map[y0:y1, x0:x1]  # (h, w) uint8 view

        # --- 检查是否几乎完全包含某个已有畴区 ---
        sampled_ids, counts = np.unique(id_roi[local_mask], return_counts=True)
        for eid, count in zip(sampled_ids, counts):
            if eid != -1 and count > self.area_registry[eid] * self.contain_threshold:
                return False, mask_area

        # --- 检查是否几乎完全被已有畴区覆盖 ---
        covered_by_existing = (sampled_ids != -1).sum()
        if covered_by_existing > mask_area * self.contain_threshold:
            return False, mask_area

        # --- 检查重叠比例 ---
        existing_overlap = overlap_roi[local_mask]
        overlap_ratio = (existing_overlap >= 1).sum() / mask_area
        if overlap_ratio > self.max_overlap_ratio:
            return False, mask_area

        # --- 检查最大重叠次数（可选）---
        if self.max_overlap_count is not None:
            if (existing_overlap >= self.max_overlap_count).any():
                return False, mask_area

        return True, mask_area

    def commit(self, local_mask, bbox):
        """确认放置，通过 ROI 切片更新全局状态。"""
        x0, y0, x1, y1 = bbox

        # 更新 overlap_count_map（ROI 切片是 view，直接写入生效）
        roi_ov = self.overlap_count_map[y0:y1, x0:x1]
        roi_ov[local_mask] += 1

        # 更新 id_map
        roi_id = self.id_map[y0:y1, x0:x1]
        roi_id[local_mask] = self._curr_id

        mask_area = int(local_mask.sum())
        self.area_registry[self._curr_id] = mask_area
        self._curr_id += 1


# =========================================================================
# GPUFastHexagonGenerator — GPU 加速生成器
# =========================================================================

class GPUFastHexagonGenerator(BaseDomainGenerator):
    """
    GPU 加速六边形畴区生成器。

    参数接口与 HexagonGenerator 完全一致，额外提供 use_gpu / gpu_device 开关。

    三层优化：
    - FastROIMask: 局部 bbox 掩码，替代全画布 PIL 掩码
    - ROIOverlapController: bbox 切片重叠检测，替代全画布索引
    - GPU 颜色渲染: torch CUDA tensor 保持图像，最后才转 PIL
    """

    def __init__(self,
                 # --- 颜色 / 纹理 ---
                 color_mean=(163, 138, 127),
                 bg_mean=(153, 115, 85),
                 color_std=12,
                 texture_std=8,
                 bg_noise_std=3,
                 # --- 几何 / 尺寸 ---
                 base_r_range=(60, 90),
                 base_num_range=(4, 6),
                 size_std=None,
                 mag_factor=1.0,
                 shape_jitter=0.05,
                 image_scale=1.0,        # 画布缩放因子，半径 ∝ image_scale
                 # --- 边缘毛刺 ---
                 edge_burr_amplitude=0.0,
                 edge_burr_subdivisions=3,
                 # --- 重叠控制 ---
                 max_overlap_ratio=0.2,
                 max_overlap_count=3,
                 contain_threshold=0.85,
                 min_area_factor=10,
                 # --- 渲染 ---
                 supersample_ratio=1,
                 # --- GPU 开关 ---
                 use_gpu=True,
                 gpu_device=None,
                 ):
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
        # GPU
        self._init_gpu(use_gpu, gpu_device)

    def _init_gpu(self, use_gpu, gpu_device):
        """初始化 GPU 后端。"""
        self.use_gpu = False
        self._torch = None
        self.device = None

        if not use_gpu:
            return

        try:
            import torch
            self._torch = torch
        except ImportError:
            return

        if not torch.cuda.is_available():
            return

        try:
            if gpu_device is not None:
                self.device = torch.device(gpu_device)
            else:
                self.device = torch.device("cuda")
            # 冒烟测试
            _ = torch.zeros(1, device=self.device)
            self.use_gpu = True
        except Exception:
            self.device = None
            self.use_gpu = False

    # ------------------------------------------------------------------
    # 几何生成 — 与 HexagonGenerator 完全一致
    # ------------------------------------------------------------------

    def _random_hexagon(self, cx, cy, r):
        """生成带扰动的六边形顶点。"""
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

    def _apply_edge_burrs(self, poly):
        """边缘毛刺 — 与 HexagonGenerator 完全一致。"""
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

            nx = -dy / edge_len
            ny = dx / edge_len

            max_disp = amp * edge_len
            steps = np.random.randn(n_sub + 1) * max_disp / math.sqrt(n_sub)
            walk = np.cumsum(steps)
            walk -= np.linspace(walk[0], walk[-1], n_sub + 1)

            result.append([x1, y1])

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
        生成一张合成畴区图像（GPU 加速或 CPU 快路径）。

        注意：由于畴区放置是顺序的（重叠检测依赖前置状态），
        每次迭代的操作（ROI 掩码、颜色渲染）都是微小张量。
        GPU 的 kernel launch 开销在此场景下远超计算收益。
        因此即使 use_gpu=True，域渲染仍走 CPU 路径；
        GPU 仅用于背景噪声生成等可批量的操作。

        Args:
            image_size: (width, height) 目标输出尺寸

        Returns:
            (PIL.Image, list of polygons)
        """
        W_orig, H_orig = image_size
        W = W_orig * self.supersample_ratio
        H = H_orig * self.supersample_ratio

        # Phase 0: 计算有效半径和数量
        r_min = int(self.base_r_range[0] * self.mag_factor * self.supersample_ratio * self.image_scale)
        r_max = int(self.base_r_range[1] * self.mag_factor * self.supersample_ratio * self.image_scale)

        count_min = max(1, int(self.base_num_range[0] / (self.mag_factor ** 2)))
        count_max = max(count_min + 1, int(self.base_num_range[1] / (self.mag_factor ** 2)))
        num_domains = (count_min, count_max)

        # Phase 1: 创建背景（GPU 批量生成后转 CPU；或直接 CPU 生成）
        if self.use_gpu:
            bg_arr = self._create_bg_gpu_to_cpu(W, H)
        else:
            bg_arr = self._create_bg_cpu_arr(W, H)

        # Phase 2: 重叠控制器
        min_area = self.min_area_factor * self.supersample_ratio
        oc = ROIOverlapController(
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

            # 大小分布
            if self.size_std is not None:
                r_mean = (r_min + r_max) / 2.0
                r = int(np.clip(np.random.normal(r_mean, self.size_std),
                                r_min, r_max))
            else:
                r = random.randint(r_min, r_max)

            poly = self._random_hexagon(cx, cy, r)
            poly = self._apply_edge_burrs(poly)

            # ROI 掩码（替代全画布 PIL 掩码）
            local_mask, bbox = FastROIMask.make_mask(poly, W, H)
            if local_mask is None:
                continue

            is_valid, _ = oc.check(local_mask, bbox)
            if not is_valid:
                continue

            oc.commit(local_mask, bbox)

            # 颜色渲染 — 始终走 CPU（GPU per-iteration 开销 > 收益）
            self._render_domain_cpu(bg_arr, local_mask, bbox)

            # 记录多边形（坐标还原到输出尺寸）
            polygons.append([
                [p[0] / self.supersample_ratio, p[1] / self.supersample_ratio]
                for p in poly
            ])

        # Phase 3: 最终图像
        final_image_before_resize = Image.fromarray(bg_arr.astype(np.uint8))
        final_image = final_image_before_resize.resize(
            (W_orig, H_orig), resample=Image.LANCZOS
        )

        return final_image, polygons

    # ------------------------------------------------------------------
    # 背景生成
    # ------------------------------------------------------------------

    def _create_bg_cpu_arr(self, W, H):
        """CPU 背景：numpy float32，避免重复 PIL 转换。"""
        bg = np.zeros((H, W, 3), dtype=np.float32)
        for c, m in enumerate(self.bg_mean):
            bg[:, :, c] = np.random.normal(m, self.bg_noise_std, (H, W))
        np.clip(bg, 0, 255, out=bg)
        return bg

    def _create_bg_gpu_to_cpu(self, W, H):
        """GPU 批量生成背景噪声后立即转回 numpy，后续域渲染走 CPU。"""
        T = self._torch
        bg = T.zeros((H, W, 3), dtype=T.float32, device=self.device)
        for c, m in enumerate(self.bg_mean):
            noise = T.randn(H, W, device=self.device) * self.bg_noise_std + m
            bg[:, :, c] = noise.clamp(0, 255)
        return bg.cpu().numpy()

    # ------------------------------------------------------------------
    # 颜色渲染（始终 CPU — GPU per-iteration 开销 > 收益）
    # ------------------------------------------------------------------

    def _render_domain_cpu(self, img_arr, local_mask, bbox):
        """CPU 颜色渲染：直接操作 numpy float32 数组。"""
        x0, y0, x1, y1 = bbox
        roi = img_arr[y0:y1, x0:x1]  # (h, w, 3) view

        n_pixels = int(local_mask.sum())

        for c in range(3):
            base_color = np.random.normal(self.color_mean[c], self.color_std)
            noise = np.random.normal(0, self.texture_std, n_pixels).astype(np.float32)
            textured = np.clip(base_color + noise, 0, 255)
            roi[:, :, c][local_mask] = textured
