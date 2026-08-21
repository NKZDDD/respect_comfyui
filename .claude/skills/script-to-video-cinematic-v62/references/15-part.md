第十五部分｜同场景兼容机位合并生产
1. 目的
减少同一场景相邻机位被逐张重复生成的调用次数，同时保持每个机位的Canonical身份、分辨率、Camera Authority和下游可引用性。
本机制只处理“已经证明必要的View如何合并生产”。在进入本文件前必须先按[场景机位覆盖规划与重复视图控制](16-location-view-coverage-and-redundancy-control.md)完成Story/Shot Spatial Demand、Location View Coverage Plan、View Utility Contract与View Distinctness Gate。
核心原则：
[text]可以合并生产调用≠ 合并Canonical View身份≠ 证明每个View都值得存在≠ 允许模型自由发明多角度≠ 下游上传整张多机位图
2. 三种模式
A. SINGLE_VIEW
一个调用只生成一个LOC_VIEW。用于高风险空间、独立高分辨率机位或不兼容机位。
B. VIEW_BATCH
一个调用生成2至3个独立输出文件。每个Output Index绑定一个完整LOC_VIEW Revision ID。优先使用此模式。
C. VIEWPACK_ATLAS
模型一次只能返回一张图时，生成固定2×2 Atlas。最多使用三个电影Panel：
[text]TOP_LEFT     = Child View 1TOP_RIGHT    = Child View 2BOTTOM_LEFT  = Child View 3BOTTOM_RIGHT = Geometry Check Panel或空白校验区
输出后必须无损裁切为独立子View文件。不得把Atlas直接投入SCSTATE、Storyboard或Video。
3. 合并资格
全部满足才允许合并：
每个View的utility_decision为REQUIRED或有明确理由的OPTIONAL；REDUNDANT/BLOCKED不得入组。
每个View有明确Role、独有Coverage与至少一个Story/Shot/KF/Camera Reveal消费者。
同一Location、Spatial、Geometry Proxy完整Revision。
同一Reality Thread、Story Time、天气、光线与环境状态。
同一Camera Cluster或相邻连续Zone。
每对相邻View至少共享两个Landmark。
无镜面、Portal侧别、楼层、门窗顺序或永久Geometry歧义。
不包含人物Blocking、临时Prop位置、伤势、破坏或其他时间状态。
每个子View有固定Camera XYZ、Look-at、Lens/FOV、Visible Zone和独立完整ID。
每组最多3个机位。
Atlas裁切后每个子View达到derived_view_min_resolution；真人影视16:9默认不低于1920×1080。若目标模型输出不足以同时满足，改用VIEW_BATCH独立输出或SINGLE_VIEW。
4. 分组算法
按下列顺序聚类：
[text]先排除REDUNDANT/BLOCKED Candidate→ 再按Location/Spatial/GEO Revision分组→ 再按Reality Thread和环境状态分组→ 再按Camera Cluster/连续Zone分组→ 对Portal/Mirror/Resolution风险拆分→ 每组保留2至3个View→ 单独剩余View使用SINGLE_VIEW
不以“数量接近”或“填满Atlas格位”作为合并理由；必要性由View Utility决定，合并只以空间兼容性和像素预算为理由。
5. ID与文件
生产任务与子View分开登记：
[text]PRJ_NOVA__LOC_001_VIEWBATCH_B01_R01├─ PRJ_NOVA__LOC_001_VIEW_A01_R01├─ PRJ_NOVA__LOC_001_VIEW_A02_R01└─ PRJ_NOVA__LOC_001_VIEW_A03_R01
若使用Atlas：
[text]PRJ_NOVA__LOC_001_VIEWPACK_P01_R01__PRIMARY.pngPRJ_NOVA__LOC_001_VIEW_A01_R01__PRIMARY.pngPRJ_NOVA__LOC_001_VIEW_A02_R01__PRIMARY.pngPRJ_NOVA__LOC_001_VIEW_A03_R01__PRIMARY.png
每个子文件记录：source_pack_id、panel_slot/output_index、crop_box_px、resolution_px和独立SHA-256。通过的子View可以独立Promotion为CANONICAL；失败的子View单独返工，不静默替换其他已批准View。
6. VIEWPACK完整提示词合同
[text]【PRODUCTION TARGET】Target View Pack ID: {FULL_VIEWPACK_ID}Child View Count: {2|3}Output Mode: SEPARATE_FILES | FIXED_2X2_ATLAS【REFERENCE INPUT】Image 1 = {FULL_LOC_ID}Who / What + Visible Content: 当前Location外观与材质身份Story Time / Current State: {THREAD/TIME/ENVIRONMENT}Controls: 材质、色彩、地域、固定设施视觉设计Does Not Control: Camera、World Geometry、人物、临时状态Applicable Scope: 全部Child ViewImage 2 = {FULL_SPATIAL_ID}Who / What + Visible Content: 米制Spatial MasterStory Time / Current State: 当前Spatial RevisionControls: 坐标、Zone、Anchor、Route、Barrier、PortalDoes Not Control: 材质、人物、CameraApplicable Scope: 全部Child ViewImage 3 = {FULL_GEO_ID}Who / What + Visible Content: 同一Geometry ProxyStory Time / Current State: 当前Geometry RevisionControls: 投影、尺度、遮挡、TopologyDoes Not Control: 材质、人物、时间状态Applicable Scope: 全部Child View【PANEL IDENTITY MAP】Output 1 / TOP_LEFT = {FULL_LOC_VIEW_ID_1}View Role: {ROLE}Unique Coverage: {UNIQUE_ZONE/PORTAL/ROUTE/AXIS/PARALLAX}Story / Shot / KF Consumers: {FULL_REVISION_IDS}Difference from Other Child Views: {MATERIAL_DIFFERENCE}Camera Rig: {XYZ / Look-at / Lens / Aspect}Visible Zones: {...}Shared Landmarks: {...}Applicable Scope: 仅此Child ViewOutput 2 / TOP_RIGHT = {FULL_LOC_VIEW_ID_2}...Output 3 / BOTTOM_LEFT = {FULL_LOC_VIEW_ID_3}...【CROSS-VIEW LOCK】全部Child View必须由Image 3的同一物理空间投影。固定Landmark数量、顺序、尺度、距离、遮挡和连接关系一致；Image 1只提供外观。不得镜像、移动固定结构或为每个Panel创造另一套场景。【DISTINCTNESS LOCK】每个Child View执行各自View Role与Unique Coverage。不得把不同Rig平均为三个近似眼平中景；不得只改变焦段、Zoom或轻微横移；不得模仿相邻Panel的Camera、Crop、Composition或Visible Zone。任何Child View若失去独有Coverage，返回REDUNDANT_VIEW_REJECTED，不为填满格位保留。【EMPTY-STATE LOCK】全部Panel为空场。禁止人物、马匹、尸体、临时兵器、伤势、破坏状态、字幕、水印和随机可读文字。【OUTPUT AND DERIVATION】优先返回多个独立图像文件；若只能返回Atlas，严格使用固定格位。每个Child View裁切后必须达到最低分辨率，并以对应完整LOC_VIEW ID命名。若做不到，返回VIEWPACK_RESOLUTION_BLOCKED。
7. 下游引用规则
PR/VIEWSET索引独立子LOC_VIEW，可登记其来源Pack，但不以Pack替代View。
SCSTATE只上传覆盖当前空间状态所需的单一LOC_VIEW或PR，不上传整张Atlas。
Storyboard按KF Camera覆盖选择独立LOC_VIEW/GEO；不同KF需要不同View时，分别在Prompt映射其适用KF，不把Pack概括成一个Image身份。
Video仍默认只上传Canonical Storyboard；VIEWPACK不能成为视频补图。
8. 失败与回退
任一Panel分辨率不足：该组改用VIEW_BATCH独立输出；仍不足则SINGLE_VIEW。
任一Panel镜像、结构漂移或Landmark不闭环：只返工该子View；连续失败时拆包。
平台不能保证固定格位：不使用Atlas。
下游需要未覆盖新机位：从同一GEO新增单View或新兼容批次，不放大裁切旧图假装新机位。
合并输出变成三个近似构图：拆包，并按各View Role重新生成；若某View仍无独有Coverage，删除该View而不是继续返工。
