# Gen UI 可选技能发现（与 PlanShip 对齐）

[`gen-ui`](https://github.com/yeqiana/gen-ui) 是可选呈现规则，不是扫码依赖，不是 HTML 运行时。

1. 先检查当前宿主实际激活的 Skill 列表；仅“文件夹存在”不能证明已激活。
2. Codex/Claude 的候选位置包括 `~/.agents/skills/gen-ui/SKILL.md`、`${CODEX_HOME}/skills/gen-ui/SKILL.md`、`~/.claude/skills/gen-ui/SKILL.md`、当前项目 `.agents/skills/gen-ui/SKILL.md` / `.claude/skills/gen-ui/SKILL.md`。以宿主实际生效位置为准。
3. 若当前宿主已加载，读取其 `SKILL.md` 和必要的协议参考后，将其用在对话展示与报告的可读性审查上。
4. 若不存在或未加载，按 `references/genui-html.md` 使用内建静态 HTML/MD 双格式。**不阻断扫码，不擅自联网安装、clone 或修改宿主配置。**
5. 仅用户明确要求安装时，才考虑安装到当前宿主已存在的技能目录，并先核对来源、目录冲突和权限。
6. 不能把生成的静态 HTML 称为 Gen UI 动态组件。没有脚本和外部依赖时也不能宣称有实时过滤/搜索互动。

参考 [PlanShip 公开集成规范](https://github.com/yeqiana/plan-ship/blob/main/references/gen-ui.md)。
