"""Detector-free text cropper for clean receipt-like images.

The program intentionally does not use OCR or a text-detection model. It uses
dark-pixel row/column projections to propose text bands and then writes crops
with a fixed amount of padding around the measured ink bounds. It is designed
for the synthetic receipts in this project; uncertain cases should still be
reviewed using the generated contact sheet and source preview.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps


def contiguous_runs(values: np.ndarray) -> list[tuple[int, int]]:
    """Return inclusive contiguous true runs from a boolean vector."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, value in enumerate(values.tolist()):
        if value and start is None:
            start = i
        elif not value and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(values) - 1))
    return runs


def merge_runs(runs: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        old_start, old_end = merged[-1]
        if start - old_end - 1 <= max_gap:
            merged[-1] = (old_start, end)
        else:
            merged.append((start, end))
    return merged


def find_text_bands(
    dark: np.ndarray,
    min_row_pixels: int = 3,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Find horizontal text bands and separately record barcode bands."""
    h, w = dark.shape
    row_counts = dark.sum(axis=1)
    active = row_counts >= max(min_row_pixels, int(round(w * 0.001)))
    raw = contiguous_runs(active)
    bands = merge_runs(raw, max_gap=2)
    kept: list[tuple[int, int]] = []
    barcode_bands: list[tuple[int, int]] = []
    for y1, y2 in bands:
        band_h = y2 - y1 + 1
        peak = int(row_counts[y1 : y2 + 1].max())
        # Separator rules are short, very dark horizontal bands. Barcode bars
        # are much taller and span a large portion of the receipt width.
        col_counts = dark[y1 : y2 + 1].sum(axis=0)
        xs = np.flatnonzero(col_counts > 0)
        span = int(xs[-1] - xs[0] + 1) if xs.size else 0
        band_pixels = dark[y1 : y2 + 1]
        density = float(band_pixels.mean())
        if band_h <= 12 and span > int(w * 0.20):
            continue
        # Barcode bars form a tall, dense band with very similar ink coverage
        # on almost every row.  The row-coverage check prevents large bold
        # receipt headers from being mistaken for barcodes.
        row_mean = float(np.median(band_pixels.sum(axis=1)) / max(1, span))
        row_cv = float(band_pixels.sum(axis=1).std() / max(1.0, band_pixels.sum(axis=1).mean()))
        barcode_like = (
            band_h >= 60 and span > int(w * 0.30) and density > 0.15
        ) or (
            band_h >= 40
            and span > int(w * 0.30)
            and density > 0.18
            and row_mean > 0.45
            and row_cv < 0.16
        )
        if barcode_like:
            barcode_bands.append((y1, y2))
            continue
        if band_h >= 80 and span > int(w * 0.30):
            continue
        if band_h >= 2:
            kept.append((y1, y2))
    return kept, barcode_bands


def find_segments(dark: np.ndarray, y1: int, y2: int) -> list[tuple[int, int, int, int]]:
    """Split a text band into fields/words while preserving normal spaces."""
    band = dark[y1 : y2 + 1]
    col_counts = band.sum(axis=0)
    active = col_counts >= 1
    runs = contiguous_runs(active)
    line_h = y2 - y1 + 1
    # Merge character/word gaps, but retain the much larger gaps between
    # receipt columns. The threshold scales with text height.
    runs = merge_runs(runs, max_gap=max(5, int(round(line_h * 1.80))))
    segments: list[tuple[int, int, int, int]] = []
    for x1, x2 in runs:
        sub = band[:, x1 : x2 + 1]
        ys, xs = np.where(sub)
        if ys.size < 20:
            continue
        bx1, bx2 = x1 + int(xs.min()), x1 + int(xs.max())
        by1, by2 = y1 + int(ys.min()), y1 + int(ys.max())
        bbox_w, bbox_h = bx2 - bx1 + 1, by2 - by1 + 1
        ink_box = sub[int(ys.min()) : int(ys.max()) + 1,
                      int(xs.min()) : int(xs.max()) + 1]
        density = float(ink_box.mean())
        column_coverage = float(np.count_nonzero(ink_box.sum(axis=0)) / bbox_w)
        # Reject residual rules, edge fragments, and isolated specks. Normal
        # receipt glyphs are substantially taller than these artifacts.
        if bbox_h <= 12 and bbox_w >= 30:
            continue
        if bbox_w <= 5 or bbox_h <= 5:
            continue
        if bbox_w <= 7 and bbox_h <= 12:
            continue
        if bbox_w >= 30 and density < 0.11:
            continue
        if bbox_w >= 30 and bbox_h <= 25 and column_coverage > 0.85:
            continue
        segments.append((bx1, by1, bx2, by2))
    return segments


def find_inverse_segments(gray: np.ndarray, dark: np.ndarray, y1: int, y2: int) -> list[tuple[int, int, int, int]]:
    """Find light text printed on a dark filled row (for example table headers)."""
    dark_band = dark[y1 : y2 + 1]
    xs = np.flatnonzero(dark_band.sum(axis=0) > 0)
    if xs.size == 0 or float(dark_band.mean()) < 0.50:
        return []
    light = gray[y1 : y2 + 1] > 180
    runs = contiguous_runs(light.sum(axis=0) >= 2)
    band_x1, band_x2 = int(xs[0]), int(xs[-1])
    runs = [
        (a, b)
        for a, b in runs
        if not (
            b - a + 1 < gray.shape[1] * 0.15
            and (a <= band_x1 + 15 or b >= band_x2 - 15)
        )
    ]
    # White glyphs may be interrupted by scratches in the dark ink band;
    # allow a larger internal gap while keeping the much larger gaps between
    # header fields intact.
    runs = merge_runs(runs, max_gap=25)
    segments: list[tuple[int, int, int, int]] = []
    for x1, x2 in runs:
        sub = light[:, x1 : x2 + 1]
        ys, x_offsets = np.where(sub)
        if ys.size < 8:
            continue
        bx1, bx2 = x1 + int(x_offsets.min()), x1 + int(x_offsets.max())
        by1, by2 = y1 + int(ys.min()), y1 + int(ys.max())
        near_side_edge = bx1 < gray.shape[1] * 0.03 or bx2 > gray.shape[1] * 0.97
        if near_side_edge and bx2 - bx1 + 1 < gray.shape[1] * 0.05:
            continue
        if bx2 - bx1 + 1 >= 12 and by2 - by1 + 1 >= 8:
            segments.append((bx1, by1, bx2, by2))
    return segments


def make_crop(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    padding: int,
    barcode_bands: list[tuple[int, int]] | None = None,
    neighboring_bands: tuple[tuple[int, int] | None, tuple[int, int] | None] = (None, None),
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    x1, y1, x2, y2 = bbox
    left = max(0, x1 - padding)
    top = max(0, y1 - padding)
    previous_band, next_band = neighboring_bands
    if previous_band is not None:
        prev_y2 = previous_band[1]
        if top <= prev_y2:
            top = prev_y2 + 1
    # Keep the human-readable digits below a barcode separate from the bars.
    # The normal 8 px top padding is reduced only when it would cross a
    # detected barcode band.
    for bar_y1, bar_y2 in barcode_bands or []:
        if y1 > bar_y2 and top <= bar_y2:
            top = bar_y2 + 1
            break
    right = min(image.width - 1, x2 + padding)
    bottom = min(image.height - 1, y2 + padding)
    if next_band is not None:
        next_y1 = next_band[0]
        if bottom >= next_y1:
            bottom = next_y1 - 1
    box = (left, top, right + 1, bottom + 1)
    return image.crop(box), (left, top, right - left + 1, bottom - top + 1)


def write_contact_sheet(crop_paths: list[Path], output: Path) -> None:
    cell_w, cell_h, cols = 330, 100, 3
    rows = max(1, math.ceil(len(crop_paths) / cols))
    sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(crop_paths):
        with Image.open(path) as crop:
            thumb = crop.convert("RGB")
            thumb.thumbnail((300, 65))
            x = (i % cols) * cell_w + 10
            y = (i // cols) * cell_h + 20
            sheet.paste(thumb, (x, y))
        label = path.stem[:34]
        draw.text(((i % cols) * cell_w + 8, (i // cols) * cell_h + 3), label, fill="black")
    sheet.save(output, quality=95)


def process_image(input_path: Path, output_dir: Path, threshold: int, padding: int) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(input_path).convert("RGB")
    gray = np.asarray(ImageOps.grayscale(image), dtype=np.uint8)
    dark = gray < threshold
    bands, barcode_bands = find_text_bands(dark)
    fallback_used = False
    adaptive_used = False
    detection_mode = "normal"
    # Some textured/scanned receipts have a few dark background pixels on
    # almost every row.  That can connect the full image into one giant band
    # and produce zero text candidates.  Retry only those failed images with
    # a stricter row-ink requirement; successful images retain the original
    # behavior and coordinates.
    if not any(find_segments(dark, y1, y2) for y1, y2 in bands):
        fallback_row_pixels = max(8, int(round(image.width * 0.015)))
        bands, barcode_bands = find_text_bands(dark, fallback_row_pixels)
        fallback_used = True
        detection_mode = "strict_fallback"

    # A textured paper background can place a few dark pixels on nearly every
    # row, defeating both global projection passes. In that zero-crop case
    # only, use local contrast against a blurred background. This keeps the
    # normal successful path unchanged while recovering text strokes that are
    # darker than their immediate paper neighborhood.
    if not any(find_segments(dark, y1, y2) for y1, y2 in bands):
        blurred = np.asarray(
            Image.fromarray(gray).filter(ImageFilter.GaussianBlur(radius=5)),
            dtype=np.float32,
        )
        local_contrast_dark = gray.astype(np.float32) < (blurred - 18.0)
        adaptive_row_pixels = max(30, int(round(image.width * 0.08)))
        adaptive_bands, adaptive_barcodes = find_text_bands(local_contrast_dark, adaptive_row_pixels)
        if any(find_segments(local_contrast_dark, y1, y2) for y1, y2 in adaptive_bands):
            dark = local_contrast_dark
            bands = adaptive_bands
            barcode_bands = adaptive_barcodes
            fallback_used = True
            adaptive_used = True
            detection_mode = "adaptive_local_contrast"

    inverse_segments: list[tuple[int, int, int, int]] = []
    if fallback_used and not adaptive_used:
        row_counts = dark.sum(axis=1)
        active = row_counts >= max(8, int(round(image.width * 0.015)))
        for raw_y1, raw_y2 in merge_runs(contiguous_runs(active), max_gap=2):
            band_h = raw_y2 - raw_y1 + 1
            if 20 <= band_h <= 60:
                inverse_segments.extend(find_inverse_segments(gray, dark, raw_y1, raw_y2))
    rows: list[dict[str, object]] = []
    crop_paths: list[Path] = []
    boxes: list[tuple[int, int, int, int]] = []
    crop_index = 1
    for band_index, (y1, y2) in enumerate(bands):
        neighboring_bands = (
            bands[band_index - 1] if band_index > 0 else None,
            bands[band_index + 1] if band_index + 1 < len(bands) else None,
        )
        for x1, yy1, x2, yy2 in find_segments(dark, y1, y2):
            if fallback_used:
                bbox_w = x2 - x1 + 1
                bbox_h = yy2 - yy1 + 1
                near_side_edge = x1 < image.width * 0.03 or x2 > image.width * 0.97
                if near_side_edge and bbox_w < image.width * 0.05:
                    continue
                if adaptive_used:
                    adaptive_edge = x1 < image.width * 0.05 or x2 > image.width * 0.95
                    if adaptive_edge and bbox_w < image.width * 0.08:
                        continue
                # In noisy scans, simple logos above the merchant name can
                # resemble isolated glyphs. Restrict this rule to the fallback
                # path and only to tall, compact shapes near the image top.
                if (
                    yy2 < image.height * 0.25
                    and bbox_h >= 45
                    and bbox_w < image.width * 0.20
                ):
                    continue
            crop, box = make_crop(
                image,
                (x1, yy1, x2, yy2),
                padding,
                barcode_bands,
                neighboring_bands,
            )
            filename = f"crop_{crop_index:03d}.png"
            path = output_dir / filename
            crop.save(path)
            crop_paths.append(path)
            boxes.append(box)
            rows.append({
                "source_image": input_path.name,
                "crop_id": f"crop_{crop_index:03d}",
                "source_x": box[0], "source_y": box[1],
                "width": box[2], "height": box[3],
                "padding_px": padding, "threshold": threshold,
                "detection_mode": detection_mode,
                "file": filename,
            })
            crop_index += 1

    # Append inverse-text fields after ordinary dark-text fields so their
    # coordinates are included in the same manifest and source preview.
    if inverse_segments:
        for x1, yy1, x2, yy2 in inverse_segments:
            crop, box = make_crop(image, (x1, yy1, x2, yy2), padding, barcode_bands)
            filename = f"crop_{crop_index:03d}.png"
            path = output_dir / filename
            crop.save(path)
            crop_paths.append(path)
            boxes.append(box)
            rows.append({
                "source_image": input_path.name,
                "crop_id": f"crop_{crop_index:03d}",
                "source_x": box[0], "source_y": box[1],
                "width": box[2], "height": box[3],
                "padding_px": padding, "threshold": threshold,
                "detection_mode": detection_mode,
                "file": filename,
            })
            crop_index += 1

    with (output_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["source_image"])
        writer.writeheader()
        writer.writerows(rows)

    preview = image.copy()
    draw = ImageDraw.Draw(preview)
    for x, y, w, h in boxes:
        draw.rectangle((x, y, x + w - 1, y + h - 1), outline=(50, 205, 50), width=2)
    preview.save(output_dir / "source_with_boxes.jpg", quality=95)
    write_contact_sheet(crop_paths, output_dir / "contact_sheet.jpg")
    return len(crop_paths)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--threshold", type=int, default=130)
    parser.add_argument("--padding", type=int, default=8)
    args = parser.parse_args()
    count = process_image(args.input, args.output_dir, args.threshold, args.padding)
    print(f"created={count} crops")


if __name__ == "__main__":
    main()
