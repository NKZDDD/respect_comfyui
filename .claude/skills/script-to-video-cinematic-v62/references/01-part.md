第一部分｜SKILL.md 核心工作流
---name: produce-cinematic-ai-short-dramadescription: 将小说、剧本或故事资料编译为电影级AI短剧生产包，覆盖Story Truth、Registry、Spatial、Continuity、CVS、风险驱动图片物化、Zone-Coherent SCSTATE逻辑合同、最多三格的Continuation Storyboard、强制Storyboard时间骨架、有效参考选择、导演级Video执行、上游Canonical Boundary Plan、模型原生多镜头与声音、Story-First完整production_prompt。用于新建或更新AI短剧生产Skill、生成资产/故事板/视频提示词，以及修复图片层过度承载、视频缺少故事板约束、参考图堆叠冲突、视频动作或表演粗糙、人物空间瞬移、状态丢失、未来状态前置、道具实例混淆、Canonical ID缩写漂移和Image编号身份不明。---
电影级AI短剧生产
核心任务
把输入故事逐层编译为唯一、连续、可执行的影视生产真相。保持原故事的核心事实、人物关系、因果、关键剧情点和结局；只在用户授权范围内优化节奏、导演表达、镜头、分段与AI生产适配。
始终执行下列总原则：
先确定Canon，再生成视觉；不得让下游生成误差反向改写上游事实。
把“是什么”与“怎么表现”分开；参考图提供指定Authority，不是像素复制目标。
把叙事结构与生产容器分开；Scene、Beat、Shot由剧情决定，SEG时长由目标视频模型参数决定。
每个生成调用都交付实际参考图清单、上传顺序、六字段Compact Reference Identity Map和一段完整可复制的production_prompt；Image N必须明确是谁/是什么，不能只写控制范围。
对所有状态执行双向时间保护：未激活状态不得提前出现，已激活持续状态不得无事件消失。
使用动态数量：不得固定每SEG镜头数、KF数或SCSTATE数。
只把已确认的Canonical资产投入下游；草图、测试图和失败版本没有生产Authority。
所有资产、状态和生产对象ID只能从Canonical Registry读取并逐字符完整复用；禁止缩写、别名、模糊匹配和人工改写。
同一Location先从Scene、Blocking、Shot、KF和Camera Reveal提取真实空间需求，建立LOCATION VIEW COVERAGE PLAN与逐View VIEW UTILITY CONTRACT。只有能揭示独有Zone/Portal/Route/Barrier/Anchor、服务独有动作轴/反向关系或提供不可由裁切替代的真实视差/遮挡的机位，才能通过VIEW DISTINCTNESS GATE；仅焦段、Zoom、轻微横移或裁切不同的视图必须去重。通过后才执行VIEW MERGE ELIGIBILITY AUDIT。所有视角仍由同一Spatial与Geometry Proxy投影；可安全合并的机位可用一次VIEW_BATCH/VIEWPACK生产，但每个输出仍保留独立完整LOC_VIEW ID、文件和Camera Authority。
下游当前服饰权威必须是穿在当前PH人物身上的完整LOOK/CT；视频首次显露的身体或服饰区域必须已有视觉覆盖，否则限制Camera或阻断生产。
每个VIDEO/SEG由视频模型一次生成完整多镜头成片及批准的原生Transition；禁止依赖外部镜头拼接、后期补转场或剪掉失败帧。
人物与道具的位置、姿态支撑和Zone必须持续继承；没有批准的移动事件、Route与完成条件，不得跨SCSTATE或KF静默换位。
Canonical逻辑完整性不等于全部状态必须出图。先执行Image Materialization Gate；未命中新身份/LOOK、首次显露、不可逆结果、关键Location/Hero Prop、Canonical跨SEG边界锚点或实测高风险状态时，保持LOGICAL_ONLY或DEFER_TO_VIDEO。
CVS保持唯一全局世界真相；同一CVS横跨远距离、不同高度、Barrier或不相容动作轴时，建立共享同一Story Time、Object Count和Source CVS的Zone-Coherent SCSTATE Slice。其他Zone实体登记为OFF-FRAME ACTIVE，不得为了同框移动或融合。
SCSTATE、Storyboard和Video Prompt一律先写FULL SCENE STORY CANON → EXACT VISUAL MOMENT → BEFORE/NOW/AFTER → PRIMARY NARRATIVE SUBJECT → COMPACT REFERENCE IDENTITY MAP，最后才写技术合同；隐藏ID后仍必须能理解原文确切时刻与因果。
每张Storyboard Sheet最多3个KF；更多关键时刻使用有序Continuation Sheet。同一SEG仍只有一个SBPKG，禁止九宫格、高密度缩人排版和把多个Action Phase塞进一格。
每个Video SEG必须携带覆盖完整关键时间推进的Mandatory Storyboard Temporal Spine。它可由同一SBPKG的有序Continuation Storyboard Sheets或有序独立Canonical KF Anchors承载，但不得退化为只有Start、LOOK、SCSTATE或文字Prompt。Storyboard提供时间、因果、Action Phase、构图意图与镜头顺序，不与SCSTATE竞争世界状态Authority。
Video参考执行mandatory_storyboard_plus_selective_effective_supplemental：先通过Storyboard Reference Admission Gate确认故事板版本、SEG、时段、Thread、状态和位置合法，再用Effective Reference Selection Gate只补故事板不能充分承担的当前人物LOOK/CT、关键LOC_VIEW、Hero Prop或BNDANCHOR。每张补图必须证明唯一Authority贡献；参考数量不以模型上限为目标。
任何AI视频生成帧都只能作为QC证据，禁止注册为下一SEG的Reference、Temporal Primary或Canonical入口。相邻SEG使用在两条视频生产前由Story Truth、CVS、Spatial、当前LOOK/CT和Prop Ledger编译的BNDPLAN及可选BNDANCHOR；不得从上一视频尾帧提取或反向生成边界Authority。
图像减压不得降低一致性维度。Hero人物Identity与当前完整LOOK/CT、Location视觉Master与相关LOC_VIEW、Spatial/GEO、World Position、Zone、Anchor、Support、Route、Orientation、Count与Holder均为不可降级底座；删图前必须通过REFERENCE DIMENSION COVERAGE GATE。
Video production_prompt必须采用director_level_expanded，把30秒完整戏剧弧拆成逐时间窗口执行卡；每个窗口写动作阶段、微表演、眼神与呼吸、身体重心、接触/惯性/延迟反应、镜头景别与运动、焦点、切换机制、环境反应、对白/声音同步和窗口出口。
提示词细化不是堆形容词。每条导演指令必须服务Story Beat、人物目标、空间位置、物理因果或视听节奏；发生冲突时保住故事因果、Storyboard时间骨架、人物/LOOK、World Position、关键动作结果与原生音频，再降低镜头复杂度和装饰细节。
开始前解析项目参数
从用户输入、已有项目文件和上下文中尽量解析下列参数。只在缺失值会实质改变结果且无法安全推断时询问；其他情况采用明确标注的默认值。
[text]project_idid_policy = FQID_CANONICAL_REVISION_REQUIREDasset_registry_pathregistry_snapshot_idsource_type = novel | screenplay | outline | existing_assetsadaptation_authority = preserve | optimize_pacing | authorized_rewriteinstruction_language = 中文dialogue_languagecultural_settingvisual_medium = live_action | 3d | 2d | mixedvisual_styleaspect_ratio = 9:16target_image_modeltarget_video_modelseg_duration = 15s | 30s | custom fixed durationvideo_audio_mode = native_audio | silent_video | separate_audioproduction_scope = full_project | episode_range | current_episodecurrent_episodeexisting_canonreference_capacity_per_callspatial_consistency_mode = geo_proxy | measured_2_5d | text_onlylocation_view_coverage_policy = demand_driven_dynamicview_distinctness_policy = unique_spatial_authority_requiredredundancy_overlap_heuristic = 0.80location_view_production_mode = auto | compatible_view_batch | single_view_onlyview_batch_output_mode = separate_files | atlas_with_lossless_crop | unsupportedview_batch_max_views = 3derived_view_min_resolutioncostume_asset_mode = auto | separate_cost | direct_lookreveal_coverage_policy = require_coverage_or_constrain_cameratransition_execution_mode = MODEL_NATIVE_ONLYexternal_transition_editing = FORBIDDENexternal_shot_assembly = FORBIDDENnative_multishot_support = reliable | limited | unsupported | unknownnative_audio_transition_support = yes | no | unknownoutput_depth = analysis | plan | production_readyscstate_spatial_slice_policy = zone_coherent_when_requiredstory_first_prompt_order = requiredstoryboard_max_kf_per_sheet = 3video_execution_reliability = high | medium | low | unknownimage_composite_reliability = high | medium | low | unknownvideo_reliability_evidence = user_verified | project_pilot_verified | model_profile_only | unverifiedscstate_materialization_policy = logical_first | risk_based | always_visualstoryboard_materialization_policy = mandatory_temporal_spine | ordered_continuation_sheets | ordered_kf_anchorsstoryboard_video_reference_policy = mandatory_temporal_spinevideo_reference_policy = mandatory_storyboard_plus_selective_effective_supplementalstoryboard_reference_admission_gate = requiredeffective_reference_selection_gate = requiredvideo_prompt_detail_mode = director_level_expandedmicro_performance_contract = requiredaction_phase_physical_response_contract = risk_driven_requiredcinematic_camera_grammar_contract = requiredgenerated_video_frame_reference_policy = forbiddencanonical_boundary_policy = canonical_cut_pair | shared_stable_anchor | motivated_hard_cut | opaque_buffer_pairreference_dimension_coverage_gate = requiredposition_contract_policy = immutable_without_authorized_movementimage_complexity_budget = conservative | standard | expanded
不要把提示词语言等同于文化设定。地域、服饰、医院、建筑、货币、称谓等只服从World Bible和Story Truth。
选择工作路径
全流程生产
按第0至17章顺序执行，并读取全部参考文件：
[架构与权威](references/01-architecture-and-authority.md)
[资产与参考权威](references/02-assets-and-reference-authority.md)
[连续性、CVS与SCSTATE](references/03-continuity-cvs-scstate.md)
[导演、镜头、SEG与故事板](references/04-directing-seg-storyboard.md)
[视频执行与声音](references/05-video-execution.md)
[完整提示词与交付模板](references/06-production-prompt-library.md)
[PROP规格、物理实例与数量连续性](references/08-prop-spec-and-physical-instance.md)
[原子资产完整提示词模板](references/09-atomic-asset-prompt-templates.md)
[Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)
[空间坐标、机位Rig与多视角一致性](references/11-spatial-rig-and-multiview-consistency.md)
[服饰资产、完整LOOK与首次显露覆盖](references/12-costume-look-and-visual-coverage.md)
[视频模型原生镜头切换](references/13-model-native-shot-transition.md)
[空间状态门控与Authority完整视频参考](references/14-spatial-state-gating-and-video-reference-minimization.md)
[同场景兼容机位合并生产](references/15-compatible-location-view-batching.md)
[场景机位覆盖规划与重复视图控制](references/16-location-view-coverage-and-redundancy-control.md)
[Story-First、Zone-Coherent SCSTATE与故事板可读性门控](references/17-story-first-zone-coherent-scstate-and-storyboard-readability.md)
[Logical-First、Video-Weighted Execution、Canonical Boundary与一致性底座](references/18-logical-first-video-weighted-execution.md)
[强制Storyboard时间骨架、有效参考选择与导演级Video执行](references/19-mandatory-storyboard-directorial-video-execution.md)
[漏洞审计与冲突处理](references/07-loophole-audit.md)
单项资产生产
先读[Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)、[资产与参考权威](references/02-assets-and-reference-authority.md)和[原子资产完整提示词模板](references/09-atomic-asset-prompt-templates.md)。Location/SPATIAL/PR或同场景多视角任务同时读[空间坐标、机位Rig与多视角一致性](references/11-spatial-rig-and-multiview-consistency.md)、[场景机位覆盖规划与重复视图控制](references/16-location-view-coverage-and-redundancy-control.md)和[同场景兼容机位合并生产](references/15-compatible-location-view-batching.md)；先证明每个View必要，再讨论合并生产。COST/LOOK/CT或人物服饰覆盖任务同时读[服饰资产、完整LOOK与首次显露覆盖](references/12-costume-look-and-visual-coverage.md)。如果资产包含持续状态、空间组合或跨时间继承，同时读[连续性、CVS与SCSTATE](references/03-continuity-cvs-scstate.md)。若出现两件以上同款道具、背景库存、道具交接/损坏/消耗或物体数量漂移，同时读[PROP规格、物理实例与数量连续性](references/08-prop-spec-and-physical-instance.md)。
故事板生产或修复
读取[Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)、[连续性、CVS与SCSTATE](references/03-continuity-cvs-scstate.md)、[导演、镜头、SEG与故事板](references/04-directing-seg-storyboard.md)、[Story-First、Zone-Coherent SCSTATE与故事板可读性门控](references/17-story-first-zone-coherent-scstate-and-storyboard-readability.md)、[Logical-First、Video-Weighted Execution、Canonical Boundary与一致性底座](references/18-logical-first-video-weighted-execution.md)、[强制Storyboard时间骨架、有效参考选择与导演级Video执行](references/19-mandatory-storyboard-directorial-video-execution.md)、[空间坐标、机位Rig与多视角一致性](references/11-spatial-rig-and-multiview-consistency.md)、[场景机位覆盖规划与重复视图控制](references/16-location-view-coverage-and-redundancy-control.md)、[空间状态门控与Authority完整视频参考](references/14-spatial-state-gating-and-video-reference-minimization.md)、[服饰资产、完整LOOK与首次显露覆盖](references/12-costume-look-and-visual-coverage.md)、[视频模型原生镜头切换](references/13-model-native-shot-transition.md)和[完整提示词与交付模板](references/06-production-prompt-library.md)。
视频提示词生产或时间逻辑修复
读取[Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)、[连续性、CVS与SCSTATE](references/03-continuity-cvs-scstate.md)、[视频执行与声音](references/05-video-execution.md)、[Story-First、Zone-Coherent SCSTATE与故事板可读性门控](references/17-story-first-zone-coherent-scstate-and-storyboard-readability.md)、[Logical-First、Video-Weighted Execution、Canonical Boundary与一致性底座](references/18-logical-first-video-weighted-execution.md)、[强制Storyboard时间骨架、有效参考选择与导演级Video执行](references/19-mandatory-storyboard-directorial-video-execution.md)、[空间状态门控与Authority完整视频参考](references/14-spatial-state-gating-and-video-reference-minimization.md)、[视频模型原生镜头切换](references/13-model-native-shot-transition.md)、[服饰资产、完整LOOK与首次显露覆盖](references/12-costume-look-and-visual-coverage.md)和[完整提示词与交付模板](references/06-production-prompt-library.md)。若Camera移动、转身或扩大取景会暴露新空间，同时读[空间坐标、机位Rig与多视角一致性](references/11-spatial-rig-and-multiview-consistency.md)及[场景机位覆盖规划与重复视图控制](references/16-location-view-coverage-and-redundancy-control.md)。
体系更新或漏洞检查
读取全部参考文件，最后逐条执行[漏洞审计与冲突处理](references/07-loophole-audit.md)。
17章生产编译流程
0｜项目初始化（Project Initialization）
冻结任务参数、生产范围、目标模型、固定SEG时长、画幅、语言、文化设定、视觉媒介、已有Canon和用户授权。建立唯一Canonical Asset Registry，冻结project_id、ID Policy和Registry Snapshot；不得在下游自行扩大改编权限或临时造ID。
1｜源文本解析与实体消歧（Source Parsing & Entity Resolution）
解析时间、地点、人物、别名、关系、道具、事件、对白、画外信息和现实线程。把同一实体的别名合并；不要因空间角色变化重复创建同一Physical Entity。
2｜故事真相（Story Truth）
建立客观事实、Presented Truth、隐藏真相、未解信息和因果链。当前生产提示词只能使用当前Story Time合法呈现的信息；不得用全剧隐藏真相提前剧透。
区分：
Story Unresolved：故事本身尚未确定，禁止补写成事实。
Visual Underspecified：故事未规定但画面必须决定，允许建立Open Design Degree并冻结为视觉Canon。
3｜叙事结构（Narrative Structure）
按Project → Episode → Scene → Beat → Shot表达需求解析，不把SEG放入叙事层级。
Scene：相对连续时间/行动中，围绕一个主要目标并产生明确状态变化的戏剧单位。
Beat：刺激或行动导致认知、目标、情绪、关系、权力或局势发生有意义变化的最小戏剧单位。
Shot：表达Beat，不创造新的Story Truth。
不得固定“一Beat一镜头”。
4｜人物与世界规则（Character & World Rules）
建立人物长期动机、关系、弧光、能力、身体限制、表演边界、文化规则和世界运行规则。把永久规则与当前状态分开。
5｜资产系统（Asset System）
建立资产Blueprint并按当前生产范围物化。使用依赖拓扑生产：
[text]CHAR → PH关键/复杂/复用COST → Canonical COST Visual Asset简单COST → LOGICAL_ONLY Costume Contractselected PH + COST Visual Asset或Costume Contract → 完整LOOKLOOK / previous CT + state delta → CTLOC + SPATIAL + Geometry Proxy → Story/Shot Spatial Demand → Location View Coverage Plan → View Utility Contract → View Distinctness Gate → View Merge Eligibility Audit → VIEW_BATCH/VIEWPACK或单View生成 → 独立Canonical LOC_VIEW子文件 → LOC_VIEWSET / PRPROP_SPEC → PROP_SET / PROP_INSTANCE → PROP_INSTANCE_CTPROP / VEH / CRE / GRP / VFX及其必要状态CVS + component authorities → Story-First Narrative Contract → SCSTATE逻辑合同 → Image Materialization Gate → 可选Zone-Coherent Visual Slice / KF Anchor相邻SEG Boundary State + Shot Intent → BNDPLAN → 可选预编译BNDANCHOR OUT/IN
每项先从Registry分配完整Asset Family ID和Canonical Revision ID，再标记RESERVED | NEW | EXISTING_CANONICAL | LOGICAL_ONLY | VISUAL_ANCHOR_REQUIRED | VISUAL_QC_REQUIRED | DEFER_TO_VIDEO | DEFERRED。逻辑对象先完整登记，再通过Image Materialization Gate决定是否生成图片；不得用“保险”替代真实物化触发器。编号一经占用不得回收或转给另一实体。
6｜空间主表（Spatial Master）
冻结Location坐标原点、轴向、单位、拓扑、Zone、Anchor XYZ、Route、Barrier/Portal、Seat/Support Anchor、连接关系、门窗、固定结构、尺度、Landmark和当前空间修订。SPATIAL/GEO首先是逻辑几何合同；高风险场景可建立3D、2.5D Proxy或可测平面图，不要求图片模型一次生成多视图证明几何。每个Location先建立一张视觉Master，再从Scene、Blocking、Shot/KF需求和Camera Reveal Envelope建立Location View Coverage Plan，默认只生产当前执行不可替代的1至2个View；新增View仍需Role、独有Coverage、消费者、Overlap、Allowed Crop和Distinctness证据。PR/View Set只索引已批准视角，不默认触发新图片调用。
7｜标准连续性（Canonical Continuity）
维护唯一Continuity Ledger。按Story Time与Reality Thread解析Resolved World State。所有状态必须有来源事件、激活条件、持续规则、失活/替换条件或合法自然生命周期。人物位置同样是状态：Zone、Anchor、Support Binding、Posture Class与Orientation在没有合法移动事件时持续不变。
8｜导演设计（Directing Design）
确定Scene Objective、Conflict、Tactic、Turn、Outcome、Performance Intent、Blocking和空间行动。每次Blocking改变都写Start Anchor、Release Support、Route、Barrier/Portal Crossing、End Anchor与Completion；Director读取当前LOOK/CT和物理限制，不能为构图擅自移动Canon实体。
9｜标准视觉状态（Canonical Visual State / CVS）
冻结当前关键物理视觉真相：人物当前有效视觉根、World Position State、姿态、World Root/Foot XYZ或Anchor Offset、Zone、Seat/Support Binding、朝向、占地/支撑点、视线、手占用、Prop Holder、空间状态、持续视觉状态和关键结果。CVS不包含景别、构图、镜头角度或镜头运动；画面左右不能取代World坐标。
CVS保持唯一全局真相。SCSTATE默认是CVS派生的逻辑合同，不要求每个CVS出图。先编译FULL SCENE STORY CANON、EXACT VISUAL MOMENT、BEFORE/NOW/AFTER与PRIMARY NARRATIVE SUBJECT，再执行Image Materialization Gate。只有需要冻结稳定结果时才建立Visual Slice；若同一CVS横跨远距离、不同高度、Barrier或不相容动作轴，每个Visual Slice只显示一个Camera-coherent Spatial Cluster，其他实体登记为OFF-FRAME ACTIVE。中间动作、姿势、反应与Camera变化优先标记DEFER_TO_VIDEO。
10｜视觉过渡（Visual Transition / VT）
定义两个稳定CVS之间的合法变化：起点、事件、物理过程、同步Delta、终点和不可逆结果。位置变化必须通过Authorized Spatial Transition：解除支撑、起身、沿批准Route移动、穿越合法Portal并在目标Anchor完成。中间动作可以不成为SCSTATE，但关键结果必须进入终点CVS。
11｜摄影与镜头设计（Cinematography & Shot Design）
根据Beat、Performance、Blocking和空间可拍性决定景别、机位、角度、构图、焦点、景深、运动和屏幕方向。Physical Direction属于CVS/空间，Screen Direction属于Shot。
12｜剪辑与时间（Editing & Timing）
分配镜头时长、动作节奏、反应停顿、对白速度、切点、声画关系和模型原生Transition。根据叙事关系与模型能力选择NATIVE_CUT、遮挡、甩镜、光学覆盖、受控Dissolve或VFX Transition；不得固定只用硬切，也不得用转场掩盖逻辑断裂。每个Transition写Mechanism、Cinematic Grammar、Narrative Function与模型内执行方法。
13｜SEG包装（SEG Packaging）
把已经设计好的影视内容装入所选固定时长生产容器。镜头数和转场数动态决定。每个Model-Native Transition完整归属一个SEG并占用真实时长；SEG边界只能位于已完成动作、对白与状态结果后的稳定Beat，禁止把一次动作、对白或原生转场拆到两个独立生成视频。每对相邻SEG建立BNDPLAN，选择预编译Canonical Cut Pair、Shared Stable Anchor、Motivated Hard Cut或Opaque Buffer Pair；不得以生成视频尾帧补救边界。
14｜生产解析（Production Resolution）
先执行SEG Visual Risk Assessment与Image Materialization Gate，再从Canon解析本次调用的Authority-Complete Nonconflicting Reference Set。先建立REFERENCE DIMENSION COVERAGE MATRIX，确认Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal和Prop/Count/Holder六维全部有Authority来源。Video第一层必须选择能覆盖完整关键时间推进的Mandatory Storyboard Temporal Spine，并通过版本、SEG、Thread、时段、状态、位置与边界Admission；第二层才选择具有唯一贡献的LOOK/CT、LOC_VIEW、Hero Prop或BNDANCHOR补图。任何来源为生成视频Frame Grab的Image立即返回GENERATED_FRAME_REFERENCE_FORBIDDEN。所有Image继续执行Exact Registry Lookup、文件/Fingerprint检查和六字段Identity Map；故事板缺失、准入失败、补图无独有贡献、缺维或冲突时分别返回VIDEO_STORYBOARD_SPINE_MISSING、STORYBOARD_REFERENCE_ADMISSION_FAILED、VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN、REFERENCE_DIMENSION_COVERAGE_GAP或VIDEO_REFERENCE_AUTHORITY_CONFLICT。
15｜标准故事板（Canonical Storyboard）
从当前CVS/SCSTATE逻辑合同产生KF。每个KF都保留自然语言剧情句、说话者/对白、Source State、Action Phase、完整World Position State、Position Delta、Camera和Forbidden Future State，并标记TEXT_CANON_ONLY | VISUAL_ENTRY_ANCHOR | VISUAL_RESULT_ANCHOR | VISUAL_HIGH_RISK_ANCHOR | VISUAL_BOUNDARY_ANCHOR。图片生成可以逐张产生独立Anchor，再确定性排成每张最多3个KF的Continuation Sheet；也可直接以批准的有序独立KF Anchors承载。无论采用哪种视觉载体，同一SBPKG必须形成覆盖完整关键时间推进的Mandatory Storyboard Temporal Spine，不能只有入口图或文字Canon。一个SEG仍只有一个SBPKG。删去SCSTATE图片不等于删去Source CVS、Zone、Anchor、Support、Route或Orientation。
16｜视频执行计划（Video Execution Plan）
先重新写完整SEG剧情摘要和逐秒因果，再锁定Mandatory Storyboard Temporal Spine：优先上传当前SEG全部有序Continuation Sheets；若平台更适合单图，则上传覆盖同一完整关键推进的有序Canonical KF Anchors。可靠度只决定故事板承载颗粒度、补图数量与提示词冗余度，不决定是否提供故事板。通过Storyboard Reference Admission Gate后，再按Effective Reference Selection Gate选择当前人物LOOK/CT、Camera Reveal需要的核心LOC_VIEW、Hero Prop或BNDANCHOR；每张补图必须有唯一Authority贡献和Applicable Window。SCSTATE不默认上传；同一稳定状态不得用SCSTATE、Storyboard、LOOK和PR重复投票。跨SEG入口只读取预编译BNDPLAN/BNDANCHOR，不读取上一视频尾帧；容量不足先故事板去重、改用等价有序载体或拆SEG，不得删除关键因果与结果。
17｜视频生产提示词（Video Production Prompt）
按Story-First顺序输出一段完整可执行的导演级Prompt，包含Model Capability、Mandatory Audio、完整30秒戏剧弧、Mandatory Storyboard Temporal Spine、Storyboard Admission、Reference Dimension Coverage、Effective Reference Role Map、Canonical Boundary Plan、Entry与全局Invariant。随后以逐时间窗口Execution Card写Beat目的、人物目标/阻力、动作Phase、微表演、身体重心、接触与延迟反应、Camera景别/角度/运动/焦点、对白/声音同步、状态门控、原生Transition和窗口出口；最后写Exit、Forbidden与Quality Priority。冲突时执行Story Causality > Storyboard Temporal Spine > Boundary/Entry/Exit > Character Identity与LOOK/CT > World Position与Spatial > Mandatory Audio > Action Completion > Camera Complexity > Decorative Detail。允许简化镜头，不得删关键因果、声音、位置合同或结果。视频完成后只做QC与重生成决策，任何帧不得进入下一SEG Reference Manifest。
Authority与冻结顺序
严格执行：
[text]F1 Story FreezeStory Truth / Narrative Facts↓F2 Visual Canon FreezeCHAR / PH / COST / LOOK / LOC / PROP / SPATIAL / Geometry Proxy / View Coverage Plan / View Utility / VIEWPACK / LOC_VIEW / Visual Coverage↓F3 Current State FreezeContinuity / Current Appearance / Blocking / CVS / VT Result↓F4 Cinematic FreezeShot / Model-Native Transition / Timing / SEG↓F5 Visual Compilation FreezeCanonical KF / Storyboard Package↓F6 ExecutionVideo Prompt / AI Video
禁止下游静默反向传播。若下游暴露上游不可执行，显式回到最近有Authority的层做最小修订，重新冻结并重编译受影响的下游。
Canonical核心对象
维护八类核心对象：
Story Truth
Character / World Rules
Asset Canon
Spatial Canon
Continuity Ledger
Canonical Visual State
Cinematic Plan
Canonical Storyboard Package
Video是Execution Output，不是新的Canon。生成得更晚不代表Authority更高。
命名与ID完整性
新项目使用项目命名空间、完整对象路径和不可变Revision：
[text]PRJ_NOVA__CHAR_001_R01PRJ_NOVA__CHAR_001_PH01_R01PRJ_NOVA__COST_001_R01PRJ_NOVA__CHAR_001_PH01_LK01_R01PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01PRJ_NOVA__LOC_001_PR01_R01PRJ_NOVA__SPATIAL_001_R01PRJ_NOVA__LOC_001_GEO01_R01PRJ_NOVA__LOC_001_VIEW_A01_R01PRJ_NOVA__LOC_001_VIEWSET01_R01PRJ_NOVA__PROP_SPEC_001_V01_R01PRJ_NOVA__PROP_INST_001_CT01_R01PRJ_NOVA__SCSTATE_EP01_SC03_ST01_R01PRJ_NOVA__SCSTATE_EP01_SC03_ST01_SLC01_R01PRJ_NOVA__CVS_EP01_SC03_01_R01PRJ_NOVA__SBPKG_EP01_SEG01_R01PRJ_NOVA__SBSHEET_EP01_SEG01_A_R01PRJ_NOVA__KF_EP01_SEG01_01_R01PRJ_NOVA__TRANS_EP01_SEG01_01_R01PRJ_NOVA__BNDPLAN_EP01_SEG01_TO_SEG02_R01PRJ_NOVA__BNDANCHOR_EP01_SEG01_TO_SEG02_OUT_R01PRJ_NOVA__BNDANCHOR_EP01_SEG01_TO_SEG02_IN_R01
生产字段只使用完整Canonical Revision ID。CT01、LOOK01、KF03、“女主状态图”和“上一张图”均不是合法ID。SCSTATE属于Story State，不因SEG切分改ID；同一Scene跨SEG且状态未变时继续调用同一完整Revision ID。
全剧唯一且无同款歧义的Hero Prop可继续使用PROP_001对象路径，但实际生产ID必须是如PRJ_NOVA__PROP_001_R01的完整Revision ID。出现重复同款物件时，PROP_SPEC只控制共同外观，PROP_INST才是唯一Physical Entity；批量未追踪库存使用PROP_SET，交互时通过事件物化实例。不得要求完全同款实例为了区分身份而随机改色、加划痕或改标签。
维护[Canonical ID注册表与参考资产解析](references/10-canonical-id-registry-and-resolution.md)规定的唯一Registry。Canonical文件名必须以完整Revision ID开头；Target、Parent、Reference、CVS、SCSTATE、KF、Storyboard和Video中的ID都从Registry原样复制。不得用前缀/后缀搜索、最近匹配、自动别名或最新版本替代指定ID。
全局参考图规则
每个有或无参考图的生成调用都先输出REFERENCE INPUT MANIFEST：
[text]Production TargetReference CountImage N / Reference IDExact Canonical Filename / File RoleCanonical Relative Path / Resolved PathSHA-256 Fingerprint / AvailabilityWho / What + Visible ContentStory Time / Current StateAuthority TypeMUST PRESERVEMUST TRANSFORMMUST NOT COPYDOES NOT CONTROLApplicable ScopeUpload Order
随后输出一段ONE COMPLETE production_prompt，并复用完全一致的Image编号。Prompt内部必须包含下列紧凑映射；它只是现有Manifest的语义回显，不创建新资产、新ID或新注册表：
[text]【COMPACT REFERENCE IDENTITY MAP】Image N = {Exact Canonical Revision ID}Who / What + Visible Content: {自然语言说明这张图中的人、物或场景及画面可见内容}Story Time / Current State: {年龄/阶段/LOOK或CT/事件前后/Thread}Controls: {本次调用中有权控制的维度}Does Not Control: {无权控制的维度}Applicable Scope: {目标、KF或绝对时间窗口}
禁止让生产人员或模型自行猜测参考图；禁止孤立使用“完全按照Image 1”“保持Image 1不变”“严格复制参考图”等表达。只有ID、文件解析正确但上述语义映射不完整时，才使用REFERENCE_MAPPING_BLOCKED；不要重复建设另一套Reference系统。
若单张Image包含多个人物、多个Panel或多个时间状态，Who / What + Visible Content必须用Panel/区域与完整ID逐项消歧；无法消歧时阻断，不把整图概括成一个身份。
若单张Image是VIEWPACK，还必须写Panel Identity Map：固定格位、子LOC_VIEW完整ID、Camera Rig、可见Zone、裁切框、最低派生分辨率和下游适用范围。VIEWPACK只拥有生产容器与跨Panel一致性校验Authority，不拥有“任意机位”Authority；SCSTATE、Storyboard和Video默认引用裁切后独立LOC_VIEW，不得把整张多机位Atlas当作一个Camera参考。只有任务本身需要同时比较多个机位时，才允许上传整张VIEWPACK。
Manifest和Prompt交付前执行Exact ID Echo Audit。Reference Count大于0时，任何ID、文件、路径、Fingerprint或Authority未通过解析，输出REFERENCE_RESOLUTION_BLOCKED，不得猜图继续。
时间状态完整性
对人物、道具、Location、VFX、Holder和环境状态统一执行：
[text]NOT_ACTIVE↓ Activation EventACTIVE↓ PersistenceDEACTIVATION / REPLACEMENT / LIFECYCLE ENDINACTIVE
生效前禁止完整、部分、弱化、模糊、预示或融合形式的未来状态；剧情明确要求Foreshadowing时，把预示本身单独定义为合法状态。生效后持续继承，直到有合法结束原因。
输出纪律
根据用户范围交付相应深度，但生产级输出至少包含：
本次Scope与Assumptions。
Canonical事实和未解信息。
当前范围资产计划与依赖顺序；Location同时交付View Coverage Plan、Coverage Matrix、View Utility与去重结果。
Registry Snapshot、每个资产的完整Canonical Revision ID、文件定位和状态。
每个NEW资产的Reference Resolution Manifest、Compact Reference Identity Map和完整Prompt。
Spatial、Continuity、CVS、Story-First Narrative Contract、SCSTATE/SLC和VT。
Scene、Beat、Blocking、Shot、Timing和SEG。
Storyboard Package的完整SEG摘要、≤3 KF Continuation Sheet、Reference Manifest、逐KF剧情合同和完整Prompt。
SEG Visual Risk Assessment、Image Materialization Decision、Mandatory Storyboard Temporal Spine、Storyboard Admission结果、Reference Dimension Coverage Matrix、Effective Video Reference Set、完整30秒剧情摘要、逐窗口导演级执行卡和完整Prompt。
每个原生Transition的完整ID、Mechanism、Transition Window、State Switch Point和禁止外部剪辑合同。
每对相邻SEG的BNDPLAN、可选BNDANCHOR OUT/IN、边界模式和生成视频帧禁入记录。
明确区分Canon、生产适配和模型输出。
不得只输出模板骨架或要求用户自行补齐关键字段。若信息不足，保留明确占位状态并说明缺口，不能把推测伪装成Canon。
结束前自检
在交付前执行[漏洞审计与冲突处理](references/07-loophole-audit.md)，至少确认：
没有第二套当前世界状态。
CVS没有Camera字段。
CT不是并行效果贴层。
Reference Authority没有被写成像素复制。
Storyboard内容唯一，Sheet数量只是版式承载。
跨远距离、不同高度、Barrier或不相容动作轴的CVS已建立Zone-Coherent SLC；其他Zone实体为OFF-FRAME ACTIVE，没有为同框移动或融合。
每个SCSTATE、Storyboard和Video Prompt隐藏ID后仍能判断原文确切时刻、主角、动作、前因和下一刻禁入事件。
每张Storyboard Sheet最多3个KF；不存在4格以上密集排版、九宫格或把多个Action Phase塞入一格。
SCSTATE数量、KF数量和Shot数量均为动态。
关键单一Delta不会被“至少两类变化”规则错误过滤。
每项状态都有时间边界与合法生命周期。
每次生成调用都给出真实参考图和上传顺序。
Storyboard与Video分别处理Reference Firewall和Temporal State Gating。
不存在Action Replay、未来污染、持续状态丢失或下游静默改Canon。
同款道具已分离Appearance Specification、Physical Instance与Instance CT。
Active物体总数能由Visible、Partial、Occluded与Off-frame实例完整对账。
遮挡、装入容器或离画不会被误判为消失，重新入画恢复同一实例历史。
所有生产ID均为Registry中的完整Canonical Revision ID，没有缩写、别名或漏Revision。
每个Reference ID都解析到唯一Canonical文件、角色、路径、Fingerprint和Availability。
Manifest与Prompt通过Exact ID Echo Audit，不存在Dangling Reference或Silent Redirect。
每个Prompt中的Image N都有完整ID、Who/What、当前时间状态、Controls、Does Not Control和Applicable Scope；不存在只有“Image 1控制什么”却没有说明它是谁/是什么的槽位。
身份映射缺失、错序或与Manifest不一致时已输出REFERENCE_MAPPING_BLOCKED，没有猜图继续，也没有新增重复资产系统。
每个高风险Location使用同一Spatial坐标系和Geometry Proxy生成所有必要视角，多视角Landmark、尺度、门窗、固定家具和连接关系闭环一致。
每个Location在分配View前已从Scene、Blocking、Shot、KF和Camera Reveal提取真实空间需求，并完成Location View Coverage Plan与Coverage Matrix。
每个批准LOC_VIEW都有明确View Role、独有Coverage、完整消费者ID、与已有View的差异和不可由Allowed Crop替代的理由；没有固定三视图、焦段差冒充新机位或轻微横移重复图。
Overlap高且无独有Zone/关系/消费者的Candidate已触发REDUNDANT_VIEW_REJECTED；Coverage不足已用新View、GEO_PROXY或Camera限制解决。
相邻View Reference只控制固定结构Identity、Landmark、尺度和Overlap；Prompt明确其不控制当前Camera XYZ、Look-at、Lens、Crop、Composition和Visible Zone，且禁止复现邻图构图。
每个Location已执行View Merge Eligibility Audit；合并组不超过3个机位，且同组共享Location/Spatial/GEO Revision、时间状态、光照和环境状态。不同Reality Thread、不同Location Revision、永久Geometry变化、Portal/镜像高风险或无足够像素预算的机位没有被强行合并。
每个VIEWPACK都有固定Panel Identity Map；每个子View已无损裁切为独立文件、使用独立完整LOC_VIEW ID与Fingerprint，并逐View通过Camera、Landmark、遮挡、尺度和最低分辨率检查。下游没有把整张多机位Atlas误当作单一Camera Authority。
CVS/SCSTATE/KF中的人物和关键Prop使用World XYZ或Anchor Offset定位；切镜不会静默改变真实Zone或朝向。
每个相邻SCSTATE/KF完成Position Delta审计；没有Authorized Movement Event时，Zone、Anchor、Seat/Support Binding、Posture Class和Orientation逐项继承。
所有跨Barrier或离开座椅/床/车辆的换位均有Release、Route、Portal Crossing、到达Anchor和Action Completion；不存在为同框或争吵构图直接把人物搬到前场。
每个当前人物造型均有穿在当前PH上的完整LOOK；独立COST只按关键度、复杂度和复用价值物化。
每个Video Window完成Camera Reveal Envelope与First Reveal Coverage Gate；未定义区域已补当前LOOK/CT覆盖或明确禁止显露。
每个逻辑状态先通过Image Materialization Gate；未命中身份/LOOK、首次显露、关键Location/Hero Prop、不可逆结果、跨SEG边界或实测风险时保持LOGICAL_ONLY/DEFER_TO_VIDEO。
SCSTATE默认是逻辑合同，Visual Slice只冻结必要稳定结果；没有默认一CVS一图，也没有把中间姿势或动作过程强制出图。
每个KF都有文字Canon与Materialization Mode；只有必要KF逐张生成Anchor，没有默认让图片模型生成三格Storyboard。
每个Video SEG都有覆盖完整关键推进的Mandatory Storyboard Temporal Spine；没有退化为只有Start、SCSTATE、LOOK或文字Prompt。
每张Storyboard参考已通过版本、SEG、Thread、时间范围、状态、位置、边界与顺序Admission；错版、未来状态、错误位置或跨SEG Sheet没有被上传。
每个Video执行Reference Dimension Coverage、Role与Conflict Audit：Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal、Prop/Count/Holder六维均有来源；Supplemental补图均有独有Authority贡献，不与Storyboard争夺Time、Action Phase、Blocking或Camera顺序。
错误SCSTATE没有在Storyboard中被静默修正；已建立新Revision/SLC并重编全部受影响下游。
Video Reference Set是mandatory_storyboard_plus_selective_effective_supplemental；没有为填满上限增加冗余图，也没有因减图丢失人物、LOOK、空间、位置、状态或Prop Authority。
每个Video Prompt达到导演级执行密度：时间窗口、Beat目的、微表演、动作阶段、物理反应、Camera Grammar、声音同步和窗口出口均明确；没有用形容词堆砌替代可执行动作。
Image Complexity超过预算时已SPLIT_ANCHOR、LOCAL_IMAGE_EDIT、LOGICAL_ONLY或DEFER_TO_VIDEO，没有缩小人物或塞入更多Panel。
任何生成视频尾帧、截图或Frame Grab均未进入下一SEG Reference Manifest；视频输出只作为QC证据。
每对相邻SEG均有预先编译的BNDPLAN；同场同状态高风险边界使用来自上游Canon的BNDANCHOR OUT/IN或共享稳定锚点，动作、对白和Transition没有跨SEG拆分。
人物与场景位置锁定没有因SCSTATE/SBSHEET减图而消失；World XYZ、Zone、Anchor、Support、Route、Barrier/Portal与Orientation逐项保留并通过Position Delta审计。
每个VIDEO/SEG配置为MODEL_NATIVE_ONLY并由模型一次生成完整多镜头成片；不存在外部镜头拼接、后期补转场或失败帧裁除依赖。
每个Transition有完整Canonical Revision ID、叙事功能、Mechanism、时间所有权、Exit/Entry与状态隔离；Shielded Switch只在100%遮挡后发生。
模型能力不足时已降级到更安全的原生Transition、单镜头连续表达或明确BLOCKED，没有静默改用后期。
