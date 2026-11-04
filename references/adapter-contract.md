# 现有 28 条扫描策略的接入契约

`qr-audit` 的内置 Python 参考扫描器只能做 V01–V03 基线扫描。要测量**原有 28 条策略的真实贡献**，应复用用户项目中的解码器与原有预处理函数，而不是按名称凭空重写。

## A. 先审计、后接线

1. 阅读扫描入口及解码器实际依赖，定位当前全部 28 条策略的实现（若未找到，标 `NOT_VERIFIED`）。
2. 给每条策略建立 `V01`–`V28` → 源码文件/函数/参数/执行条件的映射。
3. 审计 `isPure`、`tryInvert`、`tryRotate`、`tryDownscale` 和是否有多码成功后短路。
4. 记录源码 Git HEAD、dirty 状态、相关文件 SHA-256 和运行配置 SHA-256。
5. 只在获得用户同意后添加少量日志/适配代码；优先通过独立包装调用原有函数，不改变其图像处理细节或参数。

## B. 每次尝试的最小接口

建议包装层提供与下面行为等价的调用（这是契约，不是宣称用户代码已经有这个接口）：

```python
# 伪代码，仅说明协议，不直接运行
attempt = execute_existing_variant(
    image_path=image_abs_path,
    strategy_id='V23',
    decoder_id='zxingcpp',
    disable_early_stop=True,
)
```

返回记录必须包含 `run_id`、`image_id`、`strategy_id`、`decoder_id`、`status`、`duration_ms`、载荷或载荷哈希、异常/跳过原因。优先保留完整多码结果（`all_payloads`），同时报告最先获得的载荷，以免多码时丢失信息。

不管策略成功与否，**贡献度模式**都必须完成该图像全部符合条件的策略和解码器组合。仅因成功解码而不继续执行是不合格的。

## C. 必须生成的证据

```text
<本次 run>/evidence/
  inventory.json
  run-manifest.json
  attempts.jsonl
  decoder-build-info.json       # 可选，对 OpenCV/ZXing 版本更精确
  source-audit.md               # 人工源码阅读及真实定位说明
  source-hashes.json            # 各代码/配置文件 SHA-256
  logs/
```

## D. 运行统计

所有行记录应能对应到 `manifest.images × manifest.strategy_order × manifest.decoders`。不能因为某条策略没有被执行，就省略对应 attempt 行。

用：

```powershell
python "<SKILL_ROOT>\scripts\validate_evidence.py" --manifest "<run>\evidence\run-manifest.json" --attempts "<run>\evidence\attempts.jsonl"
python "<SKILL_ROOT>\scripts\run.py" contribution --manifest "<run>\evidence\run-manifest.json" --attempts "<run>\evidence\attempts.jsonl" --out-dir "<新的贡献度统计目录>"
```

输出含 `strategy-contribution.csv`、`strategy-contribution-by-scope.csv`、`strategy-group-removal-loss.csv` 和完整 JSON。类别贡献是“完整类别移除后召回损失”，不能从若干单策略独占贡献求和推断。

## E. 禁止伪装的能力

`NOT_RUN` 和 `SKIPPED_INELIGIBLE` 必须写明原因。缺少实现、缺少解码器、网络不可用、没有读到源码，不能被包装成“图片没有二维码”。算法无法接入时停止完整贡献度结论，保留基线扫描和源码审计成果。
