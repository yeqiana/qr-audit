# qr-audit v1.1.0 交付说明

## 本轮修复范围

本版本落实 L2 证据契约、输入一致性、文件/配对统计、载荷身份比较和通用执行器接入。不新增图像增强算法，不修改或重排初始 28 条策略定义。

### P1 — 证据归属与字段一致性

- 新增共享 `evidence_contract.py`，统一 CLI、统计脚本和报告构建所使用的校验规则。
- attempt 必须匹配 manifest 的 run_id、image_id、group_id、side_id、relative_path 和 input_sha256。
- attempt_id 全局唯一；attempt_index 在逻辑组合内连续且唯一，允许明确的多次重试。
- 校验 payload 文本与 SHA-256、hash-only identity 的算法和数据范围、有限非负耗时、ERROR 与 skip 字段。
- 区分结构校验和来源核验；来源、注册表或输入指纹未核验时，不允许贡献度结论为有效。

### P1 — 输入一致性

- 扫描前后重新生成 inventory snapshot；验证器重新计算两份清单的差异，不信任 manifest 中未经复算的状态字段。
- 贡献度分析阶段再次哈希当前输入文件，检测扫描结束后的图片变更。
- 检测内容变化、新增和删除，保留证据并标记 INPUT_CHANGED。
- 输入变化时阻断有效贡献度结论，不把变更当作正常成功/失败结果。

### P1 — 文件级与配对级贡献度

- 递归发现混合目录结构，不因先发现配对组而漏掉独立图片组。
- pair_id 基于 group_id + normalized_pair_key，避免跨组同名混合。
- 文件级与配对级分别计算顺序新增、重复、独占贡献和整类策略移除损失。
- 缺失侧、单目录和歧义配对保留在报告，但不强行计入双侧配对分母。

### P1 — 载荷身份与报告

- 支持文本载荷、显式 scope 的 hash-only 载荷和多二维码载荷集合。
- 只有算法与数据范围一致时才比较哈希；比较信息不足时显示 NOT_COMPARABLE。
- 多码集合按无序身份集合比较；同一逻辑组合的矛盾重试会阻断贡献度。
- 左右配对结果统一使用 SAME / DIFFERENT / ONE_SIDE_ONLY / NOT_COMPARABLE / PAYLOAD_CONFLICT。
- MD 与 HTML 从同一 report model 生成，并共享同一人工复核判定。

### P2 — 通用执行器

- 新增策略执行器和解码器注册表。
- 外部适配模块通过 register_qr_audit(strategies, decoders, context) 注册已审计的策略和解码器。
- scan 模式允许提前停止；contribution 模式关闭提前停止。
- 未实现、依赖缺失和解码器不可用明确记录为 NOT_RUN，不伪装成不适用。

## 能力边界

- 28 条初始策略定义保持不变。
- 内置参考扫描仍只提供 V01–V03；V04–V28 必须接入真实执行器后才能运行。
- 通用适配接口不代表用户本地项目已经接线。
- 微信 App 实扫、业务有效性和真实图片集识别率仍需实际环境验证。

## 验证

- 新增合成测试覆盖混合目录发现、跨组 pair_id、run/hash/耗时矛盾、重复重试、输入新增/删除/修改、文件/配对损失差异、hash-only、多码集合、MD/HTML 状态一致、执行器提前停止/条件跳过/异常。
- GitHub Actions 结果以本次提交对应的实际 workflow run 为准；不以本地未执行测试宣称通过。
