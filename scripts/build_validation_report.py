"""Build a compact QA report for a batch of generated receipt crops."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    batch = args.batch
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    receipt_dirs = sorted(p for p in batch.iterdir() if p.is_dir() and p.name.startswith("receipt_"))

    summaries: list[dict[str, object]] = []
    aggregate_rows: list[dict[str, object]] = []
    for receipt_dir in receipt_dirs:
        manifest = receipt_dir / "manifest.csv"
        rows = list(csv.DictReader(manifest.open(encoding="utf-8", newline=""))) if manifest.exists() else []
        crop_count = len(rows)
        summaries.append({
            "receipt": receipt_dir.name,
            "crop_count": crop_count,
            "fallback_or_special_review": "yes" if receipt_dir.name == "receipt_0038" else "no",
            "status": "review" if crop_count == 0 or crop_count < 15 else "ok",
        })
        for row in rows:
            row = dict(row)
            row["receipt"] = receipt_dir.name
            aggregate_rows.append(row)

    with (output / "crop_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["receipt", "crop_count", "fallback_or_special_review", "status"])
        writer.writeheader()
        writer.writerows(summaries)

    aggregate_fields = ["receipt", "source_image", "crop_id", "source_x", "source_y", "width", "height", "padding_px", "threshold", "file"]
    with (output / "aggregate_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=aggregate_fields)
        writer.writeheader()
        writer.writerows(aggregate_rows)

    cols, cell_w, cell_h = 5, 360, 280
    rows = max(1, math.ceil(len(receipt_dirs) / cols))
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    for index, receipt_dir in enumerate(receipt_dirs):
        contact = receipt_dir / "contact_sheet.jpg"
        x = (index % cols) * cell_w
        y = (index // cols) * cell_h
        draw.text((x + 8, y + 5), f"{receipt_dir.name}  ({len([p for p in receipt_dir.glob('crop_*.png')])} crops)", fill="black")
        if contact.exists():
            with Image.open(contact) as image:
                thumb = image.convert("RGB")
                thumb.thumbnail((cell_w - 16, cell_h - 32))
                sheet.paste(thumb, (x + 8, y + 25))
    sheet.save(output / "validation_overview.jpg", quality=92)

    # A single 50-receipt image is useful as an index but cannot remain sharp
    # when zoomed. Export high-resolution pages with five native-width contact
    # sheets per page; each page is intended for zoomed inspection.
    highres_dir = output / "highres_overviews"
    highres_dir.mkdir(exist_ok=True)
    page_size = 5
    for page_start in range(0, len(receipt_dirs), page_size):
        page_dirs = receipt_dirs[page_start : page_start + page_size]
        panels: list[Image.Image] = []
        max_width = 0
        for receipt_dir in page_dirs:
            contact = receipt_dir / "contact_sheet.jpg"
            if not contact.exists():
                continue
            with Image.open(contact) as image:
                panel = image.convert("RGB")
            title_h = 42
            titled = Image.new("RGB", (panel.width, panel.height + title_h), "white")
            titled.paste(panel, (0, title_h))
            ImageDraw.Draw(titled).text((8, 10), receipt_dir.name, fill="black")
            panels.append(titled)
            max_width = max(max_width, titled.width)
        page_h = sum(panel.height for panel in panels)
        page = Image.new("RGB", (max_width, page_h), "white")
        y = 0
        for panel in panels:
            page.paste(panel, (0, y))
            y += panel.height
        page.save(highres_dir / f"validation_overview_{page_start // page_size + 1:02d}.jpg", quality=95)

    total = sum(int(item["crop_count"]) for item in summaries)
    reviewed = sum(1 for item in summaries if item["status"] == "review")
    (output / "README.md").write_text(
        f"# Fake batch validation\n\n"
        f"Receipts reviewed: {len(summaries)}\n\n"
        f"Total crops: {total}\n\n"
        f"Receipts requiring attention by count rule: {reviewed}\n\n"
        "Use `validation_overview.jpg` for visual QA, `crop_summary.csv` for per-receipt counts, "
        "and `aggregate_manifest.csv` for all crop coordinates.\n\n"
        "For zoomed inspection, use the native-width pages in `highres_overviews/`.\n",
        encoding="utf-8",
    )
    print(f"receipts={len(summaries)} crops={total} flagged={reviewed}")


if __name__ == "__main__":
    main()
