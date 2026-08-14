# Canonical ID注册表与参考资产解析

## 目录

1. 问题定义与最高规则
2. 唯一ID模型
3. ID语法与命名空间
4. Family ID、Revision ID与Attempt
5. Canonical Asset Registry
6. ID分配与冻结
7. Canonical文件命名和定位
8. Reference Resolution Gate
9. Manifest与Prompt精确回显
10. 各生产层ID合同
11. 状态与修订规则
12. 旧项目迁移
13. 错误处理
14. 交付模板
15. 硬规则与审计

## 1. 问题定义与最高规则

正式定义：

```text
Canonical ID Drift
= 缩写
+ 改写
+ 大小写变化
+ 漏层级
+ 漏版本
+ 别名替代
+ 模糊匹配
+ ID与真实文件脱钩
```

最高规则：

> Canonical ID是不可改写的机器主键，不是方便阅读的名称。

一旦注册，所有层必须逐字符复用同一个完整ID。禁止把：

```text
PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01
```

写成：

```text
CT01
女主CT01
CHAR_001_CT01
PH01_LK01_CT01
CHAR1_LOOK1_STATE1
```

显示名称可写“女主雨夜受伤状态”，但显示名称只能进入`display_name`，不能替代任何ID字段。

## 2. 唯一ID模型

维护两层ID：

```text
ASSET FAMILY ID
= 稳定语义对象

CANONICAL REVISION ID
= 某个不可变Canonical版本
```

生产Reference、Parent、CVS绑定、SCSTATE、KF、Storyboard和Video必须使用`CANONICAL REVISION ID`。Family ID只用于注册表分组、查修订历史和分配下一个Revision，不能直接指向一张生产参考图。

一个Canonical Revision ID只能对应一个明确资产版本；一个Canonical文件只能归属于一个Canonical Revision ID。不得一ID多图、多ID一图或同ID覆盖保存。

## 3. ID语法与命名空间

新项目使用Fully Qualified ID：

```text
{PROJECT_ID}__{OBJECT_PATH}_R{NN}
```

规则：

- `PROJECT_ID`：`PRJ_`加3至16位大写ASCII字母或数字。
- 命名空间分隔符固定为双下划线`__`。
- `OBJECT_PATH`只使用大写ASCII、数字和单下划线。
- Revision固定为两位起步：`R01`、`R02`；超过99时扩为三位并全项目统一。
- ID区分大小写；生产时执行Exact String Match。
- 禁止空格、中文、连字符、斜杠、括号、模糊编号和未补零数字。

示例：

```text
PRJ_NOVA__CHAR_001_R01
PRJ_NOVA__CHAR_001_PH01_R01
PRJ_NOVA__COST_001_R01
PRJ_NOVA__CHAR_001_PH01_LK01_R01
PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01
PRJ_NOVA__LOC_001_R01
PRJ_NOVA__LOC_001_PR01_R01
PRJ_NOVA__SPATIAL_001_R01
PRJ_NOVA__PROP_SPEC_001_V01_R01
PRJ_NOVA__PROP_INST_001_R01
PRJ_NOVA__SCSTATE_EP01_SC03_ST01_R01
PRJ_NOVA__SBPKG_EP01_SEG01_R01
```

注意：`V01`表示故事/设计层面的合法规格版本；末尾`R01`表示该资产的不可变Canonical修订。两者不得混用。

## 4. Family ID、Revision ID与Attempt

### Asset Family ID

```text
PRJ_NOVA__CHAR_001_PH01_LK01_CT01
```

表示“这个Canonical对象是什么”，不绑定具体文件。

### Canonical Revision ID

```text
PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01
```

表示“当前被批准的具体不可变版本”，生产Reference只使用它。

### Candidate Attempt

```text
PRJ_NOVA__CHAR_001_PH01_LK01_CT01__TRY_003.png
```

Attempt不是Canon，不进入Reference Manifest，不拥有Canonical Revision ID Authority。用户或生产体系确认后，另存为：

```text
PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01__PRIMARY.png
```

禁止把`TRY_003`直接改写成`R01`并覆盖旧文件；必须执行Promotion、登记文件、计算Fingerprint并冻结。

## 5. Canonical Asset Registry

每个项目维护唯一`CANONICAL ASSET REGISTRY`。它是ID、文件与Authority的唯一索引，不允许另建第二份可独立编辑的资产清单。

项目级字段：

```text
schema_version
project_id
registry_snapshot_id
id_policy
project_root
last_updated
assets[]
redirects[]
counter_ledger
```

每项资产字段：

```text
canonical_revision_id
asset_family_id
asset_type
display_name
status
parent_ids[]
story_scope
reality_thread
authority_summary
files[]
effective_story_time
replacement_id_or_none
created_from_attempt_or_none
```

每个文件字段：

```text
role = PRIMARY | DETAIL | MASK | SOURCE
canonical_filename
relative_path
media_type
sha256
width / height_or_duration
availability
```

状态：

- `RESERVED`：ID已占用，可作为生成Target，不能作为Reference。
- `CANDIDATE`：已生成未确认，不能作为Reference。
- `CANONICAL`：已冻结且文件可解析，可以作为Reference。
- `LOGICAL_ONLY`：有Canon逻辑，无图片文件，不能占Image槽。
- `DEFERRED`：未来需要，本次不可引用。
- `DEPRECATED`：已失效，只保留历史与Replacement映射。

## 6. ID分配与冻结

任何新对象先通过Registry分配，不得在Prompt、SCSTATE或Storyboard里临时造ID。

执行：

```text
解析新对象
↓
检查是否已有同一Physical / Canonical Entity
↓
从counter_ledger保留下一编号
↓
建立Asset Family ID
↓
保留Canonical Revision ID，status=RESERVED
↓
生成Candidate
↓
确认Canonical
↓
登记文件与SHA-256，status=CANONICAL
↓
下游Reference解锁
```

编号一经保留不得回收。失败或删除的Candidate可以丢弃，但其已分配编号不转给另一个对象，防止历史记录串线。

同一实体不得因Scene、SEG、机位或功能名称改变而创建新ID；新ID只来自新Canonical对象、合法阶段分支、持续状态或Revision。

## 7. Canonical文件命名和定位

Canonical文件名必须以完整Revision ID开头：

```text
{CANONICAL_REVISION_ID}__{FILE_ROLE}.{ext}
```

示例：

```text
PRJ_NOVA__CHAR_001_PH01_LK01_CT01_R01__PRIMARY.png
PRJ_NOVA__PROP_SPEC_001_V01_R01__DETAIL_LABEL.png
```

文件夹名称不承担身份Authority；移动目录不会改变ID。Registry使用项目根目录下的规范相对路径，执行环境可以另外给出已解析绝对路径。

一个生产人员能够凭Manifest直接找到文件，Manifest必须同时给出：

```text
Exact Canonical Revision ID
Exact Canonical Filename
File Role
Canonical Relative Path
Resolved Local Path或Asset URI
SHA-256短指纹
Availability = VERIFIED
```

禁止只写“女主CT01参考图”“上一张定妆图”或仅给ID却不给文件定位。

## 8. Reference Resolution Gate

任何Prompt编译前执行：

```text
Requested Canonical Revision ID
↓ Exact Registry Lookup
Unique Match?
↓ Status = CANONICAL?
File Role resolved?
↓ Path exists / URI available?
Fingerprint matches?
↓ Authority and Story Scope legal?
PASS → allocate Image N
```

所有条件通过后才能输出Prompt。禁止：

- 以前缀、后缀或简称搜索。
- 自动选择“最像”的ID。
- 用最新文件替代指定Revision。
- 用显示名称代替ID。
- 因文件移动而猜路径。
- Reference缺失时继续输出看似完整的Prompt。

Reference Count大于0且任一Reference未解析时，本次生产调用状态必须为`REFERENCE_RESOLUTION_BLOCKED`。

## 9. Manifest与Prompt精确回显

执行`Exact ID Echo Contract`：

1. Registry中的Canonical Revision ID原样复制到Manifest。
2. Manifest中的ID原样复制到Prompt的Reference Role Map。
3. Prompt中的Target、Parent、Source CVS、SCSTATE、KF与Prop Instance字段同样从Registry/Production Registry读取。
4. 任何ID不得人工重打、翻译、缩写或“为了简洁”省略前缀/Revision。
5. Image N是单次调用临时槽位，不能替代Canonical ID。

每次调用输出：

```text
ID ECHO AUDIT
Target ID exact match: PASS
Parent IDs exact match: PASS
Reference IDs exact match: PASS
Manifest ↔ Prompt Image map: PASS
Filename ↔ Registry ID prefix: PASS
Unresolved / abbreviated IDs: 0
```

## 10. 各生产层ID合同

### Asset Production

Target使用`RESERVED` Revision ID；Parent只使用`CANONICAL` Revision ID。候选图确认前不得成为下游Parent。

### Continuity / CVS

`active_visual_asset_id`、Prop Instance、Location PR与Spatial Revision全部写完整Canonical Revision ID。禁止只写`LOOK01`、`CT02`、`PR01`。

### SCSTATE

Source CVS、人物Root、Location PR、Prop SPEC/INSTANCE CT及文件Reference全部写完整Revision ID。SCSTATE本身也先注册为RESERVED，确认后再成为CANONICAL。

### Storyboard

`SOURCE SCSTATE / CVS / VT`、每个KF ID、Storyboard Package ID和Reference ID均逐字符完整。内部可以使用`Image 1`方便模型，但必须同一行保留对应完整ID。

### Video

Entry/Target KF、SBPKG、人物CT、Prop Instance和所有补充Reference使用完整Revision ID。禁止在Video Prompt里把上游ID缩成`KF03`、`CT01`或“上一板”。

### File Handoff

每一项交付都附`Asset Pickup Card`：

```text
Display Name
Exact Canonical Revision ID
Exact Filename
Relative / Resolved Path
File Role
Fingerprint
Used As Image N
Applicable Scope
```

## 11. 状态与修订规则

Canonical Revision内容不可覆盖修改。需要修正时：

```text
Family ID unchanged
R01 remains immutable
new file → R02
Registry marks R01 DEPRECATED或仍合法于旧Scope
replacement_id = exact R02 ID
```

下游不会自动跳到R02。任何Replacement必须列出Affected Scope并重新编译所有受影响Manifest、SCSTATE、Storyboard和Video Prompt。

同一Revision ID的SHA-256变化属于非法覆盖，必须阻断生产。文件仅移动时，ID和SHA-256不变，只更新Registry path并生成新Snapshot。

## 12. 旧项目迁移

禁止在同一生产包中混用Legacy短ID与FQID。

执行一次性迁移：

```text
冻结旧资产清单
↓
为每个旧ID解析唯一Physical / Canonical Entity
↓
分配PROJECT_ID命名空间和Revision
↓
建立old_exact_id → new_exact_revision_id映射
↓
重命名或登记真实文件
↓
更新全部下游引用
↓
执行Dangling Reference Audit
↓
冻结Registry Snapshot
```

Redirect只服务迁移审计，不得在生产时把旧简称静默转成新ID。发现旧ID时输出`LEGACY_ID_NOT_ALLOWED`，要求使用Registry中的新Revision ID。

## 13. 错误处理

错误码：

| Code | 含义 | 处理 |
|---|---|---|
| ID_NOT_FOUND | Registry无完全匹配 | 阻断，不猜测 |
| ID_ABBREVIATED | 使用简称或漏层级 | 阻断，返回完整ID |
| ID_DUPLICATE | 同一ID多条记录 | 冻结Registry修复 |
| FILE_NOT_FOUND | 登记文件不可用 | 阻断，修复路径/文件 |
| FILE_ID_MISMATCH | 文件名不以Revision ID开头 | 重命名或重新登记 |
| HASH_MISMATCH | Canonical文件被覆盖 | 创建新Revision并回编 |
| STATUS_NOT_CANONICAL | Candidate等被引用 | 完成Promotion或更换Reference |
| REVISION_SUPERSEDED | 引用了已替换版本 | 按Scope显式选择并回编 |
| AUTHORITY_SCOPE_MISMATCH | 文件存在但无当前Authority | 选择合法Reference |
| MULTIPLE_MATCHES | Registry非唯一 | 阻断并修复主键 |

可列出人工检查候选，但任何候选都不得自动进入Image槽或Prompt。

## 14. 交付模板

```text
【REGISTRY SNAPSHOT】
Project ID: {exact_project_id}
Registry Snapshot ID: {exact_snapshot_id}
ID Policy: FQID + CANONICAL REVISION REQUIRED

【PRODUCTION TARGET RESOLUTION】
Display Name: {human_name}
Asset Family ID: {exact_family_id}
Canonical Revision ID: {exact_target_revision_id}
Status: RESERVED | CANONICAL

【REFERENCE RESOLUTION MANIFEST】
Image 1
Display Name: {human_name}
Exact Canonical Revision ID: {exact_reference_revision_id}
Exact Filename: {exact_filename}
File Role: PRIMARY
Canonical Relative Path: {path}
Resolved Local Path / URI: {path_or_uri}
SHA-256: {fingerprint}
Availability: VERIFIED
Authority Type: {authority}
Applicable Scope: {scope}

【RESOLUTION RESULT】
Unique ID Match: PASS
Canonical Status: PASS
File Availability: PASS
Fingerprint: PASS
Authority Scope: PASS
Abbreviated IDs: 0
Production Prompt Release: ALLOWED
```

## 15. 硬规则与审计

### 十五条硬规则

1. ID只能由Canonical Asset Registry分配。
2. 新项目使用PROJECT命名空间的Fully Qualified ID。
3. Production Reference只使用Canonical Revision ID。
4. ID逐字符匹配并区分大小写。
5. 禁止缩写、别名、翻译、漏前缀和漏Revision。
6. 显示名称不得进入ID字段。
7. Image N不能替代Canonical ID。
8. Candidate和Reserved资产不能作为Reference。
9. 一个Revision ID只能对应一个不可变Canonical版本。
10. Canonical文件名必须以完整Revision ID开头。
11. Reference必须解析到真实文件角色、路径和Fingerprint。
12. 查不到、查到多个或Fingerprint变化时立即阻断。
13. Revision替换必须显式回编受影响下游。
14. Legacy ID迁移后不得继续进入生产包。
15. 交付前必须通过Dangling、Duplicate、Abbreviation和Echo Audit。

### 交付审计

- [ ] Project ID、Registry Snapshot和ID Policy已冻结。
- [ ] 每个Family ID、Revision ID和真实文件是一对一可解析关系。
- [ ] 所有Target已预留，所有Reference状态为CANONICAL。
- [ ] Parent、Source CVS、SCSTATE、KF、SBPKG和Prop Instance均使用完整Revision ID。
- [ ] 没有`CT01`、`LOOK01`、`KF03`、“女主状态图”等替代正式ID。
- [ ] Manifest给出精确文件名、路径、角色、Fingerprint和Availability。
- [ ] Manifest与Prompt中的ID和Image编号完全一致。
- [ ] 没有Dangling Reference、Duplicate ID、Orphan Canonical File或Silent Redirect。
- [ ] 任何Reference Resolution失败都会阻断，而不是猜测继续。
