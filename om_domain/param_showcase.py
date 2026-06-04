"""
控制变量参数效果展示脚本。

基准参数与 gen_multi_mag.py 的 SHARED_GEN_KWARGS 保持一致。
通过固定随机种子、逐一改变关键参数的方式生成对比图，
直观展示每个参数对合成畴区图像的影响。

运行方式:
    python -m om_domain.param_showcase                  # 全部生成
    python -m om_domain.param_showcase --seed 123       # 指定种子
    python -m om_domain.param_showcase --size 1024      # 指定图像尺寸
    python -m om_domain.param_showcase --gen-only       # 仅生成器参数
    python -m om_domain.param_showcase --aug-only       # 仅增强器参数
    python -m om_domain.param_showcase --multi-mag-only # 仅多倍率总览
"""

import os
import sys
import random
import argparse
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from om_domain.hexagon_generator import HexagonGenerator
from om_domain.augment import MicroscopyAugment


# =========================================================================
# 全局配置
# =========================================================================
OUTPUT_DIR = "./output/param_showcase"
DEFAULT_SEED = 42
DEFAULT_IMAGE_SIZE = (512, 512)

# 基准生成器参数 — 与 gen_multi_mag.py 的 SHARED_GEN_KWARGS 保持一致
BASELINE_CONFIG = dict(
    # -- 颜色 / 纹理 --
    color_mean=(163, 138, 127),
    bg_mean=(153, 115, 85),
    color_std=0.2,               # 固定 0.2（与 gen_multi_mag 一致）
    texture_std=2,
    bg_noise_std=2,
    # -- 几何 / 尺寸 --
    base_r_range=(15, 25),
    base_num_range=(200, 400),
    size_std=25,
    mag_factor=1.0,
    shape_jitter=0.1,
    orientation_std=0,            # 畴区取向标准差（度）(0=同向)
    image_scale=None,             # 运行时根据画布尺寸自动计算 = W/1024
    # -- 边缘毛刺 --
    edge_burr_amplitude=0.08,
    edge_burr_subdivisions=4,
    # -- 重叠控制 --
    max_overlap_ratio=0.3,
    max_overlap_count=3,
    contain_threshold=0.85,
    min_area_factor=5,
    # -- 渲染 --
    supersample_ratio=1,
)

# 多倍率映射 — 与 gen_multi_mag.py 的 MAG_FACTORS 一致
# 公式: radius = base_r × mag × image_scale × ss
#       count  = base_n / mag²
MAG_FACTORS = {
    "2.5x":  0.25,
    "5x":    0.5,
    "10x":   1.0,    # 参考倍率
    "20x":   2.0,
    "50x":   5.0,
    "100x": 10.0,
}


# =========================================================================
# 工具函数
# =========================================================================

def reset_seed(seed):
    """重置所有随机数生成器状态。"""
    random.seed(seed)
    np.random.seed(seed)


def make_generator(image_size, **overrides):
    """以 BASELINE_CONFIG 为基础创建 HexagonGenerator。

    自动计算 image_scale = image_width / 1024，与 gen_multi_mag.py 的行为一致。
    """
    cfg = BASELINE_CONFIG.copy()
    cfg.update(overrides)
    # 若未显式覆盖 image_scale，则根据画布宽度自动计算
    if cfg.get("image_scale") is None:
        cfg["image_scale"] = image_size[0] / 1024
    return HexagonGenerator(**cfg)


def effective_params(mag_factor, image_scale=None, supersample_ratio=None):
    """计算给定 mag_factor 的有效半径范围和数量范围。"""
    br = BASELINE_CONFIG["base_r_range"]
    bn = BASELINE_CONFIG["base_num_range"]
    im_sc = image_scale if image_scale is not None else BASELINE_CONFIG["image_scale"]
    ss = supersample_ratio if supersample_ratio is not None else BASELINE_CONFIG["supersample_ratio"]

    r_min = int(br[0] * mag_factor * im_sc * ss)
    r_max = int(br[1] * mag_factor * im_sc * ss)
    c_min = max(1, int(bn[0] / (mag_factor ** 2)))
    c_max = max(c_min + 1, int(bn[1] / (mag_factor ** 2)))
    return (r_min, r_max), (c_min, c_max)


# =========================================================================
# 参数展示定义
# =========================================================================

GENERATOR_SHOWCASES = [
    # ---- Color / Texture ----
    {
        "title": "color_std — Inter-domain Color Variation",
        "param": "color_std",
        "values": [0, 0.2, 1, 5, 15],
        "labels": ["0\n(identical)", "0.2\n(baseline)", "1", "5", "15\n(extreme)"],
    },
    {
        "title": "texture_std — Intra-domain Texture Noise",
        "param": "texture_std",
        "values": [0, 1, 2, 5, 15],
        "labels": ["0\n(smooth)", "1", "2\n(baseline)", "5", "15\n(rough)"],
    },
    {
        "title": "bg_noise_std — Background Noise",
        "param": "bg_noise_std",
        "values": [0, 1, 2, 6, 15],
        "labels": ["0\n(solid)", "1", "2\n(baseline)", "6", "15\n(noisy)"],
    },
    {
        "title": "color_mean — Domain Hue",
        "param": "color_mean",
        "values": [
            (200, 160, 140),
            (163, 138, 127),
            (140, 150, 160),
            (120, 140, 120),
            (180, 120, 120),
        ],
        "labels": ["warm brown", "baseline", "cool gray", "greenish", "reddish"],
    },
    {
        "title": "bg_mean — Background Hue",
        "param": "bg_mean",
        "values": [
            (180, 140, 110),
            (153, 115, 85),
            (120, 130, 140),
            (100, 120, 100),
            (160, 120, 120),
        ],
        "labels": ["warm brown", "baseline", "cool gray", "greenish", "reddish"],
    },

    # ---- Geometry / Size ----
    {
        "title": "base_r_range — Domain Radius Range",
        "param": "base_r_range",
        "values": [(8, 12), (12, 18), (15, 25), (25, 40), (40, 60)],
        "labels": ["8-12\n(tiny)", "12-18", "15-25\n(baseline)", "25-40", "40-60\n(large)"],
    },
    {
        "title": "shape_jitter — Vertex Radial Perturbation",
        "param": "shape_jitter",
        "values": [0.0, 0.05, 0.1, 0.2, 0.35],
        "labels": ["0.0\n(regular)", "0.05", "0.1\n(baseline)", "0.2", "0.35\n(distorted)"],
    },
    {
        "title": "orientation_std — Domain Orientation Spread",
        "param": "orientation_std",
        "values": [0, 5, 15, 30, 60],
        "labels": ["0°\n(aligned)", "5°", "15°", "30°", "60°\n(random)"],
    },
    {
        "title": "size_std — Size Distribution",
        "param": "size_std",
        "values": [None, 10, 25, 40, 60],
        "labels": ["uniform", "std=10", "std=25\n(baseline)", "std=40", "std=60\n(spread)"],
    },
    {
        "title": "base_num_range — Domain Count Range",
        "param": "base_num_range",
        "values": [(50, 100), (100, 200), (200, 400), (400, 800), (800, 1600)],
        "labels": ["50-100\n(sparse)", "100-200", "200-400\n(baseline)", "400-800", "800-1600\n(dense)"],
    },

    # ---- Edge Burr ----
    {
        "title": "edge_burr_amplitude — Edge Roughness Amplitude",
        "param": "edge_burr_amplitude",
        "values": [0.0, 0.04, 0.08, 0.12, 0.18],
        "labels": ["0.0\n(smooth)", "0.04", "0.08\n(baseline)", "0.12", "0.18\n(rough)"],
        "extra": {"edge_burr_subdivisions": 4},
    },
    {
        "title": "edge_burr_subdivisions — Edge Subdivision Density",
        "param": "edge_burr_subdivisions",
        "values": [1, 2, 4, 8, 12],
        "labels": ["1\n(off)", "2", "4\n(baseline)", "8", "12\n(fine)"],
        "extra": {"edge_burr_amplitude": 0.08},
    },

    # ---- Overlap Control ----
    {
        "title": "max_overlap_ratio — Max Overlap Ratio",
        "param": "max_overlap_ratio",
        "values": [0.0, 0.15, 0.3, 0.6, 0.9],
        "labels": ["0.0\n(no overlap)", "0.15", "0.3\n(baseline)", "0.6", "0.9\n(heavy)"],
    },
    {
        "title": "max_overlap_count — Max Pixel Coverage Layers",
        "param": "max_overlap_count",
        "values": [1, 2, 3, 6, None],
        "labels": ["1\n(single)", "2", "3\n(baseline)", "6", "unlimited"],
    },
    {
        "title": "contain_threshold — Containment Threshold",
        "param": "contain_threshold",
        "values": [0.3, 0.6, 0.85, 0.95],
        "labels": ["0.3\n(strict)", "0.6", "0.85\n(baseline)", "0.95\n(lenient)"],
    },

    # ---- Rendering ----
    {
        "title": "supersample_ratio — Anti-aliasing Supersampling",
        "param": "supersample_ratio",
        "values": [1, 2, 4],
        "labels": ["1x\n(no AA)", "2x", "4x\n(high AA)"],
    },
]

# 增强器参数展示 — 各项关闭，逐一开启测试
AUGMENT_SHOWCASES = [
    {
        "title": "Brightness Adjustment",
        "aug_type": "brightness",
        "values": [0.4, 0.7, 1.0, 1.5, 2.0],
        "labels": ["0.4\n(very dark)", "0.7\n(dim)", "1.0\n(original)", "1.5\n(bright)", "2.0\n(overexposed)"],
    },
    {
        "title": "Contrast Adjustment",
        "aug_type": "contrast",
        "values": [0.3, 0.7, 1.0, 1.5, 2.0],
        "labels": ["0.3\n(very low)", "0.7\n(low)", "1.0\n(original)", "1.5\n(high)", "2.0\n(very high)"],
    },
    {
        "title": "Gamma Correction",
        "aug_type": "gamma",
        "values": [0.5, 0.8, 1.0, 1.4, 2.0],
        "labels": ["0.5\n(shadow lift)", "0.8", "1.0\n(neutral)", "1.4", "2.0\n(shadow crush)"],
    },
    {
        "title": "Gaussian Blur",
        "aug_type": "blur",
        "values": [0, 1.5, 3.0, 6.0, 10.0],
        "labels": ["0\n(sharp)", "1.5", "3.0", "6.0", "10.0\n(blurry)"],
    },
    {
        "title": "Salt & Pepper Noise",
        "aug_type": "sp_noise",
        "values": [0.0, 0.005, 0.01, 0.03, 0.05],
        "labels": ["0\n(clean)", "0.5%", "1%", "3%", "5%\n(noisy)"],
    },
    {
        "title": "Color Jitter / White Balance Shift",
        "aug_type": "color_jitter",
        "values": [0, 10, 20, 40, 60],
        "labels": ["0\n(no shift)", "+-10", "+-20", "+-40", "+-60\n(strong cast)"],
    },
]


# =========================================================================
# 图像生成逻辑
# =========================================================================

def generate_baseline_image(seed, image_size):
    """生成基准图像（使用默认配置）。"""
    reset_seed(seed)
    gen = make_generator(image_size)
    img, _ = gen.generate(image_size)
    return img


def generate_variant_image(param_name, param_value, seed, image_size, extra=None):
    """生成一个参数变体图像。"""
    reset_seed(seed)
    overrides = {param_name: param_value}
    if extra:
        overrides.update(extra)
    gen = make_generator(image_size, **overrides)
    img, _ = gen.generate(image_size)
    return img


def apply_augment(img, aug_type, value):
    """对图像应用指定的增强效果（确定性，prob=1.0）。"""
    base = dict(
        brightness_range=(1, 1), brightness_prob=0,
        contrast_range=(1, 1), contrast_prob=0,
        gamma_range=None, gamma_prob=0,
        blur_range=(0, 0), blur_prob=0,
        sp_noise_prob=0, sp_noise_amount=0,
        color_jitter_range=None, color_jitter_prob=0,
        rotate_prob=0,
    )

    if aug_type == "brightness":
        base.update(brightness_range=(value, value), brightness_prob=1.0)
    elif aug_type == "contrast":
        base.update(contrast_range=(value, value), contrast_prob=1.0)
    elif aug_type == "gamma":
        base.update(gamma_range=(value, value), gamma_prob=1.0)
    elif aug_type == "blur":
        base.update(blur_range=(value, value), blur_prob=1.0)
    elif aug_type == "sp_noise":
        base.update(
            sp_noise_prob=1.0 if value > 0 else 0,
            sp_noise_amount=value)
    elif aug_type == "color_jitter":
        base.update(
            color_jitter_range=(-value, value),
            color_jitter_prob=1.0 if value > 0 else 0)
    else:
        raise ValueError(f"Unknown augment type: {aug_type}")

    aug = MicroscopyAugment(**base)
    img_out, _ = aug(img)
    return img_out


# =========================================================================
# 绘图
# =========================================================================

def plot_generator_showcase(showcase, seed, image_size, output_dir):
    """为一组生成器参数绘制对比图并保存。"""
    title = showcase["title"]
    param = showcase["param"]
    values = showcase["values"]
    labels = showcase.get("labels", [str(v) for v in values])
    extra = showcase.get("extra", None)

    n = len(values)
    fig_w = min(3.0 * n, 20)
    fig, axes = plt.subplots(1, n, figsize=(fig_w, 3.8))
    if n == 1:
        axes = [axes]

    for i, (val, lbl) in enumerate(zip(values, labels)):
        img = generate_variant_image(param, val, seed, image_size, extra)
        axes[i].imshow(img)
        axes[i].set_title(lbl, fontsize=9, pad=4)
        axes[i].axis('off')

    fig.suptitle(title, fontsize=12, fontweight='bold', y=0.98)
    plt.subplots_adjust(left=0.01, right=0.99, top=0.88, bottom=0.02, wspace=0.05)

    safe_name = title.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_")
    path = os.path.join(output_dir, f"gen_{safe_name}.png")
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close(fig)
    return path


def plot_augment_showcase(showcase, base_img, output_dir):
    """为一组增强参数绘制对比图并保存。"""
    title = showcase["title"]
    aug_type = showcase["aug_type"]
    values = showcase["values"]
    labels = showcase.get("labels", [str(v) for v in values])

    n = len(values) + 1
    fig_w = min(3.0 * n, 20)
    fig, axes = plt.subplots(1, n, figsize=(fig_w, 3.8))
    if n == 1:
        axes = [axes]

    axes[0].imshow(base_img)
    axes[0].set_title("Original\n(no augment)", fontsize=9, pad=4)
    axes[0].axis('off')

    for i, (val, lbl) in enumerate(zip(values, labels)):
        aug_img = apply_augment(base_img, aug_type, val)
        axes[i + 1].imshow(aug_img)
        axes[i + 1].set_title(lbl, fontsize=9, pad=4)
        axes[i + 1].axis('off')

    fig.suptitle(title, fontsize=12, fontweight='bold', y=0.98)
    plt.subplots_adjust(left=0.01, right=0.99, top=0.88, bottom=0.02, wspace=0.05)

    safe_name = title.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_")
    path = os.path.join(output_dir, f"aug_{safe_name}.png")
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close(fig)
    return path


def plot_multi_mag_overview(seed, image_size, output_dir):
    """
    多倍率视场与畴区密度总览图。

    使用 gen_multi_mag.py 的 MAG_FACTORS，展示各倍率下
    畴区大小和密度的自然变化（公式驱动，非手动调参）。
    每个 mag 仅用该倍率对应的 mag_factor 覆盖 BASELINE。

    image_scale 自动按 image_width/1024 计算（与 gen_multi_mag.py 一致）。
    """
    n = len(MAG_FACTORS)
    fig, axes = plt.subplots(1, n, figsize=(3.5 * n, 4.5))

    im_sc = image_size[0] / 1024   # 与 gen_multi_mag 一致: image_scale = W/1024
    ss = BASELINE_CONFIG["supersample_ratio"]

    for i, (label, mf) in enumerate(MAG_FACTORS.items()):
        reset_seed(seed)
        gen = make_generator(image_size, mag_factor=mf)
        img, _ = gen.generate(image_size)

        (r_min, r_max), (c_min, c_max) = effective_params(mf, im_sc, ss)

        axes[i].imshow(img)
        axes[i].set_title(
            f"{label}\nmag={mf}\nr={r_min}-{r_max}px\nn={c_min}-{c_max}",
            fontsize=8, pad=2)
        axes[i].axis('off')

    fig.suptitle(
        f"Multi-Magnification Overview (color_std=0.2, image_scale={im_sc:.2f})\n"
        "radius ∝ mag    count ∝ 1/mag²    —    gen_multi_mag.py parameters",
        fontsize=12, fontweight='bold', y=0.99)
    plt.subplots_adjust(left=0.01, right=0.99, top=0.84, bottom=0.02, wspace=0.04)

    path = os.path.join(output_dir, "multi_mag_overview.png")
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close(fig)
    return path


# =========================================================================
# 主入口
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="控制变量参数效果展示 — 生成每个参数的对比图")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"随机种子 (默认: {DEFAULT_SEED})")
    parser.add_argument("--size", type=int, default=DEFAULT_IMAGE_SIZE[0],
                        help=f"输出图像边长 (默认: {DEFAULT_IMAGE_SIZE[0]})")
    parser.add_argument("--output", type=str, default=OUTPUT_DIR,
                        help=f"输出目录 (默认: {OUTPUT_DIR})")
    parser.add_argument("--gen-only", action="store_true",
                        help="仅生成 生成器参数展示")
    parser.add_argument("--aug-only", action="store_true",
                        help="仅生成 增强器参数展示")
    parser.add_argument("--multi-mag-only", action="store_true",
                        help="仅生成 多倍率总览图")
    args = parser.parse_args()

    seed = args.seed
    image_size = (args.size, args.size)
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 65)
    print("  控制变量参数效果展示")
    print(f"  color_std = 0.2 (固定)    种子: {seed}    尺寸: {image_size}")
    print(f"  输出: {output_dir}")
    print("=" * 65)

    records = []  # (category, title, rel_path)

    # ---- 多倍率总览 ----
    if args.multi_mag_only or (not args.gen_only and not args.aug_only):
        print("\n[多倍率总览] Multi-Magnification Overview")
        print("-" * 45)
        path = plot_multi_mag_overview(seed, image_size, output_dir)
        rel = os.path.relpath(path, output_dir)
        records.append(("多倍率总览", "Multi-Magnification Overview", rel))
        print(f"  → {rel}")
    elif args.multi_mag_only:
        # multi-mag-only: skip gen/aug
        path = plot_multi_mag_overview(seed, image_size, output_dir)
        rel = os.path.relpath(path, output_dir)
        records.append(("多倍率总览", "Multi-Magnification Overview", rel))
        print(f"  → {rel}")
        print("\n" + "=" * 65)
        print(f"  完成! 共生成 {len(records)} 张图")
        print(f"  输出目录: {os.path.abspath(output_dir)}")
        print("=" * 65)
        return

    # ---- 生成器参数 ----
    if not args.aug_only and not args.multi_mag_only:
        print("\n[生成器参数] HexagonGenerator  (color_std=0.2)")
        print("-" * 45)
        for i, sc in enumerate(GENERATOR_SHOWCASES, 1):
            name = sc["title"].split(" — ")[0]
            print(f"  [{i:2d}/{len(GENERATOR_SHOWCASES)}] {name} ...", end=" ", flush=True)
            path = plot_generator_showcase(sc, seed, image_size, output_dir)
            rel = os.path.relpath(path, output_dir)
            records.append(("生成器参数 (color_std=0.2)", sc["title"], rel))
            print("OK")

    # ---- 增强器参数 ----
    if not args.gen_only and not args.multi_mag_only:
        print("\n[增强器参数] MicroscopyAugment")
        print("-" * 45)
        print("  生成基准图像 ...", end=" ", flush=True)
        base_img = generate_baseline_image(seed, image_size)
        print("OK\n")

        for i, sc in enumerate(AUGMENT_SHOWCASES, 1):
            name = sc["title"]
            print(f"  [{i:2d}/{len(AUGMENT_SHOWCASES)}] {name} ...", end=" ", flush=True)
            path = plot_augment_showcase(sc, base_img, output_dir)
            rel = os.path.relpath(path, output_dir)
            records.append(("增强器参数", sc["title"], rel))
            print("OK")

    # ---- 汇总 ----
    print("\n" + "=" * 65)
    print(f"  完成! 共生成 {len(records)} 张对比图")
    print(f"  输出目录: {os.path.abspath(output_dir)}")
    print("=" * 65)

    # 打印各倍率有效参数
    print("\n  各倍率有效参数预览:")
    print(f"  {'Mag':<8} {'mag_f':<8} {'radius':<16} {'count':<16}")
    print(f"  {'-'*48}")
    im_sc = image_size[0] / 1024   # 自动计算（与 gen_multi_mag 一致）
    ss = BASELINE_CONFIG["supersample_ratio"]
    for label, mf in MAG_FACTORS.items():
        (r_min, r_max), (c_min, c_max) = effective_params(mf, im_sc, ss)
        print(f"  {label:<8} {mf:<8.2f} {r_min}-{r_max} px{'':<6} {c_min}-{c_max}")
    print(f"  (image_scale={im_sc:.2f}, supersample_ratio={ss})")

    # 生成索引
    index_path = os.path.join(output_dir, "index.md")
    _write_index_md(index_path, records, seed, image_size)
    print(f"\n  索引文件: {index_path}")


def _write_index_md(path, records, seed, image_size):
    """生成 Markdown 索引文件。"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write("# 参数效果展示 — 索引 (color_std=0.2)\n\n")
        f.write(f"- **随机种子**: `{seed}`\n")
        f.write(f"- **图像尺寸**: `{image_size[0]}×{image_size[1]}`\n")
        f.write(f"- **基准参数**: 与 `gen_multi_mag.py` 的 `SHARED_GEN_KWARGS` 一致\n")
        f.write(f"- **color_std**: 固定为 `0.2`\n")
        f.write(f"- 每张图保持其他参数不变，仅改变目标参数（控制变量法）\n\n")
        f.write("---\n\n")

        current_cat = None
        for cat, title, rel in records:
            if cat != current_cat:
                current_cat = cat
                f.write(f"## {cat}\n\n")
            f.write(f"### {title}\n\n")
            f.write(f"![{title}]({rel})\n\n")


if __name__ == "__main__":
    main()
