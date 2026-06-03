"""
显微镜图像增强器。

开闭原则 (OCP)：通过构造函数注入参数来改变增强行为，
无需修改类代码。两个原始脚本的不同增强参数均可通过配置实现。
"""

import random
from PIL import ImageFilter
import torchvision.transforms.functional as TF


class MicroscopyAugment:
    """
    模拟显微镜成像效果的图像增强。

    可配置亮度、对比度、Gamma、高斯模糊和旋转。
    返回增强后的图像及旋转角度（用于多边形坐标跟随）。
    """

    def __init__(self,
                 brightness_range=(0.8, 1.3),
                 brightness_prob=0.8,
                 contrast_range=(0.8, 1.3),
                 contrast_prob=0.8,
                 gamma_range=None,
                 gamma_prob=0.5,
                 blur_range=(2, 4),
                 blur_prob=1.0,
                 rotate_prob=0.0,
                 rotate_range=(-180, 180)):
        """
        Args:
            brightness_range: 亮度调整范围 (min, max)
            brightness_prob: 亮度调整触发概率 [0, 1]
            contrast_range: 对比度调整范围 (min, max)
            contrast_prob: 对比度调整触发概率 [0, 1]
            gamma_range: Gamma 调整范围，None 则不启用
            gamma_prob: Gamma 调整触发概率 [0, 1]
            blur_range: 高斯模糊半径范围 (min, max)
            blur_prob: 应用模糊的概率 [0, 1]
            rotate_prob: 应用旋转的概率 [0, 1]
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
        self.rotate_prob = rotate_prob
        self.rotate_range = rotate_range

    def __call__(self, img):
        """
        应用增强。

        Returns:
            (img, angle): 增强后的 PIL 图像和旋转角度（度）
        """
        angle = 0.0

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

        return img, angle
