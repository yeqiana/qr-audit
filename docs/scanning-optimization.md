# QR Audit：新鲜源码、受控并发和识别收益验收

## 目标和边界

本 Skill 的产品目标是尽可能**正确**地解码更多二维码，并能稳定复跑、追踪失败。不能为了测试“最新代码”而在每次运行时重新生成全部算法，也不复用旧临时脚本、旧运行产物或未知来源的执行器。一次扫描从指定的当前源码启动**新的 Python 进程**，每次创建新的 run_id，记录实际加载模块、策略、配置、依赖及输入指纹。离线时并不能自动知道远端分支是否更新，因而“最新”是操作者明确选择的本次源码版本，而非无法验证的 GitHub 最新状态。

### 仅三层

- **Scanner**：图像发现、真实算法/解码器、按图并行、可选早停；
- **Evidence**：run_id、源码/配置与图片指纹、逐次尝试、输入前后变化、异常；
- **Report**：文件/配对覆盖、准确性或真值缺失、性能、完整贡献度（仅合法矩阵）。

不要引入数据库、Redis、MQ、分布式锁、复杂调度器。Worktree 是开发实验隔离，不是扫描任务的必需依赖。

## 实际运行方式

```powershell
# 单独新 Python 进程运行；从你确认的 qr-audit 源码根目录启动
python scripts/run.py scan --input-root "D:\\images" --report-root "D:\\reports" --workers 1

# 相同输入及源码版本，在新的 run_id 下跑对照
python scripts/run.py scan --input-root "D:\\images" --report-root "D:\\reports" --workers 4

# 注意：这是完整无早停贡献矩阵，耗时会显著增加
python scripts/run.py scan --experiment-mode contribution --input-root "D:\\images" --report-root "D:\\reports" --workers 1
```

默认 1 worker；只有确认本机 OpenCV、ZXing-C++、本地 CLI 适配器支持线程并行而不污染状态，才探索 2/4/8。实现为**有界线程池**：最多 `workers*2` 张输入在途，主线程按照冻结图片清单顺序唯一写入 attempts.jsonl。线程并发能否加速取决于本地原生库是否释放 GIL、内部线程和系统资源，不做无依据加速承诺。原生扫描器有全局状态、非并发安全时应固定 workers=1，未来确认必要时再引入进程级并行。

## 证据与失败门槛

- 每次扫描先写 `run-manifest.json`，`run_status=RUNNING`，以便异常中断后保留来源。成功结束才改为 `COMPLETE`；
- `source_consistency` 对运行开始时冻结的本次源码/配置文件再次 SHA-256 校验；变动时状态为 `BLOCKED_SOURCE_CHANGED`；
- 输入前后清单变化则 `BLOCKED_INPUT_CHANGED`；
- 不擅自复制更换旧证据，不从旧 run 补造新 run；扫码结果不保证正确载荷，仍须真值集核验；
- `scan` 允许成功后早停，适合实际使用；`contribution` 关闭早停，并且只有 `structural_status=PASS`、`provenance_status=VERIFIED`、`contribution_metrics_valid=true` 才能写独占与移除损失。

## 受控性能基准

将 1/2/4/8 个 worker 在**同一 SHA-256 输入清单、同一代码快照、同一依赖与同一策略/解码器配置**下做独立 run，每档至少多次运行，记录图片级 P95、总墙钟、成功文件/配对、异常数、峰值内存/CPU。只有在成功覆盖与正确载荷均不退化时，才按真实测试结果提高默认 worker。不能将不同批次、不同机器的原始耗时直接相减。

算法优化先做困难图片的人工分类：图像是否完整保留二维码、静区是否被裁、定位角是否缺失、真实尺寸/对比度与预期载荷。对受控真值集比较文件及配对的新增正确解码、错误载荷、冲突、异常、P95。观察不到新增不代表该策略理论无价值，更不能用早停扫描的顺序新增统计直接删掉策略。

## 最小验收清单

| 检查 | 门槛 |
| --- | --- |
| 1 worker 与 4 worker 同一图集 | image×strategy×decoder 状态与载荷身份一致，允许不同运行 ID 与耗时 |
| 原始文件/源码扫描中变化 | 不允许继续报告可信有效结果 |
| worker 在执行中抛异常 | 保留唯一新 run 的未完成证据，不伪造 COMPLETE |
| 旧报告/历史数据 | 不得覆盖或删除 |
| 无 OpenCV 或不支持纯码 | NOT_RUN，不得伪装为图像不适用 |
| 贡献度输入、源码、矩阵不完整 | N/A/INCOMPLETE，不输出可用于删除策略的损失 |
| 新策略的收益 | 必须在独立真值集给出新增正确解码和可能的退化 |
