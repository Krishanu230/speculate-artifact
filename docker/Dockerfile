# syntax=docker/dockerfile:1.7
FROM eclipse-temurin:8-jdk AS jdk8

# ---------------------------------------------------------------------------
# Base-tool stage: shared runtime plus the embedded Java analyzer build.
# Keep this isolated from benchmark sources so repo changes do not force a
# Java analyzer rebuild.
# ---------------------------------------------------------------------------
FROM maven:3.9.9-eclipse-temurin-11 AS base-tool

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV JDK11_HOME=/opt/java/openjdk
ENV JDK8_HOME=/opt/jdks/jdk8
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:/opt/java/openjdk/bin:${PATH}

COPY --from=jdk8 /opt/java/openjdk /opt/jdks/jdk8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /artifact

COPY tool /artifact/tool
COPY scripts/prepare_java_tool.sh /artifact/scripts/prepare_java_tool.sh

RUN chmod +x /artifact/scripts/prepare_java_tool.sh

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv "$VIRTUAL_ENV" \
    && "$VIRTUAL_ENV/bin/pip" install --upgrade pip \
    && "$VIRTUAL_ENV/bin/pip" install -r /artifact/tool/knowl-apidocs/requirements.txt

RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/prepare_java_tool.sh

# ---------------------------------------------------------------------------
# Base stage: Java review/runtime assets. Changing Django sources should not
# invalidate this stage or the embedded Java analyzer build above.
# ---------------------------------------------------------------------------
FROM base-tool AS base

COPY benchmarks/java /artifact/benchmarks/java
COPY scripts /artifact/scripts

RUN chmod +x /artifact/scripts/*.sh

# ---------------------------------------------------------------------------
# Django-runtime stage: shared interpreter surface for Django repos. Repo
# dependency installs belong in repo-specific stages on top of this layer.
# ---------------------------------------------------------------------------
FROM base AS django-runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libmysqlclient21 \
        python3.9 \
        python3.9-venv \
        python3.11 \
        python3.11-venv \
    && rm -rf /var/lib/apt/lists/*

# ===========================================================================
# DJANGO INTEGRATION: incremental, repo-by-repo.
# The first integrated repo is mathesar, which needs an older interpreter than
# the Ubuntu 24.04 default Python shipped by the base image.
# ===========================================================================
FROM django-runtime AS django-mathesar-deps
COPY benchmarks/django/mathesar/requirements.txt /tmp/mathesar/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python3.9 -m venv /opt/django-venvs/mathesar \
    && /opt/django-venvs/mathesar/bin/pip install --upgrade pip \
    && grep -vE '^clevercsv==' /tmp/mathesar/requirements.txt > /tmp/mathesar/requirements-filtered.txt \
    && /opt/django-venvs/mathesar/bin/pip install -r /tmp/mathesar/requirements-filtered.txt \
    && /opt/django-venvs/mathesar/bin/pip install --upgrade --force-reinstall numpy pandas \
    && /opt/django-venvs/mathesar/bin/pip install "clevercsv>=0.8.0" \
    && grep -vE '^(Django|djangorestframework)$' /artifact/tool/knowl-apidocs/requirements.txt > /tmp/mathesar-tool-requirements.txt \
    && /opt/django-venvs/mathesar/bin/pip install -r /tmp/mathesar-tool-requirements.txt

FROM django-runtime AS django-education-backend-deps
COPY benchmarks/django/education-backend/poetry.lock benchmarks/django/education-backend/pyproject.toml /tmp/education-backend/
RUN --mount=type=cache,target=/root/.cache/pip \
    python3.11 -m venv /opt/django-venvs/education-backend \
    && /opt/django-venvs/education-backend/bin/pip install --upgrade pip poetry poetry-plugin-export \
    && cd /tmp/education-backend \
    && /opt/django-venvs/education-backend/bin/poetry export --without-hashes --only main --format=requirements.txt --output requirements.txt \
    && /opt/django-venvs/education-backend/bin/pip install -r requirements.txt \
    && grep -vE '^(Django|djangorestframework)$' /artifact/tool/knowl-apidocs/requirements.txt > /tmp/education-backend-tool-requirements.txt \
    && /opt/django-venvs/education-backend/bin/pip install -r /tmp/education-backend-tool-requirements.txt

FROM django-runtime AS django-librephotos-runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        exiftool \
        ffmpeg \
        git \
        imagemagick \
        libmagic1 \
        libpq5 \
        libvips42t64 \
    && rm -rf /var/lib/apt/lists/*

FROM django-librephotos-runtime AS django-librephotos-deps
COPY benchmarks/django/librephotos/requirements.txt /tmp/librephotos/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        g++ \
        liblapack-dev \
        libopenblas-dev \
        libpq-dev \
        libx11-dev \
        pkg-config \
        python3.11-dev \
    && python3.11 -m venv /opt/django-venvs/librephotos \
    && /opt/django-venvs/librephotos/bin/pip install --upgrade pip \
    && CMAKE_BUILD_PARALLEL_LEVEL=1 /opt/django-venvs/librephotos/bin/pip install --default-timeout=1000 -r /tmp/librephotos/requirements.txt \
    && grep -vE '^(Django|djangorestframework)$' /artifact/tool/knowl-apidocs/requirements.txt > /tmp/librephotos-tool-requirements.txt \
    && /opt/django-venvs/librephotos/bin/pip install --default-timeout=1000 -r /tmp/librephotos-tool-requirements.txt \
    && rm -rf /var/lib/apt/lists/*

FROM django-runtime AS django-treeherder-deps
COPY benchmarks/django/treeherder/requirements/common.txt /tmp/treeherder/requirements-common.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        default-libmysqlclient-dev \
        gcc \
        python3.9-dev \
    && python3.9 -m venv /opt/django-venvs/treeherder \
    && /opt/django-venvs/treeherder/bin/pip install --upgrade pip \
    && /opt/django-venvs/treeherder/bin/pip install -r /tmp/treeherder/requirements-common.txt \
    && grep -vE '^(Django|djangorestframework)$' /artifact/tool/knowl-apidocs/requirements.txt > /tmp/treeherder-tool-requirements.txt \
    && /opt/django-venvs/treeherder/bin/pip install -r /tmp/treeherder-tool-requirements.txt \
    && rm -rf /var/lib/apt/lists/*

FROM django-librephotos-runtime AS django-integrated-sources
COPY benchmarks/django/repos.json /artifact/benchmarks/django/repos.json
COPY benchmarks/django/mathesar /artifact/benchmarks/django/mathesar
COPY benchmarks/django/education-backend /artifact/benchmarks/django/education-backend
COPY benchmarks/django/librephotos /artifact/benchmarks/django/librephotos
COPY benchmarks/django/treeherder /artifact/benchmarks/django/treeherder
RUN find /artifact/benchmarks/django/mathesar -type f -name "*.sh" -exec sed -i 's/\r$//' {} + \
    && sed -i 's/\r$//' /artifact/benchmarks/django/education-backend/src/manage.py \
    && sed -i 's/\r$//' /artifact/benchmarks/django/librephotos/manage.py \
    && sed -i 's/\r$//' /artifact/benchmarks/django/treeherder/manage.py \
    && cp /artifact/benchmarks/django/education-backend/src/core/.env.ci /artifact/benchmarks/django/education-backend/src/core/.env

# ===========================================================================
# FAST MODE (default): overlay pre-compiled class files onto clean source
# Usage: docker build --target fast -t knowl-artifact -f docker/Dockerfile .
# ===========================================================================
FROM django-integrated-sources AS fast
COPY --from=django-mathesar-deps /opt/django-venvs/mathesar /opt/django-venvs/mathesar
COPY --from=django-education-backend-deps /opt/django-venvs/education-backend /opt/django-venvs/education-backend
COPY --from=django-librephotos-deps /opt/django-venvs/librephotos /opt/django-venvs/librephotos
COPY --from=django-treeherder-deps /opt/django-venvs/treeherder /opt/django-venvs/treeherder
COPY precompiled/ /artifact/benchmarks/java/
ENTRYPOINT ["/bin/bash", "/artifact/scripts/entrypoint.sh"]
CMD ["/bin/bash", "/artifact/scripts/run_restcountries_review.sh"]

# ===========================================================================
# REBUILD MODE: compile all benchmark repos from source (parallel stages)
# Usage: docker build --target rebuild -t knowl-artifact -f docker/Dockerfile .
# ===========================================================================

FROM base AS compile-cwa-verification-server
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only cwa-verification-server

FROM base AS compile-catwatch-backend
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only catwatch-backend

FROM base AS compile-restcountries
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only restcountries

FROM base AS compile-ocvn
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only ocvn

FROM base AS compile-management-api-for-apache-cassandra
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only management-api-for-apache-cassandra

FROM base AS compile-digdag
RUN --mount=type=cache,target=/root/.m2 \
    --mount=type=cache,target=/root/.gradle \
    /artifact/scripts/run_java_repo.sh --compile-only digdag

FROM base AS compile-ur-codebin-api
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only Ur-Codebin-API

FROM base AS compile-ohsome-api
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only ohsome-api

FROM base AS compile-quartz-manager-parent
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only quartz-manager-parent

FROM base AS compile-features-service
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only features-service

FROM base AS compile-proxyprint-kitchen
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only proxyprint-kitchen

FROM base AS compile-senzing-api-server
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only senzing-api-server

FROM base AS compile-envirocar-server
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only enviroCar-server

FROM base AS compile-kafka-rest
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only kafka-rest

FROM base AS compile-gravitee-apim-rest-api
RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/run_java_repo.sh --compile-only gravitee-apim-rest-api

FROM base AS rebuild
COPY --from=compile-cwa-verification-server /artifact/benchmarks/java/cwa-verification-server /artifact/benchmarks/java/cwa-verification-server
COPY --from=compile-catwatch-backend /artifact/benchmarks/java/catwatch /artifact/benchmarks/java/catwatch
COPY --from=compile-restcountries /artifact/benchmarks/java/restcountries /artifact/benchmarks/java/restcountries
COPY --from=compile-ocvn /artifact/benchmarks/java/ocvn /artifact/benchmarks/java/ocvn
COPY --from=compile-management-api-for-apache-cassandra /artifact/benchmarks/java/management-api-for-apache-cassandra /artifact/benchmarks/java/management-api-for-apache-cassandra
COPY --from=compile-digdag /artifact/benchmarks/java/digdag /artifact/benchmarks/java/digdag
COPY --from=compile-ur-codebin-api /artifact/benchmarks/java/Ur-Codebin-API /artifact/benchmarks/java/Ur-Codebin-API
COPY --from=compile-ohsome-api /artifact/benchmarks/java/ohsome-api /artifact/benchmarks/java/ohsome-api
COPY --from=compile-quartz-manager-parent /artifact/benchmarks/java/quartz-manager /artifact/benchmarks/java/quartz-manager
COPY --from=compile-features-service /artifact/benchmarks/java/features-service /artifact/benchmarks/java/features-service
COPY --from=compile-proxyprint-kitchen /artifact/benchmarks/java/proxyprint-kitchen /artifact/benchmarks/java/proxyprint-kitchen
COPY --from=compile-senzing-api-server /artifact/benchmarks/java/senzing-api-server /artifact/benchmarks/java/senzing-api-server
COPY --from=compile-envirocar-server /artifact/benchmarks/java/enviroCar-server /artifact/benchmarks/java/enviroCar-server
COPY --from=compile-kafka-rest /artifact/benchmarks/java/kafka-rest /artifact/benchmarks/java/kafka-rest
COPY --from=compile-gravitee-apim-rest-api /artifact/benchmarks/java/gravitee-api-management /artifact/benchmarks/java/gravitee-api-management
ENTRYPOINT ["/bin/bash", "/artifact/scripts/entrypoint.sh"]
CMD ["/bin/bash", "/artifact/scripts/run_restcountries_review.sh"]
