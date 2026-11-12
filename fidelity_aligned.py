"""Pixel fidelity after aligning each subject's bounding box. Local only, no API calls.

fidelity.py compares outputs in place, so a model that zooms or recentres the subject
scores badly even if it kept the subject's pixels. Here, the subject's bounding box in
the input (from the Cutout Labs mask) and in the output (from the output's own alpha,
or the same box for opaque outputs that kept the framing) are both cropped and resized
to the same size before comparing. What remains is mostly redrawing, not reframing.
"""

import csv
import json
import statistics
from pathlib import Path

import numpy as np
from PIL import Image

STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
ids = [r["id"] for r in csv.DictReader(open(STUDY / "manifest.csv", encoding="utf-8"))]
ALPHA_ENGINES = {"cutout_labs": "png", "gpt_flare_edit": "png", "gpt_sunburst_edit": "png"}
SIZE = 512

rows, summary = [], {}
for engine, ext in ALPHA_ENGINES.items():
    diffs, close = [], []
    for i in ids:
        cf = Image.open(RESULTS / "cutout_labs" / f"{i}.png").convert("RGBA")
        cf_a = np.asarray(cf)[:, :, 3]
        if (cf_a > 250).mean() < 0.01:
            continue
        box_in = Image.fromarray((cf_a > 128).astype(np.uint8) * 255).getbbox()
        src = Image.open(STUDY / "images" / "inputs" / f"{i}.jpg").convert("RGB").crop(box_in).resize((SIZE, SIZE))
        mask = np.asarray(cf.crop(box_in).resize((SIZE, SIZE)))[:, :, 3] > 250

        out = Image.open(RESULTS / engine / f"{i}.{ext}").convert("RGBA")
        out_a = np.asarray(out)[:, :, 3]
        box_out = Image.fromarray((out_a > 128).astype(np.uint8) * 255).getbbox()
        if not box_out:
            continue
        o = np.asarray(out.crop(box_out).resize((SIZE, SIZE)), dtype=np.int16)
        m = mask & (o[:, :, 3] > 250)
        if m.mean() < 0.02:
            continue
        d = np.abs(o[:, :, :3] - np.asarray(src, dtype=np.int16))[m].mean(1)
        diffs.append(float(d.mean()))
        close.append(float((d <= 20).mean()))
        rows.append({"engine": engine, "id": i, "aligned_mean_abs_diff": round(diffs[-1], 1),
                     "aligned_pixels_within_20": round(close[-1] * 100, 1)})
    summary[engine] = {"compared": len(diffs),
                       "median_aligned_mean_abs_diff": round(statistics.median(diffs), 1),
                       "median_aligned_pct_within_20": round(statistics.median(close) * 100, 1)}

with open(RESULTS / "fidelity_aligned_per_image.csv", "w", newline="", encoding="utf-8") as fh:
    wr = csv.DictWriter(fh, fieldnames=["engine", "id", "aligned_mean_abs_diff", "aligned_pixels_within_20"])
    wr.writeheader()
    wr.writerows(rows)
(RESULTS / "fidelity_aligned_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
print(json.dumps(summary, indent=1))
