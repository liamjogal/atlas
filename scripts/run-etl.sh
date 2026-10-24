#!/usr/bin/env bash
# Run the ETL once, on demand, and stream its logs until it finishes.
#   scripts/run-etl.sh sync         pull live feeds, rebuild datasets, re-index (~1 min)
#   scripts/run-etl.sh facilities   update the Geofabrik extract, then re-index (first run ~10-30 min)
# The "Run ETL" GitHub workflow calls this same script. Commands match infra/etl.tf.
set -euo pipefail
JOB="${1:-}"
REGION="${AWS_REGION:-us-east-1}"
PROJECT="${ATLAS_PROJECT:-atlas}"

case "$JOB" in
  sync)       COMMAND='["atlas","sync"]' ;;
  facilities) COMMAND='["sh","-c","atlas facilities --force && atlas index"]' ;;
  *) echo "usage: $0 sync|facilities" >&2; exit 2 ;;
esac

TASK_ARN=$(aws ecs run-task --region "$REGION" --cluster "$PROJECT" \
  --task-definition "${PROJECT}-etl" \
  --capacity-provider-strategy "capacityProvider=${PROJECT}-etl,weight=1" \
  --overrides "{\"containerOverrides\":[{\"name\":\"etl\",\"command\":${COMMAND}}]}" \
  --query 'tasks[0].taskArn' --output text)
if [ -z "$TASK_ARN" ] || [ "$TASK_ARN" = "None" ]; then
  echo "Could not start the task (is the ETL instance registered with the cluster?)" >&2
  exit 1
fi
TASK_ID="${TASK_ARN##*/}"
echo "Started ${JOB}: ${TASK_ID}"

# Stream this task's log stream while polling until the task stops (no 10-minute waiter limit).
aws logs tail "/${PROJECT}/etl" --region "$REGION" --follow --format short \
  --log-stream-names "etl/etl/${TASK_ID}" 2>/dev/null &
TAIL_PID=$!
trap 'kill $TAIL_PID 2>/dev/null || true' EXIT

while true; do
  STATUS=$(aws ecs describe-tasks --region "$REGION" --cluster "$PROJECT" --tasks "$TASK_ARN" \
    --query 'tasks[0].lastStatus' --output text)
  [ "$STATUS" = "STOPPED" ] && break
  sleep 10
done
sleep 5  # let the last log lines arrive

EXIT_CODE=$(aws ecs describe-tasks --region "$REGION" --cluster "$PROJECT" --tasks "$TASK_ARN" \
  --query 'tasks[0].containers[0].exitCode' --output text)
REASON=$(aws ecs describe-tasks --region "$REGION" --cluster "$PROJECT" --tasks "$TASK_ARN" \
  --query 'tasks[0].stoppedReason' --output text)
echo "ETL ${JOB} finished: exit code ${EXIT_CODE} (${REASON})"
[ "$EXIT_CODE" = "0" ]
