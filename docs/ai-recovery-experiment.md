# qr-audit AI 实验分支：检测、恢复、超分、多引擎与配对分析

**分支：`experiment/qr-ai-recovery-v2`。基线：`ee834706`（v1.5.2）。**

实验分支不替代生产主分支，且不包含实际权重文件或用户原电脑中的2560张真实图片。此次的“接入”指代码路径可执行；不能等同已经产生真实新增正确配对。

## 为什么不继续局限于 B 系列预处理

针对“检测到二维码但无法正确解码”和“传统定位器漏掉”的失败样本，增加一条完整独立的模型支路：

```text
原 V/R + B01-B09 + 可选 WeChatQRCode（保留原序）
                   │失败
                   ▼
       A01 本地 QR 专项 YOLO 检测器
                   ▼
  多候选 bbox / 分割多边形（最多 8 候选）
                   ▼
    ROI 裁剪 / 透视修正 / 静区与多尺度
                   ▼
   二维码模块数 21/25/... 网格假设
                   ▼
      OpenCV / ZXing-C++ / ZBar
                   ▲
            可选 ONNX 图像 SR
                   ▼
     DECODED 仅来自条码解码引擎
```

二维码网格恢复只产生**候选黑白模块图片**，不会猜测 QR 字符串。候选图像必须经二维码数据纠错校验的解码引擎才被记录为 DECODED。仍要独立标注真值防止假阳性。

## AI 模型条件

1. 事先准备一个 **专门训练用于二维码检测的** Ultralytics YOLO `.pt` 权重（普通通用物体检测权重不能当作 QR 检测模型），将其合法放到工作区本地。可以研究 [QRDet](https://github.com/Eric-Canas/qrdet) 或 [QReader](https://github.com/Eric-Canas/QReader) 的权重、测试方式和许可证，但必须验证权重与当前 `ultralytics.YOLO` 的实际兼容性。
2. 可选 ONNX 超分辨率模型，必须满足约定：输入 RGB/NCHW/`float32`/`[0,1]`，输出 RGB/NCHW/`float32`/`[0,1]`，形状严格为原图的 **2x 或 4x**。如不匹配，移除 `super_resolution` 字段，不应在适配器里伪造视觉提升。
3. Python 依赖由操作者在本机准备：`opencv-python`、`numpy`、`ultralytics`；可选 `zxing-cpp`、`pyzbar`（还需要本机 libzbar）、`onnxruntime`。工具不自行 pip 安装、不访问云识别 API、不下载任何权重。
4. **许可证需要核实**：Ultralytics YOLO 的 AGPL-3.0/企业许可约束可能影响发布和商业应用。AI 分支只用于独立评估，不把其依赖或权重强制加入主分支。

## 配置（本地、显式、可审计）

复制 `assets/ai-recovery.example.json` 到本地目录，例如 `D:\\models\\qr-ai.json`，修改 `detector.weights` 指向本机实际模型文件；相对路径以配置文件所在目录为基准。

```json
{
  "schema_version":"1.0",
  "detector":{"provider":"ultralytics","weights":"models/qr-specialized-detector.pt",
              "confidence":0.2,"max_candidates":8,"device":"cpu"},
  "max_attempts":180,
  "budget_seconds":30,
  "grid_versions":7,
  "zxing":true,
  "zbar":true
}
```

启用可选超分：

```json
"super_resolution":{"provider":"onnxruntime","weights":"models/qr-sr-x2.onnx","scale":2}
```

`budget_seconds` 是解码变体之间的**软预算**，不能抢占卡住的模型原生推理调用。每幅图的模型推理耗时/内存需在真实设备上另测，初期严格使用 `--workers 1`，避免多个线程复制大模型。

## 在原扫描电脑执行

先确认历史真实扫描器仍已接回 V04/V10 等原执行路径，并配置完整的注册表与原生适配器，保留原 431 张/409 对成功集合：

```powershell
$env:QR_AUDIT_BASELINE_EVIDENCE = "D:\\baseline\\run\\evidence"
$env:QR_AUDIT_REQUIRE_BASELINE = "1"
python scripts/run.py scan `
  --input-root "D:\\qr-data" `
  --report-root "D:\\qr-ai-reports" `
  --registry-path "D:\\original-scanner\\registry.json" `
  --adapter-module real_native_adapter `
  --decoder native `
  --boost-fallback `
  --ai-fallback `
  --ai-model-config "D:\\models\\qr-ai.json" `
  --baseline-evidence "$env:QR_AUDIT_BASELINE_EVIDENCE" `
  --require-upgrade-gate `
  --workers 1
```

`real_native_adapter`、`native` 和所有 `D:\\...` 路径都是示例占位符，请先查出原电脑实际值。与原版一致的成功集合由 `recognition-regression.json` 零回退门禁核验。

**如果只想独立检查 AI 算法**，可以不加 `--boost-fallback`，直接加 `--ai-fallback --ai-model-config`；不要用默认 V01-V03 参考扫描器的结果替代原版生产路径。

## 怎样查看能力是否真的提升

- `evidence/strategy-registry.effective.json`：原策略完整保留，末尾出现 `A01`；
- `evidence/attempts.jsonl`：`decoder_id=ai`、`strategy_id=A01` 是否真正执行，候选数、AI 解码调用次数和各解码引擎命中是否出现；
- `evidence/fallback-summary.json`：对比 `newly_rescued_images`、`newly_rescued_pairs`、`rescue_by_decoder.ai`；
- `evidence/recognition-regression.json`：是否 **431/409 无丢失、无历史载荷变化**；
- 独立人工或生成源真值校验：`DECODED` 不自动等于正确内容。

先跑 G5 裁剪、G2/G4 亮度，以及旧成功对照组，再扩大到2560张。按新增**正确**配对排序，单独统计 AI 模型漏检、多二维码、多候选、错码、恢复器耗时和资源峰值。

## 跨图片配对推断（只读，不能冒充扫码成功）

```powershell
python scripts/ai_pair_consensus.py `
  --inventory "D:\\qr-ai-reports\\run\\evidence\\inventory.json" `
  --attempts "D:\\qr-ai-reports\\run\\evidence\\attempts.jsonl" `
  --out "D:\\qr-ai-reports\\run\\pair-hypothesis.json"
```

它只输出载荷身份 Hash 一致、冲突、仅单侧解码的假设；**绝不把另一张图片推测出的内容写成当前图片 DECODED**。在确认两张图确实承载同一二维码之前，不能把猜测当成恢复结果。

## 不被当前栈锁死：后续备选引擎

- **检测**：QRDet/QReader 已训练模型、YOLO 实例分割、其他 MIT/Apache 许可检测器；以同图新检出候选数选择。
- **解码**：已有 OpenCV、ZXing-C++、本版可选 ZBar；另可通过现有 `external_cli_adapter.py` 对接本机 Java BoofCV 命令行或移动端 ML Kit 实验，但需要各自编写符合 JSON 协议的桥接程序并提供真实证据。当前分支尚未交付 BoofCV/ML Kit 执行器。
- **超分/恢复**：可插拔严格 ONNX RGB 超分 contract；尝试模块级软判定和纠错搜索前，应先研究已识别版本和模块格，避免指数级无约束暴力枚举。
- **真正的数据融合**：如果能确认左右确实为相同内容，可未来尝试逐模块配准融合并再解码；此版本先提供证据诊断，不生成伪成功。

所有替代路线必须与当前基线同图对照，优先保留具有独有新增正确解码的引擎，避免仅因模型更复杂就增加生产开销。
