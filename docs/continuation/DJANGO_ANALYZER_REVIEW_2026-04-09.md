# Django Analyzer Review — 2026-04-09

## Scope

Deep review of:

- `tool/speculate-apidocs/genapidocs_v2/django_analyzer.py` (~2857 lines)

Review goals:

- Higher-level structure and architecture
- Interface / orchestration conformance
- Dead code and stale code paths
- Logging / debug cleanup candidates
- Missing or misleading documentation / contracts
- Test coverage credibility

No code changes were made as part of this review. This file records findings
only, following the artifact review process.

---

## Summary

The Django analyzer is functional enough to support the current artifact flow,
but it has materially more architectural drift than the already-reviewed Java
analyzers. The main issues are:

- a fake static-fallback path for endpoint extraction
- interface drift around `get_endpoints`
- logger contract mismatch (`logger=None` is not actually supported)
- endpoint generation reusing the component system prompt
- direct dependence on `PythonCodeAnalyzer` internals despite the `CodeAnalyzer`
  abstraction
- a significant dead-code cluster from an older analyzer design
- tests that are badly out of sync with the current implementation

This makes the file harder to trust, harder to reuse, and harder for a reviewer
to understand.

---

## Local Smoke Baseline

For iterative Django analyzer review, use a local analyzer-only smoke instead
of the Docker-backed full pipeline.

Chosen benchmark:

- `education-backend`

Why this repo:

- it matches the host Python already available for local work (`3.11`)
- it has a small enough dependency surface to set up locally
- it exercises real DRF routing and serializer extraction
- prior integration notes already established a stable baseline:
  `38` endpoints and `31` components

Tracked local smoke command:

```bash
bash scripts/smoke_django_local.sh
```

What it does:

- uses local venv `.venvs/education-backend-smoke`
- seeds `benchmarks/django/education-backend/src/.env` from
  `core/.env.ci` if needed
- preloads that env file into `os.environ` before analyzer execution so the
  dynamic endpoint-extraction subprocess inherits required JWT/database/cache
  settings
- runs `PythonCodeAnalyzer.analyze_project(...)`
- runs `DjangoAnalyzer.get_endpoints(...)`
- runs `DjangoAnalyzer.get_schema_components()`
- writes timestamped smoke outputs under
  `outputs/smoke/education-backend-local/`

This is intentionally an analyzer smoke, not a full `gen_apidocs2.py` run, so
it avoids LLM calls and stays suitable for repeated local validation during
review/fix work.

Verified baseline on `2026-04-09`:

- command: `bash scripts/smoke_django_local.sh`
- output directory:
  `outputs/smoke/education-backend-local/20260409_033903`
- result: `38` endpoints, `31` components
- summary file:
  `outputs/smoke/education-backend-local/20260409_033903/smoke_summary.json`

---

## Findings

Organized by severity.

### HIGH

#### H1 — Static fallback for endpoint discovery is not implemented

- `django_analyzer.py:125`
- `django_analyzer.py:146-150`
- `django_analyzer.py:495-499`

`get_endpoints` claims it will fall back to static extraction if dynamic
extraction fails:

- try `_extract_endpoints_dynamic(output_dir)`
- if that fails, call `_extract_endpoints_static()`

But `_extract_endpoints_static()` is only:

```python
def _extract_endpoints_static(self) -> None:
    """Extract API endpoints using static analysis."""
    # This would implement the static URL pattern analysis
    # We'll leave this as a placeholder for now, as we're focusing on the dynamic extraction
    pass
```

Impact:

- The fallback path is misleading.
- Any dynamic extraction failure effectively degrades to “return existing cached
  endpoints if any, else probably an empty list.”
- This is a real correctness / robustness issue, not just cleanup.

Why it matters:

- Functional badge risk if a reviewer hits a dynamic-extraction problem.
- Reusable badge risk because the implementation advertises a recovery path that
  does not exist.

Risk level if fixed:

- Medium to High, because any real static extractor would be new logic.
- Very low if the change is only to remove the claim and fail explicitly.

Status update on `2026-04-09`:

- implemented as an explicit reviewer-facing mode instead of a silent fallback
- dynamic failure now raises a clear error directing users toward fixing the
  Django runtime first
- explicit static mode is available via `--django-use-static-endpoints`
- best-effort static parser added from the legacy parser base with scoped fixes
  for `lookup_field`, DRF detail-route verbs, and local `.as_view()` inference
- verified dynamic baseline still holds at `38` endpoints / `31` components on
  `education-backend`
- verified explicit static mode reaches `38` endpoints on the same repo, with
  lower fidelity for some imported third-party views (`path: null`)
- detailed tracking moved to
  `docs/continuation/DJANGO_STATIC_ENDPOINT_MODE_PLAN_2026-04-09.md`

---

#### H2 — `get_endpoints` contract drifts from the base interface

- `tool/speculate-apidocs/common/core/framework_analyzer.py:75`
- `tool/speculate-apidocs/genapidocs_v2/django_analyzer.py:125`
- `tool/speculate-apidocs/genapidocs_v2/tests/test_django_analyzer_endpoints.py:692`

Base interface:

```python
def get_endpoints(self, output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
```

Django implementation:

```python
def get_endpoints(self, output_dir: str) -> List[Dict[str, Any]]:
```

The subclass is stricter than the interface and requires a positional
`output_dir`, even though the common contract explicitly makes it optional.

Evidence of drift:

- orchestration passes `output_dir=...`, so production flow works
- tests still call `get_endpoints()` with no argument

Impact:

- The analyzer no longer fully satisfies the base contract it claims to
  implement.
- This is a maintainability / reusability issue and also contributes to test
  breakage.

Why it matters:

- A reviewer reading the interface will assume the Django implementation accepts
  the same contract.
- Interface drift was already a major review item in the Java analyzers, so this
  is exactly the kind of thing that should be recorded.

Risk level if fixed:

- Very low. This should be an additive signature fix.

---

#### H3 — `logger=None` is not a real supported mode

- `django_analyzer.py:65-70`
- `django_analyzer.py:94`
- `django_analyzer.py:208-218`
- `django_analyzer.py:657+`
- `tool/speculate-apidocs/genapidocs_v2/tests/test_django_analyzer_endpoints.py:36`
- `tool/speculate-apidocs/genapidocs_v2/tests/test_django_analyzer_serializer.py:41`

Constructor signature:

```python
def __init__(..., logger=None, ...)
```

But the analyzer then unconditionally calls `self.logger.info/debug/error` in
many live paths, for example:

- subprocess logging in `_extract_endpoints_dynamic`
- endpoint-context assembly in `get_endpoint_context`
- serializer/model identification and context gathering throughout the file

Tests instantiate the analyzer without a logger:

- `DjangoAnalyzer(self.code_analyzer, self.project_path)`
- `DjangoAnalyzer(self.code_analyzer, self.test_dir)`

Impact:

- The constructor contract is misleading.
- Either the analyzer should guarantee a fallback logger, or `logger` should be
  mandatory.
- Current tests do not form a trustworthy safety net because they do not match
  the runtime expectations.

Why it matters:

- Reusable badge story is weaker when public constructor arguments do not behave
  as advertised.
- This is also a latent crash risk whenever the analyzer is used outside the
  current CLI path.

Risk level if fixed:

- Very low if solved by assigning a null logger / default logger.
- Low if constructor and tests are both tightened.

Status update on `2026-04-09`:

- implemented by normalizing Django to the same logger fallback pattern already
  used by Spring and Jersey
- constructor still accepts `logger=None`, but now assigns
  `logging.getLogger(__name__)` when no logger is provided
- targeted probe: `DjangoAnalyzer(..., logger=None)` successfully completed
  real component extraction on `education-backend` and produced `31`
  components
- smoke regression check: dynamic baseline remained `38` endpoints / `31`
  components on `education-backend`

---

#### H4 — Endpoint generation uses the component system prompt

- `tool/speculate-apidocs/genapidocs_v2/gen_apidocs2.py:568`
- `tool/speculate-apidocs/genapidocs_v2/gen_apidocs2.py:631`
- `tool/speculate-apidocs/genapidocs_v2/gen_apidocs2.py:670`
- `django_analyzer.py:2449`
- `django_analyzer.py:2608`

During endpoint processing, `gen_apidocs2.py` sets:

```python
system_prompt = self.prompt_manager.get_component_system_message()
```

That same `system_prompt` is then reused for:

- endpoint request generation
- endpoint response generation

Meanwhile Django still implements:

- `get_endpoint_request_system_message()`
- `get_endpoint_response_system_message()`

Those methods are not actually consumed in the current flow.

Impact:

- Endpoint request/response generation is using the wrong system-role prompt.
- Endpoint-specific system-message methods are effectively dead today.
- The prompt contract between `FrameworkAnalyzer`, `PromptManager`, and
  `SpecGenerator` is inconsistent.

Why it matters:

- This is a correctness / architecture issue, not just style.
- It makes the framework API misleading for future contributors.

Risk level if fixed:

- Low to Medium, because prompt changes can affect output quality.
- Still worth isolating because this is a real contract mismatch.

---

### MEDIUM

#### M1 — Django analyzer leaks through the `CodeAnalyzer` abstraction

- `tool/speculate-apidocs/common/core/code_analyzer.py`
- `django_analyzer.py:2076-2079`
- `tool/speculate-apidocs/genapidocs_v2/python_analyzer.py:37`

The common `CodeAnalyzer` contract does not expose a `.result` field. But the
Django analyzer directly checks:

```python
if actual_path not in self.code_analyzer.result:
```

in `_fetch_recursive_context`.

This is only valid because the concrete paired implementation
(`PythonCodeAnalyzer`) happens to store `self.result`.

Impact:

- The analyzer is less reusable than its interface suggests.
- Strict mocks or alternate analyzers would break.
- The abstraction boundary is weaker than it looks.

Why it matters:

- Reusable badge concerns.
- Makes the code harder to reason about because some behavior depends on
  undocumented implementation details.

Risk level if fixed:

- Low. It should be possible to replace this with public-interface checks.

---

#### M2 — Large dead-code cluster from an older design remains in the file

Primary candidates:

- `django_analyzer.py:629` `_build_function_component`
- `django_analyzer.py:1087` `_get_model_code`
- `django_analyzer.py:1161` `_get_feature_code`
- `django_analyzer.py:1183` `_get_feature_prompt`
- `django_analyzer.py:1546` `_build_component_and_dependencies_recursive`

Evidence:

- `_build_function_component` has no callers.
- `_build_component_and_dependencies_recursive` is only self-recursive and is
  not called by the live component pipeline.
- `_get_model_code` / `_get_feature_code` / `_get_feature_prompt` belong to an
  older string-assembly design and are only referenced inside that legacy path.

Current live path instead uses:

- iterative queue-based component building in `get_schema_components`
- structured endpoint context from `get_endpoint_context`

Impact:

- Reviewer noise.
- Harder to distinguish the real pipeline from abandoned experiments.
- Higher risk of future accidental edits to dead code.

Why it matters:

- This was explicitly treated as worth fixing in the Jersey review.
- Dead code in an artifact hurts reviewer confidence even when inert.

Risk level if fixed:

- Zero to Very low once each candidate is confirmed unused and not referenced by
  any active tests.

---

#### M3 — Test suite is substantially out of sync with the live implementation

- `test_django_analyzer_endpoints.py:299`
- `test_django_analyzer_endpoints.py:326`
- `test_django_analyzer_endpoints.py:355`
- `test_django_analyzer_endpoints.py:692`
- `test_django_analyzer_serializer.py:369`
- `test_django_analyzer_serializer.py:373`
- `test_django_analyzer_serializer.py:432`

Examples:

- Endpoint tests expect old keys like `viewset_code`, `serializer_code`,
  `parent_code`, `feature_code`, but `get_endpoint_context` now returns a
  structured dict with `handler`, `serializers`, `features`, etc.
- Tests call `_get_serializer_code` and `_extract_class_attribute`, which do not
  exist in the current analyzer.
- Serializer tests expect request/response schema components like
  `UserSerializerRequest`, but the current `get_schema_components()` returns
  top-level serializer contexts keyed by bare serializer names.
- Endpoint tests still call `get_endpoints()` with no `output_dir`.

Impact:

- The tests are not currently a credible safety net for refactoring.
- The presence of stale tests makes the analyzer look less maintained than it
  actually is.

Why it matters:

- Functional / Reusable badge story is weaker if local tests do not match the
  code.

Risk level if fixed:

- Medium if the tests are repaired in bulk.
- Low if tackled one stale test file / expectation cluster at a time.

---

#### M4 — Single file is too large and mixes too many responsibilities

- `tool/speculate-apidocs/genapidocs_v2/django_analyzer.py`

Approximate responsibility clusters all live in one class:

- endpoint discovery
- URL/settings resolution
- endpoint context gathering
- feature-class identification
- serializer/model graph discovery
- recursive missing-symbol context fetching
- prompt-template generation

At ~2857 lines, it is not impossible to review, but it is materially harder
than it needs to be.

Impact:

- Reviewer comprehension cost is high.
- Targeted testing and surgical changes are harder.
- Dead code becomes more difficult to spot.

Why it matters:

- Reusable badge is partly about navigability and structure, not just whether
  the code runs.

Risk level if fixed:

- High if treated as a large refactor before submission.
- Best handled as a documentation / post-submission concern unless a tiny
  extraction provides immediate clarity.

---

### LOW

#### L1 — Debug output is much noisier than the reviewed Java analyzers

- `django_analyzer.py:94`
- `django_analyzer.py:146+`
- `django_analyzer.py:356+`
- `django_analyzer.py:1838`
- `django_analyzer.py:2728+`

Observations:

- `self.debug_mode = True` is hardcoded by default.
- There are many raw `print()` debug branches.
- There is a stray unconditional `print(f"{class_key} {is_model}")` in model
  identification.
- URL discovery prints a large amount of path/debug state.

Impact:

- Clutters stdout/stderr.
- Looks unfinished to reviewers.
- Inconsistent with the cleaner logger-based style already applied to Jersey.

Why it matters:

- Mostly reviewer-impression and cleanliness.

Risk level if fixed:

- Very low if changed surgically.

---

#### L2 — Prompt-related method contracts are partially misleading

- `django_analyzer.py:2400`
- `django_analyzer.py:2449`
- `django_analyzer.py:2608`
- `tool/speculate-apidocs/common/core/prompt_management.py`

Status today:

- `get_component_system_message()` is used
- endpoint request/response instruction methods are used
- endpoint request/response system-message methods are implemented but unused

Impact:

- The interface surface suggests a cleaner prompt split than the current
  orchestration actually provides.

Why it matters:

- Mostly clarity and maintainability.

Risk level if fixed:

- Low, but any prompt-wiring change should be treated as behavior-affecting.

---

## Recommended Fix Order

This is the order that currently looks most defensible if we start addressing
these findings.

### First pass: small, high-signal, low-risk

1. Fix the `get_endpoints` signature drift so Django matches the base contract.
2. ~~Fix the logger contract:
   either make logger mandatory or install a safe default/null logger.~~
   Implemented by installing the same default module logger pattern used by the
   Java analyzers.
3. Remove stray unconditional prints and convert obvious debug prints to logger
   calls or gated debug behavior.
4. ~~Record or remove the fake static-fallback claim if we are not implementing it
   immediately.~~ Implemented as explicit static mode; no longer silent fallback.

### Second pass: architecture correctness

5. Fix endpoint system-prompt wiring so request/response generation uses the
   correct system messages.
6. Remove direct dependence on `self.code_analyzer.result` where the public
   interface can be used instead.

### Third pass: dead code and tests

7. Confirm dead helper methods one by one and delete them surgically.
8. Repair or replace the stale Django analyzer tests so they match the current
   structured-context design.

### Deferred / post-submission unless tightly scoped

9. Split the analyzer into smaller modules or helper classes.

---

## Open Questions

1. Is the intended behavior to truly support a static endpoint extractor, or was
   that fallback only ever aspirational?
2. Should `logger` be considered part of the mandatory runtime contract for all
   analyzers?
3. Do we want to preserve the endpoint-specific system-message methods and wire
   them correctly, or simplify the interface and remove them?
4. Are the stale Django tests meant to be revived, or are they effectively
   abandoned historical tests that should be replaced?

---

## Notes For Future Fixes

- No implementation decisions were made here beyond classification.
- Each actual fix should follow the review process already documented in
  `docs/continuation/ARTIFACT_REVIEW_2026-04-08.md`:
  review one violation, inspect all callers, classify risk, present exact edit
  plan, then make the smallest change and test it.
