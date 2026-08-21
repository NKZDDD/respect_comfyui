第十二部分｜服饰资产、完整LOOK与首次显露覆盖
目录
核心结论
服饰资产双路径
COST独立资产建立条件
LOOK是人物服饰主权威
LOOK与CT视觉覆盖包
Camera Reveal Envelope
First Reveal Coverage Gate
Storyboard与Video参考角色
服饰与覆盖冻结条件
Prompt执行块
常见失败与修复
1. 核心结论
下游看到的当前人物主资产必须是“服饰已经穿在当前PH人物身上的完整LOOK”，而不是一张孤立服装图。独立COST资产按价值选择建立，不是每套服装都强制出图。
当视频可能显示故事板未显示的身体或服饰区域时，必须在视频生成前提供当前LOOK/CT的对应视觉覆盖，或限制Camera不去显露该区域。视频模型不得自由想象。
2. 服饰资产双路径
路径A｜独立COST + 完整LOOK
适用于关键、复杂、复用或需要独立审批的服装：
[text]PH + COST Canonical Visual Asset↓ on-body reconstructionLOOK Canonical Full Character Asset
路径B｜服饰逻辑合同 + 完整LOOK
适用于一次性、简单、非关键服装：
[text]PH + resolved costume text contract (COST = LOGICAL_ONLY)↓ on-body reconstructionLOOK Canonical Full Character Asset
两条路径的下游结果都必须是LOOK。不得因为省略独立COST图，就省略鞋履、背面、衣长、层次、版型或穿着方式的明确视觉答案。
3. COST独立资产建立条件
满足任一项时，COST应物化为独立Canonical Visual Asset：
Hero Costume、制服、礼服、年代服装或叙事标志性造型。
复杂层次、特殊剪裁、特殊材质、关键纹样、徽章或可读文字。
同一套服装跨多个PH、角色、集数或大量镜头复用。
需要服装部门/客户独立审批或后续换人试穿。
服装本体会损坏、拆解、脱下、交接或成为剧情对象。
模型对该服装已经发生显著漂移。
以下情况可保持LOGICAL_ONLY：一次性普通T恤、简单居家服、无关键细节且只服务少量镜头的背景服装。系统仍需冻结完整文字合同，并直接建立穿在人物身上的LOOK。
独立COST图使用无Identity人台、幽灵模特、平铺与关键细节；不让示例脸、身体或Pose成为人物Authority。
4. LOOK是人物服饰主权威
LOOK必须定义：
[text]current character identity and PHhead-to-toe body proportionscostume fit on this bodyshoulder / waist / hip fitneckline / sleeve / closurelayer ordergarment length / hem positionfront / side / back constructionfabric drape and thicknessfootwearfixed wearable accessoriesmovement restrictions
LOOK至少提供FRONT、L45或R45、PROFILE、BACK，并完整显示头、手和脚。高风险服装补充坐姿/抬臂等功能视图，但这些姿态只验证穿着结构，不进入Scene Blocking。
Storyboard与SCSTATE/SLC中只要LOOK/CT已经存在，当前人物服饰Primary Authority属于LOOK/CT。Video阶段该Authority默认已经编译进Canonical Storyboard Sheet，不重复上传LOOK/CT；只有首次显露缺口经Storyboard回编仍不足并通过例外证明时，才补最小LOOK/CT Reference。独立COST不能与LOOK并列争夺最终穿着比例、人物身体或当前状态。
5. LOOK与CT视觉覆盖包
Visual Coverage回答：当Camera从不同范围观察当前人物时，哪些区域已有合法视觉定义。
每个当前Visual Root维护Coverage Map：
[text]face_headfront_torsoback_torsoleft_right_profilearms_handswaist_hiplegsfootwearrear_full_bodystate_specific_detailcoverage_status = DEFINED | TEXT_ONLY | UNDEFINEDsource_view_revision_or_file_role
LOOK的标准全身多视图通常覆盖Clean State。CT必须继承LOOK全身比例，并覆盖所有会被显露的Active State。
CT覆盖原则
CT状态只发生在脸部但视频会看到全身：可使用当前LOOK全身覆盖 + CT脸部精确Delta，并明确LOOK不允许清除CT。
CT改变衣服湿度、泥污、破损、血迹或大范围身体外观：优先建立Coverage-complete CT全身视图。
未来状态不得混入当前Coverage Package。
背面或鞋履若会首次显露，不能继续标记UNDEFINED。
Coverage View可作为同一LOOK/CT Revision下的文件角色登记；若内容改变Canonical视觉答案，则创建新Revision，禁止覆盖旧文件。
6. Camera Reveal Envelope
在Storyboard冻结后、Video Prompt前，对每个SEG/Window预测Camera和表演可能显露的最大范围：
[text]initial_cropmaximum_pullbackcamera_orbit_rangecharacter_turn_rangestand_sit_kneel_transitionlimb_extensionfront_side_back_revealfootwear_revealocclusion_releasemotion_overscan_margin
这叫Camera Reveal Envelope。它不是要求所有镜头都拍全身，而是提前判断“视频过程中可能首次看见什么”。
7. First Reveal Coverage Gate
逐Window执行：
[text]Camera Reveal Envelope∩ current Character / Costume / CT regions↓Required Coverage↓ compareCoverage Map
结果只有三种：
COVERED：可以生成视频。
SUPPLEMENTAL_REFERENCE_REQUIRED：添加当前LOOK/CT覆盖图并写严格Authority。
CAMERA_CONSTRAINED：没有合法覆盖资产，Camera必须保持在已定义区域内。
若镜头必须显露而覆盖不存在，状态为PRODUCTION_BLOCKED，先建立/批准覆盖资产。不得以“出现概率不大”为理由跳过。
Framing Expansion Embargo
在Coverage Gate通过前，Video不得扩大构图、后退、环绕、让人物转身或起身到会显示未定义区域的程度。
8. Storyboard与Video参考角色
当Storyboard只有半身而Video可能全身时，使用Authority-Complete Coverage Set；不得为了少图让模型猜测下装、背面或鞋履：
[text]Image 1 = Current Temporal Primary Anchor / Storyboard execution cropAuthority: Camera、Timing、Blocking、Action Phase、Temporal State（仅适用时间窗）Image 2 = Current LOOK/CT Full-body CoverageAuthority: Identity、Body Proportion、Current Costume、Footwear、           unseen-but-to-be-revealed body/costume regionsDOES NOT CONTROL: Camera、Pose、Blocking、Background、Story Time、Action
如需CT局部细节：
[text]Image 3 = Current CT DetailAuthority: exact active-state position/shape/severity onlyDOES NOT CONTROL: clean-state replacement, body proportion, camera or pose
优先使用已融合的Coverage-complete CT，减少多Reference冲突。所有Image都必须解析到完整Canonical Revision ID、精确文件和角色。
9. 服饰与覆盖冻结条件
F2/F3冻结前确认：
每个当前人物造型已有完整LOOK，不以孤立COST代替。
关键/复杂/复用服装已有独立COST；简单服装有完整逻辑合同。
LOOK头到脚、正侧背、鞋履、衣长、层次、穿着比例明确。
当前CT没有退回Clean LOOK，也没有未来状态。
每个Video Window完成Camera Reveal Envelope和Coverage Gate。
所有可能首次显露区域均为DEFINED，或Camera已明确受限。
补充LOOK/CT只控制Identity/服装/覆盖，不覆盖Storyboard的Camera、Pose与时间。
10. Prompt执行块
Video Prompt加入：
[text]【CAMERA REVEAL ENVELOPE】Initial Crop: ...Maximum Reveal: ...Character Rotation / Posture Change: ...Required Body / Costume Regions: ...【VISUAL COVERAGE AUTHORITY】Current Visual Root: {full canonical revision id}Coverage Source Images: ...Defined Regions: ...Unrevealed Regions: ...Authority Priority: Temporal Primary camera/time > current LOOK/CT visual coverage【FIRST REVEAL LOCK】At first appearance of lower body / back / footwear / hands, reproduce theapproved current LOOK/CT coverage. Do not invent, simplify, restyle or replace.【FRAMING EXPANSION EMBARGO】Camera and performance must remain inside approved coverage. If a region is notdefined, do not reveal it.
11. 常见失败与修复
失败
根因
修复
服装图很清楚但穿到人身上变样
COST没有经过on-body LOOK冻结
独立COST后必须生成完整LOOK
每套普通服装都出独立资产导致膨胀
无物化条件
简单服装LOGICAL_ONLY，直接生成LOOK
没有COST图导致衣服细节随机
文字合同不完整
冻结结构、材质、长度、鞋履并生成LOOK
Storyboard半身，视频全身漂移
未做First Reveal Coverage
当前LOOK/CT全身覆盖或限制Camera
补全身参考后镜头构图被重置
Reference角色重叠
Storyboard管Camera，LOOK/CT只管视觉覆盖
全身LOOK把伤口清掉
Clean LOOK覆盖当前CT
当前CT优先；明确LOOK不得控制Active Delta
背面衣服被模型想象成另一款
Back Coverage未定义
LOOK/CT BACK视图进入Coverage Package
鞋子到视频才第一次生成
LOOK裁脚
LOOK必须头手脚完整，Footwear单独核对

图像减压不取消Hero人物的首次显露覆盖。读取[Logical-First、Video-Weighted Execution、Canonical Boundary与一致性底座](18-logical-first-video-weighted-execution.md)后，COST与无差异PH可以LOGICAL_ONLY，但当前Hero LOOK仍应覆盖视频实际会显露的正面、侧面、背面、全身、手和鞋履；如果没有覆盖，限制Camera或补充单一Coverage Reference，不让视频在首次全身时自由重设计。
