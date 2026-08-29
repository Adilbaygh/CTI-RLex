"""Record the machine and software stack that produced the reported solve times.

Reviewer item 4.5: the manuscript reported runtimes "on the current workstation", which
cannot be compared against a rerun. This script writes the processor, memory, operating
system and the exact Python, NumPy, SciPy and HiGHS versions to results/environment.json,
and prints the one sentence to paste into Section 2.7 of the manuscript.

Run once on the machine that produced the timings:

    python scripts/record_environment.py
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "results" / "environment.json"


def processor_name() -> str:
    """A readable CPU name.

    ``platform.processor()`` returns a family/model string on Windows, and shelling out to
    wmic breaks on any console whose code page is not UTF-8, so the value is read from the
    registry there and from the kernel elsewhere.
    """

    system = platform.system()
    try:
        if system == "Windows":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            with key:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if name:
                return " ".join(str(name).split())
        elif system == "Darwin":
            return subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, errors="replace", timeout=20,
            ).stdout.strip()
        elif system == "Linux":
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine() or "unknown"


def memory_gib() -> float | None:
    """Installed physical memory, without shelling out to a localized command."""

    try:
        if platform.system() == "Windows":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return round(status.ullTotalPhys / 1024**3, 1)
            return None
        import os

        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
    except Exception:
        return None


def logical_cores() -> int | None:
    try:
        import os

        return os.cpu_count()
    except Exception:
        return None


def solver_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {"numpy": None, "scipy": None, "highs": None}
    try:
        import numpy

        versions["numpy"] = numpy.__version__
    except Exception:
        pass
    try:
        import scipy

        versions["scipy"] = scipy.__version__
        try:
            from scipy.optimize._highs import _highs_wrapper  # noqa: F401

            versions["highs"] = "bundled with SciPy " + scipy.__version__
        except Exception:
            versions["highs"] = "bundled with SciPy " + scipy.__version__
    except Exception:
        pass
    return versions


def main() -> None:
    versions = solver_versions()
    record = {
        "recorded_on": date.today().isoformat(),
        "processor": processor_name(),
        "logical_cores": logical_cores(),
        "memory_gib": memory_gib(),
        "operating_system": f"{platform.system()} {platform.release()}",
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "python_build": platform.python_implementation(),
        "numpy": versions["numpy"],
        "scipy": versions["scipy"],
        "linear_solver": "HiGHS via scipy.optimize.linprog(method='highs')",
        "highs": versions["highs"],
        "solver_options": "SciPy defaults; presolve on; no thread count set",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(record, indent=1), encoding="utf-8")

    details = []
    if record["logical_cores"]:
        details.append(f"{record['logical_cores']} logical cores")
    if record["memory_gib"]:
        details.append(f"{record['memory_gib']} GiB of memory")
    hardware = f" ({', '.join(details)})" if details else ""
    article = "an" if record["processor"][:1].upper() in "AEIOU" else "a"
    print(json.dumps(record, indent=1))
    print("\nwrote", OUTPUT)
    print("\nSentence for Section 2.7:\n")
    print(
        f"All solve times were measured on {article} {record['processor']}{hardware}, "
        f"running {record['operating_system']}, with Python {record['python']}, NumPy "
        f"{record['numpy']} and SciPy {record['scipy']}, solving each linear program with "
        f"HiGHS through scipy.optimize.linprog at its default options."
    )


if __name__ == "__main__":
    main()
