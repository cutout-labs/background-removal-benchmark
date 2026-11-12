"""Cost per engine from published list prices (checked 12 Nov 2026). Local only, no API calls.

GPT edit runs: exact token counts recorded from each response's `usage`.
Gemini runs: usage wasn't recorded, so tokens are computed from Google's documented
token rules (image tiling, output tokens per image size).
Cutout Labs: free for now; paid plans will come later.
"""

import csv
import json
import math
from pathlib import Path

from PIL import Image

STUDY = Path(__file__).resolve().parent
RESULTS = STUDY / "results"
rows = list(csv.DictReader(open(STUDY / "manifest.csv", encoding="utf-8")))
edits = json.loads((RESULTS / "gpt_edit_data.json").read_text(encoding="utf-8"))
PROMPT_TOKENS = 15  # "Isolate <subject> on a clean transparent background." is ~10-20 text tokens

# Azure OpenAI Global, per 1M tokens (Azure Retail Prices API, effective 1 Sep 2026)
AZ = {"txt_in": 5.00, "img_in": 8.00, "out": 30.00}
# Gemini 2.5 Flash Image: input $0.30/1M; output $30/1M, 1290 tokens per image up to 1024x1024
# Gemini 3.1 Flash Image: input $0.50/1M; output $60/1M images, 1120 tokens per 1K image
G25 = {"in": 0.30, "out": 30.00, "out_tokens": 1290}
G31 = {"in": 0.50, "out": 60.00, "out_tokens_1k": 1120, "out_tokens_2k": 1680}


def g25_input_tokens(w, h):
    if w <= 384 and h <= 384:
        return 258
    return math.ceil(w / 768) * math.ceil(h / 768) * 258


def usd(x):
    return round(x, 4)


out = {}

# Cutout Labs
out["cutout_labs"] = {"per_image": 0.0, "total_50": 0.0,
                      "note": "free for now; paid plans will come later"}

# Gemini 2.5 Flash Image
g25 = 0.0
for r in rows:
    tin = g25_input_tokens(int(r["input_w"]), int(r["input_h"])) + PROMPT_TOKENS
    g25 += tin * G25["in"] / 1e6 + G25["out_tokens"] * G25["out"] / 1e6
out["gemini_2_5"] = {"per_image": usd(g25 / 50), "total_50": usd(g25),
                     "note": "input tiles of 768px at 258 tokens; output 1290 tokens at $30/1M"}

# Gemini 3.1 Flash Image (Nano Banana 2): default media resolution = 1120 input tokens per image
g31 = 0.0
for r in rows:
    w, h = Image.open(RESULTS / "gemini_3_1" / f"{r['id']}.jpg").size
    out_tokens = G31["out_tokens_1k"] if max(w, h) <= 1536 else G31["out_tokens_2k"]
    g31 += (1120 + PROMPT_TOKENS) * G31["in"] / 1e6 + out_tokens * G31["out"] / 1e6
out["gemini_3_1"] = {"per_image": usd(g31 / 50), "total_50": usd(g31),
                     "note": "1120 input tokens per image; 1K output = 1120 tokens at $60/1M; excludes any thinking tokens"}

# GPT edits: exact usage
for e in ("gpt_flare_edit", "gpt_sunburst_edit"):
    tot = 0.0
    for rec in edits.values():
        u = rec[e]["usage"]
        tot += (u["input_tokens_details"]["text_tokens"] * AZ["txt_in"]
                + u["input_tokens_details"]["image_tokens"] * AZ["img_in"]
                + u["output_tokens"] * AZ["out"]) / 1e6
    out[e] = {"per_image": usd(tot / 50), "total_50": usd(tot), "note": "exact token usage from responses"}

(RESULTS / "costs.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))
