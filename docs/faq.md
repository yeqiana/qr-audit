# FAQ — Offline QR Code Scanning and Strategy Audit

## Can I scan QR images without logging into WeChat?

Yes, with locally installed open-source QR decoders. QR Audit's reference scanner uses OpenCV, optionally ZXing-C++ when locally available. It **does not use the WeChat app or WeChat cloud APIs**. A successful local decode is not proof of WeChat's behavior.

## Does QR Audit actually implement 28 preprocessing methods?

No. The initial registry contains **28 definitions**, keeping the original ordering and stable IDs. The bundled reference scanner implements V01 original, V02 grayscale and V03 reference contrast only. V04–V28 need the user's existing scanner or a verified adapter. The package **must not call registration an execution result**.

## Will it reduce manual review automatically?

It can reduce manual rechecks only for images that are successfully and consistently decoded by local engines; the result on any real image set is not established until measured. Disagreements, undecoded images and unverified business semantics remain visible in manual-review queues.

## Why do I need both scan and contribution modes?

Ordinary scanning may stop after first success to save time. A full contribution experiment runs every **eligible** strategy × decoder combination and records all skipped reasons. Without a complete experiment, individual exclusivity and whole-family removal loss cannot be reliably calculated.

## Can I delete every strategy whose exclusive success count is zero?

No. Two pure-mode strategies could solve the same hard image, giving each zero exclusive success, while **removing both** loses that image. Use **whole-family removal loss** before considering an entire branch. QR Audit never deletes strategies itself.

## What is a QR-code preprocessing strategy?

A named combination of image modifications (grayscale, contrast, thresholding, inversion, scaling, borders, module sampling) and sometimes decoder configuration (`isPure`). A strategy is not necessarily one distinct algorithm; different combinations may overlap.

## How does it handle WAVES_QR and WAVES_QR_RAW?

Those are default **directory side names**, not decoder names. By default files are paired by normalized relative path; missing sides and ambiguous basename matches are explicitly reported. The combined report marks a pair as locally decoded when either side returns a payload, while keeping per-side results and conflicts.

## Do all QR payload URLs get opened to verify the result?

Never. URLs are untrusted plain-text payload. They are not fetched or followed. `DECODED` only means the QR payload was read; business usefulness and website availability are separate checks not performed here.

## Why are output formats both Markdown and HTML?

Markdown preserves a readable, diffable evidence trail. An HTML file with the **same stem** is generated from the same structured report data, with inline CSS, safe escaping, offline rendering and responsive tables. No live server, CDN or scripting is required to view it.

## Is gen-ui required to produce the HTML?

No. The [gen-ui Skill](https://github.com/yeqiana/gen-ui) is optional presentation guidance. The built-in renderer creates the static file; do not claim it renders interactive ChatGPT components offline.

## Does QR Audit require WebCodex, MCP, or an ACP runtime?

No for the Skill instructions. The bundled helper CLI requires Python and the baseline scanner requires locally installed OpenCV + NumPy. A user's own 28-variant scanner may have additional dependencies.

## What can I audit if I cannot run the user's scanner?

The `audit` command can locate candidate code references, and an Agent can inspect real code/configuration. Keyword matches are only `HINT_ONLY`; runtime usage must be confirmed from execution logs and input/strategy/decoder evidence.

## How do I install or use this with Codex and Claude Code?

Clone the folder to your active host's Skills directory (`~/.agents/skills/qr-audit` for a common Codex setup or `~/.claude/skills/qr-audit` for Claude Code), restart the session and invoke `$qr-audit` or `/qr-audit` as supported by that host. See the [README](../README.md) for Windows commands.

## Is there a guaranteed recall rate or search-engine ranking?

No. The bundled smoke checks are not a real-world benchmark. Neither GitHub discoverability nor AI answer citation is guaranteed. See [reproducible evaluation](geo-methodology.md).
