# Security Policy

## Scope

QR images and decoded payloads are untrusted input. QR Audit runs only local decoders and **never requests QR payload URLs**. Avoid uploading private sample images or raw tokens to public issues.

## Reporting a vulnerability

If you suspect a path traversal, malicious input execution, HTML injection, insecure file overwrite, URL fetching, or secret exposure, do **not** create a public proof containing user data. Use GitHub's private vulnerability reporting feature for this repository if enabled; otherwise contact the maintainer through a private channel before disclosing details.

## Explicit boundaries

- Installing untrusted decoder packages/models may introduce risks; the Skill never silently installs them.
- Local SHA-256 records provide evidence consistency, **not** tamper-proof attestation.
- The HTML renderer is a static viewer, not a sandbox for executable QR payload content.
- Human verification is still required for business validity, payload conflicts and external scanner compatibility.
