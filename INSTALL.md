# Installation

## Prerequisites

- Docker (Docker Desktop 4.x+ or Docker Engine 20.10+ with BuildKit)
- At least 4 GB memory allocated to Docker (8 GB recommended)
- ~13.3 GB local Docker disk after pulling the pre-built image
- Internet access during `docker pull` or `docker build` and during
  `docker run` (to auto-fetch LLM credentials and make API calls)

## Steps

From the `artifact/` directory:

### 1. Pull the Docker image

```bash
docker pull krishannu/speculate-artifact:latest
```

Observed clean pull time on 2026-04-12: **7m 25s**.

### 2. Verify the image

```bash
docker run --rm krishannu/speculate-artifact echo "Image OK"
```

### 3. Run the default benchmark

```bash
docker run --rm -v "$(pwd)/outputs:/artifact/outputs" krishannu/speculate-artifact
```

This runs the `Ur-Codebin-API` benchmark end-to-end. LLM credentials are
fetched automatically on startup. Generated output appears in `outputs/`.

### 4. Run any Java benchmark

```bash
docker run --rm \
  -v "$(pwd)/outputs:/artifact/outputs" \
  krishannu/speculate-artifact \
  /artifact/scripts/run_java_repo.sh --analyze-only <repo-id>
```

### 5. Run any Django benchmark

```bash
bash scripts/run_django.sh <repo-id>
# repo-ids: mathesar, education-backend, treeherder, librephotos
```

See `README.md` for the full list of repo IDs and options.

## Expected install time

| Step | Time |
|------|------|
| Docker image pull (clean pull, observed 2026-04-12) | 7m 25s |
| First Java benchmark run (Ur-Codebin-API) | 2-5 minutes (depends on LLM response time) |
| First Django benchmark run | 3-10 minutes (depends on repo and LLM response time) |

## Alternate build: compile from source

To build from source instead of pulling the published image:

```bash
docker build --target fast -t speculate-artifact -f docker/Dockerfile .
```

This uses pre-compiled Java class files so no external Maven/Gradle downloads
are needed. Build time: **2-3 minutes** on a warm cache; **25-35 minutes** on
a first build (librephotos ML dependencies are compiled from source).

To compile all 15 Java repositories from source instead of using pre-compiled
classes:

```bash
docker build --target rebuild -t speculate-artifact -f docker/Dockerfile .
```

This requires internet access for Maven/Gradle dependency downloads and takes
30+ minutes depending on network speed.
