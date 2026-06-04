"""
显微镜图像增强器。

开闭原则 (OCP)：通过构造函数注入参数来改变增强行为，
无需修改类代码。两个原始脚本的不同增强参数均可通过配置实现。
"""

import random
import numpy as np
from PIL import Image, ImageFilter
import torchvision.transforms.functional as TF


class MicroscopyAugment:
    """
    模拟显微镜成像效果的图像增强。

    可配置亮度、对比度、Gamma、高斯模糊、椒盐噪声和旋转。
    返回增强后的图像及旋转角度（用于多边形坐标跟随）。
    """

    def __init__(self,
                 # -- 亮度 --
                 brightness_range=(0.8, 1.3),   # 亮度调整因子范围（<1 变暗，>1 变亮）
                 brightness_prob=0.8,            # 亮度调整触发概率 [0,1]
                 # -- 对比度 --
                 contrast_range=(0.8, 1.3),      # 对比度调整因子范围（<1 降低，>1 增强）
                 contrast_prob=0.8,              # 对比度调整触发概率 [0,1]
                 # -- Gamma 校正 --
                 gamma_range=None,               # Gamma 校正范围；None=不启用，如 (0.8, 1.3)
                 gamma_prob=0.5,                 # Gamma 调整触发概率 [0,1]
                 # -- 高斯模糊 --
                 blur_range=(2, 4),             # 模糊半径范围 (min, max)，单位像素
                 blur_prob=1.0,                  # 模糊触发概率 [0,1]
                 # -- 椒盐噪声（毛刺/脉冲噪声）--
                 sp_noise_prob=0.0,             # 椒盐噪声触发概率 [0,1]
                 sp_noise_amount=0.005,          # 噪声像素占比 [0,1]，典型值 0.001~0.02
                 sp_noise_salt_ratio=0.5,        # 盐噪声（白点）占比，余量为胡椒噪声（黑点）
                 # -- 整体色彩扰动（色温/光源变化）--
                 color_jitter_range=None,        # RGB 通道偏移范围，如 (-15, 15)；None=不启用
                 color_jitter_prob=0.5,          # 触发概率 [0,1]
                 # -- 旋转 --
                 rotate_prob=0.0,               # 旋转触发概率 [0,1]
                 rotate_range=(-180, 180),      # 旋转角度范围 (min_deg, max_deg)
                 ):
        """
        配置显微镜成像效果的增强参数。

        Args:
            brightness_range: 亮度调整因子范围（<1 变暗，>1 变亮）
            brightness_prob: 亮度调整触发概率 [0,1]
            contrast_range: 对比度调整因子范围（<1 降低，>1 增强）
            contrast_prob: 对比度调整触发概率 [0,1]
            gamma_range: Gamma 校正范围；None 表示不启用 Gamma 调整
            gamma_prob: Gamma 调整触发概率 [0,1]
            blur_range: 高斯模糊半径范围 (min, max)
            blur_prob: 模糊触发概率 [0,1]
            sp_noise_prob: 椒盐噪声触发概率 [0,1]
            sp_noise_amount: 噪声像素占比 [0,1]，典型值 0.001~0.02
            sp_noise_salt_ratio: 盐（白点）噪声占比，余量为胡椒（黑点）噪声
            rotate_prob: 旋转触发概率 [0,1]
            rotate_range: 旋转角度范围 (min_deg, max_deg)
        """
        self.brightness_range = brightness_range
        self.brightness_prob = brightness_prob
        self.contrast_range = contrast_range
        self.contrast_prob = contrast_prob
        self.gamma_range = gamma_range
        self.gamma_prob = gamma_prob
        self.blur_range = blur_range
        self.blur_prob = blur_prob
        self.sp_noise_prob = sp_noise_prob
        self.sp_noise_amount = sp_noise_amount
        self.sp_noise_salt_ratio = sp_noise_salt_ratio
        self.color_jitter_range = color_jitter_range
        self.color_jitter_prob = color_jitter_prob
        self.rotate_prob = rotate_prob
        self.rotate_range = rotate_range

    def __call__(self, img):
        """
        应用增强。

        Returns:
            (img, angle): 增强后的 PIL 图像和旋转角度（度）
        """
        angle = 0.0

        # 整体色彩扰动（色温/光源变化）—— 在亮度/对比度之前施加
        if self.color_jitter_range is not None and random.random() < self.color_jitter_prob:
            arr = np.array(img, dtype=np.int16)
            for c in range(3):
                shift = random.randint(*self.color_jitter_range)
                arr[:, :, c] = np.clip(arr[:, :, c] + shift, 0, 255)
            img = Image.fromarray(arr.astype(np.uint8))

        if random.random() < self.rotate_prob:
            angle = random.uniform(*self.rotate_range)
            img = TF.rotate(img, angle, expand=False)

        if random.random() < self.brightness_prob:
            img = TF.adjust_brightness(img, random.uniform(*self.brightness_range))

        if random.random() < self.contrast_prob:
            img = TF.adjust_contrast(img, random.uniform(*self.contrast_range))

        if self.gamma_range is not None and random.random() < self.gamma_prob:
            img = TF.adjust_gamma(img, random.uniform(*self.gamma_range))

        if random.random() < self.blur_prob:
            img = img.filter(ImageFilter.GaussianBlur(
                radius=random.uniform(*self.blur_range)))

        if random.random() < self.sp_noise_prob:
            img = self._apply_sp_noise(img)

        return img, angle

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _apply_sp_noise(self, img):
        """
        施加椒盐噪声（毛刺/脉冲噪声）。

        随机选取 sp_noise_amount 比例的像素，按 sp_noise_salt_ratio
        分配为白色（盐）或黑色（胡椒）。
        """
        arr = np.array(img, dtype=np.uint8)
        h, w = arr.shape[:2]
        n_pixels = int(h * w * self.sp_noise_amount)
        if n_pixels == 0:
            return img

        # 随机选取像素位置
        coords = (np.random.randint(0, h, n_pixels),
                  np.random.randint(0, w, n_pixels))

        # 按比例分配盐/胡椒
        n_salt = int(n_pixels * self.sp_noise_salt_ratio)
        salt_mask = np.random.choice(n_pixels, n_salt, replace=False)
        pepper_mask = np.ones(n_pixels, dtype=bool)
        pepper_mask[salt_mask] = False

        # RGB 三通道同时赋值
        arr[coords[0][salt_mask], coords[1][salt_mask]] = 255   # 白点
        arr[coords[0][pepper_mask], coords[1][pepper_mask]] = 0  # 黑点

        from PIL import Image
        return Image.fromarray(arr)
