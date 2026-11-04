# Generic Strategy and Decoder Adapter Contract

QR Audit ships a reference implementation for V01–V03 only. It does not recreate the user's existing V04–V28 preprocessing logic. The adapter contract lets an existing scanner register its real functions without changing their image algorithms.

## Module entrypoint

Create an importable Python module with:

```python
def register_qr_audit(strategies, decoders, context):
    strategies.register(
        "V04",
        transform=existing_v04_transform,
        version="scanner-build-2026.11",
        parameters={"scale": 4, "border_modules": 4},
        applicability=eligible_for_v04,
    )
    decoders.register(
        "my_decoder",
        decode=decode_with_existing_decoder,
        version="decoder-actual-version",
        options={"try_harder": True},
    )
```

The module is imported locally. It must not perform network access, install dependencies, log in to WeChat, or open decoded URLs.

## Strategy transform

```python
def transform(image, context, parameters):
    # Return the transformed image object consumed by decoder adapters.
    # Do not mutate the original source file.
    return existing_preprocess(image, **parameters)
```

The callable receives `(image, context, parameters)`. The context currently includes `cv2`, `numpy`, `input_root`, the selected run mode, and mutable `source_files` / `dependencies` lists. An adapter that delegates to helper source files should append their paths to `context["source_files"]`; add each external package/build as `{"name": "...", "version": "..." }` to `context["dependencies"]`. Declared source files are SHA-256 fingerprinted and missing paths block the run.

Optional applicability callback:

```python
def eligible(image_meta, context, parameters):
    return True
    # or: return False, "LOW_RESOLUTION"
```

A false result is recorded as `SKIPPED_INELIGIBLE` with its reason. Missing executor implementations are recorded as `NOT_RUN / NOT_IMPLEMENTED`, never as ineligible.

## Decoder adapter

The callable receives `(transformed_image, context, options)` and returns either:

```python
{"payloads": ["QR payload A", "QR payload B"], "candidate_count": 2}
```

or a compatible `(payloads, candidate_count)` tuple. Return every QR payload found, not only the first. QR Audit records UTF-8 text identities by default. If the decoder exposes only a hash, return payload identity objects with explicit algorithm, scope and value; never label an unknown hash scope as decoded-text SHA-256.

## Registering the existing 28 strategies

The initial registry remains the frozen source of strategy IDs and order. Register the actual implementation against its existing `V01`–`V28` ID. If a strategy definition is intentionally added or renamed, update and review the registry as a separate change so the registry fingerprint changes visibly.

The adapter may replace a built-in reference implementation only by passing `replace=True`. This must be explicit and should be used only when source audit confirms the replacement is the user's actual implementation.

## Running

Make the module importable on `PYTHONPATH`, then:

```powershell
python scripts/run.py scan --input-root <images> --report-root <reports> --adapter-module my_qr_adapter --decoder my_decoder
python scripts/run.py scan --experiment-mode contribution --input-root <images> --report-root <reports> --adapter-module my_qr_adapter --decoder my_decoder
```

Normal `scan` mode may stop after a successful strategy and records later attempts as `SKIPPED_EARLY_STOP`. Contribution mode disables early stopping and executes every registered strategy/selected decoder combination. An unregistered strategy or unavailable decoder is an explicit `NOT_RUN` and blocks complete contribution metrics.

## Fingerprints and evidence

QR Audit records the adapter module's local source path and SHA-256 along with its own scanner files and registry. The validator checks those files still match. If the adapter delegates to external native libraries, record their exact versions and build identities in decoder metadata/options and the run's dependency evidence.

A keyword search hit is only `HINT_ONLY`. A registered function is `EXECUTOR_REGISTERED`; source confirmation and runtime confirmation remain separate audit states.

## Alternative: existing native executable over local CLI

Use `scripts/external_cli_adapter.py` when the scanner is an existing C++/Java executable rather than Python-callable transforms. This is an **opt-in bridge, not an implementation of the 28 algorithms**.

Set `QR_AUDIT_BRIDGE_CONFIG` to an absolute JSON file following `examples/native-cli-bridge/bridge-config.example.json`. The executable must receive literal argv (never a shell command) and return a single JSON object on stdout with mandatory fields `run_id`, `image_id`, `input_sha256`, `strategy_id`, `native_strategy`, `decoder_id`, `status`, `payloads`, `candidate_count`. Native statuses may include `DECODED`, `NO_DECODE`, `DETECTED_ONLY`, `NOT_RUN`, `SKIPPED_INELIGIBLE`, `ERROR`; errors/skips require reasons.

Each source-file strategy bypasses pixel decoding in Python, so a fully connected native bridge does not require OpenCV or NumPy. All native implementation mappings must be source-confirmed; a process that only echoes requested IDs without executing the corresponding preprocessing does not constitute credible evidence. The executable, bridge config and declared source files are fingerprinted.

See [onboarding and acceptance procedure](../docs/real-scanner-onboarding.md).
