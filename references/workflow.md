# 工作流与运行门禁

## 1. 运行前确认

必须记录 workspace_root / input_root / report_root、左右目录名与配对规则、图片扩展名范围、可用解码器及版本、模型文件、扫描器源码路径、Git commit/dirty 状态、策略注册表 SHA-256、运行模式和 run_id。无法确认的项记录 `NOT_VERIFIED`。

## 2. 目录发现

默认配置：

```json
{
  "left_directory": "WAVES_QR",
  "right_directory": "WAVES_QR_RAW",
  "pair_key_mode": "relative_path",
  "recursive": true,
  "exclude_directories": ["report", "qr-tools", ".git", ".idea", "__pycache__"]
}
```

默认按相对路径配对，避免不同子目录中的同名文件误配。basename 配对必须显式启用；有重名歧义时标记 `AMBIGUOUS_PAIR`。

## 3. 解码器选择

优先复用现有本地扫描器。审计时将“解码器”和“策略”拆开记录：

- 解码器：负责识别/解码 QR 内容的实现。
- 策略：输入图像变换和/或解码器选项的组合。
- 目录侧：输入图片来自哪个目录，不代表解码器。
- attempt：一次确定的 `image × strategy × decoder` 尝试。

若扫描器内部已经执行反色、旋转、降采样或局部阈值，要读取当前依赖版本和实际配置；不能只根据库文档或默认值推断运行时状态。

## 4. 两种调度

常规扫描允许成功后停止，但每个未执行组合都应记录原因。常规扫描回答“给定预算和顺序下能自动解出多少”，不回答“每条策略真实贡献多少”。

贡献度实验必须声明预期矩阵 `images × eligible_strategies × configured_decoders`。每个组合必须有 attempt 记录。若不适用，写 `SKIPPED_INELIGIBLE` 和可复核原因；若超时或异常，写 `ERROR`。贡献度实验禁止 `SKIPPED_EARLY_STOP`。

## 5. 解码成功定义

`DECODED` 代表某个离线解码器返回了非空 QR 载荷。它不代表微信 App 一定能扫、URL 可访问、业务接口可用、载荷符合用户预期或左右目录载荷相同。同一图片由多个解码器返回不同载荷时，报告 `PAYLOAD_CONFLICT`。

## 6. 报告门禁

每组固定产出左侧、右侧、配对总表三类报告。缺失侧也要有明确报告。

配对总表勾选规则：

- 左侧或右侧任一为 `DECODED`：`任一目录离线解码 = ✓`。
- 两侧都存在且都没有 `DECODED`：`任一目录离线解码 = ✗`。
- 一侧缺失：显示缺失状态；若另一侧 `DECODED`，仍可标 `✓（仅现存侧）`。
- 两侧都解码但载荷不同：两侧分别显示成功，同时标记 `PAYLOAD_CONFLICT / MANUAL_REVIEW_REQUIRED`。

报告必须明确 `微信实扫 = NOT_TESTED`，除非用户实际完成微信实扫并提供证据。