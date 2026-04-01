## Notes
The current reviewer flow is:

1. The reviewer downloads the artifact folder.
2. The reviewer builds the image (a few minutes).
3. The reviewer runs the tool on any bundled repo. Everything, including LLM keys, should work out of the box.


Things Tried:
1. The most faithful approach would have been compiling the repos from source and then running Speculate on them. We tried compiling during the Docker image build step but could not get the time below 30 minutes, even with Maven cache mounts and parallel compile stages. In the end we fell back to baking pre-compiled classes into the image, similar to what the Respector artifact does.

## TODOs
- [x] Fill in the Django repos.
- [ ] Work on code refactoring and cleanup things like unwanted logs and keywords like 'knowl'.
- [ ] Verify on a case-by-case basis that the runs match the numbers reported in the paper: differing on gravitee
- [ ] Add a run-all mode to the runner.
- [x] Find a safe way to share LLM keys with reviewers. Perhaps a one-time fetch during setup could work.
- [ ] Add instructions on how to run it on any new django/jersey/spring repo

## Size Breakdown

| Component | Size |
|-----------|------|
| **Artifact folder (total)** | **1.2 GB** |
| `benchmarks/java/` (source repos) | 718 MB |
| `results/` (precomputed runs, zipped) | 427 MB |
| `precompiled/` (class files) | 53 MB |
| `tool/` (Speculate source) | 28 MB |
| `scripts/`, `docker/`, docs | < 1 MB |
| `outputs/` (empty, mount point) | ~ 0 |
| **Docker image** | **1.01 GB** |