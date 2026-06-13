from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a clean-machine Agent Hub acceptance check. By default this "
            "creates a temporary virtual environment, installs the current "
            "checkout without external providers, starts the server, and "
            "exercises portable API paths."
        )
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root to test.")
    parser.add_argument(
        "--use-current-python",
        action="store_true",
        help="Skip venv/install and run with the current interpreter plus PYTHONPATH.",
    )
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary workspace for debugging.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    result = run_acceptance(
        args.root,
        use_current_python=args.use_current_python,
        keep_temp=args.keep_temp,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_result(result)
    return 0 if result["ok"] else 1


def run_acceptance(
    root: Path,
    *,
    use_current_python: bool = False,
    keep_temp: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    temp_dir = Path(tempfile.mkdtemp(prefix="agent-hub-fresh-machine-"))
    checks: list[dict[str, Any]] = []
    server: subprocess.Popen[str] | None = None
    try:
        workspace = temp_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        python, env = _runtime_python(root, temp_dir, use_current_python=use_current_python, checks=checks)

        _record_command_check(
            checks,
            "cli_help",
            [str(python), "-m", "agent_hub", "--help"],
            cwd=workspace,
            env=env,
            expect="serve",
        )

        init_config = temp_dir / "init" / "agent-hub.config.json"
        init_config.parent.mkdir(parents=True, exist_ok=True)
        _record_command_check(
            checks,
            "init_config",
            [str(python), "-m", "agent_hub", "--config", str(init_config), "init"],
            cwd=workspace,
            env=env,
            expect="Wrote",
        )
        _check_initialized_config(init_config, checks)

        server_config = temp_dir / "server" / "agent-hub.config.json"
        server, base_url, health = _start_server_with_retries(
            python,
            server_config,
            workspace=workspace,
            env=env,
            checks=checks,
        )
        _record_check(
            checks,
            "server_health",
            bool(health.get("status") == "ok" and health.get("version")),
            f"{base_url}/health status={health.get('status')!r}",
        )
        _record_http_json_check(checks, "models_endpoint", f"{base_url}/v1/models", key="data")
        _record_http_json_check(checks, "readiness_endpoint", f"{base_url}/v1/readiness", key="score")
        _record_http_json_check(checks, "status_endpoint", f"{base_url}/v1/status", key="features")
        _record_http_text_check(checks, "dashboard_endpoint", f"{base_url}/dashboard", contains="Agent Hub")
        _record_route_check(checks, f"{base_url}/v1/route")

        _record_command_check(
            checks,
            "production_check_cli",
            [str(python), "-m", "agent_hub", "--config", str(server_config), "production-check", "--json"],
            cwd=workspace,
            env=env,
            expect='"object": "agent_hub.production_check"',
            allowed_returncodes={0, 1},
        )

        server_output = _stop_server(server)
        server = None
        _record_check(
            checks,
            "server_shutdown",
            "listening on" in server_output,
            "server started and stopped cleanly",
        )
    except Exception as exc:
        _record_check(checks, "fresh_machine_acceptance_exception", False, f"{type(exc).__name__}: {exc}")
    finally:
        if server is not None:
            _stop_server(server)
        if keep_temp:
            temp_note = str(temp_dir)
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_note = ""

    failed = [check for check in checks if not check["ok"]]
    return {
        "object": "agent_hub.fresh_machine_acceptance",
        "ok": not failed,
        "root": str(root),
        "temp_dir": temp_note,
        "checks": checks,
        "failed": failed,
    }


def _runtime_python(
    root: Path,
    temp_dir: Path,
    *,
    use_current_python: bool,
    checks: list[dict[str, Any]],
) -> tuple[Path, dict[str, str]]:
    env = _clean_env()
    if use_current_python:
        env["PYTHONPATH"] = str(root)
        _record_check(checks, "runtime_install", True, f"using current interpreter: {sys.executable}")
        return Path(sys.executable), env

    venv_dir = temp_dir / "venv"
    create = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=False,
    )
    if create.returncode != 0:
        _record_check(checks, "runtime_install", False, _last_lines(create.stdout))
        return Path(sys.executable), {**env, "PYTHONPATH": str(root)}

    python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(root)],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    _record_check(
        checks,
        "runtime_install",
        install.returncode == 0,
        _last_lines(install.stdout) if install.returncode else "installed checkout into temporary venv",
    )
    return python, env


def _write_portable_server_config(path: Path, *, workspace: Path, port: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = path.parent / "state"
    data = {
        "host": "127.0.0.1",
        "port": port,
        "workspace_dir": str(workspace),
        "state_dir": str(state),
        "inbox_dir": str(path.parent / "inbox"),
        "outbox_dir": str(path.parent / "outbox"),
        "archive_dir": str(path.parent / "archive"),
        "approval_mode": "safe",
        "allow_shell_tools": False,
        "shell_command_policy": "deny",
        "auto_detect_local_models": False,
        "auto_enable_available_providers": False,
        "debug_echo_enabled": True,
        "free_only": True,
        "default_route": ["echo"],
        "routes": [
            {"name": "smoke", "keywords": [], "agents": ["echo"]},
            {"name": "coding", "keywords": ["code", "test"], "agents": ["echo"]},
        ],
        "agents": [
            {
                "name": "echo",
                "provider": "echo",
                "provider_type": "echo",
                "model": "local-echo",
                "enabled": True,
                "free": True,
                "context_window": 1000000,
            }
        ],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _check_initialized_config(path: Path, checks: list[dict[str, Any]]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _record_check(checks, "init_config_shape", False, str(exc))
        return
    agents = data.get("agents") if isinstance(data, dict) else []
    agent_by_name = {
        item.get("name"): item
        for item in agents
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    local = agent_by_name.get("ollama-qwen-coder", {})
    _record_check(
        checks,
        "init_ollama_default_model",
        local.get("model") == "qwen2.5-coder:7b",
        f"ollama-qwen-coder model={local.get('model')!r}",
    )
    raw = path.read_text(encoding="utf-8")
    _record_check(
        checks,
        "init_config_no_inline_api_keys",
        '"api_key"' not in raw,
        "generated config does not contain inline api_key values",
    )
    routes = data.get("routes") if isinstance(data, dict) else []
    route_names = {route.get("name") for route in routes if isinstance(route, dict)}
    _record_check(
        checks,
        "init_routes",
        {"cloud-agent", "local-agent", "coding", "research"}.issubset(route_names),
        f"routes={sorted(str(name) for name in route_names)}",
    )


def _record_route_check(checks: list[dict[str, Any]], url: str) -> None:
    body = {
        "session_id": "fresh-machine",
        "route": "smoke",
        "messages": [{"role": "user", "content": "fresh machine smoke"}],
        "max_tokens": 32,
    }
    try:
        response = _post_json(url, body)
    except Exception as exc:
        _record_check(checks, "route_request", False, f"{type(exc).__name__}: {exc}")
        return
    text = (((response.get("message") or {}) if isinstance(response, dict) else {}).get("content") or "")
    _record_check(
        checks,
        "route_request",
        isinstance(text, str) and "fresh machine smoke" in text,
        f"response model={response.get('model') if isinstance(response, dict) else None!r}",
    )


def _record_command_check(
    checks: list[dict[str, Any]],
    check_id: str,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    expect: str,
    allowed_returncodes: set[int] | None = None,
) -> None:
    allowed = allowed_returncodes or {0}
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        _record_check(checks, check_id, False, f"{type(exc).__name__}: {exc}")
        return
    ok = completed.returncode in allowed and expect in completed.stdout
    detail = "ok" if ok else f"returncode={completed.returncode}; output={_last_lines(completed.stdout)}"
    _record_check(checks, check_id, ok, detail)


def _start_server_with_retries(
    python: Path,
    config_path: Path,
    *,
    workspace: Path,
    env: dict[str, str],
    checks: list[dict[str, Any]],
) -> tuple[subprocess.Popen[str], str, dict[str, Any]]:
    bind_failures = 0
    last_error: Exception | None = None
    for attempt in range(1, 8):
        port = _candidate_port()
        _write_portable_server_config(config_path, workspace=workspace, port=port)
        server = subprocess.Popen(
            [
                str(python),
                "-m",
                "agent_hub",
                "--config",
                str(config_path),
                "serve",
            ],
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            health = _wait_for_json(f"{base_url}/health", server=server, timeout=20.0)
            if bind_failures:
                _record_check(
                    checks,
                    "server_bind_retry",
                    True,
                    f"started after {bind_failures} bind retry attempt(s)",
                )
            return server, base_url, health
        except Exception as exc:
            last_error = exc
            output = _stop_server(server)
            message = f"{exc} {_last_lines(output)}"
            if "could not bind" in message.lower() or "address already in use" in message.lower():
                bind_failures += 1
                continue
            raise
    raise RuntimeError(f"server could not start after bind retries: {last_error}")


def _record_http_json_check(checks: list[dict[str, Any]], check_id: str, url: str, *, key: str) -> None:
    try:
        body = _get_json(url)
    except Exception as exc:
        _record_check(checks, check_id, False, f"{type(exc).__name__}: {exc}")
        return
    _record_check(checks, check_id, isinstance(body, dict) and key in body, f"keys={sorted(body)[:12]}")


def _record_http_text_check(checks: list[dict[str, Any]], check_id: str, url: str, *, contains: str) -> None:
    try:
        text = _get_text(url)
    except Exception as exc:
        _record_check(checks, check_id, False, f"{type(exc).__name__}: {exc}")
        return
    _record_check(checks, check_id, contains in text, f"bytes={len(text)}")


def _wait_for_json(url: str, *, server: subprocess.Popen[str], timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if server.poll() is not None:
            output = server.stdout.read() if server.stdout else ""
            raise RuntimeError(f"server exited early with {server.returncode}: {_last_lines(output)}")
        try:
            return _get_json(url)
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for {url}: {last_error}")


def _get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise TypeError(f"expected JSON object from {url}")
    return body


def _get_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8", errors="replace")


def _post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object from {url}")
    return payload


def _stop_server(server: subprocess.Popen[str]) -> str:
    if server.poll() is None:
        server.terminate()
        try:
            return server.communicate(timeout=10)[0] or ""
        except subprocess.TimeoutExpired:
            server.kill()
            return server.communicate(timeout=10)[0] or ""
    return server.communicate(timeout=10)[0] or ""


def _record_check(checks: list[dict[str, Any]], check_id: str, ok: bool, detail: str) -> None:
    checks.append({"id": check_id, "ok": bool(ok), "detail": detail})


def _candidate_port() -> int:
    # On Windows, binding to port 0 and immediately closing can make the chosen
    # port unavailable to the child server for a short time. Use high random
    # candidates and let the server's real bind be the first bind attempt.
    return random.SystemRandom().randint(20_000, 60_000)


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        normalized = key.upper()
        if normalized.startswith("AGENT_HUB_"):
            env.pop(key, None)
            continue
        if normalized in {
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANY_SCALE_API_KEY",
            "ANYSCALE_API_KEY",
            "CEREBRAS_API_KEY",
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_API_TOKEN",
            "DEEPINFRA_API_KEY",
            "FEATHERLESS_API_KEY",
            "FIREWORKS_API_KEY",
            "GEMINI_API_KEY",
            "GITHUB_TOKEN",
            "GROQ_API_KEY",
            "HUGGINGFACE_API_KEY",
            "HYPERBOLIC_API_KEY",
            "KLUSTER_API_KEY",
            "MISTRAL_API_KEY",
            "NOVITA_API_KEY",
            "NVIDIA_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "PARASAIL_API_KEY",
            "REPLICATE_API_TOKEN",
            "SAMBANOVA_API_KEY",
            "TOGETHER_API_KEY",
        }:
            env.pop(key, None)
            continue
        if normalized.endswith("_API_KEY") or normalized.endswith("_API_TOKEN"):
            env.pop(key, None)
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["AGENT_HUB_FRESH_MACHINE_ACCEPTANCE"] = "1"
    return env


def _last_lines(text: str, *, limit: int = 8) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return " | ".join(lines[-limit:])


def _print_result(result: dict[str, Any]) -> None:
    status = "passed" if result.get("ok") else "failed"
    print(f"Agent Hub fresh-machine acceptance {status}")
    for check in result.get("checks", []):
        marker = "OK" if check.get("ok") else "FAIL"
        print(f"{marker} {check.get('id')}: {check.get('detail')}")
    if result.get("temp_dir"):
        print(f"Temporary workspace kept at: {result['temp_dir']}")


if __name__ == "__main__":
    sys.exit(main())
