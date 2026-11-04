# QR Audit — 离线二维码扫描与策略审计 Skill

**Skill 名称：** `qr-audit`  
**版本：** `1.0.1`  
**用途：** 二维码离线批量扫描、扫描器源码审计、策略贡献度实验，以及 Markdown + 静态离线 HTML 报告交付。

## 能做什么

- 扫描用户指定的单目录、多组目录或左右配对目录。
- 默认识别 `WAVES_QR` / `WAVES_QR_RAW`，也支持用户指定其他目录名。
- 保留并追踪 28 条初始预处理策略。
- 审计真实源码、参数、解码器选项、提前停止和模块采样实现。
- 分开执行常规扫描与完整贡献度实验。
- 统计顺序新增、重复成功、独占贡献、平均耗时、P95 和整类策略移除损失。
- 输出每组至少 3 份 MD，以及每份 MD 对应的 HTML。
- 保留原图、源码、历史报告；每次运行独立留证。

## 快速触发

```text
$qr-audit 扫描：扫描 D:\workSpace\本地电脑\03-图片扫描检测\检测文件，
默认配对 WAVES_QR 和 WAVES_QR_RAW，离线运行，报告输出到检测文件\report。
```

```text
$qr-audit 策略审计：只读审计当前二维码扫描源码，核对 28 条策略的真实实现、参数、执行顺序、解码器选项和提前停止。
```

```text
$qr-audit 贡献度实验：对当前 inventory 中所有图片和所有符合条件的策略完整执行，不允许提前停止，计算单策略指标和整类策略移除损失。
```

```text
$qr-audit 全流程：先只读审计，再扫描并输出每组 3 份 MD + 3 份离线 HTML；若本机28策略执行器已对接则运行贡献度实验，否则明确标记阻断。
```

## 安装

解压 ZIP，复制完整的 `qr-audit/` 文件夹，不要只复制 `SKILL.md`。

### Codex（用户级）

```powershell
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item -Recurse ".\qr-audit" "$HOME\.agents\skills\qr-audit"
```

### Claude Code（用户级）

```powershell
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse ".\qr-audit" "$HOME\.claude\skills\qr-audit"
```

若目标目录已存在，先备份并确认版本，不要直接覆盖。实际加载路径以当前宿主为准。

## 辅助工具

本 Skill 的清点、证据校验、审计候选检索、贡献度分析和 HTML 生成使用 Python 标准库；**内置实际扫描器需要本机已安装 `opencv-python` 和 `numpy`**，`zxingcpp` 是可选的第二解码引擎。不会静默安装依赖。

- `run.py`：统一命令入口（scan、audit、contribution、all）。
- `scan_images.py`：可实跑的 V01–V03 离线基线扫描；V04–V28 需要对接现有项目实现。
- `build_report_models.py`：由本次 attempts 和 inventory 构建每组左右及总报告。
- `audit_source.py`：只读源码关键词定位候选，不会把命中认定为实现已确认。
- `inventory_images.py`：输入图片清点、SHA-256 和目录配对。
- `analyze_contributions.py`：策略贡献度和整类移除损失。
- `validate_evidence.py`：扫描尝试记录与实验完整性检查。
- `render_reports.py`：从同一结构化数据生成 MD + HTML。
- `install_tools.py`：将辅助工具安全导出到业务工作区的 `qr-tools/` 下。

注意：内置扫描器只实现 V01–V03 **参考**变体，虽然注册表保留 28 条，但其余 25 条未实现/未接线时会明确标记 `NOT_RUN`。完整 28 策略贡献度需要对接并核查本机现有实现；不能用三条策略的结果冒充全部策略。

## 自测

```powershell
python -m unittest discover -s "<Skill根>\tests" -v
python "<Skill根>\scripts\run.py" --help
python "<Skill根>\scripts\inventory_images.py" --help
python "<Skill根>\scripts\analyze_contributions.py" --help
python "<Skill根>\scripts\validate_evidence.py" --help
python "<Skill根>\scripts\render_reports.py" --help
```

## 关键限制

- 离线解码成功不等于微信 App 实扫成功。
- 候选检测不等于解码成功；解码成功不等于业务可用。
- 常规扫描允许提前停止，但不能据此计算完整策略贡献度。
- 贡献度实验必须关闭提前停止并记录每个预期组合的执行/跳过状态。
- 单条策略独占贡献为零，不代表整类策略可以删除。
- Skill 不自动修改源码、不自动删除策略、不自动联网安装依赖。


## Windows 真实运行示例

```powershell
$skill = "$HOME\.agents\skills\qr-audit"
$project = 'D:\workSpace\本地电脑\03-图片扫描检测'
$input = Join-Path $project '检测文件'
$reports = Join-Path $input 'report'

# 先按现有运行环境安装好 OpenCV / numpy（本 Skill 不自动联网安装）
python "$skill\scripts\run.py" scan --input-root "$input" --report-root "$reports" --workspace-root "$project" --decoder opencv

# 只读源码审计候选（不能以关键词命中代替人工核对）
python "$skill\scripts\run.py" audit --source-root (Join-Path $project 'qr-tools') --output (Join-Path $reports 'audit-hints.json')

# 将报告/统计辅助工具独立导出到项目下 qr-tools/qr-audit-v1.0.1
python "$skill\scripts\install_tools.py" --workspace "$project"
```

> `scan` 的返回状态是 `PASS_BASELINE_ONLY`，这意味着已执行的基础扫码有真实结果，但不等于全部 28 条策略均执行。完成完整贡献度实验后使用 `contribution --manifest ... --attempts ... --out-dir ...`，在矩阵缺失、提前停止、未实现或执行失败时严格返回阻断。

## Gen UI 可选集成

与 [PlanShip](https://github.com/yeqiana/plan-ship) 一样，把 [gen-ui](https://github.com/yeqiana/gen-ui) 视为**可选的呈现规范**，不是 HTML 运行引擎或扫描依赖。若当前 Codex/Claude 会话已加载 `gen-ui`，按实际协议优化展示；缺失时使用本 Skill 内置离线 HTML 生成器，不阻断扫描，也不在未经授权时自动克隆其他 Skill。