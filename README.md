# Speculate: Generating REST API Specifications Using LLMs

This is the artifact for our FSE 2026 paper. It contains the Speculate tool,
15 Java benchmark repositories from the Respector dataset, 4 Django benchmark
repositories, and scripts to reproduce the OpenAPI specification generation
described in the paper.

## Contents

```
artifact/
  benchmarks/java/    15 Java REST API repositories (source code)
  benchmarks/django/  4 Django REST API repositories (source code)
  precompiled/        Pre-compiled class files for all 15 Java repos
  results/            Pre-computed results from our runs (not included in Docker image)
    Runs/             Per-model generation outputs (zipped)
    RQ1/              Evaluation specs used in the paper (dev, ideal, respector)
  tool/               Speculate tool source code
  scripts/            Helper scripts used inside the container
  docker/             Dockerfile
  outputs/            Mount point for fresh run outputs
```

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

The full manifest with build commands, class paths, and other metadata is in
`benchmarks/java/repos.json`.

### Django (4 repos)

| # | Repo ID | Python |
|---|---------|--------|
| 1 | mathesar | 3.9 |
| 2 | education-backend | 3.11 |
| 3 | treeherder | 3.9 |
| 4 | librephotos | 3.11 |

The manifest with settings modules, venv paths, and other metadata is in
`benchmarks/django/repos.json`.

## Prerequisites

- **Docker** (Docker Desktop or Docker Engine with BuildKit support)
- **Disk space**: ~10 GB for the built Docker image (includes Java + Django venvs with ML deps), plus output space
- **Memory**: at least 4 GB allocated to Docker (8 GB recommended for gravitee and librephotos)
- **LLM API access**: the tool requires at least one LLM provider to generate
  OpenAPI specs. Supported providers are Azure OpenAI, Google Vertex AI
  (Gemini), and DeepSeek. See [LLM Configuration](#llm-configuration) below.


## Quick Start

### Option A — Pull pre-built image from Docker Hub (fastest)

```bash
docker pull krishannu/speculate-artifact:latest
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  krishannu/speculate-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only restcountries
```

No build step, no credential setup. The image auto-fetches working API keys
on startup.

### Option B — Build from source

From the `artifact/` directory:

```bash
docker build --target fast -t knowl-artifact -f docker/Dockerfile .
```

This uses pre-compiled Java class files. The image includes JDK 8, JDK 11,
Python, Maven, and all tool dependencies including Django venvs for all 4
Python repos. Build time: **2-3 minutes** on a warm cache; **25-35 minutes**
on a first build (librephotos ML dependencies — dlib, llama-cpp-python — are
compiled from source).

### Run on a single benchmark

No credential setup is needed. The image automatically fetches working API
keys for the paper's evaluation models on startup.

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  knowl-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only <repo-id>
```

Replace `<repo-id>` with any repo from the table above (e.g.,
`restcountries`, `cwa-verification-server`).

The generated OpenAPI spec and logs will appear under
`outputs/<repo-id>/<timestamp>/`.

### 3. Run the default demo (restcountries)

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  knowl-artifact
```

This runs the `restcountries` benchmark by default.

### Using your own LLM credentials

To use your own API keys instead of the bundled defaults, pass an env file:

```bash
cp tool/knowl-apidocs/.env.example reviewer.env
# Edit reviewer.env — fill in credentials for at least one provider
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  --env-file reviewer.env \
  knowl-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only <repo-id>
```

When `--env-file` is provided, the auto-fetch is skipped.
See [LLM Configuration](#llm-configuration) for details on each provider.

## Build Modes

The Dockerfile supports two targets:

### Fast mode (default, recommended)

```bash
docker build --target fast -t knowl-artifact -f docker/Dockerfile .
```

Uses pre-compiled Java class files from `precompiled/`. Build time: **2-3
minutes** on a warm cache; **25-35 minutes** on a first build due to
librephotos ML dependency compilation.

### Rebuild mode (compile from source)

```bash
docker build --target rebuild -t knowl-artifact -f docker/Dockerfile .
```

Compiles all 15 Java repositories from source inside Docker. Build time
depends on network speed and machine; expect **15-30+ minutes** on a first
run. Maven/Gradle dependencies are downloaded during the build.

## Running Benchmarks

### Java benchmarks

##### Analyze a bundled repo (analysis only, no recompilation)

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  --env-file reviewer.env \
  knowl-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only <repo-id>
```

This is the standard mode. It uses the pre-compiled classes already in the
image and runs the Speculate tool to generate an OpenAPI specification.

#### Full run (recompile + analyze)

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  --env-file reviewer.env \
  knowl-artifact \
  /artifact/scripts/run_java_repo.sh --full <repo-id>
```

This first recompiles the Java project from source inside the container, then
runs analysis.

### Django benchmarks

Run any of the 4 bundled Django repos using the host wrapper script:

```bash
bash scripts/run_django.sh <repo-id>
```

Or directly with Docker:

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  knowl-artifact \
  /artifact/scripts/run_django_repo.sh <repo-id>
```

Valid `<repo-id>` values: `mathesar`, `education-backend`, `treeherder`, `librephotos`.

Generated output appears under `outputs/<repo-id>/<timestamp>/`.

To use your own LLM credentials, pass `--env-file reviewer.env` as with the
Java benchmarks.

### Run on a custom (non-bundled) repository

You can run Speculate on your own Java project by mounting it into the container:

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  -v "/path/to/your/repo:/artifact/custom-repo" \
  --env-file reviewer.env \
  knowl-artifact \
  /artifact/scripts/run_custom_repo.sh \
    --repo-path /artifact/custom-repo \
    --language java \
    --framework spring \
    --java-source-root /artifact/custom-repo \
    --java-class-path /artifact/custom-repo/target/classes
```

Your project must be pre-compiled (i.e., `target/classes` must exist).
Adjust `--framework` to `jersey` or `spring` as appropriate.

For multi-module projects, pass multiple `--java-class-path` flags:

```bash
    --java-class-path /artifact/custom-repo/module-a/target/classes \
    --java-class-path /artifact/custom-repo/module-b/target/classes
```

Run `run_custom_repo.sh --help` for the full list of options.

## LLM Configuration

The tool requires at least one LLM provider. Copy `.env.example` and fill in
the credentials for the provider(s) you have access to. You only need **one**
working provider.

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

## Tool Options

Extra flags can be passed to the tool via `run_java_repo.sh` or
`run_custom_repo.sh`. For bundled repos, append them after the repo ID:

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  --env-file reviewer.env \
  knowl-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only restcountries \
    --spec-model gpt_4_1 --context-model o4_mini
```

### Model selection

| Flag | Description | Default |
|------|-------------|---------|
| `--spec-model <name>` | Model used for generating specs (schemas, endpoints) | Environment default (`AZURE_DEFAULT_MODEL_NAME`, etc.) |
| `--context-model <name>` | Model used for identifying missing code context | Same as spec model |

Model names must match a key defined in your env file (e.g., `o4_mini`,
`gpt_4_1`, `gpt_4_1_mini`, `gpt_o1`, `deepseek_r1`).

### Performance tuning

| Flag | Description | Default |
|------|-------------|---------|
| `--batch-size <n>` | Number of items processed per batch | 30 |
| `--concurrency <n>` | Maximum concurrent LLM calls | 5 |

### Retry behavior

| Flag | Description | Default |
|------|-------------|---------|
| `--llm-max-retries <n>` | API-level retries per LLM call (for transient errors) | 3 |
| `--validation-max-retries <n>` | Retries after the tool receives invalid OpenAPI output from the LLM | 2 |

### Skip stages

| Flag | Description |
|------|-------------|
| `--skip-components` | Skip component schema generation. Endpoints will be generated without pre-built `$ref` schemas. |
| `--skip-missing-context` | Skip the extra LLM call that asks for missing code symbols. Reduces LLM cost at the expense of context quality. |

## Pre-computed Results

The `results/` directory contains outputs from our runs, organized into two
subdirectories. These are not included in the Docker image.

### Runs

`results/Runs/<repo>/` contains zipped per-model generation outputs:

```
results/Runs/cwa-verification-server/
  o4-mini.zip
  gpt-4.1.zip
  gpt-4.1-mini.zip
  gpt-o1.zip
  DeepSeek-R1.zip
```

Each zip contains multiple runs (`run_1/`, `run_2/`, `run_3/`) with the
Speculate-generated `external-spec.yaml`, `internal-spec.yaml`, and `stats/`.

### RQ1

`results/RQ1/results/<repo>/` contains the evaluation data used in the paper:

```
results/RQ1/results/catwatch_backend/
  specs/
    dev.yaml                         Developer-provided spec
    ideal.yaml                       Ground-truth spec
    respector.yaml                   Respector baseline spec
  run_1/
    evaluation_report_main.xlsx      Endpoint, parameter, and request constraint evaluation
    evaluation_report_responses.xlsx  Response parameter and response constraint evaluation
  run_2/
  run_3/
```

The `specs/` folder contains reference specifications for comparison.

## Output Structure

Each run produces a timestamped directory under `outputs/<repo-id>/`:

```
outputs/<repo-id>/<timestamp>_<model>_default_context_<repo-id>/
  openapi.yaml        Generated OpenAPI specification
  knowl_debug.log     Detailed execution log
  stats/
    <repo>_stats_<timestamp>.html   Interactive stats dashboard
    <repo>_stats_<timestamp>.json   Raw stats data
    dashboard.css
    dashboard.js
```

The best way to inspect a run is to open the **stats HTML file** in a
browser. It provides an interactive dashboard showing per-endpoint and
per-component generation details, including prompts sent, LLM responses,
token usage, and validation results.

## Repo IDs Reference

### Java

```
cwa-verification-server
catwatch-backend
restcountries
ocvn
management-api-for-apache-cassandra
digdag
Ur-Codebin-API
ohsome-api
quartz-manager-parent
features-service
proxyprint-kitchen
senzing-api-server
enviroCar-server
kafka-rest
gravitee-apim-rest-api
```

### Django

```
mathesar
education-backend
treeherder
librephotos
```

## Troubleshooting

**"No usable LLM provider configuration was found"**
The container could not find valid credentials. Make sure your `reviewer.env`
file has real values (not the placeholder defaults) for at least one provider.

**Out of memory during gravitee-apim-rest-api**
Gravitee is the largest benchmark. Increase Docker memory to at least 8 GB:
Docker Desktop > Settings > Resources > Memory.

**Slow first build**
On a first build, the librephotos Django venv requires compiling `dlib` and
`llama-cpp-python` from source. This takes 25-35 minutes. Subsequent builds
use the Docker layer cache and are fast.

## License

This artifact is licensed under the Creative Commons Attribution 4.0
International License (CC-BY 4.0). See [LICENSE](LICENSE).
