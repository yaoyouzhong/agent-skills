# 模板适配与真实评测

> 本文件描述可选脚本实现的格式和契约，仅在宿主已有对应运行环境并选择这些工具时使用。默认先按 [宿主文档流程](host-workflow.md) 执行，不要求用户安装额外软件，也不把本文件的 JSON/命令设为原生文档工具的必经步骤。

## 从已填 Word 中提取格式

```text
PYTHON SKILL/scripts/template_prepare.py --source SOURCE.docx --plan TASK/clear-plan.json --outdir TASK/prepared-template
```

plan 包含 source_sha256、table_index（顶层表格从0开始）、blank_cells（row/cell/expected_text，按真实 XML 单元格）、remove_rows 和 keep_text。先实际检查标签与样例，不能按“非标签都是样例”的猜测批量生成清理计划。Windows 可用独立隐藏 Word 复制选中表格，或用 --backend ooxml 在通用 Python 环境选取普通正文表格，再清理样例。正文以外的样例文字、残留非许可文字或图片会拒绝，复杂对象需专门适配。输出还需实际打开、渲染、查看。

Word 映射的表级 append_rows 可克隆原模板的宽行承载补充字段，结构与 repeat.trailing_rows 相同，但绑定整个人员 fields：rows、when_nonempty、fields 的 row/cell/key/prefix。字体、列宽等来自该真实原行，不能借此悄悄省略字段。补充行可设置 `auto_height: true`，仅取消该克隆行继承的高度，让短字段紧凑、长字段自然增长；原型与静态行不变，仍需原生渲染核验。

## 原生 Excel 目标

通用 Python 环境使用 openpyxl 后端，不需要宿主专有库。复杂图形、宏、透视表、扩展节点等可能不能保真时明确拒绝，另做任务适配：

```text
PYTHON SKILL/scripts/template_xlsx.py --template TARGET.xlsx --data TASK/data.json --sources TASK/sources.json --source-audit TASK/audit.json --map TASK/map.json --output TASK/output.xlsx --backend openpyxl --workdir TASK/xlsx-build
PYTHON SKILL/scripts/render_output.py --xlsx TASK/output.xlsx --sheet TARGET_SHEET --outdir TASK/xlsx-render
```

映射包含 sheet、clear_ranges、static_cells、fields、repeat、print_area；只清除已核对的样例区域，remove_sample_drawings 仅在确认这些图片全是样例时启用。clear_ranges/print_area 可用 `{last}` 取实际最后一行。重复块配置 key/start_row/height/template_range/fields，字段位置用 row 相对偏移和 column 字母；merges 可用 `{row}` 或 `{r0}`、`{r1}` 等实际行号；row_heights 来自本次版式需要。

有额外业务字段时必须映射；append_unmapped 可指定原宽行 template_range、start_row 和逐字段 labels，按读者可理解的名称保留。长文本分为有界续行，不降低字号；字体和边框复制原模板。单元格写入不得重叠，未知字段不会静默丢弃。每人一工作簿，多人的来源清单先正确拆分。

已有 Node.js 与 Artifact Tool 的宿主，可选择 --backend artifact-tool --node NODE --modules NODE_MODULES；不作为通用前置条件。两种后端共用来源门禁与映射计划，复制目标格式并把简历值写为文本。原生打印范围与分页元数据由有界 OOXML 补丁设置，page_break_rows 指定本次实际需要的换页行，不能全局强加每项目一页。打印设置、合并单元格、动态数量和长文字均须在实际办公软件 PDF/页图中核对。成功导出 XLSX 不等于打印验收。包含复杂原生对象时另行核对保真，不能把未支持功能说成已保留。

单人输出可显式映射 person_boundary.mode=single_person，仍逐字段检查该人的全部渲染文字；多人不允许使用此模式。同名多人可用 ordered_name_occurrences 并绑定完整 order 人员 ID 列表。其它人物标记仍按真实模板适配。

## 独立人工基准

```text
PYTHON SKILL/scripts/evaluate_benchmark.py --gold TASK/gold.json --predictions TASK/sealed-predictions.json --adapters TASK/schema-adapters.json --out TASK/benchmark.json
```

gold.cases 每项含 id/source/source_sha256/person_name、fields（path/accepted_values/source_quote/locator/category）和 project_names。predictions 是以 case ID 为键的对象，值含 data/data_sha256。adapters 只映射相同业务字段的路径名称，不改预测值。标注方只看原件，初始预测在读取标注前封存；标注有错时保留原版、局部原图和更正原因，调优结果另评。

脚本报告标注字段命中、差异、项目边界和分类分母。长文本采用标准化包含匹配，日期/身份等采用标准化精确匹配；此指标不是全部简历的准确率，也不替代来源完整度或视觉验收。没有标注的字段不算已通过。真实格式结果与合成兼容性测试、受环境策略阻止的测试分别记录。
