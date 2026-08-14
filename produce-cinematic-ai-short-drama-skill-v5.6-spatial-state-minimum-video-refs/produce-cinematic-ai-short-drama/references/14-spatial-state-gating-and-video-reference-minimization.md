# 空间状态门控与视频参考最小化

## 目录

1. 两类高风险失败
2. World Position State
3. Seat / Support Binding
4. Barrier、Portal与Route
5. Authorized Spatial Transition
6. SCSTATE Delta Inheritance
7. Storyboard Position Continuity
8. Video Reference Authority Stack
9. Minimum Sufficient Reference Set
10. 冲突阻断与回编

## 1. 两类高风险失败

### Unauthorized Position Jump

人物在前一状态坐在发布会桌后，下一状态没有起身、绕行或穿越事件，却直接出现在观众区争吵。这不是Camera变化，而是World Truth被静默改写。

### Composite Reference Authority Collision

Video同时上传Storyboard、同一状态的SCSTATE、人物LOOK、Location PR与Prop图。Storyboard要求具体机位和Blocking，SCSTATE要求中性构图，Atomic资产又携带中性Pose或独立背景；模型会平均融合，导致人物换位、机位回退或场景重排。

这两类问题必须分别在F3位置状态和F6视频输入解析阶段解决。

## 2. World Position State

每个关键实体在CVS、SCSTATE、KF与Video Entry/Exit中维护：

```text
entity_revision_id
spatial_revision_id
zone_id
anchor_id
root_or_pivot_xyz_m
orientation_yaw_deg
posture_class = STANDING | SEATED | KNEELING | LYING | MOVING
support_binding_id
support_relation = SEATED_ON | LYING_ON | LEANING_ON | STANDING_ON | HELD_BY | NONE
contact_points
footprint_or_bbox
accessible_routes
current_barrier_side
movement_state = STABLE | TRANSITIONING
last_authorized_movement_event_id
```

位置状态遵守Persistence：没有合法事件时，下一状态逐项继承。画面里暂时看不到人物，不允许把其Anchor改为“更方便拍摄”的位置。

## 3. Seat / Support Binding

坐、躺、乘车、轮椅、担架、跪靠或被扶持都不是普通Pose，必须绑定支撑实体与接触关系。

```text
support_binding_id
support_entity_or_anchor_id
relation
local_offset_xyz_m
body_axis
contact_points
release_event_id
release_completion_condition
```

人物离开座椅前必须先发生`RELEASE_SUPPORT / STAND_UP_COMPLETION`。只要Release没有完成，Storyboard不能把人物画成站在另一Zone；Camera拉远也不能取消座椅关系。

## 4. Barrier、Portal与Route

桌子、柜台、病床护栏、墙、玻璃、门、车辆、舞台边缘和围栏必须作为空间拓扑，而不是背景装饰。

Spatial Master补充：

```text
barrier_id / bbox / blocks_which_entities
portal_or_gap_id / width / open_state
side_a_zone / side_b_zone
route_id = ordered anchors
route_length_m
route_clearance
minimum_action_time
```

人物不能穿过实心会议桌、墙或座椅排。跨Barrier只能使用批准Portal、桌端空隙、门或剧情明确的破坏事件。

## 5. Authorized Spatial Transition

任一Position State变化必须写成：

```text
movement_event_id
source_cvs_id
mover_revision_id
start_zone / start_anchor / start_support
release_support_action
route_id
barrier_or_portal_crossing
movement_cause
start_time / completion_time
end_zone / end_anchor / end_support
target_cvs_id
occlusion_coverage_if_not_fully_visible
```

合法链：

```text
SEATED_BEHIND_DESK
→ stand up completed
→ move along behind-desk lane
→ pass approved desk-end gap
→ enter public-side zone
→ arrive and establish stance
```

禁止链：

```text
SEATED_BEHIND_DESK
→ next SCSTATE directly arguing in front aisle
```

动作可在Shot中部分遮挡，但必须有足够真实时间、可行Route与明确完成条件。若剧情没有给出时间，保留原Anchor或修改导演Blocking，不得瞬移。

## 6. SCSTATE Delta Inheritance

每个SCSTATE Prompt必须先声明前一稳定状态，再声明唯一合法Delta：

```text
PREVIOUS SCSTATE
UNCHANGED POSITION STATES
AUTHORIZED MOVERS
AUTHORIZED MOVEMENT EVENT
START / ROUTE / END
SUPPORT RELEASE OR ACQUISITION
FORBIDDEN POSITION DELTA
```

规则：

- 相邻SCSTATE默认继承全部人物Zone、Anchor、Support、Orientation与Barrier Side。
- 只有`AUTHORIZED MOVERS`中的实体允许改变位置。
- 情绪升级、对白变化、照片抛出或Camera改变不自动授权人物换位。
- 为了让三人同框、显示全身或制造对峙构图，不能把人物移到房间中央。
- 一个机位看不全时，允许人物部分可见、遮挡或离画；也可使用另一个中性观察机位，但不能改World Placement。

SCSTATE是World State验证图，不是宣传剧照。若生成图与CVS位置冲突，SCSTATE作废并重生；不得回写错误位置。

## 7. Storyboard Position Continuity

每个KF增加：

```text
ENTRY WORLD POSITION STATE
POSITION DELTA FROM PREVIOUS KF
AUTHORIZED MOVEMENT EVENT ID or NONE
SUPPORT BINDING
BARRIER SIDE
ROUTE PROGRESS
EXIT WORLD POSITION STATE
```

`Authorized Movement Event ID = NONE`时，KF只能改变Camera投影、表演、视线、手势或Action Phase，不能改变人物真实Zone/Anchor/Support。

Storyboard Prompt必须声明：

```text
CAMERA MAY REFRAME; ENTITIES MAY NOT REBLOCK.
DO NOT MOVE SUBJECTS FOR VISIBILITY OR COMPOSITION.
```

若一个动作要求人物离开座位并进入另一Zone，至少提供起身/Route阶段或在可信遮挡期间完成批准移动；目标KF仍须绑定Target CVS，不得把遮挡当作自由瞬移许可证。

## 8. Video Reference Authority Stack

Video阶段使用单一组合主权威：

```text
Primary Composite Authority = Canonical Storyboard execution image(s)
Supplemental Identity/Coverage Authority = current LOOK/CT only when needed
Supplemental Detail Authority = story-critical Prop text/detail only when needed
Supplemental Geometry Authority = approved View/Proxy only when Camera reveal exceeds Storyboard coverage
```

SCSTATE已经被Storyboard消费，不再默认上传给Video。对于同一时间、同一Location、同一人物组合：

```text
Storyboard + SCSTATE = FORBIDDEN BY DEFAULT
```

只有Storyboard缺失某个稳定World State且无法回编时才可临时使用SCSTATE；此时必须先修正Storyboard，正式交付仍以Storyboard为唯一Composite Authority。

## 9. Minimum Sufficient Reference Set

按以下顺序选择：

1. 上传当前SEG的Canonical Storyboard执行图；Continuation Sheets按时间顺序上传。
2. 检查人物Identity、服饰、背面、手脚、鞋履或CT区域是否在Storyboard/现有执行图中清楚覆盖。
3. 只有存在明确Coverage缺口时，补充受影响人物的当前完整LOOK或CT；不要把所有人物图例行加入。
4. 只有故事关键文字、独特几何或材质在Storyboard中不可辨识时，补充对应Prop或Location细节。
5. 删除任何与Storyboard重复表达同一组合世界的SCSTATE、PR、LOC_VIEW或Atomic资产。

典型数量：

```text
1张Storyboard Sheet → 通常1张Reference
2张Continuation Sheets → 通常2张Reference
身份局部漂移 → 再加1张受影响人物LOOK/CT
关键文字不可读 → 再加1张Hero Prop Detail
```

超过5张Reference时执行强制Conflict Audit：逐张写`Unique Missing Authority`。无法证明唯一缺口的图片删除。模型参考上限是容量上限，不是推荐装满数量。

### 不同时上传Clean LOOK与未来CT

若同一SEG内发生Clean LOOK→CT激活，优先由Storyboard的有序KF与时间门控控制。除非模型已验证支持Reference Time Scope，否则不要同时上传Clean全身图和未来CT全身图；它们容易导致伤口提前或状态被抹平。确需补图时，只补无法由Storyboard表达的局部Coverage，并写绝对时间范围。

## 10. 冲突阻断与回编

以下任一情况返回`REFERENCE_AUTHORITY_CONFLICT`并停止Video Prompt释放：

- Storyboard与SCSTATE对同一人物给出不同World Placement。
- 两张Composite Reference对同一时间给出不同Blocking、Camera或Prop Holder。
- Supplemental LOOK/CT被要求控制Pose、Camera、Blocking或动作时间。
- Clean LOOK与未来CT同时具有全时段Authority。
- 参考图超过5张但没有逐张Unique Missing Authority。

以下任一情况返回`POSITION_STATE_TRANSITION_BLOCKED`并回到Director/CVS：

- 人物Zone或Support发生变化但没有Movement Event。
- Route穿过Barrier且没有合法Portal。
- 移动所需时间大于可用Shot Window。
- SCSTATE或KF为了构图擅自移动人物。
- Target Anchor与Location Geometry不可达。

修正后创建新的Canonical Revision并重编受影响SCSTATE、Storyboard与Video；不得覆盖旧Revision文件。
