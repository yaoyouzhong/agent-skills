# 提取、审计与复核

此参考用于来源质量、字段证据及批量回归；命令使用当前运行时解析的 `PYTHON`、`SKILL` 和新建任务目录 `TASK`。

## 来源质量与原文完整度

PDF 提取保留 raw_text、clean_text、删除字符及坐标日志；水印判断结合旋转、重复串、字体/颜色和边缘位置，不能按浅灰色或固定字体整批删除。页面字符收支应相等。页眉、页码、栏目标签与业务正文分别记录。多栏阅读顺序、空文本页、替换字形等会告警；必要时用 `--pdf-order-map TASK/order.json` 指定每页列范围和复核理由，重新提取到新目录。保留原始证据。

`source_audit.py` 从每个原文单元反查结构化字段，可发现进入 JSON 前的遗漏。单元是 PDF 文字行/表格单元格行、Word 块、Excel 单元格等，并有稳定 ID；不能只检查“JSON 中的文本有没有进 Word”。字符覆盖是候选筛查，不是语义正确性的证明。

文字提取层本身可能漏掉原件上可见的文字。任职已有日期、岗位和工作内容却缺单位，或其它关键标签和值疑似断开时，回看该记录所在原页，不能仅凭提取结果没有文字就判为未提供。确需使用图中事实时，按本参考的图片证据接口接入已看图转录；不因此要求对已齐全的证照照片做 OCR。

多栏和粗体文字还可能全部进入提取，却在行内先后顺序上出错。全文引用前检查实际阅读顺序；需要按坐标重组时保留原始提取、对应范围与字符收支依据，单独标注被剥离的侧栏或章节标签。最后对照目标独立栏核对项目全名、客户、角色等，不能用正文或其它信息中出现过该词代替对应栏填写，也不能将整句完整度通过当成语序或归属正确。

```text
PYTHON SKILL/scripts/record_evidence.py --data TASK/reviewed-data.json --sources TASK/extracted/sources.json --out TASK/located-data.json --report TASK/record-evidence.json
PYTHON SKILL/scripts/apply_policies.py --data TASK/located-data.json --sources TASK/extracted/sources.json --out TASK/policy-data.json --audit TASK/policy-audit.json
PYTHON SKILL/scripts/field_facts.py --data TASK/policy-data.json --sources TASK/extracted/sources.json --decisions TASK/fact-decisions.json --out TASK/fact-data.json --report TASK/fact-report.json
PYTHON SKILL/scripts/source_audit.py --data TASK/fact-data.json --sources TASK/extracted/sources.json --out TASK/source-audit.json
```

客户候选在 apply_policies 额外传 `--clients`；没有候选可省略。`field_facts --decisions` 也可省略，首次运行先发现待复核字段。每次用新产物路径，修改字段后重新定位/分类/审计，不能套用旧报告。

## 项目定位

`record_sources["projects[0]"]` 记录来源、标题 anchor、范围内 unit_ids、页码。定位器支持跨行名称、表格日期/名称行及章节边界。逐项目核查定位，尤其是整页容器表格、双语标题、侧栏标题、任职和项目交织的版式。

无法自动定位时在 `anchor_overrides` 按记录路径提供 source_id/unit_id/quote/reason；不能用任意扩大范围解决未匹配。标题唯一不代表项目范围正确。字段引用必须属于对应记录；相同的日期/技术不能借用相邻项目或教育经历来证明。

## 字段事实

`field_facts` 区分 source_direct、source_assembled、source_inferred、user_default、source_selected、intentionally_blank、not_provided、needs_review、extraction_failed。默认学位不能冒充直接提取；原文简称不自动扩全称；未知毕业状态保留原学历但不参与已毕业汇总。

复核决策以 `person_id:field_path` 为键，包含 origin/reason/reviewed_value/source_quotes。引用格式为 `{source_id,unit_id,quote}`，quote 必须等于原始单元。推断说明推断规则和证据；若使用文件名级别，应区分来源元数据与正文事实，并检查是否冲突。执行 Agent 阅读现有来源后，可以将确实没有明确值的空字段标为 `not_provided` 并说明原因，无需用户逐项确认；不清晰的客户保持空并写具体原因。缺页/识别失败不能标为未提供。

核对用于保证已有信息准确落入目标字段，不用于要求模板全部填满。正常缺失不属于待补齐任务；默认向用户交付简历与少量必要提示，完整队列保存在任务证据中或在用户要求时提供。实际存在而漏提取、错误归属、错列、未经依据补值及截断仍必须处理。普通空值不能成为开启证照审验或强制 OCR 的理由。

## 原文候选关闭

`coverage_decisions` 按 `source_id:unit_id` 保存完整 quote、reason 和 disposition：

- `represented_equivalently`：person_id、field_paths、field_values（复核时的实际值快照）。仅能在确实等价时使用，不以项目名/证书名代替具体职责/能力/荣誉。
- `excluded_by_user`：authority 写本次有效的省略指令。混合行须保留其中的业务事实，不能整行排除。
- `source_label` / `non_resume_content`：具体说明栏目、排版或非简历内容，不能隐藏实际遗漏。

未分类的原文差异始终阻止 DOCX 构建。明确矛盾用 source_conflicts 保留 ID、reason、source_quotes；coverage_decisions 可用 retained_conflict 并引用 conflict_id。审计仍返回 needs_review，不能算通过。只有显式 output_mode=candidate 且全部剩余问题均为 retained_conflict 时，才允许生成供复核的候选文档；正式输出仍被阻止。已通过报告绑定整个数据、原件、提取证据和审计代码；任何变更均需重新运行。source_reviews 对质量告警保存 status(passed/pending)/reason/source_sha256/detail_sha256，不能只写“已处理”。

## 渲染与版本闭环

增量核对可沿用同值、同来源哈希且精确引文仍在对应记录范围内的已审事实；每次仍验证引文和项目边界，毕业/日期门禁重新执行。不能把已审字段重新交给宽松匹配而丢掉既有精确证据，也不能将旧默认值当源事实。

```text
PYTHON SKILL/scripts/check_rendered.py --data TASK/fact-data.json --map TASK/template-map.json --render TASK/render/render.json --out TASK/render-check.json
PYTHON SKILL/scripts/review_ledger.py create --files TASK/review-files.json --visual TASK/visual-review.json --out TASK/review-receipt.json
PYTHON SKILL/scripts/review_ledger.py check --receipt TASK/review-receipt.json
```

render-check 默认按唯一“姓名：姓名”标记划分每人范围；目标模板没有该标记时，按实际模板编写人物边界适配，不接受全局文本匹配代替逐人核验。

review-files 是对象，键为 `sources,data,source_audit,facts,template,map,output,build,render,render_check`，值为对应文件路径。visual-review 包含 status=passed、pdf_sha256 和完整有序 reviewed_pages；只有实际看过全部页图才能填写。页面、模板、数据、映射、字段报告、源审计、输出、渲染或程序变更都会使回执失效。存在待核实项时只能得到 candidate，不能当作 closed。

回执状态不等于模板填写率，也不等于转换任务是否已按现有资料完成。已有信息已正确保留、缺失字段正常留空时，可以交付；局部事实仍不确定时保留技术候选状态及简要限制，不要求所有人达到 closed 后才交付。验证重点是已有信息的覆盖和对应准确性，不统计缺失字段为漏提取。

旧报告可用 `--legacy` 绑定并标记由当前原文重审替代；旧候选数不能被算成已证实遗漏数或已修复数。回执不能替代真实的人工复核。

长文本出现大行距或表头留在前页时，检查是否继承 Word 文档网格和段落 keepNext。仅按当前模板在动态长文本中调整 `snapToGrid`、段距或续行；字体字号、列宽和固定标签保留。窄栏的证书可保留简短状态，把完整有效期说明放入已有宽栏，并同时映射两个字段，不能删除日期来压页数。

## 可移植回归

```text
PYTHON SKILL/tests/test_pipeline.py --workdir TASK/new-test-run
```

测试源覆盖、进入JSON前丢段、跨项目串填、假引用、学历规则、两种动态模板、未映射字段、数据/来源变化、旧回执和未审候选。每次修复需复现原失败并验证修复；私有人名、简历和输出留在任务目录，不加入 Skill。新格式必须用独立真实数据验证，分别报告解析成功、语义映射、目标生成、渲染和视觉验收，不能把其中一步当全链路通过。

Excel 读取还保留 raw_value/raw_type/raw_formula/style_index/display_value 和原数字格式。非法数据验证枚举只在内存读取副本移除并记录原 XML，不改原件或单元格。ZIP 媒体存在即发视觉复核告警，包含 WPS DISPIMG 未加载的图片；坏日期不能因为库转成 #VALUE! 就丢掉底层数值。表格公式/图片提示、下拉字典、个人填写值须分开，日期/统招/学位冲突保留双方原文。

核对每条教育、任职、项目的日期顺序，并检查开始日期是否晚于本次处理日期。结束早于开始须待核；未来开始须核实是否计划记录。不能自动改成看似合理的年份。将受影响日期标为 needs_review，保留 source_conflicts 和原始引文；教育日期异常影响最近已毕业记录选择时，摘要学历/学位也须复核。

已知 Excel 行区间可用 record_scope_overrides 指定 source_id/unit_ids/anchor_quote/reason；边界精确来自本次工作表，不按固定项目数或全文件扩范围。定位器默认在工作表切换和证明区停止，并取教育/任职同一行的日期证据。

另运行 `PYTHON SKILL/tests/test_xlsx_intake.py --workdir TASK/new-xlsx-test`，验证非法枚举、坏日期原值、图片告警与工作表边界。

`PYTHON SKILL/tests/test_render_check.py --workdir TASK/new-render-check-test` 验证日期后“日”字保留、日期精度、相邻页单元格续接及缺字/串人反例，以及 General 科学计数数值的整数字符串显示。原始数值和数字格式始终保留；移除读取器产生的浮点 .0 不能改动源文件。

## 图片与证照证据接入

```text
PYTHON SKILL/scripts/media_evidence.py --source SOURCE.xlsx --ocr --outdir TASK/media
PYTHON SKILL/scripts/media_evidence.py --source SOURCE.pdf --all-pdf-pages --ocr --outdir TASK/scan-pages
```

Office 媒体报告保留包成员与关系；WPS cellimages/DISPIMG 保存公式单元格，普通绘图保存锚点，DOCX 保存 XML 路径。PDF 默认只渲染少于 30 个提取字符的页；图片混排页用 `--all-pdf-pages` 显式纳入。Windows OCR 依赖已有本机语言包，不安装软件、不上传简历；不支持或失败会保留 pending。Windows 不提供置信度时保留 null，不能伪造分数；识别为空仍须检查是否照片、占位图或方向/质量问题。

`compare(media_report, person)` 列出原字段、OCR 命中/未命中及日期线索。未命中不是矛盾判定。真正使用图片事实前必须查看原图，区分照片、毕业证、学位证和无关图；学校、专业、姓名和学习期间分别核对，证书颁发日不自动等于毕业日，资格证书还要核对有效期。

复核记录数组各项需 `asset_id, asset_sha256, status: visually_reviewed, reviewer, owner_name, text, reason`；`text` 是已看图后忠实转录的相关原文，保留 OCR 原始结果和纠错说明，不在这里编造事实。接入新清单：

```text
PYTHON SKILL/scripts/media_evidence.py --reviewed-media TASK/media/media.json --sources TASK/extracted/sources.json --reviews TASK/visual-transcriptions.json --outdir TASK/attached-media
```

接入保留原清单和全部旧 unit_id，另存含 `reviewed_media_text` 的 detail 与 sources.json。Office 图片与原包内成员哈希核对，PDF 页图与原件重新渲染的像素核对。来源原件、所看图片、人物身份、复核人和摘录绑定；数据事实报告、源审计及回执重做。毕业证据引用新单元时须按数据参考设置 `credential_review`，不得用未看 OCR 文本伪装人工证书确认。

OCR 是辅助手段，默认 `media_policy=when_needed`。文字已齐全且无冲突时，附有毕业证、学位证或照片不强制 OCR，也不强制逐图复核。只有当前任务确实依赖的图片事实、来源扫描正文/空文本、未解决冲突，或用户明确要求 `review_all` 时，相关复核才是门禁；清晰图片可以直接查看并转录，不必先 OCR。可选图片的提示仍保留，不能据此把缺页、正文提取失败或业务公式错误降为可选。

闭环操作见 [review-actions.md](review-actions.md)：导出的 JSON/CSV 可写入具体决策，再由 `review_actions.py` 重算字段、毕业、来源及新队列；单纯勾选通过不会关闭问题。同名人员须绑定 person ID、来源范围及图片身份。明确毕业时间证据必须绑定标签自身的值，同一行任意结束日期不能替代；整条教育记录出现“预计/在读”时保留待核。跨行列标题目前保守拒绝，可用原件人工复核或明确的用户确认，不能扩大引用范围绕过。

新增回归：`tests/test_record_checks.py` 覆盖毕业证明失效、默认值撤回、真实日历、未来毕业、同教育行学位与默认值循环引用；`tests/test_helpers.py` 覆盖合并邻接、非相邻表头、歧义标签、多人员 Word 边界、媒体接入、逐人门禁、CSV 公式转义及视觉复用的变更反例。
