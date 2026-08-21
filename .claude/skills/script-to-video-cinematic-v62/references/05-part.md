第五部分｜导演、镜头、SEG与故事板
目录
导演设计输入
Scene与Beat导演合同
Blocking与Performance
摄影与镜头合同
剪辑、节奏与对白
SEG包装
Canonical Storyboard Package
SCSTATE First与Observation Transformation
Storyboard Reference Firewall
KF合同与Action Phase
Storyboard时间与持续状态
多Scene、多Thread与多Sheet
Storyboard完整Prompt结构
Story-First与可读性硬门控
常见失败与修复
1. 导演设计输入
Director只读取已解析信息：
[text]Scene ContractBeat ChangesResolved World StateCurrent AppearanceSpatial CanonCharacter RulesPerformance ConstraintsKey Prop / Reveal Requirements
Director可以决定Blocking、Performance Intent、叙事焦点和导演概念；不能改变Story Truth、Visual Canon、空间固定结构或当前持续状态。
2. Scene与Beat导演合同
为每个Scene输出：
[text]SCENE IDENTRY STATEOBJECTIVECONFLICTTACTIC PROGRESSIONTURNOUTCOMEEXIT STATEEMOTIONAL ARCSPATIAL DRAMATIC USEKEY REVEAL
为每个Beat输出：
[text]BEAT IDTRIGGERCHARACTER INTENTTACTIC / ACTIONCOUNTERFORCEMEANINGFUL CHANGEPERFORMANCE RESULTSTATE DELTAVISUAL PRIORITYSHOT NEED
若Beat结束没有任何有意义变化，合并到相邻Beat或视为内部动作。不要为每句对白机械创建Beat。
3. Blocking与Performance
Blocking
Blocking冻结人物Zone、Anchor、World Root/Foot XYZ或Anchor Offset、姿态占地/支撑点、朝向、距离、接触、移动Route和互动关系。画面左右不能作为Physical Placement。
先检查：
当前LOOK/CT是否限制动作。
Route是否被当前Spatial State阻塞。
Prop Holder和手占用是否允许动作。
人物关系和情绪是否支持距离/接触。
关键动作是否在空间中物理可达。
Blocking Draft与Performance Intent可在F3冻结前有限互调。Camera Feasibility可以暴露“不可拍”，但不能直接决定Blocking；必要时回Director最小调整。
Performance Intent
描述可执行的表演目标，不只写情绪标签：
[text]internal objectivesubtextattention targetbody tensionbreath patternspeech behavioremotional changerestraint / releasereaction latency
用“努力控制恐惧、说话过快后突然停住”替代“很害怕”。
Stable Blocking与Transition
SCSTATE/CVS控制Stable Blocking；Storyboard/VT/Video表现两个Stable State间批准的Transition。不得在Storyboard自由创造新的Blocking结果。
人物离开座椅、床、车辆或既有Zone时，先按[空间状态门控与Authority完整视频参考](14-spatial-state-gating-and-video-reference-minimization.md)建立Authorized Spatial Transition。对白升级、为了三人同框或“争吵更有张力”均不能授权换位。
4. 摄影与镜头合同
每个Shot输出：
[text]shot_idsource_scene / beatsource_cvs or transitiondramatic_functionshot_sizesource_spatial_revision_idsource_location_view_or_geo_proxy_idcamera_position_xyz / look_at_xyzcamera_anglelens_or_perspective_intentcompositionsubject_prioritydepth_layersscreen_directioncamera_movemententry_actionexit_actionperformance_focusinformation_revealestimated_durationedit_relationship
镜头必须有功能：建立空间、揭示信息、承载动作、捕捉反应、改变权力关系或控制悬念。不要仅因“电影感”加入无意义推拉摇移。
镜头数量动态
同样15秒可以是3个情绪镜头或8至12个动作镜头。镜头数由Beat、信息量、动作复杂度、表演节奏和空间关系决定，不设固定区间。
Camera不得改变World
Camera可以改变观察位置、景别、角度和构图；不得移动门、窗、电梯、病床、墙体、道路Landmark或人物真实Physical Zone。
每个Shot必须落在已批准LOC_VIEW或Geometry Proxy覆盖中。需要新的观察方向时，先按[场景机位覆盖规划与重复视图控制](16-location-view-coverage-and-redundancy-control.md)证明该方向具有独有空间用途，再按[空间坐标、机位Rig与多视角一致性](11-spatial-rig-and-multiview-consistency.md)建立View；若只是已有View的安全裁切或轻微焦段变化，复用同一View。不得在Storyboard里第一次发明房间另一侧。不同Shot中的人物位置必须能回投到同一World坐标。
Screen Direction
Screen Direction服务镜头连续性，不能取代Physical Direction。切换机位时，根据Spatial Canon重新计算画面左右，不把“人物永远在画面左边”写成物理真相。
5. 剪辑、节奏与对白
Editing
完整规则读取[视频模型原生镜头切换](13-model-native-shot-transition.md)。本项目默认：
[text]transition_execution_mode = MODEL_NATIVE_ONLYexternal_transition_editing = FORBIDDEN
确定：
[text]cut motivationinformation rhythmreaction priorityaction continuityeye-line continuitymatch / contrastparallel thread orderscene transitiontransition mechanismmodel-native execution methodtransition window / state switch point
优先在动作完成、信息成立、视线转换、情绪变化或声音锚点处切。不得固定只用硬切；按叙事关系与模型能力选择NATIVE_CUT、Action/Eyeline/Reaction Match、Full Occlusion、Whip/Motion Bridge、Dip/Flash/Defocus、受控Dissolve或VFX Transition。
每个切换必须有Narrative Function、Mechanism、Cinematic Grammar与MODEL_NATIVE_ONLY执行合同。Dissolve、Morph和特效Transition不能掩盖不成立的时间、空间或因果。
Timing
对白按自然语速和表演停顿估时；不机械快进人物动作。节奏通过信息密度、切换和表演控制。
Timing Plan至少包含：
[text]shot durationdialogue start/endreaction holdaction contact/completionsound prelap/postlaptransition id / mechanism / time rangetransition shield / switch point / entry establishmentmusic cuesegment boundary ownership
6. SEG包装
SEG是适配AI视频模型的固定时长生产容器。流程：
[text]Scene / Beat / Shot / Timing已完成↓按seg_duration分配↓校正边界↓冻结SEG Entry / Exit State
SEG合同
[text]seg_iddurationstory_time_rangeincluded_scenes / beats / shotsentry_thread / entry_cvsexit_thread / exit_cvsactive_thread_statesprimary_dramatic_taskstate_change_ownershipdialoguesound planmodel_native_transition_idstransition_ownershipboundary rationale
边界规则
避免：
把动作的准备和接触、接触和结果拆到两个独立生成视频。
Cause在SEG01、Effect由SEG02重新决定。
在一句关键对白中间强切SEG。
让下一SEG重新初始化人物、Prop或空间。
把一次Model-Native Transition拆到两个独立生成SEG。
把转场时间放在SEG时长之外或依赖外部拼接。
允许：
叙事明确要求延迟揭示。
平行剪辑有明确Thread Entry State。
模型上限要求切分，且边界有稳定Entry/Exit State。
SEG边界必须在Transition开始前或完成后的稳定状态。若固定时长无法容纳完整Exit、Transition Window与Entry Establishment，重新分配Shot时长或SEG边界。
7. Canonical Storyboard Package
一个SEG对应一个唯一SBPKG。Package内容唯一，包括KF Contract、顺序、Source State、Shot、Action Phase和Model-Native Transition Contract。
Package与Sheet分离
旧规则“一SEG必须一张Sheet”与动态KF和线程隔离冲突。新版使用：
[text]ONE SEG = ONE CANONICAL STORYBOARD PACKAGEPackage = 1...N ordered presentation sheets
每张Sheet最多3个KF。禁止4格以上高密度排版、九宫格以及通过缩小人物容纳更多分镜。需要更多关键时刻时使用有序Continuation Sheet，不得删除关键结果或把多个Action Phase塞入一格：
[text]SBPKG_EP01_SEG01├── SHEET_A: KF01-KF03├── SHEET_B: KF04-KF06└── SHEET_C: KF07-KF09
两张Sheet不构成两套Canon，不得重编号、重设计或改变顺序。
8. SCSTATE First与Observation Transformation
Storyboard默认Reference优先级：
[text]与当前时间、Zone和叙事焦点匹配的SCSTATE Slice> Atomic Asset补充
每张Sheet只引用支持本Sheet时间与Camera-coherent Spatial Cluster的Slice，不得为了“全局完整”同时上传同一CVS的全部Slice。只在Hero Prop文字、特殊服装细节或Slice覆盖不足时补充Atomic Authority。
正式关系：
[text]SCSTATE Slice+ NEW CAMERA OBSERVATION↓STORYBOARD KF
Source CVS控制全局World State；SCSTATE Slice控制当前Zone Cluster的Identity、Current CT、Geometry、Stable Blocking和Prop State；Storyboard重新决定Shot Size、Camera Position、Angle、Composition、Depth、Focus与Action Phase。
Storyboard的New Camera Observation只改变投影。Location几何来自同一Spatial/Geometry Proxy，人物和Prop来自同一World Placement。若Camera超出批准View覆盖，KF状态为NEW_VIEW_REQUIRED并在出图前回编。
Storyboard不复制SCSTATE中性机位，也不重新融合人物、场景、道具和CT。
9. Storyboard Reference Firewall
每张Reference必须明确：
[text]Reference IDWho / What + Visible ContentStory Time MeaningCurrent StateAuthority TypeMUST PRESERVEMUST TRANSFORMMUST NOT COPYDOES NOT CONTROLApplicable KF
硬规则：
Reference只控制指定KF与维度。
不同时间SCSTATE不得平均融合成“统一人物外观”。
后期伤口、贴片、泥污、Pose、Blocking、Prop状态和人物位置不得进入较早KF。
Location PR只控制指定Location范围；不得把医院床搬入家里。
Prop Identity不控制Holder和Hand。
PROP_SPEC只控制同款外观；每个交互对象必须绑定具体PROP_INSTANCE。
Atomic人物资产的中性Pose不控制Storyboard Blocking。
Thread Firewall
男主病房线与女主雨夜线等不同Thread的重大状态不得在同一Sheet无边界混排。若同一SEG必须平行剪辑，按Thread分Sheet或分清晰状态带，并给每个KF唯一Thread ID。
Prop Instance与Object Count Lock
同款道具规则读取[PROP规格、物理实例与数量连续性](08-prop-spec-and-physical-instance.md)。Storyboard合同使用INSTANCE ID追踪物理对象，SPEC ID只提供外观。每个KF写当前Active Instance、状态、Holder/Container、Anchor和Visibility bucket；每个Package Entry/Exit对账Visible Full + Visible Partial + Occluded + Off-frame = Active Total。
遮挡、离画或装入容器不等于消失。相邻KF中同款对象不得无事件交换身份、复制、融合或丢失。内部INSTANCE ID不必画在最终画面上，但必须保留在KF合同中。
10. KF合同与Action Phase
每个KF至少包含：
[text]KF_IDSOURCE SCSTATE / CVS / VTREALITY / NARRATIVE THREADTEMPORAL POSITIONSHOT ID / SHOT SIZECAMERA POSITION / ANGLECOMPOSITION / VISUAL FOCUSSTABLE BLOCKING SOURCEACTION PHASEPERFORMANCEVISIBLE ACTIVE STATEACTIVE BUT PARTIAL / OCCLUDED / OFF-FRAMEPROP INSTANCE ID / SPEC / STATE / HOLDER / CONTAINERPROP VISIBILITY BUCKET / OBJECT COUNT LOCKLOCATION / SPATIAL REVISION / LOC_VIEW OR GEO_PROXY IDCAMERA RIG / VIEW COVERAGE STATUSENTITY WORLD XYZ / ANCHOR OFFSET / ORIENTATIONSUPPORT BINDING / BARRIER SIDE / POSTURE CLASSPOSITION DELTA FROM PREVIOUS KFAUTHORIZED MOVEMENT EVENT ID OR NONEROUTE PROGRESS / TARGET ANCHORLOCATION / SPATIAL ANCHORSCAMERA REVEAL ENVELOPEREQUIRED CHARACTER / COSTUME / CT COVERAGEFORBIDDEN FUTURE STATEENTRY CONDITIONEXIT CONDITIONOUTGOING / INCOMING TRANSITION IDTRANSITION ROLE = EXIT / TRIGGER / SHIELD_OR_PEAK / ENTRY / NONETRANSITION WORLD TRUTH AUTHORITY = NONE或明确例外
Storyboard使用TEMPORAL POSITION，如“SEG早段、受伤事件后、治疗完成前”，不与Video Execution Plan争夺绝对秒数Authority。绝对秒数在第16章冻结。
Action Phase词表
[text]PRE-ACTIONACTION STARTTRANSITIONFIRST CONTACTACTION COMPLETIONPOST-ACTIONREACTIONSTABLE EXIT STATE
相邻KF不能重复同一Phase。完成后触发No Action Replay。
关键结果Authority
可以省略不必要的中间动作帧，但不能省略关键结果。例如墙从正常到炸开，KF不必表现爆炸半程，但终点KF必须定义墙的损坏结果，不能让Video自由决定。
原生Transition Anchor
NATIVE_CUT只需Outgoing KF、瞬时cut_at和Incoming KF，并声明不得在两个机位之间生成连续Camera插值。
遮挡、甩镜、闪光、失焦等Transition在执行不可替代时增加：
[text]EXIT KFTRANSITION TRIGGER FRAMESHIELD / PEAK BLUR / PEAK LIGHT FRAMEENTRY KF
Shield/Peak Frame是执行锚点，不是SCSTATE或Stable CVS，默认没有World Truth Authority。完全遮挡前只允许From State，Switch Point后只允许Target State。
11. Storyboard时间与持续状态
Active Character Visual Root
每格先解析最高有效人物状态：CT优先于LOOK、PH、CHAR。不得在后续板退回无伤Clean LOOK。
KF Persistent State Visibility Contract
逐项标记：
当前明确可见。
当前部分可见。
当前被遮挡但仍存在。
当前画外但仍存在。
尚未激活，禁止出现。
Previous Exit → Next Entry
上一Storyboard Package的Canonical Exit Character/Prop Instance/Spatial State成为下一相关Package的Entry State。这里继承的是CVS/KF/BNDPLAN中的逻辑与预编译视觉Canon，不是上一条生成视频的最后帧。保持同一伤口位置、贴片样式、World Position、Zone、Anchor、Support Binding、Orientation、Prop SPEC、Instance ID、破损程度、Holder/Container和Active Object Count。
No Action Replay
签字完成后不得重新拿笔签；跌倒完成后不得再次跌；IV拔除后不得再次拔；文件撕毁后不得再次从完整状态撕。
Camera Reveal Envelope与视觉覆盖
Storyboard虽然可以只画半身，但必须为后续Video标记镜头运动、人物转身/起身、肢体伸展和安全裁切可能显露的最大身体/服饰范围。按[服饰资产、完整LOOK与首次显露覆盖](12-costume-look-and-visual-coverage.md)输出COVERED | SUPPLEMENTAL_REFERENCE_REQUIRED | CAMERA_CONSTRAINED。
半身KF不自动拥有未显示的下装、背面和鞋履Authority。若Video可能显露，优先回编Canonical Storyboard，使对应Sheet/KF取得足够首显覆盖；只有Storyboard无法承担且不改变Camera/Blocking/Time时，才允许Video以书面例外补充当前LOOK/CT。否则限制Camera，不让模型想象。
12. 多Scene、多Thread与多Sheet
多Location
为每个Location Reference指定Applicable KF。必要时分Sheet，避免场景融合。
平行剪辑
每个KF明确Thread、该Thread最新CVS和切换动机。屏幕最后出现Thread A不代表Thread B被重置。
时间状态带
当同一人物在一张Package中经历无伤、受伤、治疗后状态，按状态带安排KF并加Reference Firewall。若目标模型容易污染，输出Temporal Window衍生执行参考；不改变Canonical KF。
可读性
不为凑数量加入重复情绪格。每个KF必须新增动作阶段、信息、反应、空间或状态价值。每张Sheet最多3格；动作、兵器、表情、伤势、手部交互、马匹碰撞和关键Prop必须保持可检查细节。
13. Storyboard完整Prompt结构
固定为Story-First顺序：
FULL SEG STORY CANON。
EXACT VISUAL MOMENT OF THIS SHEET。
BEFORE / NOW / AFTER。
PRIMARY NARRATIVE SUBJECT。
REFERENCE INPUT MANIFEST + COMPACT REFERENCE IDENTITY MAP。
KF STORY CONTRACTS：自然语言剧情句、Speaker/Dialogue、Source Slice、Action Phase、Position Delta、Forbidden Future State。
REFERENCE FIREWALL。
CANONICAL WORLD / SPATIAL / COUNT / TEMPORAL RULES。
CAMERA AUTHORITY、VIEW COVERAGE与REVEAL ENVELOPE。
MODEL-NATIVE TRANSITION CONTRACTS。
KF MATERIALIZATION MODE：TEXT_CANON_ONLY / VISUAL_ENTRY_ANCHOR / VISUAL_RESULT_ANCHOR / VISUAL_HIGH_RISK_ANCHOR。
OUTPUT FORMAT：每Sheet最多3个KF，但只有通过Materialization Gate的KF生成独立图片Anchor。
Prompt必须声明：
当前SBPKG ID和Sheet/KF范围。
每张图的Authority与适用KF。
每个Image槽的完整ID、自然语言Who/What、可见内容、Story Time/Current State、Controls、Does Not Control与Applicable KF；不得让模型从编号猜身份。
SCSTATE只提供World State，Storyboard必须创建新Camera Observation。
所有Active State和Forbidden Future State。
Ordered KF数量与标签要求。
每个KF的Materialization Mode、触发器和独有视觉Authority；TEXT_CANON_ONLY不得伪造Image槽。
每个Transition的完整ID、Mechanism、Applicable KF、Trigger/Shield/Switch/Entry以及MODEL_NATIVE_ONLY。
不生成额外人物、额外状态、时间拼贴、重复动作或平均融合。
Camera可以重新取景，但人物不得为可见性或构图重新Blocking；AUTHORIZED MOVEMENT EVENT ID=NONE时精确继承上一KF的Zone、Anchor、Support与Barrier Side。
14. Story-First与可读性硬门控
逐Sheet执行[Story-First、Zone-Coherent SCSTATE与故事板可读性门控](17-story-first-zone-coherent-scstate-and-storyboard-readability.md)。每张Sheet必须写完整SEG剧情摘要、SEG与Sheet时间范围、Source SCSTATE Slice、唯一Primary Narrative Subject及Continuation Order。
每个KF必须包含：
[text]natural-language story sentencespeaker + dialogue/vocal actionsource SCSTATE Slice full IDaction phaseposition state + position deltaforbidden future state
隐藏ID后无法理解当前Sheet/KF的原文时刻与动作时，返回STORYBOARD_STORY_CONTEXT_INSUFFICIENT。Sheet超过3格或关键细节不可检查时返回STORYBOARD_DENSITY_BLOCKED。引用错误时间或Zone的Slice时返回STORYBOARD_SOURCE_SLICE_MISMATCH。
15. 常见失败与修复
失败
根因
修复
上一板有伤下一板无伤
未绑定Active CT
CT作为唯一视觉父状态，Exit→Entry
未来贴片提前出现
Reference无KF时间边界
Applicable KF + Future Embargo
Image编号有Authority但不知道是谁
Prompt缺语义身份回显
Compact Reference Identity Map；缺失即REFERENCE_MAPPING_BLOCKED
不同人物线程混合
一Sheet承担多个状态线程
Thread Firewall或Continuation Sheet
医院与家里融合
Location Reference无范围
分配Applicable KF/Sheet
Prop变成相似文件
未绑定同一PROP
Identity、版式、文字与Holder分权
两件同款文件交换身份
只写SPEC/外观
KF绑定INSTANCE ID、动作路径和Holder历史
道具被遮挡后复制/消失
未冻结存在数量
Visibility Bucket + Object Count Lock
空间跳轴/门位漂移
缺Spatial Anchor
KF写Zone、Anchor、Landmark与Physical Direction
同场景不同视角结构不一致
Storyboard第一次创建新空间视角
先用同一Geometry Proxy批准LOC_VIEW
切镜后人物换到门另一侧
只锁画面构图
KF锁World XYZ/Anchor Offset，Camera只投影
坐在桌后的人下一格出现在前场
SCSTATE/KF没有Position Delta Gate
锁Seat/Support；只有起身、Route、Portal Crossing与到达完成后才允许换Zone
为三人同框把角色搬到房间中央
把镜头构图当Blocking Authority
保持World Placement，改Camera、允许遮挡或拆镜头
半身板转全身视频后衣裤/鞋变化
未检查裁切外覆盖
Camera Reveal Envelope + 当前LOOK/CT覆盖
全身补充图改写了Storyboard Pose
Reference Authority重叠
Storyboard管Camera/Blocking，LOOK/CT只管视觉覆盖
所有镜头只能硬切
缺少原生Transition Grammar
按叙事与模型能力动态选择原生Mechanism
转场需要后期补
未冻结MODEL_NATIVE_ONLY
Storyboard提供完整Transition Contract和Anchor
遮挡帧被当成新世界状态
Transition Anchor权威不清
WORLD TRUTH AUTHORITY = NONE
两个机位被平滑运镜连接
NATIVE_CUT边界不清
exact cut_at + DO NOT INTERPOLATE CAMERA
转场跨两个SEG
Transition Ownership缺失
Exit、Window、Switch、Entry完整归属单一SEG
KF重复
固定凑9格
动态KF，只保留有变化价值的格
每格复制SCSTATE中景
把SCSTATE Lock当Shot Lock
强制New Camera Observation
一张Sheet塞入4格以上或九宫格
把图片容量当剧情容量
每Sheet最多3个KF，增加Continuation Sheet
默认让图片模型一次生成三格
把逻辑Sheet误当单次图片任务
独立生成必要Anchor再确定性排版，或使用批准的有序独立KF载体
只有入口KF出图就交给Video
把文字Canon误当视觉时间骨架
补齐覆盖关键推进的Mandatory Storyboard Temporal Spine
KF只有“近景/反应/KF03”
缺少自然语言剧情合同
写完整SEG摘要与逐KF施受关系、动作和结果
为显示多个远距离Zone把地点拼在一起
把CVS完整性误当单图完整性
使用同一CVS派生的Zone-Coherent SCSTATE Slice
Storyboard偷偷修正错误SCSTATE
下游覆盖上游错误
新建SCSTATE Revision/SLC并重编全部受影响下游
动作重复
Action Phase不清
Completion后进入Post/Reaction
关键结果随机
只给过程未给终点
终点CVS/KF冻结结果

16. Mandatory Storyboard Temporal Spine编译
每个Video SEG都必须从同一SBPKG取得覆盖完整关键时间推进的视觉骨架。可使用有序Continuation Storyboard Sheets，或使用同样覆盖入口、转折、不可逆结果与出口的有序独立Canonical KF Anchors；不得只上传入口图、SCSTATE、LOOK或文字Prompt。SBSHEET是SBPKG的排版载体，不要求图片模型一次生成多格，但Storyboard的时间与因果功能不可删除。
独立Anchor先审核Identity、State、Position、Count、Action Phase与可见细节；若使用Sheet，必须由已批准Anchor和文字合同确定性排版，每张最多3格。每个载体都要标明SEG绝对时间窗、包含的完整KF ID、前后顺序和Forbidden Future State。不得为了让三格同时成立，把三个人物、手部、Prop、精确文字和多个Action Phase压给一次图片调用。
Video上传前执行Storyboard Reference Admission Gate：逐张验证SBPKG Revision、SEG、Reality Thread、时间范围、Source CVS/SLC、人物LOOK/CT、World Position、Prop状态、Boundary关系和排序。任一错版、错时、未来状态或位置不匹配返回STORYBOARD_REFERENCE_ADMISSION_FAILED；完整骨架缺失返回VIDEO_STORYBOARD_SPINE_MISSING。
