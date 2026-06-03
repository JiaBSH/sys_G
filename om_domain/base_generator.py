"""
畴区生成器抽象基类。

依赖倒置原则 (DIP)：DatasetPipeline 依赖此抽象接口，
而非具体的 HexagonGenerator 或 CopyPasteGenerator。
接口隔离原则 (ISP)：仅暴露一个 generate 方法。
"""

from abc import ABC, abstractmethod


class BaseDomainGenerator(ABC):
    """生成畴区的抽象接口。所有生成器必须实现 generate 方法。"""

    @abstractmethod
    def generate(self, image_size, **kwargs):
        """
        生成单张图像及其畴区多边形。

        Args:
            image_size: (width, height) 目标图像尺寸

        Returns:
            (PIL.Image, list of polygons): 图像和多边形列表，
            多边形坐标为图像坐标系下的绝对坐标。
        """
        pass
