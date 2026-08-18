# Shelfie — Bookshelf → Library Inventory

Turns a photo of a bookshelf into a structured personal library: local spine
detection, hosted VLM reads for title/author, fuzzy matching against a
catalog, human-in-the-loop review for anything uncertain.

Status: **work in progress** — this README is being filled in as the project
is built. See commit history for progress.

## Setup and run (clean clone)

### Backend

```
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate      # Windows; `source .venv/bin/activate` on mac/Linux
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` — not required
for the test suite below, only once the VLM step is wired in.

**First run of anything that calls the local detector (`library/detector.py`)
downloads the YOLOv8n weights (~6MB) from Ultralytics' release assets** — you
need internet access for that one-time download, and it adds a few seconds to
whichever run triggers it. Look for a log line saying so
(`Loading YOLOv8n weights - first run on this machine downloads ~6MB...`).
Subsequent runs load the cached weights file and skip it.

Run the matcher test suite from the **repo root**:

```
pytest
```

`pytest` also works run directly from `backend/` — the config lives in
`pytest.ini` at the repo root and resolves correctly either way (verified
both explicitly; see commit history).

### Frontend

TODO — Expo app setup steps.

## Architecture

TODO

## Measured latency and cost

TODO — numbers, not adjectives, per the task spec.

## The catalog

TODO — what's in `catalog.csv`, and what ambiguity was deliberately included.

## Key decisions and tradeoffs

TODO

## What's unfinished / what I'd do with another day

TODO
