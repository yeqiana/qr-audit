# Reproducible Windows paired-directory workflow

Assume a project has the following local layout:

```text
D:\workSpace\本地电脑\03-图片扫描检测\
  检测文件\
    示例组A\
      WAVES_QR\
        a.png
      WAVES_QR_RAW\
        a.png
        b.png
    report\
  qr-tools\
```

### Step 1 — inspect and preserve your existing code

Read project instructions and identify the existing scanner's decoder configuration, 28 strategy definitions and early-stop behavior. Do **not** delete any strategy or overwrite existing images/results.

### Step 2 — run the installed baseline scanner

```powershell
$skill = "$HOME\.agents\skills\qr-audit"
$input = 'D:\workSpace\本地电脑\03-图片扫描检测\检测文件'
$reports = Join-Path $input 'report'
python "$skill\scripts\run.py" scan --input-root "$input" --report-root "$reports" --decoder opencv
```

This requires locally installed Python, OpenCV and NumPy. The command will record **V01–V03 baseline only**; check the returned run directory rather than assuming a fixed timestamp or result.

### Step 3 — inspect the report pairs

Each group receives a report for `WAVES_QR`, one for `WAVES_QR_RAW` and a combined report, **each with a same-stem HTML copy**. For `a.png` the combined report shows both independent results. For `b.png`, it shows the missing left side and the right-side result. It marks “either side locally decoded” if any side returned a QR payload, and surfaces differing payloads as conflicts.

### Step 4 — optional complete 28-strategy contribution experiment

Only after a verified existing implementation exports **all required attempts** per [adapter contract](../../references/adapter-contract.md):

```powershell
python "$skill\scripts\run.py" contribution --manifest '<run>/evidence/run-manifest.json' --attempts '<run>/evidence/attempts.jsonl' --out-dir '<new-output>'
```

The command must return an incomplete/blocked state if the matrix is missing variants or contains early stops. **Do not substitute a baseline scan's attempts as a complete 28-strategy experiment.**

### Step 5 — validate what was and was not proved

- Local `DECODED` = one offline decoder successfully read a payload.
- `DETECTED_ONLY` = detected QR-looking region without payload; not success.
- WeChat scan = `NOT_TESTED` unless a real WeChat scan occurred.
- URL/business validity = `NOT_VERIFIED` unless an independent authorized validation occurred.
- Input images, scanner source and historical reports remain unchanged.