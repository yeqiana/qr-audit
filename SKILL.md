---
name: qr-audit
description: "QR Audit: offline QR code scanning, source-code auditing and preprocessing strategy contribution analysis for Codex and Claude Code. 二维码离线扫描、28 条初始策略注册表、策略归因、Markdown/HTML 报告；内置参考扫描只支持 V01–V03。"
---

# QR Audit

二维码离线扫描、策略审计、贡献度实验与报告交付 Skill。

## 目标与边界

目标是尽量降低人工扫描和复核比例，同时保留现有识别能力。所有策略调整必须以真实代码和可复现实验为依据。

**必须遵守：**

1. 全程离线。不得登录微信，不得上传图片，不得访问、预览、请求或跟随二维码载荷中的 URL。
2. 原图、现有源码、现有扫描结果和既有报告默认只读。不得覆盖、删除、重命名或移动它们。
3. 不因策略名称相似、单条策略独占贡献为零、执行次数多或耗时较高，就自动删除、合并或修改策略。
4. 28 条初始策略完整保留为基线策略库。实际是否实现、参数是什么、是否被执行，必须以源码和运行证据为准。
5. 区分图片文件数、配对数、策略定义数、实际执行次数、候选检测数、解码成功数、业务可用数和人工复核数。
6. 离线解码成功不等于微信 App 实扫成功；候选检测不等于解码成功；解码出载荷不等于业务语义有效。
7. 不自动修改扫描器业务代码、不自动删除策略、不自动安装依赖。需要安装依赖或修改现有扫描器时，先给出影响和命令，等待用户明确授权。
8. 每次运行使用独立输出目录；输入、源码、依赖、策略注册表和配置均记录指纹。不得把历史运行数据冒充本次结果。

## 触发场景

- 扫描本地目录中的二维码图片，微信不可登录或不可用。
- 比较 WAVES_QR / WAVES_QR_RAW 或其他成对目录的离线解码结果。
- 审计 ZXing-C++、OpenCV、ZBar 或其他本地解码器的实际调用和选项。
- 审计图像预处理变体、执行顺序、条件分支和提前停止逻辑。
- 计算策略顺序新增、重复成功、独占贡献、平均耗时、P95 和整类策略移除损失。
- 生成按目录分类的 Markdown 与 HTML 扫描报告。

## 运行新鲜度、并发与反过度设计约束（v1.3）

1. **每次扫描启动新的 Python 进程并生成新的 run_id**；使用明确的本次源码入口，不调用历史临时脚本或旧目录的复制品。**禁止为保证“最新”而每次重新编写算法**：复用经过版本固定的核心代码才可比较、复跑。离线时不能证明与远端 GitHub 最新 HEAD 一致，只能证明本次实际使用的本地源码指纹。必要时由操作者先明确选择要运行的 Git ref。
2. 扫描前冻结输入、策略/解码器、参数、配置及已加载源码文件 SHA-256；结束时重新校验，`source_consistency=CHANGED` 必须阻断有效结论。不存在的原生实现不得用空函数充数。并发任务必须共用同一次运行的冻结版本。
3. 默认 `--workers 1`；仅在本地解码器/适配器确认线程安全时比较 `--workers 2/4/8`。worker 分配不同图片，单协调线程按固定输入顺序写唯一 evidence 文件；不能多个 worker 同时覆盖清单或历史报告。Git worktree 用于开发/对照实验，不等于提高扫描吞吐。
4. 常规 `scan` 可按成功早停；`contribution` 严禁早停、要求完整矩阵和正式来源核验，策略/解码器缺失必须显式报告。单纯增加 worker 不得宣称提升识别率。
5. 新算法只能在隔离工作区试验，对**相同输入 SHA-256**进行基线与候选对比；优先改善正确解码配对数，其次观察错误载荷、异常、P95、总耗时和资源。没有独立真值时只能报告离线解码覆盖，不能宣称准确率。
6. **只保留 Scanner / Evidence / Report 三层**，第一版不引入 Redis、数据库、队列、多节点、Agent 调度框架。修改必须有可定位的问题、最小测试和可量化收益；不自动删除零观察贡献策略。

完整实施与 1/2/4/8 worker 性能门槛见 `docs/scanning-optimization.md`。

## 运行模式

| 模式 | 用途 | 成功后提前停止 |
|---|---|---|
| `scan` 常规扫描 | 控制耗时，尽快得到可用解码结果 | 允许；后续未执行策略必须记录原因 |
| `audit` 策略审计 | 只读检查源码、依赖、配置、调用链和策略实现 | 不适用 |
| `contribution` 贡献度实验 | 统计每条策略及策略类别的真实贡献 | **禁止** |
| `all` 全流程 | 先审计，再常规扫描，再贡献度实验和报告 | 常规扫描允许；贡献度实验禁止 |

## P0：运行前检查

开始扫描前必须完成：

1. **确定路径**：记录 `workspace_root`、`input_root`、`report_root`、`tool_root`。用户给出明确路径时以用户路径为准，不从历史路径猜测。
2. **读取项目规则和现有实现**：检查 `AGENTS.md`、`CLAUDE.md`、README、脚本说明、依赖锁定文件；盘点现有扫描脚本、预处理实现、解码器、参数、配置、日志和历史结果。
3. **检查环境**：识别本地离线解码器及准确版本。ZXing-C++、OpenCV、ZBar 只是候选，不代表当前环境已经安装。需要下载模型或安装依赖时先征求用户授权。
4. **保护输入**：对输入文件生成清单和 SHA-256；跳过符号链接、目录联接、报告目录、工具目录和明确排除目录；不得把输出目录再次作为输入。
5. **建立运行身份**：生成唯一 `run_id`，保存 `run-manifest.json`、`inventory.json`、`attempts.jsonl`、运行日志和源码/依赖指纹。运行目录已存在时停止，不覆盖。

## 输入目录发现与配对规则

默认可识别成对目录名 `WAVES_QR` 和 `WAVES_QR_RAW`，但它们只是默认配置，不是 Skill 的硬编码业务限制。用户可指定其他名称。

1. 从 `input_root` 开始递归发现所有成对组和含直接图片的独立目录，不因先发现一个配对组就停止发现其他单目录组。
2. 配对目录中的左右侧目录作为组内两侧，不再被重复识别为独立组；若组根目录本身也含图片，则另建仅包含根目录直接图片的单目录组。
3. 单目录组只收集该目录直接包含的图片；其子目录继续递归发现，避免父组递归吞并子组并重复计数。
4. 根目录、子目录同时存在配对组与单目录组时，全部纳入 inventory。
5. 缺少配对目录时仍生成该侧报告和总报告，并明确标记 `MISSING_DIRECTORY`。
6. 默认按相对路径配对，统一 `/`、Unicode NFC，并按 Windows 不区分大小写规则比较。按 basename 配对必须由用户明确指定，并检查重名歧义。
7. 文件名相同但载荷不同必须标记 `PAYLOAD_CONFLICT`。
8. 未配对文件仍需独立扫描并进入总报告。

## 能力 A：离线扫描

1. 先执行现有扫描器的原图/基线扫描，保留所有解码器各自的结果。
2. 仅调用已确认本地存在、可离线运行的解码器。
3. 解码器之间保持独立结果记录，不把解码器名称误当成预处理策略名称。
4. 对每张图片记录：`image_id`、组、侧、相对路径、原图 SHA-256、解码器 ID/版本/选项、策略 ID/顺序/参数、状态、载荷或载荷 SHA-256、候选区域数、变体尺寸与 SHA-256、耗时、异常、跳过原因和执行时间。
5. 只检测到二维码候选区域但没有读出载荷，记为 `DETECTED_ONLY`，不能打勾。
6. 载荷非空且解码器确认 QR 内容，记为 `DECODED`。这只证明本地解码器读出了内容，不证明业务有效。
7. 多个解码器或策略返回不同载荷集合时标记载荷冲突并进入人工复核；单次识别到多个合法二维码按无序身份集合保留，不把多码本身视为冲突。
8. 对二维码载荷中的 URL 只按文本记录，绝不打开、请求、解析远端页面或跟随重定向。

### 外部扫描器桥接（可选）

对 Java/C++ 等原生扫描器，使用 `scripts/external_cli_adapter.py` 实现本地进程级适配：环境变量 `QR_AUDIT_BRIDGE_CONFIG` 指向桥接 JSON。该模块只传递文件路径、策略身份和必要执行上下文，不实现新的图像增强。只有当原扫描器在每次结果中确认 `run_id`、`image_id`、`input_sha256`、策略及解码器归属后，才记录该结果。桥接器不会打开二维码载荷 URL，但无法替不受信任的外部原生程序保证无网络行为。

未获取真实原扫描器源码与可执行程序时，只能交付桥接协议、合成执行证据和测试；不得把配置样例或合成执行器计为已接入的 28 个原生变体。详见 `docs/real-scanner-onboarding.md`。

## 能力 B：扫描器与策略源码审计

必须逐项核对源码，不得只根据策略名称判断：

- 策略定义与真实实现函数/类的映射；
- 图像变换与解码器选项的边界；
- 输入目录与解码器路径的区别；
- 参数默认值、覆盖来源、单位、像素上限和执行条件；
- 预处理顺序、短路、重试、异常吞吐和多码处理；
- 反色、旋转、降采样、`tryHarder`、`isPure` 等选项是否存在、当前版本是否支持、是否启用；
- 白边是否按二维码模块宽度计算，边框是否计入最大像素限制；
- 模块采样是否真正定位定位图案/网格、估算模块数并完成几何校正；若只是固定倍率缩放，不得称为模块级采样；
- 纯码模式是否只对单码、对齐、已裁剪/已矫正图像启用；
- 失败是否有明确分类，是否存在未记录的隐式重试；
- 依赖版本、模型文件、复跑命令和历史结果是否可复现。

审计结论必须区分 `SOURCE_CONFIRMED`、`RUNTIME_CONFIRMED`、`INFERRED`、`NOT_VERIFIED`。源码存在不等于运行时实际执行。具体 28 策略的接线与导出契约参见 `references/adapter-contract.md`。

## 初始 28 条策略库

完整清单位于 `assets/strategy-registry.initial.json`。必须保留全部 28 条定义，并以 `V01`–`V28` 稳定 ID 追踪。

策略库中的参数未知时保持 `null`，不得用猜测值补齐。每条策略的 `implementation_status` 初始为 `NOT_VERIFIED`，审计后才能更新证据状态；本 Skill 不自动改写用户现有策略代码。

**V1.1 内置扫描器能力边界：** `scripts/scan_images.py` 可以使用已经安装的 OpenCV 执行 V01 原图、V02 灰度和 V03 参考自动对比度（三者为本 Skill 的参考实现，非对用户现有代码的逐字复刻）。通过 `--adapter-module` 可注册现有策略和解码器执行器；V04–V28 未接入前仍记录 `NOT_RUN`。执行器接入不等于源码确认，加载的适配器源码会纳入指纹。

## 两种扫描调度与贡献度要求

### 常规扫描 `scan`

- 允许成功后提前停止，以控制扫描成本。
- 对每张图片记录实际执行的策略和解码器。
- 未执行的后续策略记录 `SKIPPED_EARLY_STOP` 及原因；因图像特征不适用的策略记录 `SKIPPED_INELIGIBLE`。
- 常规扫描可用于成功率和耗时统计，但**不能单独作为完整策略贡献度证据**。

### 贡献度实验 `contribution`

- 对每张图片逐一执行所有符合条件的策略和规定的解码器组合。
- **关闭成功后提前停止**；发现任何 `SKIPPED_EARLY_STOP` 都判定本次贡献度实验不完整。
- 对不适用策略仍写入跳过记录，说明 `skip_reason`。
- manifest 必须声明图片集合、策略顺序、解码器集合和预期组合；每个预期组合必须有执行或跳过记录。每条 attempt 绑定 run_id、图片身份、输入 SHA-256、策略、解码器、attempt_id 和连续重试序号。
- 必须使用 schema 2.0 证据契约；同一逻辑组合允许多次 attempt，但 attempt_id 不可重复、attempt_index 必须从 1 连续递增，矛盾重试载荷必须阻断贡献度结论。
- 扫描前后重新清点输入，识别内容变化、新增和删除；校验器必须读取 before/after 两份 inventory 并重新计算差异，不能只信任 manifest 的 STABLE 字段。贡献度分析时还要重新哈希当前输入文件，防止扫描结束后图片再次变化。输入变化时保留证据，但将本次实验标记无效，不发布有效贡献度结论。
- 分别核验 inventory、策略注册表和源码文件指纹。结构校验 PASS 不代表来源已验证；贡献度结论必须要求 provenance VERIFIED。
- 配对身份使用组 ID + 规范化配对键生成的 pair_id；文件级和配对级成功、独占贡献、类别移除损失必须分别统计。
- 相同策略的多解码器结果分别保留，再按图片集合汇总策略效果。
- 若执行失败、超时、进程中断或预期组合缺失，贡献度结论标记 `INCOMPLETE`，不得把缺失统计成零贡献。

### 必须统计的指标

对每条策略至少计算：

- `success_images`：该策略至少有一个解码器成功读出载荷的图片数；
- `ordered_new_success`：按既定策略顺序，首次由该策略找回的图片数；
- `repeat_success`：该策略成功但此前策略已经成功的图片数；
- `exclusive_contribution`：完整贡献度实验中，仅该策略成功、其他策略均未成功的图片数；
- `attempt_count`、`skipped_count`；
- 平均耗时、P95 耗时；
- 按组、目录侧、图片配对情况的分组统计；
- 载荷冲突数量和候选检测数量。

**整类策略移除损失必须计算：**

`removal_loss(group) = all_strategy_success_images - success_images_after_removing_group`

例如 `pure_mode` 类别要把所有带纯码模式的策略一起移除，再计算损失。单条策略 `exclusive_contribution = 0` 不代表整个纯码分支可以删除。

如果贡献度实验不完整，`exclusive_contribution` 和 `removal_loss` 必须输出 `NA/INCOMPLETE`，不能输出伪造的 0。

统计脚本：`scripts/analyze_contributions.py`。统一证据契约：`scripts/evidence_contract.py`；命令行校验入口：`scripts/validate_evidence.py`。直接调用统计脚本与统一入口必须共用该契约。文件级 CSV 与配对级 CSV、类别移除损失必须分开输出。载荷比较仅在算法与数据范围相同时进行；哈希-only 证据必须声明 hash scope。

## 结果状态语义

| 状态 | 含义 | 是否打勾 |
|---|---|---|
| `DECODED` | 本地解码器读出非空 QR 载荷 | 是（仅表示离线解码） |
| `DETECTED_ONLY` | 检测到二维码区域，但没有读出载荷 | 否 |
| `NO_DECODE` | 已执行策略但未解码 | 否 |
| `ERROR` | 解码器或预处理执行异常 | 否 |
| `SKIPPED_EARLY_STOP` | 常规扫描因提前停止而未执行 | 否 |
| `SKIPPED_INELIGIBLE` | 经明确条件判断，该策略不适用 | 否 |
| `MISSING_DIRECTORY` | 预期目录不存在 | 否 |
| `PAYLOAD_CONFLICT` | 同一配对图像的解码载荷不一致 | 需人工复核 |
| `MANUAL_REVIEW_REQUIRED` | 自动流程不能可靠给出唯一结论 | 需人工复核 |

报告必须独立展示本地离线解码状态、候选检测状态、微信 App 实扫状态（默认 `NOT_TESTED`）、业务可用性（默认 `NOT_VERIFIED`）和人工复核状态。

## 报告交付

每个图片组至少生成三份 Markdown，并为每份 Markdown 生成同名 HTML：

1. 左侧目录扫描结果；
2. 右侧目录扫描结果；
3. 两侧配对总扫描结果。

缺失一侧时仍生成对应的缺失目录报告和总报告。总报告列出配对键、左右文件名、左右解码状态、载荷一致性；只要任一侧 `DECODED`，该配对的“任一目录离线解码”列打勾。若两侧载荷不同，仍显示各自解码成功，同时标记冲突和人工复核。

每份报告至少包含组名、目录名、图片名称/相对路径、图片文件数、配对数、策略定义数、实际执行次数、成功/候选/失败/异常/跳过/复核数量、成功策略、解码器、耗时、载荷、微信实扫边界、run_id、输入指纹、源码/依赖版本、生成时间、失败原因和证据路径。

使用 `scripts/render_reports.py` 从同一份结构化报告模型生成 `.md` 与 `.html`。不要先生成 HTML 再反向生成 Markdown，也不要对 Markdown 表格简单按 `|` 拆分。

## GenUI / HTML 集成

参考 [PlanShip 的 Gen UI 集成规范](https://github.com/yeqiana/plan-ship/blob/main/references/gen-ui.md) 的交付方式：Markdown 是可读、可 diff 的正式报告；HTML 是同名、可离线打开的阅读副本。

1. 如当前宿主已经安装并加载了 [`gen-ui`](https://github.com/yeqiana/gen-ui)，按 `references/skill-discovery.md` 定位并实际读取其 `SKILL.md` 和必要协议文件，再按其真实协议组织对话内呈现；不得猜测协议或声称已经加载不存在的 Skill。
2. 报告 HTML 由本 Skill 的 `scripts/render_reports.py` 从结构化数据同步生成，不依赖外部网络、CDN、字体、JavaScript 或浏览器插件。
3. HTML 必须内嵌 CSS，包含 viewport、语义化标题、表格表头、键盘焦点样式、移动端布局和打印样式。
4. HTML 使用严格内容转义；二维码载荷按文本显示，不自动生成可点击链接。
5. HTML 不伪造筛选、搜索、图表交互或动态状态。Mermaid 源码可以作为静态文本展示，不得声称已渲染成交互图。
6. 每份 MD 与 HTML 必须来自同一 `report-model.json`，记录模型 SHA-256，确保状态、数量、表格内容一致。
7. 若 `gen-ui` 未安装或未被当前宿主加载，仍可使用本 Skill 自带静态 HTML 生成器；如实记录 UI Skill 未检测到，不把静态 HTML 描述为动态交互界面。

## 推荐工作区布局

```text
<workspace_root>/
  qr-tools/
    qr-audit-v1.2.0/
  检测文件/
    <组A>/
      WAVES_QR/
      WAVES_QR_RAW/
    <组B>/
      WAVES_QR/
      WAVES_QR_RAW/
    report/
      <run_id>/
        0. 扫描总览.md
        0. 扫描总览.html
        01-<组A>/
          1. <组A>-WAVES_QR-扫描结果.md
          1. <组A>-WAVES_QR-扫描结果.html
          2. <组A>-WAVES_QR_RAW-扫描结果.md
          2. <组A>-WAVES_QR_RAW-扫描结果.html
          3. <组A>-二维码-总扫描结果.md
          3. <组A>-二维码-总扫描结果.html
        evidence/
          inventory.json
          run-manifest.json
          attempts.jsonl
          strategy-contribution.csv
          strategy-group-removal-loss.csv  # 仅完整贡献度实验
          logs/
```

实际目录名由用户参数决定。`report/` 必须从图片输入发现中排除。

## 执行顺序

1. 读取需求和项目规则，确认 workspace/input/report 路径。
2. 只读盘点目录、源码、依赖和历史结果。
3. 可选导出本 Skill 辅助工具到 workspace 的独立版本目录，不覆盖现有文件；实际扫码需要已安装的 OpenCV 或可对接的项目现有解码器。
4. 生成输入 inventory、配对清单和 SHA-256。
5. 审计现有策略实现，输出事实等级。
6. 执行常规扫描（用户要求时）。
7. 若已对接并审计现有 28 条策略执行器，执行完整贡献度实验且关闭提前停止；否则标记 `BLOCKED_NOT_CONNECTED_TO_28_IMPLEMENTATIONS`，不得通过内置 V01–V03 冒充 28 条。
8. 校验 evidence；不完整就标记 `INCOMPLETE`。
9. 生成每组 3 MD + 3 HTML；生成总索引和 CSV。
10. 检查报告内容一致、原图指纹未变化、输出目录独立。
11. 汇报真实结果、未验证项和人工复核清单。

## 禁止事项

禁止登录微信、调用微信客户端、访问二维码 URL 或上传图片；禁止改写/覆盖原图、源码、历史报告或已有运行目录；禁止未获授权安装依赖、下载模型、联网或调用在线解码服务；禁止把候选检测、载荷非空、业务可用、微信支持混为一个状态；禁止把常规扫描的提前停止数据用于完整贡献度结论；禁止把未执行策略计为失败或零贡献；禁止仅凭单条独占贡献为零删除整类策略；禁止自动删除、合并、重排或修改用户现有策略；禁止虚构耗时、解码结果、成功率、运行次数、源码确认或验收通过。


## 统一工具入口（可选 Python）

```powershell
$skill = "$HOME\.agents\skills\qr-audit"
$project = "D:\workSpace\本地电脑\03-图片扫描检测"
python "$skill\scripts\run.py" scan --input-root "$project\检测文件" --report-root "$project\检测文件\report" --workspace-root "$project" --decoder opencv
# 对接已审计执行器后，贡献度模式不提前停止：
python "$skill\scripts\run.py" scan --experiment-mode contribution --input-root "$project\检测文件" --report-root "$project\检测文件\report" --workspace-root "$project" --adapter-module my_qr_adapter --decoder opencv
python "$skill\scripts\run.py" audit --source-root "$project\qr-tools" --output "$project\检测文件\report\<run_id>\evidence\audit-hints.json"
# 对接并完整执行本地28策略后，再输入本次贡献度专用 manifest 和 attempts：
python "$skill\scripts\run.py" contribution --manifest "<manifest.json>" --attempts "<attempts.jsonl>" --inventory "<inventory.json>" --inventory-after "<inventory-after.json>" --out-dir "<新输出目录>"
```

`scan` 依赖当前机器已有的 `opencv-python` 与 `numpy`；若没有，停止并提示依赖缺失，不静默安装。`audit`/贡献度统计/HTML 渲染核心部分使用 Python 标准库。

## 真实识别率提升：独立实验策略（v1.4）

**核心目标是新增正确解码文件/有效配对，而非增加预处理策略数量。** `assets/strategy-registry.initial.json` 中 V01–V28 保持原样。由于另一台机器的真实预处理实现不在本仓库内，新增的 B01–B05 是**独立参考实验**，不能用 B 策略的结果冒充 V 策略的完成接线、独占贡献或原业务识别率提升。

- `--registry-path assets/strategy-registry.boost.json --adapter-module recognition_boost_adapter` 显式启用 B 系列；默认扫描仍采用 V01–V28，不会自动混用。
- B01 为原图；B02 最近邻放大与补白色静区；B03 Otsu 二值化与补静区；B04 CLAHE+Otsu；B05 高斯自适应阈值。按实际图像尺寸和像素预算限制输出；算法使用已经安装的本地 OpenCV/NumPy，不联网安装。
- 优先验证 G5 裁剪和 G2 亮度攻击：仅当二维码主体仍可恢复时补静区/局部二值化可能有帮助。缺失的模块无法凭空恢复。
- 对**完全相同 SHA-256 输入集**，分别运行默认基线和 B 实验。必须比较**真实人工正确答案**、新增正确解码文件/配对、候选丢失、错误载荷、异常、耗时、资源；无真值只能称“新增离线解码覆盖”，不能称准确率提高。
- 先使用 `scan --workers 1` 做小批验证，策略调优与并发调优分开；全量贡献度需 `--experiment-mode contribution` 无早停并通过来源/矩阵验证，绝不能从普通早停扫描推导独占删除损失。

详情见 `docs/recognition-boost.md`。

## P0：版本升级必须通过识别能力零回退门禁（v1.4.1）

**结构校验 PASS / provenance VERIFIED / 28 条注册表 / 生成报告成功，都不等于保留旧版识别能力。** 在对外宣称“升级成功”之前必须：
1. 核验当前执行入口调用真实原扫描器，检查历史关键成功策略（尤其 V04 Otsu+放大+白边、V10 纯码、V11/V12 8倍放大）与旧 decoder 选项。代码中存在注册定义不代表已执行。
2. 在扫描前用 `--require-strategy` 强制检查必须接入的旧策略。缺少执行器即 `REQUIRED_STRATEGY_NOT_CONNECTED` 并拒绝启动；不得退回到仅 V01–V03。
3. 用 `--baseline-evidence` 指定同输入哈希的旧 run；对**每张历史成功图片、每个成功配对及全部已观测载荷身份**做零丢失校验，发现任何回退都返回非零并标记 `BLOCKED_RECOGNITION_REGRESSION`。
4. 真实输入不存在、基线原始证据不足或配对身份无法对齐时，不得宣称已防止退化。先在真实扫描机器核对，保留历史原始证据。
5. 新增 B01–B05 只能作为补充实验，不得替代旧原生 V01–V28。新识别收益必须在全部旧成功集合保持的前提下单独报告；同总数不等于零回退。

详细的运行、验收与限制见 `docs/recognition-regression-gate.md`。**没有传基线运行只能称普通扫描结果，不得称升版回归验收通过。**

## v1.5.0：四槽合并验收与亮度专项实验

**产品目标：增加真正正确解码的文件/配对，同时严格保留历史成功集合。** 本次审计已确认同输入 2560 张、1280 对，历史431张/409对均保留，但本地执行没有新增覆盖，也未真实接入 V04–V28，B01–B05 未执行。这些是**历史实测证据**，不能当作 v1.5 的新扫描成绩。

1. **历史零回退必须在底层强制执行**：`scan_images.run_scan` 已内置 `baseline_evidence` / `require_upgrade_gate`。给使用低层入口的本地 Runner 设置 `QR_AUDIT_BASELINE_EVIDENCE=<历史evidence绝对目录>`、`QR_AUDIT_REQUIRE_BASELINE=1`，或传显式参数；缺基线运行前阻断，退化退出码3。没有基线的普通离线扫描只允许称 `PASS_BASELINE_ONLY`，不可叫升级验收通过。旧 inventory 中 `left_ids/right_ids` 可只读兼容。
2. **旧原生接线审计**：`native_coverage_audit.py` 检查 V04/V10/V11/V12 是否有真正的 native 调用记录与来源标识。仅 R 策略有成功不代表 V 策略迁移完成。没有原始本地 `baseline_scanner.py` 时不得谎称旧V已经恢复。
3. **亮度专项 opt-in**：原 B01–B05 不变，新增 B06（动态Gamma）、B07（Sauvola局部二值化）、B08（低频背景光照校正+Otsu），仅在指定 boost 注册表及适配器的实验模式中执行；不改变默认旧版扫描配置。
4. **独立 WeChatQRCode opt-in**：`wechat_decoder_adapter.py` 为 `wechat` 解码器，需指定已经存在的本地模型及 `QR_AUDIT_WECHAT_MODEL_CONFIG`；OpenCV4使用4个Caffe文件，OpenCV5使用2个ONNX文件。绝不自动下载安装，不等价于微信App扫码。
5. **同输入A/B**：先在已知载荷真值的小样本确认新增正确解码、错误载荷、失去的成功、配对覆盖、P95/CPU/RSS；通过后才允许原电脑2560张全量零回退验收。四槽代码合并或 CI 合成测试不能替代实物扫码验证。

实施说明：`docs/recognition-regression-gate.md`、`docs/native-coverage-acceptance.md`、`docs/brightness-experiment.md`、`docs/wechat-decoder-experiment.md`。不增加数据库/MQ/服务部署层。


## v1.5.1 · 三类离线识别增强已接入可选失败兜底

**上线条件**：只有真实旧策略无解码结果时，才启动补静区/放大、Gamma/Sauvola/背景校正等 B01–B08，随后如有本地模型，可使用 W01 WeChatQRCode 原图兜底。仅通过显式 `--boost-fallback` / `--wechat-fallback` 启用；**默认识别流程不变**。V/R 原生/参考策略及其身份不可被 B/W 替代。

- 用户原电脑的历史输入（2,560张、1,280对）仅有已知的 431张/409对基线；截至该版本未能在此连接机器验证新增覆盖。因此不得以 CI 合成结果宣称真实识别率已提升。
- `run_scan` 的输出将追加 `evidence/strategy-registry.effective.json`（本次合成注册表，不修改原注册表）、`evidence/fallback-summary.json`（本次观察到的新增文件/配对及贡献策略，未认证载荷真值）。旧成功必须经 `--baseline-evidence` 同输入按图像及载荷集合做零回退验收。
- 新增标准 OpenCV/ZXing 解码器只执行 B 策略；本地原生 source_file 解码器仅执行原注册表；WeChat 仅执行最后的 W01，必须预先具备本地模型与支持的 OpenCV，缺模型直接阻断，不静默跳过。初次建议 `workers=1`。
- 带原有真实 adapter / registry 调用方式见 `docs/failure-fallback-usage.md`；不要单独用默认 V01–V03 参考扫描替换之前原生/本地 R scanner；旧 V04/V10 接线完整性仍要独立验收。

## v1.5.2：大图防失效、区域透视恢复与微信增强组合

- **大图**：B02–B08 自动选择最高符合 8M 输出预算的 4/3/2/1 缩放倍数，连 1 倍都不满足则使用 INTER_AREA 按比例收缩；不可把这些自适应处理称为与旧版固定 4 倍算法完全等价。先通过真实旧执行器获取旧成功载荷。
- **B09**：使用 OpenCV detectMulti/detect 查找二维码四角，选择面积最大的有效定位框，做单码透视校正并在变换后补白边，最多约 8M 像素。无有效候选时有界全图兜底；不具备任意多个二维码候选的全部解析能力。
- **微信离线模型**：`--boost-fallback --wechat-fallback` 可在 B02/B04/B06/B08/B09 上尝试 WeChatQRCode，并保留 W01 最后原图尝试；不支持无本地模型运行。手机微信 App 人工扫码效果不等同这个模块。
- **证据**：`evidence/fallback-summary.json` 增加 rescue_by_decoder、rescue_by_strategy_decoder 观测指标。不可据此声称载荷正确，必须配合历史同输入零回退与人工真值。默认不开启增强，V/R 原注册表和顺序不变。参见 `docs/recognition-recovery-v152.md`。

## v2.0.0-ai.1（独立实验分支，不属于正式主线）

只在 `experiment/qr-ai-recovery-v2` 分支开启本地 `--ai-fallback --ai-model-config /path/ai.json`，在原V/R与已有B/W增强都失败时才运行 A01（本地 YOLO 专用二维码候选检测→多候选裁剪/角点透视修正→模块网格重建假设→OpenCV/ZXing/ZBar解码，另有可选 ONNX RGB超分）。不能把普通通用YOLO权重当作二维码检测器，更不能用AI生成载荷替代真正解码。

本版权重文件不随GitHub仓库分发、不会自动下载、也不会上传图像；依赖缺失或本地权重加载失败时拒绝开始。具体启用、模型/许可证约束、历史零回退和配对分析见 `docs/ai-recovery-experiment.md`。**合成模型测试不能证明 2560 张真实图识别率提升**。
