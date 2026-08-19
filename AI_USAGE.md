# AI usage

Claude Code (Anthropic) wrote most of the implementation in this repo -
backend (Django/DRF, detector, matcher, VLM reader, management command) and
frontend (Expo/React Native) alike - under my direction, in a single ongoing
session. This is an honest account of how, not a claim that it was
hands-off.

## How I worked with it

Every non-trivial piece of work followed the same loop: I specified the
behavior and constraints (including explicit failure-handling requirements -
"never crash, never silently drop, never guess"), Claude proposed a plan and
waited for a go-ahead before writing code, then implemented in small commits
with a rationale in each message. I did not accept generated code as
finished by default - the matcher in particular got a dedicated audit pass
rather than being trusted because it existed.

**I directed an audit of `matcher.py` rather than accepting it as done, and
it surfaced a real bug.** After the matcher was built and passing its
tests, I asked for a structured audit before moving on to detection - not a
rewrite, a check. That audit found that a spine read with no author (VLM
correctly returned `null` rather than guess) could still auto-add on title
score alone if the title was confident enough and the margin over the
runner-up was wide enough - a real, demonstrable case: reading "Dune" with no
author landed a score of 1.0 with a comfortable margin, clearing both gates
with zero author verification. The catalog's other ambiguous pairs had only
been safe by accident (tied at exactly zero margin). This became an
unconditional author gate (`match()` in `matcher.py`), not a conditional
exception, and a permanent test - I would not have caught this by reading
the code once and trusting it worked because the tests were green.

**I pushed back on Claude's recommendations more than once, and the code is
different because of it.** Some concrete instances, not a general claim:

- When `catalog.py` still depended on `django.conf.settings`, Claude's first
  fix moved the dependency later (inside the function, resolved lazily) and
  called it decoupled. I rejected that as only decoupling from Django's
  *boot order*, not from Django itself - the module still couldn't run
  standalone. It was rebuilt with no Django import at all.
- For the `load_catalog` management command, Claude's default idempotency
  check was "skip if the table already has any rows." I rejected that as too
  weak - if I edit `catalog.csv`, that check means the command silently does
  nothing on a rerun, and I'd rather not discover that at 2am before a demo.
  It was rebuilt as a real per-row upsert that reports counts (created /
  updated / unchanged).
- Claude's review-flow plan defaulted to building a retry endpoint for
  failed VLM spines. I cut it - the measured failure rate from the real
  benchmark run was 1 spine out of 203 (0.5%), and that didn't justify new
  backend scope with the review screen still unbuilt and this README not yet
  written. Failed spines get discard-only instead, and the README says so
  plainly rather than implying more robustness than exists.
- On the fallback detector's trigger threshold, I asked Claude to consider a
  detection-density heuristic instead of a raw box-count check and told it
  explicitly to give me the tradeoff, not just pick one. It recommended
  against the heuristic (the actual failure mode found - duplicate
  overlapping detections inflating the count - wasn't what a density
  heuristic would even target) in favor of a smaller, targeted IoU-dedup
  fix. I agreed with that reasoning and said so before it was built - not
  every exchange here was a rejection; several were me directing verification
  of a recommendation I ended up accepting.

I also required real numbers over descriptions throughout: measured
detect/VLM/match latency and per-spine cost from actual benchmark runs
against real photos (not estimates), the real API error bodies from actual
faults hit during benchmarking (an account credit exhaustion, Anthropic's
many-image size limit, and request timeouts - kept in
`docs/vlm-evidence/`, not synthesized), and the real truncation cost of the
matcher's length-ratio penalty (2 of 8 test cases) rather than a qualitative
"it's aggressive." Where something only half-worked - the frontend was never
exercised in an actual browser, no automation tool was available in this
environment - the README says that plainly instead of claiming a pass that
didn't happen.

## What's in this repo as a result

`app/AGENTS.md`, `app/CLAUDE.md` (which just `@`-imports `AGENTS.md`), and
`app/.claude/settings.json` are committed, not gitignored - they're part of
how this project was actually built, not scaffolding to hide. `AGENTS.md`
is a standing note to check Expo's versioned docs before writing frontend
code, added because Expo's SDK has changed enough during this project's
lifetime to matter; `.claude/settings.json` just enables the official Expo
plugin for this session's tooling.
