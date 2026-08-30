"""Reusable visual components for the CTI-RLex desktop interface."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QEvent, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QImageReader,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .i18n import DEFAULT_LANGUAGE, normalize_language, pick


def clear_layout(layout: QVBoxLayout | QHBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            clear_layout(child)  # type: ignore[arg-type]


class NumericItem(QStandardItem):
    """Table item with numeric sorting when possible."""

    def __init__(self, value: Any, language: str = DEFAULT_LANGUAGE) -> None:
        if value is None:
            display = ""
        elif isinstance(value, bool):
            display = (
                pick(language, "Ҳа", "Yes") if value else pick(language, "Йўқ", "No")
            )
        elif isinstance(value, float):
            if abs(value) and (abs(value) < 1e-4 or abs(value) >= 1e6):
                display = f"{value:.3e}"
            else:
                display = f"{value:.6f}".rstrip("0").rstrip(".")
        else:
            display = str(value)
        super().__init__(display)
        self.raw_value = value
        self.setEditable(False)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other: QStandardItem) -> bool:
        if isinstance(other, NumericItem):
            try:
                return float(self.raw_value) < float(other.raw_value)
            except (TypeError, ValueError):
                pass
        return super().__lt__(other)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        description = QLabel(subtitle)
        description.setObjectName("PageSubtitle")
        description.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(description)


class MetricCard(QFrame):
    def __init__(self, label: str, value: str = "—", accent: str = "") -> None:
        super().__init__()
        self.setObjectName("MetricCard")
        self.setMinimumWidth(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(17, 15, 17, 14)
        layout.setSpacing(3)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.label_label = QLabel(label)
        self.label_label.setObjectName("MetricLabel")
        self.accent_label = QLabel(accent)
        self.accent_label.setObjectName("MetricAccent")
        self.accent_label.setWordWrap(True)
        layout.addWidget(self.value_label)
        layout.addWidget(self.label_label)
        layout.addWidget(self.accent_label)

    def set_value(self, value: str, accent: str | None = None) -> None:
        self.value_label.setText(value)
        if accent is not None:
            self.accent_label.setText(accent)


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("Card")
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(17, 16, 17, 17)
        self.layout_box.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            self.layout_box.addWidget(label)
        if subtitle:
            label = QLabel(subtitle)
            label.setObjectName("CardSubtitle")
            label.setWordWrap(True)
            self.layout_box.addWidget(label)


class Notice(QLabel):
    def __init__(self, text: str, warning: bool = False) -> None:
        super().__init__(text)
        self.setObjectName("NoticeWarn" if warning else "NoticeInfo")
        self.setWordWrap(True)


class DataTable(QTableView):
    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        super().__init__()
        self.language = normalize_language(language)
        self._headers: list[str] = []
        self._rows: list[list[Any]] = []
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.setWordWrap(False)

    def set_data(self, headers: list[str], rows: list[list[Any]]) -> None:
        self.setSortingEnabled(False)
        self._headers = list(headers)
        self._rows = [list(row) for row in rows]
        model = QStandardItemModel(len(rows), len(headers), self)
        model.setHorizontalHeaderLabels(headers)
        for row_index, row in enumerate(rows):
            for column_index in range(len(headers)):
                value = row[column_index] if column_index < len(row) else ""
                item = NumericItem(value, self.language)
                if row_index % 2:
                    item.setBackground(QColor("#F8FAFC"))
                model.setItem(row_index, column_index, item)
        self.setModel(model)
        self.resizeColumnsToContents()
        for column in range(len(headers)):
            self.setColumnWidth(column, min(max(self.columnWidth(column), 95), 310))
        self.setSortingEnabled(True)

    def export_csv(self, parent: QWidget, suggested_name: str) -> None:
        target, _ = QFileDialog.getSaveFileName(
            parent,
            pick(self.language, "Жадвални CSV сифатида сақлаш", "Save table as CSV"),
            suggested_name,
            "CSV files (*.csv)",
        )
        if not target:
            return
        try:
            with Path(target).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(self._headers)
                writer.writerows(self._rows)
        except OSError as exc:
            QMessageBox.critical(
                parent, pick(self.language, "Сақлаш хатоси", "Save error"), str(exc)
            )


class TablePanel(QFrame):
    def __init__(
        self,
        title: str,
        caption: str = "",
        minimum_height: int = 310,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__()
        self.language = normalize_language(language)
        self.setObjectName("TablePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 14, 15, 15)
        layout.setSpacing(9)
        header = QHBoxLayout()
        labels = QVBoxLayout()
        labels.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("CardSubtitle")
        self.caption_label.setWordWrap(True)
        labels.addWidget(self.title_label)
        if caption:
            labels.addWidget(self.caption_label)
        header.addLayout(labels, 1)
        self.export_button = QPushButton(pick(self.language, "CSV экспорт", "Export CSV"))
        self.export_button.setObjectName("GhostButton")
        header.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        self.table = DataTable(self.language)
        self.table.setMinimumHeight(minimum_height)
        layout.addWidget(self.table)
        self.export_button.clicked.connect(self._export)

    def set_data(self, headers: list[str], rows: list[list[Any]]) -> None:
        self.table.set_data(headers, rows)

    def load_csv(self, path: Path) -> None:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        if rows:
            self.set_data(rows[0], rows[1:])
        else:
            self.set_data([], [])

    def _export(self) -> None:
        safe = "_".join(self.title_label.text().split()) + ".csv"
        self.table.export_csv(self, safe)


class ImageCanvas(QScrollArea):
    zoom_changed = pyqtSignal(int)

    def __init__(self, path: Path | None = None, language: str = DEFAULT_LANGUAGE) -> None:
        super().__init__()
        self.language = normalize_language(language)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidgetResizable(False)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: white;")
        self.setWidget(self._label)
        self._path: Path | None = None
        self._source_size = QSize(1, 1)
        self._zoom = 1.0
        self._fit = True
        self.viewport().installEventFilter(self)
        if path is not None:
            self.set_image(path)

    @property
    def path(self) -> Path | None:
        return self._path

    def set_image(self, path: Path | None) -> None:
        self._path = path
        self._zoom = 1.0
        self._fit = True
        if path is None or not path.exists():
            self._label.setText(pick(self.language, "Расм топилмади", "Image not found"))
            self._label.resize(480, 220)
            return
        reader = QImageReader(str(path))
        self._source_size = reader.size()
        if not self._source_size.isValid():
            self._source_size = QSize(1200, 800)
        self._render()

    def set_fit(self) -> None:
        self._fit = True
        self._zoom = 1.0
        self._render()

    def zoom_in(self) -> None:
        self._fit = False
        self._zoom = min(3.0, self._zoom * 1.2)
        self._render()

    def zoom_out(self) -> None:
        self._fit = False
        self._zoom = max(0.25, self._zoom / 1.2)
        self._render()

    def actual_size(self) -> None:
        self._fit = False
        self._zoom = 1.0
        self._render(actual=True)

    def _target_width(self, actual: bool = False) -> int:
        if actual:
            return self._source_size.width()
        viewport_width = max(520, self.viewport().width() - 18)
        if self._fit:
            return min(viewport_width, self._source_size.width())
        return int(min(self._source_size.width(), max(280, viewport_width * self._zoom)))

    def _render(self, actual: bool = False) -> None:
        if self._path is None or not self._path.exists():
            return
        width = self._target_width(actual)
        ratio = self._source_size.height() / max(self._source_size.width(), 1)
        height = max(1, int(width * ratio))
        reader = QImageReader(str(self._path))
        reader.setAutoTransform(True)
        reader.setScaledSize(QSize(width, height))
        image = reader.read()
        if image.isNull():
            self._label.setText(reader.errorString())
            return
        pixmap = QPixmap.fromImage(image)
        self._label.setPixmap(pixmap)
        self._label.resize(pixmap.size())
        percent = round(100 * width / max(self._source_size.width(), 1))
        self.zoom_changed.emit(percent)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Type.Resize and self._fit:
            self._render()
        return super().eventFilter(watched, event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_in() if event.angleDelta().y() > 0 else self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)


class ImagePanel(QFrame):
    def __init__(
        self,
        title: str,
        caption: str,
        path: Path | None,
        minimum_height: int = 500,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__()
        self.language = normalize_language(language)
        self.setObjectName("ImagePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 14, 15, 15)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        caption_label = QLabel(caption)
        caption_label.setObjectName("CardSubtitle")
        caption_label.setWordWrap(True)
        title_box.addWidget(title_label)
        title_box.addWidget(caption_label)
        toolbar.addLayout(title_box, 1)
        self.zoom_label = QLabel("—")
        self.zoom_label.setObjectName("CardSubtitle")
        toolbar.addWidget(self.zoom_label)
        for text, callback in (
            ("−", self._zoom_out),
            (pick(self.language, "Мослаш", "Fit"), self._fit),
            ("+", self._zoom_in),
            (pick(self.language, "Алоҳида очиш", "Open separately"), self._open),
            (pick(self.language, "Нусха сақлаш", "Save a copy"), self._save),
        ):
            button = QToolButton()
            button.setText(text)
            button.setObjectName("GhostButton")
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.canvas = ImageCanvas(path, self.language)
        self.canvas.setMinimumHeight(minimum_height)
        self.canvas.zoom_changed.connect(lambda value: self.zoom_label.setText(f"{value}%"))
        layout.addWidget(self.canvas)

    def set_image(self, path: Path | None) -> None:
        self.canvas.set_image(path)

    def _zoom_in(self) -> None:
        self.canvas.zoom_in()

    def _zoom_out(self) -> None:
        self.canvas.zoom_out()

    def _fit(self) -> None:
        self.canvas.set_fit()

    def _open(self) -> None:
        if self.canvas.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.canvas.path)))

    def _save(self) -> None:
        path = self.canvas.path
        if path is None:
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            pick(self.language, "Расм нусхасини сақлаш", "Save a copy of the image"),
            path.name,
            "PNG image (*.png);;All files (*)",
        )
        if target:
            try:
                shutil.copy2(path, target)
            except OSError as exc:
                QMessageBox.critical(
                    self, pick(self.language, "Сақлаш хатоси", "Save error"), str(exc)
                )


class AvailabilityPanel(QWidget):
    """Switch between computed content and an explicit unavailable state."""

    def __init__(
        self,
        content: QWidget,
        title: str = "Натижа ҳали ҳисобланмаган",
        message: str = (
            "Ушбу саҳифа учун зарур ҳисоблашни юқоридаги тугма орқали ишга туширинг. "
            "Натижалар фақат жорий benchmarkдан олинади."
        ),
    ) -> None:
        super().__init__()
        self.content = content
        self.placeholder = Card(title)
        description = QLabel(message)
        description.setWordWrap(True)
        description.setObjectName("CardSubtitle")
        self.placeholder.layout_box.addWidget(description)
        layout = QStackedLayout(self)
        layout.addWidget(self.placeholder)
        layout.addWidget(content)
        self._stack = layout
        self.set_available(False)

    def set_available(self, available: bool) -> None:
        self._stack.setCurrentWidget(self.content if available else self.placeholder)


class FigureDialog(QDialog):
    def __init__(
        self,
        title: str,
        caption: str,
        path: Path,
        parent: QWidget | None = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1220, 820)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(
            ImagePanel(title, caption, path, minimum_height=690, language=language)
        )


class FigureTile(QFrame):
    clicked = pyqtSignal()

    def __init__(
        self,
        number: int,
        title: str,
        caption: str,
        path: Path,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__()
        language = normalize_language(language)
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 12)
        layout.setSpacing(7)
        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedHeight(185)
        preview.setStyleSheet("background: #F8FAFC; border-radius: 8px;")
        reader = QImageReader(str(path))
        size = reader.size()
        if size.isValid():
            target_width = min(430, max(1, int(185 * size.width() / max(size.height(), 1))))
            reader.setScaledSize(QSize(target_width, 185))
        image = reader.read()
        if not image.isNull():
            preview.setPixmap(QPixmap.fromImage(image))
        else:
            preview.setText(pick(language, "Олдиндан кўриш мавжуд эмас", "Preview unavailable"))
        label = QLabel(
            pick(language, f"{number}-расм. {title}", f"Figure {number}. {title}")
        )
        label.setObjectName("CardTitle")
        desc = QLabel(caption)
        desc.setObjectName("CardSubtitle")
        desc.setWordWrap(True)
        layout.addWidget(preview)
        layout.addWidget(label)
        layout.addWidget(desc)
        layout.addStretch()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def make_page() -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setObjectName("PageScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(24, 22, 24, 26)
    layout.setSpacing(15)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    scroll.setWidget(content)
    return scroll, content, layout


def open_figure_dialog(
    parent: QWidget,
    title: str,
    caption: str,
    path: Path,
    language: str = DEFAULT_LANGUAGE,
) -> Callable[[], None]:
    def callback() -> None:
        dialog = FigureDialog(title, caption, path, parent, language)
        dialog.exec()

    return callback
