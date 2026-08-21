第三部分｜资产与参考权威
目录
资产生产闭环
资产树与命名
Canonical Reference最高规则
Derived Asset Transformation Contract
Production Reference Manifest
参考容量与Authority完整集
人物资产
地点与空间资产
道具、载具、生物、群体和VFX
生产状态与交付顺序
资产常见失败
SCSTATE Slice资产边界
1. 资产生产闭环
执行：
[text]当前Production Scope↓解析真正需要的资产↓在Canonical Asset Registry检查/分配完整Revision ID↓建立Required Asset List↓标记NEW / EXISTING_CANONICAL / LOGICAL_ONLY / DEFERRED↓按依赖拓扑排序↓为每个NEW资产生成Reference Manifest↓生成ONE COMPLETE production_prompt↓生产并确认Canonical Asset↓登记精确文件名、路径、角色与Fingerprint↓作为下游Parent Authority
分析全剧、只生产EP01时，登记未来Blueprint，但不提前物化所有未来资产。避免资产爆炸、未来剧透和无效返工。
资产依赖不是固定“先人物再场景再道具”，而是有向无环依赖：
[text]Story / Character Rules → CHARCHAR → PHWorld / Costume Rules → COST Visual Asset或LOGICAL_ONLY Costume Contractselected PH + resolved COST → complete LOOKLOOK或previous CT + Continuity Delta → CTWorld / Location Rules → LOCTopology / Scale / Coordinates → SPATIAL → GEO_PROXYLOC + SPATIAL + GEO_PROXY + Story/Shot Spatial Demand → View Coverage Plan → View Utility/Distinctness → LOC_VIEW → LOC_VIEWSET / PRStory Truth → PROP_SPEC → PROP_SET / PROP_INSTANCE → PROP_INSTANCE_CTStory Truth → unique PROP / VEH / CRE / VFXCVS + Canonical Components → SCSTATE
2. 资产树与命名
所有示意Local ID在实际生产时都必须解析为[Canonical ID注册表与参考资产解析](10-canonical-id-registry-and-resolution.md)规定的完整Canonical Revision ID。例如本节的CHAR_001_PH01_LK01_CT01实际输出为PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01。后续不得退回Local ID或缩成CT01。
人物树
[text]CHAR_001├── CHAR_001_PH01│   ├── CHAR_001_PH01_LK01│   │   ├── CHAR_001_PH01_LK01_CT01│   │   └── CHAR_001_PH01_LK01_CT02│   └── CHAR_001_PH01_LK02└── CHAR_001_PH02
PH是CHAR下的阶段分支，不是PH01连续生长为PH02。CT才是同一LOOK下的持续状态链。
地点树
[text]LOC_001SPATIAL_001_R01LOC_001_GEO01LOC_001_VIEW_A01LOC_001_VIEWSET01LOC_001_PR01LOC_001_CT01       # 仅当环境持续视觉状态需要独立资产
其他资产
[text]PROP_001 / PROP_001_CT01                    # 唯一且无同款歧义PROP_SPEC_001_V01                           # 共同外观规格PROP_SET_001                                # 未逐件追踪库存PROP_INST_001 / PROP_INST_001_CT01          # 唯一物理实体及其状态VEH_001 / VEH_001_CT01CRE_001 / CRE_001_CT01GRP_001VFX_001SCSTATE_EP01_SC03_ST01
同一Physical Entity改变功能或空间角色时继续同一Identity，除非它真的成为新实体。例如同一扇门从出口变成封锁点，不创建第二个PROP。
3. Canonical Reference最高规则
冻结：
[text]Canonical Reference ≠ Pixel Copy TargetIdentity Lock ≠ Pixel LockState Lock ≠ Pose LockGeometry Lock ≠ Camera LockCostume Lock ≠ Composition LockSCSTATE Lock ≠ Shot LockStoryboard Lock ≠ Still-image Morph Target
下游继承Reference的Authority，不默认继承其表现形式。
统一执行：
[text]REFERENCE AUTHORITY EXTRACTION↓CANONICAL PRESERVATION↓TARGET DELTA RESOLUTION↓NEW ASSET RECONSTRUCTION
禁止默认：
[text]Reference → Copy → Minor Edit
参考图里的Pose、Camera、Composition、Background、Lighting、Expression、示例Blocking、Sheet Layout，仅在该Reference明确拥有对应Authority时才可继承。
4. Derived Asset Transformation Contract
任何有Parent Reference的派生任务必须写：
[text]REFERENCE IDAUTHORITY TYPEMUST PRESERVEMUST TRANSFORMMUST NOT COPYDOES NOT CONTROLAPPLICABLE SCOPEREQUIRED VISUAL DELTA
MUST PRESERVE
列出Parent真正拥有的Canonical信息。例如CHAR保留骨相和五官几何，COST保留服装结构与材质。
MUST TRANSFORM
列出本次目标需要产生的新阶段、新状态、新组合或新观察。例如PH改变年龄阶段，LOOK将COST穿到当前PH上。
MUST NOT COPY
列出不得像素继承的Pose、Camera、构图、背景、灯光、无关表情、示例人物和Sheet排版。
DOES NOT CONTROL
列出该Reference没有Authority的维度，防止模型用“看得到”替代“有权决定”。
REQUIRED VISUAL DELTA
回答：
目标ID与Parent不同，画面上必须具体哪里不同？
如果无法回答，检查是否真的需要新资产。
5. Production Reference Manifest
每次生成调用都先给生产人员Manifest，再给Prompt。没有参考图也明确写Reference Count: 0 / NONE。
标准格式：
[text]【PRODUCTION TARGET】Target Canonical Revision ID:Target Type:Parent Dependency:Registry Snapshot ID:【REFERENCE INPUT MANIFEST】Reference Count: NImage 1Exact Canonical Revision ID:Exact Canonical Filename:File Role:Canonical Relative Path:Resolved Local Path / Asset URI:SHA-256 Fingerprint:Availability: VERIFIEDAsset Identity:Who / What + Visible Content:Story Time / Current State:Authority Type:MUST PRESERVE:MUST TRANSFORM:MUST NOT COPY:DOES NOT CONTROL:Applicable Scope:Image 2...【UPLOAD ORDER】Image 1 → Image 2 → ...【COMPACT REFERENCE IDENTITY MAP】Image 1 = {Exact Canonical Revision ID}Who / What + Visible Content: {自然语言主体/资产身份及图中可见内容}Story Time / Current State: {年龄/阶段/LOOK或CT/事件前后/Thread}Controls: {本次有权控制内容}Does Not Control: {本次无权控制内容}Applicable Scope: {目标/KF/时间窗口}【ONE COMPLETE production_prompt】...
硬规则：
Image编号属于当前调用，不是全剧永久编号。
Target、Parent和Reference ID只能从同一Registry Snapshot逐字符复制完整Canonical Revision ID。
Manifest与Prompt内部ID、Image编号和文件角色完全一致。
明确精确文件名、路径/URI、Fingerprint、Availability、用途、Authority、适用KF/时间范围和不控制范围。
禁止缩写、别名、显示名称替代、模糊匹配和自动选择最新Revision。
任一Reference未通过Exact Resolution时阻断Prompt，不要求生产人员自行猜图。
不单独使用“完全按照Image 1”“保持Image 1不变”“严格复制Reference”。
最终Prompt内逐Image回显六字段紧凑身份映射；Image 1不能只写Authority，必须用自然语言说明它是谁/是什么以及处于哪个Story Time与Current State。
身份、状态或适用范围缺失，或上传顺序与映射不一致时输出REFERENCE_MAPPING_BLOCKED；该检查复用现有Manifest，不创建新资产类型或第二套注册表。
单图含多人、多Panel或多时间状态时，在Who / What + Visible Content内按Panel/区域绑定完整ID和当前状态；不能把整图笼统写成“人物参考”。
6. 参考容量与Authority完整集
Authority-Complete Nonconflicting Reference Set不是越少越好，而是在Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal、Prop/Count/Holder六维全部有来源的前提下删除冗余。任何生成视频截图、尾帧或Frame Grab均无Reference Authority。
超出模型容量时按顺序降载：
使用高层融合资产代替低层资产：CT代替CHAR+PH+LOOK。
已融合进LOOK/CT的Wearable Prop不重复上传。
非关键背景角色合并为GRP。
非Hero Prop由PR/SCSTATE文字合同约束，不单独Reference。
使用局部Composite Authority Reference，但明确它不是新Canon。
按Thread、Location或Temporal Reference Window隔离执行输入。
最后才调整SCSTATE/Storyboard呈现粒度；只有六维Coverage仍为COMPLETE时才能删除图片，人物与场景位置合同不得降级。
若两个Reference控制同一维度，必须明确Authority Priority；不能让模型平均融合。
7. 人物资产
7.1 CHAR｜Permanent Identity Root
回答“这个人是谁”。固定：
核心骨相与五官几何关系。
眼、鼻、嘴、下颌Identity。
基础身体Identity比例。
肤色与永久辨识特征。
不固定：
精确Story Age、当前长期发型、胡须、体型阶段。
剧情服装、伤势、污染、情绪、Pose和场景。
首次建立无参考图时，使用中性展示服，不把它认定为剧情COST。
7.2 PH｜Persistent Appearance Phase
回答“同一个人在某个长期时期是什么外观”。它是Identity-Preserving Appearance Transformation。
可控制：
明显年龄阶段。
长期发型、胡须、体型、长期生理阶段。
长期基础外观变化。
不控制剧情服装、伤口、污渍、当前Pose或当前情绪。
7.3 COST｜Costume Visual Identity或逻辑合同
定义服装结构、剪裁、层次、材质、颜色、纹样、固定配件、鞋履和穿着方式。COST不控制人物脸、身体、发型和Pose。
关键、复杂、复用、标志性、需要独立审批或会成为剧情对象的服装，物化独立Canonical COST图。一次性、简单、非关键服装可登记为LOGICAL_ONLY完整文字合同，直接与PH重建LOOK。两种路径都不得跳过LOOK。详细决策读取[服饰资产、完整LOOK与首次显露覆盖](12-costume-look-and-visual-coverage.md)。
当关键文字、徽章或标识具有剧情意义时，建立可读Canon；不要让生图模型随机生成。
7.4 LOOK｜PH + COST Reconstruction
回答“当前PH人物真实穿上某个COST后的完整人物视觉表现”。
[text]Character / PH Identity Authority+ COST Authority↓NEW FULL CHARACTER LOOK RECONSTRUCTION
LOOK不是局部换衣编辑。任何单一Reference都不控制最终构图。LOOK形成后，Storyboard中当前服装Primary Authority属于LOOK；不要默认同时用LOOK和COST重复控制同一服装。
LOOK必须完整覆盖当前人物头到脚、身体比例、服装穿着比例、正侧背、下装、鞋履、衣长、层次和背面结构。视频会显露Storyboard裁切外区域时，LOOK/CT Coverage Package提供这些区域的唯一Authority。
7.5 CT｜Continuity Visual State Asset
定义：基于当前Production Representation，需要跨独立生产单元稳定复现的完整持续视觉状态。
[text]current LOOK或previous CT+ all still-active previous state+ new canonical delta↓NEW COMPLETE RESOLVED CHARACTER STATE
CT不是clean LOOK + 伤口贴纸，也不是并行的CT_INJURY + CT_WET + CT_DIRTY效果层。一个当前CT必须是完整合并状态。
CT可包含：伤口、血迹、贴片、湿度、泥污、妆容破坏、持续疲劳、烧伤、服装破损等。
CT不包含Scene Blocking，例如双手撑桌、躺地、抓住某人。持续影响外观的身体状态可进入CT；当前姿态进入CVS/SCSTATE。
生成CT02时，Parent必须是CT01而不是退回Clean LOOK，除非Canonical Replacement明确重置了所有旧状态。
8. 地点与空间资产
本节只定义分层；完整坐标、Geometry Proxy、Canonical Location View、闭环校验和World Placement规则读取[空间坐标、机位Rig与多视角一致性](11-spatial-rig-and-multiview-consistency.md)。机位需求、独有Coverage、重复视图拒绝和相邻View参考防火墙读取[场景机位覆盖规划与重复视图控制](16-location-view-coverage-and-redundancy-control.md)。
8.1 LOC｜Location Visual Identity
回答地点“长什么样”：建筑语言、材质、色彩、固定门窗/设施的视觉设计、地域文化和长期识别特征。
8.2 SPATIAL｜Spatial Master
回答地点“如何构成”：统一World坐标、单位、尺度、Topology、Zone、Anchor XYZ、Route、连接关系、固定结构位置和Landmark。高风险空间必须建立3D或2.5D Geometry Proxy。可用平面/轴测表达，但Sheet排版没有Camera Authority。
8.3 LOC_VIEW｜Canonical Location View
每个视角先由Scene/Shot/KF空间需求证明独有用途，再从同一Spatial Revision与Geometry Proxy按明确Camera Rig生成、闭环核对并登记。每个View必须有View Role、独有Zone/空间关系、消费者与不可由Existing Crop替代理由。禁止固定三视图，禁止把焦段、Zoom、轻微横移或裁切差异登记为多个Canonical View。多视图Sheet只能汇编已批准View，不得成为新的几何生成调用。
8.4 PR｜Location Production Reference
[text]LOC Appearance Authority+ Current SPATIAL / GEO_PROXY Geometry Authority+ approved LOC_VIEW index↓NEW LOCATION PRODUCTION REFERENCE
PR不是复制LOC图片，也不是复制Spatial示意图排版。它不能自动决定人物位置和最终Camera。若View之间无法由同一组World坐标解释，PR不得冻结为Canonical。
8.5 Location CT
仅当环境持续视觉状态跨生产单元、视觉重要且需要稳定复现时建立，例如烧焦墙面、长期积水、被封门、爆炸后结构损坏。临时可自然生成的小杂物不必资产化。
9. 道具、载具、生物、群体和VFX
PROP
全剧唯一且不会与同款物件混淆的Hero Prop，可用PROP_001同时承载外观和单件物理身份。
出现两件以上同型号、同版式或同外观物件时，必须读取[PROP规格、物理实例与数量连续性](08-prop-spec-and-physical-instance.md)，并分离：
[text]PROP_SPEC = 共同外观规格PROP_SET = 可选的未追踪同款库存PROP_INSTANCE = 唯一Physical EntityPROP_INSTANCE_CT = 该实例的完整持续状态
PROP_SPEC固定共同尺寸、材质、颜色、结构、版式、可读文字和产品身份；它不拥有Holder、Hand、Owner、Anchor、当前损坏或生命周期。
PROP_INSTANCE拥有自己的物理ID、Holder/Container、位置、状态、事件和连续性历史。同SPEC实例允许完全同外观，不得为模型区分而擅自改色、加划痕或改标签。
PROP_SET只用于背景批量库存。某一件开始被拿取、移动、损坏、特写或承担因果时，通过SET_MATERIALIZATION事件物化为唯一INSTANCE；SET数量减一、实例数量加一，总物理数量不变。
Logical Instance不等于必须生成独立图片。共同外观Reference使用SPEC；只有实例存在可见、持续、独有状态时才生成INSTANCE CT Reference，防止20件同款道具产生20张无意义重复资产。
VEH
固定车型/结构、比例、材质、颜色、永久损伤与内外空间关系。当前车门、灯光、载荷、破损等用VEH CT或CVS表达。
CRE
固定非人类生物Identity、骨骼/身体结构、材质和永久特征。长期变异阶段可用PH式分支，临时伤势用CT。
GRP
定义群体类型、人数范围、服装逻辑、密度、队形或行为类别。GRP不替代重要个体角色资产。
VFX
定义能力/效果的视觉语言、颜色、形态、尺度、运动规律和可见生命周期。VFX必须有Activation Event；未来VFX不得从第一帧存在。
10. 生产状态与交付顺序
每项资产输出：
[text]asset_family_idcanonical_revision_idasset_typestatusregistry_snapshot_idcanonical_filename / file_rolerelative_path / resolved_pathsha256 / availabilitystory_scopedependencycanonical_authorityreference_manifestproduction_promptrequired_visual_deltadownstream_usage
状态：
NEW：本次必须生产并确认。
EXISTING_CANONICAL：调用已有Canon，不重复生成。
LOGICAL_ONLY：逻辑阶段存在，但当前无需单独图片。
VISUAL_ANCHOR_REQUIRED：命中身份、首次显露、关键Location/Hero Prop、不可逆结果或边界触发器，必须生成稳定视觉Anchor。
VISUAL_QC_REQUIRED：已有视觉候选，但必须通过Identity、State、Position、Count与Geometry检查。
DEFER_TO_VIDEO：状态逻辑完整，中间姿势、动作或Camera过程交给视频模型执行。
DEFERRED：未来范围需要，本次只登记Blueprint。
禁止把“已经生成过”自动等同于CANONICAL。只有用户选定或体系明确确认的版本才能进入Production Resolution。
11. 资产常见失败
失败
原因
修正
PH像Root重画
把Identity Lock写成Pixel Lock
明确年龄/阶段Target Delta和MUST NOT COPY
LOOK像贴衣服
把派生当局部编辑
要求完整人物重建，分离PH与COST Authority
服装图存在但视频穿着比例漂移
把COST当下游人物服饰主权威
先生成穿在当前PH上的完整LOOK
简单服装资产爆炸
所有COST都强制出图
简单非关键COST设LOGICAL_ONLY，仍生成LOOK
故事板半身、视频全身随机
LOOK/CT覆盖不完整
First Reveal Coverage Gate；补覆盖或限制Camera
CT旧伤消失
Parent退回LOOK
使用previous CT并展开Active State
CT继承地面Pose
把Scene Blocking误当人物状态
将Pose移到CVS/SCSTATE
PR复制LOC机位
未区分Geometry与Camera
写Geometry Lock ≠ Camera Lock
同一Location不同视角拼不起来
多视角分别自由生成
同一Spatial/GEO_PROXY逐View投影并闭环核对
同一Location场景图高度相似
未先做View Coverage/Utility，所有机位都看向空间中心
按需求分配View Role；拒绝轻微横移、Zoom或裁切重复图
人物随视角换Zone
只用画面左右描述位置
CVS/SCSTATE写World XYZ、Anchor Offset和朝向

12. SCSTATE Slice资产边界
SCSTATE首先是逻辑状态合同。SCSTATE Visual Slice是同一Parent SCSTATE与Source CVS的可选派生视觉验证资产，不是新的World State、Location或Reality Thread。只有同时命中Image Materialization Gate且CVS横跨远距离、不同高度、Barrier或不相容动作轴时才建立SLC图片。
每个SLC必须拥有独立完整Revision ID和文件，但共享：
[text]source_cvs_idparent_scstate_idstory_timeobject_count_registeractive_instance_registerspatial_revision
SLC只拥有指定Camera-coherent Spatial Cluster的Visibility与中性Observation Authority。其他Zone实体保持OFF-FRAME ACTIVE；不得为视觉完整而复制、移动或融合。未物化时，Storyboard直接读取SCSTATE/CVS逻辑合同；Video不默认上传SLC。
13. Image Materialization Gate与原子资产减压
所有视觉资产在生成前读取[Logical-First、Video-Weighted Execution、Canonical Boundary与一致性底座](18-logical-first-video-weighted-execution.md)。逻辑对象、Registry ID、状态和依赖先完整建立，再判断是否出图。
当前PH与CHAR没有实际可见差异时，PH可LOGICAL_ONLY。
一次性简单服装可LOGICAL_ONLY，由完整on-body LOOK承担穿着结果。
CT只有可见持续Delta满足物化触发器时出图；瞬时表情、姿势和动作过程不建立CT图。
Location默认一张Master加当前需求的1至2个不可替代View；SPATIAL/GEO/PR不因存在就触发写实图。
普通非Hero Prop只登记SPEC/INSTANCE；近景、可读、损坏、交接或数量关键时才出图。
每张图片必须记录Materialization Trigger、Candidate Image Role、Unique Authority Contribution与Image Complexity Score。没有真实触发器时返回IMAGE_MATERIALIZATION_UNJUSTIFIED。
| Prop样式变化 | 未绑定同一PROP ID | 固定Identity、版式、尺寸、文字Canon |
| 两件同款被当成一件 | SPEC与Physical Instance未分离 | SPEC共享外观，INSTANCE独立持有状态与历史 |
| 遮挡后多出/少一道具 | 未维护Existence与Count | Instance Registry + Object Count Lock |
| 同款实例被随机改色 | 用视觉差异代替物理ID | 允许同外观，用ID、Holder、Anchor与事件区分 |
| 批量道具资产爆炸 | 每件同款都生成图片 | PROP_SET + 单一SPEC Reference，交互时物化 |
| 前面完整ID后面写CT01 | 把ID当显示名称 | 所有ID从Registry复制完整Revision ID，禁止缩写 |
| ID存在但找不到图片 | ID与文件未登记一对一关系 | Manifest输出精确文件名、路径、角色、Fingerprint和Availability |
| 同一ID指向新旧两张图 | Canonical文件被覆盖 | Revision不可变；修改创建R02并显式回编 |
| Reference自动选相近资产 | 使用模糊/最近匹配 | Exact Resolution失败即阻断，不猜测 |
| Image 1控制范围明确但身份不明 | Prompt只回显槽位与Authority | 增加六字段Compact Reference Identity Map；缺字段即REFERENCE_MAPPING_BLOCKED |
| 参考图混色/混人 | Authority范围不清 | Reference Firewall与Applicable Scope |
| 资产数量爆炸 | 每个微变化都物化 | 只生产当前可见、持续、重要且下游需要的状态 |
