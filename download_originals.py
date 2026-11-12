"""Download the original Unsplash photos listed in manifest.csv into images/originals/.

The photos are under the Unsplash License. Checksums are compared with manifest.csv;
a mismatch usually means Unsplash re-encoded the file, not that it's a different photo.
"""

import csv
import hashlib
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "images" / "originals"
OUT.mkdir(parents=True, exist_ok=True)

photos = {r["id"]: r["photo"] for r in csv.DictReader(open(ROOT / "candidates.csv", encoding="utf-8"))}
mismatched = 0
for row in csv.DictReader(open(ROOT / "manifest.csv", encoding="utf-8")):
    path = OUT / f"{row['id']}.jpg"
    if not path.exists():
        url = f"https://images.unsplash.com/{photos[row['unsplash_id']]}?w={row['orig_w']}&fm=jpg&q=95"
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    ok = hashlib.sha256(path.read_bytes()).hexdigest() == row["original_sha256"]
    mismatched += not ok
    print(row["id"], "ok" if ok else "checksum differs", row["url"])
print(f"{mismatched} checksum differences")
