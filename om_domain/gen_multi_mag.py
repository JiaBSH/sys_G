"""
多倍率合成畴区数据集生成。

通过 mag_factor 控制倍率差异:
  - 有效半径 = base_r_range * mag_factor * image_scale * supersample_ratio
  - 有效数量 = base_num_range / mag_factor²  （与 image_scale 无关）
  - mag_factor=1.0 对应 10x，image_scale=1.0 对应参考画布 (1024, 681)

运行方式:
    python -m om_domain.gen_multi_mag                  # auto 选择后端
    python -m om_domain.gen_multi_mag --gpu            # 强制 GPU
    python -m om_domain.gen_multi_mag --backend fast_cpu  # CPU 优化版 (~35x 加速)
    python -m om_domain.gen_multi_mag --backend original  # 原始版（对比基准）
"""

import os
import json
import argparse
from datetime import datetime

from om_domain.pipeline import DatasetPipeline
from om_domain.hexagon_generator import HexagonGenerator
from om_domain.gpu_hexagon_generator import GPUFastHexagonGenerator
from om_domain.augment import MicroscopyAugment

# =========================================================================
# 倍率 → mag_factor 映射（>1 高倍近景畴大稀少，<1 低倍远景畴小密集）
# =========================================================================
MAG_FACTORS = {
    #"2.5x":  0.25,
    "5x":    0.5,
    "20x":   2.0,
    "50x":   5.0,
    "100x": 10.0,
}

# =========================================================================
# 输出控制
# =========================================================================
TOTAL_PER_MAG = 20                           # 每个倍率生成的图像数量
OUTPUT_ROOT = "../data/syn_multimag/raw_rotation"            # 输出根目录，结构: {root}/{mag}/image/ 和 label/
IMAGE_SIZE = (4096, 2724)                          # 输出图像尺寸 (width, height)，长边 2048

# =========================================================================
# 共享生成器参数（r = base_r × mag × scale × ss,  n = base_n / mag²）
# =========================================================================
SHARED_GEN_KWARGS = dict(
    # -- 颜色 / 纹理 --
    color_mean=(163, 138, 127),          # 畴区 RGB 均值
    bg_mean=(153, 115, 85),              # 背景 RGB 均值
    color_std=0.2,                       # 畴区间色差标准差 (0~30)
    texture_std=2,                       # 畴区内纹理噪声标准差 (0~20, 0=平滑)
    bg_noise_std=2,                      # 背景噪声标准差 (0~10, 0=纯色)
    # -- 几何 / 尺寸 --
    base_r_range=(15, 25),               # 基础半径范围 px (mag=1,scale=1,ss=1)
    base_num_range=(200, 400),           # 基础数量范围 (mag=1, 最终=base/mag²)
    size_std=25,                         # 半径标准差 (None=均匀分布)
    shape_jitter=0.1,                    # 顶点扰动比例 (0=正六边形, 0.1=不规则)
    orientation_std=60,                   # 畴区取向标准差（度）(0=同向, 值越大越随机)
    image_scale=4,                       # 画布缩放因子 (半径∝scale, 数量不变)
    # -- 边缘毛刺 --
    edge_burr_amplitude=0.05,            # 毛刺振幅 (0=光滑, 0.05=微刺, 0.1=锯齿)
    edge_burr_subdivisions=4,            # 边细分点数 (≥2, 越大越细密)
    # -- 重叠控制 --
    max_overlap_ratio=0.1,               # 单畴区最大重叠比例 [0,1]
    max_overlap_count=3,                 # 单像素最大覆盖次数 (None=不限)
    contain_threshold=0.85,              # 包含判定阈值 (新畴区覆盖旧畴区超此比例则拒)
    min_area_factor=5,                   # 最小面积系数 (实际=系数×ss, 过小丢弃)
    # -- 渲染 --
    supersample_ratio=1,                 # 超采样倍率 (1=原生, >1=抗锯齿, 慢ratio²)
)

# =========================================================================
# 共享增强器参数（显微镜成像模拟）
# =========================================================================
SHARED_AUG_KWARGS = dict(
    # -- 亮度 --
    brightness_range=(0.8, 1),           # 亮度因子范围 (<1 暗, >1 亮)
    brightness_prob=0.8,                 # 触发概率 [0,1]
    # -- 对比度 --
    contrast_range=(0.4, 1),             # 对比度因子范围 (<1 降, >1 增)
    contrast_prob=0.8,                   # 触发概率 [0,1]
    # -- Gamma --
    gamma_range=(0.7, 1.3),              # Gamma 范围 (<1 提暗, >1 压亮; None=关)
    gamma_prob=0.8,                      # 触发概率 [0,1]
    # -- 高斯模糊 --
    blur_range=(0.5, 1),              # 模糊半径范围 px
    blur_prob=1,                         # 触发概率 [0,1]
    # -- 整体色彩扰动（色温/光源变化）--
    color_jitter_range=(-12, 12),        # RGB 通道偏移范围 (None=关)
    color_jitter_prob=0.8,               # 触发概率 [0,1]
    # -- 椒盐噪声 --
    sp_noise_prob=0,                     # 触发概率 [0,1]
    # -- 旋转 --
    rotate_prob=0.0,                     # 触发概率 [0,1]
)


def print_effective_params():
    """打印各倍率的有效参数预览（含 mag_factor、image_scale 联合效果）。"""
    print("\n=== Effective Parameters ===")
    base_r = SHARED_GEN_KWARGS["base_r_range"]
    base_n = SHARED_GEN_KWARGS["base_num_range"]
    im_sc = SHARED_GEN_KWARGS["image_scale"]
    ss = SHARED_GEN_KWARGS["supersample_ratio"]

    print(f"{'Mag':<8} {'mag_f':<8} {'radius':<16} {'count':<16}")
    print("-" * 48)
    for label, mf in MAG_FACTORS.items():
        r_min = int(base_r[0] * mf * im_sc * ss)
        r_max = int(base_r[1] * mf * im_sc * ss)
        c_min = max(1, int(base_n[0] / (mf ** 2)))
        c_max = max(c_min + 1, int(base_n[1] / (mf ** 2)))
        print(f"{label:<8} {mf:<8.2f} {r_min}-{r_max} px{'':<6} {c_min}-{c_max}")
    print(f"(image_scale={im_sc}, supersample_ratio={ss})")
    print("=" * 48)


def save_params(output_dir: str, mag_label: str, mag_factor: float, backend: str):
    """保存本轮生成的全部参数到输出目录 params.json。

    方便后续复现实验或追溯图像对应的配置。
    """
    params = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mag_label": mag_label,
        "mag_factor": mag_factor,
        "total_per_mag": TOTAL_PER_MAG,
        "image_size": list(IMAGE_SIZE),
        "backend": backend,
        "generator_kwargs": SHARED_GEN_KWARGS,
        "augment_kwargs": SHARED_AUG_KWARGS,
    }
    param_path = os.path.join(output_dir, "params.json")
    with open(param_path, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    print(f"[Params] saved → {param_path}")


def generate_one_magnification(mag_label: str, mag_factor: float, backend: str = "auto"):
    """为单个倍率生成 TOTAL_PER_MAG 张图像。

    Args:
        mag_label: 倍率标签，如 "2.5x"
        mag_factor: 倍率因子
        backend: 生成器后端
            - "original": 原始 HexagonGenerator（慢，用作对比基准）
            - "fast_cpu": ROI 优化的 GPUFastHexagonGenerator（~35x 加速，推荐）
            - "gpu": GPU 加速版（背景噪声在 CUDA 上生成，域渲染走 CPU）
            - "auto": 自动选择——有 CUDA 则 gpu，否则 fast_cpu
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

    # 保存生成参数
    save_params(output_dir, mag_label, mag_factor, backend)
    print(f"[Done] {mag_label}: {TOTAL_PER_MAG} images → {output_dir}")


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="Generate multi-magnification domain images"
    )
    parser.add_argument(
        "--backend", choices=["original", "fast_cpu", "gpu", "auto"],
        default="auto",
        help="Generator backend: original (slow baseline) | fast_cpu (~35x faster) "
             "| gpu (GPU background) | auto (pick best available)"
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
