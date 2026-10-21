# 批处理与效率

> 本文件描述可选脚本实现的格式和契约，仅在宿主已有对应运行环境并选择这些工具时使用。默认先按 [宿主文档流程](host-workflow.md) 执行，不要求用户安装额外软件，也不把本文件的 JSON/命令设为原生文档工具的必经步骤。

用户仍只提供原始简历和目标格式。以下文件、命令和复核记录由 Agent 内部完成。所有来源只读、所有生成物写任务目录；包内不保存真实简历。保留既有来源、日期、毕业、事实、逐人内容和视觉门禁。

## 一次准备

```text
PYTHON SKILL/scripts/batch_pipeline.py prepare --input SOURCE_DIR1 SOURCE_DIR2 --template TARGET.docx --workdir TASK
```

初次 TASK 必须是新目录；同任务再次 prepare 可识别原件、提取方式、依赖或模板变化。每个来源按当前原件哈希、提取代码、格式库版本、阅读顺序缓存，内容发生变化即失效，文件名相同也会重提取。来源 ID 在本任务内保持稳定，不因新增文件改变已有人物的引用。模板原件每次验证；不会把输出目录当输入扫描。

输出 JSON 给出 `sources`、`source_snapshot`、`index`、模板 `inspection` 和变更计划。阅读索引及每份 `source-bundles/sNNNN.md`；每个原文单元包含稳定 ID、定位和**完整文字**，没有摘要截断。原始文字、坐标和清理日志仍在来源 detail。复杂多栏、身份或边界问题回看原 PDF/Office，不能只相信提取结果。跨文件人物按身份合并，一个文件多人须明确 scope，不按文件数猜人数。

集中写标准数据与目标映射，格式仍遵循 [data-and-template.md](data-and-template.md)。同时记录空项原因和证据；无法判断的进入回查队列。普通缺失不问用户补齐，不对已齐全文字材料强制 OCR。

## 精确引用代替抄写

可选简写由 `review_bundle.hydrate` 展开为原有数据契约，**不替代任何事实门禁**：

```json
{
  "id": "p001",
  "source_ids": ["s0001"],
  "fields": {"meta": {"name": "示例人员", "sex": ""}, "projects": [{"name": "示例项目", "desc": "", "resp": ""}]},
  "record_refs": {
    "projects[0]": {"source_id": "s0001", "anchor_unit_id": "u-title", "from_unit": "u-title", "through_unit": "u-last", "reason": "该项目标题至下一项目标题之前"}
  },
  "field_text_refs": {
    "projects[0].desc": {"source_id": "s0001", "unit_ids": ["u-intro"], "strip_prefix": "项目介绍："},
    "projects[0].resp": {"source_id": "s0001", "from_unit": "u-duty-first", "through_unit": "u-duty-last", "join": "\n"}
  },
  "evidence_refs": {"meta.name": [{"source_id": "s0001", "unit_id": "u-name"}]},
  "blank_review_groups": [{"fields": ["meta.sex"], "classification": "source_not_provided", "reviewer": "本次实际复核Agent", "reason": "已阅读本人的全部现有文字，没有性别或足够的交叉推导依据"}]
}
```

上例是 `people` 中的一个人员对象。数据顶层还须放 `source_snapshot`，复制本次 prepare 输出的同名对象即可；也可在任务脚本中用 `review_bundle.snapshot(manifest)` 获取。它绑定原件、原文文字和完整提取哈希。源文件/提取发生变化后，旧简写、旧空项意见会被拒绝；先重新阅读受影响人员再更新该快照，不能只刷新哈希来绕过回查。

例中的 ID 必须换成本次真实单元。`field_text_refs` 对应字段初始为空，脚本从指定单元无损取全文；允许空格、换行或空字符串连接。只能显式去掉确实属于字段标签的首部，不删业务正文。不同段落或多栏内容用精确 unit_ids，不能把整段范围笼统塞入项目介绍。项目、任职、教育的文字引用必须在对应 `record_refs` / `record_sources` 范围内，跨项目引用拒绝。记录范围仍由现有来源审计检查独立标题和边界。

已有完整 `record_sources` / `evidence` 可以原样使用，批处理不会以宽松匹配覆盖已给定的定位。资料不足的毕业状态保留未知；引用存在并不自动证明毕业、职务或客户含义。`evidence_refs`、事实与毕业证据的 `source_refs` 只展开精确原文，不作语义批准。不能重复声明同一字段的全文证据与简写。

`blank_review_groups` 是 Agent 已实际回查的判断；每项必须列出确切空字段、理由和实际复核人，只展开到这些字段。明确审过的正常缺失同时写入原有字段事实分类，避免为同一空项再填一遍 decisions；资料不足仍保持 needs_review，已知可填但仍空白会阻止继续生成。新的目标空项仍逐项检查。不得用“全部未提供”自动关闭未知、漏提或无法识别的字段。

## 规则、空项与排版样本

```text
PYTHON SKILL/scripts/batch_pipeline.py run --workdir TASK --data TASK/reviewed-data.json --map TASK/template-map.json
```

可附 `--clients CLIENT_EVIDENCE.json` 和 `--decisions FACT_DECISIONS.json`。该命令自动连接日期统一、必要的记录定位、默认规则、事实分类、原文到字段审计和实际模板空项统计。输出 `exceptions/review.json` 按人集中列出目标空项及事实/来源问题，链接回完整来源；先补回已有信息，再确认正常缺失。普通缺失完成回查即可留空，不能为了消除 candidate 伪造来源确认。

需要修改字段或证据时修改任务输入后重跑；不沿用失效报告。未审空项或原文遗漏会停在对应工作节点。`--defer-render` 只用于已有明确渲染限制时保存排版候选，不能称排版通过。

校验允许构建后，自动选完整文本量最短、最长人员生成独立 `layout-sample.docx` 并原生渲染。它使用完整当前来源门禁，只显示选中人员，报告标记 `sample_only`，不能生成全量验收回执。实际查看样本全部页面，核对目标字体字号、标签、列宽、续行和分页，调整映射后重新生成；不要缩字、截断或省略长内容来提速。

按 [quality-and-review.md](quality-and-review.md) 的 visual-review 格式写样本已看页证据，然后：

```text
PYTHON SKILL/scripts/batch_pipeline.py run --workdir TASK --data TASK/reviewed-data.json --map TASK/template-map.json --pilot-review TASK/pilot-visual.json
```

命令生成全批 Word、验证每人的实际内容，再执行原生渲染和逐人渲染文字核验。默认渲染分辨率和字体大小不变。样本排版正确不代表全部页面都正确；实际查看所有尚未验证的页面后写全量视觉记录：

```text
PYTHON SKILL/scripts/batch_pipeline.py run --workdir TASK --data TASK/reviewed-data.json --map TASK/template-map.json --pilot-review TASK/pilot-visual.json --visual TASK/full-visual.json
```

最终返回 `converted_and_visually_reviewed` 及回执路径。技术回执可能因源文事实矛盾保持 candidate；准确转换和所有事实真实性核清是不同范围，不把 pending 清空当目标。

通用 `prepare` 支持 Word、Excel 等来源和 DOCX/XLSX 目标。批处理 `run` 当前串联 Word 目标；Excel 目标继续 [format-adapters.md](format-adapters.md) 的 `template_xlsx.py` 和逐人原生打印流程，复用原文阅读包及变更计划，不把 Excel 输出改成 Word。旧 DOC/XLS 目标先在任务副本转换，保留原件。

## 安全复用与计时

同样输入重跑会验证缓存文件、当前原件、提取、代码、数据及映射哈希；被修改或缺失的缓存重建，旧证据保留。仅格式不变、数据字段完全相同的输出可复用；仍对**当前**数据执行来源及逐人完整性检查。字体目录、渲染器与渲染代码也参与渲染缓存，不能用旧环境的页图冒充新结果。

已有实际看过的旧回执可通过 `--previous-receipt OLD/receipt.json` 得到像素复用计划。按 `layout_review.py complete` 合并真实新审页面，只有像素哈希完全一致的旧已审页面能复用。来源/业务规则重新验证；新页、变更页全部查看。首次冷测试不提供旧数据或旧回执。

```text
PYTHON SKILL/scripts/batch_pipeline.py mark --workdir TASK --phase source-review --state start
PYTHON SKILL/scripts/batch_pipeline.py mark --workdir TASK --phase source-review --state stop
PYTHON SKILL/scripts/batch_pipeline.py status --workdir TASK
```

在实际整理、空项回查和看图区间各记录 start/stop；区间不应包含无关任务。`batch-state.json` 保存完整开始时间、程序阶段、失败、缓存命中和 Agent 区间。Agent 区间是实际操作墙钟，包含阅读、模型处理、工具往返和可能的等待，**不是模型推理耗时**；如果与程序阶段重叠，不能相加。独立测试还应在读 Skill 前记录外层开始时间，所有输出和验收完成后记录结束，包含准备与任务适配。

分别报告冷启动完整执行、同输入复跑和改动一人后的增量执行；同时核对人数、每人的项目/教育/任职、已提供字段、原文覆盖、目标空项回查和全部页面，不能以压缩文本、跳过检查、降低页图分辨率或复用答案制造提速。
