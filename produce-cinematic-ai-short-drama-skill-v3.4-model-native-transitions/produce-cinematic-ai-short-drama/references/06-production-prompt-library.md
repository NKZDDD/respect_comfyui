# 完整提示词与交付模板

## 目录

1. Prompt Compiler总规则
2. 单次生成调用交付格式
3. 原子资产模板路由
4. SCSTATE完整模板
5. Canonical Storyboard完整模板
6. Video完整模板
7. Episode生产包格式

## 1. Prompt Compiler总规则

执行实际任务时，把所有花括号字段解析为具体内容。资料不足时明确写`UNRESOLVED`或`OPEN DESIGN DEGREE REQUIRED`，不得把空占位符交给生成模型。

每段最终Prompt必须：

- 是一段完整、独立、可复制的生产指令。
- 明确目标ID、任务、Canon来源、参考图、必须保留、必须改变、禁止复制、不控制范围和输出格式。
- 展开关键CT、Prop Instance、Object Count和Spatial状态，不只写内部ID。
- Location任务展开Spatial坐标、Geometry Proxy、Camera Rig和View覆盖；人物视频任务展开当前LOOK/CT Coverage与Camera Reveal Envelope。
- 多镜头Video展开完整Shot Timeline、Model-Native Transition Contract、Shield/Switch Point与一次生成成片要求；不得把转场留给外部剪辑。
- 使用当前调用真实Image编号，并与Manifest完全一致。
- 所有`{..._ID}`字段在最终交付时解析为Registry中的完整Canonical Revision ID；不得只填`CT01`、`LOOK01`、`KF03`或显示名称。
- 先通过[Canonical ID注册表与参考资产解析](10-canonical-id-registry-and-resolution.md)的Exact Resolution Gate，再释放Prompt。
- 用正向任务、明确Authority和必要Forbidden组合，不堆砌互相矛盾的负面词。
- 不用“同上”“参考前文”“保持一致”等弱表达代替具体合同。

## 2. 单次生成调用交付格式

每项NEW资产、Storyboard或Video先输出：

```text
【生产目标】
Display Name: {human_readable_name}
Asset Family ID: {exact_family_id}
Target Canonical Revision ID: {exact_target_revision_id}
Target Type: {type}
Production Status: NEW
Story Scope: {episode/scene/story_time}

【REGISTRY SNAPSHOT】
Project ID: {exact_project_id}
Registry Snapshot ID: {exact_snapshot_id}
ID Policy: FQID_CANONICAL_REVISION_REQUIRED

【依赖关系】
Canonical Source Revision IDs: {full_source_revision_ids}
Parent Canonical Revision ID: {full_parent_revision_id_or_none}
Required Visual Delta: {visible_difference}

【REFERENCE INPUT MANIFEST】
Reference Count: {N}

Image 1
Exact Canonical Revision ID: {full_reference_revision_id}
Exact Canonical Filename: {filename}
File Role: {PRIMARY/DETAIL/MASK/SOURCE}
Canonical Relative Path: {path}
Resolved Local Path / Asset URI: {path_or_uri}
SHA-256 Fingerprint: {hash}
Availability: VERIFIED
Asset Identity: {what it is}
Authority Type: {authority}
MUST PRESERVE: {list}
MUST TRANSFORM: {list}
MUST NOT COPY: {list}
DOES NOT CONTROL: {list}
Applicable Scope: {range}

Image 2
...

【上传顺序】
Image 1 → Image 2 → ...

【ID ECHO AUDIT】
Target / Parent / Reference exact match: PASS
Manifest ↔ Prompt Image map: PASS
Filename ↔ Revision ID prefix: PASS
Unresolved / abbreviated IDs: 0

【ONE COMPLETE production_prompt】
"""
{resolved prompt}
"""
```

无Reference时写：

```text
Reference Count: 0
Reference: NONE
Reason: 本资产为首次Canonical Root生成。
```

若Reference Count大于0而任一ID、状态、文件、路径、Fingerprint或Authority未解析，输出`REFERENCE_RESOLUTION_BLOCKED`和错误码，不输出生产Prompt。

## 3. 原子资产模板路由

角色、阶段、服装、LOOK、Character CT、Location、Spatial、PR、unique PROP、VEH、CRE、GRP与VFX的完整模板读取[原子资产完整提示词模板](09-atomic-asset-prompt-templates.md)。Location多视角和World Placement同时读取[空间坐标、机位Rig与多视角一致性](11-spatial-rig-and-multiview-consistency.md)；服饰物化决策、完整LOOK和裁切外显露同时读取[服饰资产、完整LOOK与首次显露覆盖](12-costume-look-and-visual-coverage.md)。

出现重复同款道具、背景库存、实例交接/损坏/消耗、遮挡重现或Object Count问题时，不使用unique PROP模板，改读[PROP规格、物理实例与数量连续性](08-prop-spec-and-physical-instance.md)。

Storyboard/Video包含镜头切换、遮挡、甩镜、闪光、失焦、Dissolve、声音桥或多Scene切换时，读取[视频模型原生镜头切换](13-model-native-shot-transition.md)。

## 4. SCSTATE完整模板

Manifest按当前调用列出所有人物CT/LOOK、Location PR、Hero Prop SPEC/INSTANCE及必要组件。

```text
【TASK】

创建{SCSTATE_ID} Scene State Composite Asset。根据{SOURCE_CVS_ID}，把当前Story Time已经合法成立的人物、Location、Prop Instance、持续状态与Frozen Blocking重新构建为一张稳定完整的世界状态母图。

`{SCSTATE_ID}`、`{SOURCE_CVS_ID}`及下列全部资产字段必须替换为完整Canonical Revision ID，并与Registry Snapshot逐字符一致。

本图不是Storyboard、动作过程图或最终电影镜头；不得新增或修改Canonical State。

【STORY TIME & THREAD】

Scene：{scene_id}
Story Time Meaning：{事件前后边界}
Reality Thread：{thread}
State Meaning：{一句话完整状态}

【SOURCE CVS】

CVS：{cvs_id}
只能视觉物化该CVS；若Reference与CVS冲突，以CVS为准并重建Reference组合。

【REFERENCE ROLE MAP】

{逐Image写Authority Type、MUST PRESERVE、MUST TRANSFORM、MUST NOT COPY、DOES NOT CONTROL、Applicable Scope}

【REFERENCE FIREWALL】

每张Reference只控制分配维度。人物资产背景/Pose/Camera不得进入Blocking；Location示例人物不得出现；PROP_SPEC只控制共同外观，不能改变INSTANCE Holder、位置或状态；任何单一图不得决定整体Composition。

【CHARACTER STATE CONTRACT】

{逐人物：Active Visual Root、Identity、Current LOOK/CT、Zone/Anchor、Stable Pose、Orientation、Gaze、Hand Occupancy、Active State、Must Visible、Partial、Occluded/Off-frame、Not Yet Active、Prop Instance Binding}

【PROP INSTANCE STATE CONTRACT】

{逐实例：INSTANCE ID、SPEC + Revision、Current State、Existence、Holder、Hand、Owner、Container、Zone/Anchor、Orientation、Physical Relation、Visibility Bucket、Forbidden Future State}

【OBJECT COUNT LOCK】

Active Instance Total：{count}
Visible Full：{IDs}
Visible Partial：{IDs}
Occluded：{IDs}
Off-frame：{IDs}
PROP_SET Available Count：{set/count或NONE}
Count-changing Event：{event或NONE}
Reconciliation：Full + Partial + Occluded + Off-frame = Active Total。

【LOCATION & SPATIAL CONTRACT】

Location：{PR_ID}
Spatial Revision：{ID}
Geometry Proxy / Location View：{完整ID}
Coordinate Origin / Axis / Unit：{信息}
Current Zone：{信息}
Fixed Landmarks：{信息}
Character / Prop Anchors：{信息}
Entity World Root/Foot/Pivot XYZ + Anchor Offset：{信息}
Orientation / Support / Footprint：{信息}
Relative Position：{信息}
Routes / Temporary Obstacles：{信息}
Forbidden Spatial Changes：不得镜像、移动固定结构或改变实体真实Zone。

【RELATIONAL BLOCKING】

{逐关系写距离、高度、Facing、Contact、Eye Line、Movement Coupling和Occlusion Priority}

【PRESENCE / VISIBILITY】

ACTIVE & MUST BE VISIBLE：{列表}
ACTIVE & PARTIALLY VISIBLE：{列表}
ACTIVE BUT OCCLUDED / OFF-FRAME：{列表}
NOT YET ACTIVE / FORBIDDEN：{列表}

【TEMPORAL LOCK】

只表达一个明确Story Time。所有未来人物状态、Prop破损、Holder变化、Location损坏、VFX和Blocking结果不得提前出现；所有已激活持续状态不得无事件消失。

【MUST PRESERVE STATE LIST】

{人物、服装、CT、Prop SPEC/INSTANCE、Holder、Location、Landmark逐项列出}

【CAMERA / PRESENTATION】

使用中性稳定中全景或全景，以记录Identity、当前CT、Stable Blocking、人物关系、Hero Prop和Geometry为第一目标。Camera不得改变World。

【FORBIDDEN】

不得多格、时间拼贴、重复人物、额外Prop Instance、动作半程、极端镜头、运动模糊、未来状态、Clean State恢复、错误Holder、空间镜像或新设计。

【OUTPUT】

输出一张单幅{aspect_ratio}的{SCSTATE_ID} Canonical Stable World State图。
```

## 5. Canonical Storyboard完整模板

```text
【TASK】

创建{SBPKG_ID}的{SHEET_ID}，包含有序KF{range}。根据指定SCSTATE/CVS、Shot与Action Phase，用新的Camera Observation把唯一Canonical World转译为可供视频执行的Storyboard。

【REFERENCE INPUT MANIFEST / ROLE MAP】

{逐Image写Reference ID、Story Time Meaning、Authority、Preserve/Transform/Not Copy/Does Not Control、Applicable KF}

【REFERENCE FIREWALL】

每张SCSTATE只控制被分配的KF。不得把未来CT、伤口、泥污、Pose、Blocking、Prop State、Location或人物位置反向应用到较早KF；不得把多个状态平均融合。Location和Thread同样按KF隔离。

【CANONICAL WORLD RULES】

不得重新设计人物、PH、LOOK、CT、Location、Geometry、PROP SPEC或Stable Blocking。Active Character Visual Root按CT > LOOK > PH > CHAR解析。Previous Exit必须成为Next Entry。

【CANONICAL ID LOCK】

Target、Source SCSTATE/CVS/VT、KF、人物CT、Location PR、Prop SPEC/INSTANCE和所有Reference都使用完整Canonical Revision ID。禁止简称、别名、“上一张图”、漏项目命名空间或漏Revision。

【CAMERA AUTHORITY】

SCSTATE Lock不等于Shot Lock。为每个KF创建新的景别、机位、角度、构图、深度和焦点，但不得移动World或实体Physical Zone。

【SPATIAL / VIEW / WORLD PLACEMENT LOCK】

每个KF写完整Spatial Revision、LOC_VIEW或GEO_PROXY ID、Camera XYZ/Look-at、View Coverage Status，以及人物/Prop World XYZ、Anchor Offset和Orientation。所有视角必须来自同一Geometry Proxy；Camera只投影，不得静默移动门窗、家具、人物或道具。

【CAMERA REVEAL ENVELOPE / VISUAL COVERAGE】

{逐KF/Video Window预估最大拉远、环绕、转身、起身、四肢与鞋履显露；列出Required Body/Costume Regions、当前LOOK/CT Coverage Source和状态COVERED/SUPPLEMENTAL_REFERENCE_REQUIRED/CAMERA_CONSTRAINED}

【KEYFRAME EXECUTION】

KF数量：{dynamic_count}

{逐KF完整写：KF_ID、Source State、Thread、Temporal Position、Shot、Spatial/View、Camera Rig、World Placement、Focus、Stable Blocking Source、Action Phase、Performance、Camera Reveal Envelope、Required Visual Coverage、Visible/Occluded Active State、Prop INSTANCE/SPEC/State/Holder/Container/Anchor/Visibility、Object Count、Forbidden Future State、Entry/Exit}

【PROP INSTANCE & OBJECT COUNT LOCK】

每个动作对象绑定具体INSTANCE ID。SPEC只控制共同外观。每格对账Full、Partial、Occluded、Off-frame与Active Total；没有合法Count-changing Event不得增减物体。

【ACTION / EDIT TRANSITION】

动作阶段单向推进。ACTION COMPLETION之后只能进入POST-ACTION、REACTION或STABLE EXIT STATE；不得重演动作。明确相邻KF的切换或连续运动关系。

【MODEL-NATIVE TRANSITION CONTRACTS】

执行模式：MODEL_NATIVE_ONLY；External Transition Editing / Shot Assembly：FORBIDDEN。

{逐Transition写完整Revision ID、From/To Shot、Mechanism、Cinematic Grammar、Narrative Function、Temporal Position、Exit/Trigger/Shield或Peak/Switch/Entry、From/Target State、World Truth Authority、Forbidden Mixing}

NATIVE_CUT只使用瞬时边界，不插值两个机位。Shield/Peak Anchor不是SCSTATE或新世界状态。

【CONTINUITY & TEMPORAL LOCK】

未激活状态不得出现；已激活持续状态必须继承。画外、遮挡或装入容器不等于失活。关键结果必须在终点KF明确。

【OUTPUT FORMAT】

输出{layout}的单张Storyboard Sheet，清晰标注KF_ID并按阅读顺序排列。只包含指定KF，不增加重复格、未来状态、额外人物/物件、时间拼贴、Reference Sheet排版或水印。
```

## 6. Video完整模板

```text
【TASK】

生成{VIDEO_ID}，时长{duration}，画幅{aspect_ratio}。以{SBPKG_ID}为Primary Composite Visual Authority，在一次视频模型生成中直接输出包含全部有序Shot、模型原生镜头切换、动作、表演、Camera和声音连续性的完整SEG成片。

Storyboard不是逐像素Morph目标；不得生成网格、边框、标签或Panel过渡。

禁止分别输出镜头素材后拼接；禁止依赖外部剪辑补切镜、遮挡、黑帧、甩镜、叠化、声音桥或修剪失败帧。

【REFERENCE ROLE MAP】

{逐Image写Authority、MUST PRESERVE、MUST TRANSFORM、MUST NOT COPY、DOES NOT CONTROL、Applicable Time Window}

【CANONICAL START STATE】

{0秒时人物Identity/CT、Location、Prop INSTANCE/SPEC/State/Holder/Container/Object Count、Blocking、Camera和Forbidden Future State}

【CANONICAL ID LOCK】

VIDEO、SBPKG、Entry/Target KF、人物CT、Location、Prop Instance和补充Reference都使用Registry中的完整Canonical Revision ID。Image N仅是本次调用槽位，不能替代ID。

【TIMELINE EXECUTION】

{逐Window写绝对时间、Entry State、Intent、Action Causality、Camera、Activation Event、Allowed State、Forbidden Future State、Target State、Instance Entry/Exit Register、Object Count、Sound Cue}

【MODEL-NATIVE COMPLETE OUTPUT】

Execution Mode：MODEL_NATIVE_ONLY
External Transition Editing：FORBIDDEN
External Shot Assembly：FORBIDDEN
Native Multishot Support：{RELIABLE/LIMITED/UNSUPPORTED/UNKNOWN}

本次只返回一条完整{duration}成片；全部Shot和Transition必须直接存在于这条输出视频中。不得返回多个素材、候选段落、转场占位或后期说明。

【SHOT TIMELINE】

{逐Shot写完整Shot ID、时间范围、Source/Target KF/CVS、Active State、Camera、Action/Performance、Audio、Entry与Exit Condition}

【MODEL-NATIVE TRANSITION WINDOWS】

{逐Transition写完整TRANSITION ID、时间、From/To Shot、Mechanism、Cinematic Grammar、Narrative Function、Exit Composition/Action、Trigger、Shield/Peak、Switch Point、Entry Composition/Action、Motion Vector、Audio Bridge、Completion与Failure Signature}

【SHIELDED STATE SWITCH / NO SHOT MORPH】

NATIVE_CUT在指定cut_at瞬时切换；禁止在两个独立机位之间生成连续Camera运动或Morph。Shielded Transition在100%遮挡/批准峰值前只允许From State，Switch Point后只允许Target State。Transition Shield默认没有World Truth Authority，不得产生混合人物、混合服饰、混合Prop或混合Location。

【ACTION CAUSALITY】

所有动作按意图、准备、启动、轨迹、First Contact、受力/阻力、反应、完成和结果执行。动作Target必须是具体INSTANCE。Prop不得瞬移、复制、融合、穿手或无交接换Holder。

【PROP INSTANCE & OBJECT COUNT LOCK】

SPEC只控制共同外观；INSTANCE控制唯一物理身份。遮挡、离画、进入容器期间继续维护实例。除Creation、Entry/Exit、Destruction、Consumption、Split、Merge或Transformation事件外，Active Total保持不变。

【PERFORMANCE】

{Subtext、Attention、Breath、Body Tension、Gesture、Facial Change、Reaction Latency、Speech Rhythm}

【CAMERA EXECUTION】

{逐Shot写Spatial Revision、LOC_VIEW/GEO_PROXY、World坐标起点、Look-at、运动路径、速度、终点构图、切点与停稳条件}。Camera不得改变Geometry或实体真实位置，不得越出批准空间覆盖。

【CAMERA REVEAL ENVELOPE】

Initial Crop：{信息}
Maximum Pullback / Orbit：{信息}
Character Turn / Posture / Limb Reveal：{信息}
Required Body / Costume / CT Regions：{信息}

【VISUAL COVERAGE AUTHORITY / FIRST REVEAL LOCK】

Current Visual Root：{完整LOOK或CT Revision ID}
Coverage Source Images：{Image编号与完整ID}
Defined Regions：{信息}
Coverage Status：{COVERED/SUPPLEMENTAL_REFERENCE_REQUIRED/CAMERA_CONSTRAINED}
Authority Priority：Storyboard控制Camera、Pose、Blocking、Action与Time；当前LOOK/CT只控制Identity、身体比例、当前服饰、鞋履和首次显露区域。

当下装、背面、手脚或其他区域第一次出现时，只能复现批准Coverage。未定义区域不得显露；Coverage Gate通过前执行Framing Expansion Embargo。

【DIALOGUE / SOUND】

模式：{native_audio/silent/separate_audio}
{对白文本、说话者、时间、表演、环境、SFX、音乐和Silence Beat}

使用native_audio时，J-Cut、L-Cut、Sound Match、Sound Drop和Ambience Bridge由同一次生成完成，不留给后期。

【STATE ACTIVATION & TEMPORAL LOCK】

每个状态只在指定Activation Event后出现。未来状态在此前不得以完整、部分、弱化、模糊、预示或融合形式出现；已激活状态持续到合法替换。

【NO ACTION REPLAY】

已完成的签字、跌倒、拔针、撕毁、撞击或其他Activation Event不得再次发生。

【FINAL STATE】

{SEG结束时完整人物、Prop Instance Register、Object Count、Location、Holder/Container、Blocking和Camera状态，作为下一SEG Entry Authority}

【FORBIDDEN】

禁止人物换脸、年龄漂移、服装重设、自由想象未定义身体/背面/下装/鞋履、伤口错位/消失、未来状态提前、PROP SPEC漂移、INSTANCE交换/克隆/丢失、Holder错位、销毁后完整重生、空间镜像、超出Geometry Proxy覆盖、额外人物、Panel Morph、Shot Morph、静态滑动、融化变形、多个分段素材输出、外部剪辑依赖和未授权剧情变化。

【OUTPUT】

输出一条已经包含全部有序Shot、原生Transition和批准声音连续性的完整{duration}视频，画幅{aspect_ratio}，严格达到Final State。不输出单独镜头、剪辑素材、占位转场或后期处理建议；不添加片头、字幕、水印或额外结尾，除非项目配置明确要求。
```

## 7. Episode生产包格式

```text
0. PROJECT CONFIG与Assumptions
1. PROJECT ID / ID POLICY / REGISTRY SNAPSHOT
2. CANONICAL ASSET REGISTRY与ID Resolution Audit
3. EPISODE STORY TRUTH / Presented Truth
4. ENTITY MAP与未解信息
5. Scene / Beat Map
6. Current Resolved World State
7. Required Asset List / Reserved Revision IDs
8. Asset Dependency Order
9. 每个NEW资产：Resolved Manifest + Complete Prompt
10. Spatial Master / Current Revision
11. Geometry Proxy / Canonical LOC_VIEW / Multiview Reconciliation
12. COST物化决策 / Complete LOOK / CT Visual Coverage Map
13. Continuity Ledger Deltas与State Lifecycle
14. Directing / Blocking / Performance
15. CVS与VT
16. SCSTATE Plan与每项Resolved Manifest + Prompt
17. Shot / Editing / Timing
18. Model-Native Transition Plan / Capability Gate
19. SEG Packaging / Transition Ownership
20. Storyboard Package：Resolved Manifest + KF/Transition Contract + Prompt
21. Camera Reveal Envelope / First Reveal Coverage Gate
22. Video Execution Plan / Shot + Transition Windows
23. Video：一次生成完整多镜头成片Manifest + Complete Prompt
24. Audio Cue Sheet（需要时）
25. Canonical Exit State / Next Entry Handoff
```

若用户只要求某一层，交付该层和其必要上游合同；不要强制输出无关部分。但不得省略该层执行所需的Reference Manifest、状态展开或完整Prompt。
