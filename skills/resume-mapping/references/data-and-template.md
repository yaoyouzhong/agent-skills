# 数据与目标模板映射

> 本文件描述可选脚本实现的格式和契约，仅在宿主已有对应运行环境并选择这些工具时使用。默认先按 [宿主文档流程](host-workflow.md) 执行，不要求用户安装额外软件，也不把本文件的 JSON/命令设为原生文档工具的必经步骤。

## 结构化数据

`fields` 保存本次简历的全部业务字段，可按用户模板增减。其它顶层字段是来源/审计元数据。建议教育、项目字段遵循以下命名，以便确定性规则脚本处理；按原件填值，不从此示例复制事实。

目标模板允许部分填写。来源没有的字段用空字符串，整类经历未提供时可用空数组；不添加假经历来填满示例行。执行 Agent 阅读现有来源后，将正常缺失标为 `not_provided` 并说明原因即可，不要求用户逐字段补充或确认。识别失败和真实歧义分别保留 `extraction_failed/needs_review`，不能降成普通缺失。内部元数据和空值原因不写进客户简历。

```json
{
  "processing_date": "2026-10-20",
  "people": [
    {
      "id": "p001",
      "source_ids": ["s0001"],
      "fields": {
        "meta": {"name": "示例人员", "level": "", "degree": ""},
        "education": [
          {"start": "2012", "end": "2016", "school": "示例学校", "major": "软件工程", "level": "本科", "degree": "", "status": "completed"}
        ],
        "skills": "保留原文技能描述。",
        "projects": [
          {"name": "客户服务平台", "start": "2022.03", "end": "2024.01", "client": "", "desc": "为示例银行建设客户服务平台。", "tech": "Java", "resp": "保留职责、成果和编号。"}
        ]
      },
      "evidence": [
        {"field": "education[0].school", "source_quotes": [{"source_id": "s0001", "unit_id": "u-actual-id", "locator": "page 1 / 教育经历", "quote": "原件中对应的完整文字单元"}]}
      ]
    }
  ],
  "source_reviews": {},
  "excluded_sources": {}
}
```

- `source_ids` 连接提取清单；同一来源可有多个人，同一人可有多个来源。
- `education[].status` 为 `completed`、`in_progress`、`incomplete`、`unknown`。不能仅凭日期已过去就填 `completed`；来源履历和毕业证/明确毕业表述等证据能确认时可填写。未知状态要复核。
- `processing_date` 使用本次任务实际日期，示例日期不能复制到后续任务。校验日期不修改原文精度；年份/月份都按区间比较，日期交叠不强行排序。
- 每一条教育经历保存自身学历和学位；`fields.meta.level/degree` 由规则脚本选最近已毕业记录后派生。在读、未毕业记录不能用于摘要。
- `fields` 中非空字段都须映射或有本次授权的省略理由；教育状态 `status` 是内部选择元数据，可不显示。来源定位、质量告警、字段变更日志放在 `fields` 外，避免误写入客户简历。
- 如果用户要求不展示在读经历，可保留在 `retained_records` 等审计元数据中，不放入用于输出的 `fields.education`；应在教育选择之前保留证据，不能删除原件。
- 客户补全候选依据必须来自对应项目，不能拿原简历里别的项目给本项目补客户。

### 毕业状态依据

原文在同一教育行明确写了授予学位，且有学校与学位的精确引用时，可按 `source_declared_awarded_degree` 认定来源声明已毕业，仍不是独立学历认证。原始学位与 `user_default` 必须分开；同一文件另一教育行的学位无效，大专异常学位不构成毕业依据。

其它毕业依据放在人员 `education_status_evidence["education[0]"]`：`record_sha256` 必须用 `record_checks.education_binding(record)` 计算，`basis` 为 `explicit_source`、`credential_review`、`source_declared_graduation_date` 或 `user_confirmation`。来源依据需 `source_quotes`（来源单元全文，不是自造摘录）；毕业时间字段须按复核回读参考绑定同记录的学校、标签和对应日期。`credential_review` 还需 `reviewer`、`asset_sha256`、`owner_verified: true`，图片须先实际查看并接入已复核媒体单元。`user_confirmation` 需真实确认的 `reviewer`、`reason`、`confirmation_reference`，Agent 不能为消除待核项虚构用户确认。

学校、专业、学历、日期或状态变化后，旧状态证明失效。学位不在记录指纹中，避免默认补出的值反过来成为完成依据；证书本身的引用与图片哈希仍须一致。

真实原文中的肯定获奖表述（如同一教育段“曾获优秀毕业生”）可作为明确毕业语义，须由执行 Agent 先核对归属，并用 `record_sources["education[0]"]` 绑定该段的 `source_id/unit_ids`。提名、候选、否定、其它教育段或普通奖学金不能代替已经毕业。此处只是定位已有毕业语义，不改变最近已毕业的选择规则。

### 实际空项复核

`people[].blank_reviews` 为内部记录，键是字段路径。每项至少含 `classification`、`reason` 和实际复核人 `reviewer`；分类为 `source_not_provided`、`insufficient`、`unreadable`、`intentional_rule`、`already_represented` 或 `available_but_missed`。存在相关原文时保存精确 `source_quotes`；全文确无该信息时保存本次读取的来源和范围，不伪造“缺失”的原文。可补项完成后记录 `resolution: filled`，再运行 `fill_coverage.py`。它优先采用此次复核结论，不把证据不足说成来源未提供。

日期规范化只跟随原本有效的证明和覆盖快照。`stale_before_date_normalization` 表示规范前已失效，即使规范后碰巧与旧值或哈希相同仍须重新复核，不能直接清除标记来声称有效。

## DOCX 映射

模板由用户指定；下面只是映射格式示例，索引不适用于任意模板。先运行 `inspect`，表格、行、真实单元格和段落均从 0 计数。合并单元格按 OOXML 中真实 `w:tc` 计数，不用 `python-docx row.cells` 展开的重复列号。

```json
{
  "page_break_between_people": true,
  "paragraphs": [],
  "tables": [
    {
      "index": 0,
      "fields": [
        {"row": 0, "cell": 1, "key": "meta.name"},
        {"row": 1, "cell": 1, "key": "meta.level"},
        {"row": 2, "cell": 1, "key": "meta.degree"}
      ],
      "repeat": [
        {
          "key": "projects",
          "rows": [4, 5],
          "fields": [
            {"row": 0, "cell": 0, "text": "项目经历{index}"},
            {"row": 0, "cell": 1, "key": "name"},
            {"row": 1, "cell": 1, "keys": ["desc", "tech", "resp"], "separator": "\n"}
          ]
        }
      ],
      "omit_rows": []
    }
  ],
  "omit_fields": {}
}
```

### 映射语义

- `paragraphs` 绑定正文直接子段落：`{"index": 0, "key": "meta.name"}`。不包括表格内段落。当前模板中的全部正文段落/表格将按人复制，唯一的最终 `sectPr` 保留一次。
- `tables[].index` 是正文直接子表格索引；可映射多个不同的表格。没有映射的固定文本仍保留，必须检查是否有示例人名/占位提示未清除。
- `fields` 指向原模板中固定行和单元格；`key` 相对于整个人的 `fields`。
- `repeat` 选择原模板闭区间 `[起始行, 结束行]`，按数组记录完整克隆。重复区的 `row` 从区间首行算起，`key` 相对于该条记录。`{index}` 从 1 开始编号。区间不可交叠；不要留下旧的第二/第三项目示例块。
- Word 与 Excel 的 `repeat.key: projects` 默认 `order: start_desc`，按开始日期从近到远显示；先满足日期可确定的先后关系，其余候选按来源原序优先，缺失/无效开始日期稳定排后。排序仅改变显示位置和编号，字段覆盖仍指向原始数组索引，整条及其续行一起移动。其它集合默认保留来源顺序；用户指定来源顺序时显式 `order: source`。不把进行中无条件置顶，不用结束日期冒充缺失开始日期。
- 多段教育放同一框分行时，Word 可在单行、单物理单元格的重复区设置 `combine_records: true`。每条按该绑定生成独立段落，合入同一个模板单元格，沿用其字体字号和边框；不能与多单元格或项目续行混用。较长经历自然换行，不截断内容。教育字段来源仍按每条原记录索引追溯，不能把学校、专业和学位跨记录拼接。
- `omit_rows` 删除明确的冗余空白/示例行，索引仍相对于原模板。不能和重复区或静态字段冲突。
- `keys` 可将多个字段用 `separator` 合并到一个已有单元格，保留模板没有独立列的职责、角色等信息。不要把整段 JSON 塞进一个字段。
- `key_labels` 可为同格的各个非空值添加语义前缀，例如 `{"start":"开始：","end":"结束："}`。单端日期或字段缺失时仍能看清剩余值属于哪一项；不会输出缺失值或自动补日期。标签仅可指向该绑定的 keys。
- 正文段落也可绑定 `education[0].school` 等明确标量路径。任务生成映射时按实际记录数建立段落；不要硬编码固定人数/经历条数。
- 文本替换保留该单元格/段落首个段落及文字格式，不改全局字体字号。长文本必须通过实际渲染检查。复杂行内样式、纵向合并横跨重复块、嵌套表格需要任务内适配。
- `remove_floating: true` 可在明确需要顺序汇编时取消该表的浮动定位；默认不改。其它几何修复按当前模板实际问题进行，不继承其它模板的特定缩进和列宽。
- `omit_fields` 是 `{字段路径模式: 本次明确省略理由}`，如用户要求教育表不单独显示学位，可用精确路径或 `education[].degree`，并说明真实理由。它不能代替用户授权省略内容。不要使用 `*` 一次性掩盖所有遗漏。
- `page_break_between_people` 必须显式填写，按本次要求决定；对每人重复完整模板不符合需求时（如“一页多人名单”），另写任务适配。

单个来源、表格行数和项目数都不固定。示例中的业务字段只说明 schema，**示例映射没有覆盖整份示例数据**，不能直接执行后绕过未映射字段错误。依据真实模板完成所有字段映射再构建。

### 长文本与分页适配

映射可显式设置 widow_control（布尔值），以及 tables[].keep_with_next_rows（原始行号）。repeat 内的 keep_with_next_rows/cant_split_rows 使用块内行号；keep_lines_cells 为 `{row,cell}` 列表。按实际页图选择短标题/技术行，不把全部长职责设为禁止跨页。

任职职责等长文本不宜塞进狭窄职务列。repeat.trailing_rows 可从本表任意真实行 `[start,end]` 克隆附加行，when_nonempty 指定记录字段，fields 与普通重复绑定相同；例如使用当前模板的全宽正文行承载 details。绑定的 prefix 仅在字段非空时添加说明。附加行样式来自当前模板，不固定某份模板的行号。人物分页使用段前分页，避免独立硬分页符产生空白页。所有适配仍需重新渲染验证。

`compact_empty_body_paragraphs: true` 可在逐人段前分页时压缩模板表格外的空段落，并移除两人之间多余空段落；最终表后必要空段落仍保留。只在实测出现空白页时使用，不修改表格内容。跨页单元格的渲染核对仅接受相邻页末行/首行的连续文本，且中间穿插文字必须是同一记录的其他字段；检查报告单列这些续接，仍需目视确认。
