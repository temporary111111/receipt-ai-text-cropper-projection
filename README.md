# Receipt text cropper

This standalone program prepares receipt images for the later AI-generated-vs-real text classification study. It isolates visible text into individual PNG crops and does not run OCR or classification.

## What it produces

For each input receipt, the cropper writes:

- one PNG crop per detected text word/line;
- `manifest.csv` containing source coordinates and crop metadata;
- `source_with_boxes.jpg` generated from the same crop coordinates;
- `contact_sheet.jpg` for visual review.

The cropper is detector-free. It uses grayscale dark-pixel projections and a limited fallback pass for unusually textured receipts. Every batch should still be visually inspected before the crops are treated as ground truth.

## Workspace layout

The code is kept separate from the shared dataset:

```text
C:\Users\dev\Workspace\school\elective\
├── programs\
│   ├── receipt_text_cropper\
│   │   ├── auto_crop_text.py
│   │   └── scripts\
│   └── receipt_feature_extractor\
└── data\
    └── receipt_dataset\
        ├── raw\
        │   └── receipts\
        │       ├── 0_real\
        │       └── 1_fake\
        ├── processed\
        │   └── crops\
        │       └── <crop runs and validation outputs>
        └── features\
            └── pilots\
```

The raw images and generated outputs are intentionally outside the program folder so both programs can use the same dataset without duplicating it.

## Run one receipt

From this folder, using the bundled Python runtime:

```powershell
$py = 'C:\Users\dev\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$input = '..\..\data\receipt_dataset\raw\receipts\1_fake\receipt_0001.png'
$output = '..\..\data\receipt_dataset\processed\crops\receipt_0001'

& $py '.\auto_crop_text.py' `
  --input $input `
  --output-dir $output `
  --threshold 130 `
  --padding 8
```

The PowerShell wrapper in `scripts\run_auto_crop.ps1` accepts the same input and output paths.

## Review rule

Inspect `contact_sheet.jpg` and, when needed, `source_with_boxes.jpg` for every pilot or batch before using the crops for feature extraction. The cropper is tuned for this receipt dataset and is not a general-purpose OCR/text detector.
