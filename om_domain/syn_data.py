"""
合成畴区数据集生成 — 入口脚本。

通过 HexagonGenerator 在带噪背景上随机放置六边形畴区，
经 MicroscopyAugment 模拟显微镜成像效果后保存为标注数据集。

运行方式: python -m om_domain.syn_data
"""

from om_domain.pipeline import DatasetPipeline
from om_domain.hexagon_generator import HexagonGenerator
from om_domain.augment import MicroscopyAugment


def main():
    # =========================================================================
    # 生成器配置 — HexagonGenerator
    # =========================================================================
    generator = HexagonGenerator(
        # -- 颜色 / 纹理 --
        color_mean=(163, 138, 127),   # 畴区颜色 RGB 均值
        bg_mean=(153, 115, 85),       # 背景颜色 RGB 均值
        color_std=0.5,                   # 畴区间颜色标准差，越大各畴区色差越大
        texture_std=8,                 # 畴区内部纹理噪声标准差，越大纹理越粗糙
        bg_noise_std=3,                # 背景噪声标准差，越大背景越粗糙
        # -- 几何 / 尺寸 --
        base_r_range=(50, 90),         # 基础半径范围 (min, max)，随 mag_factor 线性缩放
        base_num_range=(20, 40),         # 基础数量范围 (min, max)，随 mag_factor² 反比缩放
        size_std=20,                   # 畴区半径标准差；None=均匀分布，数值=正态分布（均值取 base_r_range 中点）
        mag_factor=0.2,                  # 畴区缩放倍率；>1 放大畴区，<1 缩小畴区
        shape_jitter=0.1,              # 顶点径向扰动比例；0=正六边形，越大形状越不规则
        # -- 边缘毛刺（生长粗糙度）--
        edge_burr_amplitude=0.1,      # 边缘毛刺振幅（相对边长）；0=光滑，0.05=明显毛刺
        edge_burr_subdivisions=4,       # 每条边细分点数；越大毛刺越细密
        # -- 重叠控制 --
        max_overlap_ratio=0.5,         # 单个畴区允许的最大重叠比例 [0,1]
        max_overlap_count=3,           # 单个像素允许被覆盖的最大畴区数
        contain_threshold=0.85,        # 包含判定阈值；新畴区覆盖某旧畴区超此比例则拒绝
        min_area_factor=10,            # 最小有效面积因子，实际 min_area = factor × supersample_ratio
        # -- 渲染 --
        supersample_ratio=1,           # 超采样倍率（抗锯齿）；1=不超采样，>1 以更高分辨率渲染后降采样
    )

    # =========================================================================
    # 增强器配置 — MicroscopyAugment
    # =========================================================================
    augmenter = MicroscopyAugment(
        # -- 亮度 --
        brightness_range=(0.7, 1),   # 亮度调整因子范围（<1 变暗，>1 变亮）
        brightness_prob=0.8,            # 亮度调整触发概率 [0,1]
        # -- 对比度 --
        contrast_range=(0.5, 1),      # 对比度调整因子范围（<1 降低，>1 增强）
        contrast_prob=0.8,              # 对比度调整触发概率 [0,1]
        # -- Gamma --
        gamma_range=(0.9, 1.1),         # Gamma 校正范围（<1 提亮暗部，>1 压暗亮部）
        gamma_prob=0.5,                 # Gamma 调整触发概率 [0,1]
        # -- 模糊 --
        blur_range=(0.5, 1.5),             # 高斯模糊半径范围（像素），越大模糊越强
        blur_prob=1,                    # 高斯模糊触发概率 [0,1]
        # -- 椒盐噪声（传感器坏点/脉冲噪声）--
        sp_noise_prob=0,             # 椒盐噪声触发概率 [0,1]
        sp_noise_amount=0.005,          # 噪声像素占比，典型值 0.001~0.02
        sp_noise_salt_ratio=0.5,        # 白点（盐）占比，余量为黑点（胡椒）
        # -- 旋转 --
        rotate_prob=0.0,                # 图像旋转触发概率；0=不旋转
    )

    # =========================================================================
    # 流水线 — DatasetPipeline
    # =========================================================================
    pipeline = DatasetPipeline(generator, augmenter)

    pipeline.run(
        output_root="./data/syn_data",   # 输出根目录，自动创建 image/ 和 label/ 子目录
        n=10,                              # 生成样本数量
        name_prefix="syn_g_edge_02",              # 输出文件名前缀
        image_size=(1024, 800)              # 输出图像尺寸 (width, height)
    )


if __name__ == "__main__":
    main()
