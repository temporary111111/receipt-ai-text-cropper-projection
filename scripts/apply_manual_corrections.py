"""Apply reviewed, per-image crop corrections without changing the cropper."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from PIL import Image, ImageDraw


def write_contact_sheet(crop_paths: list[Path], output: Path) -> None:
    cell_w, cell_h, cols = 330, 100, 3
    rows = max(1, (len(crop_paths) + cols - 1) // cols)
    sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(crop_paths):
        with Image.open(path) as crop:
            thumb = crop.convert("RGB")
            thumb.thumbnail((300, 65))
            x = (i % cols) * cell_w + 10
            y = (i // cols) * cell_h + 20
            sheet.paste(thumb, (x, y))
        draw.text(((i % cols) * cell_w + 8, (i // cols) * cell_h + 3), path.stem[:34], fill="black")
    sheet.save(output, quality=95)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--corrections", type=Path, required=True)
    args = parser.parse_args()

    corrections: dict[tuple[str, str], dict[str, str]] = {}
    with args.corrections.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            corrections[(row["receipt"], row["crop_id"])] = row
    affected_receipts = {receipt for receipt, _ in corrections}

    for receipt_dir in sorted(p for p in args.batch.iterdir() if p.is_dir() and p.name.startswith("receipt_")):
        if receipt_dir.name not in affected_receipts:
            continue
        manifest_path = receipt_dir / "manifest.csv"
        if not manifest_path.exists():
            continue
        with manifest_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        kept: list[dict[str, str]] = []
        boxes: list[tuple[int, int, int, int]] = []
        crop_paths: list[Path] = []
        source_name = rows[0]["source_image"] if rows else receipt_dir.name + ".png"
        source_path = args.dataset_root / source_name
        with Image.open(source_path) as source:
            source = source.convert("RGB")
            for row in rows:
                correction = corrections.get((receipt_dir.name, row["crop_id"]))
                if correction and correction["action"] == "remove":
                    crop_path = receipt_dir / row["file"]
                    if crop_path.exists():
                        crop_path.unlink()
                    continue
                if correction and correction["action"] == "replace_box":
                    x = int(row["source_x"])
                    y = int(correction["source_y"])
                    w = int(row["width"])
                    h = int(correction["height"])
                    left, top = max(0, x), max(0, y)
                    right = min(source.width, x + w)
                    bottom = min(source.height, y + h)
                    source.crop((left, top, right, bottom)).save(receipt_dir / row["file"])
                    row["source_y"] = str(top)
                    row["height"] = str(bottom - top)
                kept.append(row)
                boxes.append((int(row["source_x"]), int(row["source_y"]), int(row["width"]), int(row["height"])))
                crop_paths.append(receipt_dir / row["file"])

            with manifest_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source_image", "crop_id", "source_x", "source_y", "width", "height", "padding_px", "threshold", "file"])
                writer.writeheader()
                writer.writerows(kept)

            preview = source.copy()
            draw = ImageDraw.Draw(preview)
            for x, y, w, h in boxes:
                draw.rectangle((x, y, x + w - 1, y + h - 1), outline=(50, 205, 50), width=2)
            preview.save(receipt_dir / "source_with_boxes.jpg", quality=95)
        write_contact_sheet(crop_paths, receipt_dir / "contact_sheet.jpg")


if __name__ == "__main__":
    main()
