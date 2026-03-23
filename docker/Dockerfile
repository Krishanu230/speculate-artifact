# syntax=docker/dockerfile:1.7
FROM --platform=linux/amd64 eclipse-temurin:8-jdk AS jdk8

# ---------------------------------------------------------------------------
# Base stage: shared runtime with Python, Maven, JDK 11 + 8, tool code
# ---------------------------------------------------------------------------
FROM --platform=linux/amd64 maven:3.9.9-eclipse-temurin-11 AS base

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
COPY benchmarks /artifact/benchmarks
COPY scripts /artifact/scripts

RUN chmod +x /artifact/scripts/*.sh

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv "$VIRTUAL_ENV" \
    && "$VIRTUAL_ENV/bin/pip" install --upgrade pip \
    && "$VIRTUAL_ENV/bin/pip" install -r /artifact/tool/knowl-apidocs/requirements.txt

RUN --mount=type=cache,target=/root/.m2 \
    /artifact/scripts/prepare_java_tool.sh

# ===========================================================================
# FAST MODE (default): overlay pre-compiled class files onto clean source
# Usage: docker build --target fast -t knowl-artifact -f docker/Dockerfile .
# ===========================================================================
FROM base AS fast
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
