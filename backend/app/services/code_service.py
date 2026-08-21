import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

from app.core.config import settings
from app.schemas.code import CodeFileOut, CodeRunOut, CodeTreeOut


def _project_root(project_id: int) -> Path:
    return (Path(settings.project_workspace_root).resolve() / str(project_id))


def _target_dir(project_id: int, target: Literal["code", "tests"]) -> Path:
    root = _project_root(project_id)
    return root / ("code" if target == "code" else "tests")


def _project_venv_python(project_id: int) -> Path:
    root = _project_root(project_id)
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _ensure_project_venv(project_id: int) -> Path:
    python = _project_venv_python(project_id)
    if not python.exists():
        venv_dir = _project_root(project_id) / ".venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            timeout=120,
        )
    return python


def _pip_cache_dir() -> str:
    return str((Path(settings.project_workspace_root).resolve().parents[2] / ".pip-cache"))


def _sanitize_requirements(code_root: Path) -> Path | None:
    requirements_file = code_root / "requirements.txt"
    if not requirements_file.exists():
        return None
    names: list[str] = []
    for line in requirements_file.read_text(encoding="utf-8").splitlines():
        package = line.strip()
        if not package or package.startswith("#"):
            continue
        name = re.split(r"[<>=!~;]", package, maxsplit=1)[0].strip()
        name = re.sub(r"\[.*?\]$", "", name)
        if name and name not in names:
            names.append(name)
    if not names:
        return None
    if "passlib" in names and not any(name.startswith("bcrypt") for name in names):
        names.append("bcrypt<5")
    safe_file = code_root / ".requirements-safe.txt"
    safe_file.write_text("\n".join(names), encoding="utf-8")
    return safe_file


def parse_code_files(content: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    current_path: str | None = None
    buffer: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[FILE]"):
            if current_path is not None:
                entries.append((current_path, _clean_body("\n".join(buffer))))
            current_path = stripped[len("[FILE]") :].strip()
            buffer = []
        elif current_path is not None:
            buffer.append(line)
    if current_path is not None:
        entries.append((current_path, _clean_body("\n".join(buffer))))
    return entries


def _clean_body(body: str) -> str:
    lines = body.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip("\n")


def _safe_path(base: Path, relative_path: str) -> Path:
    target = (base / relative_path).resolve()
    target.relative_to(base.resolve())
    return target


def write_files(
    project_id: int,
    content: str,
    target: Literal["code", "tests"],
) -> list[str]:
    base = _target_dir(project_id, target)
    base.mkdir(parents=True, exist_ok=True)
    entries = parse_code_files(content)
    if not entries:
        raise ValueError("未解析到 [FILE] 代码块")
    written: list[str] = []
    for relative_path, body in entries:
        if target == "tests":
            parts = Path(relative_path).parts
            if parts and parts[0] == "tests":
                relative_path = "/".join(parts[1:])
        path = _safe_path(base, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written.append(relative_path)
    return written


def list_code_files(project_id: int) -> CodeTreeOut:
    base = _target_dir(project_id, "code")
    if not base.exists():
        return CodeTreeOut(exists=False, files=[])
    files = []
    for path in sorted(base.rglob("*")):
        if path.is_file():
            relative = path.relative_to(base)
            if "__pycache__" in relative.parts or path.suffix == ".pyc":
                continue
            files.append(
                CodeFileOut(
                    path=relative.as_posix(),
                    size=path.stat().st_size,
                )
            )
    return CodeTreeOut(exists=True, files=files)


def read_code_file(project_id: int, relative_path: str) -> str:
    base = _target_dir(project_id, "code")
    path = _safe_path(base, relative_path)
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    return path.read_text(encoding="utf-8")


def _decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_verify(project_id: int) -> CodeRunOut:
    base = _target_dir(project_id, "code")
    if not base.exists():
        return CodeRunOut(ok=False, phase="missing", output="未生成代码目录")
    venv_python = _ensure_project_venv(project_id)
    requirements_file = base / "requirements.txt"
    if requirements_file.exists():
        install_file = _sanitize_requirements(base)
        if install_file is None:
            install_file = requirements_file
        install = subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "-r",
                str(install_file),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "PIP_CACHE_DIR": _pip_cache_dir(), "PYTHONUTF8": "1"},
        )
        if install.returncode != 0:
            output = _decode_output(install.stderr) or _decode_output(install.stdout)
            return CodeRunOut(
                ok=False,
                phase="dependencies",
                output=(output or "依赖安装失败")[:2000],
            )
    python_files = list(base.rglob("*.py"))
    if not python_files:
        return CodeRunOut(ok=False, phase="missing", output="未找到 Python 文件")

    for py_file in python_files:
        result = subprocess.run(
            [str(venv_python), "-m", "py_compile", str(py_file)],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        if result.returncode != 0:
            output = _decode_output(result.stderr) or _decode_output(result.stdout)
            return CodeRunOut(
                ok=False,
                phase="syntax",
                output=(output or f"语法检查失败: {py_file}")[:2000],
            )

    entry = base / "main.py"
    if not entry.exists():
        alt = base / "app" / "main.py"
        if alt.exists():
            entry = alt
    if entry.exists():
        try:
            command = [sys.executable, str(entry)]
            cwd = None
            if entry.parent.name == "app":
                command = [str(venv_python), "-m", "app.main"]
                cwd = base
            else:
                command = [str(venv_python), str(entry)]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            output = _decode_output(result.stdout) + _decode_output(result.stderr)
            if result.returncode == 0:
                return CodeRunOut(
                    ok=True,
                    phase="run",
                    output=(output or "程序运行结束")[:3000],
                )
            return CodeRunOut(
                ok=False,
                phase="runtime",
                output=(output or "程序运行失败")[:3000],
            )
        except subprocess.TimeoutExpired as exc:
            output = _decode_output(exc.stdout) + _decode_output(exc.stderr)
            return CodeRunOut(
                ok=True,
                phase="startup",
                output=(
                    output + "\n[服务已启动，验证运行 10 秒后自动停止]"
                )[:3000],
            )
    return CodeRunOut(
        ok=True,
        phase="syntax",
        output="语法检查通过，未发现主入口，可按 README 启动。",
    )


def run_tests(project_id: int) -> CodeRunOut:
    base = _target_dir(project_id, "tests")
    if not base.exists() or not any(base.rglob("test_*.py")):
        return CodeRunOut(ok=False, phase="missing", output="未生成测试文件")
    venv_python = _ensure_project_venv(project_id)
    subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pytest",
            "httpx",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PIP_CACHE_DIR": _pip_cache_dir(), "PYTHONUTF8": "1"},
    )
    try:
        code_root = _target_dir(project_id, "code")
        result = subprocess.run(
            [str(venv_python), "-m", "pytest", str(base), "-q"],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=code_root,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        output = _decode_output(exc.stdout) + _decode_output(exc.stderr)
        return CodeRunOut(ok=False, phase="timeout", output=output[:4000])
    output = _decode_output(result.stdout) + _decode_output(result.stderr)
    return CodeRunOut(
        ok=result.returncode == 0,
        phase="pytest",
        output=output[:4000],
    )
