"""Background solver workers with no dependency on project working folders."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from PyQt6.QtCore import QThread, pyqtSignal

from leximin.dag.analysis import AnalysisCancelled

from .i18n import DEFAULT_LANGUAGE, normalize_language, pick


def localized_progress(message: str, language: str) -> str:
    if normalize_language(language) == "en":
        return message
    prefixes = {
        "Method completed: ": "Усул якунланди: ",
        "Source ablation completed: ": "Манба абляцияси якунланди: ",
        "Recourse frontier completed: scale ": "Қайта мослашув фронти якунланди: масштаб ",
        "Sensitivity case ": "Сезгирлик ҳолати ",
    }
    exact = {
        "Terminal representation invariance completed": "Терминал тасвирининг инвариантлик аудити якунланди",
        "Scalability audit completed": "Масштабланиш аудити якунланди",
        "Effectiveness indicators completed": "Самарадорлик кўрсаткичлари ҳисобланди",
    }
    if message in exact:
        return exact[message]
    for source, target in prefixes.items():
        if message.startswith(source):
            return target + message[len(source) :]
    return message


class SolveWorker(QThread):
    completed = pyqtSignal(dict, float)
    failed = pyqtSignal(str)

    def __init__(self, benchmark: Path) -> None:
        super().__init__()
        self.benchmark = benchmark

    def run(self) -> None:
        try:
            from leximin.dag import load_cti_benchmark, solve_cti_rlex

            started = perf_counter()
            model = load_cti_benchmark(self.benchmark)
            solution = solve_cti_rlex(model)
            runtime = perf_counter() - started
            payload = solution.to_dict()
            payload["solver"] = {
                "method": "SciPy HiGHS linear programming with progressive filling",
                "fairness_unit": "claimant aggregate across terminal records",
                "guarantee_scope": "every positive-demand period and every scenario",
            }
            self.completed.emit(payload, runtime)
        except Exception as exc:  # noqa: BLE001 - displayed in the GUI
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class FullAnalysisWorker(QThread):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, benchmark: Path, language: str = DEFAULT_LANGUAGE) -> None:
        super().__init__()
        self.benchmark = benchmark
        self.language = normalize_language(language)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            from leximin.dag import load_cti_benchmark, run_full_analysis
            from leximin.gui.data import load_benchmark_document

            raw = load_benchmark_document(self.benchmark, self.language)
            model = load_cti_benchmark(self.benchmark)

            def report(current: int, total: int, message: str) -> None:
                self.progress.emit(round(100 * current / max(total, 1)))
                self.log_line.emit(localized_progress(message, self.language))

            result = run_full_analysis(
                model,
                raw,
                progress=report,
                cancelled=lambda: self._cancelled,
            )
            self.completed.emit(result)
        except AnalysisCancelled as exc:
            self.failed.emit(
                pick(
                    self.language,
                    "Таҳлил фойдаланувчи томонидан бекор қилинди.",
                    str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001 - displayed in the GUI
            self.failed.emit(f"{type(exc).__name__}: {exc}")
