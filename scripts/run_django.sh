#!/bin/bash
export MSYS_NO_PATHCONV=1

# ====================================================================
# ACM-FSE 2026 Artifact Evaluation: mega-django Environment
# ====================================================================

REPO=$1
IMAGE="karar2/mega-django:latest" 
TOOL_DIR="$(pwd)/knowl-apidocs"
OUTPUT_DIR="outputs/$REPO"
CONTAINER_NAME="fse_eval_$REPO"

if [ -z "$REPO" ]; then
    echo "==============================================================="
    echo "Usage: ./run_django.sh [treeherder | mathesar | librephotos | education-backend]"
    echo "==============================================================="
    exit 1
fi

if [ ! -f "reviewer.env" ]; then
    echo "Error: reviewer.env file not found!"
    echo "Please copy .env.example to reviewer.env and add your LLM API keys."
    exit 1
fi

if [ ! -d "$TOOL_DIR" ]; then
    echo "Error: Could not find the knowl-apidocs tool at $TOOL_DIR"
    exit 1
fi

echo "Starting API spec generation for: $REPO"
echo "Using Docker Image: $IMAGE"

docker rm -f $CONTAINER_NAME 2>/dev/null

case $REPO in
    treeherder)
        docker run --name $CONTAINER_NAME --env-file reviewer.env -v "$TOOL_DIR:/root/knowl-apidocs" $IMAGE \
            /venvs/treeherder/bin/python /root/knowl-apidocs/genapidocs_v2/gen_apidocs2.py \
            /artifact/repos/treeherder/ \
            --spec-model o4-mini --context-model o4-mini \
            --django-settings-module "treeherder.config.settings"
        
        mkdir -p "$OUTPUT_DIR"
        docker cp $CONTAINER_NAME:/artifact/repos/treeherder/.knowl_logs2/ "./$OUTPUT_DIR/"
        ;;

    mathesar)
        docker run --name $CONTAINER_NAME --env-file reviewer.env -v "$TOOL_DIR:/root/knowl-apidocs" $IMAGE \
            /venvs/mathesar/bin/python /root/knowl-apidocs/genapidocs_v2/gen_apidocs2.py \
            /artifact/repos/mathesar/ \
            --spec-model o4-mini --context-model o4-mini \
            --django-settings-module "config.settings"

        mkdir -p "$OUTPUT_DIR"
        docker cp $CONTAINER_NAME:/artifact/repos/mathesar/.knowl_logs2/ "./$OUTPUT_DIR/"
        ;;

    librephotos)
        docker run --name $CONTAINER_NAME --env-file reviewer.env -v "$TOOL_DIR:/root/knowl-apidocs" $IMAGE \
            /venvs/librephotos/bin/python /root/knowl-apidocs/genapidocs_v2/gen_apidocs2.py \
            /artifact/repos/librephotos/ \
            --spec-model o4-mini --context-model o4-mini \
            --django-settings-module "librephotos.settings.development"

        mkdir -p "$OUTPUT_DIR"
        docker cp $CONTAINER_NAME:/artifact/repos/librephotos/.knowl_logs2/ "./$OUTPUT_DIR/"
        ;;

    education-backend)
        docker run --name $CONTAINER_NAME --env-file reviewer.env -v "$TOOL_DIR:/root/knowl-apidocs" $IMAGE \
            /venvs/edubackend/bin/python /root/knowl-apidocs/genapidocs_v2/gen_apidocs2.py \
            /artifact/repos/education-backend/src/ \
            --spec-model o4-mini --context-model o4-mini \
            --django-explicit-urls-file /artifact/repos/education-backend/src/core/urls/v2.py \
            --django-settings-module "core.settings"

        mkdir -p "$OUTPUT_DIR"
        docker cp $CONTAINER_NAME:/artifact/repos/education-backend/src/.knowl_logs2/ "./$OUTPUT_DIR/"
        ;;

    *)
        echo "Invalid repository name."
        echo "Choose from: treeherder, mathesar, librephotos, education-backend"
        exit 1
        ;;
esac

docker rm $CONTAINER_NAME >/dev/null

echo "==============================================================="
echo "Success! The generated API specs and logs have been saved to:"
echo "$(pwd)/$OUTPUT_DIR"
echo "==============================================================="