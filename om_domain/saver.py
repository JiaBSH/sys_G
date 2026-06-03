"""
ISAT 格式保存器。

单一职责：将图像和多边形标注以 ISAT 格式写入磁盘。
"""

import os
import json
from .common import polygon_to_bbox


class ISATSaver:
    """以 ISAT 标注格式保存图像和 JSON。"""

    def __init__(self, category="畴区"):
        self.category = category

    def save(self, img, polygons, img_path, json_path):
        """
        保存单张样本的图像和 JSON 标注文件。

        Args:
            img: PIL Image 对象
            polygons: 多边形顶点列表
            img_path: 图像保存路径
            json_path: JSON 标注保存路径
        """
        img.save(img_path)

        objects = []
        for i, poly in enumerate(polygons, 1):
            objects.append({
                "category": self.category,
                "group": i,
                "segmentation": poly,
                "bbox": polygon_to_bbox(poly),
                "area": 0.0,
                "layer": 1.0,
                "iscrowd": False,
                "note": ""
            })

        label = {
            "info": {
                "description": "ISAT",
                "folder": os.path.dirname(img_path),
                "name": os.path.basename(img_path),
                "width": img.width,
                "height": img.height,
                "depth": 3,
                "note": ""
            },
            "objects": objects
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(label, f, indent=2, ensure_ascii=False)
