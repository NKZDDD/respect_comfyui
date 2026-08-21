第十九部分｜强制Storyboard时间骨架、有效参考选择与导演级Video执行
目录
核心结论
Mandatory Storyboard Temporal Spine
Storyboard视觉承载形式
Storyboard Reference Admission Gate
Effective Reference Selection Gate
视频参考角色与推荐组合
Director-Level Video Prompt
Temporal Window Execution Card
Micro-Performance Contract
Action Phase & Physical Response Contract
Cinematic Camera Grammar Contract
Audio-Visual Synchronization
Detail Density与执行复杂度
Quality Priority与Fallback
失败码与修复
完整生产模板
结束前审计
1. 核心结论
视频模型能力增强后，把中间动作、微表演、运镜、原生切换和声音执行交给Video；不得把人物身份、当前LOOK/CT、场景几何、World Position、时间状态、Prop实例或剧情结果交给模型自由重写。
正式关系：
[text]Mandatory Canonical Storyboard Temporal Spine+ Selective Effective Character / Location / Prop References+ Expanded Directorial Video Prompt→ Model-Native Complete Video
不得以“视频模型很强”为由取消Storyboard，也不得以“稳定”为由把SCSTATE、全部人物资产、全部Location View和Prop同时堆入Video。
2. Mandatory Storyboard Temporal Spine
每个正式生产SEG必须拥有一个唯一Canonical Storyboard Package，且Video Reference Manifest必须包含能覆盖本SEG完整关键时间进程的视觉载体：
[text]storyboard_video_reference_policy = mandatory_temporal_spine
Storyboard Temporal Spine必须回答：
本SEG先发生什么、后发生什么；
每个关键Beat由谁施动、谁受动；
人物从哪个World Position开始，经什么Authorized Route到达什么Anchor；
每个关键Action Phase、Contact、Reaction与Stable Result；
Shot顺序、观察方向、切换动机与Transition所有权；
哪个事件激活CT、Prop或Location State；
SEG出口的Character、Spatial、Count、Holder与Temporal Truth。
人物LOOK、LOC_VIEW、Prop SPEC、SCSTATE或文字Prompt均不能替代Storyboard Temporal Spine。
2.1 完整覆盖不等于每个动作都出图
所有KF继续保留文字Canon；视觉Spine只物化足以锁定完整关键时间进程的Entry、Turn、Contact/Activation、Irreversible Result、Exit与高风险Blocking Anchor。自然中间运动交给Video Prompt展开。
不得出现某个关键时间窗既没有Storyboard Sheet/KF Anchor覆盖，也没有合法理由标记为两Anchor之间的Video Reconstruction。
2.2 Capacity处理
若完整Storyboard Spine超过模型参考上限：
删除重复情绪KF，不删关键因果；
把同一SBPKG内已批准Anchor确定性排为每Sheet最多3格；
在模型更适合独立图片时，上传同一SBPKG的有序独立KF Anchor；
仍超容量时拆分SEG并重新建立稳定边界；
禁止静默丢弃中段转折、Action Completion或Exit Result。
无法在容量内提供完整Temporal Spine时返回STORYBOARD_REFERENCE_CAPACITY_BLOCKED。
3. Storyboard视觉承载形式
Storyboard不可缺少，但允许根据模型实测选择两种等价承载：
3.1 Ordered Continuation Sheets
[text]Image 1 = Storyboard Sheet A / SEG前段Image 2 = Storyboard Sheet B / SEG中段Image 3 = Storyboard Sheet C / SEG后段
每张最多3个KF，所有Sheet共享同一SBPKG与Continuation Order。Video不得生成Sheet边框、标签或Panel Layout。
3.2 Ordered Independent KF Anchors
[text]Image 1 = Entry AnchorImage 2 = Turn AnchorImage 3 = Contact / Activation AnchorImage 4 = Result AnchorImage 5 = Exit Anchor
它们仍是Canonical Storyboard的视觉承载，不是绕过Storyboard的另一套Reference系统。适用于多格Sheet理解不稳定、Panel融合或未来状态泄漏风险较高的模型。
4. Storyboard Reference Admission Gate
Storyboard在Canon中存在不等于其图片自动有Video Reference资格。每张Sheet或Anchor进入Video前逐项审核：
[text]Narrative AccuracyCharacter IdentityCurrent LOOK / CTSpatial / GeometryWorld Position / Zone / Anchor / OrientationSupport / Route / Barrier / PortalTemporal State / Future-State EmbargoProp Instance / Count / HolderAction PhaseCamera ObservationImage Legibility / Face / Hand / Critical Detail
任一关键项错误时：
[text]STORYBOARD_REFERENCE_ADMISSION_FAILED
修复顺序：
判断Source CVS、Blocking、Shot与KF文字Canon是否正确；
上游正确则建立新Storyboard/KF Visual Revision；
上游错误则先修订最近有Authority的层；
重编受影响Sheet、Reference Map、Video Prompt与BNDPLAN；
禁止用正确LOOK、LOC_VIEW或文字Prompt去“压过”错误Storyboard。
5. Effective Reference Selection Gate
Mandatory Storyboard Spine之外，人物、场景和Prop图片按“是否产生独有有效作用”选择，不固定数量。
每张候选Supplemental必须同时满足：
[text]CORRECT = 通过Reference Admission与Canonical ResolutionUNIQUE = 解决未被Storyboard Spine覆盖的独有Authority缺口NONCONFLICTING = 不控制Camera、Blocking、Time或Action PhaseWINDOWED = 有明确Applicable Video WindowLEGIBLE = 对模型可见且足以解决该缺口
任一不满足则返回VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN并删除候选。
5.1 合法补图触发器
Hero Identity在Storyboard中不够清晰或跨镜头易漂；
当前完整LOOK/CT的身体、背面、下装、鞋履或伤势区域将首次显露；
Camera Reveal进入Storyboard未充分说明但已由Spatial批准的新Zone/观察方向；
Hero Prop文字、结构、尺寸或状态结果在Storyboard中不可辨；
不可逆CT Result需要独立清晰Authority；
模型Pilot证明某一维度仅靠Storyboard不稳定。
5.2 禁止补图动机
为填满模型Reference上限；
“可能有用”或“多一张更保险”；
与Storyboard表达完全相同状态；
错误Storyboard尚未修复；
让LOOK重新控制Pose或Blocking；
让LOC_VIEW重新控制当前Camera Composition；
让Prop SPEC重新决定Holder、Count或Action Phase。
6. 视频参考角色与推荐组合
典型30秒SEG可从下列候选池动态选择：
[text]Mandatory Temporal Spine:- 1...N ordered Storyboard Sheets  OR- 2...N ordered Independent Storyboard KF AnchorsSelective Supplemental:- 0...N current Hero LOOK / CT- 0...1 relevant core LOC_VIEW per active Camera Reveal cluster- 0...N critical Hero Prop / State Result references- optional precompiled BNDANCHOR IN / OUT
典型双人或三人多镜头SEG常为4至7张，但这不是固定数量。每个Image必须有独有Authority贡献；关键Storyboard Spine不得为了保留补图而被挤出容量。
6.1 Reference Role分权
Reference
Controls
Does Not Control
Storyboard Sheet / KF Anchor
Story Time、Shot、Blocking、Action Phase、Camera Intent、State Result
完整未显示人物覆盖、未显示Geometry与Prop微细节
Current LOOK / CT
Identity、比例、服饰、当前伤势与可见覆盖
Pose、Position、Camera、Time、Action Phase
LOC_VIEW
固定建筑、Landmark、材质、门窗、已批准Visible Zone
人物Blocking、当前Camera Path、Story Time
Prop SPEC / Result
外观、材质、尺寸、结构或批准结果
Instance Holder、Count、Trajectory、Action Time
BNDANCHOR
预编译Canonical Boundary State
生成视频偶然尾帧与未批准动作

同一时间窗只能有一个Storyboard Temporal Primary；Supplemental按维度补充，不构成第二个Composite Primary。SCSTATE/SLC默认不上传Video。
7. Director-Level Video Prompt
Video Prompt不得只有字段标题、镜头标签或一句动作摘要。固定包含：
MODEL CAPABILITY与完整成片输出合同；
MANDATORY STORYBOARD TEMPORAL SPINE MAP；
FULL SEG STORY CANON；
EXACT SEG RANGE与BEFORE/NOW/AFTER；
PRIMARY NARRATIVE SUBJECT与Dramatic Arc；
Reference Admission结果、Role Map与六维Coverage；
GLOBAL CANONICAL INVARIANTS；
TEMPORAL WINDOW EXECUTION CARDS；
MICRO-PERFORMANCE CONTRACT；
ACTION PHASE & PHYSICAL RESPONSE；
CINEMATIC CAMERA GRAMMAR；
DIALOGUE、SFX、Ambience与Music同步；
Temporal State、Prop Count、No Replay与Forbidden；
FINAL STATE、BNDPLAN与Output Format；
QUALITY PRIORITY与Fallback。
每个部分必须结合当前剧情填满；不得只交付模板骨架。
8. Temporal Window Execution Card
把固定SEG按因果、表演、镜头与状态变化动态划分窗口。普通Beat可以2至5秒，高风险接触、交接、跌倒或状态激活可细分为0.5至1.5秒；不得机械固定窗口数量。
每个窗口至少写：
[text]TIME WINDOWSTORY / BEAT PURPOSEACTIVE CHARACTER / LOOK / CTWORLD POSITION / ZONE / ANCHOR / SUPPORT / ORIENTATIONPROP INSTANCE / COUNT / HOLDERPRIMARY NARRATIVE SUBJECTTRIGGERACTION CAUSALITYACTION PHASEPHYSICAL PATH / COMPLETION CONDITIONMICRO-PERFORMANCEEYE-LINE / ATTENTIONCAMERA / COMPOSITION / FOCUSCUT OR TRANSITION MOTIVATIONDIALOGUE / VOCAL DELIVERY / LIP SYNCSFX / AMBIENCE / MUSICSTATE DELTANEXT TRIGGERFORBIDDEN FUTURE STATE
逐窗重复当前持续状态和关键位置，不以“同上”“保持一致”代替。
9. Micro-Performance Contract
“细腻”来自角色目标、压抑与泄露，不来自堆砌随机动作。关键Beat至少选择与剧情相关的下列维度：
[text]internal objectivesubtextattention targeteye movement before head movementbreath pattern / breath changefacial muscle tensionblink / swallow / hesitationhand and finger behaviorbody tension / weight shiftreaction latencyrestraint / leakage / releasespeech preparation and recovery
使用可拍行为描述，例如“先保持面对记者，眼睛先右移，停顿半秒后才转头”，不要只写“紧张”“悲伤”或“电影感表演”。
背景人物只获得符合空间与事件的低优先级自然反应，不得抢夺Primary Narrative Subject。
10. Action Phase & Physical Response Contract
攻击、跌倒、搀扶、交接、拥抱、起身、转身、开门、上下车等高风险动作按需要展开：
[text]ANTICIPATIONINITIATIONTRAJECTORYCONTACTFOLLOW-THROUGHREACTION LATENCYRECOVERY / LOSS OF BALANCESTABLE RESULT
逐Phase写施动者、受动者、身体或Prop路径、接触位置、重量与惯性、完成条件、声音和状态Delta。
硬规则：
受动者不得在Contact前完整反应；
Prop不得在手闭合前成为Holder；
跌倒必须有失衡、支撑失败与落地过程；
Completion后不得Replay；
CT只在Activation Action Completion后生效；
中间姿势不建立新的Stable Canon，除非剧情需要。
11. Cinematic Camera Grammar Contract
每个Shot或切换必须说明：
[text]Narrative FunctionSource Storyboard KF / Time WindowShot Size / Angle / Lens IntentCamera World Position / Look-at或自然语言投影Composition / Depth Layers / Subject PriorityCamera Movement Start / Path / Speed Change / StopEye-line / Axis / Screen DirectionFocus Target / Focus PullCamera Reveal EnvelopeCut Motivation / Edit RelationshipTransition Mechanism / Shield / Switch PointInformation Revealed by the New Shot
Camera只投影Canonical World，不移动人物、门窗、家具、Zone或Prop。不得为了“更有张力”增加无功能推拉摇移；镜头复杂度必须服务Beat、表演或信息。
12. Audio-Visual Synchronization
原生音频模式逐窗锁定：
Dialogue/VO/OS的准确文字、Speaker、开始/结束、语速、停顿与情绪策略；
口型只绑定当前Speaker；
脚步、布料、抓握、碰撞、落地、呼吸等动作声与物理事件同步；
Room Tone与Ambience随Location持续；
J-Cut、L-Cut、Sound Match/Drop或Ambience Bridge与Transition属于同一生成；
音乐不覆盖关键对白和关键物理声音。
声音缺失不得通过增加Camera复杂度补偿。
13. Detail Density与执行复杂度
Prompt更详细不等于每秒堆满事件。为每个SEG执行：
[text]Narrative Event LoadHero CountDialogue LoadHigh-Risk Action Phase CountCamera / Transition LoadAudio Synchronization LoadState Activation Count
如果模型负载过高，优先减少装饰性背景动作、复杂景深、无必要拉焦、无功能运镜和重复Reaction Shot；不得删除关键因果、Storyboard Spine、Identity、LOOK/CT、World Position、Action Completion、Mandatory Audio或Canonical Result。
Prompt只有长篇形容词、重复禁令或每个窗口都完全相同的描述时，不算高Detail Density。
14. Quality Priority与Fallback
冲突或超载时按以下顺序保护：
[text]1. Story Truth / Storyboard Temporal Spine2. Boundary / Entry / Exit3. Character Identity + Current LOOK / CT4. World Position / Spatial / Geometry5. State / Prop Instance / Count / Holder6. Mandatory Dialogue / Audio7. Action Completion / Physical Causality8. Performance Intent / Reaction Priority9. Camera Complexity / Focus Effects10. Decorative Detail / Background Micro-action
允许把复杂运镜降级为稳定Camera、把多次拉焦降为单一Focus或把装饰动作交给自然生成；禁止用简化Camera作为人物瞬移、动作缺失或状态重置的理由。
15. 失败码与修复
Code
Trigger
Repair
`VIDEO_STORYBOARD_SPINE_MISSING`
Video没有覆盖完整关键时间进程的Storyboard视觉载体
补齐当前SBPKG的有序Sheet/Anchor并重编Manifest
`STORYBOARD_REFERENCE_ADMISSION_FAILED`
Sheet/Anchor的身份、位置、状态、Prop或可读性错误
新建正确Revision；禁止用补图压过错误
`STORYBOARD_REFERENCE_CAPACITY_BLOCKED`
完整Spine无法进入模型容量
去重复KF、改变承载或拆SEG，不删关键因果
`VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN`
Supplemental无独有作用或与Storyboard冲突
删除或限定真正缺口与时间窗
`VIDEO_PROMPT_EXECUTION_DETAIL_INSUFFICIENT`
Prompt只有剧情/镜头标签，没有可执行窗口
补Temporal Window Execution Cards
`VIDEO_PERFORMANCE_CONTRACT_INSUFFICIENT`
只有情绪词，没有行为与反应层次
增加Subtext、Breath、Attention、Latency与Restraint
`VIDEO_ACTION_PHASE_INCOMPLETE`
高风险动作缺准备、路径、接触、反应或结果
展开Action Phase和Completion
`VIDEO_CAMERA_GRAMMAR_INSUFFICIENT`
镜头只有景别/运动，没有叙事功能与切换动机
补Shot Function、Axis、Focus、Reveal与Cut Motivation
`VIDEO_EXECUTION_OVERLOADED`
因果、动作、音频和Camera超过实测能力
按Quality Priority简化或拆SEG
`REFERENCE_MAPPING_BLOCKED`
Image槽位没有完整ID、Who/What、Current State、Controls或Applicable Window
修正Compact Reference Identity Map后再执行

16. 完整生产模板
[text]【MODEL CAPABILITY / COMPLETE OUTPUT】Video ID:Reliability / Evidence:Native Multishot / Audio / Transition Support:Output: one complete fixed-duration video, no external assembly【FULL SEG STORY CANON】{完整施动者、目标、冲突、因果、关键结果与观众知识}【MANDATORY STORYBOARD TEMPORAL SPINE】SBPKG ID:Carrier Mode: ORDERED_CONTINUATION_SHEETS | ORDERED_KF_ANCHORSImage Order / Full IDs / Time Range / KF Range:Admission Result per Image:Temporal Coverage: COMPLETE【EXACT SEG RANGE / BEFORE / NOW / AFTER】{入口、当前30秒任务、出口与Future-State Embargo}【COMPACT REFERENCE IDENTITY MAP】Image N = {完整Revision ID}Who / What + Visible Content:Story Time / Current State:Reference Role:Controls:Does Not Control:Applicable Video Window:Unique Authority Contribution:Admission Status:任一Image缺少完整Revision ID、Who / What + Visible Content、Story Time / Current State、Controls、Does Not Control或Applicable Video Window时返回`REFERENCE_MAPPING_BLOCKED`。【EFFECTIVE REFERENCE SELECTION】Mandatory Storyboard Images:Selected Supplemental Images:Rejected Redundant / Incorrect Images:Reference Capacity Rationale:【REFERENCE DIMENSION COVERAGE MATRIX】Identity:LOOK / Active CT:Spatial / Geometry:Position / Blocking:State / Temporal:Prop / Count / Holder:【GLOBAL CANONICAL INVARIANTS】{人物、LOOK/CT、World XYZ、Zone、Anchor、Support、Route、Barrier/Portal、Orientation、Prop与状态底座}【DRAMATIC ARC / PRIMARY NARRATIVE SUBJECT】{整段权力、知识、情绪或威胁变化；逐窗焦点交接}【TEMPORAL WINDOW EXECUTION CARDS】Window N / Time:Story Purpose:Active State + Position + Prop:Trigger:Action Causality + Phase + Physical Path:Completion Condition:Micro-Performance + Eye-line:Camera + Focus + Cut/Transition Motivation:Dialogue / Vocal Delivery / Lip Sync:SFX / Ambience / Music:State Delta / Next Trigger / Forbidden:【MICRO-PERFORMANCE CONTRACT】{主角逐Beat的Objective、Subtext、Breath、Attention、Hands、Weight、Latency与Restraint/Release}【ACTION PHASE & PHYSICAL RESPONSE】{所有高风险动作的Anticipation至Stable Result}【CINEMATIC CAMERA GRAMMAR】{逐Shot叙事功能、机位、构图、轴线、运动、焦点、Reveal、切换和Transition}【AUDIO-VISUAL SYNCHRONIZATION】{对白、VO/OS、口型、SFX、Ambience、Music和Audio Bridge}【TEMPORAL / PROP / NO REPLAY / FORBIDDEN】{激活、持续、禁入、实例、数量、Holder与已完成动作不得重演}【FINAL STATE / CANONICAL BOUNDARY】{Exit CVS、BNDPLAN、可选BNDANCHOR、下一SEG只继承Canon而非视频尾帧}【QUALITY PRIORITY / FALLBACK】{若过载，明确先简化什么；绝不删什么}
17. 结束前审计
[ ] 每个Video都包含当前SEG完整Mandatory Storyboard Temporal Spine。
[ ] Storyboard以有序Continuation Sheet或同一SBPKG的独立KF Anchor承载，没有绕过Storyboard。
[ ] 每张Storyboard Reference通过Narrative、Identity、LOOK/CT、Spatial、Position、Temporal、Prop与Legibility准入。
[ ] 错误Storyboard已建立新Revision，没有用LOOK/LOC_VIEW或文字压过。
[ ] Supplemental逐张命中独有Authority缺口，数量不是固定值。
[ ] SCSTATE/SLC未与同状态Storyboard同时上传Video。
[ ] 每个Image有完整ID、Who/What、Current State、Role、Controls、Does Not Control、Window、Unique Contribution与Admission Status。
[ ] 六维Coverage完整，人物与场景位置底座未因减图消失。
[ ] Video Prompt包含完整Temporal Window Execution Cards，不只是镜头标签或情绪形容词。
[ ] 关键Beat有可拍Micro-Performance；高风险动作有完整Action Phase与物理结果。
[ ] 每个Shot有Narrative Function、Axis、Focus、Reveal与Cut/Transition Motivation。
[ ] Dialogue、Lip Sync、SFX、Ambience和Music按时间同步。
[ ] 超载时按Quality Priority简化Camera和装饰，不删因果、位置、状态、声音或结果。
[ ] 所有生成视频截图、尾帧与Frame Grab只用于QC，未进入下一SEG Reference。
