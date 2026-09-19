import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.project import Project
from app.schemas.code import CodeFileOut, CodeRunOut, CodeTreeOut


def _project_root(project_id: int) -> Path:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
    if project is not None and project.folder:
        return Path(project.folder).resolve()
    return Path(settings.project_workspace_root).resolve() / str(project_id)


def _target_dir(project_id: int, target: Literal["code", "tests"]) -> Path:
    root = _project_root(project_id)
    return root / ("code" if target == "code" else "tests")


def code_root(project_id: int) -> Path:
    return _target_dir(project_id, "code")


def tests_root(project_id: int) -> Path:
    return _target_dir(project_id, "tests")


def project_python(project_id: int) -> Path:
    return _ensure_project_venv(project_id)


def _project_venv_python(project_id: int) -> Path:
    root = _project_root(project_id)
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _ensure_project_venv(project_id: int) -> Path:
    python = _project_venv_python(project_id)
    if python.exists():
        return python
    venv_dir = _project_root(project_id) / ".venv"
    venv_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"创建项目虚拟环境失败：{exc}") from exc
    if not python.exists():
        raise RuntimeError(f"创建项目虚拟环境失败：未生成 {python}")
    return python


def _pip_cache_dir() -> str:
    """pip 缓存目录。路径层级不足时回退到系统临时目录，避免 IndexError。"""
    try:
        base = Path(settings.project_workspace_root).resolve()
        return str(base.parents[min(2, len(base.parents) - 1)] / ".pip-cache")
    except (OSError, ValueError, IndexError):
        return str(Path(tempfile.gettempdir()) / "sdlc-pip-cache")


# pip 参数中可能被滥用来劫持依赖源或执行安装脚本的选项。
_UNSAFE_PIP_OPTIONS = {
    "--extra-index-url",
    "--index-url",
    "-i",
    "--find-links",
    "-f",
    "--trusted-host",
    "--proxy",
    "--global-option",
    "--install-option",
    "--prefer-binary",
    "--no-binary",
    "--editable",
    "-e",
    "--src",
    "--build",
    "--target",
    "-t",
    "--cache-dir",
    "--config-settings",
    "--require-hashes",
}

# 合法包名的正则：字母数字开头，仅含字母数字、._-
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _sanitize_requirements(code_root: Path) -> Path | None:
    """净化 requirements.txt：只保留包名，剔除版本与所有 pip 选项。"""
    requirements_file = code_root / "requirements.txt"
    if not requirements_file.exists():
        return None
    names: list[str] = []
    for line in requirements_file.read_text(encoding="utf-8").splitlines():
        package = line.strip()
        # 丢弃注释、空行，以及一切以 - 开头的 pip 选项/全局参数。
        if not package or package.startswith("#") or package.startswith("-"):
            continue
        name = re.split(r"[<>=!~;]", package, maxsplit=1)[0].strip()
        name = re.sub(r"\[.*?\]$", "", name)
        # 剔除可能夹带选项（如 "requests --index-url"）或路径的行。
        if not _PACKAGE_NAME_RE.match(name):
            continue
        if name not in names:
            names.append(name)
    if not names:
        return None
    if "passlib" in names and not any(name.startswith("bcrypt") for name in names):
        names.append("bcrypt")
    safe_file = code_root / ".requirements-safe.txt"
    safe_file.write_text("\n".join(names), encoding="utf-8")
    return safe_file


def _cleanup_safe_requirements(code_root: Path) -> None:
    safe_file = code_root / ".requirements-safe.txt"
    safe_file.unlink(missing_ok=True)


# 子进程允许继承的环境变量白名单：避免把平台 SECRET_KEY 等泄露给生成的代码。
_ENV_PASSTHROUGH = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SystemRoot",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
    "TERM",
)


def subprocess_env(project_id: int, **extra: str) -> dict[str, str]:
    """构造最小化环境变量，供所有生成代码的子进程使用。"""
    env = {
        key: value
        for key in _ENV_PASSTHROUGH
        if (value := os.environ.get(key)) is not None
    }
    # 把项目虚拟环境的可执行目录前置到 PATH，确保调用到 venv 内的解释器。
    venv_bin = str(_project_venv_python(project_id).parent)
    existing_path = env.get("PATH", "")
    env["PATH"] = os.pathsep.join([venv_bin, existing_path]) if existing_path else venv_bin
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_CACHE_DIR"] = _pip_cache_dir()
    env["PIP_NO_INPUT"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env.update(extra)
    return env


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



def _repo_dir(project_id: int) -> Path | None:
    """Return the project's own Git root, never an accidental parent repo."""
    root = _project_root(project_id)
    marker = root / ".git"
    return root if marker.exists() else None


def _git_run(project_id: int, args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    root = _project_root(project_id)
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=subprocess_env(project_id),
    )


def init_git_repo(project_id: int) -> dict:
    root = _project_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".gitignore").exists():
        (root / ".gitignore").write_text(
            ".venv/\n__pycache__/\n*.pyc\n.pytest_cache/\n.requirements-safe.txt\n.env\n",
            encoding="utf-8",
        )
    if _repo_dir(project_id) is None:
        result = _git_run(project_id, ["init"], timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "初始化 Git 仓库失败")
    return git_status(project_id)


def git_status(project_id: int) -> dict:
    if _repo_dir(project_id) is None:
        return {"is_repo": False, "branch": "", "clean": True, "changed_files": 0, "files": []}
    branch_result = _git_run(project_id, ["branch", "--show-current"])
    status_result = _git_run(project_id, ["status", "--porcelain=v1"])
    if status_result.returncode != 0:
        raise RuntimeError(status_result.stderr.strip() or "读取 Git 状态失败")
    entries = [line for line in status_result.stdout.splitlines() if line.strip()]
    files = [line[3:] if len(line) > 3 else line for line in entries]
    return {
        "is_repo": True,
        "branch": branch_result.stdout.strip() or "HEAD",
        "clean": not entries,
        "changed_files": len(entries),
        "files": files,
    }


def git_diff(project_id: int) -> str:
    if _repo_dir(project_id) is None:
        return "未检测到 Git 仓库。"
    result = _git_run(project_id, ["diff", "--no-ext-diff", "--no-color"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "读取 Git diff 失败")
    cached = _git_run(project_id, ["diff", "--cached", "--no-ext-diff", "--no-color"])
    output = result.stdout
    if cached.returncode == 0 and cached.stdout:
        output += "\n\n# Staged changes\n" + cached.stdout
    return output or "工作区没有未提交的差异。"


def git_log(project_id: int, limit: int = 12) -> list[dict[str, str]]:
    if _repo_dir(project_id) is None:
        return []
    result = _git_run(project_id, ["log", f"-n{max(1, min(limit, 50))}", "--format=%h%x09%an%x09%ad%x09%s", "--date=short"])
    if result.returncode != 0:
        return []
    entries: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        commit, author, date, subject = (line.split("\t", 3) + ["", "", "", ""])[:4]
        entries.append({"commit": commit, "author": author, "date": date, "subject": subject})
    return entries


def git_commit(project_id: int, message: str) -> dict:
    message = message.strip()
    if not message:
        raise ValueError("提交说明不能为空")
    if _repo_dir(project_id) is None:
        raise RuntimeError("请先初始化 Git 仓库")
    add_result = _git_run(project_id, ["add", "-A"])
    if add_result.returncode != 0:
        raise RuntimeError(add_result.stderr.strip() or "暂存 Git 变更失败")
    staged = _git_run(project_id, ["diff", "--cached", "--quiet"])
    if staged.returncode == 0:
        return {"created": False, "commit": "", "message": "没有可提交的变更"}
    commit_result = _git_run(
        project_id,
        ["-c", "user.name=SDLC Agent", "-c", "user.email=sdlc-agent@local", "commit", "-m", message],
        timeout=60,
    )
    if commit_result.returncode != 0:
        raise RuntimeError(commit_result.stderr.strip() or "创建 Git 提交失败")
    head = _git_run(project_id, ["rev-parse", "--short", "HEAD"])
    return {"created": True, "commit": head.stdout.strip(), "message": message}


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


def write_code_file(project_id: int, relative_path: str, content: str) -> str:
    base = _target_dir(project_id, "code")
    path = _safe_path(base, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return relative_path


def edit_code_file(
    project_id: int,
    relative_path: str,
    old_string: str,
    new_string: str,
) -> str:
    base = _target_dir(project_id, "code")
    path = _safe_path(base, relative_path)
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    content = path.read_text(encoding="utf-8")
    if old_string not in content:
        raise ValueError("未在文件中找到要替换的内容")
    path.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
    return relative_path


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
            # 净化后无可安装项：跳过安装，直接做语法检查。
            install_file = None
        if install_file is not None:
            install = subprocess.run(
                [
                    str(venv_python),
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "--no-input",
                    "-r",
                    str(install_file),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                env=subprocess_env(project_id),
            )
            _cleanup_safe_requirements(base)
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
            env=subprocess_env(project_id),
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
                env=subprocess_env(project_id),
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
    return run_stage_tests(project_id, stage_code=None)


_STAGE_TEST_PREFIXES: dict[str, list[str]] = {
    "unit-test": ["test_core"],
    "integration-test": ["test_integration"],
    "system-test": ["test_system"],
    "testing": ["test_app"],
    "sprint-dev": ["test_app"],
}


def _cleanup_stage_files(base: Path, stage_code: str | None) -> None:
    """Remove stale test files from the same stage before writing new ones."""
    if not base.exists():
        return
    prefixes = _STAGE_TEST_PREFIXES.get(stage_code, []) if stage_code else []
    if not prefixes:
        return
    for path in base.iterdir():
        if path.is_file() and path.suffix == ".py":
            name = path.name
            if name.startswith("conftest"):
                continue
            for prefix in prefixes:
                if name == f"{prefix}.py" or name.startswith(f"{prefix}_"):
                    path.unlink(missing_ok=True)
                    break


def run_stage_tests(project_id: int, stage_code: str | None = None) -> CodeRunOut:
    tests_base = _target_dir(project_id, "tests")
    code_tests_base = _target_dir(project_id, "code") / "tests"
    _cleanup_stage_files(tests_base, stage_code)
    _cleanup_stage_files(code_tests_base, stage_code)
    has_tests = (
        (tests_base.exists() and any(tests_base.rglob("test_*.py")))
        or (code_tests_base.exists() and any(code_tests_base.rglob("test_*.py")))
    )
    if not has_tests:
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
        env=subprocess_env(project_id),
    )
    code_root = _target_dir(project_id, "code")
    test_dirs: list[str] = []
    if tests_base.exists() and any(tests_base.rglob("test_*.py")):
        test_dirs.append(str(tests_base))
    if code_tests_base.exists() and any(code_tests_base.rglob("test_*.py")):
        test_dirs.append(str(code_tests_base))
    try:
        result = subprocess.run(
            [str(venv_python), "-m", "pytest", *test_dirs, "-q"],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(code_root),
            env=subprocess_env(project_id, PYTHONPATH=str(code_root)),
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
