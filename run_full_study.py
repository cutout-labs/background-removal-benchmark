"""Run the Cutout Labs API and both Gemini image models on the 50 photos.

The GPT models are run separately by run_gpt_edits.py, which sends the photo to the
images edit endpoint. Needs .env with GEMINI_API_KEY and CUTOUT_API_KEY (free at
https://www.cutoutlabs.com/background-removal-api). CUTOUT_API_URL is optional.
"""

import os
import csv
import time
import json
import base64
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import requests

STUDY_DIR = Path(__file__).resolve().parent
INPUTS_DIR = STUDY_DIR / "images" / "inputs"
MANIFEST_PATH = STUDY_DIR / "manifest.csv"
RESULTS_DIR = STUDY_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

ENGINES = {
    "cutout_labs": RESULTS_DIR / "cutout_labs",
    "gemini_2_5": RESULTS_DIR / "gemini_2_5",
    "gemini_3_1": RESULTS_DIR / "gemini_3_1",
}
for d in ENGINES.values():
    d.mkdir(parents=True, exist_ok=True)

# Load environment
env_vars = {}
for line in (STUDY_DIR / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env_vars[k.strip()] = v.strip()

GEMINI_KEY = env_vars["GEMINI_API_KEY"]
CUTOUT_API_KEY = env_vars["CUTOUT_API_KEY"]
CUTOUT_API_URL = env_vars.get("CUTOUT_API_URL", "https://api.cutoutlabs.com/v1.0/removebg")

BENCHMARK_JSON = RESULTS_DIR / "benchmark_data.json"
BENCHMARK_CSV = RESULTS_DIR / "benchmark_data.csv"

benchmark_records = {}
if BENCHMARK_JSON.exists():
    try:
        benchmark_records = json.loads(BENCHMARK_JSON.read_text(encoding="utf-8"))
    except Exception:
        benchmark_records = {}


def inspect_image(path: Path):
    try:
        with Image.open(path) as im:
            has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
            return {
                "width": im.width,
                "height": im.height,
                "mode": im.mode,
                "has_alpha": has_alpha,
                "bytes": path.stat().st_size,
            }
    except Exception as e:
        return {"error": str(e), "bytes": path.stat().st_size if path.exists() else 0}


def run_cutout_labs(img_bytes: bytes, out_path: Path):
    t0 = time.perf_counter()
    try:
        resp = requests.post(
            CUTOUT_API_URL,
            headers={"X-Api-Key": CUTOUT_API_KEY},
            files={"image_file": ("photo.jpg", img_bytes, "image/jpeg")},
            data={"size": "auto"},
            timeout=60,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        if resp.status_code == 200:
            out_path.write_bytes(resp.content)
            info = inspect_image(out_path)
            return {
                "status": "success",
                "latency_ms": elapsed_ms,
                "engine_time_ms": float(resp.headers.get("X-Process-Time-Ms", elapsed_ms)),
                **info,
            }
        return {
            "status": "error",
            "status_code": resp.status_code,
            "error": resp.text[:200],
            "latency_ms": elapsed_ms,
        }
    except Exception as e:
        return {"status": "exception", "error": str(e), "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


def run_gemini(model_name: str, img_b64: str, prompt: str, out_path: Path, max_retries=3):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
            ]
        }]
    }
    
    for attempt in range(max_retries):
        t0 = time.perf_counter()
        try:
            resp = requests.post(url, json=payload, timeout=90)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "inlineData" in part:
                            raw = base64.b64decode(part["inlineData"]["data"])
                            out_path.write_bytes(raw)
                            info = inspect_image(out_path)
                            return {
                                "status": "success",
                                "latency_ms": elapsed_ms,
                                "mime_type": part["inlineData"].get("mimeType"),
                                **info,
                            }
                return {
                    "status": "no_image_returned",
                    "latency_ms": elapsed_ms,
                    "response": resp.text[:200],
                }
            elif resp.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            else:
                return {
                    "status": "error",
                    "status_code": resp.status_code,
                    "error": resp.text[:200],
                    "latency_ms": elapsed_ms,
                }
        except Exception as e:
            if attempt == max_retries - 1:
                return {"status": "exception", "error": str(e), "latency_ms": 0}
            time.sleep(2)
    return {"status": "rate_limited", "latency_ms": 0}


def process_image(row):
    img_id = row["id"]
    category = row["category"]
    subject = row["intended_subject"]
    input_file = INPUTS_DIR / f"{img_id}.jpg"
    prompt = f"Isolate {subject} on a clean transparent background."
    
    if img_id not in benchmark_records:
        benchmark_records[img_id] = {
            "id": img_id,
            "category": category,
            "tags": row["tags"],
            "intended_subject": subject,
            "prompt": prompt,
            "input_w": int(row["input_w"]),
            "input_h": int(row["input_h"]),
            "engines": {},
        }
    
    rec = benchmark_records[img_id]["engines"]
    img_bytes = input_file.read_bytes()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    
    tasks = {}
    if "cutout_labs" not in rec or rec["cutout_labs"].get("status") != "success":
        tasks["cutout_labs"] = lambda: run_cutout_labs(img_bytes, ENGINES["cutout_labs"] / f"{img_id}.png")
    if "gemini_2_5" not in rec or rec["gemini_2_5"].get("status") != "success":
        tasks["gemini_2_5"] = lambda: run_gemini("gemini-2.5-flash-image", img_b64, prompt, ENGINES["gemini_2_5"] / f"{img_id}.png")
    if "gemini_3_1" not in rec or rec["gemini_3_1"].get("status") != "success":
        tasks["gemini_3_1"] = lambda: run_gemini("gemini-3.1-flash-image", img_b64, prompt, ENGINES["gemini_3_1"] / f"{img_id}.jpg")

    if tasks:
        # Run the engines in parallel for this image
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_engine = {executor.submit(fn): name for name, fn in tasks.items()}
            for future in as_completed(future_to_engine):
                eng_name = future_to_engine[future]
                try:
                    result = future.result()
                    rec[eng_name] = result
                except Exception as exc:
                    rec[eng_name] = {"status": "error", "error": str(exc)}
    
    # Save snapshot after every image
    BENCHMARK_JSON.write_text(json.dumps(benchmark_records, indent=2), encoding="utf-8")
    return img_id


def write_csv():
    fieldnames = [
        "id", "category", "tags", "intended_subject",
        "cf_latency_ms", "cf_has_alpha", "cf_w", "cf_h", "cf_bytes",
        "g25_latency_ms", "g25_has_alpha", "g25_w", "g25_h", "g25_bytes",
        "g31_latency_ms", "g31_has_alpha", "g31_w", "g31_h", "g31_bytes",
    ]
    with open(BENCHMARK_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for img_id, d in benchmark_records.items():
            e = d["engines"]
            row_dict = {
                "id": img_id,
                "category": d["category"],
                "tags": d.get("tags", ""),
                "intended_subject": d["intended_subject"],
                
                "cf_latency_ms": e.get("cutout_labs", {}).get("latency_ms", ""),
                "cf_has_alpha": e.get("cutout_labs", {}).get("has_alpha", ""),
                "cf_w": e.get("cutout_labs", {}).get("width", ""),
                "cf_h": e.get("cutout_labs", {}).get("height", ""),
                "cf_bytes": e.get("cutout_labs", {}).get("bytes", ""),
                
                "g25_latency_ms": e.get("gemini_2_5", {}).get("latency_ms", ""),
                "g25_has_alpha": e.get("gemini_2_5", {}).get("has_alpha", ""),
                "g25_w": e.get("gemini_2_5", {}).get("width", ""),
                "g25_h": e.get("gemini_2_5", {}).get("height", ""),
                "g25_bytes": e.get("gemini_2_5", {}).get("bytes", ""),
                
                "g31_latency_ms": e.get("gemini_3_1", {}).get("latency_ms", ""),
                "g31_has_alpha": e.get("gemini_3_1", {}).get("has_alpha", ""),
                "g31_w": e.get("gemini_3_1", {}).get("width", ""),
                "g31_h": e.get("gemini_3_1", {}).get("height", ""),
                "g31_bytes": e.get("gemini_3_1", {}).get("bytes", ""),

            }
            writer.writerow(row_dict)


def main():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Total test photos in manifest: {len(rows)}")
    completed_count = sum(
        1 for r in rows
        if r["id"] in benchmark_records
        and all(benchmark_records[r["id"]]["engines"].get(e, {}).get("status") == "success"
                for e in list(ENGINES))
    )
    print(f"Already completed: {completed_count}/50")

    for i, row in enumerate(rows, 1):
        img_id = row["id"]
        # check if fully done
        if img_id in benchmark_records:
            all_done = all(
                benchmark_records[img_id]["engines"].get(e, {}).get("status") == "success"
                for e in list(ENGINES)
            )
            if all_done:
                continue

        t_start = time.perf_counter()
        print(f"[{i:02d}/50] Running {img_id} (Category {row['category']}: '{row['intended_subject']}') [parallel]...")
        process_image(row)
        t_dur = round(time.perf_counter() - t_start, 1)
        print(f"[{i:02d}/50] Finished {img_id} in {t_dur}s")

    write_csv()
    print("\nBenchmark successfully finished across all 50 photos! Flat CSV updated.")


if __name__ == "__main__":
    main()
