"""#1721: start.sh syncs Python deps before uvicorn; pip failure does not start the server."""
from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_START = Path(__file__).resolve().parents[1] / "start.sh"


def _write_fake_python(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys
            log = os.environ["START_STEP_LOG"]
            env_val = os.environ.get("TEST_DOTENV_KEY", "")
            argv = sys.argv[1:]
            if argv[:2] == ["-m", "pip"]:
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(f"pip {' '.join(argv[2:])} env={env_val}\\n")
                sys.exit(int(os.environ.get("PIP_EXIT", "0")))
            if argv[:2] == ["-m", "uvicorn"]:
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(f"uvicorn {' '.join(argv[2:])} env={env_val}\\n")
                sys.exit(0)
            sys.exit(0)
            """
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _write_fake_npm(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys
            log = os.environ["START_STEP_LOG"]
            with open(log, "a", encoding="utf-8") as fh:
                fh.write("npm " + " ".join(sys.argv[1:]) + "\\n")
            sys.exit(0)
            """
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _prepare_root(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    (root / "start.sh").write_text(REPO_START.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "requirements.txt").write_text("agno[openai,sqlite]>=3.0.0,<4\n", encoding="utf-8")
    (root / ".env").write_text("TEST_DOTENV_KEY=proof_value_1721\n", encoding="utf-8")
    (root / "web").mkdir()
    _write_fake_python(root / ".venv" / "bin" / "python")
    _write_fake_npm(root / "bin" / "npm")
    return root


def _run_start(
    root: Path,
    env: dict[str, str],
    args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = env.copy()
    run_env["PATH"] = str(root / "bin") + os.pathsep + run_env.get("PATH", "")
    cmd = ["bash", str(root / "start.sh")]
    if args is None:
        cmd.extend(["--no-build", "--host", "127.0.0.1", "--port", "8010"])
    else:
        cmd.extend(args)
    return subprocess.run(
        cmd,
        cwd=root,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_start_sh_syncs_requirements_before_uvicorn(tmp_path):
    root = _prepare_root(tmp_path)
    log = tmp_path / "steps.log"
    env = os.environ.copy()
    env["START_STEP_LOG"] = str(log)
    env["PIP_EXIT"] = "0"
    proc = _run_start(root, env)
    assert proc.returncode == 0, proc.stderr
    steps = log.read_text(encoding="utf-8").splitlines()
    assert steps[0].startswith("pip install -r")
    assert "requirements.txt" in steps[0]
    assert "env=proof_value_1721" in steps[0]
    assert steps[1].startswith("uvicorn ")
    assert "--host 127.0.0.1" in steps[1]
    assert "--port 8010" in steps[1]
    assert "env=proof_value_1721" in steps[1]

    (root / "requirements.txt").write_text(
        "agno[openai,sqlite]>=3.0.0,<4\npackaging>=24.0\n", encoding="utf-8"
    )
    log.write_text("", encoding="utf-8")
    proc = _run_start(root, env)
    assert proc.returncode == 0, proc.stderr
    steps = log.read_text(encoding="utf-8").splitlines()
    assert steps[0].startswith("pip install -r")
    assert "requirements.txt" in steps[0]
    assert steps[1].startswith("uvicorn ")


def test_start_sh_default_path_runs_pip_frontend_and_uvicorn_in_order(tmp_path):
    root = _prepare_root(tmp_path)
    log = tmp_path / "steps.log"
    env = os.environ.copy()
    env["START_STEP_LOG"] = str(log)
    env["PIP_EXIT"] = "0"
    proc = _run_start(root, env, args=[])
    assert proc.returncode == 0, proc.stderr
    steps = log.read_text(encoding="utf-8").splitlines()
    assert len(steps) == 4
    assert steps[0].startswith("pip install -r")
    assert "requirements.txt" in steps[0]
    assert "env=proof_value_1721" in steps[0]
    assert steps[1] == "npm install"
    assert steps[2] == "npm run build"
    assert steps[3].startswith("uvicorn ")
    assert "--host 127.0.0.1" in steps[3]
    assert "--port 8010" in steps[3]
    assert "env=proof_value_1721" in steps[3]


def test_start_sh_pip_failure_does_not_start_uvicorn(tmp_path):
    root = _prepare_root(tmp_path)
    log = tmp_path / "steps.log"
    env = os.environ.copy()
    env["START_STEP_LOG"] = str(log)
    env["PIP_EXIT"] = "1"
    proc = _run_start(root, env)
    assert proc.returncode != 0
    assert log.exists()
    steps = log.read_text(encoding="utf-8").splitlines()
    assert any(s.startswith("pip ") for s in steps)
    assert not any(s.startswith("uvicorn ") for s in steps)
    assert proc.stderr.strip() != ""
