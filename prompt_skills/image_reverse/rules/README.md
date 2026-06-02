# Image Reverse Rulebook

这些规则是图片反推模型每次分析图片时必须加载的分类规则源。运行时提示词只注入短索引，完整细则在本目录维护，避免规则散落在代码中。

## 分类

- `01_overall_visible_facts.md`: 整体原则、三档反推、可见事实优先级
- `02_person_body_pose.md`: 人物、躯干、头手脚、关节链、遮挡关系
- `03_spatial_relationships.md`: 九宫格、时钟方向、镜头角度、前中后景
- `04_objects_counts_text.md`: 物品身份、数量、文字、水印、Logo
- `05_exposure_nsfw.md`: 暴露内容、成人裸露、隐私部位、性意味动作和液体
- `06_color_style_materials.md`: 颜色、光线、风格、材质纹理
- `07_output_json_quality.md`: JSON结构、正负提示词边界、去重和质量复核

