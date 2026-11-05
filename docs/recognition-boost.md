# 二维码识别增强实验：B01–B05（v1.4）

## 目标与可信边界

本轮不宣称历史 2,560 张 / 1,280 对真实图集已经提升成功率：这些输入及原始扫描器位于另一台电脑。本仓库新增的是**可以真实执行且可评估的候选增强**，优先针对缺少静区、较暗/不均匀光照的小尺寸二维码。原 V01–V28 初始注册表保持不变，B01–B05 属于独立实验参考实现，不是本地原扫描器的 28 条策略接线。

| 策略 | 处理 | 适用假设 |
| --- | --- | --- |
| B01 | 原图，不预处理 | 保留基线，不丢现有可识别结果 |
| B02 | 最近邻 4× + 16 像素白边 | 静区被裁切，但定位点与数据模块仍完整 |
| B03 | Otsu + 最近邻 4× + 白边 | 全局低对比度、可用阈值分离 |
| B04 | CLAHE + Otsu + 最近邻 4× + 白边 | 局部对比度较差 |
| B05 | 高斯自适应阈值 + 最近邻 4× + 白边 | 局部照明变化、渐变亮度 |

这些算法不能恢复已经丢失的二维码模块。标准二维码对静区有要求；白边是待验证的启发式补救，不是完整几何重建。输出限制 8,000,000 像素，超过预算会记录 ERROR、阻断相应贡献度验证，不能伪装为已完成。

## 开启独立实验

在明确选定的 **qr-audit v1.4 源码**中，使用已经安装的本地 Python、OpenCV、NumPy：

```powershell
# 小样本基线：原初始28条定义不变，只能确定它们本次实际是否执行
python scripts/run.py scan --input-root "D:\\samples" --report-root "D:\\reports" --decoder opencv --workers 1

# 新的隔离 B01–B05 识别实验，必须明确指定新的registry和adapter
python scripts/run.py scan --input-root "D:\\samples" --report-root "D:\\reports" --decoder opencv --workers 1 --registry-path assets/strategy-registry.boost.json --adapter-module recognition_boost_adapter

# 完整实验：不允许提前停止，计算合法的B策略贡献（不是V策略贡献）
python scripts/run.py scan --experiment-mode contribution --input-root "D:\\samples" --report-root "D:\\reports" --decoder opencv --workers 1 --registry-path assets/strategy-registry.boost.json --adapter-module recognition_boost_adapter
```

若已经安装 ZXing-C++，可另行指定 `--decoder zxingcpp` 验证候选在该解码器上的效果；没有安装不得声称执行成功，也不得联网静默安装。日常扫描的默认注册表和模式均未更改。

## 同数据评估方法

1. 按原输入 SHA-256 固定试验集，并留出未参与调参的真实测试集。优先 G5 裁剪组左侧（历史 0/391 成功）和 G2 亮度攻击组，人工确认有码/无码、是否完整保留模块。
2. 两个 run 使用相同图片、同一个解码器/版本和尽可能相同的计时环境；B01 是原图基线。比较同 run 中 B01 与 B01–B05 的可解码并集，既有原扫描器与 B实验的数据源/算法不同，不可直接称 V01–V28 + B 联合提升。
3. 输出新增解码文件数、**有效配对数**、丢失数量、解码文本/正确答案是否一致、错误载荷数量、异常、平均/P95与完整来源校验。无独立真值仅写“离线解码覆盖”，不可写“识别正确率”。
4. 对大图、缺失定位模块、模糊、色偏、真实多码及无二维码样本做边界和反例测试；仅在保覆盖且有新增正确结果时才推荐把候选算法并入实际扫描器。
5. B 的执行即使通过完整贡献矩阵认证，也**不能**证明用户原生 V01–V28 的实现已接入。真实接线仍按 `docs/local-runner-p0-acceptance.md` 验收。

## 防过度设计

不增加数据库、任务队列、模型、外部下载或复杂 Agent 调度。本轮只增加一个参考算法适配器、一份独立注册表、极简 CLI 配置及合成真值回归。默认不增成本：新模式须用户显式 opt-in，默认扫描路径与原来的 V01–V28 完全一致。
