import json
import os
import tempfile
import subprocess
from flask import Flask, request, jsonify
import sys, shutil

app = Flask(__name__)

MAX_SCRIPT_BYTES = 200_000
DEFAULT_TIMEOUT_SEC = 20

PYTHON_BIN = sys.executable
if not os.path.exists(PYTHON_BIN):
    PYTHON_BIN = shutil.which("python3") or shutil.which("python") or "/usr/bin/python3"
NSJAIL_BIN = shutil.which("nsjail") or "nsjail"

# absolute paths so they work both inside and outside the jail
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NSJAIL_CFG = os.path.join(BASE_DIR, "nsjail.cfg")
RUNNER_PATH = os.path.join(BASE_DIR, "app", "runner.py")

# toggle nsjail on or off
USE_NSJAIL = (os.getenv("USE_NSJAIL", "1") == "1")
# on Cloud Run, auto-disable since gVisor blocks a required prctl
if os.getenv("K_SERVICE"):
    USE_NSJAIL = False

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

        # write script to /tmp so it is visible in the jail
        with tempfile.NamedTemporaryFile("w", delete=False, dir="/tmp", suffix=".py") as tf:
            tf.write(script_text)
            script_path = tf.name

        try:
            cmd = []
            if USE_NSJAIL:
                cmd = [NSJAIL_BIN, "-Mo", "--config", NSJAIL_CFG, "--", PYTHON_BIN, RUNNER_PATH, script_path]
            else:
                cmd = [PYTHON_BIN, RUNNER_PATH, script_path]
                
            print(f"EXEC_MODE={ 'nsjail' if USE_NSJAIL else 'no-nsjail' }", flush=True)

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
