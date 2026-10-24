#!/usr/bin/env bash
# Build the image for ARM (Graviton) and push it to ECR. CI does this on every push to master;
# run it by hand for the very first deployment, before CI is connected.
# Usage: scripts/push-image.sh
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
PROJECT="${ATLAS_PROJECT:-atlas}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
TAG=$(git rev-parse --short HEAD)

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker buildx build --platform linux/arm64 --target runtime \
  -t "${REGISTRY}/${PROJECT}:${TAG}" -t "${REGISTRY}/${PROJECT}:latest" --push "$(dirname "$0")/.."
echo "Pushed ${REGISTRY}/${PROJECT}:${TAG} (and :latest)"
