# WeChatQRCode：仅离线、可选的第三解码器实验

本适配器**不等于手机微信App实际扫描器**。优先解决 G5 裁剪组“微信放大图常能扫而电脑未解码”的差距，但是否带来新增正确覆盖需要实际逐图比对，不能仅依赖模拟模型测试。

## 版本兼容

- OpenCV 4.x 的 WeChatQRCode 通常要求四个本地 Caffe 文件（检测/超分超参数及权重）。
- OpenCV 5.x 的接口已经改为两个 ONNX 模型文件。切勿混用旧接口（官方 5.x 文档在版本迁移时存在不一致）。
- 本机安装的 OpenCV 必须带 `wechat_qrcode` 模块，模型文件要由操作者事先合法获取并存放本地。运行过程**不会联网下载、安装、自动发现旧模型**。
- 缺少模型配置或 OpenCV 模块时注册 `wechat` 为不可用，尝试结果必须是 NOT_RUN；配置错误则在扫描前失败，而不能冒充真正执行。
- 模型文件本身加入源指纹（SHA-256），每个 worker 独立创建模型对象，避免本地 native 对象共享；模型可能较大，先仅以 `--workers 1` 验收资源。

## 启用

例如 OpenCV 5.x：

```json
{"models":["detector.onnx","super_resolution.onnx"]}
```

OpenCV 4.x 则是四个 Caffe 文件路径，配置中采用 `models` 顺序：detector prototxt、detector caffemodel、super resolution prototxt、super resolution caffemodel。

```powershell
$env:QR_AUDIT_WECHAT_MODEL_CONFIG = "D:\\models\\wechat\\models.json"
python scripts/run.py scan `
  --input-root "D:\\qr-samples" `
  --report-root "D:\\qr-experiments" `
  --registry-path assets/strategy-registry.boost.json `
  --adapter-module recognition_boost_adapter `
  --adapter-module wechat_decoder_adapter `
  --decoder wechat `
  --workers 1
```

这是**仅B参考策略+可选解码器**的独立试验，不能与旧原生V扫描混为一次完成的升级。对100张有真实正确答案的小样本，区分微信App手动扫描、WeChatQRCode离线解码、ZXing与OpenCV结果，并比较新增正确文件与配对、错误载荷和开销。旧成功必须在正式合入时零丢失。
