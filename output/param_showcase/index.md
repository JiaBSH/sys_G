# 参数效果展示 — 索引 (color_std=0.2)

- **随机种子**: `42`
- **图像尺寸**: `1024×1024`
- **基准参数**: 与 `gen_multi_mag.py` 的 `SHARED_GEN_KWARGS` 一致
- **color_std**: 固定为 `0.2`
- 每张图保持其他参数不变，仅改变目标参数（控制变量法）

---

## 生成器参数 (color_std=0.2)

### color_std — Inter-domain Color Variation

![color_std — Inter-domain Color Variation](gen_color_std_—_Inter-domain_Color_Variation.png)

### texture_std — Intra-domain Texture Noise

![texture_std — Intra-domain Texture Noise](gen_texture_std_—_Intra-domain_Texture_Noise.png)

### bg_noise_std — Background Noise

![bg_noise_std — Background Noise](gen_bg_noise_std_—_Background_Noise.png)

### color_mean — Domain Hue

![color_mean — Domain Hue](gen_color_mean_—_Domain_Hue.png)

### bg_mean — Background Hue

![bg_mean — Background Hue](gen_bg_mean_—_Background_Hue.png)

### base_r_range — Domain Radius Range

![base_r_range — Domain Radius Range](gen_base_r_range_—_Domain_Radius_Range.png)

### shape_jitter — Vertex Radial Perturbation

![shape_jitter — Vertex Radial Perturbation](gen_shape_jitter_—_Vertex_Radial_Perturbation.png)

### size_std — Size Distribution

![size_std — Size Distribution](gen_size_std_—_Size_Distribution.png)

### base_num_range — Domain Count Range

![base_num_range — Domain Count Range](gen_base_num_range_—_Domain_Count_Range.png)

### edge_burr_amplitude — Edge Roughness Amplitude

![edge_burr_amplitude — Edge Roughness Amplitude](gen_edge_burr_amplitude_—_Edge_Roughness_Amplitude.png)

### edge_burr_subdivisions — Edge Subdivision Density

![edge_burr_subdivisions — Edge Subdivision Density](gen_edge_burr_subdivisions_—_Edge_Subdivision_Density.png)

### max_overlap_ratio — Max Overlap Ratio

![max_overlap_ratio — Max Overlap Ratio](gen_max_overlap_ratio_—_Max_Overlap_Ratio.png)

### max_overlap_count — Max Pixel Coverage Layers

![max_overlap_count — Max Pixel Coverage Layers](gen_max_overlap_count_—_Max_Pixel_Coverage_Layers.png)

### contain_threshold — Containment Threshold

![contain_threshold — Containment Threshold](gen_contain_threshold_—_Containment_Threshold.png)

### supersample_ratio — Anti-aliasing Supersampling

![supersample_ratio — Anti-aliasing Supersampling](gen_supersample_ratio_—_Anti-aliasing_Supersampling.png)

