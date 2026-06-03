"""
重叠控制器 — 在图像上放置新畴区时检测并控制重叠程度。

单一职责：验证新畴区的放置是否满足重叠约束，并在确认后登记。
从两个生成器中提取了完全相同的 id_map / overlap_count_map / area_registry 逻辑。
"""

import numpy as np


class OverlapController:
    """
    控制畴区放置时的重叠约束。

    维护三张状态图：
    - overlap_count_map: 每个像素被多少畴区覆盖
    - id_map: 每个像素属于哪个畴区 ID
    - area_registry: 每个畴区 ID 的原始面积

    约束规则：
    1. 新畴区不能几乎完全包含某个旧畴区（contain_threshold）
    2. 新畴区不能几乎完全被旧畴区群体覆盖（contain_threshold）
    3. 新畴区与已有畴区的重叠比例不能超过 max_overlap_ratio
    4. 任何像素不能被超过 max_overlap_count 个畴区覆盖（可选）
    """

    def __init__(self, width, height,
                 max_overlap_ratio=0.2,
                 max_overlap_count=None,
                 contain_threshold=0.85,
                 min_area=50):
        """
        Args:
            width, height: 画布尺寸
            max_overlap_ratio: 新畴区允许的最大重叠比例
            max_overlap_count: 单个像素允许的最大重叠次数（None 则不检查）
            contain_threshold: 包含判定阈值（面积比）
            min_area: 最小有效面积（像素）
        """
        self.overlap_count_map = np.zeros((height, width), dtype=np.uint8)
        self.id_map = np.full((height, width), -1, dtype=np.int32)
        self.area_registry = {}
        self.max_overlap_ratio = max_overlap_ratio
        self.max_overlap_count = max_overlap_count
        self.contain_threshold = contain_threshold
        self.min_area = min_area
        self._curr_id = 0

    def check(self, mask_bool):
        """
        检查新畴区是否可以放置在指定位置。

        Args:
            mask_bool: 布尔数组，True 表示新畴区覆盖的像素

        Returns:
            (is_valid, mask_area): 是否允许放置，以及 mask 面积
        """
        mask_area = int(mask_bool.sum())

        if mask_area < self.min_area:
            return False, mask_area

        # 检查是否几乎完全包含某个已有畴区
        sampled_ids, counts = np.unique(self.id_map[mask_bool], return_counts=True)
        for eid, count in zip(sampled_ids, counts):
            if eid != -1 and count > self.area_registry[eid] * self.contain_threshold:
                return False, mask_area

        # 检查是否几乎完全被已有畴区覆盖
        covered_by_existing = (sampled_ids != -1).sum()
        if covered_by_existing > mask_area * self.contain_threshold:
            return False, mask_area

        # 检查重叠比例
        existing_overlap = self.overlap_count_map[mask_bool]
        overlap_ratio = (existing_overlap >= 1).sum() / mask_area
        if overlap_ratio > self.max_overlap_ratio:
            return False, mask_area

        # 检查最大重叠次数（可选）
        if self.max_overlap_count is not None:
            if (existing_overlap >= self.max_overlap_count).any():
                return False, mask_area

        return True, mask_area

    def commit(self, mask_bool):
        """确认放置，更新内部状态。"""
        mask_area = int(mask_bool.sum())
        self.overlap_count_map[mask_bool] += 1
        self.id_map[mask_bool] = self._curr_id
        self.area_registry[self._curr_id] = mask_area
        self._curr_id += 1
