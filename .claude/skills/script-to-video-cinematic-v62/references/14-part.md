第十四部分｜空间状态门控与Authority完整视频参考
目录
两类高风险失败
World Position State
Seat / Support Binding
Barrier、Portal与Route
Authorized Spatial Transition
SCSTATE Delta Inheritance
Storyboard Position Continuity
Video Reference Authority Stack
Authority-Complete Nonconflicting Reference Set
冲突阻断与回编
1. 两类高风险失败
Unauthorized Position Jump
人物在前一状态坐在发布会桌后，下一状态没有起身、绕行或穿越事件，却直接出现在观众区争吵。这不是Camera变化，而是World Truth被静默改写。
Composite Reference Authority Collision
Video同时上传Storyboard、同一状态的SCSTATE、人物LOOK、Location PR与Prop图。Storyboard要求具体机位和Blocking，SCSTATE要求中性构图，Atomic资产又携带中性Pose或独立背景；模型会平均融合，导致人物换位、机位回退或场景重排。
这两类问题必须分别在F3位置状态和F6视频输入解析阶段解决。
2. World Position State
每个关键实体在CVS、SCSTATE、KF与Video Entry/Exit中维护：
[text]entity_revision_idspatial_revision_idzone_idanchor_idroot_or_pivot_xyz_morientation_yaw_degposture_class = STANDING | SEATED | KNEELING | LYING | MOVINGsupport_binding_idsupport_relation = SEATED_ON | LYING_ON | LEANING_ON | STANDING_ON | HELD_BY | NONEcontact_pointsfootprint_or_bboxaccessible_routescurrent_barrier_sidemovement_state = STABLE | TRANSITIONINGlast_authorized_movement_event_id
位置状态遵守Persistence：没有合法事件时，下一状态逐项继承。画面里暂时看不到人物，不允许把其Anchor改为“更方便拍摄”的位置。
3. Seat / Support Binding
坐、躺、乘车、轮椅、担架、跪靠或被扶持都不是普通Pose，必须绑定支撑实体与接触关系。
[text]support_binding_idsupport_entity_or_anchor_idrelationlocal_offset_xyz_mbody_axiscontact_pointsrelease_event_idrelease_completion_condition
人物离开座椅前必须先发生RELEASE_SUPPORT / STAND_UP_COMPLETION。只要Release没有完成，Storyboard不能把人物画成站在另一Zone；Camera拉远也不能取消座椅关系。
4. Barrier、Portal与Route
桌子、柜台、病床护栏、墙、玻璃、门、车辆、舞台边缘和围栏必须作为空间拓扑，而不是背景装饰。
Spatial Master补充：
[text]barrier_id / bbox / blocks_which_entitiesportal_or_gap_id / width / open_stateside_a_zone / side_b_zoneroute_id = ordered anchorsroute_length_mroute_clearanceminimum_action_time
人物不能穿过实心会议桌、墙或座椅排。跨Barrier只能使用批准Portal、桌端空隙、门或剧情明确的破坏事件。
5. Authorized Spatial Transition
任一Position State变化必须写成：
[text]movement_event_idsource_cvs_idmover_revision_idstart_zone / start_anchor / start_supportrelease_support_actionroute_idbarrier_or_portal_crossingmovement_causestart_time / completion_timeend_zone / end_anchor / end_supporttarget_cvs_idocclusion_coverage_if_not_fully_visible
合法链：
[text]SEATED_BEHIND_DESK→ stand up completed→ move along behind-desk lane→ pass approved desk-end gap→ enter public-side zone→ arrive and establish stance
禁止链：
[text]SEATED_BEHIND_DESK→ next SCSTATE directly arguing in front aisle
动作可在Shot中部分遮挡，但必须有足够真实时间、可行Route与明确完成条件。若剧情没有给出时间，保留原Anchor或修改导演Blocking，不得瞬移。
6. SCSTATE Delta Inheritance
每个SCSTATE Prompt必须先声明前一稳定状态，再声明唯一合法Delta：
[text]PREVIOUS SCSTATEUNCHANGED POSITION STATESAUTHORIZED MOVERSAUTHORIZED MOVEMENT EVENTSTART / ROUTE / ENDSUPPORT RELEASE OR ACQUISITIONFORBIDDEN POSITION DELTA
规则：
相邻SCSTATE默认继承全部人物Zone、Anchor、Support、Orientation与Barrier Side。
只有AUTHORIZED MOVERS中的实体允许改变位置。
情绪升级、对白变化、照片抛出或Camera改变不自动授权人物换位。
为了让三人同框、显示全身或制造对峙构图，不能把人物移到房间中央。
一个机位看不全时，允许人物部分可见、遮挡或离画；也可使用另一个中性观察机位，但不能改World Placement。
SCSTATE是World State验证图，不是宣传剧照。若生成图与CVS位置冲突，SCSTATE作废并重生；不得回写错误位置。
7. Storyboard Position Continuity
每个KF增加：
[text]ENTRY WORLD POSITION STATEPOSITION DELTA FROM PREVIOUS KFAUTHORIZED MOVEMENT EVENT ID or NONESUPPORT BINDINGBARRIER SIDEROUTE PROGRESSEXIT WORLD POSITION STATE
Authorized Movement Event ID = NONE时，KF只能改变Camera投影、表演、视线、手势或Action Phase，不能改变人物真实Zone/Anchor/Support。
Storyboard Prompt必须声明：
[text]CAMERA MAY REFRAME; ENTITIES MAY NOT REBLOCK.DO NOT MOVE SUBJECTS FOR VISIBILITY OR COMPOSITION.
若一个动作要求人物离开座位并进入另一Zone，至少提供起身/Route阶段或在可信遮挡期间完成批准移动；目标KF仍须绑定Target CVS，不得把遮挡当作自由瞬移许可证。
8. Video Reference Authority Stack
Video阶段使用按时间窗唯一Primary的角色栈：
[text]Mandatory Temporal/Cinematic Authority = ordered Storyboard Sheets or ordered Canonical KF Anchors covering the complete SEG progressionSupplemental Atomic Authority = proven Identity / Coverage / Geometry / Prop / State Result gap onlyReference Policy = mandatory_storyboard_plus_selective_effective_supplemental
SCSTATE已经被Storyboard消费，不再默认上传给Video。对于同一时间、同一Location、同一人物组合：
[text]Storyboard + SCSTATE = FORBIDDEN BY DEFAULT
Video不得用SCSTATE/SLC临时补救错误Canon。图片缺口先判断是否需要物化；中间动作和姿势可交给视频，但当前SEG仍必须有覆盖完整关键推进的Storyboard视觉骨架。载体可以是有序Continuation Sheets，也可以是同一SBPKG的有序独立KF Anchors；Hero Identity、当前LOOK/CT、相关LOC_VIEW以及World Position/Zone/Anchor/Support/Route/Orientation合同不得因减图消失。
9. Authority-Complete Nonconflicting Reference Set
读取[Logical-First、Video-Weighted Execution、Canonical Boundary与一致性底座](18-logical-first-video-weighted-execution.md)，按以下顺序选择：
读取视频可靠度及证据；它只调整骨架颗粒度、补图和Prompt冗余度。
建立六维Coverage Matrix：Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal、Prop/Count/Holder。
选择覆盖完整关键推进的有序Continuation Sheets或有序Canonical KF Anchors，建立Mandatory Storyboard Temporal Spine。
对每张故事板执行Revision、SEG、Thread、时间、状态、位置、Prop、边界与顺序Admission。
检查Camera Reveal、首次显露、新Zone、位置、Prop、State Result与Boundary缺口。
仅对真实缺口增加互补Supplemental，并证明Unique Authority Contribution和Applicable Window。
删除重复SCSTATE/SLC、重复KF、LOOK、PR或其他Atomic资产，但不得破坏完整时间骨架和六维Coverage。
拒绝所有生成视频截图、尾帧与Frame Grab；跨SEG只用预编译BNDPLAN/BNDANCHOR。
典型数量：
[text]Storyboard Spine → 当前SEG全部必要Continuation Sheets，或等价的有序关键KF AnchorsIdentity Supplemental → 主角当前完整LOOK/CT，仅在身份或首次显露覆盖不足时Spatial Supplemental → 当前Camera Reveal涉及的核心LOC_VIEW，仅在新Zone/Geometry不足时Detail Supplemental → Hero Prop或BNDANCHOR，仅在独有细节/边界不足时
模型参考上限是容量上限，不是推荐装满数量；最少张数也不是目标。Storyboard骨架缺失返回VIDEO_STORYBOARD_SPINE_MISSING；故事板错版、错时或错位返回STORYBOARD_REFERENCE_ADMISSION_FAILED；任一Supplemental没有独有Authority贡献时返回VIDEO_REFERENCE_UNIQUE_UTILITY_UNPROVEN；删图后任一维度无Authority时返回REFERENCE_DIMENSION_COVERAGE_GAP；存在权威冲突时返回VIDEO_REFERENCE_AUTHORITY_CONFLICT。
Position Visualization Floor
以下任一成立时，位置不能只靠文字，当前Temporal Primary、独立KF Anchor或BNDANCHOR必须清晰物化相关Spatial Cluster：
两名以上Hero的相对位置决定冲突、视线或身体接触；
人物受Seat/Support、桌、床、护栏、车辆或Barrier约束；
人物将通过Portal、绕过桌端、跨Zone或沿唯一Route移动；
攻击、交接、搀扶、跌倒、拥抱或多人手部关系依赖精确距离；
相邻SEG处于同一Location、同一Story Time并要求位置连续。
该Anchor只负责可见Cluster的World Placement与当前时间状态；Camera可由Shot合同控制。若一个Camera无法同时验证远距离Zone，建立不同时间窗或Zone-Coherent Anchor，不得把人物挪近。这样减掉的是重复SCSTATE图，不是位置视觉证据。
不同时上传Clean LOOK与未来CT
若同一SEG内发生Clean LOOK→CT激活，由Mandatory Storyboard Temporal Spine与时间门控控制。不得同时上传Clean全身图和未来CT全身图；它们容易导致伤口提前或状态被抹平。发现局部Coverage缺口时先回编Storyboard；仍无法解决且例外通过后，只补单一时间窗所需的最小局部Authority。
10. 冲突阻断与回编
以下任一情况返回REFERENCE_AUTHORITY_CONFLICT并停止Video Prompt释放：
Storyboard与SCSTATE对同一人物给出不同World Placement。
两张Composite Reference对同一时间给出不同Blocking、Camera或Prop Holder。
Supplemental LOOK/CT被要求控制Pose、Camera、Blocking或动作时间。
Clean LOOK与未来CT同时具有全时段Authority。
原子补充Reference没有首次显露缺口、时间窗与Storyboard回编仍不足的书面证明。
生成视频截图、尾帧或Frame Grab进入Reference Manifest。
删图后Identity、LOOK/CT、Spatial/Geometry、Position/Blocking、State/Temporal或Prop/Count/Holder任一维无Authority。
以下任一情况返回POSITION_STATE_TRANSITION_BLOCKED并回到Director/CVS：
人物Zone或Support发生变化但没有Movement Event。
Route穿过Barrier且没有合法Portal。
移动所需时间大于可用Shot Window。
SCSTATE或KF为了构图擅自移动人物。
Target Anchor与Location Geometry不可达。
修正后创建新的Canonical Revision并重编受影响SCSTATE、Storyboard与Video；不得覆盖旧Revision文件。
