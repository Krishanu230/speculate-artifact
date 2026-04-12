# Requirements

## Hardware

- **CPU**: Any modern x86_64 or ARM64 processor
- **RAM**: At least 4 GB allocated to Docker (8 GB recommended for the
  gravitee-apim-rest-api benchmark)
- **Disk**: ~13.3 GB local Docker disk after pulling the pre-built image

## Software

- **Docker**: Docker Desktop 4.x+ or Docker Engine 20.10+ with BuildKit
- **OS**: Linux, macOS, or Windows with Docker Desktop
- No other software is required. All dependencies (Python, Java, Maven) are
  included in the Docker image.

## Network

- Internet access is required during:
  - `docker pull` — to download the published artifact image
  - `docker build` — to pull the base image (~500 MB)
  - `docker run` — to auto-fetch LLM credentials and make LLM API calls

## Platform note

The Docker image is multi-arch and builds natively for both `linux/amd64`
and `linux/arm64` (Apple Silicon Macs). No emulation overhead.
