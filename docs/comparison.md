# QR Audit vs ZXing-C++, OpenCV and ZBar

QR Audit is **not another QR decoder**. It is a workflow and evidence layer around one or more locally installed decoders and existing image preprocessing recipes.

| System | Primary role | What QR Audit adds |
| --- | --- | --- |
| [ZXing-C++](https://github.com/zxing-cpp/zxing-cpp) | Barcode/QR decoding library with configurable options | Independent attempt evidence, experiment completeness, per-strategy and family-level contribution reporting |
| [OpenCV QRCodeDetector](https://docs.opencv.org/4.x/de/dc3/classcv_1_1QRCodeDetector.html) | Computer-vision QR detection and decoding | Group pairing, provenance, alternate preprocessing and report generation |
| [ZBar](https://github.com/mchehab/zbar) | Barcode/QR scanning library | Cross-decoder comparison and evidence contracts if present |
| QR Audit | Local scanning workflow + audit + measurement + reports | It cannot replace decoder algorithms or guarantee compatibility with WeChat |

### Key differences

1. **Scanner vs auditor:** Decoders answer “what QR payload did we get?”; QR Audit asks “which image, transform, decoder, parameters and run produced it?”
2. **Thresholds vs validated transformations:** The 28 initial recipes are historical definitions. Only three reference recipes are implemented within the package; the remaining ones need a verified scanner adapter.
3. **Speed vs attribution:** Fast production scanning may stop on success. Contribution analysis cannot stop early if it claims a complete counterfactual impact analysis.
4. **Detection vs decoding vs business success:** They are distinct statuses. QR Audit does not follow QR payload URLs.
5. **Gen UI vs static HTML:** [gen-ui](https://github.com/yeqiana/gen-ui) is optional guidance for readable presentations, not a decoder or an offline interactive renderer.

### Not a substitute for the WeChat app

Open-source decoders may behave differently from the WeChat app. An offline decoded payload supports a bounded claim only: this chosen decoder and recipe successfully decoded the image in this recorded run. The skill never uses a logged-in WeChat account.