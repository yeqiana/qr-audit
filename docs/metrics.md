# Measuring QR preprocessing strategy contributions

A strategy's raw success count is **not** its marginal value, and an individual strategy's unique count is **not** the same as the loss caused by removing a whole family.

Assume a complete experiment on the same two images with three strategies:

| Image | `pure_a` | `pure_b` | `normal` |
| --- | --- | --- | --- |
| `hard.png` | DECODED | DECODED | NO_DECODE |
| `easy.png` | NO_DECODE | NO_DECODE | DECODED |

With order `pure_a → pure_b → normal`, the ordered-new counts are **1, 0, 1**. Each `pure` strategy's **exclusive** count is **0** (because the other pure strategy also succeeds on `hard.png`). Yet removing the entire `pure_mode` family loses **1 successful image**. Do not remove a whole family just because every member's exclusive contribution is zero.

Define `Sᵢ` as image IDs decoded successfully by strategy i:

- Ordered new success: `|Sᵢ − union(S₁..Sᵢ₋₁)|`.
- Repeated success: `|Sᵢ ∩ union(S₁..Sᵢ₋₁)|`.
- Individual exclusive success: `|Sᵢ − union(Sⱼ, j ≠ i)|`.
- Whole-family removal loss: `|union(all Sᵢ) − union(Sᵢ outside family)|`.

Use wall-clock duration for **executed** attempts, report arithmetic mean and nearest-rank P95, and keep skipped/error states visible. Group results by input group and side. For pairing, count physical files separately from pair IDs.

### Completeness gate

`scan` mode can stop early for cost control but is **not a valid source for a full contribution analysis**. `contribution` mode needs a complete expected `image × strategy × decoder` matrix. An ineligible strategy must still have an explicit skipped record and reason. Absent combinations, unexpected early stops, or missing implementations make removal-loss/exclusive estimates `INCOMPLETE` rather than zero.

### What is a valid optimization claim?

A candidate optimization must preserve the baseline's decoded-image set on a representative holdout dataset, compare conflicts and errors, and measure latency including expensive variants. Only then should an implementation PR be considered; QR Audit itself remains read-only on the original scanner.