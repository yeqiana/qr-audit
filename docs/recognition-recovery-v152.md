# qr-audit v1.5.2 识别修复：图像算法、执行顺序与本机验收

## 本轮范围与确定的改动

本轮直接修复 v1.5.1 真实代码中的三个缺口：大图 B02–B08 固定4倍触发输出上限、OpenCV已检测到候选但缺少透视恢复、WeChatQRCode仅尝试原图。**不替换任何历史原生V策略**，默认不添加新的扫描步骤；仅在开启 `--boost-fallback` 后使用。

| 模块 | 新行为 | 不能声称的内容 |
|---|---|---|
| B02–B08 | 4/3/2/1 倍中选择安全最大值；1倍仍超8M则等比 INTER_AREA 下采样 | 与旧固定4倍完全一致，或能恢复已丢失的信息 |
| B09 | 用 QRCodeDetector.detectMulti/detect 找角点，对最大候选做透视矫正、补足静区；没有角点则走受限全图 | 能恢复所有裁剪、所有二维码候选 |
| WeChatQRCode | 仅在 B02/B04/B06/B08/B09 加独立模型解码，再以 W01 做原图兜底 | 与手机微信App采用完全相同引擎 |
| 审计 | fallback-summary 追加按解码器、策略+解码器拆解的额外成功统计 | 观测到 DECODED 就能证明载荷正确 |

**算法细节：** B09 不对透视矫正图再盲目放大4倍，因为线性插值后的模块边界放大可能导致二维码无法解码；它直接给恢复后的码加约 1/6 码宽的白边，限制最大提取边长为2048。多码情况下暂只取最大的合法候选，后续可单独评测多码分支。

## 需要真实旧版接线的操作

在原始扫描器所在电脑上，使用原版注册表、adapter 和 decoder 参数；文档中名称必须用实际工作区查到的值替换。**禁止用此仓库默认 V01–V03、B/R 参考策略冒充原生 V04/V10。**

```powershell
$env:QR_AUDIT_BASELINE_EVIDENCE = "D:\\history\\run-id\\evidence"
$env:QR_AUDIT_REQUIRE_BASELINE = "1"
python scripts/run.py scan `
  --input-root "D:\\images" `
  --report-root "D:\\qr-reports" `
  --registry-path "D:\\real-scanner\\registry.json" `
  --adapter-module actual_native_adapter `
  --decoder native `
  --boost-fallback `
  --baseline-evidence "$env:QR_AUDIT_BASELINE_EVIDENCE" `
  --require-upgrade-gate `
  --workers 1
```

若本机安装对应 OpenCV4/5 + 合法本地 WeChatQRCode 模型文件（配置流程见 `docs/wechat-decoder-experiment.md`），追加 `--wechat-fallback`。缺模型时应在输出目录创建前阻断，不能把 Not Run 当作实际验证通过。

## 第一轮真实数据验收

1. 冻结 G5 裁剪80张、G2/G4亮度各40–80张，以及已成功样本30张；记录输入哈希、目录侧、正确载荷真值。
2. 确认 B02–B08 对700×700及以上图片不再出现 `BOOST_OUTPUT_EXCEEDS_PIXEL_LIMIT`。如被下采样，标注其可能导致识别损失；保留原样基线先行。
3. 确认 B09 真正检测/执行过且图像输出不超8M。对候选检测失败和多码图片只给 `NOT_VERIFIED`，不能虚构完整恢复。
4. 同样输入对照 `--boost-fallback` 与 `--boost-fallback --wechat-fallback`：比较 `fallback-summary.json` 的 `rescue_by_decoder`、`rescue_by_strategy_decoder`，并人工核验 payload 身份；本机模型必须是真的，合成单测仅为执行链路模拟。
5. 比较 2,560张 / 1,280对历史基线的同相对路径和 SHA-256，通过 `recognition-regression.json` 确认旧431张和409对**没有任何丢失、载荷未变化**。任何一项不可证实则不能认定正式升级。
6. 记录耗时、P95与 ERROR、SKIPPED_INELIGIBLE 分布。若本轮耗时不合理，优先减少不产生独有收益的组合，不应盲目增加更多滤镜。

## 尚未解决的限制

- 旧 V04/V10/V11/V12 等仍须在原电脑真正接入并提供来源证据。
- B09 取最大的有效检测框，没有对多个二维码候选逐个验证；特殊模糊、模块丢失和裁切严重的图无法保证解码。
- 当前自动停止策略只在首个解码载荷之后停止。错误载荷需要有独立人工真值才能识别，零回退证据不会自动认证解码内容正确。
- 本次 GitHub CI 只验证合成图片、模拟微信模型与执行合同；**真实识别率仍以你的电脑上完整样本实测为准**。
