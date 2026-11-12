# AI image editors vs. a background remover: image selection

This file fixes how the test images are chosen. It was written before any candidate photo was looked at, and the rules don't change after selection starts. Every candidate considered is logged in `candidates.csv` with the decision and, for rejections, the reason.

## Set size and categories

50 distinct photographs, each with one primary category. The categories and counts come from Cutout Labs' earlier draft protocol, "How to test background removal on 50 difficult product photos".

| Code | Category | Count | What it tests |
| :--- | :--- | ---: | :--- |
| A | Ordinary solid products | 10 | Baseline subject detection and clean outer contours |
| B | White or pale products on pale backgrounds | 8 | Low-contrast edges, texture, and contact shadows |
| C | Handles, holes, laces, and mesh | 8 | Interior gaps and narrow structures |
| D | Reflective metal, glass, and translucent packaging | 8 | Reflections, refraction, and semitransparency |
| E | Fur, hair, fabric fringe, feathers, or plants | 8 | Fine boundaries and background-colored spill |
| F | Busy scenes, overlaps, and mixed lighting | 8 | Subject selection and foreground ambiguity |

Secondary tags are recorded but don't change category counts: `text` (readable text or a logo on the subject, where image generators may redraw details), `person`, `hand`, `animal`, `food`.

## Source

Unsplash search on unsplash.com with the "Free" license filter, in the order Unsplash returns results. Queries per category, in the order they are used:

| Category | Queries |
| :--- | :--- |
| A | sneaker product photography; headphones product photography; wristwatch product photography; backpack product photography; skincare bottle product photography; coffee bag packaging |
| B | white sneakers on white background; white ceramic vase; white candle product; white t-shirt flat lay; white cosmetic jar; white headphones white background |
| C | coffee mug product photography; bicycle studio; wire chair; scissors; woven basket; teapot |
| D | perfume bottle; wine glass; glass jar; sunglasses product photography; stainless steel water bottle; clear plastic bottle |
| E | dog portrait; cat portrait; curly hair portrait; potted plant; flower bouquet; feather |
| F | hand holding product; person holding drink; food on table; products on store shelf; person holding phone; person carrying shopping bags |

For each category, go through its queries in order. From each query, take eligible results in rank order, at most 2 per query, until the category is full. If all queries are used and the category is still short, repeat the pass allowing up to 4 per query. Only the first 30 results of a query are considered.

## Eligibility

A candidate is rejected if any of these apply. Checks 1–4 are automatic; 5–9 are a visual check of the original photo only, never of any tool's output.

1. Not under the Unsplash License, or marked Unsplash+ / premium.
2. Original long side under 2048 pixels.
3. Title, description, or tags mention a 3D render, illustration, mockup, or AI generation.
4. Already used in an earlier Cutout Labs test, sample, or blog post (listed in `excluded-known.txt`), or a second photo from the same photographer in the same category.
5. Not a real photograph: render, illustration, collage, screenshot, or heavy compositing.
6. The photo doesn't fit the category definition (for B, both the subject and the background must be predominantly white or pale).
7. No clear intended subject a person could name in a few words ("the mug", "the dog"). Category F is exempt, because ambiguity is what it tests; the intended subject is still recorded.
8. Text overlays, watermarks, borders, or frames added to the image.
9. Nudity, a child as the main subject, graphic content, or an identifiable trademark used as the whole subject in a way that suggests endorsement (product photos with ordinary branding are allowed).

## Recording

For every selected photo, `manifest.csv` records: id, category, secondary tags, intended subject (written before any tool runs), Unsplash URL, photographer, license, original dimensions, the input file's dimensions, and its SHA-256 checksum.

The input file sent to every tool is the Unsplash original scaled to a 2048-pixel long side, JPEG quality 92. The inputs are in `images/inputs/`. Originals aren't stored here; `download_originals.py` downloads them from Unsplash and checks them against the manifest.

## After selection

The list is frozen once `manifest.csv` is complete. No photo is replaced after a tool has processed it, whatever the result. The 28 photos already used in earlier tests can be run as a separate, clearly labeled supplementary set, reported apart from the main results.
