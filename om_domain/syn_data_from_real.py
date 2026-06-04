"""
基于真实数据的 Copy-Paste 数据集生成 — 入口脚本。

从标注数据中提取畴区实例，通过颜色统一化、缩放、旋转后
随机放置到新背景上。可通过 python -m om_domain.syn_data_from_real 运行。
"""

from om_domain.pipeline import DatasetPipeline
from om_domain.copy_paste_generator import CopyPasteGenerator
from om_domain.augment import MicroscopyAugment


def main():
    # ---- 数据源路径 ----
    SOURCE_JSON_DIR = "data/source/train_label"
    SOURCE_IMG_DIR = "data/source/train_image"
    OUTPUT_DIR = "data/sys_2"

    # ---- 生成器配置（从真实数据提取实例）----
    generator = CopyPasteGenerator(
        json_dir=SOURCE_JSON_DIR,
        img_dir=SOURCE_IMG_DIR,
        margin=20,
        color_std=2,               # 畴区间颜色标准差，越大色差越大
        texture_std=10,            # 畴区内部纹理噪声，越大纹理越粗糙
        bg_noise_std=5,            # 背景噪声标准差，越大背景越粗糙
        max_overlap_ratio=0.5,     # 单个畴区允许的最大重叠比例
        max_overlap_count=None,    # 单像素最大重叠次数（None=不限制）
        min_area=50,               # 畴区最小有效面积（像素）
        size_std=None,             # 畴区大小标准差（None=均匀分布；设为值=正态分布）
        num_range=(30, 42),        # 每张图畴区数量范围
        size_scale_range=(0.3, 0.6),  # 实例缩放范围
        shape_jitter=0             # 顶点形状扰动标准差（0=不扰动）
    )

    if not generator.instances:
        print("[Error] No instances extracted. Check source paths.")
        return

    # ---- 增强器配置（与原 syn_data_from_real.py microscopy_augment 一致）----
    augmenter = MicroscopyAugment(
        brightness_range=(0.5, 1),
        brightness_prob=0.8,
        contrast_range=(0.5, 1),
        contrast_prob=0.8,
        gamma_range=None,       # 原版不使用 Gamma
        blur_range=(2, 4),
        blur_prob=1.0,          # 原版必然模糊
        # -- 毛刺 --
        sp_noise_prob=0.0,      # 默认不启用毛刺
        rotate_prob=0.0
    )

    # ---- 流水线 ----
    pipeline = DatasetPipeline(generator, augmenter)

    pipeline.run(
        output_root=OUTPUT_DIR,
        n=10,
        name_prefix="syn_real",
        image_size=(1024, 800)
    )


if __name__ == "__main__":
    main()
