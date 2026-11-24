#!/usr/bin/env bash
# Create or update the stack from the AWS Academy Learner Lab terminal (or any
# shell with AWS credentials).
#   ./scripts/deploy.sh https://github.com/<owner>/badger-dodo-cloud.git [region]
set -euo pipefail

REPO_URL="${1:?Usage: deploy.sh <git-repo-url> [region]}"
REGION="${2:-us-east-1}"
STACK="badger-dodo"
DIR="$(cd "$(dirname "$0")/.." && pwd)"

aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$STACK" \
  --template-file "$DIR/infra/badger-dodo-stack.yaml" \
  --parameter-overrides GitRepoUrl="$REPO_URL"

aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs" --output table
