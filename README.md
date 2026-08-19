# Shelfie — Bookshelf → Library Inventory

Turns a photo of a bookshelf into a structured personal library: local spine
detection, a hosted vision-language model reads title/author off each spine,
fuzzy matching against a catalog decides what's confident enough to auto-add,
and a human-in-the-loop review screen handles everything else.

## Setup and run (clean clone)

These steps were run against a fresh `git clone` of this repo while writing
this section, not copied from memory — see the "verified" notes inline.

### Backend

```
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate      # Windows; `source .venv/bin/activate` on mac/Linux
pip install -r requirements.txt
```

Verified: `pip install -r requirements.txt` succeeds clean on a fresh venv
(Python 3.12, Windows). It pulls in `torch`/`torchvision` for Ultralytics, so
expect a few minutes and a few hundred MB on first install.

Copy `backend/.env.example` to `backend/.env` and fill in `ANTHROPIC_API_KEY`.
This is the only required secret — `DJANGO_SECRET_KEY` has a dev fallback if
unset. The key is only needed once a scan actually reaches the VLM step;
migrations, `load_catalog`, and the test suite all run fine without it.

Then:

```
python manage.py migrate
python manage.py load_catalog
```

`load_catalog` loads `catalog.csv` into the `CatalogBook` table — it's needed
so a confirmed match's foreign key has a real row to point at. It's
idempotent: rerun it any time (e.g. after editing `catalog.csv`) and it
reports `N created, M updated, K unchanged` rather than silently doing
nothing on a second run.

**First call to the local detector (`library/detector.py`) downloads the
YOLOv8n weights (~6MB)** from Ultralytics' release assets and caches them at
`backend/yolov8n.pt`. Verified twice in a clean clone: the download itself
was under a second over a normal connection, but earlier in this project's
development the same download took **over 100 seconds** over a slow/erratic
connection — it's genuinely network-dependent, not a fixed cost. After the
weights are cached, loading them into memory (once per process) measured
**~2-5 seconds** across several runs on this machine — that's the number
"warm start" refers to elsewhere in this README, and it's excluded from every
per-photo timing figure below.

Run the test suite from the **repo root**:

```
pytest
```

Verified this also works run directly from `backend/` — the config lives in
`pytest.ini` at the repo root (`pythonpath = backend` plus `testpaths`), and
both directions were re-tested in a clean clone for this README, not assumed
from earlier in development.

To exercise the API against real photos: `python manage.py runserver 0.0.0.0:8000`
— binding to `0.0.0.0`, not the default `127.0.0.1`, is what makes it
reachable from a phone on the same network (see LAN IP note below).

### Frontend

```
cd app
npm install
npx expo start --web    # or `npx expo start` for the native dev client
```

Verified `npm install` succeeds clean (491 packages; `npm audit` flags the
usual transitive-dependency vulnerabilities in the Expo toolchain, nothing
project-specific) and `npx tsc --noEmit` is clean in a fresh clone.

`app/config.ts` has one constant that matters for **native device testing**:

```ts
const LAN_IP = "172.20.10.3";
```

The web target always talks to `localhost:8000` directly, no change needed.
A physical device can't resolve `localhost` as this computer, so it needs
this machine's real LAN IP - re-check it before each device-testing session
(it's changed several times during development, including once from being
tethered to a phone hotspot):

```
# Windows (PowerShell)
(Get-NetIPAddress -InterfaceAlias "Wi-Fi" -AddressFamily IPv4).IPAddress
# mac/Linux
ipconfig getifaddr en0
```

Camera and photo-library permission strings are already configured in
`app/app.json` via the `expo-image-picker` plugin entry - no extra setup.

## Architecture

```
photo → [local] YOLOv8n spine detection → per-spine crops
      → [hosted] Claude Sonnet 5 reads title/author off each crop
      → [local]  fuzzy match against catalog.csv (rapidfuzz)
      → auto-add (confident) or → [human] review queue in the Expo app
```

**What runs where, and why:**

- **Detection is local** (`library/detector.py`): YOLOv8n, pretrained on
  COCO's "book" class, CPU inference, no fine-tuning. When it under-detects
  on tightly-packed spines (its known weak spot), a hand-rolled edge-density
  fallback (OpenCV Sobel-X column-energy peaks) slices the image into
  vertical strips instead. Finding rectangular regions in an image doesn't
  need a hosted model - a small local one is fast, free, and good enough
  with a fallback behind it.
- **Reading text off a spine is hosted** (`library/vlm_reader.py`): Claude
  Sonnet 5, via the Anthropic API. This is the one step where quality
  genuinely requires a frontier vision-language model - reading small,
  often blurry or angled spine text and correctly returning `null` instead
  of guessing is exactly the kind of judgment a small local model doesn't
  reliably have. Runs in one of two modes selected by a constant
  (`VLM_MODE` in `vlm_reader.py`): **batched** (all of a photo's crops
  split into chunks of `BATCH_CHUNK_SIZE` = 10 per API call) or **per-spine**
  (one call per crop) - see Measured numbers below for the real cost/latency
  difference.
- **Matching is local** (`library/matcher.py`): rapidfuzz string scoring
  against the in-memory `catalog.csv`. Simple, cheap, no reason to pay
  hosted compute for scoring a few hundred short strings.
- **Review is local**, in the Expo app talking to the Django backend over
  plain REST (`POST /api/scan`, `GET/POST /api/library`,
  `DELETE /api/library/<id>`).

## Measured numbers

Real numbers from `backend/scripts/benchmark_scan.py` run against the 7 real
bookshelf photos in `backend/tests/fixtures/photos/`, batched mode, after the
resize/chunking fixes described below. Not estimates.

| photo | spines | detect ms | vlm ms | match ms | total ms | review | unmatched | failed | tokens in | tokens out | cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| shelf_1 | 7 | 963 | 5,008 | 6 | 5,977 | 2 | 5 | 0 | 4,029 | 165 | $0.0097 |
| shelf_2 | 38 | 698 | 36,621 | 92 | 37,411 | 6 | 32 | 0 | 22,339 | 2,759 | $0.0723 |
| shelf_3 | 46 | 258 | 42,139 | 77 | 42,474 | 3 | 42 | 1 | 25,624 | 2,946 | $0.0807 |
| shelf_4 | 41 | 284 | 32,833 | 68 | 33,185 | 4 | 37 | 0 | 27,469 | 2,041 | $0.0753 |
| shelf_5 | 21 | 259 | 28,107 | 70 | 28,437 | 3 | 18 | 0 | 14,794 | 2,256 | $0.0521 |
| shelf_6 | 13 | 250 | 69,699 | 37 | 69,986 | 1 | 12 | 0 | 11,315 | 3,401 | $0.0566 |
| shelf_7 | 37 | 273 | 26,719 | 92 | 27,084 | 5 | 32 | 0 | 24,969 | 1,783 | $0.0678 |
| **total** | **203** | | | | | | | **1** | 130,539 | 15,351 | **$0.4145** |

**203 spines detected across 7 photos, $0.4145 total, ~$0.002/spine
($0.4145 / 203 = $0.00204)** in batched mode, using Claude Sonnet 5's
standard pricing ($2/MTok input, $10/MTok output, confirmed against
Anthropic's published pricing at the time of this run).

`detect_ms` above is warm - the one-time model load (~2-5s, see Setup) is
excluded, not averaged into any photo's number, exactly because a "detect
took 2 seconds" and a "detect took 100 seconds because it also loaded the
model" claim would otherwise get silently blended into one misleading
average.

**Per-spine mode comparison** - measured on `shelf_1` only (7 spines), then
**extrapolated** to all 203; this is explicitly an extrapolation, not a
measurement across all 7 photos, because per-spine mode at real scale is
~150-200+ individual API calls with real rate-limit risk, which wasn't worth
running just to confirm arithmetic:

| mode | spines | vlm ms | tokens in | tokens out | cost | cost/spine |
|---|---|---|---|---|---|---|
| batched | 7 | 4,442 | 4,029 | 150 | $0.0096 | $0.00137 |
| per-spine | 7 | 17,656 | 5,862 | 105 | $0.0128 | $0.00183 |

Per-spine cost **1.33x** batched (measured), per-spine latency **~4x**
batched (measured, 17,656ms vs 4,442ms). Extrapolated to 203 spines at
shelf_1's per-spine rate: **~$0.37 total cost, ~8.5 minutes of sequential
VLM wait time** - the real story is latency, not cost; the two modes land
within striking distance on dollars, but per-spine's sequential round trips
are what actually cost you at scale.

**Chunking traded latency for reliability.** Before `BATCH_CHUNK_SIZE` was
introduced, `shelf_6` (13 crops, one unchunked call) completed in ~25s of VLM
time. After chunking into groups of 10, the same photo (now 2 sequential
calls) took ~70s. That's the real cost of the reliability fix described
below - `BATCH_CHUNK_SIZE` in `vlm_reader.py` is the one knob to turn if a
demo needs to trade some of that reliability margin back for speed.

## The catalog

`catalog.csv` (169 entries, repo root) was generated by a script, not typed
by hand, specifically to contain six deliberate ambiguity types a real
catalog would have - each one is a genuine test of a different piece of
`matcher.py`'s logic:

1. **Same title, different author** - two books both titled *Origin* (Dan
   Brown vs. Jessica Khoury). Tests that the author score, not just title,
   decides between them.
2. **Same author, similar/truncatable titles** - *Dune* and *Dune Messiah*,
   both Frank Herbert. This is the pair the length-ratio penalty exists for
   (see Key decisions below).
3. **Title variants via `alt_titles`** - *Harry Potter and the Sorcerer's
   Stone* / *...Philosopher's Stone*, same book, US/UK title difference.
4. **Author name formatting** - *A Game of Thrones* credits "George R.R.
   Martin"; *A Clash of Kings* (same series, same real person) credits
   "Martin, George R. R." - tests `normalize_author`'s comma-reordering and
   initial-collapsing.
5. **Accent/diacritic normalization** - "Gabriel García Márquez" vs. "Gabriel
   Garcia Marquez" across two different books, tests `normalize_title`'s
   NFKD accent-stripping.
6. **Same title and author, different edition** - two rows for *1984* (mass
   market paperback, 1961; centennial hardcover, 2003) and two for *Harry
   Potter and the Sorcerer's Stone*. Tests that a confident match with a
   close-second-place candidate (two real editions) reads as ambiguity, not
   confidence - see `AMBIGUITY_MARGIN` in `matcher.py`.

## Key decisions and tradeoffs

**The length-ratio penalty is deliberately aggressive, and that's measured,
not assumed.** `_length_ratio_penalty()` in `matcher.py` exists because raw
fuzzy-match scoring can rank a short title as a near-perfect match against a
much longer one that simply contains it - "Dune" scores high against "Dune
Messiah" on substring containment alone. Tested against 8 realistic
truncated-but-legitimate read cases, the penalty still ranks the wrong,
shorter book above the correct, longer one in **2 of 8**. Softening the curve
(sqrt, a floor) was tried and doesn't fix it - the ambiguity is genuinely in
the text itself ("Dune" read off a spine is indistinguishable from a
truncated read of "Dune Messiah"; the information to tell them apart isn't
there), not in how the penalty is shaped. The mitigation is the
review/unmatched path, not a better formula - a wrong top-ranked candidate
has been verified to never reach `AUTO` status, so the actual failure mode is
"needs a human to confirm," never a silent wrong add.

**The author gate is unconditional.** `match()` will not return `AUTO`
without a real author read, full stop, regardless of how confident the title
score is. This exists because of a bug the matcher audit found: reading
"Dune" with no author auto-added on title alone (score 1.0, a comfortable
margin over "Dune Messiah") before this gate existed - the catalog's other
ambiguous pairs had only been safe by coincidence, tied at exactly zero
margin. A non-tied case slipped straight through. Fixed as an unconditional
rule rather than a conditional exception, because "no author, but the title
felt unique enough" is exactly the kind of judgment call that shouldn't be
made silently.

**`catalog.py` has no Django dependency at all** - no `django.conf.settings`,
importable and runnable from a bare Python REPL or a standalone script. This
mattered in practice: `matcher.py` (which depends on it) is fully unit-tested
without any Django bootstrap, and a future threshold-tuning script against
labelled data would have no reason to need Django installed.

**No retry endpoint for failed VLM reads.** The review flow lets a failed
spine be discarded, not retried. This was a deliberate scope cut: the real
measured failure rate across all 7 benchmark photos was **1 failed spine out
of 203 (0.5%)**, and building a new backend endpoint to handle a half-percent
failure rate, this close to a deadline with the review screen still unbuilt
at the time, wasn't a good trade. If the real-world failure rate turns out
higher than this benchmark suggests, that's the first thing to revisit.

## Failure handling

Three **real, unplanned** API faults were hit while benchmarking against the
7 real photos - not synthetic tests, not injected failures. Full details
with the actual API error bodies are in
[docs/vlm-evidence/api_failure_incidents.md](docs/vlm-evidence/api_failure_incidents.md):

1. **Account credit exhaustion** - every one of 203 spines across all 7
   photos came back individually marked `status="failed"` with the real
   error code (`vlm_api_error_400`) attached, not a crash and not a 500.
2. **Anthropic's many-image request size limit** - a request with many
   images and any single image over 2000px on its longest edge gets
   rejected. Hit on 2 of 7 photos before being fixed with a resize guard
   (`MAX_CROP_DIMENSION` = 1800px in `vlm_reader.py`).
3. **Timeouts on large batches** - sending 38-46 crops in one request
   reliably exceeded the 30s timeout even with every crop under the size
   limit. Hit on 2 of 7 photos before being fixed by chunking
   (`BATCH_CHUNK_SIZE` = 10).

All three were caught per-spine, with the real error surfaced, not a crash
and not a silent drop - and (1) is the same failure-isolation design proving
itself under a genuine account-level fault, not just the mocked failure paths
in the test suite.

## Honest limitations

- **The edge-density fallback detector breaks on multi-row shelves.** It
  slices the image into vertical strips using one set of x-boundaries for
  the whole photo - fine for a single row, wrong for two independently-
  positioned rows stacked vertically, since the same boundaries get applied
  to both. Evidence committed at
  [docs/detection-evidence/shelf_6_fallback.jpg](docs/detection-evidence/shelf_6_fallback.jpg) -
  a real two-row library shelf where the strips visibly misalign on the
  second row. The fallback now emits an explicit warning when it runs,
  rather than silently producing bad slices.
- **A cheap fix for multi-row shelves was tried and abandoned** because the
  underlying signal isn't reliable, not because it ran out of time. Tried
  segmenting rows first via horizontal (Sobel-Y) edge-energy peaks, the same
  approach that works for vertical spine boundaries, rotated 90°. It doesn't
  transfer: a confirmed **single-row** shelf photo produced **more** row-
  energy peaks (8) than a confirmed **two-row** shelf (6) - the signal is
  dominated by spine text, shadows, and lighting, not actual shelf dividers.
  Time-boxed at ~30 minutes and abandoned per that plan rather than pushed
  through with an unvalidated threshold.
- **The review queue is session-only, not persisted to device storage.** If
  the Expo app is killed mid-review, undecided spines are lost. This is a
  deliberate scope decision, not an oversight - it matches the backend's
  existing design (`LibraryEntry`'s own docstring: "scans are stateless"),
  and nothing is *mis*-recorded when it happens: auto-added entries are
  already durably saved server-side the moment a scan completes, only
  un-reviewed items disappear.
- **88% of real spines come back unmatched** (178 of 203 across the 7
  benchmark photos). This is expected, not a matcher defect: `catalog.csv`
  is a deliberately small, 169-entry curated fixture built to exercise
  specific ambiguity types, not a real book database - most real-world
  titles scanned off an actual shelf simply aren't in it. The review flow
  was built around this being the common case (manual entry defaults open
  on an unmatched card, not tucked behind disabled buttons) precisely
  because of this number.

## What's unfinished / what I'd do with another day

- **Matcher thresholds are hand-set, not calibrated.** `HIGH_CONFIDENCE_THRESHOLD`,
  `AMBIGUITY_MARGIN`, `REVIEW_FLOOR`, and the title/author weights were
  reasoned about against this specific catalog, not tuned against labelled
  data (real photos, real VLM reads, ground-truth catalog IDs) - there
  wasn't time to build that dataset this session.
- **Review queue persistence** (AsyncStorage) so an in-progress review
  survives an app restart, not just a network hiccup mid-decision.
- **A real interactive pass on the review flow in an actual browser.** No
  browser automation tool was available in this environment - the frontend
  was verified via `tsc --noEmit`, a clean web bundle export, and live HTTP
  contract tests against a running Django server (not just Django's test
  client), but never actually clicked through. This is the single highest-
  value thing to do before a live demo.
- **Multi-row shelf handling**, properly this time - likely needs a
  different signal entirely (e.g. clustering YOLO box y-centers when there
  are enough of them, rather than a generic edge-energy projection).
- **The original uploaded photo is never saved server-side** - only the
  per-spine crops (`MEDIA_ROOT/crops/`) are. No reprocessing or audit trail
  back to the source image.
- **No cleanup story for saved crops** - they accumulate in `MEDIA_ROOT`
  indefinitely across scans.
- **No frontend test suite.** `app/` has no Jest setup - adding one wasn't
  worth the new infrastructure for this scope, per an explicit decision this
  session, but it's a real gap for anything beyond a live demo.
