# Installation

## Prerequisites

- Docker (Docker Desktop 4.x+ or Docker Engine 20.10+ with BuildKit)
- At least 4 GB memory allocated to Docker (8 GB recommended)
- ~2 GB free disk space (1.2 GB artifact + 1 GB Docker image)
- Internet access during `docker build` (to pull the base image) and during
  `docker run` (to auto-fetch LLM credentials and make API calls)

## Steps

From the `artifact/` directory:

### 1. Build the Docker image

```bash
docker build --target fast -t knowl-artifact -f docker/Dockerfile .
```

This takes **2-3 minutes**. It uses pre-compiled Java class files so no
external Maven/Gradle downloads are needed.

### 2. Verify the build

```bash
docker run --rm knowl-artifact echo "Build OK"
```

### 3. Run the default benchmark

```bash
docker run --rm -v "$(pwd)/outputs:/artifact/outputs" knowl-artifact
```

This runs the `restcountries` benchmark end-to-end. LLM credentials are
fetched automatically on startup. Generated output appears in `outputs/`.

### 4. Run any benchmark

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  knowl-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only <repo-id>
```

See `README.md` for the full list of repo IDs and options.

## Expected install time

| Step | Time |
|------|------|
| Docker image build (fast mode) | 2-3 minutes |
| First benchmark run (restcountries) | 2-5 minutes (depends on LLM response time) |
| **Total** | **< 10 minutes** |

## Alternate build: compile from source

To compile all 15 Java repositories from source instead of using pre-compiled
classes:

```bash
docker build --target rebuild -t knowl-artifact -f docker/Dockerfile .
```

This requires internet access for Maven/Gradle dependency downloads and takes
30+ minutes depending on network speed.
