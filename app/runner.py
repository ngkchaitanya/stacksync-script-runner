import importlib.util
import io
import json
import os
import sys
import types
import traceback
from contextlib import redirect_stdout

def load_module_from_path(path: str, module_name: str = "userscript"):
    if not os.path.isfile(path):
        raise RuntimeError(f"Script not found at path: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load script")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SyntaxError as e:
        # create an rror with filename, line, and caret
        line = (e.text or "").rstrip("\n")
        caret = ""
        if e.offset and e.offset > 0:
            caret = " " * (e.offset - 1) + "^"
        msg = f"SyntaxError: {e.msg} at line {e.lineno}\n{line}\n{caret}"
        raise RuntimeError(msg)
    except Exception as e:
        tb = "".join(traceback.format_exception_only(type(e), e)).strip()
        raise RuntimeError(f"Error while importing the script: {tb}")
    return mod

def is_json_serializable(x) -> bool:
    try:
        json.dumps(x)
        return True
    except Exception:
        return False

def name_error_hint(message: str) -> str:
    lower = message.lower()
    hints = []
    if "name 'true' is not defined" in lower:
        hints.append("Use True instead of true.")
    if "name 'false' is not defined" in lower:
        hints.append("Use False instead of false.")
    if "name 'null' is not defined" in lower:
        hints.append("Use None instead of null.")
    if hints:
        return f" Hint: {' '.join(hints)}"
    return ""

def run_user_main(script_path: str):
    mod = load_module_from_path(script_path)

    if not hasattr(mod, "main") or not isinstance(getattr(mod, "main"), types.FunctionType):
        raise RuntimeError("Script must define a function main()")

    try:
        f = io.StringIO()
        with redirect_stdout(f):
            result = mod.main()
    except NameError as e:
        msg = f"NameError: {e}{name_error_hint(str(e))}"
        raise RuntimeError(msg)
    except Exception as e:
        # Show exception type and message
        tb_last = traceback.format_exc(limit=1)
        msg = f"{type(e).__name__}: {e}".strip()
        raise RuntimeError(f"Error while running main(): {msg}\n{tb_last}")

    if not is_json_serializable(result):
        raise RuntimeError("main() must return JSON-serializable data")

    out = {
        "result": result,
        "stdout": f.getvalue()
    }
    print(json.dumps(out))

def usage():
    print("Usage: python app/runner.py /path/to/user_script.py", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        usage()
        sys.exit(2)
    try:
        run_user_main(sys.argv[1])
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
