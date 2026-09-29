# Agent instructions: projection cropper

## Purpose

This repository contains the detector-free projection cropper. It isolates
receipt text into word/line crops using grayscale dark-pixel projections and a
limited fallback pass. It does not perform OCR or classification.

## Entrypoint

- `auto_crop_text.py` — one-receipt crop generation.
- `scripts/run_auto_crop.ps1` — PowerShell wrapper.

## Data contract

- AI images are under `data/receipt_dataset/raw/receipts/1_fake` and use label
  `1`.
- Real images are under `data/receipt_dataset/raw/receipts/0_real` and use
  label `0`.
- Keep raw data and generated crops outside this repository.

## Review requirements

Always inspect `contact_sheet.jpg` and `source_with_boxes.jpg` for pilot or
batch outputs. This cropper is dataset-specific and is not a general OCR
detector. Do not treat crops as ground truth without visual review.

## Do not change

Do not modify the PaddleOCR detector or either feature extractor from this
repository. Do not commit datasets, generated images, or Python environments.
