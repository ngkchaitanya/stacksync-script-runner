# Safe Python Script Execution Service

A small Flask API that runs user-submitted Python in a sandbox and returns the `main()` result plus `stdout`. I run nsjail for local and Docker, and disable it on Cloud Run due to a gVisor syscall restriction. The API shape stays the same in both cases.

* Endpoint: `POST /execute`
* Dockerized service exposing port `8080`
* Uses nsjail for sandboxing locally and in Docker
* Deployable to Cloud Run
* Fallback mode on Cloud Run when gVisor blocks nsjail syscalls

## Quick start (local, with nsjail)

```bash
docker build -t ss-exec .
docker run -p 8080:8080 -e PORT=8080 ss-exec
```

Test:

```bash
curl -s -X POST http://localhost:8080/execute \
  -H "Content-Type: application/json" \
  -d '{"script":"def main():\n  print(\"hello\")\n  return {\"ok\": True}"}'
```

Expected:

```json
{"result":{"ok":true},"stdout":"hello\n"}
```

## Live Cloud Run URL

Service: `https://ss-exec-isrdf7uyha-uc.a.run.app`

Example:

```bash
curl -s -X POST "https://ss-exec-isrdf7uyha-uc.a.run.app/execute" \
  -H "Content-Type: application/json" \
  -d '{"script":"def main():\n  print(\"hello\")\n  return {\"ok\": True}"}'
```

## API

**POST** `/execute`

**Request body**

```json
{
  "script": "def main():\n  print('hello')\n  return {\"ok\": True}",
  "timeout": 5
}
```

* `script` required. A Python string that defines `main()` and returns JSON serializable data.
* `timeout` optional. Integer 1 to 30 seconds. Defaults to 20.

**Response**

```json
{
  "result": { "ok": true },
  "stdout": "hello\n"
}
```

**Error cases**

* `400 {"error":"Missing 'script' field"}`
* `400 {"error":"Script too large"}`
* `400 {"error":"main() must return JSON-serializable data"}`
* `408 {"error":"Execution timed out"}`

## Security model

* Local and Docker: user code runs under nsjail with a writable `/tmp`, CPU and memory rlimits, and no network. See `nsjail.cfg` for the exact caps.
* Cloud Run: gVisor blocks a required `prctl`, so I switch nsjail off (`USE_NSJAIL=0`) and keep strict timeouts. Same API, same contract.
* Runtime libs available: standard library, NumPy, Pandas.

## Design decisions

* Flask + Gunicorn for a small surface and fast cold starts.
* nsjail for isolation in Docker. I use a reduced config by default so it runs on plain Docker without extra flags.
* Cloud Run fallback because gVisor blocks `PR_SET_SECUREBITS`. I detect Cloud Run via `K_SERVICE` and flip `USE_NSJAIL=0`.
* Temp files in `/tmp` inside the container so there is no dependency on host paths.

## Configuration

Environment variables:

* `PORT` - web server port. Default 8080. Cloud Run sets this automatically.
* `USE_NSJAIL` - set `1` to run via nsjail, `0` to disable. On Cloud Run I auto-disable when `K_SERVICE` is present. You can check the active value in logs (EXEC\_MODE=...).

## Project structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py        # Flask app and /execute route (nsjail toggle lives here)
│   └── runner.py      # Loads user script, runs main(), returns {result, stdout}
├── nsjail.cfg         # nsjail config (strict for local; Cloud Run uses fallback)
├── requirements.txt
└── Dockerfile
```

## Build and deploy to Cloud Run

One time:

```bash
REGION=us-central1
PROJECT_ID=$(gcloud config get-value project)
REPO=ss-exec-repo
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/ss-exec:v1"

gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION" || true
```

Build and push with Cloud Build:

```bash
gcloud builds submit --tag "$IMAGE" .
```

Deploy:

```bash
gcloud run deploy ss-exec \
  --image "$IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 30s \
  --set-env-vars USE_NSJAIL=0
```

Get the URL:

```bash
gcloud run services describe ss-exec --region "$REGION" \
  --format='value(status.url)'
```

**Repro note**
Built with Python 3.11 slim on Debian bookworm. nsjail is built from the google/nsjail source during the Docker build. The exact commit is visible in the Docker build logs. Python deps are pinned in `requirements.txt` for stable builds.

## Postman quick setup

* Method: POST
* URL: `http://localhost:8080/execute` or your Cloud Run URL
* Headers: `Content-Type: application/json`
* Body: Raw, JSON

Payloads to try:

Simple

```json
{"script":"def main():\n  print('hello')\n  return {\"ok\": True}"}
```

With NumPy

```json
{"script":"def main():\n  import numpy as np\n  print(np.arange(4))\n  return {\"sum\": int(np.sum([1,2,3]))}"}
```

Optional longer timeout

```json
{"script":"def main():\n  import time; time.sleep(2); return {\"done\": True}", "timeout": 25}
```

## Local development tips

* Rebuild local image after code changes:

```bash
docker build -t ss-exec:v3 .
docker run -p 8081:8080 -e PORT=8080 ss-exec:v3
```

* Force fallback mode locally:

```bash
docker run -p 8082:8080 -e PORT=8080 -e USE_NSJAIL=0 ss-exec:v3
```

## .dockerignore

Add this to keep builds fast:

```
.venv
.git
__pycache__/
*.pyc
*.pyo
*.log
node_modules
.DS_Store
.pytest_cache/
build/
dist/
```

## Known limitations

* `main()` must return JSON-serializable data. I intentionally reject other types.
* Third-party packages are limited to what is baked into the image. Installing packages at runtime is blocked.
* On Cloud Run, nsjail is disabled. If full jail semantics are required in production, run this image on a VM or GKE Standard with the needed capabilities.

## Troubleshooting

* Port already allocated
  Use a different host port, for example `-p 8081:8080`.

* NameError mentioning `true`
  Use Python constants: `True`, `False`, `None`.

* Numpy slow to import locally
  Increase `time_limit` in `nsjail.cfg` and the `timeout` field in the request.

## Submission checklist

* GitHub repo URL
* Cloud Run URL
* README includes:

  * local docker run
  * Cloud Run example with your URL
  * note about nsjail fallback on Cloud Run
* Time spent estimate
