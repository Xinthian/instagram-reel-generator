#!/usr/bin/env python3
"""Wake one existing codespace and check its app over authenticated SSH."""
import json
import os
import shutil
import subprocess
import sys
import time


def gh(*arguments, timeout=30):
    result = subprocess.run(
        ["gh", *arguments], capture_output=True, text=True, timeout=timeout, check=True
    )
    return result.stdout


def health_ok(output):
    """curl appends its status on the last line; reject redirects and non-JSON."""
    body, separator, status = output.rpartition("\n")
    if not separator or status.strip() != "200":
        return False
    try:
        result = json.loads(body)
    except (ValueError, TypeError):
        return False
    return isinstance(result, dict) and result.get("ok") is True


def main():
    if not shutil.which("gh"):
        raise RuntimeError("Install GitHub CLI (gh) and log in with the codespace scope.")
    repo = os.environ.get("REPO", "Xinthian/instagram-reel-generator")
    port = int(os.environ.get("PORT", "7008"))
    timeout = float(os.environ.get("WAKE_TIMEOUT_SECONDS", "300"))
    interval = float(os.environ.get("WAKE_POLL_SECONDS", "5"))
    if not 1 <= port <= 65535 or timeout <= 0 or interval <= 0:
        raise RuntimeError("PORT, WAKE_TIMEOUT_SECONDS and WAKE_POLL_SECONDS must be positive and valid.")
    name = os.environ.get("CODESPACE_NAME")
    if not name:
        spaces = json.loads(gh("codespace", "list", "--repo", repo, "--limit", "100", "--json", "name,displayName"))
        matches = [space["name"] for space in spaces if space.get("displayName") == "reel-generator"]
        if len(matches) != 1:
            raise RuntimeError("Expected one reel-generator codespace; set CODESPACE_NAME to an existing name.")
        name = matches[0]
    if not name or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name):
        raise RuntimeError("Invalid codespace name.")
    endpoint = f"/user/codespaces/{name}"
    state = json.loads(gh("api", endpoint))["state"]
    print(f"Codespace: {name} ({state})", flush=True)
    if state in {"Shutdown", "ShutDown"}:
        gh("api", "--method", "POST", endpoint + "/start")
    elif state in {"Failed", "Deleted"}:
        raise RuntimeError(f"Codespace cannot start in state {state}.")
    url = f"https://{name}-{port}.app.github.dev"
    deadline = time.monotonic() + timeout
    private = False
    while time.monotonic() < deadline:
        try:
            call_timeout = max(0.1, min(30, deadline - time.monotonic()))
            state = json.loads(gh("api", endpoint, timeout=call_timeout))["state"]
            if state in {"Failed", "Deleted"}:
                raise RuntimeError(f"Codespace entered state {state}.")
            if state == "Available":
                if not private:
                    gh("codespace", "ports", "visibility", f"{port}:private", "-c", name, timeout=call_timeout)
                    private = True
                # No public endpoint or GitHub login page is accepted as app health.
                command = f"curl --silent --show-error --max-time 5 --write-out '\\n%{{http_code}}' http://127.0.0.1:{port}/api/health"
                output = gh("codespace", "ssh", "-c", name, "--", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", command, timeout=max(0.1, min(30, deadline - time.monotonic())))
                if health_ok(output):
                    print(f"Ready (private; sign in to GitHub, then use app username reel): {url}")
                    return 0
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, KeyError):
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))
    raise RuntimeError(f"Timed out waiting for the app. Last state: {state}. Open the codespace and check /tmp/reel-generator-<uid>/server.log.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        if isinstance(error, subprocess.CalledProcessError):
            message = "GitHub CLI request failed. Check login/codespace permissions with gh auth status."
        else:
            message = str(error)
        print(message, file=sys.stderr)
        sys.exit(1)
