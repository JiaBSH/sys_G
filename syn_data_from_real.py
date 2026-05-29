import os
import json
import random
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import torchvision.transforms.functional as TF
from shapely.geometry import Polygon, box

# -----------------------------
# 工具函数：多边形边界处理 (保留原逻辑)
# -----------------------------
def refine_polygons(polygons, width, height):
    refined_polygons = []
    img_boundary = box(0, 0, width, height)
    
    for poly_coords in polygons:
        if len(poly_coords) < 3: continue
        is_outside = any(x < 0 or x > width or y < 0 or y > height for x, y in poly_coords)
        
        if not is_outside:
            refined_polygons.append(poly_coords)
        else:
            try:
                poly_shape = Polygon(poly_coords)
                if not poly_shape.is_valid:
                    poly_shape = poly_shape.buffer(0)
                intersected = poly_shape.intersection(img_boundary)
                
                if intersected.geom_type == 'Polygon':
                    coords = list(intersected.exterior.coords)[:-1]
                    if len(coords) >= 3: refined_polygons.append(coords)
                elif intersected.geom_type == 'MultiPolygon':
                    for p in intersected.geoms:
                        coords = list(p.exterior.coords)[:-1]
                        if len(coords) >= 3: refined_polygons.append(coords)
            except:
                continue
    return refined_polygons

def polygon_to_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]

# -----------------------------
# 新增：坐标旋转辅助
# -----------------------------
def rotate_point(point, angle_rad, cx, cy):
    """绕点(cx, cy)旋转"""
    x, y = point
    x0 = x - cx
    y0 = y - cy
    xr = x0 * math.cos(angle_rad) - y0 * math.sin(angle_rad) + cx
    yr = x0 * math.sin(angle_rad) + y0 * math.cos(angle_rad) + cy
    return [xr, yr]

# -----------------------------
# 新增：畴区实例类
# -----------------------------
class DomainInstance:
    def __init__(self, img_patch, polygon, area):
        self.image = img_patch # RGBA PIL Image (背景透明)
        self.polygon = polygon # 相对坐标
        self.area = area

# -----------------------------
# 提取素材库 (含边缘剔除 + 异常颜色过滤)
# -----------------------------
def extract_instances(json_dir, img_dir, margin=20):
    instances = []
    instance_colors = [] 
    bg_colors = [] 
    
    if not os.path.exists(json_dir):
        print(f"Error: JSON directory not found: {json_dir}")
        return [], [155, 115, 85]

    all_files = os.listdir(json_dir)
    json_files = [f for f in all_files if f.lower().endswith('.json')]
    
    filtered_edge_count = 0 
    
    for j_file in json_files:
        try:
            with open(os.path.join(json_dir, j_file), 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            
            target_name = os.path.splitext(j_file)[0]
            img_path = None
            for ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tif']:
                temp_path = os.path.join(img_dir, target_name + ext)
                if os.path.exists(temp_path):
                    img_path = temp_path
                    break
            
            if not img_path: continue

            full_img = Image.open(img_path).convert("RGBA")
            W, H = full_img.size
            full_img_np = np.array(full_img)
            bg_mask = np.ones((H, W), dtype=bool)

            for obj in data.get('objects', []):
                poly = obj.get('segmentation', [])
                if len(poly) < 3: continue

                bbox = polygon_to_bbox(poly)
                min_x, min_y = int(bbox[0]), int(bbox[1])
                max_x, max_y = int(bbox[2]) + 1, int(bbox[3]) + 1
                
                # 1. 边缘检查 (剔除截断物体)
                if (min_x < margin) or (min_y < margin) or (max_x > W - margin) or (max_y > H - margin):
                    filtered_edge_count += 1
                    continue

                min_x = max(0, min_x); min_y = max(0, min_y)
                max_x = min(W, max_x); max_y = min(H, max_y)
                
                if max_x - min_x < 5 or max_y - min_y < 5: continue

                # 切图
                patch = full_img.crop((min_x, min_y, max_x, max_y))
                rel_poly = [[p[0]-min_x, p[1]-min_y] for p in poly]
                
                # 生成Mask
                mask = Image.new("L", patch.size, 0)
                ImageDraw.Draw(mask).polygon([(x,y) for x,y in rel_poly], fill=255)
                
                patch_arr = np.array(patch)
                mask_arr = np.array(mask)
                
                # 2. 计算平均颜色
                valid_pixels = patch_arr[mask_arr > 0]
                if len(valid_pixels) == 0: continue
                mean_color = np.mean(valid_pixels[:, :3], axis=0)
                
                # 保存实例
                patch_arr[:, :, 3] = mask_arr # 更新Alpha
                final_patch = Image.fromarray(patch_arr)
                
                instances.append(DomainInstance(final_patch, rel_poly, obj.get('area', 0), mean_color))
                instance_colors.append(mean_color)
                
                bg_mask[min_y:max_y, min_x:max_x] = False

            # 统计背景
            bg_pixels = full_img_np[bg_mask]
            if len(bg_pixels) > 0:
                bg_colors.append(np.mean(bg_pixels[:, :3], axis=0))

        except Exception as e:
            print(f"[Warning] Error in {j_file}: {e}")

    # 3. 异常偏离过滤 (2-Sigma)
    filtered_outlier_count = 0
    if len(instances) > 5:
        colors_np = np.array(instance_colors)
        global_mean = np.mean(colors_np, axis=0)
        dists = np.linalg.norm(colors_np - global_mean, axis=1)
        threshold = np.mean(dists) + 2 * np.std(dists)
        
        valid_instances = []
        for i, dist in enumerate(dists):
            if dist <= threshold:
                valid_instances.append(instances[i])
            else:
                filtered_outlier_count += 1
        instances = valid_instances

    global_bg = np.mean(bg_colors, axis=0) if bg_colors else [155, 115, 85]
    print(f"[Init] Extracted {len(instances)} valid instances.")
    print(f"       - Filtered {filtered_edge_count} edge objects.")
    print(f"       - Filtered {filtered_outlier_count} color outliers.")
    
    return instances, global_bg
# -----------------------------
# 类定义：增加 color 属性
# -----------------------------
class DomainInstance:
    def __init__(self, img_patch, polygon, area, color):
        self.image = img_patch # 原始切片(含Alpha)
        self.polygon = polygon
        self.area = area
        self.color = color     # 记录该实例的平均颜色
# -----------------------------
# 生成逻辑：统一单图颜色
# -----------------------------
def generate_copy_paste_sample(instance_bank, bg_mean, image_size, num_range, size_scale_range, shape_jitter):
    W, H = image_size
    
    # 1. 生成背景
    bg_array = np.zeros((H, W, 3), dtype=np.uint8)
    for c in range(3):
        noise = np.random.normal(bg_mean[c], 5, (H, W))
        bg_array[:, :, c] = np.clip(noise, 0, 255)
    image = Image.fromarray(bg_array).convert("RGBA")

    # 2. 【关键】选定本张图的 "主题色"
    # 从素材库中随机抽一个真实颜色作为基准
    if instance_bank:
        theme_color = random.choice(instance_bank).color
    else:
        theme_color = [120, 120, 120] # Fallback

    overlap_count_map = np.zeros((H, W), dtype=np.uint8)
    id_map = np.full((H, W), -1, dtype=np.int32)
    area_registry = {} 

    final_polygons = []
    target_count = random.randint(*num_range)
    attempts = 0
    curr_id = 0
    
    while len(final_polygons) < target_count and attempts < target_count * 20:
        attempts += 1
        if not instance_bank: break
        
        inst = random.choice(instance_bank)

        # 3. 【关键】使用主题色重构 Patch
        # 获取 Mask
        mask_img = inst.image.split()[3]

        # 创建纯色底图 + 噪点
        patch_arr = np.zeros((inst.image.height, inst.image.width, 3), dtype=np.float32)
        patch_arr[:, :] = theme_color
        noise = np.random.normal(0, 3, patch_arr.shape) # 添加噪点模拟质感
        patch_arr = np.clip(patch_arr + noise, 0, 255).astype(np.uint8)

        # 合成 RGBA
        patch_colored = Image.fromarray(patch_arr).convert("RGBA")
        patch_colored.putalpha(mask_img) # 应用原始 Mask

        # 3.5 可选缩放：根据 size_scale_range 对实例进行缩放
        if isinstance(size_scale_range, (tuple, list)) and len(size_scale_range) == 2:
            scale = random.uniform(size_scale_range[0], size_scale_range[1])
        else:
            try:
                scale = float(size_scale_range)
            except:
                scale = 1.0

        if abs(scale - 1.0) > 1e-6:
            new_w = max(1, int(patch_colored.width * scale))
            new_h = max(1, int(patch_colored.height * scale))
            patch_scaled = patch_colored.resize((new_w, new_h), resample=Image.BICUBIC)
            scaled_polygon = [[p[0] * scale, p[1] * scale] for p in inst.polygon]
        else:
            patch_scaled = patch_colored
            scaled_polygon = [p[:] for p in inst.polygon]

        # 4. 旋转（在缩放后的图像上）
        angle = random.uniform(0, 5)
        patch_rot = patch_scaled.rotate(angle, expand=True, resample=Image.BICUBIC)

        cx_old, cy_old = patch_scaled.width / 2, patch_scaled.height / 2
        cx_new, cy_new = patch_rot.width / 2, patch_rot.height / 2
        rad = math.radians(-angle)

        new_poly_rel = []
        # 可选：对多边形顶点加入高斯噪声（像素），在缩放后、旋转前应用
        if shape_jitter and shape_jitter > 1e-6:
            jittered_polygon = []
            for x, y in scaled_polygon:
                jx = x + random.gauss(0, shape_jitter)
                jy = y + random.gauss(0, shape_jitter)
                jittered_polygon.append([jx, jy])
        else:
            jittered_polygon = scaled_polygon
            #print("No shape jitter applied.")

        for p in jittered_polygon:
            pr = rotate_point(p, rad, cx_old, cy_old)
            pr[0] += (cx_new - cx_old)
            pr[1] += (cy_new - cy_old)
            new_poly_rel.append(pr)

        # 5. 放置与检测
        paste_x = random.randint(-int(patch_rot.width/2), W - int(patch_rot.width/2))
        paste_y = random.randint(-int(patch_rot.height/2), H - int(patch_rot.height/2))
        
        abs_poly = [[x + paste_x, y + paste_y] for x, y in new_poly_rel]
        
        try:
            temp_mask = Image.new("L", (W, H), 0)
            draw_poly = [(int(x), int(y)) for x, y in abs_poly]
            ImageDraw.Draw(temp_mask).polygon(draw_poly, fill=1)
        except: continue
        
        mask_bool = np.array(temp_mask) == 1
        mask_area = mask_bool.sum()
        if mask_area < 50: continue

        # QC 检测
        is_valid = True
        sampled_ids, counts = np.unique(id_map[mask_bool], return_counts=True)
        for eid, count in zip(sampled_ids, counts):
            if eid != -1 and count > area_registry[eid] * 0.85: 
                is_valid = False; break
        if not is_valid: continue
        if (sampled_ids != -1).sum() > mask_area * 0.85: continue
        
        existing_overlap = overlap_count_map[mask_bool]
        if (existing_overlap >= 1).sum() / mask_area > 0.3: continue 

        image.paste(patch_rot, (paste_x, paste_y), patch_rot)
        
        overlap_count_map[mask_bool] += 1
        id_map[mask_bool] = curr_id
        area_registry[curr_id] = mask_area
        curr_id += 1
        
        final_polygons.append(abs_poly)

    return image.convert("RGB"), final_polygons
# -----------------------------
# 显微镜增强 (保留)
# -----------------------------
def microscopy_augment(img):
    angle = 0.0
    # 稍微降低了旋转概率，因为前面已经旋转过物体了
    if random.random() < 0: 
        angle = random.uniform(-180, 180)
        img = TF.rotate(img, angle, expand=False)
    
    if random.random() < 0.8:
        img = TF.adjust_brightness(img, random.uniform(0.8, 1.3))
    if random.random() < 0.8:
        img = TF.adjust_contrast(img, random.uniform(0.8, 1.3))
    
    # 增加一点高斯模糊模拟对焦
    if random.random() < 1:
        img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(2, 4)))
        
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
# 主程序
# -----------------------------
def generate_dataset(source_json, source_img, output_root, n=100, size_scale_range=(0.3, 0.6), shape_jitter=0):
    # 1. 提取素材
    instances, bg_mean = extract_instances(source_json, source_img)
    if not instances: return

    img_dir = os.path.join(output_root, "image")
    lab_dir = os.path.join(output_root, "label")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(lab_dir, exist_ok=True)

    print(f"[Start] Generating {n} images...")

    for i in range(n):
        # 2. 生成 (Copy-Paste)
        img, polygons = generate_copy_paste_sample(
            instances, bg_mean, 
            image_size=(1024, 1024), 
            num_range=(15, 22),
            size_scale_range=size_scale_range,
            shape_jitter=shape_jitter
        )

        # 3. 增强
        img, angle = microscopy_augment(img)
        W, H = img.size
        
        # 4. 全局旋转时的坐标跟随
        if abs(angle) > 1e-6:
            cx, cy = W / 2, H / 2
            rad = math.radians(-angle)
            new_polys = []
            for poly in polygons:
                new_polys.append([rotate_point(p, rad, cx, cy) for p in poly])
            polygons = new_polys

        # 5. 边界截断
        final_polygons = refine_polygons(polygons, W, H)
        
        # 6. 保存
        name = f"syn_real_{i:05d}"
        save_isat_sample(
            img,
            final_polygons,
            os.path.join(img_dir, name + ".png"),
            os.path.join(lab_dir, name + ".json")
        )

        if (i+1) % 10 == 0:
            print(f"Generated {i+1}/{n}")


if __name__ == "__main__":
    # --- 配置路径 ---
    # 请修改为你的真实数据路径
    SOURCE_JSON_DIR = "data/train_label" 
    SOURCE_IMG_DIR = "data/train_image"
    OUTPUT_DIR = "data/train/output"
    
    # 运行
    generate_dataset(SOURCE_JSON_DIR, SOURCE_IMG_DIR, OUTPUT_DIR, n=10)
    pass