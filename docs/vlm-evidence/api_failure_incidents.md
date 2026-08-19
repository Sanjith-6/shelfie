# Real API failures hit while benchmarking, and how the pipeline handled them

Both incidents below happened running `backend/scripts/benchmark_scan.py`
against the real 7-photo fixture set, not synthetic tests. Kept as evidence
that the failure-isolation design in `vlm_reader.py` and `views.py` holds up
under genuine faults, not just the mocked failure paths in the test suite.

## Incident 1: account credit exhaustion (first batched run, before credits were added)

All 7 photos, same result:

```
Running shelf_1.jpg in batched mode...
Batched VLM call failed for 7 crop(s): vlm_api_error_400
Running shelf_2.jpg in batched mode...
Batched VLM call failed for 38 crop(s): vlm_api_error_400
Running shelf_3.jpg in batched mode...
Batched VLM call failed for 46 crop(s): vlm_api_error_400
Running shelf_4.jpg in batched mode...
Batched VLM call failed for 41 crop(s): vlm_api_error_400
Running shelf_5.jpg in batched mode...
Batched VLM call failed for 21 crop(s): vlm_api_error_400
Running shelf_6.jpg in batched mode...
Batched VLM call failed for 13 crop(s): vlm_api_error_400
Running shelf_7.jpg in batched mode...
Batched VLM call failed for 37 crop(s): vlm_api_error_400
```

Real API error body (pulled directly, not inferred from the status code):

```json
{"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."}}
```

**What this demonstrates**: every one of the 203 detected spines across all 7
photos came back as an individually-marked `status="failed"` entry with the
real error code (`vlm_api_error_400`) attached - not a crash, not a 500, not
a silently empty response. Detection and the rest of the pipeline ran
completely normally around the failure. This is the "never crash, never
silently drop" contract holding up under an unplanned, real account-level
fault.

## Incident 2: batched-mode-at-scale limits (after credits were added)

4 of 7 photos failed on the credited rerun, for two distinct, diagnosed causes
- not the same failure repeating:

**Anthropic's many-image request size limit** (`shelf_4`, `shelf_7`) - real
error body:

```json
{"type": "error", "error": {"type": "invalid_request_error", "message": "messages.0.content.11.image.source.base64.data: At least one of the image dimensions exceed max allowed size for many-image requests: 2000 pixels"}}
```

Measured crop dimensions per photo (`max(width, height)` per crop), from the
real detector output, no VLM call needed to measure this:

| photo | crops | crops > 2000px | max dimension seen | path |
|---|---|---|---|---|
| shelf_1 | 7 | 7 | 4284 | fallback |
| shelf_2 | 38 | 0 | 1645 | yolo |
| shelf_3 | 46 | 0 | 1806 | yolo |
| shelf_4 | 41 | 6 | 2155 | yolo |
| shelf_5 | 21 | 0 | 1716 | yolo |
| shelf_6 | 13 | 0 | 1605 | yolo |
| shelf_7 | 37 | 1 | 2005 | yolo |

Notably, `shelf_1`'s crops are *all* over 2000px (fallback strips are always
full image height, 4284px) yet that call succeeded - the limit only appears
to bite when a request has both many images *and* at least one over 2000px.
`shelf_1` has few enough crops (7) to be exempt.

**Timeout** (`shelf_2`, `shelf_3`) - both have 0 crops over 2000px, so the
size limit doesn't explain these. `vlm_ms` was ~61.6s and ~63.3s respectively
- consistent with the 30s `REQUEST_TIMEOUT` being hit twice (`MAX_RETRIES=1`)
plus retry backoff. Sending 38-46 full crops in one request is apparently
slow enough to process that a fixed 30s budget is marginal-to-insufficient at
that volume, independent of the size-limit issue.

**What this demonstrates**: two structurally different real failure modes
in batched mode at scale, both caught cleanly - every spine in the 4 failed
photos came back `status="failed"` with its real, specific error code
(`vlm_api_error_400` vs `vlm_timeout`), not conflated into one generic
failure. This is a real, measured limitation of batched mode as currently
implemented (no chunking, no per-request size guard) - see the README's
tradeoffs section.
