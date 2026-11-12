"""How much of the original photo survives in each output. Local only, no API calls.

For each output whose aspect ratio matches the input, resize it to the input size and
compare it with the input photo inside the subject area (where the Cutout Labs cutout
is opaque and, for engines with alpha, where that engine's output is opaque too).
A cutout that keeps the photo's own pixels in place scores near 0; a subject that was
redrawn, moved, or rescaled scores high.
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
ENGINES = {"cutout_labs": "png", "gemini_2_5": "png", "gemini_3_1": "jpg",
           "gpt_flare_edit": "png", "gpt_sunburst_edit": "png"}

rows, summary = [], {}
for engine, ext in ENGINES.items():
    diffs, close, skipped = [], [], 0
    for i in ids:
        src = np.asarray(Image.open(STUDY / "images" / "inputs" / f"{i}.jpg").convert("RGB"), dtype=np.int16)
        h, w = src.shape[:2]
        subject = np.asarray(Image.open(RESULTS / "cutout_labs" / f"{i}.png").convert("RGBA"))[:, :, 3] > 250
        out = Image.open(RESULTS / engine / f"{i}.{ext}")
        if abs(out.width / out.height - w / h) > 0.03 or subject.mean() < 0.01:
            skipped += 1
            continue
        out = out.convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        o = np.asarray(out, dtype=np.int16)
        mask = subject & (o[:, :, 3] > 250)
        if mask.mean() < 0.005:
            rows.append({"engine": engine, "id": i, "mean_abs_diff": "", "pixels_within_20": "", "note": "subject missing"})
            diffs.append(255.0)
            close.append(0.0)
            continue
        d = np.abs(o[:, :, :3] - src)[mask].mean(1)
        diffs.append(float(d.mean()))
        close.append(float((d <= 20).mean()))
        rows.append({"engine": engine, "id": i, "mean_abs_diff": round(diffs[-1], 1),
                     "pixels_within_20": round(close[-1] * 100, 1), "note": ""})
    summary[engine] = {"compared": len(diffs), "skipped_aspect_or_empty": skipped,
                       "median_mean_abs_diff": round(statistics.median(diffs), 1),
                       "median_pct_pixels_within_20": round(statistics.median(close) * 100, 1)}

with open(RESULTS / "fidelity_per_image.csv", "w", newline="", encoding="utf-8") as fh:
    wr = csv.DictWriter(fh, fieldnames=["engine", "id", "mean_abs_diff", "pixels_within_20", "note"])
    wr.writeheader()
    wr.writerows(rows)
(RESULTS / "fidelity_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
print(json.dumps(summary, indent=1))
