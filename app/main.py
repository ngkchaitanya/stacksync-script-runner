import json
import os
import tempfile
import subprocess
from flask import Flask, request, jsonify
import sys, shutil

app = Flask(__name__)

MAX_SCRIPT_BYTES = 200_000
DEFAULT_TIMEOUT_SEC = 20

# Prefer the interpreter running the API, fall back cleanly
PYTHON_BIN = sys.executable
if not os.path.exists(PYTHON_BIN):
    PYTHON_BIN = shutil.which("python3") or shutil.which("python") or "/usr/bin/python3"

NSJAIL_BIN = shutil.which("nsjail") or "nsjail"

# Absolute paths so they work both inside and outside the jail
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Pick config by env. Default to light for Cloud Run compatibility.
# NSJAIL_MODE = os.getenv("NSJAIL_MODE", "light")  # "light" or "full" (anything non-"light" uses full)
# NSJAIL_CFG = os.path.join(
#     BASE_DIR,
#     "nsjail-light.cfg" if NSJAIL_MODE == "light" else "nsjail.cfg"
# )
NSJAIL_CFG = os.path.join(
    BASE_DIR,
    "nsjail-light.cfg")

RUNNER_PATH = os.path.join(BASE_DIR, "app", "runner.py")

# Toggle nsjail on or off at runtime
USE_NSJAIL = os.getenv("USE_NSJAIL", "1") == "1"
# Do not auto-disable on Cloud Run. We rely on the light config there.

def validate_body(body):
    if not isinstance(body, dict):
        return "Body must be a JSON object"
    if "script" not in body:
        return "Missing 'script' field"
    if not isinstance(body["script"], str):
        return "'script' must be a string"
    if len(body["script"].encode("utf-8")) > MAX_SCRIPT_BYTES:
        return "Script too large"
    if "timeout" in body:
        t = body["timeout"]
        if not isinstance(t, int) or t <= 0 or t > 30:
            return "Invalid 'timeout'. Use an integer between 1 and 30 seconds"
    return None

def get_timeout(body):
    t = body.get("timeout")
    return int(t) if isinstance(t, int) and 1 <= t <= 30 else DEFAULT_TIMEOUT_SEC

@app.post("/execute")
def execute():
    try:
        body = request.get_json(force=True, silent=True)
        err = validate_body(body)
        if err:
            return jsonify({"error": err}), 400

        script_text = body["script"]
        timeout_sec = get_timeout(body)

        # Write script to /tmp so it is visible to the jailed process
        with tempfile.NamedTemporaryFile("w", delete=False, dir="/tmp", suffix=".py") as tf:
            tf.write(script_text)
            script_path = tf.name

        try:
            if USE_NSJAIL:
                cmd = [
                    NSJAIL_BIN,
                    "-C", NSJAIL_CFG,
                    "--", PYTHON_BIN, RUNNER_PATH, script_path
                ]
            else:
                cmd = [PYTHON_BIN, RUNNER_PATH, script_path]

            print(
                f"EXEC_MODE={'nsjail' if USE_NSJAIL else 'no-nsjail'} "
                f"CFG={os.path.basename(NSJAIL_CFG)} "
                f"PYTHON_BIN={PYTHON_BIN}",
                flush=True
            )

            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec + 1,
            )
        finally:
            try:
                os.remove(script_path)
            except Exception:
                pass

        if proc.returncode != 0:
            return jsonify({"error": proc.stderr.strip() or "Execution failed"}), 400

        try:
            payload = json.loads(proc.stdout)
        except Exception:
            return jsonify({"error": "Runner output was not valid JSON", "raw": proc.stdout}), 500

        return jsonify(payload), 200

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Execution timed out"}), 408
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
