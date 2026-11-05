# 原生旧策略恢复：V04/V10/V11/V12 真实接线验收

**本仓库不能访问用户电脑 `backup` 中的原始扫描器。**
本轮不会用参考 R/B 策略冒充旧版 V04–V28，也不会把“成功总数回到431张”当作原生实现等价。

## 在有原始 scanner 源码的本机完成

1. 只读盘点 `backup/.../baseline_scanner.py` 的 `variants`、`scan_run.py`，给出 V04、V10、V11、V12 与真实原生函数的逐项映射。旧版 V04 的 PIL 白底合成→灰度→ImageOps.autocontrast→Otsu→NEAREST4x→白边32；旧 V10 的灰度→NEAREST4x→白边32→ZXing is_pure=True 且 TextMode.Plain；V11 最近邻 8×无边框、V12 8×加白边64。**这些步骤仅来自历史审计描述，不代表已取得或审核真实源码。**
2. 复用已提供的 `external_cli_adapter.py` 接口，显式设置 `QR_AUDIT_BRIDGE_CONFIG`，将 native_strategy 映射到用户本机实际方法，绑定原生二进制与源码 SHA-256。若没有适配器，不要通过注册假空函数制造“已接入”。
3. 在真实小样本中，验证纯码选项确实被原生 ZXing 调用，比较旧版成功载荷无序集合；逐次记录原生策略与解码器身份和选项，包括 `is_pure`、`text_mode`。不得以 R02 代替 V10 的接线证明。
4. 新 run 不覆盖历史证据。验收必须经过 `regression_gate.py` 全量零回退检查，且还需要独立的人为标注确认真实正确载荷。

## 只读接线检测

```powershell
python scripts/native_coverage_audit.py `
  --manifest "D:\\reports\\run-id\\evidence\\run-manifest.json" `
  --attempts "D:\\reports\\run-id\\evidence\\attempts.jsonl"
```

默认要求 V04/V10/V11/V12 被标为 REGISTERED，并存在真实运行 attempt 的 native_strategy_id、native_decoder_id 与 bridge_config_sha256。一项不满足则返回非零。即使通过，也仅是原生执行与来源标记的**初步证据**；不能证明变换顺序/纯码参数等价。对仅普通扫描提前停止而没有执行到的 V，输出 NOT_OBSERVED 而非错误地当作贡献为零。

此工具是只读审计，不引入新的调度器、数据库或扫描算法。
