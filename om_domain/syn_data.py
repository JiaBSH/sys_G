"""
合成畴区数据集生成 — 入口脚本。

使用六边形生成器在带噪背景上随机放置畴区。
可通过 python -m om_domain.syn_data 运行。
"""

from om_domain.pipeline import DatasetPipeline
from om_domain.hexagon_generator import HexagonGenerator
from om_domain.augment import MicroscopyAugment


def main():
    # ---- 生成器配置 ----
    generator = HexagonGenerator(
        base_r_range=(60, 90),
        base_num_range=(4, 6),
        color_mean=(163, 138, 127),
        bg_mean=(153, 115, 85),
        color_std=2,               # 畴区间颜色标准差，越大色差越大
        texture_std=8,             # 畴区内部纹理噪声，越大纹理越粗糙
        bg_noise_std=3,            # 背景噪声标准差，越大背景越粗糙
        max_overlap_ratio=0.5,     # 单个畴区允许的最大重叠比例
        max_overlap_count=3,       # 单个像素允许的最大重叠次数
        size_std=20,               # 畴区大小标准差（None=均匀分布；设为值=正态分布）
        mag_factor=0.2,            # 放大倍率（<1 缩小畴区）
        supersample_ratio=1,       # 超采样倍率（抗锯齿）
        shape_jitter=0.2         # 顶点径向扰动比例（0=正六边形，越大越不规则）
    )

    # ---- 增强器配置（与原 syn_data.py microscopy_augment 一致）----
    augmenter = MicroscopyAugment(
        brightness_range=(0.9, 1.3),
        brightness_prob=0.8,
        contrast_range=(0.9, 1.1),
        contrast_prob=0.5,
        gamma_range=(0.9, 1.1),
        gamma_prob=0.5,
        blur_prob=0.0,          # 原版不使用模糊
        rotate_prob=0.0
    )

    # ---- 流水线 ----
    pipeline = DatasetPipeline(generator, augmenter)

    pipeline.run(
        output_root="./data/syn_data",
        n=10,
        name_prefix="syn",
        image_size=(512, 512)
    )


if __name__ == "__main__":
    main()
