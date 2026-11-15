#!/usr/bin/env bash
# Copy the images that you tested on dev to prod, with no rebuild: prod then runs the same
# bytes. Each named image goes from dev's registry to prod's registry as :latest. Then the
# prod web app or Function that runs the image is stopped and started, so Azure pulls the
# image (a restart keeps the cached image). The script prints the prod digest before each
# copy, and the command that puts that digest back.
#
#   infra/copy-dev-images-to-prod.sh core app seeder retention
#
# Needs `az login` with access to both resource groups. The Dynatrace dashboard and the
# RateXp Dynatrace app are no images; docs/custom-deploy.md (Dev environment) tells how
# they go to prod.
set -euo pipefail

# The names that infra/main.tf gives the default project "ratexp" in prod and in dev.
PROJECT=ratexp
DEV_REGISTRY=${PROJECT}devacr
PROD_REGISTRY=${PROJECT}acr
PROD_GROUP=rg-${PROJECT}

usage() {
  echo "usage: $0 <image>... (core, app, seeder, retention)" >&2
  exit 2
}

# Check every name before the first copy, so a typo copies nothing.
[[ $# -gt 0 ]] || usage
for image in "$@"; do
  case $image in
    core | app | seeder | retention) ;;
    *) usage ;;
  esac
done

for image in "$@"; do
  case $image in
    core | app) kind=webapp ;;
    seeder | retention) kind=functionapp ;;
  esac
  before=$(az acr repository show --name "$PROD_REGISTRY" --image "$image:latest" --query digest --output tsv)
  az acr import --name "$PROD_REGISTRY" --registry "$DEV_REGISTRY" \
    --source "$image:latest" --image "$image:latest" --force
  after=$(az acr repository show --name "$PROD_REGISTRY" --image "$image:latest" --query digest --output tsv)
  echo "$image: prod $before -> $after"
  echo "$image: to roll back, run: az acr import --name $PROD_REGISTRY --registry $PROD_REGISTRY" \
    "--source $image@$before --image $image:latest --force, then stop and start $PROJECT-$image"
  az "$kind" stop --resource-group "$PROD_GROUP" --name "$PROJECT-$image"
  az "$kind" start --resource-group "$PROD_GROUP" --name "$PROJECT-$image"
done
echo "Started. core and the dashboard answer after about 2 minutes."
