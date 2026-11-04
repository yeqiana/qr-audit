# Contributing to QR Audit

Contributions are welcome for offline QR scanning, adapter contracts, evidence-quality improvements, reproducible fixtures, documentation and tests.

Before opening a PR:

1. Explain the real scanner/problem and affected scope; keep existing image and source inputs protected.
2. Add a deterministic regression test or honestly mark an unverified integration.
3. Run `python -m unittest discover -s tests -v` and `python scripts/validate_skill_package.py`.
4. Never call registered-but-unimplemented variants “executed”. Never fabricate benchmark results or AI-search citations.
5. Never embed private QR payloads, credentials, tokens or customer images in tests or docs.
6. Preserve the difference between ordinary early-stopped scanning and complete contribution experiments.

Issue reports should include sanitized command, versions, minimal fixture, expected/actual result and evidence hashes where available. Git commit messages should use Chinese descriptions following the maintainer convention: `feat: 中文内容` / blank line / `模块名称1,模块名称2` / blank line / `项目名称`.
