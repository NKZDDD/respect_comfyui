# 空间坐标、机位Rig与多视角一致性

## 目录

1. 核心结论
2. 空间资产分层
3. Spatial Master坐标合同
4. Geometry Proxy
5. Canonical Location View
6. 多视角闭环校验
7. 人物与道具的World Placement
8. Storyboard与Video的空间执行
9. 空间资产冻结条件
10. 完整Prompt结构
11. 常见失败与修复

## 1. 核心结论

同一场景的不同视角不能分别让图像模型自由设计。每个视角都必须是同一个Spatial Master和同一个Geometry Proxy的投影结果。

正式关系：

```text
LOC Appearance Authority
+ SPATIAL World Geometry Authority
+ approved Camera Rig
↓
CANONICAL LOCATION VIEW
↓ approved views only
LOCATION VIEW SET / PR
```

`LOC`回答“长什么样”，`SPATIAL`回答“物理上如何构成”，`LOC_VIEW`回答“从一个批准机位如何看见同一物理空间”。多角度Sheet只能汇编已批准视角，不能一次性要求模型在一张图里独立想象多个视角。

## 2. 空间资产分层

### LOC｜Appearance Kit

控制建筑语言、材质、色彩、固定设施的视觉设计、地域和文化。LOC示例图的透视和摆放不自动成为Geometry Canon。

### SPATIAL｜World Geometry

控制坐标系、尺度、Topology、Zone、Anchor、Route、墙体、门窗、固定家具、层高、开口和连接关系。

### GEO_PROXY｜Geometry Proxy

把SPATIAL物理化为可从不同机位一致观察的简化3D块模、2.5D轴测体或严格测绘代理。它控制几何投影，不控制材质风格。

### LOC_VIEW｜Canonical Location View

从同一GEO_PROXY和指定Camera Rig生成的一张批准视角。它继承LOC外观和SPATIAL几何，但不控制人物Blocking。

### LOC_VIEWSET / PR｜Approved View Index

按空间覆盖需求登记多个已批准`LOC_VIEW`。Sheet若存在，只是索引/展示，不是重新生成或平均融合视角。

## 3. Spatial Master坐标合同

每个Spatial Revision必须冻结：

```text
spatial_revision_id
parent_spatial_revision_id
coordinate_system = right_handed | declared alternative
origin_anchor_id
origin_xyz_m = [0, 0, 0]
axis_definition = +X / +Y / +Z
unit = meter
level_elevations
outer_boundary
walkable_surfaces
fixed_geometry
zones
anchors_xyz
routes_as_ordered_anchor_paths
door_window_opening_direction
fixed_furniture_bbox
scale_anchors
temporary_obstacles
forbidden_geometry_changes
```

Anchor不能只写“门边”“床旁”。至少写唯一完整Canonical Revision ID或Spatial成员ID、`xyz`、所属Zone、朝向和与固定结构的距离。Route必须以同一坐标系的Anchor序列表达。

### 坐标不是画面左右

`+X`、`+Y`、`+Z`和Anchor关系属于Physical Truth；“画面左侧”“右后方”只属于某个Camera Observation。切换机位后重新投影Screen Direction，不改变World Placement。

## 4. Geometry Proxy

以下情况默认使用3D或2.5D Geometry Proxy：

- 同一场景出现三个及以上显著不同机位。
- 有环绕、跟拍、穿门、跨Zone或长距离移动。
- 门窗、病床、桌椅、车辆、楼梯等固定关系承担剧情。
- 同一场景跨多集重复使用。
- 图像模型已经出现视角无法拼合、镜像或比例漂移。

推荐优先级：

```text
真实3D Blockout / 摄影测量
> 尺寸化2.5D平面 + 轴测
> 仅文本坐标合同
> 独立AI多视角图
```

最后一项不能独立通过空间冻结。没有3D工具时，至少建立带尺寸的平面、立面/轴测、Anchor坐标和视角重叠Landmark。

## 5. Canonical Location View

每个View单独生成、校验和登记，使用完整Revision ID。例如：

```text
PRJ_NOVA__LOC_001_VIEW_A01_R01
PRJ_NOVA__LOC_001_VIEW_A02_R01
PRJ_NOVA__LOC_001_VIEWSET01_R01
```

每个View合同包含：

```text
view_revision_id
source_loc_revision_id
source_spatial_revision_id
source_geo_proxy_revision_id
camera_anchor_xyz_m
look_at_xyz_m
camera_height_m
yaw_pitch_roll_deg
lens_mm_or_horizontal_fov
aspect_ratio
visible_zones
occluded_zones
visible_landmarks
scale_anchors
overlap_landmarks_with_adjacent_views
allowed_crop
forbidden_geometry_changes
```

同一View的材质、固定设施和Landmark来自LOC；其透视、遮挡顺序、相对位置和尺度来自Geometry Proxy。不得用生成结果反向改写Spatial Master。

### Coverage不足

Storyboard或Video所需机位超出已批准View覆盖时，只能：

1. 从同一Geometry Proxy建立新`LOC_VIEW`并批准；或
2. 直接使用Geometry Proxy作为该机位空间Authority。

不得让Storyboard或Video模型补想看不见的另一侧空间。

## 6. 多视角闭环校验

每个新View必须与至少一个相邻已批准View共享两个以上可识别Landmark，并执行闭环核对：

```text
door/window count and ordering
wall/opening connectivity
fixed furniture identity and bbox
route continuity
landmark relative distance
ceiling/floor height
mirror status
occlusion order
scale consistency
view overlap correspondence
```

若A能看见门与床、B也能看见门与床，两者必须能由同一组World坐标解释。无法解释时，View保持`CANDIDATE`，不得进入PR、SCSTATE或Storyboard。

一张漂亮但无法回投到Spatial坐标的图，不是Canonical Location View。

## 7. 人物与道具的World Placement

CVS、SCSTATE和KF中人物/关键Prop位置至少写：

```text
entity_revision_id
root_or_foot_point_xyz_m
anchor_id + local_offset_xyz_m
orientation_yaw_deg
posture_footprint_or_bbox
ground_contact_surface
eye_target_xyz_or_entity
hand_contact_target
distance_to_key_landmarks
movement_route_id
```

对于坐/躺/跪姿，用身体支撑点、身体轴线和占地包围盒补充Foot Point。道具使用自身Pivot、Holder/Container和Anchor；不能只写“在人物左边”。

不同Camera View只投影同一World Placement。禁止为保持构图美观，让人物在切镜时静默换到另一个Zone、门的另一侧或走廊镜像位置。

## 8. Storyboard与Video的空间执行

### Storyboard

每个KF绑定：

```text
source_spatial_revision_id
source_location_view_id_or_geo_proxy_id
camera_rig
entity_world_placement
screen_projection_result
view_coverage_status = COVERED | NEW_VIEW_REQUIRED | BLOCKED
```

Storyboard可重新构图和裁切，但不能修改World Placement或固定Geometry。`NEW_VIEW_REQUIRED`必须在出图前回到Location View生产。

### Video

Video Window冻结Camera Path在World坐标中的起点、终点、朝向与安全范围。人物移动使用World Route，不使用画面像素平移。Camera运动不得越出已批准Geometry覆盖，也不得因遮挡重建另一套房间结构。

## 9. 空间资产冻结条件

F2 Visual Canon Freeze前必须全部通过：

- Spatial坐标、单位、原点、轴向和Revision明确。
- 固定Geometry、Anchor、Route和Scale可测量。
- 高风险空间已有Geometry Proxy。
- 每个必要机位来自同一Proxy，不是独立自由生成。
- View间Landmark闭环一致，可解释遮挡和尺度。
- 无镜像、门窗数量变化、家具换位或连接关系冲突。
- View文件、完整Revision ID、路径和Fingerprint已登记。

任一失败，空间资产不得标记`CANONICAL`，下游Prompt不得用故事板融合效果掩盖问题。

## 10. 完整Prompt结构

生成`LOC_VIEW`时至少包含：

1. Target Canonical Revision ID。
2. LOC、SPATIAL、GEO_PROXY完整Reference Manifest。
3. World Coordinate Contract。
4. Exact Camera Rig。
5. Visible/Hidden Zone与Landmark清单。
6. 与相邻View的Overlap Landmarks。
7. MUST PRESERVE Appearance与Geometry。
8. MUST NOT COPY示意图排版、人物、临时Prop和无关Camera。
9. Forbidden Geometry Changes。
10. 单一视角输出格式。

禁止使用“同一场景，请生成多个角度”作为唯一几何约束。

## 11. 常见失败与修复

| 失败 | 根因 | 修复 |
|---|---|---|
| 同场景多视角拼不起来 | 每个视角独立生图 | 同一Geometry Proxy逐View投影 |
| 门窗左右互换 | 把画面左右当物理方向 | World坐标 + Camera投影 |
| 床/桌比例变化 | 无尺度和BBox | Meter单位 + Scale Anchor + Fixed BBox |
| 人物切镜后换位置 | Blocking只写构图位置 | Root XYZ + Anchor Offset + Orientation |
| 环绕后出现新房间 | Camera超出视角覆盖 | 新建View或使用Proxy；未覆盖则阻断 |
| 一张多视图Sheet内部矛盾 | 一次调用同时发明多视角 | 单View生产、闭环批准后再汇编 |
| Storyboard看似修好但视频仍漂 | 上游空间Candidate未冻结 | 不把融合效果当Geometry通过依据 |
| LOC图强迫PR复制机位 | Appearance与Geometry混权 | LOC仅管视觉，Proxy/View管投影 |
