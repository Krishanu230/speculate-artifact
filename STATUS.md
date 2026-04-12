# Status

We are applying for the **Available**, **Functional**, and **Reusable** badges.

## Functional

The artifact includes:

- The complete Speculate tool source code
- 15 Java benchmark repositories from the Respector dataset
- 4 Django benchmark repositories (mathesar, education-backend, treeherder, librephotos)
- Pre-compiled class files for all Java benchmarks
- Pre-computed generation results across 5 LLM models (o4-mini, gpt-4.1,
  gpt-4.1-mini, gpt-o1, DeepSeek-R1)
- Evaluation reports (RQ1) with endpoint, parameter, and constraint metrics
- A Dockerized workflow that reproduces the OpenAPI spec generation described
  in the paper for both Java and Django benchmarks

The reviewer can:

1. Pull the published Docker image and run the tool on any of the 15 Java or 4 Django
   bundled benchmarks without manual credential setup
2. Inspect pre-computed results and evaluation reports in `results/`
3. Compare fresh outputs against pre-computed results
4. Run the tool with different LLM models via `--spec-model`

## Reusable

The artifact supports reuse beyond the paper's evaluation:

- Run on custom Java repositories by mounting them into the container
- Run on any of the 4 bundled Django repositories via `scripts/run_django.sh`
- Switch between LLM providers (Azure OpenAI, Gemini, DeepSeek)
- Configure model selection, concurrency, retry behavior, and generation
  stages via command-line flags
- The `.env.example` template documents how to add new Azure deployments
  or providers
- Source code is included and inspectable within the Docker image
- The image builds natively on both `linux/amd64` and `linux/arm64`

## Available

The artifact is publicly accessible on archival and container registries:

- **Zenodo**: https://doi.org/10.5281/zenodo.19185245
- **Docker Hub**: `krishannu/speculate-artifact:latest`
- **GitHub**: https://github.com/Krishanu230/speculate-artifact
