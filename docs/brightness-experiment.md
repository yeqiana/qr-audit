# 亮度专项识别增强：B06–B08（仅实验，不替换原生路径）

本次新增的亮度分支为 opt-in，**仅针对保留二维码数据模块但亮度/局部对比度不利于解码的图片**。与 B01–B05 同一实验注册表，未修改原 V01–V28、旧原生 scanner、默认 decoder 或早停行为。

| ID | 方案 | 条件/局限 |
|---|---|---|
| B06 | 基于灰度中位数动态 Gamma | 暗、亮图不同曲线；不能恢复饱和丢失的信息 |
| B07 | 15×15 局部 Sauvola，k=0.34，R=128 | 自实现局部均值和方差，不依赖外部模型；可能增强噪点 |
| B08 | 31×31 低频背景校正 + Otsu | 适合平滑亮度渐变；近零背景或复杂纹理需防误读 |

所有变体最终最近邻放大4倍、补16像素白色静区，输出不超过800万像素。真实效果必须同独立已知答案比较；不允许把单纯 DECODED 当正确。

## 在原电脑独立实验

先冻结 100–230 张困难样本的 SHA-256 和微信测试分类，**先运行原旧版 scanner 基线**，再独立启用 boost：

```powershell
python scripts/run.py scan `
  --input-root "D:\\qr-samples" `
  --report-root "D:\\qr-experiments" `
  --decoder opencv `
  --registry-path assets/strategy-registry.boost.json `
  --adapter-module recognition_boost_adapter `
  --workers 1
```

当前这条命令只执行 B 系列，不包含 V/R 原生分支，不可以用它单独替代既有 scanner。对照报告必须分别给出：原始图片 SHA-256、已知载荷真值、微信是否成功/何种放大方式、B01–B08 新增正确文件与配对、错误载荷、墙钟时间和 P95。注意原电脑的微信实测与电脑离线解码是两个不同能力。
