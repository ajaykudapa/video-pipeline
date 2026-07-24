#!/usr/bin/env bash
# End-to-end smoke test: generate a sample video, upload it, wait for the
# job to complete. Run after `docker compose up -d --build`.
set -euo pipefail

API=${API:-http://localhost:8080}
SAMPLE=samples/smoke.mp4

echo "==> waiting for API..."
for i in $(seq 1 30); do
  curl -fsS "$API/api/healthz" >/dev/null 2>&1 && break
  [ "$i" = 30 ] && { echo "API never became healthy"; exit 1; }
  sleep 2
done

echo "==> generating 5s test video..."
mkdir -p samples
if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -y -v error -f lavfi -i testsrc2=duration=5:size=1280x720:rate=30 \
         -f lavfi -i sine=frequency=440:duration=5 \
         -c:v libx264 -c:a aac -shortest "$SAMPLE"
else
  docker compose run --rm -v "$PWD/samples:/out" --entrypoint ffmpeg worker \
    -y -v error -f lavfi -i testsrc2=duration=5:size=1280x720:rate=30 \
    -f lavfi -i sine=frequency=440:duration=5 \
    -c:v libx264 -c:a aac -shortest /out/smoke.mp4
fi

echo "==> uploading..."
JOB_ID=$(curl -fsS -X POST "$API/api/videos" -F "file=@$SAMPLE;type=video/mp4" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "    job: $JOB_ID"
echo "==> waiting for processing..."
for i in $(seq 1 90); do
  STATUS=$(curl -fsS "$API/api/jobs/$JOB_ID" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "    [$i] $STATUS"
  case "$STATUS" in
    completed) echo "==> SMOKE TEST PASSED"; exit 0 ;;
    completed_with_errors) echo "==> completed with errors (check DLQ / logs)"; exit 1 ;;
  esac
  sleep 2
done
echo "==> TIMED OUT"; exit 1
