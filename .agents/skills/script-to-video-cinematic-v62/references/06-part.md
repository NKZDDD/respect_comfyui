第六部分｜视频执行与声音
目录
Video Authority
Storyboard到Video的变换
Video Reference Manifest
Timeline Execution Window
Temporal State Gating
Temporal Reference Window
Action Causality与物理
Performance与Camera Execution
Model-Native Shot Transition
Dialogue、声音与音乐
模型适配
Video Prompt结构
Story-First、Mandatory Storyboard与有效参考门控
常见失败与修复
1. Video Authority
Video只执行：
Canonical KF之间的合法中间运动。
Performance Motion与微表情。
身体惯性、呼吸、步态、接触和反作用。
衣料、头发、环境、颗粒和自然物理。
已冻结Camera Plan的连续执行。
已冻结声音计划的时间执行。
已批准State Transition的Activation与结果。
已冻结Shot顺序及Model-Native Transition Window。
在一次模型生成中输出包含全部Shots、Transitions与声音连续性的完整SEG成片。
Video不能：
改人物Identity、服装、伤口、道具或Location。
自由想象Storyboard裁切外未定义的人体、服饰、鞋履或空间。
新建关键剧情事实、文字、Holder或空间关系。
重新决定镜头、动作顺序或结局。
把后期状态提前融合。
输出分镜头素材、转场占位或依赖外部剪辑完成成片。
将生成偶然结果提升为Canon。
2. Storyboard到Video的变换
正式关系：
[text]Canonical KF State A↓ Temporal Performance ReconstructionCanonical KF State B
不是：
[text]KF01 pixels → morph → KF02 pixels
Storyboard锁定关键状态、顺序、Camera目标和时间状态；不锁中间每一帧。禁止：
Storyboard Panel Morph。
静态人物平移或缩放。
角色融化变形。
前后KF平均融合。
把整张Sheet网格、边框、标签或排版生成进视频。
把NATIVE_CUT错误解释为两个独立机位之间的连续Camera运动。
把Transition Shield Frame解释成新的Location、CVS或角色状态。
3. Video Reference Manifest
默认先执行[强制Storyboard时间骨架、有效参考选择与导演级Video执行](19-mandatory-storyboard-directorial-video-execution.md)。可靠度影响骨架颗粒度、补充参考数量和提示词冗余度，但不影响Storyboard是否存在。每个SEG先提供覆盖完整关键时间推进的Mandatory Storyboard Temporal Spine，再补有唯一用途的原子Reference。
[text]Image 1..N = 当前SEG按时间排列的Continuation Storyboard Sheets或有序Canonical KF AnchorsImage N+1 = 主角当前完整LOOK/CT（只有故事板不能稳定身份或首次显露时）Image N+2 = 当前Camera Reveal涉及的核心LOC_VIEW（只有新空间覆盖缺口时）Image N+3 = Hero Prop或BNDANCHOR（只有独有细节或边界缺口时）Authority:- Storyboard关键视觉状态、时间推进与因果顺序- 人物与空间组合、Action Phase、Shot目标与Camera意图- Prop SPEC外观、INSTANCE物理绑定、数量与Temporal State- Shot顺序、Transition Mechanism和Transition AnchorDoes Not Control:- 自然中间动作- 呼吸和微表情- 衣料细微物理- 未在Canon中规定的微环境运动
默认不上传SCSTATE，也不重新上传全部Atomic Assets。SCSTATE已经在故事板阶段被消费；同一世界状态同时上传Storyboard与SCSTATE会制造Blocking/Camera双主权。完整选择规则读取[空间状态门控与Authority完整视频参考](14-spatial-state-gating-and-video-reference-minimization.md)。
执行Storyboard Reference Admission Gate与Effective Reference Selection Gate：
[text]Current SEG Storyboard Spine = Mandatory Temporal/Cinematic AuthoritySCSTATE for same state = REMOVELocation/Prop already legible in Storyboard = REMOVECharacter LOOK/CT = ADD ONLY FOR PROVEN IDENTITY OR COVERAGE GAPHero Prop Detail = ADD ONLY FOR PROVEN TEXT/DETAIL GAP
Video必须上传构成完整时间骨架所需的已批准Sheet/Anchor，但不得重复上传相同时刻或跨SEG Sheet。逐秒因果、动作、音频和状态门控在Prompt中必须完整；Supplemental不得控制Camera、Blocking、Time或Action Phase。模型Reference上限不是推荐填满数量；容量不足先去重、换成等价有序KF载体或拆SEG，禁止删除关键因果与结果。
例外：若Camera Reveal Envelope会显露Storyboard未显示的身体/服饰区域，优先回编Canonical Storyboard Sheet/KF，使首显覆盖进入Storyboard。只有Storyboard无法承担且不改变Camera、Blocking、Action Phase或Time时，才按[服饰资产、完整LOOK与首次显露覆盖](12-costume-look-and-visual-coverage.md)补充受影响人物的当前LOOK/CT，并书面说明缺口、首显时间窗、独有Authority Contribution及回编Storyboard仍不足的原因；否则返回VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN。
同一SEG发生Clean LOOK→CT时，优先让有序Storyboard KF与Timeline Gate表达变化。未经模型Reference Time Scope验证，不同时上传Clean全身图与未来CT全身图；否则容易伤情前置或状态互相抵消。
每次执行Manifest写：
[text]video_targetreference_countimage_numberreference_idwho_or_what_and_visible_contentstory_time_and_current_stateauthority_typemust_preservemust_transformmust_not_copydoes_not_controlapplicable_time_windowupload_order
4. Timeline Execution Window
第16章把Storyboard Temporal Position解析为绝对秒数。每个窗口写：
[text]WINDOW IDTIME RANGEENTRY KF / ENTRY CVSENTRY ACTIVE STATE SETSHOT / CAMERASOURCE SPATIAL REVISION / LOC_VIEW OR GEO_PROXYCAMERA PATH IN WORLD COORDINATESCAMERA REVEAL ENVELOPEVISUAL COVERAGE STATUSACTIVE SHOT IDTRANSITION ID / ROLE / MECHANISMTRANSITION SHIELD / SWITCH POINTCHARACTER INTENTACTION CAUSALITYFIRST CONTACTSTATE ACTIVATION EVENTALLOWED STATEFORBIDDEN FUTURE STATETARGET KF / TARGET CVSEXIT CONDITIONPROP INSTANCE ENTRY / EXIT REGISTEROBJECT COUNT LOCK / COUNT-CHANGING EVENTSOUND CUE
示例：
[text]0.0–8.0sEntry State: LOOK01，无伤、无贴片Action: 女主与对方争执并后退Allowed: 原始完整造型Forbidden: CT01伤口、CT02贴片、后续血迹Exit: 攻击动作即将发生8.0–15.0sEntry: LOOK01Activation Event: 10.0s玻璃划过左额Before 10.0s: 脸部完整After 10.0s: CT01伤口首次出现并持续Forbidden: CT02贴片Exit: 伤口已成立
5. Temporal State Gating
每个状态必须有：
[text]Activation EventActivation TimeAllowed WindowForbidden Prior WindowPersistenceDeactivation / Replacement
State Timeline Lock
在Video Prompt中逐时间段写唯一合法人物/Prop/Location/VFX状态。不要只写“保持时间一致”。
Future-State Embargo
未到Activation Time时，禁止未来状态以任何形式出现，包括淡淡白色贴片、模糊伤口、提前湿衣、已裂纹瓶子、预先焦黑墙面或尚未发动的能量光。
Past-State Persistence
状态成立后必须持续，直至合法Replacement。例如脸伤成立后，后续镜头不能恢复；治疗贴片出现后不能在下一镜头消失。
No Action Replay
进入Post-action后不得重演Activation Event。Video不得为了连接KF再次拔针、再次撕文件或再次跌倒。
6. Temporal Reference Window
Canonical Storyboard Package保持唯一，但Execution Input可以按模型弱点生成时间窗口：
[text]SBPKG Canonical Truth↓ Production AdapterTemporal Reference Window A: KF01-KF03Temporal Reference Window B: KF03-KF05
规则：
Window是衍生执行参考，不是新Canon。
只裁取/重排已有KF，不重画、不改内容、不改顺序。
当前Window不提供尚未激活的未来视觉状态。
相邻Window共享边界KF或Entry/Exit State，保持连续。
MODEL_NATIVE_ONLY时，Window只用于同一次完整生成中的逻辑/Reference Time Scope，不能拆成多个视频调用。
不得因为模型支持分段执行就分别生成后外部拼接；能力不足时改用更安全原生Transition、单镜头连续表达或阻断。
不给模型看到未来状态通常比看到后用文字禁止更稳定，但这种适配不能改变Canon。
7. Action Causality与物理
每个动作写成：
[text]intentpreparationinitiationtrajectoryfirst_contactforce / resistancereactioncompletionresulting_state
避免动作清单式并列。明确谁发起、作用于什么、如何接触、结果属于谁。
同步Delta
一个动作引起多个结果时，在同一Activation Event同步执行人物、Prop、Holder、Spatial和VFX变化。
物理可见结果
关键结果必须与终点KF一致。Video可生成自然碎片轨迹，但不能改变Canonical破坏范围、伤口位置、谁拿到道具或门是否打开。
接触与手部
明确手占用、抓握位置、接触对象、方向和接触后Holder。禁止物体穿手、瞬移、复制或在无交接动作时换Holder。
Instance-Bound Action与数量守恒
同款道具完整规则读取[PROP规格、物理实例与数量连续性](08-prop-spec-and-physical-instance.md)。每个动作目标必须使用具体PROP_INSTANCE ID；PROP_SPEC只能决定共同外观，不能作为被拿取、打碎或交接的物理对象。
每个Window冻结Entry/Exit Instance Register：实例状态、Holder/Container、Anchor、Visibility与存在状态。遮挡、离画或装入容器期间仍保留实例；重新出现时恢复同一ID和所有Active State。
执行：
[text]ACTIVE_TOTAL = VISIBLE_FULL + VISIBLE_PARTIAL + OCCLUDED + OFF_FRAME
没有Creation、Entry/Exit、Destruction、Consumption、Split、Merge或Transformation事件时，Active Total不得变化。从PROP_SET物化实例只改变追踪方式，不能让画面凭空多出一件。
8. Performance与Camera Execution
Performance
按窗口描述：
[text]subtextattentionbreathbody tensiongesture economyfacial changereaction latencyspeech rhythmemotional result
表演由意图推动，避免持续夸张表情、无意义点头、随机挥手和每句对白都大动作。
Camera
执行已冻结Shot：
明确起始机位、运动方向、速度、终点构图和停稳条件。
不用Camera运动掩盖人物漂移。
保持轴线、视线和Physical Direction。
只在叙事需要时使用推、拉、摇、移、跟、升降或手持。
切镜时保持Entry/Exit动作和状态连续。
Camera Path使用同一Spatial World坐标，不能越出已批准Location View/Geometry Proxy覆盖。
Camera只投影人物和道具World Placement，不能为了构图让实体静默换Zone或镜像。
人物Position State没有Authorized Movement Event时，Zone、Anchor、Support Binding与Barrier Side保持不变。
First Reveal Coverage Gate
逐Window预测最大拉远、环绕、人物转身/起身、肢体伸展、背面与鞋履显露。结果为：
[text]COVEREDSUPPLEMENTAL_REFERENCE_REQUIREDCAMERA_CONSTRAINEDPRODUCTION_BLOCKED
SUPPLEMENTAL_REFERENCE_REQUIRED时加入当前完整LOOK/CT视图；CAMERA_CONSTRAINED时把运动限制在已定义裁切内；剧情要求必须显露但覆盖不存在时阻断生产。Coverage通过前执行Framing Expansion Embargo。
9. Model-Native Shot Transition
完整规则读取[视频模型原生镜头切换](13-model-native-shot-transition.md)。每个Video Target固定：
[text]transition_execution_mode = MODEL_NATIVE_ONLYexternal_transition_editing = FORBIDDENexternal_shot_assembly = FORBIDDEN
Transition Timeline
在Shot Window之间插入真实占时的Transition Window：
[text]FROM SHOT / EXIT ACTION↓TRANSITION TRIGGER↓SHIELD / PEAK MOTION / PEAK LIGHT↓ STATE SWITCH POINTTARGET SHOT / ENTRY ESTABLISHMENT
NATIVE_CUT在cut_at瞬时切换，不生成连续Camera插值。遮挡/甩镜/光学Transition在完全Shield或批准峰值后切换；解除后只允许Target State。
Model-Native Complete Output
模型一次返回一条完整SEG，不返回多个镜头文件、候选片段、剪辑点占位或后期建议。Transition失败时重新生成或降级为更安全的模型内切换；不得外部拼接、补黑帧、补叠化或裁掉失败帧。
Transition与时间状态
Transition视觉重叠不等于Canonical State共存。From-only Window受Future-State Embargo；Target-only Window受Past-State Persistence。Shield Frame默认没有World Truth Authority，不能成为第三套混合状态。
10. Dialogue、声音与音乐
Dialogue Authority
对白文本、说话者、信息、姓名、金额、地名和关系只服从Story Canon。翻译只能改变语言表达，不得顺手本地化剧情事实，除非用户授权Adaptation。
Dialogue Timing
写：
[text]speakerlinelanguagestart/enddeliverysubtextpauseoverlaplip-sync priorityoff-screen / on-screen
避免机械加速。对白过长时调整Shot/SEG包装或精炼授权范围内的表达，不让人物异常快说。
Sound Design
为每个Scene/SEG建立：
[text]room tone / ambienceforeground SFXaction contact SFXoff-screen cuedialogue perspectivemusic entry/exitsilence beatsound bridge
声音必须服务信息、空间和情绪。不要用持续大音乐覆盖关键对白或用夸张音效替代不清晰动作。
音频模式
native_audio：Video Prompt包含对白、SFX、环境和音乐时间。
silent_video：明确禁止口型对白和随机音频，仅输出视觉执行。
separate_audio：输出独立Audio Cue Sheet，Video只执行需口型/节奏配合的视觉标记。
项目要求完全无需额外剪辑且交付含声音成片时，优先native_audio。J-Cut、L-Cut、Sound Match、Sound Drop和Ambience Bridge必须在同一次生成中按时间执行。
11. 模型适配
只适配生产表达：
支持的单条时长。
参考图数量与尺寸。
Image编号语法。
是否支持首尾帧、多个参考、原生音频或镜头切换。
原生多镜头可靠度、时间码精度、完全遮挡切换、Reference Time Scope和音频Transition能力。
对Prompt长度、负面词和画幅的限制。
不得适配Canon内容：
不生成不同剧情版本的Storyboard。
不因模型更喜欢特写而改Blocking/空间。
不因参考上限删除关键Identity或Temporal State。
Canonical KF内容唯一；Grid Arrangement、边距、标签、裁取和Window可由Production Adapter调整。
当native_multishot_support = LIMITED/UNKNOWN时优先Full Occlusion、Dip、Flash、Defocus或低复杂度Motion Bridge；UNSUPPORTED时改为同一生成中的单镜头连续表达或MODEL_NATIVE_TRANSITION_BLOCKED。不得静默切换外部剪辑。
12. Video Prompt结构
固定按Story-First顺序包含：
FULL 30-SECOND STORY CANON / VIDEO ID。
EXACT SEG MOMENT AND RANGE。
BEFORE / NOW / AFTER。
PRIMARY NARRATIVE SUBJECT。
MANDATORY STORYBOARD TEMPORAL SPINE MAP与REFERENCE INPUT MANIFEST。
STORYBOARD REFERENCE ADMISSION结果、COMPACT REFERENCE IDENTITY MAP与REFERENCE ROLE MAP。
EFFECTIVE REFERENCE SELECTION、六维Coverage与去重记录。
CANONICAL START STATE与GLOBAL EXECUTION INVARIANTS。
FULL SEG DRAMATIC ARC与TEMPORAL WINDOW EXECUTION CARDS。
MICRO-PERFORMANCE、ACTION PHASE & PHYSICAL RESPONSE。
CINEMATIC CAMERA GRAMMAR、CAMERA REVEAL ENVELOPE与FIRST REVEAL COVERAGE。
DIALOGUE、AUDIO-VISUAL SYNCHRONIZATION与MANDATORY SOUND。
SHOT TIMELINE、MODEL-NATIVE TRANSITION WINDOWS与NO SHOT MORPH。
STATE ACTIVATION、TEMPORAL LOCK、PROP COUNT与NO ACTION REPLAY。
FINAL STATE、BNDPLAN、FORBIDDEN、QUALITY PRIORITY与OUTPUT FORMAT。
Prompt必须说明：
Storyboard是关键状态Authority，不是逐像素Morph目标。
每个Image槽位用完整ID与自然语言明确Who/What、可见内容、Story Time/Current State、Controls、Does Not Control和Applicable Time Window；映射缺失或错序时输出REFERENCE_MAPPING_BLOCKED。
每个时间窗口唯一合法状态。
哪个事件激活哪个Delta。
终点状态和不可改变结果。
自然运动自由度和禁止重新设计范围。
每个Transition的完整ID、Mechanism、时间、Shield/Switch/Entry及模型内完成要求。
返回结果已经是完整多镜头成片，不依赖任何外部编辑。
13. Story-First、Mandatory Storyboard与有效参考门控
执行[Story-First、Zone-Coherent SCSTATE与故事板可读性门控](17-story-first-zone-coherent-scstate-and-storyboard-readability.md)。Video不能假定模型能够仅凭Sheet标签理解剧情；必须重新写完整SEG剧情摘要，并把每个时间窗写成“施动者→动作→受动者→物理结果→反应→下一触发”的逐秒因果。
先完成Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal与Prop/Count/Holder六维Coverage Matrix，再锁定当前SEG的Mandatory Storyboard Temporal Spine。每张Storyboard参考先通过SBPKG Revision、SEG、Reality Thread、时间范围、Source State、人物LOOK/CT、World Position、Prop状态、边界和排序Admission。任何生成视频截图、尾帧或Frame Grab均禁止进入Reference Manifest。每张Image明确：
[text]Exact Anchor / Sheet / BNDANCHOR Revision IDReference RoleSEG / applicable time rangecontained KF IDs（如适用）visible story momentcontrols / does not controlapplicable video window
Storyboard骨架之外，不得同时上传表达同一状态的SCSTATE/SLC、人物LOOK、Location PR或重复Anchor。补充原子图必须证明独有Identity、Coverage、Geometry、Prop、State Result或Boundary缺口；无独有用途返回VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN，冲突返回VIDEO_REFERENCE_AUTHORITY_CONFLICT，缺维返回REFERENCE_DIMENSION_COVERAGE_GAP。骨架缺失、Admission失败或容量无法承载时分别返回VIDEO_STORYBOARD_SPINE_MISSING、STORYBOARD_REFERENCE_ADMISSION_FAILED或STORYBOARD_REFERENCE_CAPACITY_BLOCKED。完整SEG故事或逐秒因果缺失时返回VIDEO_STORY_CONTEXT_INSUFFICIENT。
Video production_prompt采用导演级逐窗口执行卡。每个窗口至少写：Beat目的、人物目标与阻力、精确动作阶段、眼神/呼吸/肌肉张力/反应延迟、身体重心与接触物理、Camera景别/角度/运动/焦点、对白与声音同步、状态门控和窗口出口。缺失时分别返回VIDEO_PROMPT_EXECUTION_DETAIL_INSUFFICIENT、VIDEO_PERFORMANCE_CONTRACT_INSUFFICIENT、VIDEO_ACTION_PHASE_INCOMPLETE或VIDEO_CAMERA_GRAMMAR_INSUFFICIENT。
相邻SEG只读取在两条视频生产前由上游Canon编译的BNDPLAN与可选BNDANCHOR OUT/IN。动作、对白、状态激活和原生Transition必须在单一SEG内完成；视频尾帧只用于QC和是否重生成的判断。
14. 常见失败与修复
失败
根因
修复
第一帧已有后期贴片
整板未来状态融合
Timeline Gate + Temporal Window
Video缺少Storyboard，只上传入口/LOOK/SCSTATE
缺失时间、因果和镜头骨架
补齐Mandatory Storyboard Temporal Spine
Video同时上传Storyboard与同状态SCSTATE
两个Composite Authority的Blocking/Camera冲突
保留Storyboard骨架，删除重复SCSTATE
Storyboard版本、时段或位置不匹配
未执行Admission Gate
停止并换成当前SBPKG合法Sheet/Anchor
Video同时重复上传人物、Location与Prop
原子资产与Storyboard争夺Composite Authority
默认删除；仅保留已证明首显缺口的单一补图
Prompt只有Shot/KF标签没有完整剧情
假定模型会自行理解故事
重写完整SEG摘要与逐秒施受因果
参考图接近模型上限
重复上传SCSTATE、重复KF与原子资产
保留完整Storyboard骨架和独有Supplemental；去重、换载体或拆SEG
Prompt动作笼统、表演僵硬
只有剧情摘要没有导演级执行卡
补动作Phase、微表演、物理反应、Camera Grammar与声画同步
为了少图删掉LOOK或LOC_VIEW
把少Reference误解为少Authority
六维Coverage Gate；恢复当前LOOK/CT或相关LOC_VIEW
上一视频尾帧作为下一SEG Image 1
生成误差回流并与Canonical入口冲突
`GENERATED_FRAME_REFERENCE_FORBIDDEN`；使用预编译BNDPLAN/BNDANCHOR
拼接点重复动作或姿态跳跃
动作/对白/状态激活跨SEG
回编到完成Beat；使用Canonical Cut Pair或Motivated Hard Cut
Clean LOOK与未来CT同时上传
全局参考融合造成伤情前置或被抹平
优先Storyboard时间带；未经验证不并列上传两套全身状态
Image 1有控制规则但模型不知道是谁
Video Prompt缺主体/状态语义映射
Compact Reference Identity Map + Mapping Gate
伤口出现后消失
未展开Active State
每Window重复Persistence合同
人物像幻灯片移动
把KF当像素Morph
Temporal Performance Reconstruction
同一动作做两次
KF Phase和Prompt重复
Completion后No Replay
Prop瞬移换手
Holder/Hand/交接未写
Action Causality + Prop Contract
同款道具状态串到另一件
动作只绑定SPEC
每个动作绑定INSTANCE ID
遮挡后多一件/少一件
无Entry/Exit数量登记
Instance Register + Object Count Lock
销毁后完整道具重现
只写视觉破坏未写存在状态
Transformation/Destruction Event + Exit Reconciliation
场景结构漂移
Camera重写World
Geometry Lock与Shot Execution分离
环绕后房间结构变化
Camera越出批准空间覆盖
同一Geometry Proxy Camera Path；未覆盖则新建View
切镜后人物空间位置变化
使用Screen Position当World Position
World XYZ/Anchor Offset固定，逐镜投影
半身故事板生成全身后服装漂移
首次显露覆盖不足
优先回编Storyboard；仍不足才用书面例外补当前LOOK/CT
补全身图后Pose或Camera被重置
LOOK与Storyboard权威冲突
Storyboard管时空；LOOK/CT只管视觉覆盖
模型随机露出未定义鞋履/背面
无Framing Expansion Embargo
限制Camera或先补Coverage
模型只输出一个长镜头
未声明Shot/Transition Timeline
Model-Native Complete Output + 精确Window
两个机位被动画连接
NATIVE_CUT被当Camera Move
exact cut_at + NO SHOT MORPH
人物/场景在转场中融合
没有Shielded State Switch
100% Shield后切换，Target-only Entry
模型输出多个镜头素材
Task暗示后期组装
单条完整SEG输出，禁止候选片段
转场失败后依赖后期补救
执行模式未锁
原生降级/重新生成/BLOCKED
转场视觉重叠导致未来状态前置
把Overlap当Canon共存
From-only/Target-only Gate
表演过度
只有情绪形容词
写Subtext、Breath、Restraint和Reaction
对白太快
固定时长硬塞文本
调整授权内文本或SEG边界
未来状态淡淡预现
只禁完整状态
禁完整/部分/弱化/模糊/融合形式
视频创造关键文字
Storyboard未冻结Prop内容
文字进入PROP/KF，Video只执行显现
