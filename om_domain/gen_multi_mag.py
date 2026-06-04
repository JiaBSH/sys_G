"""
多倍率合成畴区数据集生成。

通过 mag_factor 控制倍率差异:
  - 有效半径 = base_r_range * mag_factor
  - 有效数量 = base_num_range / mag_factor²
  - mag_factor=1.0 对应 10x

所有图像长边 1024 (1024×800)。

运行方式:
    python -m om_domain.gen_multi_mag                  # auto 选择后端
    python -m om_domain.gen_multi_mag --gpu            # 强制 GPU
    python -m om_domain.gen_multi_mag --backend fast_cpu  # CPU 优化版
    python -m om_domain.gen_multi_mag --backend original  # 原始版
"""

import os
import argparse

from om_domain.pipeline import DatasetPipeline
from om_domain.hexagon_generator import HexagonGenerator
from om_domain.gpu_hexagon_generator import GPUFastHexagonGenerator
from om_domain.augment import MicroscopyAugment

# =========================================================================
# 倍率 → mag_factor 映射
# 有效半径 min @ 20x = 100 × 2.0 = 200 ✓
# =========================================================================
MAG_FACTORS = {
    "2.5x":  0.25,
    "5x":    0.5,
    "20x":   2.0,
    "50x":   5.0,
    "100x": 10.0,
}

TOTAL_PER_MAG = 4
OUTPUT_ROOT = "./data/syn_multimag/raw"
IMAGE_SIZE = (1024, 681)

# =========================================================================
# 共享生成器参数
# base_r_range=(100,250), base_num_range=(8,25) 通过 mag_factor 控制各倍率
# =========================================================================
SHARED_GEN_KWARGS = dict(
    # 颜色 / 纹理
    color_mean=(163, 138, 127),
    bg_mean=(153, 115, 85),
    color_std=0.2,
    texture_std=8,
    bg_noise_std=3,
    # 几何 / 尺寸 (通过 mag_factor 缩放)
    base_r_range=(15, 25),
    base_num_range=(200, 350),
    size_std=25,
    shape_jitter=0.1,
    # 边缘毛刺
    edge_burr_amplitude=0.08,
    edge_burr_subdivisions=4,
    # 重叠控制
    max_overlap_ratio=0.3,
    max_overlap_count=3,
    contain_threshold=0.85,
    min_area_factor=5,
    # 渲染
    supersample_ratio=1,
)

SHARED_AUG_KWARGS = dict(
    brightness_range=(0.8, 1),
    brightness_prob=0.8,
    contrast_range=(0.5, 1),
    contrast_prob=0.8,
    gamma_range=(0.7, 1.3),
    gamma_prob=0.8,
    blur_range=(0.3, 0.8),
    blur_prob=0,
    sp_noise_prob=0,
    rotate_prob=0.0,
)


def print_effective_params():
    """打印各倍率的有效参数预览。"""
    print("\n=== Effective Parameters ===")
    print(f"{'Mag':<8} {'mag_f':<8} {'radius':<16} {'count':<16}")
    print("-" * 48)
    base_r = SHARED_GEN_KWARGS["base_r_range"]
    base_n = SHARED_GEN_KWARGS["base_num_range"]
    for label, mf in MAG_FACTORS.items():
        r_min = int(base_r[0] * mf)
        r_max = int(base_r[1] * mf)
        c_min = max(1, int(base_n[0] / (mf ** 2)))
        c_max = max(c_min + 1, int(base_n[1] / (mf ** 2)))
        print(f"{label:<8} {mf:<8.2f} {r_min}-{r_max} px{'':<6} {c_min}-{c_max}")
    print("=" * 48)


def generate_one_magnification(mag_label: str, mag_factor: float, backend: str = "auto"):
    """为单个倍率生成 TOTAL_PER_MAG 张图像。

    Args:
        mag_label: 倍率标签，如 "2.5x"
        mag_factor: 倍率因子
        backend: 生成器后端
            - "original": 原始 HexagonGenerator
            - "fast_cpu": ROI 优化的 GPUFastHexagonGenerator (CPU 路径)
            - "gpu": GPU 加速的 GPUFastHexagonGenerator
            - "auto": 有 CUDA 则 gpu，否则 fast_cpu
    """
    output_dir = os.path.join(OUTPUT_ROOT, mag_label)
    if os.path.exists(output_dir):
        print(f"[Skip] {mag_label}: output dir already exists ({output_dir})")
        return

    # 解析后端
    if backend == "auto":
        try:
            import torch
            backend = "gpu" if torch.cuda.is_available() else "fast_cpu"
        except ImportError:
            backend = "fast_cpu"

    if backend == "original":
        generator = HexagonGenerator(
            mag_factor=mag_factor,
            **SHARED_GEN_KWARGS,
        )
    elif backend in ("fast_cpu", "gpu"):
        generator = GPUFastHexagonGenerator(
            mag_factor=mag_factor,
            use_gpu=(backend == "gpu"),
            **SHARED_GEN_KWARGS,
        )
    else:
        raise ValueError(f"Unknown backend: {backend}")

    print(f"[Backend] {mag_label}: {backend}")

    augmenter = MicroscopyAugment(**SHARED_AUG_KWARGS)
    pipeline = DatasetPipeline(generator, augmenter)

    pipeline.run(
        output_root=output_dir,
        n=TOTAL_PER_MAG,
        name_prefix=f"syn_{mag_label.replace('.', 'p')}",
        image_size=IMAGE_SIZE,
    )
    print(f"[Done] {mag_label}: {TOTAL_PER_MAG} images → {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate multi-magnification domain images"
    )
    parser.add_argument(
        "--backend", choices=["original", "fast_cpu", "gpu", "auto"],
        default="auto",
        help="Generator backend (auto=GPU if available, else fast_cpu)"
    )
    parser.add_argument(
        "--gpu", action="store_true",
        help="Shorthand for --backend=gpu"
    )
    args = parser.parse_args()

    backend = "gpu" if args.gpu else args.backend

    print_effective_params()
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    for mag_label, mag_factor in MAG_FACTORS.items():
        generate_one_magnification(mag_label, mag_factor, backend=backend)
    print(f"\nAll magnifications generated under {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
