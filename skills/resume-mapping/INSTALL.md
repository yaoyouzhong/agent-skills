# 给当前 AI Agent 的通用安装入口

适用于支持 Agent Skills、可以读写本地文件和执行命令的 AI 工具；不限定客户端或模型供应商。Windows、macOS 使用同一份包。`SKILL.md` 是入口，所有脚本和参考使用相对路径；`agents/openai.yaml` 只是可选界面元数据，其它客户端可忽略。包内没有模型、账号、API Key、真实人员简历或固定目标模板。

用户说“安装这个 Skill”时，先安装本包，不要先索取原始简历与目标模板。原始简历与目标模板是在安装后执行转换时提供的两项业务输入。

## 安装并验收

1. 读取 `SKILL.md`、本文件及 `package-manifest.json`，检查脚本。解压时拒绝绝对路径、上级目录和符号链接等越界成员。
2. 由**当前宿主客户端**的原生导入功能、已公开文档或本机配置确定真实的用户级 Skills 目录。优先使用原生 ZIP 导入；如宿主允许本地脚本，也可用本包安装器。不要根据模型名称猜客户端，不要求安装 Codex，不把某三个客户端当支持白名单。不同 AI 工具可以使用同一个包，但目录和加载动作由各宿主决定。
3. 找到现有 Python 3.11+。有宿主依赖查询工具就使用；没有时检查本机 `python3`、`python` 或 Windows `py -3`，不得依赖其它电脑的绝对运行时路径。
4. 安装器只依赖 Python 标准库；`--target-dir` 接受任何宿主已确认的 Skill 完整目录。先预览再按用户已授权的安装请求执行，宿主本身要求的授权照常遵守：

   ```text
   PYTHON scripts/install_skill.py --target-dir VERIFIED_SKILLS_DIR/resume-mapping
   PYTHON scripts/install_skill.py --target-dir VERIFIED_SKILLS_DIR/resume-mapping --apply
   ```

   `VERIFIED_SKILLS_DIR` 由当前 Agent 确定，不让普通使用者配置映射或修改源码。安装器校验每个公共文件；同版重复安装不改文件，已有不同或改过的版本会保留并报出，不自动覆盖。Python 尚未可用时可由宿主原生导入包，但要明确“规则已导入、运行依赖未就绪”。
5. 对已安装目录运行 `PYTHON scripts/environment_check.py`。已有合适运行时可直接复用；依赖缺少时，在安装目录的同级隐藏运行时目录创建独立环境，依赖下载仅来自常规 Python 包源，不做全局 pip 安装：

   ```text
   PYTHON scripts/install_skill.py --target-dir VERIFIED_SKILLS_DIR/resume-mapping --apply --setup-env
   ```

   返回的 `runtime.python` 是后续执行本 Skill 的解释器路径。离线已有依赖时可加 `--reuse-system-packages --offline`。包内 `requirements.txt` 固定了本版经过回归的直接依赖；下载失败如实保留日志，不忽略失败。缺少 Python 或办公渲染程序时，先报告具体缺项；本脚本不会自行安装系统软件或修改安全配置。
6. 使用安装后的解释器，在全新临时目录执行 `tests/test_pipeline.py --workdir NEW_TASK_DIR`，确认合成来源到 Word 的结构自测。此自测不需要真实简历，不等同最终排版验收。若有 Word/Excel 或 LibreOffice，再用 `render_output.py` 渲染合成输出并实际看图；无渲染器时说明只能完成结构生成，不能声称排版已通过。
7. 按宿主的方式刷新或新开对话，确认该宿主的技能目录/选择器确实列出 `resume-mapping`，再实际加载其正文。安装器的 `client_discovery: unverified` 只能由这一步补证，文件复制成功不等于客户端已加载。不要自动修改宿主插件、安全、账号或模型配置。没有目录发现/命令执行/看图能力时说明哪一环受限，而非谎称安装与转换成功。

## 文档能力按任务检查

- **现代 PDF、DOCX、XLSX 来源和 Word 结构生成**：Python 3.11+ 与 requirements 中的库，不依赖特定宿主 API。
- **普通 Excel 目标**：默认 `openpyxl` 后端，不需要 Node.js 或 OpenAI Artifact Tool。可选的 Artifact Tool 后端保留给已经具备它的环境；复杂原生对象会明确要求专门适配。
- **最终页图验收**：Windows 可用 Microsoft Word/Excel 隐藏独立实例；macOS/其它环境可用已安装的 LibreOffice，例如 `/Applications/LibreOffice.app/Contents/MacOS/soffice`，通过 `--soffice` 或 `RESUME_SOFFICE` 指定。Mac 版 Office 不支持本包的 Windows COM 桥接。字体须与目标模板相符，替代渲染器的换行与分页要实看，不保证与 Word 完全一致。
- **旧 DOC/RTF/XLS**：Windows 用现有 Office 转换任务副本；其它环境使用已有 LibreOffice。加密、受策略阻止或损坏的文件不算空简历。
- **已填 Word 样例抽取格式**：Windows 可用 Word；普通不含复杂对象的表格可用 `template_prepare.py --backend ooxml`。正文以外有样例文字、图片或复杂关系时拒绝默默复制，另做任务适配。
- **OCR**：按需。现成 Windows OCR 是可选后端；其它系统可使用宿主的看图能力或已配置的 OCR，并通过已有证据接口接入。文字齐全时不要求 OCR。

## 安装完成后的使用

告诉用户安装目录、实际解释器、已通过的自测和仍缺的渲染/看图能力。以后用户只需说：“用简历Mapping Skill，把【原始简历目录或附件】按【目标模板路径或附件】整理。”缺哪一项才提示哪一项。

客户端目录示例与官方来源仅用于帮助发现，不限制兼容范围，见 [references/host-installation.md](references/host-installation.md)。
