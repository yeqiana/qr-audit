# v1.5.2 · 三类识别能力进入实际扫描失败兜底路径

> 本次是可选增强功能上线，不是历史 2560 张已提升的宣称。所有结果只在固定输入与人工真值校验后才允许称“正确识别”。

## 目标

此前 B01–B08 和 WeChatQRCode 只是彼此独立的实验。新版 `--boost-fallback` 将补白边/放大（B02）、亮度增强（B03–B08）**追加**在本次扫描中实际传入的原生/参考注册表末尾；已有策略一旦成功，新增路径自动跳过，不覆盖先前成功载荷。

`--wechat-fallback` 会在更末尾增加 W01 原图 WeChatQRCode，必须同时开启 `--boost-fallback` 并提前准备本地 OpenCV 4/5 对应模型。没有模型时扫描前拒绝启动；不会联网下载。W01 不等于手机微信 App 的解码器。

## 原电脑如何运行（务必带真实旧扫描器适配器）

```powershell
# 例：先由本地 Codex 确认真正旧版本扫描时采用的注册表、适配器和解码器
$env:QR_AUDIT_BASELINE_EVIDENCE = "D:\\historical\\evidence"
$env:QR_AUDIT_REQUIRE_BASELINE = "1"
python scripts/run.py scan `
  --input-root "D:\\images" `
  --report-root "D:\\reports" `
  --registry-path "D:\\qr-tools\\scan-registry.json" `
  --adapter-module offline_adapter `
  --decoder native `
  --boost-fallback `
  --baseline-evidence "$env:QR_AUDIT_BASELINE_EVIDENCE" `
  --require-upgrade-gate `
  --workers 1
```

**`offline_adapter`、`native` 和示例路径只是占位符**，必须用本机真实已有的名称。若需要微信模型，先依照 `docs/wechat-decoder-experiment.md` 设置 `QR_AUDIT_WECHAT_MODEL_CONFIG`，再添加 `--wechat-fallback`。

如没有真实旧版扫描适配器，不要尝试把默认 V01–V03 参考扫描当成历史原扫描器，更不要将 B/R/WeChat 等价替换旧V策略。

## 关键实现

- 原始注册表不修改；合成后的完整注册表在 `evidence/strategy-registry.effective.json` 冻结并被校验，原来的策略 ID 顺序不变。
- 为避免原生扫描器误收像素数组，原生自定义 decoder 仅执行原注册表部分；自动追加的 ZXing-C++ 和 OpenCV 只用于 B 预处理；微信仅对末尾 W01 原图执行。
- 提前停止只保留原策略成功的载荷，不会额外执行 B/W，因此原有成功结果不受新的处理算法覆盖；如已传入 `--baseline-evidence` 则由核心回归门禁再次检查。
- `evidence/fallback-summary.json` 是**本次扫描内部的观测增量**：新找回图片、配对以及每个策略的观测成功数。没有真值校验不能称正确率提升。
- `NOT_RUN`、`SKIPPED_INELIGIBLE` 与 `SKIPPED_EARLY_STOP` 分别记账，不得将声明策略数冒充实际执行数。

## 验收任务

第一轮先做 G5 裁剪、G2/G4 亮度各 30~80 张，保留未参与调参的真实测试集、微信放大原图人工扫码结果与载荷真值。结果分别报告 ZXing/OpenCV、B02–B08、W01 的**新增正确图片和配对**、错误载荷、耗时/P95。已有431张409对的完整原扫描能力必须零退化；门禁阻断即不得发布为成功升级。

性能上，因为需要在原路失败图片上尝试多种增强，扫描时间可能增加。先 `workers=1` 建立可比基线，再小规模测试 2/4 workers。

## v1.5.2 执行变化

原 `--boost-fallback` 会附加 B09 候选二维码透视矫正；大图增强自动降低放大倍率、必要时下采样，减少因 800 万像素输出上限产生的执行异常。勾选 `--wechat-fallback` 时，微信离线解码器还会在 B02/B04/B06/B08/B09 的增强像素上尝试识别（原生 source_file 解码器仍与这些像素分支隔离），最终 W01 原图解码仍保留。

更详细的能力和限制请阅读 `docs/recognition-recovery-v152.md`。
