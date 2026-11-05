# QR Audit — 离线二维码扫描与策略审计 Skill

**Skill 名称：** `qr-audit`  
**版本：** `1.5.1`
**用途：** 二维码离线批量扫描、扫描器源码审计、策略贡献度实验，以及 Markdown + 静态离线 HTML 报告交付。

## 能做什么

- 递归扫描用户指定的单目录、多组目录或左右配对目录，混合结构不漏组。
- 默认识别 `WAVES_QR` / `WAVES_QR_RAW`，也支持用户指定其他目录名。
- 保留并追踪 28 条初始预处理策略。
- 审计真实源码、参数、解码器选项、提前停止和模块采样实现。
- 分开执行常规扫描与完整贡献度实验。
- 统计文件级与配对级顺序新增、重复成功、独占贡献、平均耗时、P95 和整类策略移除损失。
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
- `scan_images.py`：V01–V03 参考离线扫描器，支持普通扫描和关闭提前停止的贡献度模式；可通过适配器接入 V04–V28。
- `build_report_models.py`：由本次 attempts 和 inventory 构建每组左右及总报告。
- `audit_source.py`：只读源码关键词定位候选，不会把命中认定为实现已确认。
- `inventory_images.py`：输入图片清点、SHA-256 和目录配对。
- `analyze_contributions.py`：策略贡献度和整类移除损失。
- `validate_evidence.py` + `evidence_contract.py`：schema 2.0 证据归属、哈希、重试、来源和完整性校验。
- `executor_registry.py`：通用策略变换与解码器适配器注册契约。
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

# 将报告/统计辅助工具独立导出到项目下 qr-tools/qr-audit-v1.5.1
python "$skill\scripts\install_tools.py" --workspace "$project"
```

> `scan` 的返回状态是 `PASS_BASELINE_ONLY`，不等于全部 28 条策略均执行。贡献度分析必须同时提供 `manifest`、`attempts`、扫描前 `inventory`、扫描后 `inventory-after` 和冻结注册表；运行前后输入变化、来源指纹未核验、矩阵缺失、提前停止、未实现、不可用解码器或矛盾重试都会阻断有效贡献度结论。

## 证据契约与执行器接入

- 证据升级为 schema 2.0：attempt 必须绑定 run_id、image_id、group_id、side_id、相对路径和输入 SHA-256；重试使用唯一 attempt_id 与连续 attempt_index。
- 扫描前后重新清点图片，发现内容变化、新增或删除时保留证据但阻断有效贡献度结论。
- 文件级与配对级指标分开；pair_id 同时包含 group_id 和规范化配对键。缺失侧、单目录、歧义配对不强行纳入配对分母。
- 哈希-only 载荷必须明确 algorithm 和 scope；多二维码按无序身份集合比较；MD 与 HTML 使用同一判定模型。
- 通过 `--adapter-module` 注册真实策略和解码器；贡献度模式关闭提前停止。详见 [执行器接入契约](references/adapter-contract.md) 与 [证据契约](references/evidence-contract.md)。

## 真实扫描器接入（外部本地 CLI）

无需复制或重写原扫描器的图像增强算法。使用 [真实扫描器接入与验收](docs/real-scanner-onboarding.md) 中的配置，逐一登记经过源码确认的策略 ID 到原始扫描器策略 ID 的映射。

```powershell
$env:QR_AUDIT_BRIDGE_CONFIG = 'D:\\absolute\\path\\bridge-config.json'
python scripts/run.py scan --experiment-mode contribution --input-root 'D:\\images' --report-root 'D:\\reports' --adapter-module external_cli_adapter --decoder native
```

外部程序必须针对每次尝试返回与 run_id、image_id、原图 SHA-256 和 native_strategy 对应的 JSON 证据；无法对齐、缺少策略或执行异常均阻断可信贡献度结论。未接入本地真实扫描器前，不能宣称已完成 28 策略接入或降低 709 对样本的人工复核率。

## Gen UI 可选集成

与 [PlanShip](https://github.com/yeqiana/plan-ship) 一样，把 [gen-ui](https://github.com/yeqiana/gen-ui) 视为**可选的呈现规范**，不是 HTML 运行引擎或扫描依赖。若当前 Codex/Claude 会话已加载 `gen-ui`，按实际协议优化展示；缺失时使用本 Skill 内置离线 HTML 生成器，不阻断扫描，也不在未经授权时自动克隆其他 Skill。

## 隔离运行、可追溯与受控并发

- 使用明确的本次 `qr-audit/scripts/run.py` 入口，新的 Python 进程和新的 run_id；不要调用历史临时脚本或复制旧结果。
- 默认 `--workers 1`；可使用 `--workers 2`、`--workers 4` 或 `--workers 8` 进行**同输入**性能对比。当前是图片级有界线程池，不能保证每台机器都加速；本地原生适配器必须先验证线程安全。
- 在 `run-manifest.json` 查看 `execution`、`source_fingerprint`、`source_consistency`，源码在扫描期间被更改会标记 `BLOCKED_SOURCE_CHANGED`。
- `scan` 是快速覆盖，`--experiment-mode contribution` 才是无早停完整贡献度验证；两者不可混用。

```powershell
python scripts/run.py scan --input-root "D:\\images" --report-root "D:\\reports" --workers 1
python scripts/run.py scan --input-root "D:\\images" --report-root "D:\\reports" --workers 4
```

不要以“算法数更多、worker 更多、报告更长”为优化目标。参见 `docs/scanning-optimization.md`。

## v1.4.1 强制升级验收：旧成功样本零回退

如果仅运行 `scripts/run.py scan`，而没有传入历史扫描基线，它仍可能因为原生策略未接入只执行 V01–V03。因此不能将 `PASS_BASELINE_ONLY` 当作旧版识别能力保留的证明。

可使用 `--require-strategy V04 --require-strategy V10` 在扫描前检查必须的真实执行器，缺失则拒绝运行；完成后使用 `--baseline-evidence` 与旧扫描证据逐图片、逐配对和载荷身份比较。独立对照命令：

```powershell
python scripts/regression_gate.py --baseline-evidence "D:\\old\\evidence" --candidate-evidence "D:\\new\\evidence"
```

任一旧成功丢失、载荷不一致、输入 SHA-256 或配对结构不同都返回非零退出码；新增加成功不能抵消旧样本丢失。历史扫描共 431 张成功文件、409 个成功配对，只是**最小统计基线**，不能代替逐项比较。

另外修正安装器，确保带出 B01–B05 增强适配器、实验策略注册表和回归校验器。详见 `docs/recognition-regression-gate.md`。当前仓库的合成测试不能替代另一台电脑实际 2,560 图集验收。

## v1.5.0：识别能力保留 + 亮度与微信模型独立实验

四项并行改造：兼容旧版配对证据并在 **run_scan 底层**统一回归门禁、V04/V10等原生调用证据审计、B06动态Gamma/B07 Sauvola/B08背景校正、可选的OpenCV WeChatQRCode离线解码器。

**在用于验收升级的本机 Runner 进程环境中**明确传历史证据目录，避免低层 `scan_all.py` 绕过上层 `run.py`：

```powershell
$env:QR_AUDIT_BASELINE_EVIDENCE = "D:\\historical\\evidence"
$env:QR_AUDIT_REQUIRE_BASELINE = "1"
python scripts/run.py scan --input-root "D:\\images" --report-root "D:\\reports" --workers 1 --baseline-evidence "$env:QR_AUDIT_BASELINE_EVIDENCE"
```

上例只说明门禁用法：**不能直接用默认V01–V03参考扫描器替换原版**。恢复旧 V04/V10/V11/V12 必须由原电脑实际接入并有原生执行记录和零回退证据。新 B01–B08 需要显式 `--registry-path assets/strategy-registry.boost.json --adapter-module recognition_boost_adapter`；WeChat需额外 `--adapter-module wechat_decoder_adapter --decoder wechat` 及预先准备的本地模型。独立实验结果不能混同手机微信实扫效果。

参见 `docs/native-coverage-acceptance.md`、`docs/brightness-experiment.md`、`docs/wechat-decoder-experiment.md`。

## v1.5.1 实际失败兜底模式（保留旧路径）

之前 B01–B08 和 WeChatQRCode 需要单独实验，现在增加**可合成原有注册表的执行路径**：`--boost-fallback` 在原生/参考策略失败后依次执行 B01–B08；`--wechat-fallback` 在此基础上把 W01 微信离线模型放到最后（需预先在本地配置模型，不等于手机微信本身）。

原注册表始终不修改，完整实际注册表保存 `evidence/strategy-registry.effective.json`；本轮新增观测成功汇总保存 `evidence/fallback-summary.json`，详细说明与本地命令见 [失败兜底正式接线说明](docs/failure-fallback-usage.md)。

注意：**必须传入你真实使用的旧扫描器配置、适配器、解码器和历史基线**。如果使用默认参考 V01–V03，即使组合增强能扫出图片，也不能把它当成原原生扫描器的升级证据。当前仍未在你的真实 2560 张数据上重新测量正确成功率。
