# 安装简历Mapping

给具备 Agent Skills 加载及文档处理能力的 AI 客户端使用，不限定模型或客户端。用户只需让当前 Agent 安装本 Skill；执行转换时再提供原始简历和目标模板。

## 默认安装

1. 使用宿主原生 ZIP/仓库导入功能，或已有文件工具把 `resume-mapping` 的公共清单文件及清单本身复制到该宿主已确认的 Skills 目录。排除运行时生成的 `__pycache__`、`.pyc` 和系统桌面元数据，不把这些未校验文件当作安装内容。目录依据当前客户端的真实配置或官方说明确定，不按模型名称猜路径。拒绝 ZIP 绝对路径、上级目录和符号链接等越界成员。
2. 读取 `SKILL.md`；使用已有文件/哈希工具按 `package-manifest.json` 核验公共文件。保留其它或用户修改过的版本，不静默覆盖。无需为了核验安装 Python，若宿主缺少哈希工具则明确包完整性尚未核验。
3. 按宿主方式刷新或重新加载，确认 `resume-mapping` 确实可发现并加载。文件复制成功不等于宿主已加载。
4. 发现宿主已提供的来源读取、目标编辑/保存和预览/看图工具，用合成小样本实际读写与重开；具备预览能力时实际看图。没有 Python 时不要求运行 Python 自测。
5. 用简单结果告诉用户能否完成本次文档任务；具体缺项只在实际影响任务时说明。不要求用户准备开发环境，不自动安装 Python、Office、LibreOffice、OCR 套件、插件或大型运行包。

安装与可用性验证由当前 Agent 完成，不让普通用户执行命令或选择软件后端。模型服务沿用宿主已有配置；本包不包含模型、账号或 API Key。

## 已有解释器时的可选辅助

宿主已有可用 Python 时，可使用标准库安装器精确核验并复制目录：

```text
PYTHON scripts/install_skill.py --target-dir VERIFIED_SKILLS_DIR/resume-mapping
PYTHON scripts/install_skill.py --target-dir VERIFIED_SKILLS_DIR/resume-mapping --apply
```

这是可选安装方法，不是所有宿主的必经步骤。`environment_check.py` 只检查可选脚本环境，不以其缺少 Python 库否决已经具备原生文档能力的宿主。

若选择脚本路径，先复用宿主随附或本机已有的运行环境和库。`requirements.txt` 记录脚本路径经过回归的依赖，不代表用户必须安装这些软件。旧 `--setup-env` 保留给明确要求配置独立 Python 环境的维护者，默认安装/使用不调用；没有这些依赖时优先改用现有文档工具，不自动安装。

## 文档能力边界

- 读取来源、写目标文件和实际预览由当前宿主工具承担；支持的格式取决于实际工具，不单凭模型名称承诺。
- 本包的普通 Word/Excel 脚本后端可按需复用；已有 Windows Word/Excel、LibreOffice 等也可作为本机工具使用，不要求用户另行安装。
- 原生文档工具无法处理的旧格式、复杂对象或损坏/加密文件，先用已有其它工具解决；仍不可用才报告具体限制。不把读取失败当空资料，不静默改目标格式。
- 没有实际渲染/看图能力时可以完成可确定的其它部分，但不能声称最终排版已验收。
- OCR 按需，可直接使用现有多模态看图能力；文字信息足够时不要求 OCR。

使用：“用简历Mapping，把【原始简历目录或附件】按【目标模板路径或附件】整理。”业务流程见 [references/host-workflow.md](references/host-workflow.md)。宿主导入方式示例见 [references/host-installation.md](references/host-installation.md)。
