# 宿主安装示例及能力边界

本包采用 [Agent Skills 开放格式](https://agentskills.io/specification)：必需入口是带 name、description 的 SKILL.md，辅助文件使用相对路径。兼容性由宿主能否加载此格式，以及能否使用实际文档工具决定，不按客户端名称设白名单。本文件中的例子不是全部支持列表。

通用安装优先宿主自带 ZIP/仓库导入或已有文件工具复制到已确认的目录；不要求 Python。已有 Python 的宿主也可选择 `install_skill.py --target-dir VERIFIED_SKILL_DIRECTORY --apply`。当前版本不会声称已在所有宿主或所有操作系统实机验收。

| 例子 | 已核对的发现方式 | 本包的处理方式 |
|---|---|---|
| Claude Code | 用户级 `~/.claude/skills/<name>/SKILL.md` | 可用 `--host claude-code` 作为目录便捷提示，或通用 target-dir |
| DeepSeek Harness | `$DSH_HOME/skills`，未指定时 `~/.dsh/skills`；也有 Agents/custom roots | `--host deepseek-harness` 尊重 DSH_HOME；自定义 roots 用 target-dir；仍须确认当前配置启用技能加载 |
| WorkBuddy | 官方提供“添加技能 → 上传技能”导入本地包；实际用户目录由版本/配置决定 | 优先原生导入同一 ZIP；Agent 从本机配置确认目录后也可用 target-dir；不写死未经验证的目录 |
| Codex / 其它 Agent Skills 宿主 | 使用各自文档及当前配置 | 不需要为了本包切换到 Codex；已知 Codex 用户目录可用 --host codex，其它宿主用 target-dir或原生导入 |

Windows 的 `~` 是当前用户目录，macOS 的 `~` 同样由当前宿主解析；不要复制作者机器的用户名或目录。模型服务名不等于客户端名，例如某客户端使用 DeepSeek 模型，并不能据此认定它是 DeepSeek Harness。

本包不修改客户端插件组合、自动授权、系统信任中心或云端模型配置。客户端内置隔离环境与真实本机文件系统可能不同，须确认安装位置对后续会话持续可见。仅有聊天、无法读写本地目录或调用文档工具的环境，不能靠上传本包自动获得缺失的系统能力。

官方来源（2026-10-20核对）：

- [Agent Skills 规范](https://agentskills.io/specification)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [DeepSeek Harness 的技能目录实现](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/src/index.ts)
- [WorkBuddy 本地技能包导入](https://cloud.tencent.com/document/product/1831/134432)
