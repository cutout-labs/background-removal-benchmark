"""Local analysis of the AI-vs-segmentation outputs. Makes no API calls.

Classifies each output's background and records size, aspect ratio, and latency.
GPT results come from run_gpt_edits.py, which sends the photo as an edit.
"""

import csv
import json
import statistics
from pathlib import Path

import numpy as np
from PIL import Image

STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
manifest = {r["id"]: r for r in csv.DictReader(open(STUDY / "manifest.csv", encoding="utf-8"))}
first = json.loads((RESULTS / "benchmark_data.json").read_text(encoding="utf-8"))
edits = json.loads((RESULTS / "gpt_edit_data.json").read_text(encoding="utf-8"))

ENGINES = {
    "cutout_labs": ("Cutout Labs (standard segmentation engine)", "png"),
    "gemini_2_5": ("Gemini 2.5 Flash Image", "png"),
    "gemini_3_1": ("Gemini 3.1 Flash Image (Nano Banana 2)", "jpg"),
    "gpt_flare_edit": ("gpt-image-2.5-flare (Azure, edit)", "png"),
    "gpt_sunburst_edit": ("gpt-image-2.5-sunburst (Azure, edit)", "png"),
}


def record(engine, img_id):
    if engine.endswith("_edit"):
        return edits.get(img_id, {}).get(engine, {})
    return first[img_id]["engines"].get(engine, {})


def border_pixels(rgb: np.ndarray, band: int = 12) -> np.ndarray:
    return np.concatenate([rgb[:band].reshape(-1, 3), rgb[-band:].reshape(-1, 3),
                           rgb[:, :band].reshape(-1, 3), rgb[:, -band:].reshape(-1, 3)])


def is_painted_checker(gray: np.ndarray) -> bool:
    """A light two-tone grid along the image edges: the look of transparency, painted in."""
    for patch in (gray[:48, :48], gray[:48, -48:], gray[-48:, :48], gray[-48:, -48:]):
        if patch.min() < 140:
            continue
        hi, lo = patch > patch.mean() + 4, patch < patch.mean() - 4
        if hi.mean() > 0.25 and lo.mean() > 0.25 and (patch[hi].mean() - patch[lo].mean()) > 10:
            # Alternation: many sign changes along rows and columns.
            s = np.sign(patch - patch.mean())
            flips = (np.abs(np.diff(s, axis=0)) > 0).mean() + (np.abs(np.diff(s, axis=1)) > 0).mean()
            if flips > 0.04:
                return True
    return False


def classify(path: Path) -> str:
    im = Image.open(path)
    if im.mode in ("RGBA", "LA") or "transparency" in im.info:
        a = np.asarray(im.convert("RGBA"))[:, :, 3]
        return "real alpha" if (a < 10).mean() > 0.02 else "alpha channel, nothing removed"
    rgb = np.asarray(im.convert("RGB").resize((512, 512)), dtype=np.int16)
    gray = rgb.mean(2)
    if is_painted_checker(gray):
        return "painted checkerboard"
    b = border_pixels(rgb)
    if (b.min(1) > 240).mean() > 0.9:
        return "solid white"
    return "other opaque background"


rows, summary = [], []
for engine, (label, ext) in ENGINES.items():
    lat, kinds, res_kept, aspect_kept, ok = [], {}, 0, 0, 0
    for img_id, m in manifest.items():
        rec = record(engine, img_id)
        path = RESULTS / engine / f"{img_id}.{ext}"
        if rec.get("status") != "success" or not path.exists():
            rows.append({"engine": engine, "id": img_id, "status": rec.get("status", "missing"),
                         "error": str(rec.get("error", ""))[:120]})
            continue
        ok += 1
        with Image.open(path) as im:
            w, h = im.size
        iw, ih = int(m["input_w"]), int(m["input_h"])
        kind = classify(path)
        kinds[kind] = kinds.get(kind, 0) + 1
        res_kept += max(w, h) >= 0.95 * max(iw, ih)
        aspect_kept += abs(w / h - iw / ih) < 0.03
        lat.append(rec["latency_ms"])
        rows.append({"engine": engine, "id": img_id, "status": "success", "category": m["category"],
                     "background": kind, "width": w, "height": h, "input_w": iw, "input_h": ih,
                     "latency_ms": rec["latency_ms"]})
    lat.sort()
    summary.append({
        "engine": engine, "label": label, "succeeded": ok, "of": len(manifest),
        "background": kinds,
        "full_resolution": res_kept, "aspect_ratio_kept": aspect_kept,
        "latency_s": {"median": round(statistics.median(lat) / 1000, 1),
                      "p90": round(lat[int(0.9 * (len(lat) - 1))] / 1000, 1),
                      "min": round(lat[0] / 1000, 1), "max": round(lat[-1] / 1000, 1)} if lat else None,
    })

with open(RESULTS / "analysis_per_image.csv", "w", newline="", encoding="utf-8") as fh:
    cols = ["engine", "id", "status", "category", "background", "width", "height", "input_w", "input_h", "latency_ms", "error"]
    w = csv.DictWriter(fh, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
(RESULTS / "analysis_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
for s in summary:
    print(json.dumps(s))
