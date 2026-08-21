第十八部分｜Logical-First、Canonical Boundary与一致性底座
目录
适用问题与根因
Authority重新分配
项目能力参数与可靠度校准
Image Materialization Gate
原子资产减压
SCSTATE逻辑合同与可选Visual Slice
Storyboard文字Canon与Anchor物化
Authority-Complete Nonconflicting Execution Set
Reference Dimension Coverage与Role Map
强化Video Prompt与执行优先级
Canonical Boundary Plan与生成帧禁入
Image Complexity Budget
图片错误的局部修复策略
生产链与失败码
完整模板
结束前审计
1. 适用问题与根因
当项目实测满足以下不对称时启用本章：
视频模型能稳定执行人物动作、空间移动、镜头切换、原生音频和连续状态；
图片模型在多人物同框、手部交互、复杂Blocking、多Hero Prop、多格Storyboard或跨Zone构图中更容易出错；
错误图片一旦被批准为SCSTATE、KF或Storyboard，就会把错误站位、错误手部、错误数量或错误状态传给视频。
问题不是Canon过多，而是把过多Canon证明任务交给了静态图。
正确原则：
保留完整Story Truth、Registry、Spatial、Continuity、CVS、Object Count、Holder与Temporal Gate；只把必须冻结的视觉事实物化为少量图片，把连续动作、Camera、声音和中间状态交给已验证可靠的视频模型。
不得把“图像减压”解释成：
删除CVS或Spatial；
允许视频自由改写人物位置、数量或状态；
跳过Entry/Exit State；
让视频生成结果自动升级为Canon；
为节省图片而忽略首次显露覆盖或不可逆CT。
2. Authority重新分配
2.1 逻辑Canon必须完整
下列字段默认可以是LOGICAL_ONLY，但不得缺失：
Story Time与Reality Thread；
World Position、Zone、Anchor、Support Binding与Orientation；
Authorized Route与Barrier/Portal Crossing；
Holder、Object Count、Physical Instance ID与Existence Ledger；
Activation Event、Persistence、Embargo、Deactivation与Lifecycle；
Entry State、Exit State与Canonical Result；
Camera Reveal Envelope与首次显露需求。
2.2 图片负责冻结
图片优先承担：
Character Identity；
当前PH上完整LOOK及需要显露的正面、侧面、背面、全身和鞋履；
Location视觉身份和实际需要的不可替代View；
Hero Prop外观与近景可读细节；
不可逆CT或Prop损坏的稳定结果；
跨SEG必须精确继承、且在两条视频生产前由上游Canon预编译的Boundary Anchor；
视频模型经过项目测试仍无法可靠推断的高风险结果。
2.3 视频模型负责执行
在批准的Entry与Exit之间，视频模型负责：
中间姿势、起身、行走、转身、跌倒、打斗和交接过程；
表情、呼吸、迟疑、疼痛和情绪渐变；
Camera运动与模型原生镜头切换；
动态光影、粒子、衣料、头发和群体微动作；
原生对白、VO、环境声、动作声和声画桥；
从批准Start Anchor沿批准Route到批准End Anchor的连续物理过程。
视频无权发明未批准的伤势、换装、Prop复制、跨Zone瞬移、隐藏关系或未来状态。
2.4 不可降级的一致性底座
图像减压只删除重复视觉载体，不删除Authority维度。以下底座始终保留：
Hero人物Identity与当前PH上的完整LOOK或Active CT；
新Location视觉Master、当前Camera Reveal所需的独有LOC_VIEW及Spatial/GEO；
每个关键人物与Prop的World XYZ、Zone、Anchor、Support Binding、Orientation与Route；
State/Temporal Gate、Prop Instance、Count、Holder与Existence；
相邻SEG的Boundary State、Boundary Mode与Entry/Exit合同。
如果删除一张图会让任一维度失去唯一Authority，不能删除，必须保留或用不冲突的原子Reference补齐。
3. 项目能力参数与可靠度校准
项目初始化增加：
[text]video_execution_reliability = high | medium | low | unknownimage_composite_reliability = high | medium | low | unknownvideo_reliability_evidence = user_verified | project_pilot_verified | model_profile_only | unverifiedscstate_materialization_policy = logical_first | risk_based | always_visualstoryboard_materialization_policy = mandatory_temporal_spine | ordered_continuation_sheets | ordered_kf_anchorsstoryboard_video_reference_policy = mandatory_temporal_spinevideo_reference_policy = mandatory_storyboard_plus_selective_effective_supplementalstoryboard_reference_admission_gate = requiredeffective_reference_selection_gate = requiredvideo_prompt_detail_mode = director_level_expandedgenerated_video_frame_reference_policy = forbiddencanonical_boundary_policy = canonical_cut_pair | shared_stable_anchor | motivated_hard_cut | opaque_buffer_pairreference_dimension_coverage_gate = requiredposition_contract_policy = immutable_without_authorized_movementimage_complexity_budget = conservative | standard | expanded
当前用户工作流的推荐默认：
[text]video_execution_reliability = highimage_composite_reliability = lowvideo_reliability_evidence = user_verifiedscstate_materialization_policy = risk_basedstoryboard_materialization_policy = mandatory_temporal_spinestoryboard_video_reference_policy = mandatory_temporal_spinevideo_reference_policy = mandatory_storyboard_plus_selective_effective_supplementalstoryboard_reference_admission_gate = requiredeffective_reference_selection_gate = requiredvideo_prompt_detail_mode = director_level_expandedgenerated_video_frame_reference_policy = forbiddencanonical_boundary_policy = canonical_cut_pairreference_dimension_coverage_gate = requiredposition_contract_policy = immutable_without_authorized_movementimage_complexity_budget = conservative
可靠度是项目级执行参数，不是永久模型真理。首次复杂SEG后记录：身份保持、动作完成、空间Route、状态门控、音频、切换和Exit稳定性。任一关键项连续失败，降低可靠度并增加Storyboard颗粒度、Supplemental或Prompt约束；无论可靠度高低，Mandatory Storyboard Temporal Spine都不能省略。
unknown默认按medium处理。只有用户明确确认或项目Pilot通过后才使用high路径。
4. Image Materialization Gate
每个CHAR/PH/COST/LOOK/CT/LOC_VIEW/PROP/SCSTATE/KF在生成图片前回答：
[text]Target Canonical ID:Logical State Exists: YES | NOCandidate Image Role:Materialization Trigger:Video Inference Risk:Cross-SEG Reuse:First Reveal Coverage Gap:Image Complexity Score:Decision: LOGICAL_ONLY | VISUAL_ANCHOR_REQUIRED | VISUAL_QC_REQUIRED | DEFER_TO_VIDEOReason:
只有满足至少一项才允许物化：
新人物或新LOOK首次出现；
首次全身、背面、侧面、手部、鞋履或此前未定义区域显露；
不可逆伤势、污渍、破损、换装、Prop损坏或Location永久变化首次激活；
相邻SEG在同一场景、同一状态或同一空间轴上需要预编译Canonical Boundary Anchor；
Hero Prop需要近景辨认、可读内容或精确数量规格；
新Location首次建立且Camera会显露关键Geometry、Portal、Route或Landmark；
多人物空间关系本身就是剧情关键稳定结果；
目标视频模型经项目测试无法可靠生成该状态；
用户明确要求视觉状态资产。
未命中：
[text]Materialization Mode = LOGICAL_ONLYImage Call = NONEExecution Owner = VIDEO_MODEL或LOGICAL_CONTRACT
禁止以“后面可能用到”“CVS很完整”“最好保险”为由预生成图片。
5. 原子资产减压
5.1 人物、PH、COST、LOOK与CT
CHAR仍应为Hero人物建立稳定Identity Authority。
当前PH与CHAR没有实际可见差异时，PH可LOGICAL_ONLY，在LOOK合同中写明年龄阶段。
服装只服务一个LOOK、没有复用/审批/剧情识别价值时，COST可LOGICAL_ONLY。
Hero人物当前完整LOOK仍是首次显露的主要视觉Authority；不得只给COST平铺图让视频猜穿着结果。
CT只在可见结果真实变化且满足Materialization Gate时出图；无可见Delta的CT保持逻辑状态。
视频中的瞬时表情、姿势和动作过程不建立CT图。
5.2 Location、SPATIAL、GEO与View
SPATIAL和GEO首先是坐标/拓扑/Geometry合同，不因存在就强制生成写实图。
每个Location先生产一张Location Master，再按当前Camera Reveal需求生产1至2个不可替代LOC_VIEW；数量仍可动态增加，但每个新View必须通过Coverage与Distinctness Gate。
高风险空间可以使用可测量2.5D/3D Proxy或平面图作为逻辑几何证据；不要求图片模型一次生成多视图Sheet来证明几何。
PR与VIEWSET默认只做索引，不产生新的生成调用。
不得因图像减压退回“同一Location生成大量相似视图”。
5.3 Prop
非Hero手机、普通杯子、椅子、文件夹等可只登记SPEC、INSTANCE与状态逻辑。
近景辨认、可读文字、损坏、交接、数量谜题或剧情功能关键时才生成Prop视觉资产。
同款物件继续执行PROP_SPEC与PROP_INST分离；图片减少不等于实例ID减少。
6. SCSTATE逻辑合同与可选Visual Slice
重新定义：
[text]SCSTATE = CVS派生的逻辑状态合同SCSTATE Visual Slice = 可选的稳定结果视觉物化
每个SCSTATE必须有完整Story-First、Position、Holder、Count、Temporal与Forbidden合同，但不要求有图片文件。
状态值：
[text]LOGICAL_ONLYVISUAL_ANCHOR_REQUIREDVISUAL_QC_REQUIREDDEFER_TO_VIDEO
默认LOGICAL_ONLY或DEFER_TO_VIDEO的例子：
同座位内的说话/听话反应；
电话接通、挂断、人物转头；
沿已批准Route的中间行走姿势；
打斗、跌倒、挣脱的中间Action Phase；
Camera切换本身；
无持续视觉结果的短暂表情变化。
Visual Slice只冻结稳定结果，不表现“动作正在发生”。跨Zone时仍遵守Zone-Coherent Slice；如果稳定结果本身不需要静态验证，可以完全不物化Slice。
7. Storyboard文字Canon与Anchor物化
KF始终保留完整文字Canon：故事句、对白、Source CVS/SLC、Action Phase、Position Delta、Camera、时间和Forbidden Future State。增加：
[text]KF Materialization Mode =TEXT_CANON_ONLY |VISUAL_ENTRY_ANCHOR |VISUAL_RESULT_ANCHOR |VISUAL_HIGH_RISK_ANCHOR
推荐：
[text]KF01 = VISUAL_ENTRY_ANCHORKF02 = TEXT_CANON_ONLYKF03 = TEXT_CANON_ONLYKF04 = VISUAL_RESULT_ANCHOR
每张Storyboard Sheet最多3个KF的可读性规则继续有效，但Sheet可以是逻辑Continuation容器，不要求每个KF都有图片。
禁止默认让图片模型一次生成三格Storyboard。正确流程：
逐张生成通过Materialization Gate的独立KF Anchor；
单张审核Identity、State、Position、Count和可见细节；
如生产人员需要Sheet，使用确定性排版把已批准Anchor和文字KF合同编入SBSHEET；
若只有1至2个Anchor且视频模型支持独立参考，SBSHEET保持LOGICAL Package，不额外生成图片。
增加Sheet只改变承载，不增加Canonical故事版本。
8. Authority-Complete Nonconflicting Execution Set
废止固定的all_current_seg_storyboard_sheets_only，也废止把“图片越少越先进”当作目标。Reference Set必须同时满足：
[text]COMPLETE = 六个一致性维度均有AuthorityNONCONFLICTING = 同一维度、同一时间窗只有一个最终控制者EFFICIENT = 没有无独有贡献的重复图
8.1 六维Reference Dimension Coverage Gate
每个SEG在删除任何图片前建立：
Dimension
必须回答
合法Authority来源
Identity
画面中每个Hero是谁
当前LOOK/CT、清晰Canonical Anchor
LOOK/CT Coverage
Camera会显露哪些身体、服饰、伤势区域
完整LOOK/CT或覆盖充分的Anchor
Spatial/Geometry
镜头会显露哪些Zone、Portal、Landmark与遮挡关系
LOC_VIEW、GEO/Proxy、Boundary Anchor
Position/Blocking
每个人当前在哪、靠什么、朝向哪里、能沿哪条Route移动
CVS、World Position State、BNDPLAN、Anchor
State/Temporal
哪些状态已激活、持续、禁入或替换
CVS、Temporal Gate、KF/BNDPLAN
Prop/Count/Holder
哪个物理实例、数量多少、由谁持有、落点何处
Prop Ledger、KF/BNDANCHOR、SPEC补图

CVS/Spatial/Route/Temporal等逻辑合同可以覆盖物理维度，但Identity、材质、服饰和可见空间外观不能只靠抽象文字。在Reference Set中删除LOOK或LOC_VIEW之前，必须证明Temporal Primary已经清晰覆盖其适用范围。
任一维度为UNOWNED或两个来源给出冲突事实，分别返回：
[text]REFERENCE_DIMENSION_COVERAGE_GAPVIDEO_REFERENCE_AUTHORITY_CONFLICT
8.2 HIGH可靠度
仍使用Mandatory Storyboard Temporal Spine。可选择较精炼的有序KF Anchors承载，但必须覆盖入口、关键转折、不可逆结果和出口；不能退化为Start-only。若Storyboard看不清人物背面、鞋履、Active CT或即将揭示的新Zone，按Effective Reference Selection Gate补当前LOOK/CT或精确LOC_VIEW。
8.3 MEDIUM可靠度
使用当前SEG有序Continuation Sheets或更密的Canonical KF Anchors形成完整时间骨架；再按六维矩阵补充真正缺失的LOOK/CT、LOC_VIEW、Hero Prop或BNDANCHOR。不得把同一状态重复成SCSTATE、KF、LOOK和Location四张图。
8.4 LOW可靠度
使用更细颗粒的Continuation Storyboard Sequence与更明确的逐窗口导演执行卡；若超过模型容量，先去除重复KF、换成等价有序载体，再优先把SEG重新划到稳定Beat。不得删除关键因果，也不得让动作、对白或Transition跨SEG。
8.5 选择记录
[text]VIDEO REFERENCE SET DECISIONSEG ID:Model Reliability / Evidence:Execution Mode:Reference Capacity:Dimension Coverage Matrix:Chosen Images:Rejected Redundant Images:Uncovered Risk:Fallback:
参考数量不以模型上限为目标，也不以最少数量为目标；以“六维完整、零冲突、无冗余”为目标。
9. Reference Dimension Coverage与Role Map
每张视频参考图必须分配一个角色：
[text]TEMPORAL_PRIMARYCANONICAL_BOUNDARY_EXIT_TARGETCANONICAL_BOUNDARY_ENTRY_PRIMARYIDENTITY_SUPPLEMENTALCOVERAGE_SUPPLEMENTALGEOMETRY_SUPPLEMENTALPROP_SUPPLEMENTALSTATE_RESULT_SUPPLEMENTAL
规则：
同一Applicable Time Window只能有一个Temporal Primary；Boundary OUT和IN分别只适用于各自SEG的出口或入口，不在同一窗口竞争。
Supplemental图不得控制Camera、Blocking、Story Time、Action Phase或Transition。
不得同时上传表达同一稳定状态的SCSTATE、Storyboard、KF Anchor和LOOK；但删除前必须通过六维Coverage Gate。
原子补图必须对应书面的Identity、Coverage、Geometry、Prop或State Result缺口。
每张Image继续写完整Revision ID、Who/What、Current State、Controls、Does Not Control和Applicable Scope。
图中存在多人物或多Panel时必须逐区域消歧；无法消歧则阻断。
任何文件来源若是生成视频截图、尾帧、Frame Grab或视频插帧，立即返回GENERATED_FRAME_REFERENCE_FORBIDDEN。
若两个参考在同一Authority维度给出不一致事实，返回VIDEO_REFERENCE_AUTHORITY_CONFLICT。
合理示例：
[text]Image 1 = 当前SEG入口Canonical Anchor | TEMPORAL_PRIMARY | 00:00-00:18Image 2 = 当前SEG结果Anchor | STATE_RESULT_SUPPLEMENTAL | 00:24-00:30Image 3 = 女主当前LOOK背面 | COVERAGE_SUPPLEMENTAL | 仅首次背面显露Image 4 = 当前Camera Reveal对应LOC_VIEW | GEOMETRY_SUPPLEMENTAL | 仅新Zone与LandmarkImage 5 = Hero Prop | PROP_SUPPLEMENTAL | 仅Prop外观与数量规格
错误示例：把上一SEG视频尾帧放在Image 1，再同时上传当前Storyboard、SCSTATE和LOOK，让生成误差、构图与Canonical Authority共同争夺入口。
10. 强化Video Prompt与执行优先级
Video Prompt必须完整包含：
MODEL CAPABILITY CONTRACT
MANDATORY AUDIO CONTRACT
FULL SEG STORY CANON
EXACT EXECUTION RANGE
BEFORE / ENTRY / NOW / EXIT / AFTER
PRIMARY NARRATIVE SUBJECT
REFERENCE ROLE MAP
ENTRY STATE
SECOND-BY-SECOND CAUSAL EXECUTION
AUTHORIZED MOVEMENT / ROUTE / COMPLETION
STATE ACTIVATION / PERSISTENCE / EMBARGO
CAMERA / MODEL-NATIVE TRANSITION
PERFORMANCE
AUDIO / VO / DIALOGUE
CAMERA REVEAL ENVELOPE
EXIT STATE
FORBIDDEN
执行冲突优先级：
[text]Story Causality> Entry / Exit State> Character Identity / Current LOOK or CT> World Position / Spatial Geometry> Mandatory Audio> Action Completion> Camera Complexity> Decorative Detail
允许简化镜头运动、景深、粒子或背景微动作；不得删除关键因果、Mandatory Audio、动作完成或Canonical Result。
逐秒描述必须写施动者、动作、受动者、物理路径、完成条件、反应、声音和状态Delta。图片只提供Anchor，不能替代这段执行合同。
11. Canonical Boundary Plan与生成帧禁入
11.1 原则
Video是Execution Output，不是Reference Factory。无论上一SEG尾帧看起来多正确，均禁止作为下一SEG生成参考，因为它可能携带：
偶发换脸、比例漂移、服装细节损失；
Motion Blur、滚动快门、压缩纹理和半眨眼；
临时构图、镜头畸变、未完成姿态或错误光线；
Prop数量、Holder、位置或场景几何的轻微错误；
与当前Canonical Storyboard、LOOK或LOC_VIEW冲突的复合Authority。
对视频尾帧做QC只能决定该SEG是否重生成，不能赋予它下一SEG Authority。
11.2 BNDPLAN必须在相邻视频生产前建立
[text]PRJ_NOVA__BNDPLAN_EP01_SEG01_TO_SEG02_R01
BNDPLAN来自Story Truth、Source/Target CVS、Spatial、当前LOOK/CT、Prop Ledger和Shot Intent，至少登记：
[text]source_seg_id / target_seg_idboundary_story_time / reality_threadsource_cvs_id / target_cvs_idcompleted_action / completed_dialoguecharacter_position_stateactive_look_ctprop_count_holder_statelocation_spatial_revisionboundary_modeexit_shot_contract / entry_shot_contractaudio_end / audio_startforbidden_cross_boundary_events
动作接触、跌倒、换装、伤势激活、Prop交接、关键对白句、J/L Cut和模型原生Transition不得跨边界拆分。
11.3 四种合法边界模式
A. CANONICAL_CUT_PAIR（同场连续默认）
在两条视频生成前，从同一Boundary State分别生成：
[text]PRJ_NOVA__BNDANCHOR_EP01_SEG01_TO_SEG02_OUT_R01PRJ_NOVA__BNDANCHOR_EP01_SEG01_TO_SEG02_IN_R01
OUT控制前一SEG最后稳定Shot；IN控制后一SEG第一个Shot。两者共享人物Identity、LOOK/CT、World Position、Zone、Support、Orientation、Prop/Count/Holder、Location/Spatial和Story Time，但Camera可以按批准的Cut Grammar不同。这样拼接点是有意设计的镜头切换，而不是要求两个独立视频逐像素接成同一运动。
B. SHARED_STABLE_ANCHOR
只有在模型经实测支持精确Start/End Reference、边界完全静止且不会产生重复停顿时，允许同一预编译Canonical Anchor同时作为前一SEG Exit Target和后一SEG Entry Primary。不得用于动作中间、说话中间、镜头运动中间或高频粒子/水火状态。
C. MOTIVATED_HARD_CUT
时间、地点、主观视点或叙事焦点明确改变时，只需BNDPLAN和下一SEG Entry Anchor。前一SEG完成自己的Exit，不追求像素匹配；下一SEG以新的Canonical Entry开始。硬切必须符合镜头语言，不能掩盖状态丢失。
D. OPAQUE_BUFFER_PAIR
当平台无法可靠控制终帧，但允许模型内生成全画面黑场、白闪、遮挡或掠过物时，可让前一SEG在动作完成后进入100%不透明稳定Buffer，下一SEG从同一Buffer开始再揭示。两端Buffer各自在本SEG内生成；不得把未完成动作藏进Buffer，也不得把它伪装成跨视频单一Transition。
11.4 Boundary Seam Gate
相邻SEG生产前检查：
[text]Action Completed Before Boundary: YESDialogue Unit Completed Before Boundary: YESState Activation Completed Before Boundary: YESPosition State Reconciled: YESProp / Count / Holder Reconciled: YESCamera Cut Grammar Intentional: YESAudio Join Defined: YESGenerated Frame Input Count: 0
任一为NO时返回SEG_BOUNDARY_DESIGN_BLOCKED并回编SEG；如果Reference Manifest出现生成帧，返回GENERATED_FRAME_REFERENCE_FORBIDDEN。
12. Image Complexity Budget
以下每项计一类复杂度：
多个时间状态；
多个不相容Zone或高度；
三个以上关键人物；
多人物手部接触；
多个Hero Prop或精确数量散落；
状态激活过程与稳定结果同时出现；
多格Storyboard与精确可读文字；
Identity、Geometry、Count、Camera和Action同时要求高精度。
保守预算下，命中两类即拆分；标准预算命中三类即拆分；扩展预算也不得把多个时间状态或不相容Zone放入同一图。
超限返回：
[text]IMAGE_COMPLEXITY_OVER_BUDGET
允许处理：
[text]SPLIT_ANCHORLOGICAL_ONLYLOCAL_IMAGE_EDITDEFER_TO_VIDEO
禁止通过缩小人物、增加格数、模糊背景或删掉关键Prop偷偷满足预算。
13. 图片错误的局部修复策略
人物脸错：回到当前CHAR/PH/LOOK Authority，只重做受影响Anchor。
服饰局部、手部或Hero Prop错：优先局部编辑；编辑结果建立新Revision。
空间站位错：重做当前Anchor或取消该Anchor并交给视频；不重做无关资产。
中间姿势错：删除图片Authority，标记DEFER_TO_VIDEO。
多格Storyboard一格错：只重做对应独立KF Anchor，再确定性重排Sheet。
背景小误差不进入Camera Reveal且不影响剧情：降低Authority或从Video Reference Set剔除。
错误已进入下游：建立新Revision并重编受影响Reference Map、Storyboard Package和Video Prompt；不得在Prompt中用文字掩盖错误图。
14. 生产链与失败码
生产链：
[text]Story Truth→ Registry / Spatial / Continuity / CVS逻辑Canon→ 最小必要Identity / LOOK / Location / Hero Prop / CT资产→ SEG Visual Risk Assessment→ Image Materialization Gate→ 少量独立Visual Anchor→ Reference Dimension Coverage Matrix→ Authority-Complete Nonconflicting Reference Set→ BNDPLAN / 可选预编译BNDANCHOR OUT与IN→ 强化Video Prompt→ Model-Native Video Execution→ Exit QC→ QC Pass或重生成；视频Frame不得回流Reference
新增失败码：
Code
条件
处理
`IMAGE_MATERIALIZATION_UNJUSTIFIED`
图片未命中任何物化触发器
改为LOGICAL_ONLY或给出真实风险证据
`IMAGE_COMPLEXITY_OVER_BUDGET`
单次图片任务超过复杂度预算
SPLIT_ANCHOR / LOCAL_IMAGE_EDIT / DEFER_TO_VIDEO
`VIDEO_RELIABILITY_UNVERIFIED`
请求HIGH路径但没有用户或Pilot证据
按MEDIUM执行
`VIDEO_REFERENCE_AUTHORITY_CONFLICT`
同一时间窗口存在冲突Primary或重叠Authority
删除/降级冲突参考并重编Role Map
`VIDEO_REFERENCE_REDUNDANT`
图片没有独有Authority或缺口
从Reference Set删除
`REFERENCE_DIMENSION_COVERAGE_GAP`
减图后Identity、LOOK/CT、Spatial、Position、State或Prop任一维无Authority
恢复必要Canonical Reference或补原子Authority
`GENERATED_FRAME_REFERENCE_FORBIDDEN`
视频截图、尾帧或Frame Grab进入任一生成Manifest
立即删除；从上游Canon编译BNDPLAN/BNDANCHOR
`SEG_BOUNDARY_DESIGN_BLOCKED`
动作、对白、状态激活或Transition跨SEG未完成
回编SEG边界到稳定Beat
`CANONICAL_BOUNDARY_MISMATCH`
BNDANCHOR与Source CVS、Spatial、LOOK/CT或Prop Ledger不符
废弃Anchor并从上游Canon生成新Revision
`VIDEO_EXECUTION_OVERLOADED`
因果、动作、音频与Camera复杂度超过实测能力
简化Camera、增加Anchor或拆分SEG

15. 完整模板
15.1 SEG Visual Risk Assessment
[text]【SEG VISUAL RISK ASSESSMENT】SEG ID:Target Video Model:Video Reliability / Evidence:Image Composite Reliability:Entry State:Exit State:Irreversible Results:First Reveal Coverage:Spatial Route Risk:Count / Holder Risk:Audio / Dialogue Risk:Model-Native Transition Risk:Required Frozen Visual Facts:Facts Safe to Defer to Video:
15.2 Image Materialization Decision
[text]【IMAGE MATERIALIZATION DECISION】Target ID:Logical Contract ID:Candidate Role:Trigger Number:Complexity Classes:Decision:Reason:If LOGICAL_ONLY, Execution Owner:If VISUAL, Required Reference Set:If VISUAL, Exact Stable Result:Forbidden Content:
15.3 Video Reference Decision与Compact Reference Identity Map
[text]【VIDEO REFERENCE SET DECISION】SEG ID:Reliability Path:Execution Mode:Reference Capacity:Chosen Reference Count:Rejected Redundant References:【REFERENCE DIMENSION COVERAGE MATRIX】Identity Authority:LOOK / Active CT Authority:Spatial / Geometry Authority:Position / Blocking Authority:State / Temporal Authority:Prop / Count / Holder Authority:Coverage Result: COMPLETE | GAP | CONFLICT【REFERENCE ROLE MAP】Image N = {完整Revision ID}Role: {MANDATORY_STORYBOARD_SPINE | IDENTITY_SUPPLEMENTAL | SPATIAL_SUPPLEMENTAL | HERO_PROP_SUPPLEMENTAL | CANONICAL_BOUNDARY}Who / What + Visible Content:Story Time / Current State:Controls:Does Not Control:Applicable Time Window:Unique Authority Contribution:Admission Status: PASS | FAIL
若任一Image缺少完整Revision ID、Who / What + Visible Content、Story Time / Current State、Controls、Does Not Control或Applicable Time Window，返回REFERENCE_MAPPING_BLOCKED；不得靠上传顺序或文件外观猜测主体。
15.4 Canonical Boundary Plan与Anchor Record
[text]【CANONICAL BOUNDARY PLAN】BNDPLAN ID:Source SEG / Target SEG:Boundary Story Time / Reality Thread:Source CVS / Target CVS:Boundary Mode:Completed Action / Dialogue / State Activation:Character Identity + LOOK/CT:World Position / Zone / Anchor / Support / Orientation:Location / Spatial / GEO:Prop / Count / Holder:Exit Shot Contract:Entry Shot Contract:Audio End / Audio Start:Forbidden Cross-Boundary Events:Generated Frame Reference Count: 0【OPTIONAL CANONICAL BOUNDARY ANCHORS】OUT Anchor ID / Fingerprint:IN Anchor ID / Fingerprint:Source Canonical References:Dimension Coverage:Controls:Does Not Control:Status: APPROVED | REJECTED
16. 结束前审计
[ ] 逻辑Canon完整，没有因少生成图片而删除CVS、Position、Count、Holder或Temporal字段。
[ ] 每张新增图片都命中明确Materialization Trigger；不存在“可能有用”的保险图。
[ ] 中间姿势、动作过程、Camera与情绪渐变已交给视频，不再强制SCSTATE/KF出图。
[ ] Hero人物当前完整LOOK、首次显露覆盖、关键Location和不可逆CT仍有足够Authority。
[ ] SCSTATE是逻辑合同，Visual Slice为可选稳定结果；没有默认一CVS一图。
[ ] Storyboard所有KF都有文字Canon，且已物化足以覆盖完整关键推进的有序视觉载体。
[ ] 没有让图片模型默认一次生成三格Storyboard；Sheet由已批准Anchor确定性排版或使用有序独立KF载体。
[ ] 每个Video SEG都有Mandatory Storyboard Temporal Spine；可靠度只调整骨架颗粒度、补图和Prompt冗余度。
[ ] 每张Storyboard参考均通过Revision、SEG、Thread、时间、状态、位置、Prop、Boundary和顺序Admission。
[ ] 六维Coverage Matrix完整；Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal、Prop/Count/Holder均有唯一Authority。
[ ] Storyboard载体共同构成唯一有序时间/镜头骨架；Supplemental图不控制Camera、Blocking、Time或Action Phase。
[ ] 同一状态未重复上传SCSTATE、Storyboard、Anchor、LOOK和Location PR；每次删除均未制造维度缺口。
[ ] 每张视频参考图都有独有Authority贡献；没有为了填满模型上限增加图片。
[ ] Video Prompt重新写完整SEG、逐窗口导演执行卡、微表演、动作阶段、物理反应、Camera Grammar、声音同步和Exit。
[ ] 图像复杂度超预算的任务已拆分、局部编辑或DEFER_TO_VIDEO。
[ ] 每对相邻SEG在生产前已有BNDPLAN，必要时已有来自上游Canon的BNDANCHOR OUT/IN。
[ ] 所有生成视频尾帧、截图和Frame Grab只用于QC，未进入任何图片或视频Reference Manifest。
[ ] 动作、对白、状态激活与模型原生Transition没有跨SEG拆分；Boundary Seam Gate全部通过。
[ ] 人物与场景位置锁定仍完整存在，未因SCSTATE或Storyboard减图而删除Zone、Anchor、Support、Route、Barrier/Portal或Orientation。
[ ] 模型可靠度有用户或Pilot证据；失败后已降级路径而非维持虚假HIGH。
