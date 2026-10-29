# Isolated Docling runtime repair — 28 October 2026

This is a continuation after the retained failed setup attempts. It does not replace their receipts or count installation as document accuracy.

The first repaired setup resolved and pinned packages, but exceeded its 900-second extraction budget while installing the CPU Torch 2.8 wheel, whose largest static library was 2,325,803,578 bytes. The partial environment remains rejected.

A new environment uses the official [Torch 2.6 / torchvision 0.21 CPU pair](https://docs.pytorch.org/get-started/previous-versions/), with NumPy 2.2.6, OpenCV 4.12 and Docling IBM models 4.0.4. Every resolved wheel retains its publisher SHA256. Larger hash/copy buffers change I/O granularity only; hash verification and ZIP CRC remain enabled. A read-only, pinned ensurepip wheel bootstraps installation without installing pip into this environment. The frozen OCR runtime is untouched.

| Actual stage | Result | Wall time | Peak owned RSS |
| --- | --- | ---: | ---: |
| Exact 40-package installation, dependency and installed-version checks | PASS | 624.235 s | 195,436,544 B |
| Native NumPy ↔ Torch array roundtrip and OpenCV resize, CPU one thread | PASS | 50.672 s | 239,673,344 B |

The exact-wheel installation itself took 483.109 seconds within its existing 900-second bound. Both supervised stages exited zero, closed their owned process trees and released the shared lock. The ABI probe loaded no document images, model weights or predictions. Repeating diagnostic stack dumps may say `Timeout` even during a successful step; terminal resource/result receipts determine whether a deadline actually failed.

The split Egret-layout and TableFormer inference stages remain separate from this runtime proof. Endpoint measurement is pending actual prediction, a parser → frozen scorer → result-writer preflight, and all-484 coverage. Its retained control remains 323/585, not the separate 324 fresh-reading result. No assistant transcription, reference/threshold changes or production activation are allowed.

The 585 product-present reference fields cover 105 images. There are 191 images with any benchmark reference and 293 without any; the 484-page execution inventory must be reported independently of the labelled-field score. This is an already-used development set with no confirmed gold labels.
