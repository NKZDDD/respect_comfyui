第十七部分｜Story-First、Zone-Coherent SCSTATE与故事板可读性门控
目录
适用范围与核心修正
Story-First编译顺序
CVS与SCSTATE Slice的Authority关系
Zone-Coherent SCSTATE Slice判定
SCSTATE Slice注册与命名
SCSTATE Slice状态合同
Narrative Sufficiency Gate
SCSTATE生产提示词顺序
Storyboard Sheet可读性门控
Storyboard逐Sheet合同
Storyboard Prompt顺序
Video Story Recompile与逐秒因果
Video Mandatory Storyboard Reference Policy
首次显露缺口与补充参考例外
错误SCSTATE的回编规则
失败码与修复路径
最终审计清单
1. 适用范围与核心修正
本规则用于修复以下系统性错误：
把CVS全局逻辑完整性误解为“单张SCSTATE必须同时显示全部Active Zone”；
为了让所有Active实体同框而缩短真实距离、移动人物、改变高度或融合地点；
一张状态图同时承担两个互不Camera-coherent的剧情焦点；
SCSTATE只剩ID、坐标和状态字段，生产模型无法理解原文确切时刻；
Storyboard一张Sheet塞入4格以上，人物、武器、表情、伤势、手部与关键Prop不可检查；
Video Prompt把完整剧情理解外包给Storyboard标签；
Video同时上传Storyboard、SCSTATE、LOOK、Location、LOC_VIEW、PR和Prop，形成重复Composite Authority。
核心原则：
CVS负责全局世界真相；SCSTATE负责逻辑状态合同，可选Visual Slice只冻结必要Cluster；Storyboard负责按时间和镜头语言描述该真相，只有必要KF物化Anchor；Video Prompt负责重新讲清完整SEG因果并执行。
2. Story-First编译顺序
所有SCSTATE、Storyboard和Video production_prompt必须按以下顺序编译，技术合同不得提前淹没剧情语义：
[text]1. FULL SCENE STORY CANON2. EXACT VISUAL MOMENT3. BEFORE / NOW / AFTER4. PRIMARY NARRATIVE SUBJECT5. COMPACT REFERENCE IDENTITY MAP6. Spatial / Count / Temporal / Camera / Forbidden Contracts
2.1 FULL SCENE STORY CANON
使用自然语言说明：
本场施动者是谁；
当前目标是什么；
谁或什么构成阻力；
动作如何产生结果；
本场关键不可逆结果是什么；
观众在当前Story Time已经知道什么、尚不知道什么。
不得把全剧Hidden Truth提前写入当前Presented Truth。
2.2 EXACT VISUAL MOMENT
明确当前图像只表现：
哪个精确Story Time或Beat位置；
哪个Zone或Camera-coherent Spatial Cluster；
谁正在对谁做什么；
动作Phase是Entry、Anticipation、Contact、Reaction还是Stable Result；
当前画面必须能验证的唯一剧情事实。
2.3 BEFORE / NOW / AFTER
必须同时说明：
BEFORE：此前已经成立并持续进入当前画面的状态；
NOW：当前图像要稳定呈现的状态或动作阶段；
AFTER：下一刻将发生但当前仍未发生的事件与Future-State Embargo。
2.4 PRIMARY NARRATIVE SUBJECT
每张SCSTATE Slice、每个KF与每张Storyboard Sheet必须声明一个主叙事焦点。背景人物和次级反应可以存在，但不得与主焦点争夺画面解释权。
3. CVS与SCSTATE Slice的Authority关系
CVS始终是唯一全局世界真相，包含同一Story Time全部Active实体、Zone、位置、Holder、Count、持续状态和环境状态。
SCSTATE Slice不是第二套CVS，也不是新的Reality Thread。它只在通过Image Materialization Gate后，把Source CVS中的一个Camera-coherent Spatial Cluster视觉物化；未通过时SCSTATE保持完整逻辑合同。
同一CVS派生的全部Slice必须共享：
[text]source_cvs_idstory_timereality_threadobject_count_registeractive_instance_registerlocation/spatial revisiontemporal state
不同Slice之间只允许下列差异：
[text]visible_zone_setprimary_narrative_subjectcamera_coherent_clustervisibility bucketneutral observation camera
其他Zone中仍存在的实体必须登记为OFF-FRAME ACTIVE。离画不等于消失，不得减少Active Count。
4. Zone-Coherent SCSTATE Slice判定
当Source CVS满足任一条件时，强制建立多个SCSTATE Slice：
Active实体分布在无法由单一中性Camera清晰验证的远距离Zone；
Zone之间存在不同楼层、高度、封闭房间、Barrier或Portal；
同一画面必须使用不相容的动作轴或观察方向才能看清两个事件；
为了同框必须改变人物World Position、缩短Route、跨越Barrier或压缩Location尺度；
需要蒙太奇、分屏、拼贴或不自然超广角才能显示全部状态；
两个剧情焦点无法在同一空间层级中保持一个明确Primary Narrative Subject；
关键手部、武器、伤势、碰撞或Prop状态会因全局同框而失去可检查细节。
若一张中性全景能够保持真实距离、真实Zone、清晰主焦点并验证所有必要状态，可以保留单一SCSTATE，不得为形式而强制切Slice。
Camera-coherent Spatial Cluster
一个合法Cluster必须满足：
所有可见实体可由同一连续空间和同一Location Revision解释；
不改变Source CVS中任何实体的World Position State；
不穿越未发生的Portal、Route或Support Release；
一个中性观察机位可以清楚验证当前剧情焦点；
被省略的Active实体均能准确登记为OFF-FRAME ACTIVE。
5. SCSTATE Slice注册与命名
当SCSTATE需要切片时，保留父状态ID并为每个视觉切片分配完整Canonical Revision ID：
[text]PRJ_NOVA__CVS_EP01_SC03_04_R01PRJ_NOVA__SCSTATE_EP01_SC03_ST04_R01PRJ_NOVA__SCSTATE_EP01_SC03_ST04_SLC01_R01PRJ_NOVA__SCSTATE_EP01_SC03_ST04_SLC02_R01
字段合同：
[text]slice_idparent_scstate_idsource_cvs_idstory_timecamera_coherent_cluster_idvisible_zone_setprimary_narrative_subjectvisible_active_entitiesoff_frame_active_entitiesshared_object_count_registershared_spatial_revision
SLC01、SLC02只能出现在说明性阅读中；任何Manifest、Prompt、Storyboard、KF或Video字段必须使用完整Revision ID。
同一CVS的多个Slice不得出现不同Object Count、不同Holder历史或相互矛盾的当前位置。若出现冲突，全部Slice作废并返回Source CVS审计。
6. SCSTATE Slice状态合同
每个Slice必须逐实体分类：
[text]VISIBLE FULLVISIBLE PARTIALOCCLUDED BUT ACTIVEOFF-FRAME ACTIVENOT ACTIVE / FORBIDDEN
并满足：
[text]Visible Full+ Visible Partial+ Occluded But Active+ Off-frame Active= Source CVS Active Total
Slice不得：
为了显示离画实体而移动当前可见实体；
把相邻Zone背景贴进当前Zone；
把不同高度或房间融合为同一平面；
以分屏、九宫格或蒙太奇冒充单一稳定状态图；
将After事件、未来伤势或未来Prop状态提前显示；
通过删除OFF-FRAME实体降低Object Count。
7. Narrative Sufficiency Gate
任何SCSTATE、Storyboard或Video Prompt在释放前执行以下测试：
如果隐藏全部ID，仅阅读自然语言Prompt，能否准确回答：这是原文哪个确切时刻、画面主角是谁、正在发生什么、此前发生了什么、下一刻什么仍未发生？
不能回答时返回：
[text]SCSTATE_STORY_CONTEXT_INSUFFICIENT
如果一张SCSTATE同时承担两个无法在同一连续空间清楚观察的剧情焦点，返回：
[text]SCSTATE_SPATIAL_SLICE_REQUIRED
如果画面意图、人物施受关系、动作结果或观众知识与Source CVS/原文因果不符，返回：
[text]SCSTATE_STORY_MISMATCH
任一错误都阻断Storyboard与Video编译。
8. SCSTATE生产提示词顺序
每个SCSTATE或Slice Prompt必须使用以下骨架：
[text]【FULL SCENE STORY CANON】{自然语言说明本场施动者、目标、冲突、因果、关键结果、观众已知/未知}【EXACT VISUAL MOMENT】Story Time：{精确时刻}Visible Zone / Cluster：{本Slice唯一空间簇}Action Phase：{稳定状态或动作阶段}Moment Sentence：{谁正在对谁做什么，当前画面验证什么}【BEFORE / NOW / AFTER】BEFORE：{已成立状态}NOW：{当前必须呈现}AFTER：{尚未发生；明确Future-State Embargo}【PRIMARY NARRATIVE SUBJECT】{唯一主焦点及画面阅读目标}【COMPACT REFERENCE IDENTITY MAP】{逐Image完整六字段映射：Exact ID / Who / What + Visible Content / Story Time / Current State / Controls / Does Not Control / Applicable Scope}【SOURCE AND SLICE CONTRACT】Parent SCSTATE：{完整ID}Source CVS：{完整ID}Visible Zone Set：{Zone列表}OFF-FRAME ACTIVE：{仍存在但本Slice不显示的实体}Object Count Reconciliation：{与Source CVS对账}【SPATIAL / TEMPORAL / CAMERA / FORBIDDEN】{World Position、Support、Holder、Count、时间门控、中性Camera、禁止事项}
技术字段正确但上述五个Story-First部分不完整，Prompt仍然不合格。
任一Image缺少完整Revision ID、Who/What、Current State、Controls、Does Not Control或Applicable Scope，返回REFERENCE_MAPPING_BLOCKED，不得依靠图片顺序猜测身份。
9. Storyboard Sheet可读性门控
每张Canonical Storyboard Sheet最多包含3个KF或分镜。
强制规则：
禁止4格以上高密度排版；
禁止九宫格；
禁止通过缩小人物或扩大无关空白来容纳更多分镜；
动作、兵器、表情、伤势、手部交互、马匹碰撞和关键Prop必须保留可检查细节；
每格必须能独立判断主叙事焦点与Action Phase；
需要更多关键时刻时增加Continuation Sheet，不得删除关键结果或把多个Action Phase塞入同一格；
增加Sheet只改变承载方式，不产生第二套Canon；同一SEG仍只有一个SBPKG。
默认每个30秒SEG使用2至3张有序Continuation Sheet。若关键时刻超过9个，不得突破每Sheet三格；先审计SEG是否过载、KF是否重复。仍不可删减时，允许增加Sheet并记录STORYBOARD_REFERENCE_CAPACITY_EXCEPTION，Video仍按时间上传全部Canonical Sheet。
10. Storyboard逐Sheet合同
每张Sheet必须写明：
[text]SBPKG_IDSHEET_IDSEG_FULL_STORY_SUMMARYSEG_TIME_RANGESHEET_TIME_RANGESOURCE_CVS_IDSOURCE_SCSTATE_SLICE_ID_LISTPRIMARY_NARRATIVE_SUBJECTCONTINUATION_ORDER
每个KF必须写：
[text]KF_IDnatural_language_story_sentencespeakerdialogue_or_vocal_actionsource_scstate_slice_idaction_phaseposition_stateposition_deltaprop_instance_stateforbidden_future_statecamera_observation
自然语言剧情句必须描述“谁对谁做什么以及这一刻改变了什么”，不能只写“近景”“反应镜头”“KF03”。
11. Storyboard Prompt顺序
Storyboard Prompt同样先写Story，再写技术合同：
[text]【FULL SEG STORY CANON】{完整SEG自然语言剧情摘要、因果与观众知识}【EXACT VISUAL MOMENT OF THIS SHEET】{本Sheet时间范围、Zone、当前动作阶段、与前后Sheet关系}【BEFORE / NOW / AFTER】{上一Sheet稳定出口 / 本Sheet动作 / 下一Sheet尚未发生事件}【PRIMARY NARRATIVE SUBJECT】{本Sheet唯一叙事焦点}【COMPACT REFERENCE IDENTITY MAP】{逐Image映射到Source SCSTATE Slice及Applicable KF}【KF STORY CONTRACTS】{每个KF的自然语言剧情句、说话者、对白、Action Phase、Position Delta、Forbidden Future State}【SPATIAL / COUNT / TEMPORAL / CAMERA / FORBIDDEN】{技术合同}
每张Sheet只引用支持本Sheet时间和Zone的SCSTATE Slice。不得为了完整感同时上传同一CVS的全部Slice。
12. Video Story Recompile与逐秒因果
Video Prompt必须重新写完整30秒剧情摘要和逐秒因果，不能假定视频模型能从Storyboard标签自行推导故事。
至少包含：
[text]FULL 30-SECOND STORY SUMMARYENTRY WORLD STATESECOND-BY-SECOND CAUSAL EXECUTIONDIALOGUE / SPEAKER / VOCAL TIMINGACTION CONTACT AND RESULT TIMINGTRANSITION OWNERSHIPEXIT WORLD STATEFORBIDDEN FUTURE STATE
逐秒因果不是镜头标签列表。每个时间窗必须说明施动者、动作、受动者、物理结果、反应与下一动作的触发关系。
13. Video Mandatory Storyboard Reference Policy
Video读取[强制Storyboard时间骨架、有效参考选择与导演级Video执行](19-mandatory-storyboard-directorial-video-execution.md)，先以六维Coverage Matrix确认Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal与Prop/Count/Holder完整，再从当前SBPKG建立覆盖完整关键推进的Mandatory Storyboard Temporal Spine。可靠度影响骨架载体、补图数量和Prompt冗余度，不允许省略Storyboard。
[text]Image 1..N = 当前SEG按时间排列的全部必要Continuation Sheets或等价有序KF AnchorsImage N+1 = 已证明必要的主角当前完整LOOK/CTImage N+2 = 已证明必要的核心LOC_VIEWImage N+3 = 已证明必要的Hero Prop或BNDANCHOR
每个Image必须映射：
[text]Exact Anchor / Storyboard Sheet / BNDANCHOR Revision IDReference RoleSEG time rangesheet time rangecontained KF IDsvisible story momentcontrolsdoes not controlapplicable video window
Storyboard骨架以外默认禁止上传：
对应SCSTATE或SCSTATE Slice；
人物CHAR、PH、LOOK或CT；
LOC、SPATIAL、GEO、LOC_VIEW、VIEWPACK或PR；
马匹、车辆、武器、Hero Prop或其他原子资产。
所有Storyboard载体共同构成一条有序Temporal Spine，不是互相竞争的多套World State。SCSTATE是上游逻辑/可选视觉中间态，不得与同状态Storyboard形成双主权；Supplemental只控制自己的缺口，不控制时间顺序、Action Phase、Blocking或Camera编排。
14. Storyboard Admission与有效补充参考
Video先对每张Storyboard参考执行Admission，再判断是否需要补充原子参考图：
[text]1. 核对SBPKG Revision、SEG、Reality Thread、时间范围、Source State、LOOK/CT、World Position、Prop状态、Boundary关系与顺序2. 检查缺口是否可通过回编Storyboard补足3. 优先新建或修订Canonical Storyboard Sheet/KF4. 重新执行Storyboard可读性、完整时间骨架与Reference Capacity审计5. 只有Storyboard无法充分承担且补图有唯一Authority贡献时，才加入原子Reference
补充参考必须记录：
[text]storyboard_admission_statusmissing_visual_authorityfirst_reveal_windowwhy_storyboard_recompile_is_insufficientsupplemental_exact_idunique_authority_contributioncontrolsdoes_not_controlapplicable_scope
补充资产只控制缺失的Identity、服饰/身体覆盖、关键文字、Geometry或Hero Prop外观，不得控制Camera、Pose、Blocking、Action Phase、Story Time或Position State。删图前必须证明Source CVS、World Position、Zone、Anchor、Support、Route、Orientation与相关LOC_VIEW仍在Authority链中。
任何生成视频截图、尾帧或Frame Grab禁止进入Reference Map；相邻SEG只能读取两条视频生产前已建立的BNDPLAN及可选BNDANCHOR OUT/IN。
Admission失败或无法证明补图作用时返回：
[text]STORYBOARD_REFERENCE_ADMISSION_FAILEDVIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN
15. 错误SCSTATE的回编规则
错误SCSTATE不得在Storyboard阶段“修好”，因为这样会形成上游错误、下游正确的双重世界状态。
发现SCSTATE错误时必须：
[text]1. 标记错误SCSTATE/Slice为REJECTED_CANDIDATE或SUPERSEDED2. 判断Source CVS是否正确3. CVS正确：建立新的SCSTATE Revision或新SLC4. CVS错误：先修订CVS并重新冻结Continuity5. 重新编译全部受影响Storyboard Sheet、KF、Shot、Transition和Video6. 禁止旧SCSTATE、旧Storyboard或旧Video继续作为Reference
不得仅修改Storyboard人物位置来掩盖SCSTATE的Zone、因果或主焦点错误。
16. 失败码与修复路径
失败码
触发条件
修复
`SCSTATE_STORY_CONTEXT_INSUFFICIENT`
隐藏ID后无法理解原文时刻与动作
重写Story-First五部分
`SCSTATE_SPATIAL_SLICE_REQUIRED`
一个状态图承担多个不相容空间焦点
从同一CVS建立多个SLC
`SCSTATE_STORY_MISMATCH`
画面意图或因果不符合Source CVS/原文
停止下游并修订SCSTATE或CVS
`STORYBOARD_DENSITY_BLOCKED`
Sheet超过3格或关键细节不可检查
增加Continuation Sheet
`STORYBOARD_STORY_CONTEXT_INSUFFICIENT`
Sheet/KF只有标签而无剧情句
补全SEG摘要与逐KF自然语言合同
`STORYBOARD_SOURCE_SLICE_MISMATCH`
KF引用错误Zone/时间的Slice
更换Source Slice并重编Sheet
`STORYBOARD_REFERENCE_CAPACITY_EXCEPTION`
关键时刻超过3张Sheet容量
审计SEG/KF后保留必要额外Sheet
`VIDEO_STORY_CONTEXT_INSUFFICIENT`
Video未重写完整30秒故事和逐秒因果
重编Video Prompt
`VIDEO_STORYBOARD_SPINE_MISSING`
Video没有覆盖完整关键推进的Storyboard视觉骨架
补齐有序Sheet或等价KF Anchors
`STORYBOARD_REFERENCE_ADMISSION_FAILED`
Storyboard错版、错SEG、错时间、错状态或错位置
换成当前SBPKG合法载体并重审
`STORYBOARD_REFERENCE_CAPACITY_BLOCKED`
平台容量无法承载完整必要骨架
去重、换载体或在稳定Beat拆SEG
`VIDEO_REFERENCE_COMPOSITE_CONFLICT`
Video同时上传Storyboard与SCSTATE/重复资产
删除重复Composite Reference
`VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN`
原子补图没有独有Authority贡献
优先回编Storyboard或删除补图
`VIDEO_PROMPT_EXECUTION_DETAIL_INSUFFICIENT`
Video Prompt没有逐窗口可执行导演指令
补齐动作、表演、Camera、声音与出口

17. 最终审计清单
[ ] 每个Prompt先写Story-First五部分，再写技术合同。
[ ] 隐藏ID后仍能判断确切故事时刻、主角、动作、前因与下一刻禁入事件。
[ ] CVS仍是唯一全局World Truth。
[ ] 跨远距离、不同高度、Barrier或不相容动作轴的状态已切为Zone-Coherent SLC。
[ ] 所有SLC共享Source CVS、Story Time、Object Count和Spatial Revision。
[ ] 其他Zone实体登记为OFF-FRAME ACTIVE，没有被删除或移动。
[ ] 每张SCSTATE Slice只有一个Primary Narrative Subject。
[ ] 错误SCSTATE没有在Storyboard阶段偷偷修正。
[ ] 每张Storyboard Sheet最多3个KF，没有九宫格或高密度缩人排版。
[ ] 每张Sheet包含完整SEG摘要、时间范围和Source Slice。
[ ] 每个KF包含自然语言剧情句、说话者/对白、Action Phase、Position Delta和Forbidden Future State。
[ ] 同一SEG只有一个SBPKG；Continuation Sheet只是有序承载。
[ ] Video Prompt重新写完整30秒剧情摘要和逐秒因果。
[ ] Video具有覆盖完整关键推进的Mandatory Storyboard Temporal Spine，每张Storyboard参考都通过Admission。
[ ] 每张Supplemental都有Role、独有Authority与Applicable Window，六维Coverage无缺口。
[ ] 人物与场景位置锁定未因SCSTATE/SBSHEET减图丢失，生成视频帧未进入下一SEG参考。
[ ] Storyboard载体共同组成一条有序时间骨架；同一状态未重复上传SCSTATE、LOOK或Location PR。
[ ] 原子补图只解决明确Identity、Coverage、Geometry、Prop或State Result缺口。
