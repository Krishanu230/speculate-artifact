# Django Static Endpoint Mode Plan — 2026-04-09

## Scope

Track the design and implementation of an explicit static endpoint-extraction
mode for the Django analyzer.

This is intentionally separate from the broader Django analyzer review so the
change can be reasoned about and committed in isolation.

Related review finding:

- `H1` / first Django issue in
  `docs/continuation/DJANGO_ANALYZER_REVIEW_2026-04-09.md`

---

## Problem

Current behavior in
`tool/speculate-apidocs/genapidocs_v2/django_analyzer.py`:

- `get_endpoints(...)` tries dynamic runtime extraction first
- on failure it prints "falling back to static analysis"
- `_extract_endpoints_static()` is a placeholder and does nothing

This creates two problems:

1. The code advertises a recovery path that does not actually exist.
2. Dynamic extraction failures can degrade into an empty endpoint list instead
   of a clear reviewer-facing error.

---

## Desired Behavior

Static endpoint parsing must be an explicit reviewer-triggered mode, not a
silent fallback.

Default reviewer path:

- use dynamic Django runtime introspection
- if dynamic extraction fails, stop with a clear error
- tell the reviewer to prefer fixing the Django runtime environment
- mention that a best-effort static parser mode exists via an explicit flag

Static mode:

- enabled only through a dedicated CLI flag
- uses a best-effort static parser based on legacy parser logic
- is documented as lower-fidelity than runtime extraction

---

## When Static Mode Should Run

After this change, static parsing should be invoked only in these cases:

1. CLI flag:
   `--django-use-static-endpoints`
2. Wrapper forwarding:
   `bash scripts/run_django.sh <repo-id> --django-use-static-endpoints`
3. Programmatic construction:
   `DjangoAnalyzer(..., use_dynamic=False)`

Static mode should **not** run automatically when dynamic extraction fails.

---

## Why This Direction

This is primarily a reviewer-experience and correctness decision.

Why not silent fallback:

- it hides the fact that runtime extraction failed
- it can silently change endpoint quality and counts
- it makes debugging harder for reviewers and future maintainers
- it weakens trust in the output because the extraction mode is implicit

Why keep static mode at all:

- some reviewer environments may fail to boot Django cleanly
- legacy static parsing logic already exists and is usable as a best-effort mode
- explicit invocation makes the tradeoff visible

---

## Legacy Parser Assessment

Source reviewed:

- `/Users/abc/llm-openapi-paper/knowl-apidocs/genapidocs_v1/urlpatternsparser.py`
- `/Users/abc/llm-openapi-paper/knowl-apidocs/genapidocs_v1/router_parser.py`
- helper functions from
  `/Users/abc/llm-openapi-paper/knowl-apidocs/genapidocs_v1/util.py`

Observed on current `education-backend` analysis output:

- dynamic extractor baseline: `38` endpoints
- legacy static parser baseline: `32` endpoints

Primary gaps in the legacy parser:

- hardcoded `{pk}` instead of reading `lookup_field`
- incomplete DRF detail-route handling (`PUT` / `PATCH` / `partial_update`)
- some `.as_view()` classes collapse to `method: none`
- imported third-party views such as `dj-rest-auth` and `drf-spectacular`
  are not resolved well enough for parity with runtime extraction

Conclusion:

- the legacy parser is a viable base for a best-effort static mode
- it is not a full-parity drop-in replacement for dynamic extraction

---

## Planned Implementation

### Behavioral changes

1. Add an explicit CLI flag for Django static endpoint mode.
2. Wire `DjangoAnalyzer(use_dynamic=...)` from that flag.
3. Remove the silent dynamic-to-static fallback.
4. On dynamic failure, raise a clear error directing the reviewer toward:
   - fixing the Django runtime environment first
   - using `--django-use-static-endpoints` only if necessary
5. Implement `_extract_endpoints_static()` using a port of the legacy parser.

### Small fixes to include in the static parser port

These are in scope for the first implementation:

- respect viewset `lookup_field`
- emit detail routes with:
  - `GET retrieve`
  - `PUT update`
  - `PATCH partial_update`
  - `DELETE destroy`
- preserve leading `/` in URLs so output shape matches the dynamic extractor
- improve local `.as_view()` method inference where the class exists in project code

### Explicit non-goals for this change

- do not auto-fallback from dynamic to static
- do not guarantee parity with runtime extraction
- do not solve all imported third-party view cases
- do not batch unrelated Django analyzer fixes into this change

---

## Planned Files

Expected code changes:

- `tool/speculate-apidocs/genapidocs_v2/django_analyzer.py`
- `tool/speculate-apidocs/genapidocs_v2/gen_apidocs2.py`
- `tool/speculate-apidocs/genapidocs_v2/django_static_endpoint_parser.py` (new)
- `README.md`

Expected tracking-doc updates after implementation:

- `docs/continuation/DJANGO_ANALYZER_REVIEW_2026-04-09.md`
- this file

---

## Risk Classification

Overall: **Medium**

Reasons:

- adds a new explicit CLI mode
- changes failure-path behavior in endpoint extraction
- introduces a new parser module
- keeps default dynamic mode unchanged for successful runs

Why not High:

- no LLM prompt/orchestration change
- no schema-component logic change
- no broad refactor across many files
- static mode remains opt-in

---

## Verification Plan

### Level 1 — targeted checks

1. Run the explicit static parser mode on `education-backend`
2. Inspect endpoint count and output shape
3. Confirm static mode is only used when requested
4. Confirm dynamic failure now raises a clear reviewer-facing error instead of
   pretending to fall back

### Level 2 — smoke runs

Dynamic baseline must still pass:

```bash
bash scripts/smoke_django_local.sh
```

Expected:

- `38` endpoints
- `31` components

Static smoke should also run explicitly once after implementation.

---

## Reviewer-Facing Messaging

Intended wording direction:

- dynamic runtime extraction is preferred
- if Django cannot boot cleanly, reviewers should first try to fix the runtime
  setup
- if that is not feasible, use `--django-use-static-endpoints`
- static mode is best-effort and may miss some imported third-party routes

---

## Current Status

Status: **IMPLEMENTED AND VERIFIED**

Implemented in working tree:

- added explicit CLI flag `--django-use-static-endpoints`
- wired `DjangoAnalyzer(use_dynamic=...)` from that flag
- removed the silent dynamic-to-static fallback
- added a best-effort static parser in
  `tool/speculate-apidocs/genapidocs_v2/django_static_endpoint_parser.py`
- documented the mode in `README.md`

Verification completed on `2026-04-09`:

1. Dynamic baseline smoke:
   - command: `bash scripts/smoke_django_local.sh`
   - output:
     `outputs/smoke/education-backend-local/20260409_040340/`
   - result: `38` endpoints, `31` components

2. Explicit static-mode targeted probe:
   - repo: `education-backend`
   - result: `38` endpoints
   - behavior: explicit static extraction succeeds without Django runtime
     introspection
   - fidelity note: some imported third-party views are included with
     `path: null`, so this remains a best-effort fallback rather than a
     runtime-equivalent mode

3. Dynamic failure-path probe:
   - forced dynamic URL-resolution failure
   - confirmed behavior: raises a clear `RuntimeError` instructing the user to
     prefer fixing the Django runtime and to use
     `--django-use-static-endpoints` only if necessary

4. Static parser refactor for SLOC reduction:
   - file reduced from `800` lines to `450` lines
   - rewritten from dual regex-driven parser classes into a smaller AST-driven
     parser with shared endpoint helpers
   - verified exact output parity against the previously committed static
     parser on `education-backend` (`38` unique endpoints before and after)
   - verified normal dynamic smoke still remained at `38` endpoints / `31`
     components

Known remaining gap in static mode:

- on `education-backend`, imported third-party views such as `dj-rest-auth`
  and `drf-spectacular` can still appear with incomplete symbol fidelity,
  including `path: null`
- this is consistent with the intended non-goal of not guaranteeing parity with
  runtime extraction
