# 运行证据数据契约

## 1. 文件清单

```text
<report_root>/<run_id>/evidence/
  inventory.json
  run-manifest.json
  attempts.jsonl
  strategy-contribution.csv
  strategy-group-removal-loss.csv
  logs/
```

## 2. run-manifest.json

正式实验建议字段：

```json
{
  "schema_version": "1.0",
  "run_id": "20261104T152000Z-unique",
  "mode": "contribution",
  "started_at": "2026-11-04T15:20:00+08:00",
  "input_root": "D:/workspace/input",
  "inventory_sha256": "sha256...",
  "strategy_registry_sha256": "sha256...",
  "source_fingerprint": {
    "git_commit": "abc123",
    "git_dirty": false,
    "files": [{"path": "qr-tools/scan.py", "sha256": "sha256..."}]
  },
  "dependencies": [{"name": "zxing-cpp", "version": "actual-version"}],
  "strategy_order": ["V01", "V02"],
  "strategies": [{"strategy_id": "V01", "groups": ["baseline"]}],
  "decoders": [{"decoder_id": "zxingcpp"}],
  "images": [{"image_id": "img-1", "group_id": "group-a", "side_id": "WAVES_QR", "path": "group-a/WAVES_QR/a.png", "sha256": "sha256..."}]
}
```

示例为缩略结构；正式实验应包含全部图片、实际策略和解码器。

## 3. attempts.jsonl

每行一个 JSON 对象：

```json
{
  "attempt_id": "run-1-img-1-V01-zxingcpp-1",
  "run_id": "run-1",
  "image_id": "img-1",
  "group_id": "group-a",
  "side_id": "WAVES_QR",
  "relative_path": "a.png",
  "input_sha256": "sha256...",
  "strategy_id": "V01",
  "strategy_order": 1,
  "decoder_id": "zxingcpp",
  "decoder_version": "actual-version",
  "decoder_options": {"try_harder": true},
  "status": "DECODED",
  "payload": "decoded text",
  "payload_sha256": "sha256...",
  "candidate_count": 1,
  "duration_ms": 12.4,
  "variant_width": 400,
  "variant_height": 400,
  "variant_sha256": "sha256...",
  "skip_reason": null,
  "error": null,
  "executed_at": "2026-11-04T15:20:01+08:00"
}
```

允许状态：`DECODED`、`DETECTED_ONLY`、`NO_DECODE`、`ERROR`、`SKIPPED_EARLY_STOP`、`SKIPPED_INELIGIBLE`、`NOT_RUN`。

跳过记录必须有 `skip_reason`。`DECODED` 应提供载荷或载荷 SHA-256。

## 4. 贡献度完整性

manifest 应声明 `images`、`strategy_order` 和 `decoders`。贡献度实验预期组合为 `images × strategies × decoders`。每个组合至少有一条 attempt，执行或跳过均可，但必须有明确状态和原因。`SKIPPED_EARLY_STOP` 会使实验失败。

## 5. 来源指纹

至少保存输入图片 SHA-256、策略注册表 SHA-256、扫描器相关源码 SHA-256、Git commit/dirty 状态、解码器包版本、模型文件 SHA-256、运行配置 SHA-256、运行时间、命令、退出码和日志 SHA-256。

指纹只能证明文件内容一致性，不能证明报告语义绝对正确或文件不可被篡改。关键结论仍需人工审阅。

## 6. 隐私和载荷

载荷只保存在本地证据中。报告按用户要求展示原始内容或预览；URL 只作为普通文本显示，不创建可点击链接、不访问目标站点。若载荷疑似凭据或令牌，应在可分享报告中脱敏，同时保留本地受控证据中的原始值及哈希。
