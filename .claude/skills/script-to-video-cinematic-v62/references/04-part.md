第四部分｜连续性、CVS与SCSTATE
目录
唯一状态真相
Event与同步State Delta
状态生命周期
时间状态完整性
人物持续视觉状态
地点、空间、道具与Holder连续性
Canonical Visual State
Visual Transition
Scene State Composite Asset
SCSTATE创建阈值
SCSTATE Visual Contract
SCSTATE信息优先级与容量
跨Scene、SEG与Thread继承
Position State与合法换位
Zone-Coherent SCSTATE Slice
1. 唯一状态真相
删除任何第二套Current World State Database。唯一逻辑：
[text]EVENT / BEAT↓STATE DELTA↓CANONICAL CONTINUITY LEDGER↓ 按Story Time + Reality Thread解析RESOLVED WORLD STATE W(t)
正确公式：
[text]W(t) + EVENT → ΔW → W(t+1)
Continuity Ledger记录历史变化；Resolved World State是查询结果，不是第二份可独立编辑的状态数据库。
建议Ledger字段：
[text]event_id / story_time / reality_thread / source_scene_beataffected_entity / state_dimensionprevious_value / delta / result_valueactivation_event / persistence_class / deactivation_or_replacementvisual_asset_binding / canon_status
2. Event与同步State Delta
使用：
One Story Event → Multiple Synchronized State Deltas
例如女主砸碎瓶子：
[text]EVENT_025├── Prop: 完整 → 破碎├── Holder: 女主 → NONE├── Spatial: 地面出现碎玻璃障碍└── Character: 手部可能被划伤
所有Delta共享事件源和成立时间。不得让各资产系统独立推演，造成瓶子已碎但手里仍有完整瓶子、地面障碍延后出现等错位。
关键事件的Cause与Canonical Result原则上归属同一SEG：
[text]枪响 → 中枪成立 → SEG Exit CVS已受伤
下一SEG从受伤状态继续。只有叙事本身要求延迟揭晓时，才允许Cause与可见Result分离，但客观Story Truth仍要明确。
3. 状态生命周期
所有重要状态使用：
[text]NOT_ACTIVE↓ Activation EventACTIVE↓ PersistenceDEACTIVATION / REPLACEMENT / NATURAL LIFECYCLE ENDINACTIVE
字段：
[text]state_id / state_owneractivation_event / activation_story_time / active_windowpersistence_class / replacement_prioritydeactivation_event / natural_decay_rule / visual_representation
Persistence Class
INSTANT：只属于事件瞬间，不需跨生产单元继承。
SCENE_LOCAL：本场戏内持续。
CROSS_SCENE：跨Scene持续，直到明确结束。
LONG_TERM：跨Episode或长期存在。
PERMANENT：不可逆或长期永久变化。
状态失活必须来自事件、时间差或生命周期规则。例如湿衣可以因换衣、烘干或足够Time Gap结束；伤口、烧焦墙面和衣服破损不能因下一镜头“不方便”而消失。
自然过程是合法Transition，但必须由规则和Story Time支持，不能由模型随意恢复。
4. 时间状态完整性
Past-State Persistence
已经激活且仍Active的状态必须持续继承。画面暂时看不见不等于失活。
Future-State Embargo
状态在Activation Event之前没有视觉Authority。禁止以完整、部分、弱化、模糊、预示或融合形式提前出现。
Foreshadowing Exception
若剧情明确要求预示，把预示定义为独立合法状态，例如：
[text]VFX_PRECURSOR_01Activation: 能力即将失控的先兆事件
不得把未来完整状态的泄漏解释成“预示”。
Later KF Must Never Rewrite Earlier Time
任何较晚KF中才成立的人物、道具、Location、Holder、VFX或环境状态，不得反向污染较早视频时间。
5. 人物持续视觉状态
每次解析角色时确定：
[text]Current Active Character Visual RootCT > LOOK > PH > CHAR
只要CT存在，Storyboard和SCSTATE不得退回Clean LOOK生成当前人物。
展开Persistent Visible State Checklist，不要只传CT ID：
[text]Active Visual Root: CHAR_001_PH01_LK02_CT03Still Active:- 左额伤口- 左脸轻微血迹- 右颈医用贴片- 右袖口破损- 裙摆泥污Not Yet Active:- 后续手术绷带
Presence ≠ Visibility
为每个状态指定：
[text]ACTIVE & MUST BE VISIBLEACTIVE & PARTIALLY VISIBLEACTIVE BUT OCCLUDEDOFF-FRAME ACTIVENOT YET ACTIVE / FORBIDDEN
Logical Completeness不要求单张画面把全部状态展示给镜头。不得为了展示左手伤口强行破坏Blocking；应记录“Active but occluded”，在后续重新可见时恢复同一状态。
6. 地点、空间、道具与Holder连续性
Prop Instance与Object Count Contract
重复同款道具完整规则读取[PROP规格、物理实例与数量连续性](08-prop-spec-and-physical-instance.md)。Continuity逐实例记录：
[text]prop_instance_id / appearance_spec_id + revision / current_state_idexistence_status / activation / replacement / lifecycle_endholder / hand / owner / carrier_or_container / zone / anchorpivot_xyz / anchor_offset_xyz / orientation / physical_relation / visibility / forbidden_future_state
Holder是当前直接持有，Owner是归属，Container是包含关系；三者不得混用。Holder变化必须与双方手占用、实例位置和状态同步。
每个Story Time对账：
[text]ACTIVE_INSTANCE_TOTAL= VISIBLE_FULL + VISIBLE_PARTIAL + OCCLUDED + OFF_FRAME
遮挡、离画或装入容器不改变存在数量。总量只能由Creation、World Entry/Exit、Destruction、Consumption、Split、Merge或Transformation事件改变；从PROP_SET物化实例只改变追踪形式，不改变总物理数量。
若两件完全同款在不可观察区域发生交换且Story Truth未确定具体身份，记录INSTANCE_IDENTITY_UNRESOLVED及候选集，不得由模型随机决定。
Spatial State
完整空间规则读取[空间坐标、机位Rig与多视角一致性](11-spatial-rig-and-multiview-consistency.md)。Continuity中的物理位置必须能映射到唯一Spatial Revision：
[text]spatial_revision_identity_root_foot_or_pivot_xyz_manchor_id + local_offset_xyz_morientation_yaw_degsupport_surface / posture_footprint_or_bboxmovement_route_id
禁止只用“画面左边”“靠右”“背景里”记录人物或Prop真实位置。Camera变化只改变投影，不改变这些值。
人物位置还必须记录zone_id / support_binding_id / support_relation / current_barrier_side / posture_class / last_authorized_movement_event_id。完整规则读取[空间状态门控与Authority完整视频参考](14-spatial-state-gating-and-video-reference-minimization.md)。没有批准的移动事件时，这些字段与XYZ、Anchor、Orientation一起持续继承。
区分：
Permanent Geometry：墙、门、窗、走廊、病床固定区。
Revisable Geometry：爆炸、倒塌、装修造成的正式修订。
Temporary Spatial State：碎玻璃、封路、移动障碍、临时家具。
当前Route被障碍阻塞时，不能因为未来会移开就提前视为可用：
[text]CVS01 Route blocked↓ VT人物推开障碍CVS02 Route available
Same Visit与New Visit
连续返回同一Location时继承临时状态；长Time Gap的新访问继续LOC/SPATIAL基础，但按Lifecycle重新解析临时Prop、Anchor、Lighting和动态环境。
7. Canonical Visual State
CVS定义某一Story Time的Physical Visual Truth。它不设计服装、不生成资产，也不含Camera。
CVS字段
[text]cvs_idstory_timereality_threadscene_id / beat_idlocation_idspatial_revisioncurrent_environment_statecharacters[]:  character_id  active_visual_asset_id  physical_zone / anchor  root_or_foot_xyz / anchor_offset_xyz  posture  support_points / posture_footprint  support_binding_id / support_relation  barrier_side / posture_class  last_authorized_movement_event_id  body_orientation_yaw  gaze_target  hand_occupancy  physical_condition  persistent_visible_state_checklistprops[]:  prop_instance_id  appearance_spec_id / revision  existence_status / current_state_id  holder / hand / owner / carrier_or_container  zone / anchor / pivot_xyz / anchor_offset_xyz  orientation / physical_relation  visibility_statusprop_sets[]:  prop_set_id / available_untracked_count  materialized_instance_ids / count_reconciliationrelational_blocking[]:  distance  facing  height_relation  contact  movement_couplingactive_spatial_constraintssource_geo_proxy_revisionforbidden_stateentry_conditionexit_condition
明确删除：
[text]camera_anchorshot_sizecamera_anglecompositioncamera_movementscreen_direction
Physical Direction属于CVS，例如“从病床向房门移动”；Screen Direction属于Shot，例如“画面左向右”。
Current Appearance Resolution
在Director与CVS前解析当前PH/LOOK/CT，因为服装、伤势、孕期、铠甲、湿滑鞋履等会影响合法Blocking。CVS绑定active_visual_asset_id，第14章只解析实际Reference，不第一次决定人物穿什么。
8. Visual Transition
VT连接两个稳定CVS：
[text]vt_idsource_cvstrigger_eventaction_causalityphysical_processsynchronized_state_deltasfirst_contactcompletion_conditiontarget_cvsirreversible_result
状态演化：
[text]CVS_A stable before↓ VTCVS_B stable after
中间过程如正在拔针、纸撕到一半、脚刚离地、拳头击中瞬间通常由Storyboard Action Phase和Video执行，不建立SCSTATE。最终重要结果必须进入CVS_B。
9. Scene State Contract与可选Composite Asset
SCSTATE首先是CVS和Canonical Components派生的逻辑状态合同：
[text]CVS+ Current Character Assets+ Location PR / Spatial / Geometry Proxy Authority+ Prop SPEC Appearance / Instance State / Vehicle / Creature Authority↓SCSTATE LOGICAL CONTRACT↓ Image Materialization Gate（命中时）SCSTATE Visual Slice
SCSTATE回答“这一刻整个世界如何稳定成立”。它不要求默认生成图片；Visual Slice只在需要冻结稳定结果时物化。它不是Storyboard、最终镜头、动作过程图、人物定妆图或第二套状态数据库。
Authority边界：
CVS决定有没有伤、谁拿文件、人物站哪里、Prop状态。
SCSTATE逻辑合同完整登记已决定的状态；可选Visual Slice只重建一个必要的Camera-coherent Cluster。
Storyboard通过新Camera Observation观看世界。
Video执行两个稳定状态之间的时间过程。
若SCSTATE Visual Slice与CVS冲突，CVS正确，图片无效；根据风险选择重生成、局部编辑或取消图片并标记DEFER_TO_VIDEO，不得修改CVS迁就图片。
SCSTATE命名：SCSTATE_{EP}_{SC}_{ST}。不包含SEG；同一Story State跨SEG复用同一ID。
SCSTATE Visual Slice图像标准
单幅完整场景，默认9:16。
中性中全景或全景，Camera稳定。
人物建议占画面高度45%至70%，按场景需要调整。
尽量覆盖Identity、当前CT、Stable Blocking、相对位置、Hero Prop和主要Landmark。
不用极端特写、极端广角、Dutch Angle、夸张俯仰、运动模糊、多格或时间拼贴。
10. SCSTATE Visual Slice创建阈值
SCSTATE逻辑合同随CVS建立。只有通过[Logical-First、Video-Weighted Execution、Canonical Boundary与一致性底座](18-logical-first-video-weighted-execution.md)的Image Materialization Gate时才创建Visual Slice，并同时满足：
变化形成新的稳定世界状态。
后续Storyboard/Video需要继承或读取它。
变化在视觉上可识别或具有关键执行价值。
如果多人相对位置、Seat/Support、Barrier Side、Portal/Route、攻击距离、交接关系或同场跨SEG连续性属于剧情执行前提，即使命中“逻辑优先”，也必须让相关位置在Mandatory Storyboard Temporal Spine、独立KF Anchor或预编译BNDANCHOR中获得可见证据；不能因为不生成SCSTATE Visual Slice就把位置完全交给视频想象。
默认执行SCSTATE Delta Visibility Rule：相邻SCSTATE至少在以下四类中有两类明显变化：
Prop State。
Holder / Ownership。
Character Blocking / Spatial Relation。
Sustained Performance / Emotional Result。
不作为唯一差异：文字几毫米变化、签名半程、微表情、轻微手指变化、纸张微移、不可见纹理。
Single-Delta Critical Override
旧“至少两类”规则存在漏掉关键单一状态的风险。仅当单一Delta同时满足下列条件时，允许创建新SCSTATE并记录SINGLE_DELTA_CRITICAL_OVERRIDE：
变化是Canonical关键结果。
视觉上清晰可辨，或会直接控制后续执行。
会持续、改变风险/能力/叙事理解，或成为后续因果前提。
删除该SCSTATE会导致后续丢失状态或产生歧义。
例如：保险箱由锁定变解锁但外观完全不可辨，通常不需要新SCSTATE；炸弹红灯亮起且此后持续、决定后续行动，可以用Single-Delta Override。
创建前问：
删除这个SCSTATE，后续Storyboard或Video是否会失去必须继承的世界状态？
若否，不创建图片；保留完整SCSTATE逻辑合同，并标记LOGICAL_ONLY或DEFER_TO_VIDEO。
11. SCSTATE Visual Contract
SCSTATE Prompt必须同时包含：
[text]REFERENCE+ STRUCTURED STATE+ SPATIAL RELATION
固定结构：
TASK。
SCSTATE IDENTITY。
STORY TIME & REALITY THREAD。
SOURCE CVS。
REFERENCE INPUT MANIFEST。
COMPACT REFERENCE IDENTITY MAP。
REFERENCE ROLE MAP。
REFERENCE FIREWALL。
CHARACTER STATE CONTRACT。
PROP STATE CONTRACT。
LOCATION & SPATIAL CONTRACT。
WORLD PLACEMENT CONTRACT。
BLOCKING & RELATION CONTRACT。
PRESENCE / VISIBILITY CONTRACT。
TEMPORAL STATE LOCK。
MUST PRESERVE STATE LIST。
FORBIDDEN STATE LIST。
CAMERA / PRESENTATION RULE。
OUTPUT FORMAT。
COMPACT REFERENCE IDENTITY MAP逐Image写完整Revision ID、Who/What与可见内容、Story Time/Current State、Controls、Does Not Control和Applicable Scope。只写“Image 1控制人物LOOK”但不说明Image 1中的人物是谁、哪个年龄/状态或何时有效，SCSTATE Prompt不得释放。
Character State Contract
逐人物列出：
[text]Active Visual RootIdentity AuthorityCurrent LOOK / CTStable Physical StateZone / AnchorRoot/Foot XYZ / Anchor OffsetSupport Points / Posture FootprintBody OrientationGazeHand OccupancyActive Persistent StateMust Be VisiblePartially VisibleMay Be Occluded / Off-frameNot Yet ActiveCurrent Prop Binding
Prop Instance State Contract
逐关键Prop列出：
[text]Instance ID / Appearance SPEC + Revision / Current StateExistence Status / Holder / Hand / Owner / ContainerZone / Anchor / Pivot XYZ / Anchor Offset / Orientation / Physical Relation / Visibility BucketEntry History / Forbidden Future StateObject Count Lock / Set Inventory Reconciliation
Location & Spatial Contract
列出Location PR、Spatial Revision、Geometry Proxy/approved View、World Origin/Axis/Unit、Current Zone、Landmark、人物/Prop World XYZ与Anchor Offset、Relative Position、Route和Forbidden Spatial Change。禁止镜像翻转、移动门窗或为构图改变人物Physical Zone。
Relational Blocking
列出人物间距离、高度关系、Facing、Contact、Eye Line、Movement Coupling和Occlusion Priority。
MUST PRESERVE与FORBIDDEN
MUST PRESERVE逐项列出当前所有关键Identity、CT、Prop、Holder和Landmark；FORBIDDEN列出未来贴片、未来破损、错误Holder、未来人物、恢复Clean State和无授权空间变化。
12. SCSTATE信息优先级与容量
Authority Priority：
[text]Temporal Authority = Canonical ContinuityBlocking Authority = CVS / Frozen BlockingSpatial Geometry Authority = Spatial MasterSpatial Projection Authority = Geometry Proxy / approved LOC_VIEWCharacter Identity/State Authority = current CT / LOOKLocation Appearance Authority = PRProp Appearance Authority = PROP_SPEC或unique PROPProp Physical Identity / State Authority = Continuity + PROP_INSTANCE CTCamera Authority = neutral SCSTATE presentation rule
信息层级：
Tier A必须视觉锁死：Identity、Current CT、Hero Prop、Holder、主要Blocking、相对位置、Geometry、关键伤势。
Tier B应保持：环境持续状态、次级污渍、局部姿态、次级Prop。
Tier C可自然生成：呼吸、细小发丝、微褶皱、非关键背景细节。
参考容量不足时优先用高层资产替代低层，不删除Tier A。
13. 跨Scene、SEG与Thread继承
Storyboard A Exit → Storyboard B Entry
上一Storyboard已经成立的角色CT、Prop Instance ID、Holder/Container、Object Count、Location状态和Spatial临时状态，必须成为下一相关Storyboard的Entry State，直到合法替换。
多Thread
每个Reality/Narrative Thread维护自己的最新合法状态。SEG画面最后是Thread A，不代表Thread B状态被重置；下一SEG从B开始时解析B的最新状态。
跨SEG边界
关键State Change归属唯一SEG。优先在同一SEG内包含Cause、Activation和Canonical Result。下一SEG只继承结果，不重新执行动作。
No Action Replay
动作一旦到ACTION COMPLETION，后续只表现POST-ACTION / REACTION / STABLE EXIT STATE。签字、跌倒、拔针、撕毁和撞击不得在下一KF或SEG重新从头发生。
14. Position State与合法换位
相邻CVS/SCSTATE先执行Position Delta：
[text]previous position stateauthorized moversmovement eventsupport releaseroute / barrier crossingtarget anchor / supportcompletion condition
情绪、对白、Camera、照片抛出或人物“开始争吵”都不是换位事件。若上一状态人物坐在桌后，下一状态没有起身、绕桌和到达完成，就必须继续坐在同一Support Anchor；需要同框时允许遮挡或另选观察机位，不得把人物搬到桌前。
SCSTATE Prompt必须写PREVIOUS SCSTATE / UNCHANGED POSITION STATES / AUTHORIZED MOVERS / FORBIDDEN POSITION DELTA。位置冲突时CVS正确、SCSTATE作废；若业务确需改变Blocking，建立新CVS Revision并重编下游。
15. Zone-Coherent SCSTATE Slice
不得把CVS的全局逻辑完整性误解成单张SCSTATE必须显示全部Active Zone。详细执行[Story-First、Zone-Coherent SCSTATE与故事板可读性门控](17-story-first-zone-coherent-scstate-and-storyboard-readability.md)。
当同一CVS横跨远距离、不同高度、Barrier/Portal或不相容动作轴，或全局同框会使关键动作细节不可检查时，强制派生多个SCSTATE Slice：
[text]Source CVS = 唯一World TruthParent SCSTATE = 同一稳定状态SLC01 = Camera-coherent Cluster ASLC02 = Camera-coherent Cluster B
所有Slice共享同一Story Time、Reality Thread、Object Count、Instance Register、Spatial Revision和Source CVS。差异仅限Visible Zone、Primary Narrative Subject、Visibility Bucket和中性观察Camera。其他Zone实体登记为OFF-FRAME ACTIVE，不得删除、移动、缩短距离或融合地点。
SCSTATE/Slice Prompt必须先写：
[text]FULL SCENE STORY CANONEXACT VISUAL MOMENTBEFORE / NOW / AFTERPRIMARY NARRATIVE SUBJECTCOMPACT REFERENCE IDENTITY MAP
最后才写Spatial、Count、Temporal、Camera和Forbidden合同。隐藏ID后无法理解故事时刻与因果，返回SCSTATE_STORY_CONTEXT_INSUFFICIENT；需要空间切片时返回SCSTATE_SPATIAL_SLICE_REQUIRED；与Source CVS或原文因果不符时返回SCSTATE_STORY_MISMATCH并阻断全部下游。
