"""Run the GPT image models as edits: the photo is sent with the prompt.

An earlier run called /images/generations with the prompt only, so the models never
saw the photo; it was discarded. Results go to results/gpt_*_edit. Needs .env with
AZURE_ENDPOINT and AZURE_KEY.
"""

import base64
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image

STUDY = Path(__file__).resolve().parent
INPUTS = STUDY / "images" / "inputs"
RESULTS = STUDY / "results"
OUT_JSON = RESULTS / "gpt_edit_data.json"

env = dict(
    line.split("=", 1)
    for line in (STUDY / ".env").read_text(encoding="utf-8").splitlines()
    if "=" in line and not line.startswith("#")
)
KEY = env["AZURE_KEY"].strip()
BASE = env["AZURE_ENDPOINT"].strip().split("/openai/")[0]
URL = f"{BASE}/openai/v1/images/edits"

MODELS = {"gpt_flare_edit": "gpt-image-2.5-flare", "gpt_sunburst_edit": "gpt-image-2.5-sunburst"}
# Same prompt as the Gemini runs. background=transparent is the documented way to ask
# these models for an alpha channel, so a fair test includes it.
PARAMS = {"background": "transparent", "output_format": "png", "size": "auto", "n": "1"}


def run(engine: str, row: dict) -> dict:
    out = RESULTS / engine / f"{row['id']}.png"
    prompt = f"Isolate {row['intended_subject']} on a clean transparent background."
    data = {"model": MODELS[engine], "prompt": prompt, **PARAMS}
    for attempt in range(3):
        t0 = time.perf_counter()
        try:
            with open(INPUTS / f"{row['id']}.jpg", "rb") as fh:
                resp = requests.post(
                    URL,
                    headers={"api-key": KEY},
                    data=data,
                    files={"image": (f"{row['id']}.jpg", fh, "image/jpeg")},
                    timeout=300,
                )
        except requests.RequestException as exc:
            if attempt == 2:
                return {"status": "exception", "error": str(exc)[:300]}
            time.sleep(5)
            continue
        ms = round((time.perf_counter() - t0) * 1000, 1)
        if resp.status_code in (429, 500, 503) and attempt < 2:
            time.sleep(10 * (attempt + 1))
            continue
        if resp.status_code != 200:
            return {"status": "error", "status_code": resp.status_code, "error": resp.text[:300], "latency_ms": ms}
        body = resp.json()
        item = (body.get("data") or [{}])[0]
        if not item.get("b64_json"):
            return {"status": "no_image", "latency_ms": ms, "response": json.dumps(body)[:300]}
        out.write_bytes(base64.b64decode(item["b64_json"]))
        with Image.open(out) as im:
            info = {"width": im.width, "height": im.height, "mode": im.mode,
                    "has_alpha": im.mode in ("RGBA", "LA") or "transparency" in im.info}
        return {
            "status": "success", "latency_ms": ms, "bytes": out.stat().st_size, **info,
            "usage": body.get("usage"),
            "response_fields": {k: body.get(k) for k in ("background", "output_format", "quality", "size")},
            "params": PARAMS, "prompt": prompt,
        }
    return {"status": "failed"}


def main() -> None:
    rows = list(csv.DictReader(open(STUDY / "manifest.csv", encoding="utf-8")))
    only = sys.argv[1:]  # optional: ids and/or engine names for a pilot
    ids = [a for a in only if a in {r["id"] for r in rows}]
    engines = [a for a in only if a in MODELS] or list(MODELS)
    if ids:
        rows = [r for r in rows if r["id"] in ids]
    for e in engines:
        (RESULTS / e).mkdir(parents=True, exist_ok=True)
    records = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.exists() else {}

    jobs = [(e, r) for r in rows for e in engines
            if records.get(r["id"], {}).get(e, {}).get("status") != "success"]
    print(f"{len(jobs)} calls to make")
    with ThreadPoolExecutor(max_workers=4) as pool:
        for (e, r), res in zip(jobs, pool.map(lambda j: run(*j), jobs)):
            records.setdefault(r["id"], {})[e] = res
            OUT_JSON.write_text(json.dumps(records, indent=1), encoding="utf-8")
            print(r["id"], e, res.get("status"), res.get("latency_ms"), res.get("mode"),
                  (res.get("width"), res.get("height")), res.get("error", "")[:120])


if __name__ == "__main__":
    main()
