第十六部分｜场景机位覆盖规划与重复视图控制
目录
问题定义
正确生产顺序
Story / Shot空间需求提取
Location View Coverage Plan
View Utility Contract
View Distinctness Gate
动态视图数量与功能角色
Camera Rig差异设计
相邻View参考防火墙
与VIEW_BATCH / VIEWPACK的关系
LOC_VIEW完整提示词增量合同
发布会场景修复示例
失败码与回退
交付前审计
1. 问题定义
同一Location的多张场景图可能几何一致，却仍然没有生产价值。常见表现是：
A01、A02、A03都处于相近眼平高度。
镜头焦段接近，全部Look-at同一个空间中心。
只有轻微左右平移、缩放或裁切变化。
每张图看到的Zone、Portal、Route、Barrier和Landmark几乎相同。
下游无法说明哪一个KF、Shot或Camera Reveal必须使用其中某张图。
这类资产不是“多视角覆盖”，而是REDUNDANT VIEW FAMILY。它会增加生成次数、Reference槽位和Authority竞争，却没有补足新空间信息。
必须区分两个问题：
[text]Cross-view Geometry Consistency= 不同View能否拼回同一个物理空间View Coverage Distinctness= 每个View是否提供不可由已有View替代的独有空间Authority
两个条件都通过，LOC_VIEW才有资格进入Canonical生产。
2. 正确生产顺序
场景资产不得先任意规定三视图，再检查它们能否合并。统一执行：
[text]LOC + SPATIAL + GEO_PROXY→ Story / Shot Spatial Demand Extraction→ Location View Coverage Plan→ View Utility Contract→ View Distinctness & Redundancy Gate→ View Merge Eligibility Audit→ SINGLE_VIEW / VIEW_BATCH / VIEWPACK→ independent Canonical LOC_VIEW→ LOC_VIEWSET / PR
View Distinctness Gate回答“这张View是否值得存在”；View Merge Eligibility Audit回答“已经证明必要的View能否在同一次调用中安全生产”。不得倒置。
3. Story / Shot空间需求提取
先从当前生产范围的Scene、Beat、Blocking、Shot表达需求、Storyboard KF和Video Camera Reveal中提取空间需求，不从固定模板反推机位数量。
至少提取：
[text]source_scene_revision_idssource_beat_revision_idssource_seg_revision_idssource_shot_or_kf_demandsentry_and_exit_portalscharacter_start_end_anchorsauthorized_movement_routesbarriers_and_support_relationsrequired_action_axesrequired_reverse_directionsrequired_reaction_sightlinesrequired_camera_reveal_envelopesrequired_functional_detailscontinuity_landmarks
如果当前范围只需要正面总览和入口方向，不得因为“标准三视图”自动创建第三张相似斜角图。
如果故事后续可能需要某个方向，但当前范围尚无确定消费者，登记为DEFERRED VIEW DEMAND，不得提前生成并伪装为当前必需资产。
4. Location View Coverage Plan
每个Location在分配LOC_VIEW ID前必须建立：
[text]coverage_plan_revision_idlocation_revision_idspatial_revision_idgeo_proxy_revision_idsource_scene_revision_idssource_seg_revision_idssource_shot_or_kf_demandsrequired_zonesrequired_portalsrequired_routesrequired_barriersrequired_support_anchorsrequired_reverse_directionsrequired_camera_reveal_envelopesrequired_functional_detailscandidate_view_revision_idscoverage_matrixuncovered_demandsdeferred_demandscoverage_decision = COMPLETE | GAP | BLOCKED
coverage_matrix逐项记录每个Candidate View能覆盖哪些真实需求。若一张View没有任何独有消费者或独有空间项，不得仅因构图略有不同而保留。
每项需求必须落入以下结果之一：
COVERED_BY_VIEW：由一个批准View完整覆盖。
COVERED_BY_GEO_PROXY：下游可直接由同一Proxy安全投影，不需要额外静态View。
COVERED_BY_ALLOWED_CROP：同一View的批准裁切足够，不建立新View。
DEFERRED：不属于当前生产范围。
UNCOVERED：必须补机位或修改Camera设计。
5. View Utility Contract
每个候选LOC_VIEW必须在生成前填写：
[text]loc_view_revision_idview_rolecamera_rigunique_visible_zonesunique_portals_routes_barriers_anchorsblocking_functionstory_shot_kf_consumerscamera_reveal_consumersdifference_from_approved_viewsoverlap_ratio_estimateaxis_delta_degcamera_baseline_ratio_to_scene_diagonalparallax_or_occlusion_deltaallowed_cropcannot_be_replaced_by_crop_reasonneighbor_reference_idsutility_decision = REQUIRED | OPTIONAL | REDUNDANT | BLOCKEDdecision_reason
story_shot_kf_consumers必须使用完整Canonical Revision ID或明确的Reserved Revision ID，不得写“后面可能会用”。
difference_from_approved_views必须描述空间信息差异，例如“首次完整揭示西侧入口与长桌左端之间的Portal关系”，不能只写“角度不同”“更电影感”或“更近”。
6. View Distinctness Gate
新View只有至少满足一项，才可标记REQUIRED或OPTIONAL：
揭示已有View不可见的关键Zone。
揭示独有Portal、Route、Barrier、Seat/Support Anchor或它们之间的关系。
服务独有动作轴、Blocking关系、反打方向或关键视线。
覆盖已冻结Storyboard/Video Camera Reveal，而已有View和GEO_PROXY安全范围不能替代。
提供无法由现有高分辨率View裁切得到的真实视差、遮挡顺序或连接关系。
提供剧情必须读取的功能细节，且该细节不能由独立Detail Asset更合理地承担。
下列情况默认判定REDUNDANT：
仅改变焦段或轻微Zoom，空间关系没有新增。
仅做小幅横移、升降或裁切，可见Zone和Landmark基本相同。
与批准View拥有相同功能角色、相同消费者和相同空间Authority。
能由批准高分辨率View的allowed_crop安全得到。
只为了凑足固定三视图、对称排版或填满VIEWPACK格位。
主要差异来自临时人物、道具或灯光状态，而不是Location View本身。
建议启发式，不是跨项目硬阈值：
[text]if estimated_overlap > 80%and unique_zone_or_relation = NONEand unique_consumer = NONEthen REDUNDANT_VIEW_REJECTED
物质性差异通常至少满足以下之一：机位轴线差约35度以上；Camera Baseline达到场景对角线约15%以上；或明确揭示独有Zone、Portal、Route、Barrier、Anchor、视差或遮挡关系。功能独特性高于数值启发式；狭小空间、长焦压缩和特殊动作轴可有例外，但必须写理由。
7. 动态视图数量与功能角色
视图数量由覆盖计划决定，不固定为三张。
常见角色：
SPATIAL_MASTER：建立整体尺度、主轴和主要Zone关系。
PORTAL_ENTRY：明确入口、出口、门侧和进入路线。
ACTION_AXIS：服务核心动作、对峙、追逐或交互轴线。
REVERSE_COVERAGE：提供必要反向关系和视线，但不改变World Placement。
ROUTE_COVERAGE：覆盖长距离移动、跨Zone和Portal连续性。
FUNCTIONAL_DETAIL：读取剧情关键固定设施；能独立做Detail Asset时优先独立，而不是伪装成全新广角View。
经验范围仅供规划：
单一、简单、低风险房间通常2张就够。
有入口与动作轴的场景通常2至3张。
有跨Zone、追逐、环绕或重复使用的复杂空间可能3至4张。
任何超过当前消费者需求的View都应DEFERRED，不能因为场景重要而无限扩张。
同一Camera Position只改变Shot Size、裁切或轻微焦段时，登记为一个LOC_VIEW的allowed_crop或Derived Crop，不创建新的Canonical View ID。
8. Camera Rig差异设计
不同View的差异必须来自空间用途，不是随机扰动参数。
每个Camera Rig至少冻结：
[text]camera_xyz_mlook_at_xyz_mcamera_height_myaw_pitch_roll_deglens_mm_or_horizontal_fovaspect_ratioprimary_axisforeground_occludersvisible_zone_envelopeoccluded_zone_envelope
设计顺序：
先选View Role和必须揭示的空间关系。
从GEO_PROXY寻找能清楚观察该关系的Camera Zone。
确保与已有View产生真实轴线、Baseline、视差或遮挡差异。
再选择焦段和构图，不得用焦段变化冒充新空间覆盖。
回投Coverage Matrix，确认该View有独有消费者。
如果多个候选机位都在相近眼平高度、使用相近焦段并共同Look-at房间中心，必须暂停并重做Role设计；这通常意味着只是“左中右轻微偏移”。
9. 相邻View参考防火墙
相邻已批准View只用于跨视图身份与几何核对，不得把其构图复制到当前View。
每个相邻View槽必须在Manifest和Prompt内写：
[text]Image N = {FULL_APPROVED_NEIGHBOR_LOC_VIEW_ID}Who / What + Visible Content: 同一Location的已批准相邻视角，画面可见{具体Zone/Landmark}Story Time / Current State: {Reality Thread / Environment State}Controls: 固定结构身份、材质身份、Landmark、尺度和Overlap对应关系Does Not Control: 当前Camera XYZ、Height、Look-at、Lens、Crop、Composition、Visible Zone、Shot SizeApplicable Scope: 仅用于{CURRENT_LOC_VIEW_ID}的Cross-view Identity Verification
最终Prompt必须逐字表达等价防火墙：
[text]Image N仅用于跨视图身份验证；不控制当前Camera XYZ / Height / Look-at / Lens / Crop / Composition / Visible Zone / Shot Size。不得复现Image N的构图。
如果模型持续模仿相邻View构图，减少相邻图数量，优先保留GEO_PROXY；必要时只上传一个与当前View共享Landmark最明确的邻接View。
10. 与VIEW_BATCH / VIEWPACK的关系
只对已通过View Distinctness Gate的必要View执行[同场景兼容机位合并生产](15-compatible-location-view-batching.md)。
[text]Compatible for one call≠ Each View is necessary
Camera Cluster相近只说明它们可能兼容同批生产，不说明它们应当同时存在。一个VIEWPACK不得用空格位诱导新增冗余View。
合并前逐View确认：
utility_decision不是REDUNDANT或BLOCKED。
每个View有不同Role或不同独有Coverage。
每个View有至少一个明确消费者。
使用Atlas时每个Panel仍有足够像素预算。
合并Prompt保留每个View的独立Camera Rig和Unique Coverage，不平均化构图。
11. LOC_VIEW完整提示词增量合同
除[原子资产完整提示词模板](09-atomic-asset-prompt-templates.md)外，每个LOC_VIEW Prompt必须加入：
[text]【VIEW ROLE】View Role: {SPATIAL_MASTER | PORTAL_ENTRY | ACTION_AXIS | REVERSE_COVERAGE | ROUTE_COVERAGE | FUNCTIONAL_DETAIL}Story / Shot / KF Consumers: {完整Revision IDs}Blocking Function: {具体用途}【UNIQUE COVERAGE】Unique Visible Zones: {列表}Unique Portal / Route / Barrier / Anchor Relations: {列表}Parallax / Occlusion Difference: {说明}Difference from Approved Views: {说明}【REDUNDANCY DECLARATION】Estimated Overlap: {比例或定性}Axis Delta / Camera Baseline: {信息}Allowed Crop Alternative: {信息}Cannot Be Replaced by Existing Crop Because: {具体原因}Utility Decision: REQUIRED | OPTIONAL【NEIGHBOR REFERENCE FIREWALL】{逐Image写只控制跨View身份与Overlap；不控制当前Camera、Crop、Composition和Visible Zone}
若Cannot Be Replaced by Existing Crop Because无法给出具体理由，停止生成并返回VIEW_UTILITY_UNPROVEN。
12. 发布会场景修复示例
问题Rig：三个机位都约1.65至1.75米高、42至50毫米、Look-at发布台中心。虽然左右坐标不同，但都主要看到发布台、中央过道与同一组椅子，导致资产高度相似。
修复不是随机放大坐标差，而是重定义功能：
[text]VIEW_A01 / SPATIAL_MASTER正面略高主视角；建立发布台、媒体排、中央过道、入口与饮品桌的总体关系。VIEW_A02 / PORTAL_ENTRY机位靠近发布台右侧并朝西侧入口形成约40至55度轴线差；首次清楚揭示入口门、Julie进入Route、媒体左排与发布台左端的连接。VIEW_A03 / ACTION_AXIS机位落在入口侧反向观察饮品桌与Isabel倒地点；清楚揭示饮品桌、两瓶锚点、攻击Route、中央过道和倒地点之间的距离与遮挡。
如果VIEW_A03仍只提供A01的轻微右移版本，就删除A03，使用A01的裁切或直接用GEO_PROXY支撑后续Shot。不能因为原计划有三张图而保留。
13. 失败码与回退
失败码
条件
处理
`VIEW_COVERAGE_PLAN_REQUIRED`
未从Scene/Shot/KF提取空间需求就开始分配View
先建立Coverage Plan
`VIEW_UTILITY_UNPROVEN`
Candidate没有独有消费者或不能解释为何不可由裁切替代
删除、合并为Crop或补充真实需求
`REDUNDANT_VIEW_REJECTED`
与已有View高度重叠且无独有Authority
不分配Canonical View；保留为Rejected Candidate记录
`VIEW_DISTINCTNESS_BLOCKED`
Rig无法产生必要轴线、视差、Zone或功能差异
回到GEO_PROXY重做Camera Role/Rig
`VIEW_COVERAGE_GAP`
Storyboard/Video需求未被批准View、Proxy或Crop覆盖
新建必要View或限制Camera
`MULTIVIEW_RECONCILIATION_BLOCKED`
必要View无法由同一Spatial/GEO解释
修正Geometry或候选View，不进入下游

被拒绝View的ID若已在Registry保留，不得转给另一View；把状态标为REJECTED_CANDIDATE或按项目注册表规则保留，不得覆盖旧内容。
14. 交付前审计
[ ] 每个Location先有Story / Shot Spatial Demand Extraction。
[ ] 每个Location有Location View Coverage Plan和Coverage Matrix。
[ ] 视图数量是动态结果，不是固定三视图。
[ ] 每个Candidate View有完整View Utility Contract。
[ ] 每个批准View至少有一个明确Scene、Shot、KF或Camera Reveal消费者。
[ ] 每个批准View有独有Zone、Portal、Route、Barrier、Anchor、动作轴、视差、遮挡或功能细节之一。
[ ] 仅焦段、Zoom、轻微横移或裁切差异没有被创建为新Canonical View。
[ ] 可由已有高分辨率View安全裁切的构图已登记为allowed_crop。
[ ] Overlap高且无独有Authority的Candidate已触发REDUNDANT_VIEW_REJECTED。
[ ] View Role先于Camera Rig；焦段没有被当作独立空间用途。
[ ] 相邻View只控制固定身份、Landmark、尺度和Overlap，不控制当前Camera或Composition。
[ ] Prompt中已明确“不得复现相邻View构图”。
[ ] 只有通过Distinctness Gate的View进入View Merge Eligibility Audit。
[ ] VIEW_BATCH / VIEWPACK没有为填满格位新增冗余View。
[ ] 每个输出View保持独立完整ID、文件、Fingerprint、Camera Rig和Unique Coverage。
[ ] Coverage Gap已通过新View、GEO_PROXY或Camera约束解决，没有留给Storyboard/Video想象。
