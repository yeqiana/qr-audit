# 真实 28 策略扫描器接入与离线验收

## 目标与当前状态

将已有 Java/C++/Python 扫描器作为**原生执行器**接入 qr-audit，不改写其图像增强算法，不把 28 条注册表定义冒充 28 条真实执行。

当前仓库只包含 V01–V03 的 OpenCV 参考实现和通用适配契约。用户原始扫描目录及实际 28 条函数实现必须在同一可访问 Runner 下提供。没有这些文件时仅能完成协议与合成用例，不能给出真实成功率或人工复核降低幅度。

## 本地桥接结构

\`\`\`text
输入图片 (只读)
    ↓
inventory.json (原图 SHA-256 / 分组 / pair_id)
    ↓
qr-audit scan_images.py
    ↓ source_file / 无需 Python 重做图像预处理
external_cli_adapter.py (无 shell，限定超时，检验响应身份)
    ↓ 子进程 argv
真实 scanner.exe / java -jar scanner.jar / Python 模块
    ↓ JSON 结果 / 不访问二维码 URL
attempts.jsonl
    ↓
证据一致性与来源校验
    ↓
文件级/配对级贡献 CSV + MD/HTML
\`\`\`

桥接使用配置文件，而不是动态猜测 28 条策略。示例见 \`examples/native-cli-bridge/bridge-config.example.json\`。将样例复制到扫描器机器后逐项替换绝对路径与 native_strategy，**只有源码已定位的实际策略才允许注册**。缺一条就保留 NOT_RUN，完整实验不通过；不要用 identity/no-op 凑齐 28 条。

### CLI 请求与响应

对每个 \`image × strategy × decoder\`，进程收到原始图片绝对路径、SHA-256、run_id、image_id、strategy_id、native_strategy 和 decoder_id。

stdout 必须仅包含一个 JSON 对象。例如：

\`\`\`json
{
  "run_id": "run-20261104",
  "image_id": "image-fingerprint-id",
  "input_sha256": "64位原图SHA-256",
  "strategy_id": "V04",
  "native_strategy": "scanner-native-variant-name",
  "decoder_id": "native",
  "status": "DECODED",
  "candidate_count": 1,
  "payloads": ["https://example.invalid/qr-payload"]
}
\`\`\`

示例载荷仅作文本，不允许跟随链接。真实哈希必须是符合 SHA-256 规范的实际值。若仅保存载荷身份，则 payloads 中每个对象必须声明 \`identity.algorithm\`、\`identity.scope\`、\`identity.value\`；不要将 raw bytes SHA-256 伪标为 decoded_text_utf8。

响应字段与本次请求不一致、进程失败、超时、非法 JSON、非法状态或矛盾载荷将记录 ERROR；未实现或依赖不可用必须明确 NOT_RUN；业务不适用才是 SKIPPED_INELIGIBLE。

### Java/C++ 程序怎么适配

- C++：已有扫描器可通过一个极薄的 CLI 包装层解析这些 argv，并调用已有预处理函数、解码器，返回上述 JSON；不改变图像处理算法。
- Java：可在已有主类的 CLI 入口读取参数，或者编写独立包装器调用现有 Jar 的公开入口。若是 \`java -jar\`，配置 \`command.executable\` 为真实 java.exe 绝对路径，\`command.args\` 以 \`-jar\` 和 Jar 绝对路径开头。
- Python：已有模块如果可直接 import，优先使用 Python executor 接口；无法 import 时才通过 CLI 包装。

### 接入记录

应为每条策略留证：

| 字段 | 含义 |
|---|---|
| strategy_id | 注册表稳定 ID：V01–V28 |
| native_strategy | 原扫描器已有的函数/变体 ID |
| implementation_path | 已审计的源码类/函数及代码位置 |
| parameters | 真正使用的参数及来源 |
| decoder/version | 实际调用的引擎与版本 |
| input_sha256 | 原始图片的 SHA-256 |
| variant_sha256 | 变体内容指纹（如外部扫描器提供） |
| evidence_status | SOURCE_CONFIRMED / RUNTIME_CONFIRMED / NOT_VERIFIED |

桥接注册的函数不等于 SOURCE_CONFIRMED；必须人工/自动对照源码位置及运行日志。若原扫描器不支持每策略指定执行，应先明确此能力缺口，不伪造独立贡献。

## 运行命令

先确保当前扫描器机器已有 Python 3（仅本地 CLI 桥接不需要 OpenCV、NumPy；若同时运行参考像素策略则需要依赖）。不会自动安装依赖或下载模型。

\`\`\`powershell
$skill = 'D:\workspace\YeQianWorkSpace\yeqian\qr-audit'
$env:PYTHONPATH = Join-Path $skill 'scripts'
$env:QR_AUDIT_BRIDGE_CONFIG = 'D:\scanner\bridge-config.json'

# 少量已确认输入的离线冒烟：先允许提前停止
python "$skill\scripts\run.py" scan --input-root 'D:\scanner\smoke-input' --report-root 'D:\scanner\smoke-report' --adapter-module external_cli_adapter --decoder native

# 28 条均已接线并确认执行后：关闭提前停止，完整贡献度实验
python "$skill\scripts\run.py" scan --experiment-mode contribution --input-root 'D:\scanner\scan-input' --report-root 'D:\scanner\reports' --adapter-module external_cli_adapter --decoder native
\`\`\`

每次生成独立 run_id。会输出 before/after inventory、manifest、attempts 和报告。只有矩阵完整、无错误、原图稳定、源码与桥接配置指纹核验通过，才生成有效贡献 CSV。

## 必须验收的负面用例

- 将成功响应的 run_id、image_id、策略 ID 或输入哈希改为其他值，必为 ERROR。
- 扫描中替换文件但保留文件名，最终必须 BLOCKED_INPUT_CHANGED。
- 令外部程序返回错误 JSON、无 payload 的 DECODED、跳过缺少理由或两次重试载荷矛盾，应阻断有效贡献度。
- 删除任意一个 native_strategy 接线后，不能给出 28 策略完整结论。
- 两组相同 \`sample.png\` 不跨组配对；移除策略文件损失与配对损失必须独立。
- hash-only、多码集合和不可比较载荷都进入与报告一致的复核状态。
- 实际识别率需同一原始图片集回归，不可拿合成样例替代；仅使用新结果对比旧 709 对样本时还要核实原图 SHA-256 完全一致。

## 产出与后续限制

待接入真实扫描器后，优先输出 28 策略源码映射表、实际执行矩阵、各策略顺序新增/独占贡献、文件与配对类别移除损失、耗时分布、未解码样本队列和人工复核数量。

目前**未取得原扫描器的可执行程序、28 策略函数、原图目录**，因此不能宣称已经完成真实 28 策略接线、真实图片批量运行、微信实扫和人工比例降低。
