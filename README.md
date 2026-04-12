# Speculate: Generating REST API Specifications Using LLMs

Artifact for our FSE 2026 paper. Speculate takes a Java (Spring/Jersey) or
Django REST API project and generates an OpenAPI specification using LLMs.

This artifact includes the Speculate tool, 15 Java and 4 Django benchmark
repositories, pre-computed results from the paper's evaluation, and a
Dockerized workflow to reproduce or extend the results.

---

## Quick Start

The fastest way to try Speculate — no build step, no credential setup:

```bash
docker pull krishannu/speculate-artifact:latest
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  krishannu/speculate-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only Ur-Codebin-API
```

The image auto-fetches working LLM API keys on startup. Output appears under
`outputs/Ur-Codebin-API/<timestamp>/`. Open the `.html` stats file in a browser
for a full interactive dashboard.

---

## Reproducing Paper Results

### Step 1 — Get the image

**Recommended: pull from Docker Hub** (~13.3 GB local Docker disk after pull, no build required; observed clean pull time on 2026-04-12: 7m 25s)

```bash
docker pull krishannu/speculate-artifact:latest
```

**Alternative: build from source** (25–35 min first build; see [Building from Source](#building-from-source))

### Step 2 — Run a Java benchmark

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  krishannu/speculate-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only <repo-id>
```

Replace `<repo-id>` with any of the 15 Java repo IDs listed in [Benchmark Repositories](#benchmark-repositories).
A good starting point is `Ur-Codebin-API` (small, fast) or `cwa-verification-server`.

### Step 3 — Run a Django benchmark

```bash
bash scripts/run_django.sh <repo-id>
```

Valid repo IDs: `mathesar`, `education-backend`, `treeherder`, `librephotos`.

Output appears under `outputs/<repo-id>/<timestamp>/`.

### Using your own LLM credentials

The image auto-fetches credentials by default. To use your own instead:

```bash
cp tool/speculate-apidocs/.env.example reviewer.env
# Fill in credentials for at least one provider, then:
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  --env-file reviewer.env \
  krishannu/speculate-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only <repo-id>
```

See [LLM Configuration](#llm-configuration) for the required variables per provider.

---

## Running Speculate on Your Own Project

### Java (Spring or Jersey)

Use the tool image — no benchmarks baked in, ~840 MB, builds in ~3 min cold.

```bash
# Pull (fastest)
docker pull krishannu/speculate-artifact:tool

# Or build locally
docker build --target tool -t speculate-tool -f docker/Dockerfile .
```

Your project must be pre-compiled first (Maven/Gradle classes must exist).
Then mount it and run:

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  -v "/path/to/your/repo:/repo" \
  krishannu/speculate-artifact:tool \
  /artifact/scripts/run_custom_repo.sh \
    --repo-path /repo \
    --language java \
    --framework spring \
    --java-source-root /repo \
    --java-class-path /repo/target/classes
```

Change `--framework` to `jersey` as needed. For multi-module projects, pass
multiple `--java-class-path` flags:

```bash
    --java-class-path /repo/module-a/target/classes \
    --java-class-path /repo/module-b/target/classes
```

Run `run_custom_repo.sh --help` for the full option list.

### Django

The tool needs to run inside your project's existing Python environment — it
imports Django to introspect URL patterns, so Docker is not the right fit here.
Install the tool's dependencies into your project's venv instead:

```bash
# From your project's activated venv
pip install -r /path/to/speculate-artifact/tool/speculate-apidocs/requirements.txt
```

Then run the tool directly:

```bash
cd tool/speculate-apidocs/genapidocs_v2
python gen_apidocs2.py /path/to/your/project \
  --language python \
  --framework django \
  --django-settings-module yourapp.settings
```

Dynamic runtime introspection is preferred. If Django cannot boot cleanly in
your environment, rerun with `--django-use-static-endpoints` to use the
best-effort static parser instead. That mode may miss some imported
third-party routes, so use it only when the runtime mode cannot be made to work.

Set LLM credentials as environment variables or in a `.env` file in the
working directory. See [LLM Configuration](#llm-configuration).

---

## Pre-computed Results

The `results/` directory contains outputs from our paper runs. These are **not**
included in the Docker image — they are only in the artifact folder.

### Runs

`results/Runs/<repo>/` has zipped per-model outputs:

```
results/Runs/cwa-verification-server/
  o4-mini.zip
  gpt-4.1.zip
  gpt-4.1-mini.zip
  gpt-o1.zip
  DeepSeek-R1.zip
```

Each zip contains `run_1/`, `run_2/`, `run_3/` with the Speculate-generated
`external-spec.yaml`, `internal-spec.yaml`, and `stats/`.

### RQ1

`results/RQ1/results/<repo>/` has the evaluation data used in the paper:

```
results/RQ1/results/catwatch_backend/
  specs/
    dev.yaml                          Developer-provided spec
    ideal.yaml                        Ground-truth spec
    respector.yaml                    Respector baseline spec
  run_1/
    evaluation_report_main.xlsx       Endpoint, parameter, and request constraint evaluation
    evaluation_report_responses.xlsx  Response parameter and response constraint evaluation
  run_2/
  run_3/
```

---

## Output Structure

Each run produces a timestamped directory under `outputs/<repo-id>/`:

```
outputs/<repo-id>/<timestamp>_<model>_default_context_<repo-id>/
  openapi.yaml            Generated OpenAPI specification
  speculate_debug.log     Detailed execution log
  stats/
    <repo>_stats_<timestamp>.html   Interactive stats dashboard
    <repo>_stats_<timestamp>.json   Raw stats data
    dashboard.css
    dashboard.js
```

Open the **HTML stats file** in a browser for a full breakdown: per-endpoint
and per-component generation details, prompts sent, LLM responses, token
usage, and validation results.

---

## LLM Configuration

The tool requires at least one provider. Copy `.env.example`, fill in
credentials for one provider, and pass it via `--env-file`.

### Azure OpenAI

```env
AZURE_CONFIG_NAMES=primary
AZURE_DEFAULT_CONFIG_NAME=primary
AZURE_ENDPOINT_primary=https://your-resource.openai.azure.com/
AZURE_API_KEY_primary=your-api-key
AZURE_API_VERSION_FALLBACK=2024-05-01-preview
AZURE_MODEL_MAP_gpt_4_1_nano=primary/your-deployment-name
AZURE_DEFAULT_MODEL_NAME=gpt_4_1_nano
```

### Google Vertex AI (Gemini)

```env
GOOGLE_VERTEX_PROJECT_ID=your-gcp-project-id
GOOGLE_VERTEX_LOCATION=us-central1
GOOGLE_API_KEY=your-api-key
```

### DeepSeek

```env
DEEPSEEK_ENDPOINT=https://api.deepseek.com
DEEPSEEK_API_KEY=your-api-key
DEEPSEEK_MODEL_NAME=DeepSeek-R1-0528
```

---

## Tool Options

Append extra flags after the repo ID or `--repo-path`:

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  krishannu/speculate-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only Ur-Codebin-API \
    --spec-model gpt_4_1 --context-model o4_mini
```

### Model selection

| Flag | Description | Default |
|------|-------------|---------|
| `--spec-model <name>` | Model for generating specs | Provider default |
| `--context-model <name>` | Model for identifying missing context | Same as spec model |

Model names must match a key in your env file (`o4_mini`, `gpt_4_1`, `gpt_4_1_mini`, `gpt_o1`, `deepseek_r1`).

### Performance tuning

| Flag | Description | Default |
|------|-------------|---------|
| `--batch-size <n>` | Items per LLM batch | 30 |
| `--concurrency <n>` | Max concurrent LLM calls | 5 |

### Retry behavior

| Flag | Description | Default |
|------|-------------|---------|
| `--llm-max-retries <n>` | Retries per LLM call (transient errors) | 3 |
| `--validation-max-retries <n>` | Retries on invalid OpenAPI output | 2 |

### Skip stages

| Flag | Description |
|------|-------------|
| `--skip-components` | Skip schema component generation; endpoints generated without `$ref` schemas |
| `--skip-missing-context` | Skip the context-enrichment LLM call; reduces cost at the expense of quality |

---

## Benchmark Repositories

### Java (15 repos)

| # | Repo ID | Framework | Java |
|---|---------|-----------|------|
| 1 | cwa-verification-server | Spring | 11 |
| 2 | catwatch-backend | Spring | 11 |
| 3 | restcountries | Jersey | 11 |
| 4 | ocvn | Spring | 8 |
| 5 | management-api-for-apache-cassandra | Jersey | 8 |
| 6 | digdag | Jersey | 11 |
| 7 | Ur-Codebin-API | Spring | 11 |
| 8 | ohsome-api | Spring | 11 |
| 9 | quartz-manager-parent | Spring | 11 |
| 10 | features-service | Jersey | 11 |
| 11 | proxyprint-kitchen | Spring | 11 |
| 12 | senzing-api-server | Jersey | 11 |
| 13 | enviroCar-server | Jersey | 8 |
| 14 | kafka-rest | Jersey | 11 |
| 15 | gravitee-apim-rest-api | Jersey | 11 |

Full manifest with build commands and class paths: `benchmarks/java/repos.json`.

### Django (4 repos)

| # | Repo ID | Python |
|---|---------|--------|
| 1 | mathesar | 3.9 |
| 2 | education-backend | 3.11 |
| 3 | treeherder | 3.9 |
| 4 | librephotos | 3.11 |

Manifest with settings modules and venv paths: `benchmarks/django/repos.json`.

---

## Troubleshooting

**"No usable LLM provider configuration was found"**
The container could not find valid credentials. Ensure your `reviewer.env`
has real values (not placeholder defaults) for at least one provider.

**Out of memory during gravitee-apim-rest-api**
Gravitee is the largest benchmark. Increase Docker memory to at least 8 GB:
Docker Desktop → Settings → Resources → Memory.

---

## Building from Source

Most reviewers should use the pre-built image above. Build from source only
if you need to verify the build or make changes.

### Fast mode (recommended if building)

Uses pre-compiled Java class files from `precompiled/`:

```bash
docker build --target fast -t speculate-artifact -f docker/Dockerfile .
```

Build time: more than ** 2 hours ** on a first build
(librephotos ML dependencies — `dlib`, `llama-cpp-python` — are compiled
from source).

### Rebuild mode (compile benchmarks from source)

Compiles all 15 Java repositories from source inside Docker. Requires internet
access for Maven/Gradle downloads.

```bash
docker build --target rebuild -t speculate-artifact -f docker/Dockerfile .
```

---

## Contents

```
benchmarks/java/    15 Java REST API repositories (source code) — 165 MB
benchmarks/django/  4 Django REST API repositories (source code) — 56 MB
precompiled/        Pre-compiled class files for all 15 Java repos — 53 MB
results/            Pre-computed results from paper runs — 427 MB (not in Docker image)
  Runs/             Per-model generation outputs (zipped)
  RQ1/              Evaluation specs and reports used in the paper
tool/               Speculate tool source code — 28 MB
scripts/            Helper scripts
docker/             Dockerfile
outputs/            Mount point for fresh run outputs
```

---

## License

This artifact is licensed under the Creative Commons Attribution 4.0
International License (CC-BY 4.0). See [LICENSE](LICENSE).
