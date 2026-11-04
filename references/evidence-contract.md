# QR Audit Evidence Contract — Schema 2.0

This contract binds every attempt to one run, one frozen input inventory, one strategy registry, and one source fingerprint. Structural validation and provenance verification are separate results.

## Evidence layout

```text
<report_root>/<run_id>/evidence/
  inventory.json
  inventory-after.json
  run-manifest.json
  attempts.jsonl
```

## run-manifest.json

Required fields:

- `schema_version: "2.0"`, `run_id`, `mode` (`scan` or `contribution`).
- `inventory_sha256`: SHA-256 of canonical JSON for the complete `inventory.json` object, including its generated timestamp.
- `strategy_registry_sha256`: SHA-256 of canonical JSON for the frozen strategy registry.
- `strategy_order`, `strategies`, `decoders`, and the complete `images` list.
- `source_fingerprint.files[]`: absolute local source path and SHA-256 for the scanner, registry and loaded adapter modules.
- `input_consistency`: before/after inventory comparison with `STABLE` or `CHANGED`, plus changed, added and deleted identities.

Each image entry includes `image_id`, `group_id`, `side_id`, `relative_path`, `sha256`, and, when paired, group-scoped `pair_id`, `pair_key` and `pair_status`.

## attempts.jsonl

One JSON object per physical attempt. Required identity fields:

```json
{
  "attempt_id": "run-1-img-1-V04-zxingcpp-1",
  "attempt_index": 1,
  "run_id": "run-1",
  "image_id": "img-1",
  "group_id": "group-a",
  "side_id": "WAVES_QR",
  "relative_path": "a.png",
  "input_sha256": "source-image-sha256",
  "pair_id": "group-scoped-pair-id",
  "strategy_id": "V04",
  "decoder_id": "zxingcpp",
  "decoder_version": "actual-version",
  "status": "DECODED",
  "duration_ms": 12.4,
  "payload": "decoded text",
  "payload_sha256": "sha256-of-utf8-text",
  "payload_hash_algorithm": "sha256",
  "payload_hash_scope": "decoded_text_utf8",
  "payloads": [
    {
      "text": "decoded text",
      "identity": {
        "algorithm": "sha256",
        "scope": "decoded_text_utf8",
        "value": "sha256-of-utf8-text"
      }
    }
  ]
}
```

The payload object may contain identity only. A hash-only identity must explicitly declare algorithm and scope. A hash is never compared with another hash unless both algorithm and scope match. If text and its hash are both present, the validator recomputes SHA-256 over UTF-8 text and rejects a mismatch.

For multi-QR images, `payloads` is the complete decoded payload list. Comparison uses an order-independent identity set; the report separately preserves the number and visible text/hash identities. Multiple symbols in one image are not automatically a conflict.

## Retry semantics

- `attempt_id` is unique for every physical attempt.
- `attempt_index` is a positive, contiguous 1-based retry number within one `(run_id, image_id, strategy_id, decoder_id)` logical combination.
- Retries are retained as evidence, but a logical combination contributes at most one successful image/pair.
- A successful retry may recover an earlier transient `ERROR`; however, two retries that return different payload identity sets invalidate the logical combination.
- Duplicate attempt IDs, duplicate retry indexes, gaps, contradictory statuses, and foreign run/image/hash identities are rejected.

## Status rules

Allowed statuses: `DECODED`, `DETECTED_ONLY`, `NO_DECODE`, `ERROR`, `SKIPPED_EARLY_STOP`, `SKIPPED_INELIGIBLE`, `NOT_RUN`.

- Executed statuses require a finite, non-negative `duration_ms`.
- `DECODED` requires at least one valid payload identity.
- `ERROR` requires a non-empty `error`.
- Any skipped or `NOT_RUN` status requires a non-empty `skip_reason`.
- `NOT_IMPLEMENTED`, `DECODER_UNAVAILABLE` and missing dependencies are not valid ineligibility reasons.
- Contribution mode forbids early stop and requires one or more attempt records for every expected image × strategy × decoder logical combination. A cell may have retries.

## Input and source provenance

The scanner inventories files before execution and inventories them again before finalizing the manifest. Identity is `(group_id, side_id, relative_path)`; the second snapshot detects content changes, additions and deletions even when a filename is unchanged. The validator receives both inventory files, verifies the after-snapshot fingerprint and recomputes the diff instead of trusting the manifest's `STABLE` label. In contribution mode it also re-hashes every current input path to detect changes after the scan completed.

A changed input set is retained as evidence but marked invalid for contribution analysis. It must not produce valid exclusive contribution or removal-loss conclusions.

Validation returns two separate dimensions:

- `structural_status`: whether manifest and attempts are internally consistent.
- `provenance_status`: `VERIFIED` only when the supplied inventory, registry and every source fingerprint file match their declared SHA-256 values.

A structural PASS with provenance NOT_VERIFIED is not a complete contribution audit. Schema 1.x evidence is legacy: it may be inspected, but cannot certify complete contribution metrics.

## File and pair metrics

File metrics count physical images. Pair metrics count only unambiguous `PAIRED` entries. `pair_id` is derived from both group identity and normalized pair key, so identical filenames in different groups cannot collide.

Missing-side, single-directory and ambiguous-pair entries remain in reports, but are excluded from paired contribution denominators. File-level and pair-level exclusive contribution and family-removal loss are separate outputs.

## Commands

```powershell
python scripts/validate_evidence.py --manifest <run-manifest.json> --attempts <attempts.jsonl> --inventory <inventory.json> --inventory-after <inventory-after.json> --registry <strategy-registry.json>
python scripts/run.py contribution --manifest <run-manifest.json> --attempts <attempts.jsonl> --inventory <inventory.json> --inventory-after <inventory-after.json> --out-dir <new-output-directory>
```

The unified CLI and direct analyzer both call the same validator. Never run a direct analysis path that bypasses evidence validation.
