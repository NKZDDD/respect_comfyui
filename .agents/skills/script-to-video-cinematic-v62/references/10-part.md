第十部分｜Canonical ID注册表与参考资产解析
目录
问题定义与最高规则
唯一ID模型
ID语法与命名空间
Family ID、Revision ID与Attempt
Canonical Asset Registry
ID分配与冻结
Canonical文件命名和定位
Reference Resolution Gate
Manifest、Prompt精确回显与身份映射
各生产层ID合同
状态与修订规则
旧项目迁移
错误处理
交付模板
硬规则与审计
1. 问题定义与最高规则
正式定义：
[text]Canonical ID Drift= 缩写+ 改写+ 大小写变化+ 漏层级+ 漏版本+ 别名替代+ 模糊匹配+ ID与真实文件脱钩
最高规则：
Canonical ID是不可改写的机器主键，不是方便阅读的名称。
一旦注册，所有层必须逐字符复用同一个完整ID。禁止把：
[text]PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01
写成：
[text]CT01女主CT01CHAR_001_CT01PH01_LK01_CT01CHAR1_LOOK1_STATE1
显示名称可写“女主雨夜受伤状态”，但显示名称只能进入display_name，不能替代任何ID字段。
2. 唯一ID模型
维护两层ID：
[text]ASSET FAMILY ID= 稳定语义对象CANONICAL REVISION ID= 某个不可变Canonical版本
生产Reference、Parent、CVS绑定、SCSTATE、KF、Storyboard和Video必须使用CANONICAL REVISION ID。Family ID只用于注册表分组、查修订历史和分配下一个Revision，不能直接指向一张生产参考图。
一个Canonical Revision ID只能对应一个明确资产版本；一个Canonical文件只能归属于一个Canonical Revision ID。不得一ID多图、多ID一图或同ID覆盖保存。
3. ID语法与命名空间
新项目使用Fully Qualified ID：
[text]{PROJECT_ID}__{OBJECT_PATH}_R{NN}
规则：
PROJECT_ID：PRJ_加3至16位大写ASCII字母或数字。
命名空间分隔符固定为双下划线__。
OBJECT_PATH只使用大写ASCII、数字和单下划线。
Revision固定为两位起步：R01、R02；超过99时扩为三位并全项目统一。
ID区分大小写；生产时执行Exact String Match。
禁止空格、中文、连字符、斜杠、括号、模糊编号和未补零数字。
示例：
[text]PRJ_NOVA__CHAR_001_R01PRJ_NOVA__CHAR_001_PH01_R01PRJ_NOVA__COST_001_R01PRJ_NOVA__CHAR_001_PH01_LK01_R01PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01PRJ_NOVA__LOC_001_R01PRJ_NOVA__LOC_001_PR01_R01PRJ_NOVA__SPATIAL_001_R01PRJ_NOVA__PROP_SPEC_001_V01_R01PRJ_NOVA__PROP_INST_001_R01PRJ_NOVA__SCSTATE_EP01_SC03_ST01_R01PRJ_NOVA__SCSTATE_EP01_SC03_ST01_SLC01_R01PRJ_NOVA__SBPKG_EP01_SEG01_R01PRJ_NOVA__SBSHEET_EP01_SEG01_A_R01PRJ_NOVA__KF_EP01_SEG01_01_R01
注意：V01表示故事/设计层面的合法规格版本；末尾R01表示该资产的不可变Canonical修订。两者不得混用。
4. Family ID、Revision ID与Attempt
Asset Family ID
[text]PRJ_NOVA__CHAR_001_PH01_LK01_CT01
表示“这个Canonical对象是什么”，不绑定具体文件。
Canonical Revision ID
[text]PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01
表示“当前被批准的具体不可变版本”，生产Reference只使用它。
Candidate Attempt
[text]PRJ_NOVA__CHAR_001_PH01_LK01_CT01__TRY_003.png
Attempt不是Canon，不进入Reference Manifest，不拥有Canonical Revision ID Authority。用户或生产体系确认后，另存为：
[text]PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01__PRIMARY.png
禁止把TRY_003直接改写成R01并覆盖旧文件；必须执行Promotion、登记文件、计算Fingerprint并冻结。
5. Canonical Asset Registry
每个项目维护唯一CANONICAL ASSET REGISTRY。它是ID、文件与Authority的唯一索引，不允许另建第二份可独立编辑的资产清单。
项目级字段：
[text]schema_versionproject_idregistry_snapshot_idid_policyproject_rootlast_updatedassets[]redirects[]counter_ledger
每项资产字段：
[text]canonical_revision_idasset_family_idasset_typedisplay_namestatusparent_ids[]story_scopereality_threadauthority_summaryfiles[]effective_story_timereplacement_id_or_nonecreated_from_attempt_or_none
每个文件字段：
[text]role = PRIMARY | DETAIL | MASK | SOURCEcanonical_filenamerelative_pathmedia_typesha256width / height_or_durationavailability
状态：
RESERVED：ID已占用，可作为生成Target，不能作为Reference。
CANDIDATE：已生成未确认，不能作为Reference。
CANONICAL：已冻结且文件可解析，可以作为Reference。
LOGICAL_ONLY：有Canon逻辑，无图片文件，不能占Image槽。
DEFERRED：未来需要，本次不可引用。
DEPRECATED：已失效，只保留历史与Replacement映射。
6. ID分配与冻结
任何新对象先通过Registry分配，不得在Prompt、SCSTATE或Storyboard里临时造ID。
执行：
[text]解析新对象↓检查是否已有同一Physical / Canonical Entity↓从counter_ledger保留下一编号↓建立Asset Family ID↓保留Canonical Revision ID，status=RESERVED↓生成Candidate↓确认Canonical↓登记文件与SHA-256，status=CANONICAL↓下游Reference解锁
编号一经保留不得回收。失败或删除的Candidate可以丢弃，但其已分配编号不转给另一个对象，防止历史记录串线。
同一实体不得因Scene、SEG、机位或功能名称改变而创建新ID；新ID只来自新Canonical对象、合法阶段分支、持续状态或Revision。
7. Canonical文件命名和定位
Canonical文件名必须以完整Revision ID开头：
[text]{CANONICAL_REVISION_ID}__{FILE_ROLE}.{ext}
示例：
[text]PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01__PRIMARY.pngPRJ_NOVA__PROP_SPEC_001_V01_R01__DETAIL_LABEL.png
文件夹名称不承担身份Authority；移动目录不会改变ID。Registry使用项目根目录下的规范相对路径，执行环境可以另外给出已解析绝对路径。
一个生产人员能够凭Manifest直接找到文件，Manifest必须同时给出：
[text]Exact Canonical Revision IDExact Canonical FilenameFile RoleCanonical Relative PathResolved Local Path或Asset URISHA-256短指纹Availability = VERIFIED
禁止只写“女主CT01参考图”“上一张定妆图”或仅给ID却不给文件定位。
8. Reference Resolution Gate
任何Prompt编译前执行：
[text]Requested Canonical Revision ID↓ Exact Registry LookupUnique Match?↓ Status = CANONICAL?File Role resolved?↓ Path exists / URI available?Fingerprint matches?↓ Authority and Story Scope legal?PASS → allocate Image N
所有条件通过后才能输出Prompt。禁止：
以前缀、后缀或简称搜索。
自动选择“最像”的ID。
用最新文件替代指定Revision。
用显示名称代替ID。
因文件移动而猜路径。
Reference缺失时继续输出看似完整的Prompt。
Reference Count大于0且任一Reference未解析时，本次生产调用状态必须为REFERENCE_RESOLUTION_BLOCKED。
9. Manifest与Prompt精确回显
执行Exact ID Echo Contract：
Registry中的Canonical Revision ID原样复制到Manifest。
Manifest中的ID原样复制到Prompt的Reference Role Map。
Prompt中的Target、Parent、Source CVS、SCSTATE、KF与Prop Instance字段同样从Registry/Production Registry读取。
任何ID不得人工重打、翻译、缩写或“为了简洁”省略前缀/Revision。
Image N是单次调用临时槽位，不能替代Canonical ID。
Compact Reference Identity Map
Exact ID Echo通过后，最终Prompt还必须用自然语言明确每个Image槽的语义身份。只使用六个字段，避免重复建设复杂系统：
[text]Image N = {Exact Canonical Revision ID}Who / What + Visible Content: {这是谁/是什么，以及图中实际可见内容}Story Time / Current State: {年龄/PH/LOOK/CT/事件前后/Thread}Controls: {本次有权控制的维度}Does Not Control: {本次无权控制的维度}Applicable Scope: {Target/KF/Time Window}
完整ID解决“具体是哪一份文件”，身份映射解决“模型应把图中的谁/什么理解成什么”。二者缺一不可。身份映射直接复用Registry与Manifest信息，不产生新ID、新资产或第二套Registry。
若Exact Resolution已通过，但任一Image缺少主体、当前状态或适用范围，或上传顺序与Prompt映射不一致，返回REFERENCE_MAPPING_BLOCKED。
每次调用输出：
[text]ID ECHO AUDITTarget ID exact match: PASSParent IDs exact match: PASSReference IDs exact match: PASSManifest ↔ Prompt Image map: PASSCompact Identity Map completeness: PASSUpload Order ↔ Identity Map: PASSFilename ↔ Registry ID prefix: PASSUnresolved / abbreviated IDs: 0
10. 各生产层ID合同
Asset Production
Target使用RESERVED Revision ID；Parent只使用CANONICAL Revision ID。候选图确认前不得成为下游Parent。
Continuity / CVS
active_visual_asset_id、Prop Instance、Location PR与Spatial Revision全部写完整Canonical Revision ID。禁止只写LOOK01、CT02、PR01。
SCSTATE
Source CVS、Parent SCSTATE、SLC、人物Root、Location PR、Prop SPEC/INSTANCE CT及文件Reference全部写完整Revision ID。跨Zone时每个SLC独立注册，但共享同一Source CVS、Story Time、Object Count和Spatial Revision。SCSTATE/SLC Prompt逐Image回显Who/What、当前Story Time/State与Scope。SCSTATE/SLC先注册为RESERVED，确认后再成为CANONICAL。
Storyboard
SOURCE SCSTATE SLC / CVS / VT、每个KF ID、Storyboard Package ID、Storyboard Sheet ID和Reference ID均逐字符完整。内部可以使用Image 1方便模型，但必须同一行保留对应完整ID，并说明图中是谁/是什么、当前状态和Applicable KF。
Video
Entry/Target KF、SBPKG、被选中的Anchor/SBSHEET、预编译BNDPLAN/BNDANCHOR和例外Supplemental全部使用完整Revision ID。每个Image必须说明Reference Role、可见Story Moment、Current State、独有Authority与Applicable Time Window。未被Image Materialization Gate批准的逻辑KF不得伪造图片ID。任何生成视频截图、尾帧或Frame Grab不得注册为Reference。禁止在Video Prompt里把上游ID缩成KF03、Sheet A或“上一板”。
Canonical SEG Boundary
Boundary Plan与可选Anchor均在相邻两条视频生产前由上游Canon建立：
[text]PRJ_NOVA__BNDPLAN_EP01_SEG01_TO_SEG02_R01PRJ_NOVA__BNDANCHOR_EP01_SEG01_TO_SEG02_OUT_R01PRJ_NOVA__BNDANCHOR_EP01_SEG01_TO_SEG02_IN_R01
BNDPLAN记录Source/Target SEG、Story Time、Source/Target CVS、Boundary Mode、完成动作/对白/状态、World Position、LOOK/CT、Location/Spatial、Prop/Count/Holder及Exit/Entry Shot合同。BNDANCHOR记录Source Canonical References、Fingerprint、OUT/IN角色和Applicable SEG Window。两者不得引用Source Video Revision或Frame Time；若来源是视频输出，返回GENERATED_FRAME_REFERENCE_FORBIDDEN。
File Handoff
每一项交付都附Asset Pickup Card：
[text]Display NameExact Canonical Revision IDExact FilenameRelative / Resolved PathFile RoleFingerprintUsed As Image NApplicable Scope
11. 状态与修订规则
Canonical Revision内容不可覆盖修改。需要修正时：
[text]Family ID unchangedR01 remains immutablenew file → R02Registry marks R01 DEPRECATED或仍合法于旧Scopereplacement_id = exact R02 ID
下游不会自动跳到R02。任何Replacement必须列出Affected Scope并重新编译所有受影响Manifest、SCSTATE、Storyboard和Video Prompt。
同一Revision ID的SHA-256变化属于非法覆盖，必须阻断生产。文件仅移动时，ID和SHA-256不变，只更新Registry path并生成新Snapshot。
12. 旧项目迁移
禁止在同一生产包中混用Legacy短ID与FQID。
执行一次性迁移：
[text]冻结旧资产清单↓为每个旧ID解析唯一Physical / Canonical Entity↓分配PROJECT_ID命名空间和Revision↓建立old_exact_id → new_exact_revision_id映射↓重命名或登记真实文件↓更新全部下游引用↓执行Dangling Reference Audit↓冻结Registry Snapshot
Redirect只服务迁移审计，不得在生产时把旧简称静默转成新ID。发现旧ID时输出LEGACY_ID_NOT_ALLOWED，要求使用Registry中的新Revision ID。
13. 错误处理
错误码：
Code
含义
处理
ID_NOT_FOUND
Registry无完全匹配
阻断，不猜测
ID_ABBREVIATED
使用简称或漏层级
阻断，返回完整ID
ID_DUPLICATE
同一ID多条记录
冻结Registry修复
FILE_NOT_FOUND
登记文件不可用
阻断，修复路径/文件
FILE_ID_MISMATCH
文件名不以Revision ID开头
重命名或重新登记
HASH_MISMATCH
Canonical文件被覆盖
创建新Revision并回编
STATUS_NOT_CANONICAL
Candidate等被引用
完成Promotion或更换Reference
REVISION_SUPERSEDED
引用了已替换版本
按Scope显式选择并回编
AUTHORITY_SCOPE_MISMATCH
文件存在但无当前Authority
选择合法Reference
MULTIPLE_MATCHES
Registry非唯一
阻断并修复主键
REFERENCE_MAPPING_BLOCKED
Image身份、当前状态、范围或上传顺序映射不完整
补齐六字段紧凑映射后重新编译

可列出人工检查候选，但任何候选都不得自动进入Image槽或Prompt。
14. 交付模板
[text]【REGISTRY SNAPSHOT】Project ID: {exact_project_id}Registry Snapshot ID: {exact_snapshot_id}ID Policy: FQID + CANONICAL REVISION REQUIRED【PRODUCTION TARGET RESOLUTION】Display Name: {human_name}Asset Family ID: {exact_family_id}Canonical Revision ID: {exact_target_revision_id}Status: RESERVED | CANONICAL【REFERENCE RESOLUTION MANIFEST】Image 1Display Name: {human_name}Exact Canonical Revision ID: {exact_reference_revision_id}Exact Filename: {exact_filename}File Role: PRIMARYCanonical Relative Path: {path}Resolved Local Path / URI: {path_or_uri}SHA-256: {fingerprint}Availability: VERIFIEDAuthority Type: {authority}Applicable Scope: {scope}【COMPACT REFERENCE IDENTITY MAP】Image 1 = {exact_reference_revision_id}Who / What + Visible Content: {identity_and_visible_content}Story Time / Current State: {story_time_and_state}Controls: {authority}Does Not Control: {excluded_dimensions}Applicable Scope: {scope}【RESOLUTION RESULT】Unique ID Match: PASSCanonical Status: PASSFile Availability: PASSFingerprint: PASSAuthority Scope: PASSAbbreviated IDs: 0Production Prompt Release: ALLOWED
15. 硬规则与审计
十六条硬规则
ID只能由Canonical Asset Registry分配。
新项目使用PROJECT命名空间的Fully Qualified ID。
Production Reference只使用Canonical Revision ID。
ID逐字符匹配并区分大小写。
禁止缩写、别名、翻译、漏前缀和漏Revision。
显示名称不得进入ID字段。
Image N不能替代Canonical ID。
Candidate和Reserved资产不能作为Reference。
一个Revision ID只能对应一个不可变Canonical版本。
Canonical文件名必须以完整Revision ID开头。
Reference必须解析到真实文件角色、路径和Fingerprint。
查不到、查到多个或Fingerprint变化时立即阻断。
Revision替换必须显式回编受影响下游。
Legacy ID迁移后不得继续进入生产包。
交付前必须通过Dangling、Duplicate、Abbreviation和Echo Audit。
每个Image槽必须同时拥有完整ID与六字段语义身份映射；缺失时阻断，不让模型猜。
交付审计
[ ] Project ID、Registry Snapshot和ID Policy已冻结。
[ ] 每个Family ID、Revision ID和真实文件是一对一可解析关系。
[ ] 所有Target已预留，所有Reference状态为CANONICAL。
[ ] Parent、Source CVS、SCSTATE、KF、SBPKG和Prop Instance均使用完整Revision ID。
[ ] 没有CT01、LOOK01、KF03、“女主状态图”等替代正式ID。
[ ] Manifest给出精确文件名、路径、角色、Fingerprint和Availability。
[ ] Manifest与Prompt中的ID和Image编号完全一致。
[ ] 每个Image槽的Who/What、Visible Content、Story Time/Current State、Controls、Does Not Control和Applicable Scope已完整回显。
[ ] Upload Order与Compact Reference Identity Map逐项一致，缺失时返回REFERENCE_MAPPING_BLOCKED。
[ ] 没有Dangling Reference、Duplicate ID、Orphan Canonical File或Silent Redirect。
[ ] 任何Reference Resolution失败都会阻断，而不是猜测继续。
