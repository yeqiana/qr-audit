# qr-audit v2.0.0-ai.2：二维码模块级恢复实验

> **独立实验分支**：`experiment/qr-module-recovery-v1`，基线 `563d842`（v2.0.0-ai.1）。当前不可直接合并至 `main`，也不能用合成图推断用户真实图片识别率。

## 为什么引入模块恢复

v2.0.0-ai.1 在 176 张合成测试图中，传统 OpenCV + ZXing-C++ + B01–B09 已正确解码 155/160 张、79/80 对；追加 QRDet Nano 没有独有增益。剩余 5 张均属于静区/模块裁剪或严重低分辨率损伤。

本版仅在 A01 兜底已经尝试且**没有得到载荷**之后，可选继续执行：

1. 使用原始图像（不是 AI 补画的图片），按 v1–v10 搜索 QR 网格尺寸、模块间距、偏移、四向旋转。
2. 对 QR 固定功能模块（定位、分隔、时序、对齐和固定暗模块）打分，淘汰弱匹配。
3. 逐模块采样灰度，将不可见区域保留为缺失标记；在渲染时做有限的白/黑填充假设。
4. 对候选矩阵补标准白静区并交给 ZXing-C++ / OpenCV。二维码文字**只能来自独立解码器成功输出**，不能从另一个二维码、模型文字生成或图片文件名猜测。
5. 利用现有解码器的二维码格式与 Reed–Solomon 解码校验成功候选。**尚未实现自定义 RS 软判决/擦除纠错**，不宣称缺失数据均可恢复。

配对像素融合 `recover_pair` 是独立可调用的研究接口，不在正式 A01 单图解码中使用；必须先确认两图承载同一二维码，不能将配对推断计入某张图片的独立解码成功。

## 离线配置

保持旧配置与旧行为不变；只有显式 `module_recovery.enabled=true` 才触发额外网格恢复。

```json
{
  "schema_version": "1.0",
  "detector": {
    "provider": "ultralytics",
    "weights": "models/qrdet-n.pt",
    "confidence": 0.2,
    "max_candidates": 8,
    "device": "cuda:0",
    "imgsz": 640,
    "batch": 1
  },
  "max_attempts": 120,
  "budget_seconds": 15,
  "grid_versions": 7,
  "zxing": true,
  "zbar": false,
  "module_recovery": {
    "enabled": true,
    "max_version": 10,
    "top_k": 24,
    "max_decode": 48
  }
}
```

权重是**操作者本地准备的合法二维码专用模型**，不会由 Skill 自动下载。当前用 QRDet Nano / RTX3060 实测。模型文件不纳入仓库。上限：单图 800 万像素；较大图片跳过模块分支但保留原 A01 解码结果；所有新参数都强制校验。单图的 `budget_seconds` 对原本 A01 变体是软预算，模块候选扫描有自己的固定版本/候选/解码次数限制，**不是严格的总墙钟超时**。

## 本地合成实验（2026-11-06）

同一冻结真值数据集：176 PNG（160 有二维码、16 无码），80 对。冻结每张输入 SHA-256；对照使用原来的完整基线证据。所有图片均在 Windows 本地 Runner 进行实际扫码。

| 指标 | 完整传统多引擎 | 增加 AI 检测 | 再增加模块恢复 |
|---|---:|---:|---:|
| 正确解码图片 | 155/160 | 155/160 | **158/160** |
| 正确解码配对 | 79/80 | 79/80 | **80/80** |
| 错误载荷图片 | 0 | 0 | **0** |
| 无码负样本误解码 | 0/16 | 0/16 | **0/16** |
| 执行错误 | 0 | 0 | **0** |

新增正确图片来自：`G5_crop/WAVES_QR/05-005.png`、`G5_crop/WAVES_QR_RAW/05-005.png`、`G5_crop/WAVES_QR_RAW/05-010.png`。原来双侧失败的 `05-005` 配对因此首次成功。正式扫描中 A01 执行 21 次，3 次产生新正确载荷；零回退门禁为 `PASS_NON_REGRESSION`。

仍未独立恢复两张图片：`G5_crop/WAVES_QR/05-006.png` 和 `G7_low_resolution/WAVES_QR_RAW/07-004.png`。尝试提高候选数量、调整二值化阈值、使用 ZXing 纯码模式均未新增成功；不允许凭已解码配对成员的文字伪造另一侧的扫描成功。

> **验证范围**：这是合成图真值，不代表微信扫码体验或原始 2560 张真实图片成功率。原来 431 张 / 409 对历史成功集合仍需要用户本机真实原图与原生 V/R 执行器回归，不能把此处的“零回退”外推。

## 执行与证据

使用项目现有 `scripts/run.py scan` CLI，指定 `--boost-fallback --ai-fallback --ai-model-config <配置文件> --baseline-evidence <基线evidence> --require-upgrade-gate --workers 1`。输入只读，扫描报告使用每次独立输出目录。重点核验：

- `evidence/strategy-registry.effective.json`、`evidence/run-manifest.json`、`evidence/attempts.jsonl`；
- `evidence/fallback-summary.json`，以及 `evidence/recognition-regression.json` 必须为 `PASS_NON_REGRESSION`；
- 使用合成真值文件按路径和每张图的 SHA-256 独立计算正确图片/配对、错误载荷和无码误报；
- `build_report_models.py` 应使用本次有效策略注册表重新校验总览，而不是误用初始注册表。

新单测覆盖 QR 标准功能图案、裁剪真实解码、无码无假载荷、配对融合与独立正确解码区分、最大像素预算、配置开关、640px/batch1 参数。Windows TEMP 路径比对统一大小写规范化，JSON 使用显式 UTF-8。

## 当前限制与下一阶段

- 当前网格搜索假设候选二维码大致居中且近似正视；极端透视需结合检测器多边形单独矫正。
- 只支持 v1–v10 的固定功能图案搜索；大版本不被错误宣称为已覆盖。
- QRDet 检测无载荷时无法自动把同一配对的像素融合写入单图成功数。
- 明显缺失的数据模块无法靠视觉模型“猜对”，下一轮可研究**解码器提供的擦除位置和置信度**并做有界 RS 反馈；新成功仍必须由二维码校验和真值证明。
- 在真实 2560 张图的分类诊断与零回退验证之前，保持独立实验分支，不合并主线。
