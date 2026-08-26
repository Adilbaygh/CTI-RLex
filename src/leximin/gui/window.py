"""Standalone benchmark-driven desktop interface for CTI-RLex."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSettings, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .charts import ChartStore
from .i18n import normalize_language, pick
from .data import (
    ProjectPaths,
    allocation_table,
    base_result_tables,
    benchmark_counts,
    claimant_table,
    load_benchmark_document,
    method_table,
    recourse_table,
    rows_from_dicts,
    scenario_table,
    sensitivity_main_effects,
    sensitivity_range,
    source_table,
)
from .widgets import (
    AvailabilityPanel,
    Card,
    FigureTile,
    ImagePanel,
    MetricCard,
    Notice,
    PageHeader,
    TablePanel,
    make_page,
    open_figure_dialog,
)
from .workers import FullAnalysisWorker, SolveWorker


CHART_INFO = {
    "network": (
        ("Benchmark тармоқ топологияси", "Benchmark network topology"),
        (
            "Манбалар, йўналтирилган қирралар ва талабгор терминаллари benchmark маълумотларидан қурилди.",
            "Sources, directed edges and claimant terminals reconstructed from the benchmark.",
        ),
    ),
    "guarantees": (
        ("Талабгорларнинг робаст кафолатлари", "Claimant robust guarantees"),
        (
            "Ҳар бир талабгор учун барча мусбат талабли давр ва сценарийлардаги минимал хизмат нисбати.",
            "Minimum service ratio for each claimant across all positive-demand periods and scenarios.",
        ),
    ),
    "methods": (
        ("Самарадорлик–адолат таққосланиши", "Efficiency–fairness comparison"),
        (
            "Номинал фойдали етказиш ва минимал робаст кафолат бўйича ечувчи конфигурациялари.",
            "Solver configurations compared by nominal beneficial delivery and minimum robust guarantee.",
        ),
    ),
    "recourse": (
        ("Қайта мослашув фронти", "Recourse frontier"),
        (
            "Операцион қайта мослашув бюджети ўзгарганда кафолат вектори ва қайта конфигурация сарфи.",
            "Guarantee vector and reconfiguration effort as the operational recourse budget changes.",
        ),
    ),
    "service": (
        ("Сценарий–давр хизмат матрицаси", "Scenario–period service matrix"),
        (
            "Барча талабгор, сценарий ва даврлар бўйича етказилган сувнинг талабга нисбати.",
            "Delivered-to-demand ratio for every claimant, scenario and period.",
        ),
    ),
    "source_balance": (
        ("Манбалар фаоллиги ва сув баланси", "Source activation and water balance"),
        (
            "Мавсумий манба оқими, фойдали етказиш ва моделланган йўқотишлар.",
            "Seasonal source injection, beneficial delivery and modeled losses.",
        ),
    ),
    "source_ablation": (
        ("Манбалар критиклиги", "Source criticality"),
        (
            "Ҳар бир манба ўчирилганда минимал робаст кафолатнинг ўзгариши.",
            "Change in the minimum robust guarantee when each source is disabled.",
        ),
    ),
    "sensitivity": (
        ("Робастлик сезгирлиги", "Robustness sensitivity"),
        (
            "Benchmarkдаги тўлиқ факторли ҳолатларнинг тавсифий асосий таъсирлари.",
            "Descriptive main effects from the full-factorial cases supplied by the benchmark.",
        ),
    ),
    "scalability": (
        ("Ҳисоблаш масштабланиши", "Computational scalability"),
        (
            "Сценарийлар сони ортишида LP ўзгарувчилари ва медиан ҳисоблаш вақтининг ўзгариши.",
            "LP variable count and median runtime as the number of scenarios increases.",
        ),
    ),
}


def chart_info(key: str, language: str) -> tuple[str, str]:
    title, caption = CHART_INFO[key]
    return pick(language, title[0], title[1]), pick(language, caption[0], caption[1])


class AnalysisProgressDialog(QDialog):
    cancel_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, language: str = "uz") -> None:
        super().__init__(parent)
        self.language = normalize_language(language)
        self.setWindowTitle(
            pick(self.language, "CTI-RLex кенгайтирилган таҳлили", "CTI-RLex extended analysis")
        )
        self.setModal(False)
        self.resize(760, 510)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 17, 18, 17)
        layout.setSpacing(10)
        title = QLabel(
            pick(
                self.language,
                "Benchmark самарадорлиги ва робастлиги таҳлили",
                "Benchmark effectiveness and robustness analysis",
            )
        )
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            pick(
                self.language,
                "Таянч усуллар, манбалар абляцияси, қайта мослашув фронти, сезгирлик, "
                "тасвирлаш инвариантлиги ва масштабланиш фон режимида ҳисобланмоқда.",
                "Baseline methods, source ablation, recourse frontier, sensitivity, "
                "representation invariance and scalability are running in the background.",
            )
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.button = QPushButton(pick(self.language, "Бекор қилиш", "Cancel"))
        self.button.setObjectName("GhostButton")
        self.button.clicked.connect(self._button_clicked)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.progress)
        layout.addWidget(self.log, 1)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignRight)
        self._finished = False

    def append_log(self, line: str) -> None:
        self.log.append(line)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def mark_finished(self, success: bool) -> None:
        self._finished = True
        if success:
            self.progress.setValue(100)
        self.button.setText(pick(self.language, "Ёпиш", "Close"))
        self.button.setEnabled(True)

    def _button_clicked(self) -> None:
        if self._finished:
            self.close()
        else:
            self.cancel_requested.emit()
            self.button.setEnabled(False)
            self.append_log(
                pick(
                    self.language,
                    "Бекор қилиш сўрови юборилди; жорий LP ечими тугагач тўхтайди…",
                    "Cancellation requested; processing will stop after the current LP solve…",
                )
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._finished:
            self.cancel_requested.emit()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(
        self,
        paths: ProjectPaths,
        initial_benchmark: Path | None = None,
        auto_load: bool = True,
        language: str | None = None,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.settings = QSettings("Leximin Research", "CTI-RLex Studio")
        self.language = normalize_language(
            language if language is not None else self.settings.value("ui_language", "en")
        )
        self.chart_store = ChartStore()
        self.chart_paths: dict[str, Path] = {}
        self.current_benchmark: Path | None = None
        self.benchmark_raw: dict[str, Any] | None = None
        self.base_result: dict[str, Any] | None = None
        self.full_analysis: dict[str, Any] | None = None
        self.solve_worker: SolveWorker | None = None
        self.analysis_worker: FullAnalysisWorker | None = None
        self.analysis_dialog: AnalysisProgressDialog | None = None
        self.base_gates: list[AvailabilityPanel] = []
        self.full_gates: list[AvailabilityPanel] = []
        self.chart_panels: dict[str, list[ImagePanel]] = {}
        self.nav_buttons: list[QPushButton] = []

        self.setWindowTitle("CTI-RLex Studio — Robust Irrigation Allocation")
        self.setMinimumSize(1120, 720)
        self.resize(1480, 920)
        self._build_actions()
        self._build_menu()
        self._build_shell()
        self._build_pages()
        self._restore_window_state()
        self._set_compute_enabled(False)
        self.export_action.setEnabled(False)
        self.statusBar().showMessage(self._tr("Benchmark танланмаган", "No benchmark selected"))

        if auto_load:
            target = initial_benchmark or self._last_benchmark() or paths.default_benchmark
            if target.exists():
                self.load_benchmark(target)

    # ------------------------------------------------------------------ shell
    def _tr(self, uzbek: str, english: str) -> str:
        return pick(self.language, uzbek, english)

    def _build_actions(self) -> None:
        self.open_action = QAction(self._tr("Benchmarkни очиш…", "Open benchmark…"), self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_benchmark_dialog)
        self.reload_action = QAction(
            self._tr("Benchmarkни қайта юклаш", "Reload benchmark"), self
        )
        self.reload_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.reload_action.triggered.connect(self.reload_benchmark)
        self.export_action = QAction(
            self._tr("Натижа пакетини экспорт қилиш…", "Export result package…"), self
        )
        self.export_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_action.triggered.connect(self.export_results)
        self.exit_action = QAction(self._tr("Чиқиш", "Exit"), self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.close)
        self.solve_action = QAction(
            self._tr("Асосий CTI-RLex ечимини ҳисоблаш", "Compute base CTI-RLex solution"), self
        )
        self.solve_action.setShortcut(QKeySequence("Ctrl+R"))
        self.solve_action.triggered.connect(self.solve_base)
        self.full_analysis_action = QAction(
            self._tr("Кенгайтирилган таҳлил", "Extended analysis"), self
        )
        self.full_analysis_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.full_analysis_action.triggered.connect(self.run_full_analysis)
        self.about_action = QAction(self._tr("Лойиҳа ҳақида", "About the project"), self)
        self.about_action.triggered.connect(self.show_about)
        self.guide_action = QAction(
            self._tr("GUI фойдаланиш қўлланмаси", "GUI user guide"), self
        )
        self.guide_action.setShortcut(QKeySequence.StandardKey.HelpContents)
        self.guide_action.triggered.connect(self.show_guide)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu(self._tr("Файл", "File"))
        file_menu.addAction(self.open_action)
        self.recent_menu = file_menu.addMenu(
            self._tr("Охирги benchmarkлар", "Recent benchmarks")
        )
        file_menu.addAction(self.reload_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)
        compute_menu = self.menuBar().addMenu(self._tr("Ҳисоблаш", "Compute"))
        compute_menu.addAction(self.solve_action)
        compute_menu.addAction(self.full_analysis_action)
        help_menu = self.menuBar().addMenu(self._tr("Ёрдам", "Help"))
        help_menu.addAction(self.about_action)
        help_menu.addAction(self.guide_action)
        self._refresh_recent_menu()

    def _build_shell(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        topbar = QFrame()
        topbar.setObjectName("TopBar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(19, 10, 18, 10)
        top.setSpacing(9)
        self.window_title = QLabel(
            self._tr("CTI-RLex benchmark таҳлилчиси", "CTI-RLex benchmark analyzer")
        )
        self.window_title.setObjectName("WindowTitle")
        self.path_chip = QLabel(self._tr("Benchmark танланмаган", "No benchmark selected"))
        self.path_chip.setObjectName("PathChip")
        self.path_chip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.solve_button = QPushButton(self._tr("Асосий ечим", "Base solution"))
        self.solve_button.setObjectName("SecondaryButton")
        self.solve_button.clicked.connect(self.solve_base)
        self.analysis_button = QPushButton(
            self._tr("Кенгайтирилган таҳлил", "Extended analysis")
        )
        self.analysis_button.setObjectName("PrimaryButton")
        self.analysis_button.clicked.connect(self.run_full_analysis)
        top.addWidget(self.window_title)
        top.addWidget(self.path_chip, 1)
        language_label = QLabel(self._tr("Тил:", "Language:"))
        language_label.setObjectName("TopBarLabel")
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("LanguageCombo")
        self.language_combo.setMinimumWidth(82)
        self.language_combo.addItem("ЎЗБ", "uz")
        self.language_combo.addItem("ENG", "en")
        self.language_combo.setCurrentIndex(0 if self.language == "uz" else 1)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        top.addWidget(language_label)
        top.addWidget(self.language_combo)
        top.addWidget(self.solve_button)
        top.addWidget(self.analysis_button)
        root_layout.addWidget(topbar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(252)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(15, 18, 15, 16)
        self.sidebar_layout.setSpacing(5)
        brand = QHBoxLayout()
        mark = QLabel("LX")
        mark.setObjectName("BrandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(48, 48)
        brand_text = QVBoxLayout()
        title = QLabel("CTI-RLex")
        title.setObjectName("BrandTitle")
        subtitle = QLabel(self._tr("ОЧИҚ ИЛМИЙ ВОСИТА", "OPEN RESEARCH TOOL"))
        subtitle.setObjectName("BrandSubtitle")
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        brand.addWidget(mark)
        brand.addLayout(brand_text, 1)
        self.sidebar_layout.addLayout(brand)
        self.sidebar_layout.addSpacing(15)
        nav_label = QLabel(self._tr("НАВИГАЦИЯ", "NAVIGATION"))
        nav_label.setObjectName("BrandSubtitle")
        self.sidebar_layout.addWidget(nav_label)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.sidebar_layout.addStretch()
        self.sidebar_status = QLabel(
            self._tr("Benchmark кутилмоқда", "Waiting for a benchmark")
        )
        self.sidebar_status.setObjectName("SidebarStatus")
        self.sidebar_status.setWordWrap(True)
        self.sidebar_layout.addWidget(self.sidebar_status)
        self.stack = QStackedWidget()
        body_layout.addWidget(self.sidebar)
        body_layout.addWidget(self.stack, 1)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)

    def _add_page(self, nav_text: str, page: QWidget) -> None:
        index = self.stack.addWidget(page)
        button = QPushButton(nav_text)
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.clicked.connect(lambda _checked=False, item=index: self.stack.setCurrentIndex(item))
        self.nav_group.addButton(button, index)
        self.nav_buttons.append(button)
        self.sidebar_layout.insertWidget(self.sidebar_layout.count() - 2, button)
        if index == 0:
            button.setChecked(True)

    # ------------------------------------------------------------------ pages
    def _build_pages(self) -> None:
        self._add_page(self._tr("01   Умумий кўриниш", "01   Overview"), self._dashboard_page())
        self._add_page("02   Benchmark", self._benchmark_page())
        self._add_page(self._tr("03   Модель ва алгоритм", "03   Model and algorithm"), self._model_page())
        self._add_page(self._tr("04   Талабгорлар тақсимоти", "04   Claimant allocation"), self._allocation_page())
        self._add_page(self._tr("05   Усуллар самарадорлиги", "05   Method performance"), self._comparison_page())
        self._add_page(self._tr("06   Қайта мослашув ва вақт", "06   Recourse and time"), self._recourse_page())
        self._add_page(self._tr("07   Манбалар таҳлили", "07   Source analysis"), self._sources_page())
        self._add_page(self._tr("08   Робастлик таҳлили", "08   Robustness analysis"), self._sensitivity_page())
        self._add_page(self._tr("09   Сонли аудит", "09   Numerical audit"), self._audit_page())
        self._add_page(self._tr("10   Натижа графиклари", "10   Result charts"), self._gallery_page())
        self._add_page(self._tr("11   Тўлиқ сонли натижа", "11   Complete numerical output"), self._raw_results_page())

    def _dashboard_page(self) -> QWidget:
        page, _content, layout = make_page()
        layout.addWidget(
            PageHeader(
                self._tr("Умумий кўриниш", "Overview"),
                self._tr(
                    "Жорий benchmark, CTI-RLex ечими ва усулнинг самарадорлик кўрсаткичлари.",
                    "Current benchmark, CTI-RLex solution and method-effectiveness indicators.",
                ),
            )
        )
        row = QHBoxLayout()
        row.setSpacing(12)
        self.metrics = {
            "guarantee": MetricCard(self._tr("Минимал робаст кафолат", "Minimum robust guarantee"), "—", self._tr("leximin 1-даражаси", "leximin level 1")),
            "delivery": MetricCard(self._tr("Номинал фойдали етказиш", "Nominal beneficial delivery"), "—", "acre-ft"),
            "recourse": MetricCard(self._tr("Қайта мослашув фойдаси", "Value of recourse"), "—", self._tr("қатъий моделга нисбатан", "relative to the rigid model")),
            "fairness": MetricCard(self._tr("Адолат нархи", "Price of fairness"), "—", self._tr("утилитар таянчга нисбатан", "relative to utilitarian baseline")),
            "sensitivity": MetricCard(self._tr("Робастлик диапазони", "Robustness range"), "—", self._tr("benchmark ҳолатлари", "benchmark cases")),
        }
        for card in self.metrics.values():
            row.addWidget(card)
        layout.addLayout(row)
        self.dashboard_notice = Notice(
            self._tr(
                "Файл → Benchmarkни очиш орқали benchmark шаблонига мос JSON файлини танланг.",
                "Choose a JSON file conforming to the benchmark template via File → Open benchmark.",
            )
        )
        layout.addWidget(self.dashboard_notice)
        cards = QHBoxLayout()
        summary = Card(self._tr("Ечим хулосаси", "Solution summary"))
        self.summary_text = QLabel(self._tr("Натижа ҳисобланмаган.", "No result has been computed."))
        self.summary_text.setWordWrap(True)
        self.summary_text.setTextFormat(Qt.TextFormat.RichText)
        summary.layout_box.addWidget(self.summary_text)
        passport = Card(self._tr("Benchmark паспорти", "Benchmark passport"))
        self.dashboard_benchmark = QLabel(self._tr("Benchmark танланмаган.", "No benchmark selected."))
        self.dashboard_benchmark.setWordWrap(True)
        self.dashboard_benchmark.setTextFormat(Qt.TextFormat.RichText)
        passport.layout_box.addWidget(self.dashboard_benchmark)
        cards.addWidget(summary, 3)
        cards.addWidget(passport, 2)
        layout.addLayout(cards)
        steps = Card(self._tr("Такрорланувчан ишлаш тартиби", "Reproducible workflow"))
        label = QLabel(
            self._tr(
                "<b>1.</b> Benchmark JSON файлини очинг. &nbsp; "
                "<b>2.</b> Асосий ечим орқали бажарилувчанлик ва тақсимотни текширинг. &nbsp; "
                "<b>3.</b> Кенгайтирилган таҳлилда таянч усуллар, абляция, қайта мослашув, робастлик ва аудитни ҳисобланг. &nbsp; "
                "<b>4.</b> Натижа пакетини JSON, CSV, PNG ва SVG форматларида экспорт қилинг.",
                "<b>1.</b> Open a benchmark JSON file. &nbsp; "
                "<b>2.</b> Check feasibility and allocation with the base solution. &nbsp; "
                "<b>3.</b> Run baseline, ablation, recourse, robustness and audit calculations in the extended analysis. &nbsp; "
                "<b>4.</b> Export the result package as JSON, CSV, PNG and SVG.",
            )
        )
        label.setWordWrap(True)
        steps.layout_box.addWidget(label)
        layout.addWidget(steps)
        layout.addStretch()
        return page

    def _benchmark_page(self) -> QWidget:
        page, _content, layout = make_page()
        layout.addWidget(
            PageHeader(
                self._tr("Benchmark паспорти", "Benchmark passport"),
                self._tr(
                    "Тармоқ топологияси, талабгор–терминал мослиги, манбалар ва сценарий тузилиши.",
                    "Network topology, claimant–terminal mapping, sources and scenario design.",
                ),
            )
        )
        counts = QHBoxLayout()
        self.benchmark_metrics = {
            "claimants": MetricCard(self._tr("Талабгорлар", "Claimants")),
            "sources": MetricCard(self._tr("Манбалар", "Sources")),
            "network": MetricCard(self._tr("Тармоқ", "Network")),
            "design": MetricCard(self._tr("Сценарий × давр", "Scenario × period")),
            "cases": MetricCard(self._tr("Сезгирлик ҳолатлари", "Sensitivity cases")),
        }
        for card in self.benchmark_metrics.values():
            counts.addWidget(card)
        layout.addLayout(counts)
        metadata = Card(self._tr("Илмий қамров ва метамаълумот", "Scientific scope and metadata"))
        self.benchmark_metadata = QLabel(self._tr("Benchmark танланмаган.", "No benchmark selected."))
        self.benchmark_metadata.setWordWrap(True)
        self.benchmark_metadata.setTextFormat(Qt.TextFormat.RichText)
        metadata.layout_box.addWidget(self.benchmark_metadata)
        layout.addWidget(metadata)
        tabs = QTabWidget()
        self.network_panel = self._chart_panel("network", 670)
        tabs.addTab(self.network_panel, self._tr("Тармоқ", "Network"))
        self.claimant_panel = TablePanel(self._tr("Талабгорлар", "Claimants"), minimum_height=410, language=self.language)
        self.source_panel = TablePanel(self._tr("Манбалар", "Sources"), minimum_height=410, language=self.language)
        self.scenario_panel = TablePanel(self._tr("Сценарийлар", "Scenarios"), minimum_height=410, language=self.language)
        tabs.addTab(self.claimant_panel, self._tr("Талабгорлар", "Claimants"))
        tabs.addTab(self.source_panel, self._tr("Манбалар", "Sources"))
        tabs.addTab(self.scenario_panel, self._tr("Сценарийлар", "Scenarios"))
        tabs.setMinimumHeight(790)
        layout.addWidget(tabs)
        return page

    def _model_page(self) -> QWidget:
        page, _content, layout = make_page()
        layout.addWidget(
            PageHeader(
                self._tr("Модель ва алгоритм", "Model and algorithm"),
                self._tr(
                    "Талабгорга йўналтирилган, вақт бўйича робаст leximin тақсимоти ва чегараланган операцион қайта мослашув.",
                    "Claimant-centred, temporally robust leximin allocation with bounded operational recourse.",
                ),
            )
        )
        features = QHBoxLayout()
        for value, label, accent in (
            (self._tr("Талабгор", "Claimant"), self._tr("Адолат бирлиги", "Fairness unit"), self._tr("терминал ёзуви эмас", "not a terminal record")),
            (self._tr("Даврлар бўйича", "Period-wise"), self._tr("Робаст кафолат", "Robust guarantee"), self._tr("ҳар бир давр ва сценарий", "every period and scenario")),
            ("Leximin", self._tr("Тақсимлаш қоидаси", "Allocation rule"), self._tr("босқичма-босқич тўлдириш", "progressive filling")),
            (self._tr("Чегараланган", "Bounded"), self._tr("Операцион қайта мослашув", "Operational recourse"), self._tr("назоратланган мослашув", "controlled adaptation")),
        ):
            features.addWidget(MetricCard(label, value, accent))
        layout.addLayout(features)
        workflow = Card(self._tr("Ҳисоблаш жараёни", "Computational workflow"))
        flow = QHBoxLayout()
        stages = [
            ("1", self._tr("Benchmarkни\nтекшириш", "Validate the\nbenchmark")),
            ("2", self._tr("Кўп сценарийли\nLP қуриш", "Build the multi-\nscenario LP")),
            ("3", self._tr("Leximin босқичли\nтўлдириш", "Leximin\nprogressive filling")),
            ("4", self._tr("Тенгликни бузувчи\nмақсадлар", "Tie-break\nobjectives")),
            ("5", self._tr("Самарадорлик\nва аудит", "Effectiveness\nand audit")),
        ]
        for index, (number, text) in enumerate(stages):
            stage = Card()
            stage.layout_box.setContentsMargins(13, 12, 13, 12)
            number_label = QLabel(number)
            number_label.setObjectName("MetricAccent")
            text_label = QLabel(text)
            text_label.setObjectName("CardTitle")
            text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stage.layout_box.addWidget(number_label, 0, Qt.AlignmentFlag.AlignCenter)
            stage.layout_box.addWidget(text_label)
            flow.addWidget(stage, 1)
            if index < len(stages) - 1:
                arrow = QLabel("→")
                arrow.setStyleSheet("font-size: 20pt; color: #0284C7;")
                flow.addWidget(arrow)
        workflow.layout_box.addLayout(flow)
        layout.addWidget(workflow)
        advantage = Card(self._tr("Моделнинг асосий устунлиги", "Core model advantage"))
        text = QLabel(
            self._tr(
                "Усул кўп манбали, йўқотишли DAG тармоғида ҳар бир талабгор учун мусбат талабли "
                "ҳар бир давр ва барча стресс сценарийларда хизмат кафолатини таъминлайди. "
                "Leximin босқичлари энг кам хизмат олган талабгорни биринчи яхшилайди; кейинги "
                "детерминистик босқичлар кафолат векторини бузмасдан етказиш ва қайта мослашув "
                "сарфини тартиб билан оптималлаштиради.",
                "The method guarantees service for every claimant in every positive-demand period "
                "and every stress scenario on a lossy multi-source DAG. Leximin stages improve the "
                "least-served claimant first; subsequent deterministic stages optimize delivery and "
                "recourse effort in sequence without changing the guarantee vector.",
            )
        )
        text.setWordWrap(True)
        advantage.layout_box.addWidget(text)
        layout.addWidget(advantage)
        layout.addStretch()
        return page

    def _result_page(
        self,
        title: str,
        subtitle: str,
        widgets: list[QWidget],
        level: str,
    ) -> QWidget:
        page, _content, layout = make_page()
        layout.addWidget(PageHeader(title, subtitle))
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(14)
        for widget in widgets:
            box.addWidget(widget)
        box.addStretch()
        if level == "base":
            gate = AvailabilityPanel(
                content,
                self._tr("Асосий ечим кутилмоқда", "Waiting for the base solution"),
                self._tr(
                    "«Асосий ечим» тугмаси CTI-RLex тақсимоти ва сценарий–давр натижаларини ҳисоблайди.",
                    "The Base solution button computes the CTI-RLex allocation and scenario–period results.",
                ),
            )
            self.base_gates.append(gate)
        else:
            gate = AvailabilityPanel(
                content,
                self._tr("Кенгайтирилган таҳлил кутилмоқда", "Waiting for extended analysis"),
                self._tr(
                    "«Кенгайтирилган таҳлил» тугмаси таянч усуллар, қайта мослашув, абляция, робастлик ва аудит натижаларини ҳисоблайди.",
                    "The Extended analysis button computes baseline, recourse, ablation, robustness and audit results.",
                ),
            )
            self.full_gates.append(gate)
        layout.addWidget(gate)
        layout.addStretch()
        return page

    def _chart_panel(self, key: str, height: int = 500) -> ImagePanel:
        title, caption = chart_info(key, self.language)
        panel = ImagePanel(title, caption, None, height, self.language)
        self.chart_panels.setdefault(key, []).append(panel)
        return panel

    def _allocation_page(self) -> QWidget:
        self.allocation_panel = TablePanel(
            self._tr("Талабгорлар тақсимоти натижалари", "Claimant allocation results"),
            self._tr(
                "Талаб, қўллаш самарадорлиги, робаст кафолат ва боғловчи сценарий–давр катаклари.",
                "Demand, application efficiency, robust guarantee and binding scenario–period cells.",
            ),
            language=self.language,
        )
        return self._result_page(
            self._tr("Талабгорлар тақсимоти", "Claimant allocation"),
            self._tr(
                "Жорий benchmark учун CTI-RLex асосий тақсимоти ва талабгорлар даражасидаги адолат натижалари.",
                "CTI-RLex base allocation and claimant-level fairness results for the current benchmark.",
            ),
            [self.allocation_panel, self._chart_panel("guarantees", 480)],
            "base",
        )

    def _comparison_page(self) -> QWidget:
        self.method_panel = TablePanel(
            self._tr("Ечувчи конфигурацияларини таққослаш", "Solver configuration comparison"),
            self._tr(
                "Утилитар, умумий робаст чегара, қатъий, чегараланган қайта мослашув ва фақат номинал натижалар.",
                "Utilitarian, common robust floor, rigid, bounded-recourse and nominal-only results.",
            ),
            language=self.language,
        )
        return self._result_page(
            self._tr("Усуллар самарадорлиги", "Method performance"),
            self._tr(
                "CTI-RLex адолат, етказиш ва ҳисоблаш вақти кўрсаткичларини таянч усуллар билан таққослаш.",
                "Compare CTI-RLex fairness, delivery and runtime indicators with baseline methods.",
            ),
            [self.method_panel, self._chart_panel("methods", 510)],
            "full",
        )

    def _recourse_page(self) -> QWidget:
        self.recourse_panel = TablePanel(
            self._tr("Қайта мослашув фронтининг сонли натижалари", "Recourse-frontier numerical results"),
            self._tr(
                "Бюджет масштаби бўйича кафолат вектори, операцион сарф ва ҳисоблаш вақти.",
                "Guarantee vector, operational effort and runtime by budget scale.",
            ),
            language=self.language,
        )
        tabs = QTabWidget()
        tabs.addTab(self._chart_panel("recourse", 530), self._tr("Қайта мослашув фронти", "Recourse frontier"))
        tabs.addTab(self._chart_panel("service", 690), self._tr("Сценарий–давр матрицаси", "Scenario–period matrix"))
        tabs.setMinimumHeight(790)
        return self._result_page(
            self._tr("Қайта мослашув ва вақт тузилиши", "Recourse and temporal structure"),
            self._tr(
                "Чегараланган операцион мослашув қиймати ва даврлар бўйича танқислик тузилиши.",
                "Value of bounded operational adaptation and the period-wise shortage structure.",
            ),
            [self.recourse_panel, tabs],
            "full",
        )

    def _sources_page(self) -> QWidget:
        self.source_activation_panel = TablePanel(self._tr("Манбалар фаоллиги", "Source activation"), language=self.language)
        self.water_balance_panel = TablePanel(self._tr("Сценарий сув баланси", "Scenario water balance"), language=self.language)
        self.ablation_panel = TablePanel(self._tr("Манбани ўчириш абляцияси", "Source-removal ablation"), language=self.language)
        tabs = QTabWidget()
        tabs.addTab(self._chart_panel("source_balance", 540), self._tr("Сув баланси", "Water balance"))
        tabs.addTab(self._chart_panel("source_ablation", 500), self._tr("Манба критиклиги", "Source criticality"))
        tabs.setMinimumHeight(660)
        return self._result_page(
            self._tr("Кўп манбали тизим таҳлили", "Multi-source system analysis"),
            self._tr(
                "Манбалар фаоллиги, фойдаланиш даражаси, сув баланси ва ҳар бир манбанинг маржинал аҳамияти.",
                "Source activation, utilization, water balance and the marginal importance of each source.",
            ),
            [tabs, self.source_activation_panel, self.water_balance_panel, self.ablation_panel],
            "full",
        )

    def _sensitivity_page(self) -> QWidget:
        self.sensitivity_panel = TablePanel(
            self._tr("Сезгирликнинг асосий таъсирлари", "Sensitivity main effects"),
            self._tr(
                "Benchmark шаблонидаги омил комбинациялари бўйича тавсифий ўртача ва диапазон.",
                "Descriptive mean and range across factor combinations in the benchmark template.",
            ),
            language=self.language,
        )
        return self._result_page(
            self._tr("Робастлик таҳлили", "Robustness analysis"),
            self._tr(
                "Талаб, йўқотиш, манбалар мавжудлиги ва қайта мослашув параметрларига нисбатан ечим барқарорлиги.",
                "Solution stability with respect to demand, loss, source availability and recourse parameters.",
            ),
            [self.sensitivity_panel, self._chart_panel("sensitivity", 650)],
            "full",
        )

    def _audit_page(self) -> QWidget:
        self.representation_panel = TablePanel(self._tr("Терминал тасвирининг инвариантлиги", "Terminal representation invariance"), language=self.language)
        self.scalability_panel = TablePanel(self._tr("LP ўлчами ва ҳисоблаш вақти", "LP size and runtime"), language=self.language)
        self.residual_panel = TablePanel(self._tr("Асосий LP қолдиқлари", "Base LP residuals"), language=self.language)
        tabs = QTabWidget()
        tabs.addTab(self.representation_panel, self._tr("Тасвирлаш", "Representation"))
        tabs.addTab(self.scalability_panel, self._tr("Масштабланиш", "Scalability"))
        tabs.addTab(self.residual_panel, self._tr("Қолдиқлар", "Residuals"))
        tabs.setMinimumHeight(430)
        return self._result_page(
            self._tr("Сонли ва ҳисоблаш аудити", "Numerical and computational audit"),
            self._tr(
                "Бажарилувчанлик, талабгор тасвирининг инвариантлиги ва ҳисоблаш масштабланиши.",
                "Feasibility, claimant representation invariance and computational scalability.",
            ),
            [self._chart_panel("scalability", 480), tabs],
            "full",
        )

    def _gallery_page(self) -> QWidget:
        page, _content, layout = make_page()
        layout.addWidget(
            PageHeader(
                self._tr("Натижа графиклари", "Result charts"),
                self._tr(
                    "Барча графиклар жорий benchmark ва ҳисоблаш сессиясидан динамик қурилади.",
                    "All charts are generated dynamically from the current benchmark and compute session.",
                ),
            )
        )
        self.gallery_notice = Notice(self._tr("Асосий ечим ҳисоблангач биринчи графиклар пайдо бўлади.", "Charts appear after the base solution is computed."))
        layout.addWidget(self.gallery_notice)
        self.gallery_widget = QWidget()
        self.gallery_layout = QVBoxLayout(self.gallery_widget)
        self.gallery_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.gallery_widget)
        layout.addStretch()
        return page

    def _raw_results_page(self) -> QWidget:
        page, _content, layout = make_page()
        layout.addWidget(
            PageHeader(
                self._tr("Тўлиқ сонли натижалар", "Complete numerical output"),
                self._tr(
                    "Кафолатлар, мақсад функциялари, қолдиқлар, хизмат нисбатлари, манба оқимлари ва қирра оқимлари.",
                    "Guarantees, objectives, residuals, service ratios, source injections and edge flows.",
                ),
            )
        )
        self.raw_notice = Notice(self._tr("Асосий ечим ҳисоблангач жадваллар очилади.", "Tables appear after the base solution is computed."))
        self.raw_tabs = QTabWidget()
        self.raw_tabs.setMinimumHeight(650)
        layout.addWidget(self.raw_notice)
        layout.addWidget(self.raw_tabs)
        layout.addStretch()
        return page

    # -------------------------------------------------------------- benchmark
    def open_benchmark_dialog(self) -> None:
        start = self.current_benchmark.parent if self.current_benchmark else self.paths.default_benchmark.parent
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("CTI-RLex benchmarkни танлаш", "Select a CTI-RLex benchmark"),
            str(start),
            self._tr(
                "CTI-RLex benchmark (benchmark.json *.json);;JSON файллар (*.json);;Барча файллар (*)",
                "CTI-RLex benchmark (benchmark.json *.json);;JSON files (*.json);;All files (*)",
            ),
        )
        if selected:
            self.load_benchmark(Path(selected))

    def load_benchmark(self, path: Path) -> None:
        if self.analysis_worker is not None and self.analysis_worker.isRunning():
            QMessageBox.warning(
                self,
                self._tr("Таҳлил давом этмоқда", "Analysis in progress"),
                self._tr(
                    "Кенгайтирилган таҳлил якунлангунча benchmarkни алмаштириб бўлмайди.",
                    "The benchmark cannot be changed until the extended analysis finishes.",
                ),
            )
            return
        path = path.resolve()
        try:
            raw = load_benchmark_document(path, self.language)
            from leximin.dag import load_cti_benchmark

            load_cti_benchmark(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                self._tr("Benchmark очилмади", "Could not open benchmark"),
                self._tr(
                    "Файл CTI-RLex benchmark шаблони текширувидан ўтмади.",
                    "The file failed CTI-RLex benchmark-template validation.",
                )
                + f"\n\n{type(exc).__name__}: {exc}",
            )
            return
        self.current_benchmark = path
        self.benchmark_raw = raw
        self.base_result = None
        self.full_analysis = None
        self.chart_paths.clear()
        self._clear_results()
        self._update_recent(path)
        self._update_benchmark_view()
        try:
            self.chart_paths["network"] = self.chart_store.network(raw, self.language)
            self._refresh_chart_panels()
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(
                self._tr("Тармоқ графигини қуришда хатолик: ", "Network-chart error: ")
                + str(exc),
                8000,
            )
        self.path_chip.setText(str(path))
        self.path_chip.setToolTip(str(path))
        self.window_title.setText(str(raw.get("title", "CTI-RLex benchmark")))
        self.sidebar_status.setText(
            f"{raw['benchmark_id']}\n"
            + self._tr("Асосий ечим ҳисобланмоқда", "Computing base solution")
        )
        self._set_compute_enabled(True)
        self.export_action.setEnabled(False)
        self.statusBar().showMessage(
            self._tr("Benchmark очилди: ", "Benchmark opened: ") + path.name, 6000
        )
        self.solve_base()

    def reload_benchmark(self) -> None:
        self.load_benchmark(self.current_benchmark) if self.current_benchmark else self.open_benchmark_dialog()

    def _update_benchmark_view(self) -> None:
        if self.benchmark_raw is None:
            return
        raw = self.benchmark_raw
        counts = benchmark_counts(raw)
        self.benchmark_metrics["claimants"].set_value(
            str(counts["claimants"]),
            f'{counts["terminals"]} ' + self._tr("терминал", "terminal"),
        )
        self.benchmark_metrics["sources"].set_value(
            str(counts["sources"]),
            f'{counts["controls"]} ' + self._tr("бошқарув объекти", "control asset"),
        )
        self.benchmark_metrics["network"].set_value(
            f'{counts["nodes"]} / {counts["edges"]}', self._tr("тугун / қирра", "node / edge")
        )
        self.benchmark_metrics["design"].set_value(
            f'{counts["scenarios"]} × {counts["periods"]}',
            f'{counts["scenarios"] * counts["periods"]} '
            + self._tr("вақт ҳолати", "temporal states"),
        )
        self.benchmark_metrics["cases"].set_value(
            str(counts["sensitivity"]), self._tr("benchmark тузилиши", "benchmark design")
        )
        scope = raw.get("scientific_scope", {})
        supports = scope.get("supports", "—")
        limitations = scope.get("does_not_validate", "—")
        if isinstance(supports, list):
            supports = "; ".join(map(str, supports))
        if isinstance(limitations, list):
            limitations = "; ".join(map(str, limitations))
        self.benchmark_metadata.setText(
            f"<b>ID:</b> {raw['benchmark_id']}<br>"
            f"<b>{self._tr('Номи', 'Title')}:</b> {raw.get('title', '—')}<br>"
            f"<b>{self._tr('Йил / ҳолат санаси', 'Year / snapshot')}:</b> {raw.get('benchmark_year', '—')} / {raw.get('snapshot_date', '—')}<br>"
            f"<b>{self._tr('Схема', 'Schema')}:</b> {raw.get('schema_version', '—')}<br>"
            f"<b>{self._tr('Классификация', 'Classification')}:</b> {scope.get('classification', '—')}<br>"
            f"<b>{self._tr('Қўллаб-қувватлайди', 'Supports')}:</b> {supports}<br>"
            f"<b>{self._tr('Чеклов', 'Limitation')}:</b> {limitations}"
        )
        self.claimant_panel.set_data(*claimant_table(raw, self.language))
        self.source_panel.set_data(*source_table(raw, self.language))
        self.scenario_panel.set_data(*scenario_table(raw, self.language))
        self.dashboard_benchmark.setText(
            f"<b>{raw.get('title', raw['benchmark_id'])}</b><br><br>"
            f"{counts['claimants']} {self._tr('талабгор', 'claimant')} · "
            f"{counts['sources']} {self._tr('манба', 'source')} · "
            f"{counts['edges']} {self._tr('қирра', 'edge')} · "
            f"{counts['scenarios']} {self._tr('сценарий', 'scenario')} · "
            f"{counts['periods']} {self._tr('давр', 'period')}<br>"
            f"<span style='color:#64748B'>{self._tr('Схема', 'Schema')} {raw.get('schema_version', '—')} · "
            f"{self._tr('Ҳолат санаси', 'Snapshot')} {raw.get('snapshot_date', '—')}</span>"
        )

    def _clear_results(self) -> None:
        for gate in self.base_gates + self.full_gates:
            gate.set_available(False)
        for key, panels in self.chart_panels.items():
            if key != "network":
                for panel in panels:
                    panel.set_image(None)
        self._reset_dashboard_metrics()
        self._update_raw_results()
        self._rebuild_gallery()
        self.dashboard_notice.setText(
            self._tr(
                "Benchmark текширилди. Асосий CTI-RLex ечими ҳисобланмоқда.",
                "Benchmark validated. Computing the base CTI-RLex solution.",
            )
        )

    # --------------------------------------------------------------- compute
    def solve_base(self) -> None:
        if self.current_benchmark is None:
            self.open_benchmark_dialog()
            return
        if self.solve_worker is not None and self.solve_worker.isRunning():
            return
        self.solve_button.setEnabled(False)
        self.solve_action.setEnabled(False)
        self.solve_button.setText(self._tr("Ҳисобланмоқда…", "Computing…"))
        self.statusBar().showMessage(
            self._tr(
                "Асосий CTI-RLex ечими ҳисобланмоқда…",
                "Computing the base CTI-RLex solution…",
            )
        )
        worker = SolveWorker(self.current_benchmark)
        worker.completed.connect(self._base_solved)
        worker.failed.connect(self._base_failed)
        worker.finished.connect(self._solve_finished)
        self.solve_worker = worker
        worker.start()

    def _base_solved(self, payload: dict, runtime: float) -> None:
        if self.benchmark_raw is None or payload.get("benchmark_id") != self.benchmark_raw.get("benchmark_id"):
            self.statusBar().showMessage(
                self._tr(
                    "Олдинги benchmark ечими янги танловга аралаштирилмади.",
                    "A result from the previous benchmark was not applied to the new selection.",
                ),
                8000,
            )
            return
        self.base_result = payload
        try:
            self.chart_paths.update(
                self.chart_store.render_base(self.benchmark_raw, payload, self.language)
            )
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(
                self._tr("График қуриш хатоси: ", "Chart-rendering error: ") + str(exc),
                8000,
            )
        for gate in self.base_gates:
            gate.set_available(True)
        self.allocation_panel.set_data(
            *allocation_table(self.benchmark_raw, payload, self.language)
        )
        self._update_dashboard()
        self._update_raw_results()
        self._refresh_chart_panels()
        self._rebuild_gallery()
        self.export_action.setEnabled(True)
        self.dashboard_notice.setText(
            self._tr(
                "Асосий ечим жорий benchmarkдан ҳисобланди. Кенгайтирилган таҳлил таянч усуллар, "
                "қайта мослашув, манбалар критиклиги, робастлик ва сонли аудитни қўшади.",
                "The base solution was computed from the current benchmark. Extended analysis adds "
                "baselines, recourse, source criticality, robustness and numerical audit.",
            )
        )
        self.sidebar_status.setText(
            f"{payload['benchmark_id']}\n" + self._tr("Асосий ечим тайёр", "Base solution ready")
        )
        self.statusBar().showMessage(
            self._tr("Асосий ечим тайёр: ", "Base solution ready: ") + f"{runtime:.3f} s",
            8000,
        )

    def _base_failed(self, message: str) -> None:
        QMessageBox.critical(
            self, self._tr("Ҳисоблаш хатоси", "Computation error"), message
        )
        self.statusBar().showMessage(
            self._tr("Асосий ечимни ҳисоблаш хатоси", "Base-computation error"), 8000
        )

    def _solve_finished(self) -> None:
        self.solve_button.setText(self._tr("Асосий ечим", "Base solution"))
        self.solve_button.setEnabled(self.current_benchmark is not None)
        self.solve_action.setEnabled(self.current_benchmark is not None)
        if self.solve_worker:
            self.solve_worker.deleteLater()
        self.solve_worker = None
        if self.current_benchmark and self.base_result is None:
            QTimer.singleShot(0, self.solve_base)

    def run_full_analysis(self) -> None:
        if self.current_benchmark is None:
            self.open_benchmark_dialog()
            return
        if self.analysis_worker is not None and self.analysis_worker.isRunning():
            if self.analysis_dialog:
                self.analysis_dialog.show()
                self.analysis_dialog.raise_()
            return
        answer = QMessageBox.question(
            self,
            self._tr("Кенгайтирилган таҳлилни бошлаш", "Start extended analysis"),
            self._tr(
                "Benchmarkдаги барча сезгирлик ҳолатлари, таянч усуллар, манбалар абляцияси, "
                "қайта мослашув фронти ва аудит ечимлари ҳисобланади. Давом этасизми?",
                "All sensitivity cases, baseline methods, source-ablation runs, recourse-frontier "
                "points and audit solutions in the benchmark will be computed. Continue?",
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        dialog = AnalysisProgressDialog(self, self.language)
        worker = FullAnalysisWorker(self.current_benchmark, self.language)
        worker.log_line.connect(dialog.append_log)
        worker.progress.connect(dialog.progress.setValue)
        worker.completed.connect(self._analysis_completed)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(self._analysis_finished)
        dialog.cancel_requested.connect(worker.cancel)
        self.analysis_dialog = dialog
        self.analysis_worker = worker
        self.analysis_button.setEnabled(False)
        self.full_analysis_action.setEnabled(False)
        dialog.show()
        worker.start()

    def _analysis_completed(self, result: dict) -> None:
        if self.benchmark_raw is None or result.get("benchmark_id") != self.benchmark_raw.get("benchmark_id"):
            return
        self.full_analysis = result
        self.base_result = result["base_solution"]
        try:
            self.chart_paths.update(
                self.chart_store.render_full(self.benchmark_raw, result, self.language)
            )
        except Exception as exc:  # noqa: BLE001
            if self.analysis_dialog:
                self.analysis_dialog.append_log(
                    self._tr("График огоҳлантириши: ", "Chart warning: ") + str(exc)
                )
        self._populate_full_results(result)
        for gate in self.base_gates + self.full_gates:
            gate.set_available(True)
        self._update_dashboard()
        self._update_raw_results()
        self._refresh_chart_panels()
        self._rebuild_gallery()
        self.export_action.setEnabled(True)
        self.sidebar_status.setText(
            f"{result['benchmark_id']}\n"
            + self._tr("Кенгайтирилган таҳлил тайёр", "Extended analysis ready")
        )
        if self.analysis_dialog:
            self.analysis_dialog.append_log(
                "\n" + self._tr("Таҳлил муваффақиятли якунланди.", "Analysis completed successfully.")
            )
            self.analysis_dialog.mark_finished(True)
        self.statusBar().showMessage(
            self._tr("Кенгайтирилган таҳлил тайёр", "Extended analysis ready"), 10000
        )

    def _analysis_failed(self, message: str) -> None:
        if self.analysis_dialog:
            self.analysis_dialog.append_log("\n" + message)
            self.analysis_dialog.mark_finished(False)
        self.statusBar().showMessage(
            self._tr("Кенгайтирилган таҳлил тўхтатилди", "Extended analysis stopped"), 10000
        )

    def _analysis_finished(self) -> None:
        if self.analysis_worker:
            self.analysis_worker.deleteLater()
        self.analysis_worker = None
        self.analysis_button.setEnabled(self.current_benchmark is not None)
        self.full_analysis_action.setEnabled(self.current_benchmark is not None)

    def _populate_full_results(self, analysis: dict[str, Any]) -> None:
        assert self.benchmark_raw is not None
        self.method_panel.set_data(*method_table(analysis, self.language))
        self.recourse_panel.set_data(
            *recourse_table(self.benchmark_raw, analysis, self.language)
        )
        audit = analysis.get("operational_audit", {})
        self.source_activation_panel.set_data(
            *rows_from_dicts(
                audit.get("source_activation", []),
                [
                    ("scenario_label", self._tr("Сценарий", "Scenario")),
                    ("source_name", self._tr("Манба", "Source")),
                    ("source_class", self._tr("Класс", "Class")),
                    ("seasonal_injection_af", self._tr("Оқим (acre-ft)", "Injection (acre-ft)")),
                    ("seasonal_limit_af", self._tr("Лимит (acre-ft)", "Limit (acre-ft)")),
                    ("seasonal_utilization", self._tr("Фойдаланиш", "Utilization")),
                ],
            )
        )
        self.water_balance_panel.set_data(
            *rows_from_dicts(
                audit.get("scenario_water_balance", []),
                [
                    ("scenario_label", self._tr("Сценарий", "Scenario")),
                    ("source_injection_af", self._tr("Манба оқими", "Injection")),
                    ("beneficial_delivery_af", self._tr("Фойдали етказиш", "Beneficial delivery")),
                    ("conveyance_loss_af", self._tr("Узатиш йўқотиши", "Conveyance loss")),
                    ("application_loss_af", self._tr("Қўллаш йўқотиши", "Application loss")),
                    ("end_to_end_efficiency", self._tr("Якуний самарадорлик", "End-to-end efficiency")),
                    ("recourse_effort", self._tr("Қайта мослашув сарфи", "Recourse effort")),
                ],
            )
        )
        self.ablation_panel.set_data(
            *rows_from_dicts(
                analysis.get("source_ablation", []),
                [
                    ("disabled_source_name", self._tr("Ўчирилган манба", "Disabled source")),
                    ("disabled_source_class", self._tr("Класс", "Class")),
                    ("minimum_guarantee", self._tr("Минимал кафолат", "Minimum guarantee")),
                    ("change_in_minimum_guarantee", self._tr("Кафолат ўзгариши", "Guarantee change")),
                    ("nominal_beneficial_delivery_af", self._tr("Номинал етказиш", "Nominal delivery")),
                    ("change_in_nominal_delivery_af", self._tr("Етказиш ўзгариши", "Delivery change")),
                    ("runtime_seconds", self._tr("Ҳисоблаш вақти (s)", "Runtime (s)")),
                ],
            )
        )
        self.sensitivity_panel.set_data(*sensitivity_main_effects(analysis, self.language))
        self.representation_panel.set_data(
            *rows_from_dicts(
                analysis.get("representation_tests", []),
                [
                    ("terminal_id", self._tr("Терминал", "Terminal")),
                    ("copies", self._tr("Нусхалар", "Copies")),
                    ("guarantee_infinity_norm_error", self._tr("∞-норма хатоси", "∞-norm error")),
                    ("pass_at_1e-8", self._tr("Ўтди ≤ 1e-8", "Pass ≤ 1e-8")),
                ],
            )
        )
        self.scalability_panel.set_data(
            *rows_from_dicts(
                analysis.get("scalability", []),
                [
                    ("scenario_count", self._tr("Сценарийлар", "Scenarios")),
                    ("variables", self._tr("Ўзгарувчилар", "Variables")),
                    ("equality_constraints", self._tr("Тенгликлар", "Equalities")),
                    ("inequality_constraints", self._tr("Тенгсизликлар", "Inequalities")),
                    ("nonzeros", self._tr("Нолдан фарқлилар", "Nonzeros")),
                    ("median_runtime_seconds", self._tr("Медиан вақт (s)", "Median runtime (s)")),
                    ("maximum_lp_residual", self._tr("Максимал қолдиқ", "Max residual")),
                ],
            )
        )
        self.residual_panel.set_data(
            [self._tr("Қолдиқ", "Residual"), self._tr("Кузатилган", "Observed")],
            [[key, value] for key, value in analysis.get("base_residuals", {}).items()],
        )

    # --------------------------------------------------------------- display
    def _update_dashboard(self) -> None:
        if self.base_result is None:
            self._reset_dashboard_metrics()
            return
        guarantees = {key: float(value) for key, value in self.base_result.get("guarantees", {}).items()}
        objectives = self.base_result.get("objectives", {})
        minimum = min(guarantees.values()) if guarantees else 0.0
        nominal = float(objectives.get("nominal_beneficial_delivery_af", 0.0))
        self.metrics["guarantee"].set_value(
            f"{minimum:.4f}", self._tr("талабгорнинг минимал даражаси", "minimum claimant level")
        )
        self.metrics["delivery"].set_value(f"{nominal:,.1f}", "acre-ft")
        names = {
            row["claimant_id"]: row.get("claimant_name", row["claimant_id"])
            for row in (self.benchmark_raw or {}).get("claimants", [])
        }
        lines = "<br>".join(
            f"<b>{names.get(key, key)}:</b> {value:.6f}" for key, value in guarantees.items()
        )
        maximum_residual = max(
            (abs(float(value)) for value in self.base_result.get("residuals", {}).values()),
            default=0.0,
        )
        extra = ""
        if self.full_analysis:
            indicators = self.full_analysis["effectiveness_indicators"]
            recourse = float(indicators["value_of_recourse_minimum_guarantee_percent"])
            fairness = 100 * float(indicators["price_of_fairness_nominal_fraction"])
            low, high, count = sensitivity_range(self.full_analysis)
            recourse_text = "∞" if recourse == float("inf") else f"+{recourse:.2f}%"
            self.metrics["recourse"].set_value(
                recourse_text, self._tr("қатъий моделга нисбатан", "relative to the rigid model")
            )
            self.metrics["fairness"].set_value(
                f"{fairness:.2f}%",
                self._tr("номинал етказиш компромисси", "nominal-delivery trade-off"),
            )
            self.metrics["sensitivity"].set_value(
                f"{low:.3f}–{high:.3f}" if count else self._tr("мавжуд эмас", "n/a"),
                f"{count} " + self._tr("benchmark ҳолати", "benchmark cases"),
            )
            extra = (
                self._tr(
                    f"<br><br><b>Самарадорлик:</b> қайта мослашув фойдаси {recourse_text}; "
                    f"адолат нархи {fairness:.2f}%; робастлик диапазони "
                    f"{low:.4f}–{high:.4f} ({count} ҳолат).",
                    f"<br><br><b>Effectiveness:</b> recourse gain {recourse_text}; "
                    f"fairness cost {fairness:.2f}%; robustness range "
                    f"{low:.4f}–{high:.4f} ({count} cases).",
                )
            )
        else:
            for key in ("recourse", "fairness", "sensitivity"):
                self.metrics[key].set_value(
                    "—",
                    self._tr(
                        "кенгайтирилган таҳлил талаб қилинади",
                        "extended analysis required",
                    ),
                )
        self.summary_text.setText(
            f"{lines}<br><br><b>{self._tr('Leximin даражалари сони', 'Number of leximin levels')}:</b> "
            f"{len(self.base_result.get('leximin_levels', []))}<br>"
            f"<b>{self._tr('Номинал фойдали етказиш', 'Nominal beneficial delivery')}:</b> {nominal:,.3f} acre-ft<br>"
            f"<b>{self._tr('Энг катта LP қолдиғи', 'Maximum LP residual')}:</b> {maximum_residual:.3e}{extra}"
        )

    def _reset_dashboard_metrics(self) -> None:
        for card in self.metrics.values():
            card.set_value("—", self._tr("натижа кутилмоқда", "waiting for a result"))
        self.summary_text.setText(
            self._tr("Натижа ҳисобланмаган.", "No result has been computed.")
        )

    def _update_raw_results(self) -> None:
        while self.raw_tabs.count():
            widget = self.raw_tabs.widget(0)
            self.raw_tabs.removeTab(0)
            widget.deleteLater()
        if self.base_result is None:
            self.raw_notice.setText(
                self._tr(
                    "Асосий ечим ҳисоблангач сонли жадваллар шу ерда очилади.",
                    "Numerical tables appear here after the base solution is computed.",
                )
            )
            return
        self.raw_notice.setText(
            self._tr(
                "Жадваллар жорий benchmarkнинг хотирадаги ечимига тегишли; уларни CSV экспорт орқали сақлаш мумкин.",
                "Tables belong to the in-memory solution of the current benchmark and can be saved by CSV export.",
            )
        )
        for title, (headers, rows) in base_result_tables(
            self.base_result, self.language
        ).items():
            panel = TablePanel(title, minimum_height=500, language=self.language)
            panel.set_data(headers, rows)
            self.raw_tabs.addTab(panel, title)

    def _refresh_chart_panels(self) -> None:
        for key, panels in self.chart_panels.items():
            path = self.chart_paths.get(key)
            for panel in panels:
                panel.set_image(path)

    def _rebuild_gallery(self) -> None:
        while self.gallery_layout.count():
            item = self.gallery_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.chart_paths:
            self.gallery_notice.setText(
                self._tr(
                    "Асосий ечим ҳисоблангач биринчи графиклар пайдо бўлади.",
                    "Charts appear after the base solution is computed.",
                )
            )
            return
        self.gallery_notice.setText(
            self._tr(
                "Графиклар олдиндан тайёрланган файллардан эмас, жорий benchmark натижаларидан қурилди.",
                "Charts were generated from current benchmark results, not from prebuilt files.",
            )
        )
        rows: list[QHBoxLayout] = []
        ordered = [key for key in CHART_INFO if key in self.chart_paths]
        for index, key in enumerate(ordered):
            if index % 2 == 0:
                row = QHBoxLayout()
                row.setSpacing(14)
                rows.append(row)
                self.gallery_layout.addLayout(row)
            title, caption = chart_info(key, self.language)
            tile = FigureTile(
                index + 1, title, caption, self.chart_paths[key], self.language
            )
            tile.clicked.connect(
                open_figure_dialog(
                    self, title, caption, self.chart_paths[key], self.language
                )
            )
            rows[-1].addWidget(tile, 1)
        if len(ordered) % 2:
            spacer = QWidget()
            rows[-1].addWidget(spacer, 1)

    # ---------------------------------------------------------------- export
    def export_results(self) -> None:
        if self.base_result is None or self.benchmark_raw is None:
            return
        parent = QFileDialog.getExistingDirectory(
            self,
            self._tr("Натижа пакетини сақлаш папкаси", "Folder for the result package"),
        )
        if not parent:
            return
        safe_id = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in str(self.benchmark_raw["benchmark_id"])
        )
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = Path(parent) / f"cti_rlex_{safe_id}_{stamp}"
        try:
            (target / "tables").mkdir(parents=True)
            (target / "charts").mkdir(parents=True)
            (target / "base_solution.json").write_text(
                json.dumps(self.base_result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if self.full_analysis:
                (target / "extended_analysis.json").write_text(
                    json.dumps(self.full_analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            tables = {
                "allocation": allocation_table(
                    self.benchmark_raw, self.base_result, self.language
                ),
                **base_result_tables(self.base_result, self.language),
            }
            if self.full_analysis:
                tables.update(
                    {
                        "method_comparison": method_table(self.full_analysis, self.language),
                        "recourse_frontier": recourse_table(
                            self.benchmark_raw, self.full_analysis, self.language
                        ),
                        "sensitivity_main_effects": sensitivity_main_effects(
                            self.full_analysis, self.language
                        ),
                    }
                )
            for name, (headers, rows) in tables.items():
                filename = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
                with (target / "tables" / f"{filename}.csv").open(
                    "w", encoding="utf-8-sig", newline=""
                ) as stream:
                    writer = csv.writer(stream)
                    writer.writerow(headers)
                    writer.writerows(rows)
            for key, png in self.chart_paths.items():
                shutil.copy2(png, target / "charts" / f"{key}.png")
                svg = png.with_suffix(".svg")
                if svg.exists():
                    shutil.copy2(svg, target / "charts" / f"{key}.svg")
            manifest = {
                "format": "cti-rlex-export-v1",
                "benchmark_id": self.benchmark_raw["benchmark_id"],
                "benchmark_file": str(self.current_benchmark),
                "created_local": datetime.now().astimezone().isoformat(),
                "contains_extended_analysis": self.full_analysis is not None,
                "interface_language": self.language,
                "chart_keys": sorted(self.chart_paths),
            }
            (target / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            QMessageBox.critical(
                self, self._tr("Экспорт хатоси", "Export error"), str(exc)
            )
            return
        QMessageBox.information(
            self,
            self._tr("Экспорт тайёр", "Export complete"),
            self._tr("Натижа пакети сақланди:", "Result package saved to:")
            + f"\n{target}",
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # --------------------------------------------------------------- dialogs
    def show_about(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self._tr("Лойиҳа ҳақида", "About the project"))
        dialog.resize(650, 520)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(
            "<h2>CTI-RLex Studio</h2>"
            "<p><b>Claimant-centred Temporally Invariant Robust Leximin Allocation</b></p>"
            + self._tr(
                "<p>Йўқотишли, кўп манбали ирригация DAG тармоқларида сценарий–давр робаст "
                "кафолатлари ва чегараланган операцион қайта мослашувни ҳисоблаш, таққослаш ва "
                "текшириш учун очиқ манбали илмий дастур.</p>"
                "<p>GUI барча натижаларни танланган benchmarkдан ҳисоблайди; ташқи ишчи папкалар "
                "ёки олдиндан тайёрланган натижаларга боғлиқ эмас.</p>"
                "<hr><p><b>Версия:</b> 0.3.0<br>"
                "<b>Муаллиф:</b> Adilbay Kudaybergenov<br>"
                "<b>Ҳисоблаш ядроси:</b> Python, SciPy HiGHS, NumPy, NetworkX<br>"
                "<b>GUI:</b> PyQt6 ва Matplotlib</p>",
                "<p>Open-source scientific software for computing, comparing and validating "
                "scenario–period robust guarantees and bounded operational recourse in lossy, "
                "multi-source irrigation DAGs.</p>"
                "<p>The GUI computes every result from the selected benchmark and does not depend "
                "on external working folders or precomputed results.</p>"
                "<hr><p><b>Version:</b> 0.3.0<br>"
                "<b>Author:</b> Adilbay Kudaybergenov<br>"
                "<b>Computational core:</b> Python, SciPy HiGHS, NumPy, NetworkX<br>"
                "<b>GUI:</b> PyQt6 and Matplotlib</p>",
            )
        )
        close = QPushButton(self._tr("Ёпиш", "Close"))
        close.setObjectName("PrimaryButton")
        close.clicked.connect(dialog.accept)
        layout.addWidget(browser)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def show_guide(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self._tr("GUI фойдаланиш қўлланмаси", "GUI user guide"))
        dialog.resize(820, 690)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(
            self._tr(
                "<h2>GUI фойдаланиш қўлланмаси</h2>"
                "<h3>1. Benchmark очиш</h3>"
                "<p><b>Файл → Benchmarkни очиш…</b> ёки <b>Ctrl+O</b>. Файл CTI-RLex benchmark "
                "шаблони майдонлари ва математик мувофиқлик бўйича текширилади.</p>"
                "<h3>2. Асосий ечим</h3>"
                "<p><b>Асосий ечим</b> ёки <b>Ctrl+R</b> талабгор кафолатлари, мақсад "
                "функциялари, оқимлар, манба киримлари ва сценарий–давр нисбатларини ҳисоблайди.</p>"
                "<h3>3. Кенгайтирилган таҳлил</h3>"
                "<p><b>Ctrl+Shift+R</b> таянч усуллар, қайта мослашув фронти, манбалар абляцияси, "
                "сезгирлик ҳолатлари, терминал инвариантлиги ва масштабланишни фон режимида ҳисоблайди.</p>"
                "<h3>4. Натижалар</h3><ul>"
                "<li>талабгорлар тақсимоти ва адолат;</li>"
                "<li>самарадорлик–адолат компромисси;</li>"
                "<li>қайта мослашув ва вақт бўйича танқислик;</li>"
                "<li>манбалар фаоллиги, сув баланси ва критиклик;</li>"
                "<li>робастлик сезгирлиги ва сонли аудит.</li></ul>"
                "<h3>5. Экспорт</h3>"
                "<p><b>Файл → Натижа пакетини экспорт қилиш…</b> ёки <b>Ctrl+E</b>. Ҳар бир ишга "
                "тушириш натижаси алоҳида вақт белгили папкага JSON, CSV, PNG, SVG ва manifest билан сақланади.</p>"
                "<h3>6. Тилни алмаштириш</h3>"
                "<p>Юқори панелдаги <b>ЎЗБ / ENG</b> танлагичи интерфейс, жадвал ва графикларни "
                "дастурни қайта ишга туширмасдан алмаштиради.</p>"
                "<h3>7. Илмий талқин</h3>"
                "<p>GUI ҳисобланган benchmark натижаларини кўрсатади. Уларни реал операцион "
                "кузатув сифатида талқин қилишдан олдин benchmark келиб чиқиши ва чекловларини текширинг.</p>",
                "<h2>GUI user guide</h2>"
                "<h3>1. Open a benchmark</h3>"
                "<p>Use <b>File → Open benchmark…</b> or <b>Ctrl+O</b>. The file is checked for "
                "required CTI-RLex template fields and mathematical consistency.</p>"
                "<h3>2. Base solution</h3>"
                "<p><b>Base solution</b> or <b>Ctrl+R</b> computes claimant guarantees, objectives, "
                "flows, source injections and scenario–period ratios.</p>"
                "<h3>3. Extended analysis</h3>"
                "<p><b>Ctrl+Shift+R</b> runs baseline methods, the recourse frontier, source ablation, "
                "sensitivity cases, terminal invariance and scalability in the background.</p>"
                "<h3>4. Results</h3><ul>"
                "<li>claimant allocation and fairness;</li>"
                "<li>efficiency–fairness trade-off;</li>"
                "<li>recourse and temporal shortage;</li>"
                "<li>source activation, water balance and criticality;</li>"
                "<li>robustness sensitivity and numerical audit.</li></ul>"
                "<h3>5. Export</h3>"
                "<p>Use <b>File → Export result package…</b> or <b>Ctrl+E</b>. Every run is stored "
                "in a separate timestamped folder with JSON, CSV, PNG, SVG and a manifest.</p>"
                "<h3>6. Change language</h3>"
                "<p>The <b>ЎЗБ / ENG</b> selector in the top bar switches the interface, tables and "
                "charts without restarting the application.</p>"
                "<h3>7. Scientific interpretation</h3>"
                "<p>The GUI displays computed benchmark outcomes. Review benchmark provenance and "
                "limitations before interpreting them as observations of real operations.</p>",
            )
        )
        close = QPushButton(self._tr("Ёпиш", "Close"))
        close.setObjectName("PrimaryButton")
        close.clicked.connect(dialog.accept)
        layout.addWidget(browser)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    # -------------------------------------------------------------- settings
    def _retranslate_actions(self) -> None:
        self.open_action.setText(self._tr("Benchmarkни очиш…", "Open benchmark…"))
        self.reload_action.setText(
            self._tr("Benchmarkни қайта юклаш", "Reload benchmark")
        )
        self.export_action.setText(
            self._tr("Натижа пакетини экспорт қилиш…", "Export result package…")
        )
        self.exit_action.setText(self._tr("Чиқиш", "Exit"))
        self.solve_action.setText(
            self._tr("Асосий CTI-RLex ечимини ҳисоблаш", "Compute base CTI-RLex solution")
        )
        self.full_analysis_action.setText(
            self._tr("Кенгайтирилган таҳлил", "Extended analysis")
        )
        self.about_action.setText(self._tr("Лойиҳа ҳақида", "About the project"))
        self.guide_action.setText(
            self._tr("GUI фойдаланиш қўлланмаси", "GUI user guide")
        )

    def _language_changed(self, index: int) -> None:
        language = normalize_language(self.language_combo.itemData(index))
        if language == self.language:
            return
        busy = any(
            worker is not None and worker.isRunning()
            for worker in (self.solve_worker, self.analysis_worker)
        )
        if busy:
            QMessageBox.information(
                self,
                self._tr("Ҳисоблаш давом этмоқда", "Computation in progress"),
                self._tr(
                    "Тилни жорий ҳисоблаш якунлангач алмаштиринг.",
                    "Change the interface language after the current computation finishes.",
                ),
            )
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(0 if self.language == "uz" else 1)
            self.language_combo.blockSignals(False)
            return
        self.language = language
        self.settings.setValue("ui_language", language)
        self._rebuild_interface()

    def _rebuild_interface(self) -> None:
        page_index = self.stack.currentIndex() if hasattr(self, "stack") else 0
        old_central = self.takeCentralWidget()
        old_nav_group = getattr(self, "nav_group", None)
        if old_nav_group is not None:
            old_nav_group.deleteLater()
        if old_central is not None:
            old_central.deleteLater()

        self.base_gates = []
        self.full_gates = []
        self.chart_panels = {}
        self.nav_buttons = []
        self.menuBar().clear()
        self._retranslate_actions()
        self._build_menu()
        self._build_shell()
        self._build_pages()

        page_index = min(max(page_index, 0), self.stack.count() - 1)
        self.stack.setCurrentIndex(page_index)
        self.nav_buttons[page_index].setChecked(True)
        self._set_compute_enabled(self.current_benchmark is not None)
        self.export_action.setEnabled(self.base_result is not None)

        if self.benchmark_raw is None or self.current_benchmark is None:
            self.statusBar().showMessage(
                self._tr("Интерфейс тили ўзбекчага алмашди", "Interface language changed to English"),
                5000,
            )
            return

        self.path_chip.setText(str(self.current_benchmark))
        self.path_chip.setToolTip(str(self.current_benchmark))
        self.window_title.setText(
            str(self.benchmark_raw.get("title", "CTI-RLex benchmark"))
        )
        self._update_benchmark_view()
        try:
            if self.full_analysis is not None:
                self.chart_paths = self.chart_store.render_full(
                    self.benchmark_raw, self.full_analysis, self.language
                )
            elif self.base_result is not None:
                self.chart_paths = self.chart_store.render_base(
                    self.benchmark_raw, self.base_result, self.language
                )
            else:
                self.chart_paths = {
                    "network": self.chart_store.network(self.benchmark_raw, self.language)
                }
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(
                self._tr("Графикларни таржима қилиш хатоси: ", "Chart-localization error: ")
                + str(exc),
                8000,
            )

        if self.base_result is not None:
            self.allocation_panel.set_data(
                *allocation_table(self.benchmark_raw, self.base_result, self.language)
            )
            for gate in self.base_gates:
                gate.set_available(True)
        if self.full_analysis is not None:
            self._populate_full_results(self.full_analysis)
            for gate in self.full_gates:
                gate.set_available(True)

        self._update_dashboard()
        self._update_raw_results()
        self._refresh_chart_panels()
        self._rebuild_gallery()
        if self.full_analysis is not None:
            state = self._tr("Кенгайтирилган таҳлил тайёр", "Extended analysis ready")
        elif self.base_result is not None:
            state = self._tr("Асосий ечим тайёр", "Base solution ready")
        else:
            state = self._tr("Benchmark тайёр", "Benchmark ready")
        self.sidebar_status.setText(f"{self.benchmark_raw['benchmark_id']}\n{state}")
        self.statusBar().showMessage(
            self._tr("Интерфейс тили ўзбекчага алмашди", "Interface language changed to English"),
            5000,
        )

    def _set_compute_enabled(self, enabled: bool) -> None:
        self.solve_button.setEnabled(enabled)
        self.analysis_button.setEnabled(enabled)
        self.solve_action.setEnabled(enabled)
        self.full_analysis_action.setEnabled(enabled)

    def _last_benchmark(self) -> Path | None:
        value = self.settings.value("last_benchmark", "")
        return Path(str(value)) if value else None

    def _recent_files(self) -> list[Path]:
        value = self.settings.value("recent_benchmarks", [])
        if isinstance(value, str):
            value = [value]
        return [Path(str(item)) for item in value if Path(str(item)).exists()]

    def _update_recent(self, path: Path) -> None:
        recent = [item for item in self._recent_files() if item != path]
        recent.insert(0, path)
        self.settings.setValue("recent_benchmarks", [str(item) for item in recent[:8]])
        self.settings.setValue("last_benchmark", str(path))
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = self._recent_files()
        if not recent:
            action = self.recent_menu.addAction(self._tr("Рўйхат бўш", "No recent files"))
            action.setEnabled(False)
            return
        for path in recent:
            action = self.recent_menu.addAction(path.name + " — " + str(path.parent))
            action.triggered.connect(lambda _checked=False, item=path: self.load_benchmark(item))

    def _restore_window_state(self) -> None:
        geometry = self.settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("window_geometry", self.saveGeometry())
        if self.analysis_worker is not None and self.analysis_worker.isRunning():
            answer = QMessageBox.question(
                self,
                self._tr("Ҳисоблаш давом этмоқда", "Computation in progress"),
                self._tr(
                    "Кенгайтирилган таҳлилни бекор қилиб GUI’ни ёпасизми?",
                    "Cancel the extended analysis and close the GUI?",
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.analysis_worker.cancel()
            if not self.analysis_worker.wait(5000):
                QMessageBox.information(
                    self,
                    self._tr("Жорий LP ечими тугатилмоқда", "Current LP solve is finishing"),
                    self._tr(
                        "Хавфсиз тўхташ учун жорий ечим якунланиши керак. Бироздан кейин қайта ёпинг.",
                        "The current solve must finish before a safe stop. Try closing again shortly.",
                    ),
                )
                event.ignore()
                return
        if self.solve_worker is not None and self.solve_worker.isRunning():
            self.solve_worker.wait(5000)
        self.chart_store.close()
        super().closeEvent(event)
