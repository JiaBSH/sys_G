import os
import json
import random
import math
import numpy as np
from PIL import Image, ImageDraw
import torchvision.transforms.functional as TF
from shapely.geometry import Polygon, box
def refine_polygons(polygons, width, height):
    """
    只处理越界的多边形，确保其在边界处共线截断
    """
    refined_polygons = []
    # 定义图像边界框
    img_boundary = box(0, 0, width, height)
    
    for poly_coords in polygons:
        # 1. 快速检查：是否有顶点在图像外
        is_outside = any(x < 0 or x > width or y < 0 or y > height for x, y in poly_coords)
        
        if not is_outside:
            # 完全在内部，直接添加，不进行任何数学运算
            refined_polygons.append(poly_coords)
        else:
            # 2. 只有越界了，才执行几何裁剪
            poly_shape = Polygon(poly_coords)
            
            # 如果多边形无效（例如自交），进行修正
            if not poly_shape.is_valid:
                poly_shape = poly_shape.buffer(0)
            
            # 计算多边形与图像矩形的交集 (核心：自动计算共线交点)
            intersected = poly_shape.intersection(img_boundary)
            
            # 处理裁剪后可能变成多个多边形或非多边形的情况
            if intersected.geom_type == 'Polygon':
                coords = list(intersected.exterior.coords)[:-1] # 去掉重复的终点
                refined_polygons.append(coords)
            elif intersected.geom_type == 'MultiPolygon':
                for p in intersected.geoms:
                    refined_polygons.append(list(p.exterior.coords)[:-1])
                    
    return refined_polygons
# -----------------------------
# 生成六边形
# -----------------------------
def random_hexagon(cx, cy, r, jitter=0.05):
    # 随机生成一个初始旋转角度 (0 到 60 度之间)
# 80% 的概率取向接近 0 度，20% 的概率完全随机
    if random.random() < 0.95:
        start_angle = np.random.normal(0, np.radians(1)) # 均值为0，标准差2度的扰动
    else:
        start_angle = np.random.normal(0, np.radians(15))
    
    # 将初始角度加到 linspace 生成的基础角度上
    angles = np.linspace(0, 2*np.pi, 6, endpoint=False) + start_angle
    
    poly = []
    for a in angles:
        rr = r * (1 + np.random.uniform(-jitter, jitter))
        poly.append([
            float(cx + rr * np.cos(a)),
            float(cy + rr * np.sin(a))
        ])
    return poly


# -----------------------------
# PIL 坐标系下 polygon 旋转
# -----------------------------
def rotate_polygon(poly, angle_deg, cx, cy):
    angle = math.radians(angle_deg)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    new_poly = []
    for x, y in poly:
        x0 = x - cx
        y0 = y - cy
        xr = x0 * cos_a - y0 * sin_a + cx
        yr = x0 * sin_a + y0 * cos_a + cy
        new_poly.append([float(xr), float(yr)])
    return new_poly


def polygon_to_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


# -----------------------------
# 生成单张样本
# -----------------------------
def generate_synthetic_sample(image_size=(512, 512), num_domains=(8, 15)):
    W, H = image_size

    bg = np.zeros((H, W, 3), dtype=np.uint8)
    for c, m in enumerate([155, 115, 85]):
        bg[:, :, c] = np.clip(np.random.normal(m, 3, (H, W)), 0, 255)

    image = Image.fromarray(bg)

    polygons = []
    colors = []

    for _ in range(random.randint(*num_domains)):
        cx = random.randint(0, W-1)
        cy = random.randint(0, H-1)
        r = random.randint(25, 60)

        poly = random_hexagon(cx, cy, r)

        mask_img = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask_img).polygon(
            [(int(x), int(y)) for x, y in poly],
            fill=1
        )
        mask = np.array(mask_img)

        if mask.sum() < 50:
            continue

        color = [
            int(np.clip(np.random.normal(163, 0), 0, 255)),
            int(np.clip(np.random.normal(138, 0), 0, 255)),
            int(np.clip(np.random.normal(127, 0), 0, 255))
        ]

        img_arr = np.array(image)
        for c in range(3):
            img_arr[mask == 1, c] = color[c]
        image = Image.fromarray(img_arr)

        polygons.append(poly)
        colors.append(color)

    return image, polygons


# -----------------------------
# 显微镜增强（返回角度）
# -----------------------------
def microscopy_augment(img):
    angle = 0.0
    if random.random() < 0.0:
        angle = random.uniform(30, 60)
        img = TF.rotate(img, angle, expand=False)
    if random.random() < 0.8:
        img = TF.adjust_brightness(img, random.uniform(0.9, 1.3))
    if random.random() < 0.5:
        img = TF.adjust_contrast(img, random.uniform(0.9, 1.1))
    if random.random() < 0.5:
        img = TF.adjust_gamma(img, random.uniform(0.9, 1.1))
    return img, angle


# -----------------------------
# 保存 ISAT
# -----------------------------
def save_isat_sample(img, polygons, img_path, json_path):
    img.save(img_path)

    objects = []
    for i, poly in enumerate(polygons, 1):
        objects.append({
            "category": "畴区",
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

# -----------------------------
# 生成单张样本 (增加重叠控制)
# -----------------------------
def generate_synthetic_sample_qc(image_size=(512, 512), 
                                mag_factor=1.0,      
                                supersample_ratio=1, 
                                base_r_range=(60, 90), 
                                base_num_range=(4, 6)):
    # --- [修改1] 画布尺寸预先扩大 (超采样) ---
    W_orig, H_orig = image_size
    W, H = W_orig * supersample_ratio, H_orig * supersample_ratio

    # 1. 根据倍率调整半径 (半径也要乘超采样系数)
    r_min = int(base_r_range[0] * mag_factor * supersample_ratio)
    r_max = int(base_r_range[1] * mag_factor * supersample_ratio)
    
    # 2. 根据倍率调整数量 (密度逻辑不变)
    avg_num = (base_num_range[0] + base_num_range[1]) / 2
    count_scaled = max(2, int(avg_num / (mag_factor**2)))
    num_domains = (max(1, count_scaled - 2), count_scaled + 2)

    # 3. 初始化背景
    bg = np.zeros((H, W, 3), dtype=np.uint8)
    for c, m in enumerate([153, 115, 85]):
        bg[:, :, c] = np.clip(np.random.normal(m, 3, (H, W)), 0, 255)
    image = Image.fromarray(bg)

    # --- [修改2] 初始化全局 ID 图和面积登记表 ---
    overlap_count_map = np.zeros((H, W), dtype=np.uint8)
    id_map = np.full((H, W), -1, dtype=np.int32) # 记录每个像素被哪个 ID 覆盖
    area_registry = {} # 记录每个畴区的初始面积: {id: area}
    
    polygons = []
    target_count = random.randint(*num_domains)
    attempts = 0
    max_attempts = target_count * 20  
    curr_id = 0

    while len(polygons) < target_count and attempts < max_attempts:
        attempts += 1
        
        margin = int(r_max)
        cx = random.randint(-margin, W + margin)
        cy = random.randint(-margin, H + margin)
        r = random.randint(r_min, r_max)
        poly = random_hexagon(cx, cy, r)
        '''
        is_outside = False
        for px, py in poly:
            if px <= 1 or px >= W-1 or py <= 1 or py >= H-1:
                is_outside = True
                break
        if is_outside:
            continue
        '''
        mask_img = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask_img).polygon([(int(x), int(y)) for x, y in poly], fill=1)
        new_mask = np.array(mask_img) == 1 # 转换为布尔矩阵
        new_mask_area = new_mask.sum()
        if new_mask_area < 10 * supersample_ratio: continue
  
        # --- [修改3] 全局包含检测逻辑 (替换了原来的 for 循环) ---
        is_valid = True
        # 提取当前区域已有的 ID 情况
        sampled_ids, counts = np.unique(id_map[new_mask], return_counts=True)
        
        for eid, count in zip(sampled_ids, counts):
            if eid != -1: # 如果该像素点已经属于某个旧畴区
                # 判定：新畴区是否几乎完全覆盖了某个旧畴区
                if count > area_registry[eid] * 0.85: 
                    is_valid = False; break
        
        if not is_valid: continue

        # 判定：新畴区是否几乎完全被旧畴区群体遮挡
        if (sampled_ids != -1).sum() > new_mask_area * 0.85:
             continue

        # --- 重叠逻辑控制 ---
        existing_overlap = overlap_count_map[new_mask]
        overlap_ratio = (existing_overlap >= 1).sum() / new_mask_area
        has_q_overlap = (existing_overlap >= 3).any()

        if overlap_ratio > 0.2 or has_q_overlap:
            continue 

        # --- [修改4] 确认放置，更新全局状态 ---
        overlap_count_map[new_mask] += 1
        id_map[new_mask] = curr_id # 记录当前 ID
        area_registry[curr_id] = new_mask_area # 登记面积
        curr_id += 1

        # 颜色生成 (维持原逻辑)
        color = [int(np.clip(np.random.normal(c, 0), 0, 255)) for c in [163, 138, 127]]
        img_arr = np.array(image)
        for c in range(3):
            img_arr[new_mask, c] = color[c]
        image = Image.fromarray(img_arr)

        # 记录多边形 (坐标除以超采样系数还原)
        polygons.append([[p[0]/supersample_ratio, p[1]/supersample_ratio] for p in poly])

    # --- [修改5] 最终抗锯齿缩放 ---
    #polygons = refine_polygons(polygons, W, H)
    final_image = image.resize((W_orig, H_orig), Image.LANCZOS)
    #final_image = image.resize((W_orig, H_orig))
    
    return final_image, polygons
# -----------------------------
# 批量生成
# -----------------------------
def generate_dataset(root="./data/syn_data_1229_test_m02_d", n=1000):
    img_dir = os.path.join(root, "image")
    lab_dir = os.path.join(root, "label")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(lab_dir, exist_ok=True)

    for i in range(n):
        #m_factor = random.uniform(0.4, 3.0)
        img, polygons = generate_synthetic_sample_qc(mag_factor=0.2)

        img, angle = microscopy_augment(img)
        W, H = img.size # 获取最终图像的准确尺寸 (512, 512)
        if abs(angle) > 1e-6:
            cx, cy = img.width / 2, img.height / 2
            polygons = [
                rotate_polygon(poly, -angle, cx, cy)
                for poly in polygons
            ]
        final_polygons = refine_polygons(polygons, W, H)
        valid_polygons = [p for p in final_polygons if len(p) >= 3]

        if not valid_polygons:
            i-=1
            continue # 如果整张图都没有有效畴区，跳过
        name = f"syn_{i:05d}"
        save_isat_sample(
            img,
            valid_polygons,
            os.path.join(img_dir, name + ".png"),
            os.path.join(lab_dir, name + ".json")
        )

        if i % 50 == 0:
            print(f"[INFO] {i}/{n}")


if __name__ == "__main__":
    generate_dataset(n=10)
