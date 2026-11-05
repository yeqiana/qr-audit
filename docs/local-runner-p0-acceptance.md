# Local scanner P0 integration and acceptance (do not rewrite historical evidence)

This runbook is for the machine that **actually contains** the native/custom
scanner, its local strategy implementations, the input images, and its original
run evidence. The published `qr-audit` repository does not contain that custom
runner, and a public repository change cannot by itself certify local scans.

## Guardrails

1. Preserve all existing source files, images, manifests, attempts and reports.
   Work on a new branch/worktree and write only to a **new run_id** directory.
2. Keep the existing scan path as the historical baseline; do not modify it
   retroactively to obtain a `PASS`. A normalized legacy export is
   `HINT_ONLY` until its provenance can be independently verified.
3. No URL fetching from QR payloads, no installation, model download or network
   activity, no destructive cleanup. Default externalized reports to payload
   hashes and abstract file names/paths; internal original evidence may retain
   raw text under existing authorization.
4. Do not claim `V01–V28` have executed merely because they exist in a
   registry. Tie each V ID to an audited source function, parameters, actual
   decoder, and original implementation file hash. No no-op or fixed-resize
   substitutes for geometric module sampling.
5. A decoder feature not implemented by the adapter (such as an unsupported
   pure-mode option) is `NOT_RUN`, **not** `SKIPPED_INELIGIBLE`. A genuine
   image-size incompatibility is ineligible, with a reason recorded in **each**
   declared matrix cell.

## Recommended execution order

**P0-A — Evidence integration.** Identify the actual local scan entry point and
strategy generator. Refactor or wrap the run **at the point of execution** so
`scan_images.py` / `executor_registry.py` can produce the Schema 2.0
manifest and records. Declare run_id, strategy_order, image_id, group-scoped
pair_id, side_id, registered decoders, effective runtime parameters,
source_fingerprint.files and the before/after input inventory. Preserve real
LOCAL identifiers for legacy scans. An observed heuristic mapping is not a
proof of equivalence to a V strategy.

**P0-B — First narrow verified experiment.** Select a small, explicit real
image set covering each group, difficult cases and relevant dimensions.
If pure mode is not available in the OpenCV adapter, first run a
**ZXing-C++-only** contribution experiment with a frozen decoder scope.
Do not hide an unsupported decoder under an ineligibility status.
A single-decoder experiment verifies contributions **for that decoder only**
and does not establish the combined OpenCV+ZXing coverage.

**P0-C — Complete matrix.** For `N` images, `S` explicitly declared
strategies and `D` decoders the expected number of distinct logical cells
is `N × S × D`. Disable early stop in contribution mode. Every cell receives
an execution result, a genuine image-ineligible status, or an explicit
`NOT_RUN`; missing or failed cells block certification. Do not turn a
deterministic image-size skip into success or a genuine implementation gap
into a skip.

**P0-D — Validation, retries, and reports.** Independently run the
`validate_evidence.py` contract on the new evidence; require
`structural_status=PASS`, `provenance_status=VERIFIED`,
`contribution_metrics_valid=true`, no unresolved errors, no unexpected
missing cells and stable inputs. Only then generate exclusive contribution
and removal-loss metrics for **both files and eligible pairs**. Verify
all report denominators and sampling on the same frozen dataset.

**P0-E — Real quality gate.** Provide an independently labelled, privacy-safe
ground-truth set, including no-QR, multi-QR, one-side-only, wrong-payload,
non-UTF8/ECI, blur, brightness and cropped cases. Report recall and wrong
payloads separately. A decoder-returned text is **not** proof that it is
correct. WeChat/business tests are another authorized, distinct gate.

## Performance and safe optimization

- Compare the existing production scan and the proposed scheduler on the
  **same input SHA-256 set** under comparable environment and timing bounds.
- Preserve both decoders for coverage analysis: removing an expensive decoder
  based only on early-stopped observations can lose unique successes.
- Use complete contribution results to rank high-cost families. Only mark
  a family removable after a same-input holdout A/B test demonstrates
  no unacceptable loss of file or pair coverage, and P95, resource use and
  wrong-payload metrics meet acceptance thresholds.
- Distinguish *coverage-only review* (neither side decoded) from *side
  consistency review* (one side decoded, other side missing). Do not
  automatically waive review without independently validating payloads
  and the user's business acceptance rule.

## Minimum P0 acceptance tests

| Test | Expected |
| --- | --- |
| No decoder support for a requested option | NOT_RUN; contribution invalid |
| Real size-inapplicable image | SKIPPED_INELIGIBLE with recorded condition |
| Early stop in contribution | contribution invalid |
| Missing image×strategy×decoder | contribution invalid |
| Run/image/hash/pair mismatch | structural FAIL |
| Input modified during scan | provenance/contribution blocked |
| Source/config fingerprint modified | provenance/contribution blocked |
| Unknown V strategy mapping | no claim of real V implementation |
| One-side decode; other-side failure | OR coverage succeeds; consistency review separate |
| Changed payload vs independent truth | flagged incorrect, never counted as validated accuracy |
| Full valid matrix and source/input checks | metrics valid; file/pair removal-loss separate |

## Required handoff

Provide only a **sanitized Markdown** summary, with the actual run_id and
manifest schema, source-attested V↔native mapping, status counts by decoder,
full matrix coverage, validator JSON status, file/pair results, comparisons
with a frozen historical baseline, P95 timings, risk list and acceptance
evidence. Never paste raw QR payloads or user-specific source paths into
public repositories.
