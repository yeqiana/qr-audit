# qr-audit v1.4.1：历史成功样本零回退门禁

**缘由：** 同 SHA-256 的 2,560 张、1,280 对输入，历史扫描实际成功 431 张/409 对；部分适配器变成 400/383，最终仅 V01–V03 执行时降至 211/208。结构校验 PASS、来源 VERIFIED、28 条策略定义和 143,360 条总记录均不能证明识别能力未退化。

## 必须改变的验收口径

扫描器升级版的最低门槛不是新算法的单次 PASS，而是以下项目**全部满足**：

1. 同组相对路径、左右侧、相对图片路径和原图 SHA-256 一一对应，差异则 `BLOCKED_INPUT_CHANGED`。
2. 历史成功文件集合必须完全保留；配对任一侧成功的历史覆盖也必须保留。**新增加 10 张不能抵消旧版丢失 1 张**。
3. 对历史成功图片，候选结果仍须保留全部可比较的历史载荷身份；载荷变更应阻断升级，不能仅凭状态 DECODED 就放行。独立真值检验是另外一道门槛。
4. 比对每次真正执行的 decoder 尝试和 `NOT_RUN` 数量、`connected_strategies`，若旧 V04/V10 等源码适配器未接入，在扫描**之前**明确拒绝启动；不过“已注册”仍不能取代历史样本回归。
5. 仅允许在新 run_id 输出，旧历史证据保持只读、原样；遇到失败返回非零退出码，不在 CI 或发布说明中声称性能升级通过。

## 使用方式：现有两次运行的结果

```powershell
python scripts/regression_gate.py `
  --baseline-evidence "D:\\historical\\evidence" `
  --candidate-evidence "D:\\latest\\evidence" `
  --out "D:\\analysis\\recognition-regression.json"
```

上述两个 evidence 目录均应具有 `run-manifest.json`、`inventory.json`、`attempts.jsonl`；校验器会基于**实际 DECODED、输入哈希及载荷身份**重新计算，而不信任报告上的成功总数。旧扫描器若没有这些原始记录，不允许从一张 MD 总览“补造”证据后自称严格 PASS；应先只读验证或由当地 Codex 输出有明确来源的快照后再比较。

## 使用方式：先检查接线，再运行回归门禁

```powershell
python scripts/run.py scan `
  --input-root "D:\\images" `
  --report-root "D:\\reports" `
  --adapter-module actual_native_adapter `
  --decoder native `
  --require-strategy V04 `
  --require-strategy V10 `
  --require-strategy V11 `
  --require-strategy V12 `
  --baseline-evidence "D:\\historical\\evidence"
```

请把 `actual_native_adapter`、`native` 换成实际已有的本地原生桥接模块与 decoder ID。上述示例**不意味着这些模块在发布包中存在**；没有接线就应明确失败而非偷偷回退到 3 个参考策略。还应核查 V10 纯码是否真实用旧版引擎选项执行，不能仅靠同名策略注册。

只传入 `--baseline-evidence` 就是升版回归校验；若没有这一参数，`PASS_BASELINE_ONLY` 仍只是离线扫描完成，不代表任何能力升级已验收。严格发布应在对应真实机器上带完整基线进行测试。

## 回归状态说明

| 状态 | 含义 |
| --- | --- |
| `PASS_NON_REGRESSION` | 已有成功文件/配对及其已观测载荷均未丢失；不是正确率真值认证 |
| `BLOCKED_RECOGNITION_REGRESSION` | 任一历史成功文件/配对/历史载荷被丢失 |
| `BLOCKED_INPUT_CHANGED` | 两轮文件集合或 SHA-256 不同，不能直接比较 |
| `BLOCKED_PAIR_STRUCTURE_CHANGED` | 有效配对归属发生变化，不能比较 |
| `BLOCKED_UNVERIFIABLE` | 基线数据不完整、身份无法验证或格式不支持 |
| `REQUIRED_STRATEGY_NOT_CONNECTED` | 必须的旧策略没有实际执行器接线，扫描前阻断 |

门禁的成功并不等于微信实扫结果正确。人工真值集、异常样本、实际原生功能语义、性能和跨机器稳定性还需要独立验收。

## 防止再次发生的改造顺序

- **先恢复旧版执行能力**，不可用 V01–V03 参考扫描器或仅 B01–B05 实验策略替代旧版。V10 等 pure_mode、V04 等 Otsu+白边必须使用**可核对的旧源码与选项**。
- **运行前检查**关键策略是否真的接线、加载文件 SHA-256、解码器版本和本地 native 特性。
- **运行后做零回退比较**：431/409 的总数只是最小观察基线，仍要求逐文件、逐配对和载荷不丢。即使总计 432/410，只要丢 1 张历史成功也应失败。
- **最后才添加新识别算法**：对已失败样本做独立增量实验，必须保留旧成功集合。Worktree 隔离开发、worker 并发扫描都不能替代这条验收线。

CI 内通过的合成回归仅能证明门禁算法和接线检查能拒绝错误输入；真正的 2,560 张实际数据不会被上传到 CI，因此历史能力保护必须在原本存有图片/证据的电脑上执行。
