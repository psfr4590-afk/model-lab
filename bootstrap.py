#!/usr/bin/env python3
"""
Pretrain Pipeline Bootstrap
===========================

Canonical project-root bootstrapper.

Responsibilities:
  1. Resolve the project root from this file, never from the caller's CWD.
  2. Reconcile the execution environment using the canonical interpreter.
  3. Verify Python, Git, CMake, llama.cpp, packages, GPU hardware and CUDA.
  4. Create only the directories that belong to this project.
  5. Maintain seed URLs without duplicating entries.
  6. Apply requested configuration overrides safely.
  7. Run pipeline stages in deterministic order.
  8. Preserve resumability and produce a useful final diagnostic.

Important:
  - The project root is ALWAYS the directory containing this file.
  - This script does NOT create nested pretrain-pipeline directories.
  - GPU hardware detection and PyTorch CUDA availability are separate facts.
  - A CPU-only PyTorch wheel is NOT treated as CUDA-capable merely because
    nvidia-smi exists.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import platform
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bootstrap] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

log = logging.getLogger("bootstrap")


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = r"""
 ____  ____  _____ ____  ____  ____  _  _  _
|  _ \|  _ \| ____|_  _|_  _|/ ___|| || || |
| |_) | |_) |  _|   ||   ||  \___ \| || || |
|  __/|  _ <| |___  ||   ||   ___) |__   _|
|_|   |_| \_\_____|___|___|  |____/   |_|

Pretrain Pipeline Bootstrap
crawl -> clean -> dedup -> weight -> tokenize -> shard -> train -> GGUF
"""


# ---------------------------------------------------------------------------
# Canonical project structure
# ---------------------------------------------------------------------------

STAGE_ORDER = [
    "crawl",
    "clean",
    "dedup",
    "weight",
    "tokenize",
    "shard",
    "train",
    "export",
]


REQUIRED_PACKAGES = [
    ("yaml", "pyyaml>=6.0"),
    ("requests", "requests>=2.31"),
    ("bs4", "beautifulsoup4>=4.12"),
    ("lxml", "lxml>=5.0"),
    ("numpy", "numpy>=1.24"),
    ("tokenizers", "tokenizers>=0.19"),
    ("sentence_transformers", "sentence-transformers>=3.0"),
    ("faiss", "faiss-cpu>=1.8.0"),
    ("torch", "torch>=2.1"),
    ("safetensors", "safetensors>=0.4"),
    ("datasets", "datasets>=2.19"),
    ("huggingface_hub", "huggingface_hub>=0.23"),
    ("packaging", "packaging>=23.0"),
]


OPTIONAL_PACKAGES = [
    (
        "pdfminer",
        "pdfminer.six>=20221105",
        "Full PDF text extraction from ArXiv",
    ),
]


MIN_PYTHON = (3, 10)


# ---------------------------------------------------------------------------
# Canonical root
# ---------------------------------------------------------------------------

def project_root() -> Path:
    """
    Return the directory containing bootstrap.py.

    This is intentionally independent of the caller's current directory.
    The project must never accidentally resolve itself as:

        pretrain-pipeline/pretrain-pipeline

    or any other nesting variant.
    """
    return Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def _run(
    cmd: list[str],
    cwd: str | Path | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    printable = " ".join(str(x) for x in cmd)
    log.info("$ %s", printable)

    result = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=capture,
    )

    if check and result.returncode != 0:
        if capture:
            if result.stdout:
                log.error(result.stdout.rstrip())
            if result.stderr:
                log.error(result.stderr.rstrip())

        log.error("Command failed (exit %s)", result.returncode)
        raise SystemExit(result.returncode)

    return result


def _pip_install(packages: list[str]) -> None:
    if not packages:
        return

    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
        ]
        + packages
    )


def _is_importable(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _disk_free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


# ---------------------------------------------------------------------------
# GPU / CUDA detection
# ---------------------------------------------------------------------------

def _find_nvidia_smi() -> str | None:
    candidates = [
        shutil.which("nvidia-smi"),
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)

    return None


def _nvidia_hardware() -> dict:
    smi = _find_nvidia_smi()

    if not smi:
        return {
            "available": False,
            "name": None,
            "vram_gb": 0.0,
            "driver": None,
            "path": None,
        }

    try:
        result = subprocess.run(
            [
                smi,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return {
                "available": False,
                "name": None,
                "vram_gb": 0.0,
                "driver": None,
                "path": smi,
            }

        line = result.stdout.strip().splitlines()[0]
        fields = [x.strip() for x in line.split(",")]

        name = fields[0] if fields else "NVIDIA GPU"

        vram_gb = 0.0
        if len(fields) > 1:
            raw_vram = fields[1].replace("MiB", "").strip()
            try:
                vram_gb = float(raw_vram) / 1024.0
            except ValueError:
                pass

        driver = fields[2] if len(fields) > 2 else None

        return {
            "available": True,
            "name": name,
            "vram_gb": vram_gb,
            "driver": driver,
            "path": smi,
        }

    except Exception as exc:
        log.warning("nvidia-smi probe failed: %s", exc)

        return {
            "available": False,
            "name": None,
            "vram_gb": 0.0,
            "driver": None,
            "path": smi,
        }


def _torch_cuda() -> dict:
    """
    Inspect CUDA capability of the ACTUAL Python interpreter running
    bootstrap.py.

    This deliberately distinguishes:

        torch installed
        torch CUDA build
        CUDA runtime available
        physical NVIDIA GPU

    These are not the same thing. Apparently humanity needed all four.
    """

    try:
        import torch

        torch_version = getattr(torch, "__version__", "unknown")
        cuda_version = getattr(
            getattr(torch, "version", None),
            "cuda",
            None,
        )

        available = bool(torch.cuda.is_available())

        device_name = None
        device_count = 0

        if available:
            device_count = torch.cuda.device_count()

            if device_count:
                device_name = torch.cuda.get_device_name(0)

        return {
            "installed": True,
            "version": torch_version,
            "cuda_version": cuda_version,
            "available": available,
            "device_count": device_count,
            "device_name": device_name,
            "path": getattr(torch, "__file__", None),
        }

    except Exception as exc:
        return {
            "installed": False,
            "version": None,
            "cuda_version": None,
            "available": False,
            "device_count": 0,
            "device_name": None,
            "path": None,
            "error": str(exc),
        }


def _gpu_info() -> dict:
    hardware = _nvidia_hardware()
    torch_state = _torch_cuda()

    return {
        "hardware": hardware,
        "torch": torch_state,
        "available": torch_state["available"],
        "name": (
            torch_state["device_name"]
            or hardware["name"]
            or "CPU only"
        ),
        "vram_gb": hardware["vram_gb"],
    }


# ---------------------------------------------------------------------------
# Environment checks
# ---------------------------------------------------------------------------

def check_python() -> None:
    v = sys.version_info

    if (v.major, v.minor) < MIN_PYTHON:
        log.error(
            "Python %s.%s+ required, got %s.%s.%s",
            MIN_PYTHON[0],
            MIN_PYTHON[1],
            v.major,
            v.minor,
            v.micro,
        )
        raise SystemExit(1)

    log.info(
        "Python %s.%s.%s ✓",
        v.major,
        v.minor,
        v.micro,
    )

    log.info("Interpreter: %s", sys.executable)


def check_git() -> bool:
    path = shutil.which("git")

    if path is None:
        log.error("git not found.")
        return False

    log.info("git: %s ✓", path)
    return True


def check_cmake() -> bool:
    path = shutil.which("cmake")

    if path is None:
        log.warning(
            "cmake not found. GGUF export cannot build llama.cpp "
            "components automatically."
        )
        return False

    log.info("cmake: %s ✓", path)
    return True


def check_disk(work_dir: Path, min_gb: float = 20.0) -> None:
    free = _disk_free_gb(work_dir)

    if free < min_gb:
        log.warning(
            "Only %.1f GB free in %s. Recommended minimum: %.1f GB.",
            free,
            work_dir,
            min_gb,
        )
    else:
        log.info(
            "Disk: %.1f GB free ✓",
            free,
        )


def check_gpu() -> dict:
    info = _gpu_info()

    hardware = info["hardware"]
    torch_state = info["torch"]

    if hardware["available"]:
        log.info(
            "GPU hardware: %s (%.1f GB VRAM) ✓",
            hardware["name"],
            hardware["vram_gb"],
        )

        if hardware["driver"]:
            log.info(
                "NVIDIA driver: %s",
                hardware["driver"],
            )
    else:
        log.warning(
            "No NVIDIA GPU hardware detected through nvidia-smi."
        )

    if not torch_state["installed"]:
        log.error(
            "PyTorch is not importable from the active interpreter."
        )
        return info

    log.info(
        "PyTorch: %s",
        torch_state["version"],
    )

    if torch_state["cuda_version"]:
        log.info(
            "PyTorch CUDA build: %s",
            torch_state["cuda_version"],
        )
    else:
        log.info(
            "PyTorch CUDA build: NONE (CPU-only build)"
        )

    if torch_state["available"]:
        log.info(
            "PyTorch CUDA: AVAILABLE ✓"
        )

        if torch_state["device_name"]:
            log.info(
                "PyTorch CUDA device: %s",
                torch_state["device_name"],
            )

    elif hardware["available"]:
        log.warning(
            "NVIDIA GPU hardware is present, but PyTorch CUDA "
            "is UNAVAILABLE in the active Python environment."
        )

        log.warning(
            "Active torch: %s",
            torch_state["path"],
        )

        log.warning(
            "This is a CPU-only or otherwise non-CUDA-capable "
            "PyTorch installation."
        )

        log.warning(
            "Training will use CPU until the active interpreter "
            "has a CUDA-capable PyTorch installation."
        )

    else:
        log.warning(
            "Training will use CPU."
        )

    return info


# ---------------------------------------------------------------------------
# Dependency reconciliation
# ---------------------------------------------------------------------------

def install_dependencies(force: bool = False) -> None:
    missing: list[str] = []

    for import_name, package_spec in REQUIRED_PACKAGES:
        if force or not _is_importable(import_name):
            missing.append(package_spec)

    if missing:
        log.info(
            "Installing missing Python packages: %s",
            ", ".join(missing),
        )
        _pip_install(missing)
    else:
        log.info(
            "All required Python packages import successfully ✓"
        )

    for import_name, package_spec, description in OPTIONAL_PACKAGES:
        if not _is_importable(import_name):
            log.info(
                "Optional package unavailable: %s (%s)",
                package_spec,
                description,
            )


# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------

def ensure_dirs(base: Path) -> None:
    """
    Create only directories belonging to the canonical project.

    Nothing here creates another pretrain-pipeline directory.
    """

    dirs = [
        base / "config",

        base / "output",
        base / "output" / "logs",
        base / "output" / "checkpoints",
        base / "output" / "tokenizer",
        base / "output" / "shards",
        base / "output" / "gguf",
        base / "output" / "hf_export",

        base / "scratch",

        base / "scripts",

        base / "pipeline",
        base / "pipeline" / "trainer",
    ]

    for directory in dirs:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    log.info(
        "Directory structure ✓"
    )


# ---------------------------------------------------------------------------
# Seed URLs
# ---------------------------------------------------------------------------

def write_seed_urls(
    urls: list[str],
    path: Path,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    existing: list[str] = []
    existing_set: set[str] = set()

    if path.exists():
        for line in path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if line not in existing_set:
                existing.append(line)
                existing_set.add(line)

    new_urls: list[str] = []

    for url in urls:
        url = url.strip()

        if not url:
            continue

        if url not in existing_set:
            existing_set.add(url)
            new_urls.append(url)

    if not new_urls:
        if existing:
            log.info(
                "Seed URLs already present in %s (%d total)",
                path,
                len(existing),
            )
        return

    mode = "a" if path.exists() else "w"

    with path.open(
        mode,
        encoding="utf-8",
        newline="\n",
    ) as handle:
        if not existing:
            handle.write(
                "# Seed URLs - one per line\n"
            )

        for url in new_urls:
            handle.write(url + "\n")

    log.info(
        "Seed URLs: %d total (%d added) -> %s",
        len(existing) + len(new_urls),
        len(new_urls),
        path,
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def patch_config(
    cfg_path: Path,
    overrides: dict[str, object],
) -> None:
    import yaml

    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Pipeline configuration does not exist: {cfg_path}"
        )

    with cfg_path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        raw = yaml.safe_load(handle) or {}

    def deep_set(
        data: dict,
        keys: list[str],
        value: object,
    ) -> None:
        current = data

        for key in keys[:-1]:
            child = current.get(key)

            if not isinstance(child, dict):
                child = {}
                current[key] = child

            current = child

        current[keys[-1]] = value

    for dotkey, value in overrides.items():
        deep_set(
            raw,
            dotkey.split("."),
            value,
        )

    with cfg_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as handle:
        yaml.safe_dump(
            raw,
            handle,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

    log.info(
        "Config updated: %s",
        overrides,
    )


def patch_config_lines(
    cfg_path: Path,
    replacements: dict[str, str],
) -> None:
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Pipeline configuration does not exist: {cfg_path}"
        )

    text = cfg_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    changed = False

    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)
            changed = True

            log.info(
                "Config patch: %r -> %r",
                old,
                new,
            )

    if changed:
        cfg_path.write_text(
            text,
            encoding="utf-8",
            newline="\n",
        )


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------

def stages_from(start: str) -> list[str]:
    if start not in STAGE_ORDER:
        log.error(
            "Unknown stage '%s'. Options: %s",
            start,
            ", ".join(STAGE_ORDER),
        )
        raise SystemExit(1)

    index = STAGE_ORDER.index(start)

    return STAGE_ORDER[index:]


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight_summary(
    args,
    gpu: dict,
    base: Path,
) -> None:
    cfg_path = (
        base
        / "config"
        / "pipeline_config.yaml"
    )

    if not cfg_path.exists():
        log.error(
            "Pipeline config missing: %s",
            cfg_path,
        )
        raise SystemExit(1)

    import yaml

    with cfg_path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        cfg = yaml.safe_load(handle) or {}

    train = cfg.get("train", {})

    preset = train.get(
        "model_preset",
        "117M",
    )

    steps = int(
        train.get(
            "total_steps",
            100000,
        )
    )

    batch = int(
        train.get(
            "batch_size",
            1,
        )
    )

    accum = int(
        train.get(
            "grad_accum_steps",
            16,
        )
    )

    seq = int(
        train.get(
            "seq_len",
            1024,
        )
    )

    effective_tokens = batch * accum * seq

    params = 0

    try:
        from pipeline.trainer.model import ModelConfig

        model_config = ModelConfig.from_preset(
            preset
        )

        params = model_config.param_count()

    except Exception:
        pass

    seed_path = (
        base
        / "config"
        / "seed_urls.txt"
    )

    seed_count = 0

    if seed_path.exists():
        seed_count = sum(
            1
            for line in seed_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
            if line.strip()
            and not line.strip().startswith("#")
        )

    hardware = gpu["hardware"]
    torch_state = gpu["torch"]

    print()
    print("=" * 64)
    print("  PRE-FLIGHT SUMMARY")
    print("=" * 64)

    print(
        f"  Project root   : {base}"
    )

    print(
        f"  Interpreter    : {sys.executable}"
    )

    print(
        f"  Model preset   : {preset}"
        + (
            f" (~{params / 1e6:.0f}M params)"
            if params
            else ""
        )
    )

    print(
        f"  Total steps    : {steps:,}"
    )

    print(
        f"  Effective batch: {effective_tokens:,} tokens/step"
    )

    print(
        f"  Total tokens   : "
        f"~{steps * effective_tokens / 1e9:.2f}B"
    )

    if hardware["available"]:
        print(
            f"  GPU hardware   : "
            f"{hardware['name']} "
            f"({hardware['vram_gb']:.1f} GB)"
        )
    else:
        print(
            "  GPU hardware   : none detected"
        )

    if torch_state["available"]:
        print(
            f"  CUDA training  : AVAILABLE "
            f"({torch_state['device_name']})"
        )
    elif torch_state["installed"]:
        print(
            f"  CUDA training  : UNAVAILABLE "
            f"(torch {torch_state['version']})"
        )
    else:
        print(
            "  CUDA training  : UNAVAILABLE "
            "(PyTorch import failed)"
        )

    print(
        f"  Seed URLs      : {seed_count}"
    )

    print(
        f"  Output dir     : {base / 'output'}"
    )

    print(
        f"  Config         : {cfg_path}"
    )

    print("=" * 64)

    if torch_state["available"]:
        tok_per_sec = 2000
        mode = "CUDA"
    elif hardware["available"]:
        tok_per_sec = 50
        mode = "CPU / CUDA unavailable"
    else:
        tok_per_sec = 50
        mode = "CPU"

    eta_hours = (
        steps
        * effective_tokens
        / tok_per_sec
        / 3600
    )

    print()
    print(
        f"  Estimated training time: "
        f"~{eta_hours:.0f}h ({mode})"
    )

    print()

    if not args.yes:
        answer = input(
            "  Continue? [y/N] "
        ).strip().lower()

        if answer != "y":
            print("Aborted.")
            raise SystemExit(0)


# ---------------------------------------------------------------------------
# Environment reconciliation
# ---------------------------------------------------------------------------

def reconcile_environment(
    base: Path,
) -> None:
    reconciler = (
        base
        / "scripts"
        / "reconcile_environment.py"
    )

    if not reconciler.exists():
        log.error(
            "Environment reconciler missing: %s",
            reconciler,
        )
        raise SystemExit(1)

    log.info(
        "Reconciling execution environment ..."
    )

    command = [
        sys.executable,
        str(reconciler),
        "--project-root",
        str(base),
        "--ensure-llamacpp",
    ]

    result = subprocess.run(
        command,
        cwd=str(base),
        check=False,
    )

    if result.returncode != 0:
        log.error(
            "Environment reconciliation failed."
        )
        log.error(
            "Refusing to start the pipeline."
        )
        raise SystemExit(
            result.returncode
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(BANNER)

    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap and run the full "
            "pretrain pipeline end-to-end."
        ),
        formatter_class=(
            argparse.RawDescriptionHelpFormatter
        ),
        epilog=textwrap.dedent(
            """
            Examples:

              Full run:
                python bootstrap.py

              Custom seeds:
                python bootstrap.py --seeds "https://arxiv.org/list/cs.AI/recent,https://docs.python.org/3/"

              Seeds file:
                python bootstrap.py --seeds-file my_seeds.txt

              Model:
                python bootstrap.py --model 360M --steps 200000

              Resume:
                python bootstrap.py --stage-from clean

              Environment only:
                python bootstrap.py --check-only

              Force dependency reinstall:
                python bootstrap.py --force-reinstall
            """
        ),
    )

    parser.add_argument(
        "--seeds",
        default="",
        help=(
            "Comma-separated seed URLs to add "
            "to config/seed_urls.txt"
        ),
    )

    parser.add_argument(
        "--seeds-file",
        default="",
        help=(
            "Path to a text file containing "
            "seed URLs, one per line"
        ),
    )

    parser.add_argument(
        "--model",
        default="117M",
        choices=[
            "85M",
            "117M",
            "360M",
        ],
        help=(
            "Model size preset. Default: 117M."
        ),
    )

    parser.add_argument(
        "--steps",
        type=int,
        default=0,
        help=(
            "Total training steps. "
            "Default: value from config."
        ),
    )

    parser.add_argument(
        "--quant",
        default="Q4_K_M",
        help=(
            "GGUF quantization type."
        ),
    )

    parser.add_argument(
        "--model-name",
        default="pretrain-model",
        help=(
            "Ollama model name."
        ),
    )

    parser.add_argument(
        "--stage-from",
        default="",
        help=(
            "Start from this pipeline stage."
        ),
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help=(
            "Verify environment and exit."
        ),
    )

    parser.add_argument(
        "--no-resume",
        action="store_true",
        help=(
            "Disable pipeline resume behavior."
        ),
    )

    parser.add_argument(
        "--force-reinstall",
        action="store_true",
        help=(
            "Reinstall declared Python packages."
        ),
    )

    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Skip confirmation prompt."
        ),
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=[
            "DEBUG",
            "INFO",
            "WARNING",
        ],
    )

    args = parser.parse_args()

    logging.getLogger().setLevel(
        getattr(
            logging,
            args.log_level,
        )
    )

    # ---------------------------------------------------------------
    # CANONICAL ROOT
    # ---------------------------------------------------------------

    base = project_root()

    os.chdir(base)

    if str(base) not in sys.path:
        sys.path.insert(
            0,
            str(base),
        )

    log.info(
        "Canonical project root: %s",
        base,
    )

    # Explicit nesting guard.
    nested = base / "pretrain-pipeline"

    if nested.exists():
        log.error(
            "NESTED PROJECT DIRECTORY DETECTED:"
        )
        log.error(
            "  %s",
            nested,
        )
        log.error(
            "Bootstrap refuses to continue."
        )
        log.error(
            "The canonical root is:"
        )
        log.error(
            "  %s",
            base,
        )
        raise SystemExit(2)

    # ---------------------------------------------------------------
    # Environment
    # ---------------------------------------------------------------

    reconcile_environment(base)

    check_python()

    if not check_git():
        raise SystemExit(1)

    cmake_available = check_cmake()

    check_disk(base)

    gpu = check_gpu()

    # ---------------------------------------------------------------
    # Dependencies
    # ---------------------------------------------------------------

    if args.force_reinstall:
        log.info(
            "--force-reinstall requested."
        )

        _pip_install(
            [
                spec
                for _, spec in REQUIRED_PACKAGES
            ]
        )

    else:
        install_dependencies()

    # ---------------------------------------------------------------
    # Check-only exits here.
    # ---------------------------------------------------------------

    if args.check_only:
        log.info(
            "Environment check complete."
        )

        if gpu["hardware"]["available"] and not gpu["torch"]["available"]:
            log.warning(
                "CHECK RESULT: GPU hardware exists, "
                "but the active PyTorch installation "
                "cannot use CUDA."
            )

        return

    # ---------------------------------------------------------------
    # CMake is required for export.
    # ---------------------------------------------------------------

    if not cmake_available:
        log.error(
            "CMake is required for the export stage."
        )
        raise SystemExit(1)

    # ---------------------------------------------------------------
    # Directory structure
    # ---------------------------------------------------------------

    ensure_dirs(base)

    # ---------------------------------------------------------------
    # Seed URLs
    # ---------------------------------------------------------------

    seed_path = (
        base
        / "config"
        / "seed_urls.txt"
    )

    urls: list[str] = []

    if args.seeds:
        urls.extend(
            [
                url.strip()
                for url in args.seeds.split(",")
                if url.strip()
            ]
        )

    if args.seeds_file:
        seed_file = Path(
            args.seeds_file
        ).expanduser().resolve()

        if not seed_file.exists():
            log.error(
                "Seeds file not found: %s",
                seed_file,
            )
            raise SystemExit(1)

        for line in seed_file.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():

            line = line.strip()

            if (
                line
                and not line.startswith("#")
            ):
                urls.append(line)

    if urls:
        write_seed_urls(
            urls,
            seed_path,
        )

    elif not seed_path.exists():
        log.warning(
            "No seed URLs provided and "
            "config/seed_urls.txt does not exist."
        )

        log.info(
            "Creating default seed set."
        )

        write_seed_urls(
            [
                "https://arxiv.org/list/cs.AI/recent",
                "https://arxiv.org/list/cs.LG/recent",
                "https://en.wikipedia.org/wiki/Portal:Mathematics",
                "https://en.wikipedia.org/wiki/Portal:Computer_science",
                "https://stackoverflow.com/questions?tab=votes&pagesize=50",
                "https://docs.python.org/3/",
                "https://developer.mozilla.org/en-US/docs/Web",
                "https://paulgraham.com/articles.html",
            ],
            seed_path,
        )

    # ---------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------

    cfg_path = (
        base
        / "config"
        / "pipeline_config.yaml"
    )

    if not cfg_path.exists():
        log.error(
            "Pipeline configuration missing:"
        )
        log.error(
            "  %s",
            cfg_path,
        )
        raise SystemExit(1)

    replacements: dict[str, str] = {}

    if args.model != "117M":
        replacements[
            '  model_preset: "117M"'
        ] = (
            f'  model_preset: "{args.model}"'
        )

    if args.steps:
        replacements[
            "  total_steps: 100000"
        ] = (
            f"  total_steps: {args.steps}"
        )

    if args.quant != "Q4_K_M":
        replacements[
            '  quant: "Q4_K_M"'
        ] = (
            f'  quant: "{args.quant}"'
        )

    if args.model_name != "pretrain-model":
        replacements[
            '  model_name: "pretrain-model"'
        ] = (
            f'  model_name: "{args.model_name}"'
        )

    if replacements:
        patch_config_lines(
            cfg_path,
            replacements,
        )

    # ---------------------------------------------------------------
    # GPU tuning
    # ---------------------------------------------------------------

    hardware = gpu["hardware"]
    torch_state = gpu["torch"]

    if torch_state["available"]:
        vram = hardware["vram_gb"]

        log.info(
            "CUDA training path is active."
        )

        if vram < 4.0:
            if args.model == "360M":
                log.warning(
                    "360M selected with <4GB VRAM."
                )

                patch_config_lines(
                    cfg_path,
                    {
                        "  batch_size: 1":
                            "  batch_size: 1",
                        "  grad_accum_steps: 16":
                            "  grad_accum_steps: 32",
                    },
                )

            else:
                log.info(
                    "4GB-class GPU detected. "
                    "Keeping conservative batch settings."
                )

    elif hardware["available"]:
        log.warning(
            "NVIDIA hardware detected but "
            "CUDA training is unavailable."
        )

        log.warning(
            "No fake CUDA success will be reported."
        )

        if args.model == "117M":
            log.warning(
                "CPU fallback: reducing model preset to 85M."
            )

            patch_config_lines(
                cfg_path,
                {
                    '  model_preset: "117M"':
                        '  model_preset: "85M"',
                },
            )

    else:
        log.warning(
            "CPU-only environment."
        )

        if args.model == "117M":
            log.warning(
                "Reducing model preset to 85M "
                "for CPU execution."
            )

            patch_config_lines(
                cfg_path,
                {
                    '  model_preset: "117M"':
                        '  model_preset: "85M"',
                },
            )

    # ---------------------------------------------------------------
    # Preflight
    # ---------------------------------------------------------------

    preflight_summary(
        args,
        gpu,
        base,
    )

    # ---------------------------------------------------------------
    # Stages
    # ---------------------------------------------------------------

    if args.stage_from:
        run_stages = stages_from(
            args.stage_from
        )

        log.info(
            "Starting from stage: %s",
            args.stage_from,
        )

        log.info(
            "Will run: %s",
            run_stages,
        )

    else:
        run_stages = STAGE_ORDER

    # ---------------------------------------------------------------
    # Pipeline
    # ---------------------------------------------------------------

    try:
        from pipeline.orchestrator import Pipeline

    except Exception as exc:
        log.error(
            "Unable to import pipeline orchestrator."
        )
        log.error(
            "Project root: %s",
            base,
        )
        log.error(
            "Import error: %s",
            exc,
        )
        raise

    pipeline = Pipeline(
        str(cfg_path)
    )

    if args.no_resume:
        pipeline._resume = False

    total_start = time.time()
    failed_stage: str | None = None

    for stage in run_stages:

        log.info("")
        log.info(
            "=" * 64
        )
        log.info(
            "  STAGE: %s",
            stage.upper(),
        )
        log.info(
            "=" * 64
        )
        log.info("")

        stage_start = time.time()

        try:
            pipeline.run(stage)

        except KeyboardInterrupt:
            log.warning(
                "Pipeline interrupted by user."
            )

            log.info(
                "Progress should remain resumable."
            )

            log.info(
                "Resume with:"
            )

            log.info(
                "  python bootstrap.py --stage-from %s",
                stage,
            )

            raise SystemExit(130)

        except Exception as exc:
            log.error(
                "Stage '%s' failed: %s",
                stage,
                exc,
                exc_info=True,
            )

            log.error(
                "Fix the error and resume with:"
            )

            log.error(
                "  python bootstrap.py --stage-from %s",
                stage,
            )

            failed_stage = stage
            break

        elapsed = (
            time.time()
            - stage_start
        )

        log.info(
            "Stage '%s' completed in %.1f minutes.",
            stage,
            elapsed / 60.0,
        )

    # ---------------------------------------------------------------
    # Final summary
    # ---------------------------------------------------------------

    elapsed_total = (
        time.time()
        - total_start
    )

    print()
    print("=" * 64)

    if failed_stage:
        print(
            "  PIPELINE INCOMPLETE"
        )
        print(
            f"  Failed stage: {failed_stage}"
        )

    else:
        print(
            "  PIPELINE COMPLETE"
        )

    print(
        f"  Total time: {elapsed_total / 3600:.2f}h"
    )

    gguf_dir = (
        base
        / "output"
        / "gguf"
    )

    if gguf_dir.exists():
        ggufs = sorted(
            gguf_dir.glob("*.gguf"),
            key=lambda p: p.stat().st_mtime,
        )

        if ggufs:
            quantized = [
                item
                for item in ggufs
                if "f16" not in item.name.lower()
            ]

            final = (
                quantized[-1]
                if quantized
                else ggufs[-1]
            )

            size_mb = (
                final.stat().st_size
                / 1024
                / 1024
            )

            print()
            print(
                f"  GGUF ready: {final}"
            )

            print(
                f"  Size: {size_mb:.0f} MB"
            )

            print()
            print(
                "  Load in Ollama:"
            )

            print(
                f"    ollama create "
                f"{args.model_name} "
                f"-f "
                f"{gguf_dir / 'Modelfile'}"
            )

            print(
                f"    ollama run "
                f"{args.model_name}"
            )

        else:
            print()
            print(
                "  GGUF: not produced yet"
            )

    else:
        print()
        print(
            "  GGUF directory does not exist yet."
        )

    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
