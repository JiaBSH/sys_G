"""
数据集生成流水线。

依赖倒置原则 (DIP)：依赖 BaseDomainGenerator 抽象，
而非具体生成器。可与任何实现了 generate(image_size) 的生成器协作。

单一职责：编排 Generator → Augment → Refine → Save 流程。
"""

import os
from .common import refine_polygons, rotate_polygon
from .augment import MicroscopyAugment
from .saver import ISATSaver


class DatasetPipeline:
    """
    数据集生成流水线。

    组合以下组件完成批量生成：
    - generator:  畴区生成器（BaseDomainGenerator 的子类）
    - augmenter:  图像增强器（MicroscopyAugment 或自定义 callable）
    - saver:      保存器（ISATSaver 或自定义）
    """

    def __init__(self, generator, augmenter=None, saver=None):
        """
        Args:
            generator: BaseDomainGenerator 实例
            augmenter: callable，接受 PIL Image 返回 (Image, angle)；
                       默认为 MicroscopyAugment()
            saver: ISATSaver 实例；默认为 ISATSaver()
        """
        self.generator = generator
        self.augmenter = augmenter if augmenter is not None else MicroscopyAugment()
        self.saver = saver if saver is not None else ISATSaver()

    def run(self, output_root, n, name_prefix="syn",
            image_size=(1024, 1024)):
        """
        批量生成数据集。

        Args:
            output_root: 输出根目录（自动创建 image/ 和 label/ 子目录）
            n: 生成数量
            name_prefix: 文件名前缀
            image_size: 图像尺寸 (width, height)

        Returns:
            count: 成功生成的样本数
        """
        img_dir = os.path.join(output_root, "image")
        lab_dir = os.path.join(output_root, "label")
        os.makedirs(img_dir, exist_ok=True)
        os.makedirs(lab_dir, exist_ok=True)

        print(f"[Start] Generating {n} images...")

        generated = 0
        while generated < n:
            # 1. 生成
            img, polygons = self.generator.generate(image_size)

            # 2. 增强
            img, angle = self.augmenter(img)

            # 3. 旋转坐标跟随
            if abs(angle) > 1e-6:
                cx, cy = img.width / 2, img.height / 2
                polygons = [
                    rotate_polygon(poly, -angle, cx, cy)
                    for poly in polygons
                ]

            # 4. 边界截断
            final_polygons = refine_polygons(polygons, img.width, img.height)
            valid_polygons = [p for p in final_polygons if len(p) >= 3]

            if not valid_polygons:
                continue  # 跳过空样本

            # 5. 保存
            name = f"{name_prefix}_{generated:05d}"
            self.saver.save(
                img, valid_polygons,
                os.path.join(img_dir, name + ".png"),
                os.path.join(lab_dir, name + ".json")
            )

            generated += 1

            if generated % 50 == 0:
                print(f"[Progress] {generated}/{n}")

        print(f"[Done] Generated {generated} samples in {output_root}")
        return generated
