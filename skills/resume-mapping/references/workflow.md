# 执行命令与完成证据

以下 `SKILL`、`PYTHON` 和任务目录均由当前环境解析，不依赖某个客户端的工具名称或作者桌面路径。Python 需要 3.11 或更新版本，完整依赖版本见 requirements.txt；安装与独立环境见 INSTALL.md。Windows Office 桥接使用 PowerShell COM，不依赖 pywin32；其它平台使用已配置 LibreOffice。只读取某一种格式时，不需要其它格式的依赖。先复用当前宿主或本机已有环境，不执行全局安装。

## 1. 盘点并提取

```text
PYTHON SKILL/scripts/extract_sources.py --input source.pdf source.docx source.xlsx --workdir TASK/extracted
```

也可以传多个来源目录；输出目录必须新建且不位于被扫描目录内。目录里的未知扩展名会记入 `ignored_files`；显式指定的未知格式记为错误。防止把本次输出重新当成来源，优先传来源文件列表/专用输入目录，不要无差别扫描整个项目。

返回码：`0` 已提取且无程序告警；`2` 需要内容复核；`1` 有文件提取失败。即使某个文件失败，仍保存其余来源清单和错误，不能忽略返回码。程序无告警只代表基础提取成功，不证明简历语义完整。

输出 `sources.json`、逐来源的 `.txt` 和 `.json`；清单包含原件 SHA-256 和来源位置。旧格式转换副本也保存在此任务目录。读取支持加密/扫描件的适当工具前，先保留错误与原始证据。不要设置空密码循环猜测，不执行宏，不把错误来源排除来制造成功。

逐一判断告警是否影响本次任务；默认按需图片策略下，文字齐全且无冲突的可选附件不强制 OCR 或逐图复核。必须解决的正文/缺失/冲突告警，把实际复核动作和证据路径写在 `source_reviews`，保留原 `warnings`。实际使用的 OCR 文本、逐页定位及复核过程另存并接入清单/证据；`source_reviews` 不能只有“已处理”三个字。

## 2. 整理与默认规则

用 Agent 阅读来源，生成 `reviewed-data.json`。脚本负责确定性处理，不声称能从任意简历版式中自动理解全部字段。一个 Excel 可以包含多个人，一个人可以关联多个来源 ID。

按提供资料填写目标模板即可，不要求所有字段非空。来源未提供的值由 Agent 阅读后分类为 `not_provided` 并留空，不向用户逐条索取或确认；确有内容但提取失败或无法判定时分别记录原因。保留已有教育、任职与项目内容，默认规则只在条件满足时使用，不为填满模板推断未知事实。

数据先写本次 `processing_date` 并定位引文，再运行前置检查；默认规则、事实分类和构建也会重跑相同门禁。

```text
PYTHON SKILL/scripts/record_checks.py --data TASK/located-data.json --sources TASK/extracted/sources.json --out TASK/record-checks.json
```

`form_grid.FormGrid(sheet)` 接收提取 JSON 的工作表，`at(aliases, bounds)` 查真实标签的邻接值，`table_records(bounds, aliases, required)` 在章节范围内找实际表头；`word_table_grid(table)` 将 python-docx 的表适配为同一读取接口。重复非空标签或表头不明确时会拒绝猜选；先缩小记录范围。它提供通用定位，不代替本次人员边界和字段映射。

```text
PYTHON SKILL/scripts/apply_policies.py --data TASK/reviewed-data.json --clients TASK/client-evidence.json --sources TASK/extracted/sources.json --out TASK/normalized-data.json --audit TASK/policy-audit.json
```

没有客户补全建议时省略 `--clients`。返回码 `2` 表示学历状态/毕业日期等需要核实；先核对现有来源，无法确定时保留相关空值/原文与提示，并按脚本契约以 `output_mode=candidate` 继续完成可确定信息的转换，不冒称事实全部验收。只对**确认已毕业**记录补默认学位，学历学位摘要来自**毕业时间最近**的一条已毕业记录。在读记录不能覆盖摘要。不能用“本科加学士”“研究生加硕士”的默认值反过来证明已经毕业。

客户候选文件为 JSON 数组：

```json
[
  {
    "person_id": "p001",
    "collection": "projects",
    "index": 0,
    "client": "示例银行",
    "quote": "为示例银行建设客户服务平台",
    "source_id": "s0001",
    "unit_id": "u-actual-source-unit-id"
  }
]
```

`index` 从 0 开始，`collection` 可为 `projects` 或 `jobs`。片段必须出自同一条记录的 `name`、`desc`、`intro`、`details`、`resp` 或 `tech`，客户名称（多个用顿号分隔）也必须在片段内。有些来源把实际服务对象写在技术描述内，不能因此漏提；仍须判断这是客户而非公司、厂商或技术名，项目范围与客户角色检查继续适用。

生成前按 [quality-and-review.md](quality-and-review.md) 完成记录定位、字段分类和原文到数据审计；以下构建命令的 data 应使用该最终审计数据。

## 3. 读取当前目标模板并映射

```text
PYTHON SKILL/scripts/template_docx.py inspect --template USER_TEMPLATE.docx --out TASK/template-inspection.json
```

根据实际结构编写 `template-map.json`；格式见 [data-and-template.md](data-and-template.md)。模板、映射和数据是构建器内部的独立对象；用户只需提供原始简历和目标格式，映射与结构化数据由 Agent 生成。不给本次用户自动选择模板。自定义模板可有多个正文表格与正文段落；多节、图片/业务书签/脚注关系等复杂结构需要专门适配，脚本会拒绝可能生成重复 ID 的模板；Word 的 _GoBack 编辑光标书签可安全移除。

```text
PYTHON SKILL/scripts/template_docx.py build --template USER_TEMPLATE.docx --map TASK/template-map.json --data TASK/normalized-data.json --sources TASK/extracted/sources.json --source-audit TASK/source-audit.json --out TASK/resumes.docx --report TASK/build-report.json
PYTHON SKILL/scripts/template_docx.py check --template USER_TEMPLATE.docx --map TASK/template-map.json --data TASK/normalized-data.json --sources TASK/extracted/sources.json --source-audit TASK/source-audit.json --docx TASK/resumes.docx --report TASK/check-report.json
```

所有产物使用新路径。构建前核对全部原件哈希、每个人的来源及未使用来源的明确排除理由。构建后逐人检查内容，不能因为别人的简历包含同样句子就误判本人的内容完整。保留模板中除 `word/document.xml` 之外的包成员逐字节不变。

构建器不自动美化目标模板。若目标模板存在固定行高，而内容较长，应在任务适配中将相应行高调整为最小值/自动增长，再重新渲染核验；不要靠缩字号或截断职责解决。不能只因为有重复行，就任意删除原模板的固定标签。

## 4. 渲染并验证

```text
PYTHON SKILL/scripts/render_output.py --docx TASK/resumes.docx --outdir TASK/render
```

Windows 默认使用安装的 Microsoft Word 的独立隐藏实例，只读打开、导出 PDF、不保存原件。也可显式提供 `--soffice EXISTING_EXECUTABLE_PATH`，使用已安装或宿主提供的 LibreOffice，创建隔离配置和任务副本，不接管用户桌面实例。非 Windows 平台自动查找 RESUME_SOFFICE、PATH 或常规 Mac 应用路径。Excel 渲染副本只显示所选工作表，不把其它人的工作表一起导出。失败时保留诊断，不以文件存在冒充成功。Office 仅关闭自己创建的文档和实例，禁止结束用户的 Office 进程。

该命令生成 PDF、逐页 PNG 和带全部页文字的 `render.json`，并保持 `visual_review: pending`。由 Agent 对照原模板检查全部页图，结合逐人文字和项目数复核分页、字体、边框、表格跨页、无截断/重叠。根据渲染问题调整当前映射/任务适配后，重新生成和检查；不要沿用旧页图的验收结论。

渲染同时保存 `layout.json`。旧批次可单独运行 `layout_review.py analyze --render ... --out ...`。像素复用分两步：`layout_review.py plan --render NEW/render.json --old-receipt OLD/receipt.json --out TASK/reuse-plan.json`；逐页查看 `needs_visual_review` 后保存实际新复核的 `pdf_sha256`、`reviewed_pages`、`status`，再用 `complete --render ... --plan ... --new-review ... --out ...` 合成当前视觉证据。它会重新验证旧图、旧视觉记录和复用计划，不会自动批准变更页。

待核清单：`review_queue.py --data ... --sources ... --report TASK/record-checks.json --report TASK/facts.json --report TASK/source-audit.json --outdir TASK/review-queue`。CSV 以 UTF-8 BOM 写出，源文本的公式前缀会转义。CSV/Markdown 为审阅入口；更新字段与证据后重新生成，不能靠勾选意见关闭原有问题。

最终说明实际完成的人数、来源范围、目标模板和待核实项。Word/Excel 目标走各自完整的生成及原生渲染主链路；原生 Excel 目标使用 `template_xlsx.py` 与 `render_output.py --xlsx ... --sheet ...`，具体契约和命令见 [format-adapters.md](format-adapters.md)。每种旧格式、扫描件和复杂布局分别记录实测层级，不把任意一种成功写成所有格式通过。

对用户以转换后简历为主交付，简述影响使用的局部问题即可。普通缺失字段无需逐项列成补齐要求；完整技术清单按需提供。评估转换质量时核对现有信息是否漏填、误填、串人/串项目及截断，不把模板空格数或回执 closed 人数当作提取准确率。

## 空项回查、交叉推导和日期格式

```text
PYTHON SKILL/scripts/fill_coverage.py --data TASK/data.json --map TASK/template-map.json --out TASK/fill-before.json
PYTHON SKILL/scripts/normalize_dates.py --data TASK/data.json --out TASK/date-data.json --report TASK/date-changes.json
PYTHON SKILL/scripts/cross_fields.py --data TASK/date-data.json --sources TASK/sources.json --candidates TASK/identity-candidates.json --out TASK/inferred-data.json --report TASK/inference-changes.json
```

`cross_fields` 候选为数组，每项含 person_id、owner_person_id、owner_verified（严格 JSON true）、reviewer、reason、identity_number 和精确 source_quotes。号码须明确属于该人；多人共享来源还须 person_source_scope。号码只在本地输入/证据保存，摘要脱敏。只补空性别；已有值不覆盖，冲突另报。仅有 15 位、掩码、校验失败或缺归属的号码不自动推导。

按 fill-before 中每处实际空项回看该人及该经历的全部相关文字，记录未提供、证据不足、识别失败、按规则留空、已在对应合并栏显示、原有但遗漏等原因。证据充分的补回对应字段并保留类型与原文，不改变已确定的学历/学位/客户业务规则。正常缺失可以结束回查，不要求补齐。

日期格式化或补值后，重跑默认规则、字段事实、来源审计、构建与渲染检查，再生成 fill-after。规范化保留原值；来源覆盖快照只更新本来有效的格式等价值，包括绑定整个教育数组的快照。不能复活先前已过期的证明或引用。填充率只用于说明已填/留空，不代表准确率；准确性仍以源文与对应位置核对。
