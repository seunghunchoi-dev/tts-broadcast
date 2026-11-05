"""운영자용 화면 (Qt / PySide6, LGPL-3.0). PySide6 가 없으면 main.py 가 gui.py(tkinter)를 사용."""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QDate, QEasingCurve, QObject, QPointF, QPropertyAnimation, QSize, Qt, QTime,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDateEdit, QDialog, QFileDialog, QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSizePolicy,
                               QScrollArea, QSlider, QSpinBox, QSystemTrayIcon, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit,
                               QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import __version__, autostart, backup
from .instance import ACTIVATE_SERVER
from .audio import ALERT_PRESETS, CHIME_PRESETS, play_wav
from .broadcaster import PRIORITY_EMERGENCY, PRIORITY_NAMES, Announcement, parse_priority
from .compliance import check as compliance_check
from .compliance import disclosure_ok, in_quiet_hours, license_notice, notice_html, quiet_finding
from .config import resolve_path
from .engines import available_engines
from .gui import C, EVENT_LABELS, EVENT_TAGS, FIELD_HINTS, LEVEL_LABELS, PAGES
from .scheduler import DAY_NAMES, describe
from .textnorm import english_leftovers, normalize

log = logging.getLogger(__name__)

TAG_COLORS = {"bad": C["danger"], "warn": C["warn"], "ok": C["ok"], "live": C["primary"], "dim": C["muted"]}


def _pct(v: int) -> str:
    return f"{v}%" + (" 압축" if v > 100 else "")


def _semitone(v: int) -> str:
    return "기본" if v == 0 else f"{v:+d} 반음"


# 엔진 종류별 음성 조절 슬라이더:
# (옵션 키, 이름, 최소, 최대, 기본, 옵션값 = 슬라이더값 / 배율, 값 표시, 설명)
VOICE_CONTROLS = {
    "supertonic": [
        ("speed", "빠르기", 70, 150, 100, 100, lambda v: f"{v}%",
         "말하는 속도. 100%가 보통, 90%는 10% 느리게"),
        ("pitch", "음높이", -6, 6, 0, 1, _semitone,
         "목소리 높낮이(반음 단위). 말 빠르기는 그대로"),
        ("volume", "음량", 20, 200, 100, 100, _pct,
         "100% 초과는 찢어지지 않게 눌러서 더 크게"),
        ("steps", "음질", 2, 16, 8, 1, lambda v: f"{v} 단계",
         "높을수록 깨끗하지만 음성 만드는 시간이 늘어남 (권장 8)"),
        ("silence", "문장 간격", 0, 15, 3, 10, lambda v: f"{v / 10:.1f}초",
         "긴 문구를 나눠 읽을 때 문장 사이에 쉬는 시간"),
    ],
    "sapi": [
        ("rate", "빠르기", -10, 10, 0, 1, lambda v: "기본" if v == 0 else f"{v:+d}",
         "말하는 속도. 0이 보통, -2는 조금 느리게"),
        ("pitch", "음높이", -6, 6, 0, 1, _semitone,
         "목소리 높낮이(반음 단위). 말 빠르기는 그대로"),
        ("volume", "음량", 0, 100, 100, 1, lambda v: f"{v}%",
         "Windows 음성 자체 음량"),
    ],
}
SUPERTONIC_VOICES = [(f"F{i}", f"F{i}  ·  여성 {i}") for i in range(1, 6)] + \
                    [(f"M{i}", f"M{i}  ·  남성 {i}") for i in range(1, 6)]

QSS = """
QWidget { color: #0f172a; }
QMainWindow, #content, #page, #pageViewport { background: #f1f5f9; }
QScrollArea#pageScroll { border: none; background: transparent; }
#sidebar { background: #0f172a; }
#brandTitle { color: white; font-size: 13pt; font-weight: bold; }
#brandSub { color: #94a3b8; font-size: 8pt; }
#navSection { color: #475569; font-size: 8pt; font-weight: bold; }
QPushButton#nav { text-align: left; padding: 10px 14px; border: none; border-radius: 8px;
                  color: #94a3b8; background: transparent; font-size: 10.5pt; }
QPushButton#nav:hover { background: #1e293b; color: #e2e8f0; }
QPushButton#nav:checked { background: #2563eb; color: white; font-weight: bold; }
#sideFacility { color: #cbd5e1; font-size: 9pt; font-weight: bold; }
#sideVersion { color: #475569; font-size: 8pt; }
#pageTitle { font-size: 19pt; font-weight: bold; }
#pageSub, #muted { color: #64748b; }
#clock { color: #64748b; font-size: 10pt; }
#onair { border-radius: 15px; padding: 5px 16px; font-weight: bold; }
#onair[live="true"] { background: #dc2626; color: white; border-radius: 15px; }
#onair[live="false"] { background: #e2e8f0; color: #64748b; border-radius: 15px; }
QFrame#card { background: white; border: 1px solid #e2e8f0; border-radius: 12px; }
#cardTitle { font-size: 11pt; font-weight: bold; }
#h2 { font-size: 15pt; font-weight: bold; }
#hint { color: #94a3b8; font-size: 9pt; }
#field { color: #334155; font-weight: bold; }
#empty { color: #94a3b8; font-size: 10pt; }

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QTimeEdit, QDateEdit {
    background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 6px 10px;
    selection-background-color: #2563eb; selection-color: white; }
QPlainTextEdit, QTextEdit { padding: 8px 10px; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus,
QTimeEdit:focus, QDateEdit:focus { border: 1px solid #2563eb; background: white; }
QLineEdit:disabled, QComboBox:disabled, QTimeEdit:disabled, QDateEdit:disabled, QSpinBox:disabled {
    color: #94a3b8; background: #f1f5f9; border-color: #e2e8f0; }
QTextEdit[readOnly="true"] { background: #f8fafc; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #e2e8f0; outline: 0; padding: 4px;
    selection-background-color: #eff6ff; selection-color: #1d4ed8; }
QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button,
QDateEdit::up-button, QDateEdit::down-button { width: 18px; border: none; }
QCalendarWidget QWidget { alternate-background-color: #f8fafc; }
QSlider::groove:horizontal { height: 6px; background: #e2e8f0; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #2563eb; border-radius: 3px; }
QSlider::handle:horizontal { background: white; border: 2px solid #2563eb; width: 14px; height: 14px;
    margin: -6px 0; border-radius: 9px; }
QSlider::handle:horizontal:hover { background: #eff6ff; }
QSlider::sub-page:horizontal:disabled { background: #cbd5e1; }
QSlider::handle:horizontal:disabled { border-color: #cbd5e1; }
#sliderVal { color: #1d4ed8; font-weight: bold; min-width: 76px; }

QPushButton { background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 7px 16px; }
QPushButton:hover { background: #f1f5f9; }
QPushButton:pressed { background: #e2e8f0; }
QPushButton:disabled { color: #94a3b8; background: #f1f5f9; border-color: #e2e8f0; }
QPushButton[kind="primary"] { background: #2563eb; color: white; border-color: #2563eb; font-weight: bold; }
QPushButton[kind="primary"]:hover, QPushButton[kind="primary"]:pressed { background: #1d4ed8; border-color: #1d4ed8; }
QPushButton[kind="danger"] { background: #dc2626; color: white; border-color: #dc2626; font-weight: bold; }
QPushButton[kind="danger"]:hover, QPushButton[kind="danger"]:pressed { background: #b91c1c; border-color: #b91c1c; }
QPushButton[kind="primary"]:disabled, QPushButton[kind="danger"]:disabled { background: #cbd5e1; border-color: #cbd5e1; }
QPushButton[kind="outline"] { color: #dc2626; border-color: #fca5a5; }
QPushButton[kind="outline"]:hover { background: #fef2f2; }
QPushButton[kind="outline"]:disabled { color: #94a3b8; border-color: #e2e8f0; background: white; }
QPushButton[kind="ghost"] { border: none; background: transparent; color: #64748b; padding: 5px 10px; }
QPushButton[kind="ghost"]:hover { background: #f1f5f9; color: #0f172a; }
QPushButton[kind="link"] { border: none; background: transparent; color: #2563eb; font-weight: bold; padding: 2px 4px; }
QPushButton[kind="link"]:hover { text-decoration: underline; }
QPushButton[kind="chip"] { background: #f8fafc; border: 1px solid #e2e8f0; text-align: left; padding: 9px 12px; }
QPushButton[kind="chip"]:hover { background: #eff6ff; border-color: #93c5fd; color: #1d4ed8; }
QPushButton[big="true"] { padding: 12px 26px; font-size: 12pt; border-radius: 10px; }
QPushButton[kind="seg"] { background: #f8fafc; border-radius: 0; padding: 6px 16px; }
QPushButton[kind="seg"]:hover { background: #eff6ff; }
QPushButton[kind="seg"]:checked { background: #2563eb; color: white; border-color: #2563eb; font-weight: bold; }
QPushButton[kind="seg"][danger="true"]:checked { background: #dc2626; border-color: #dc2626; }
QPushButton[kind="seg"][pos="first"] { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton[kind="seg"][pos="last"] { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
QPushButton[kind="seg"][pos="mid"], QPushButton[kind="seg"][pos="last"] { border-left: none; }
QPushButton[kind="day"] { min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; padding: 0;
                          border-radius: 17px; background: #f8fafc; }
QPushButton[kind="day"]:checked { background: #2563eb; color: white; border-color: #2563eb; font-weight: bold; }

QCheckBox, QRadioButton { spacing: 8px; padding: 2px 0; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #cbd5e1; border-radius: 5px; background: white; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: #2563eb; }
QCheckBox::indicator:checked { background: #2563eb; border-color: #2563eb; image: url(%CHECK%); }
QRadioButton::indicator { width: 17px; height: 17px; border: 1px solid #cbd5e1; border-radius: 9px; background: white; }
QRadioButton::indicator:checked { border: 5px solid #2563eb; width: 9px; height: 9px; }
QCheckBox:disabled, QRadioButton:disabled { color: #94a3b8; }

QTableWidget { background: white; border: none; gridline-color: transparent; outline: 0;
               selection-background-color: #eff6ff; selection-color: #0f172a; alternate-background-color: #fafbfd; }
QTableWidget::item { padding: 0 8px; border-bottom: 1px solid #f1f5f9; }
QHeaderView::section { background: #f8fafc; color: #64748b; font-weight: bold; font-size: 9pt; border: none;
                       border-bottom: 1px solid #e2e8f0; padding: 7px 8px; }
QTreeWidget { border: none; background: white; outline: 0; }
QTreeWidget::item { padding: 6px 4px; border-radius: 6px; }
QTreeWidget::item:hover { background: #f8fafc; }
QTreeWidget::item:selected { background: #eff6ff; color: #1d4ed8; }
QTreeWidget::branch { background: white; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 3px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #cbd5e1; border-radius: 3px; min-width: 30px; }
QScrollBar::handle:hover { background: #94a3b8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QMenu { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: #eff6ff; color: #1d4ed8; }
QMenu::separator { height: 1px; background: #e2e8f0; margin: 4px 8px; }
QToolTip { background: #0f172a; color: white; border: none; padding: 6px 8px; }

#banner { background: #fffbeb; border: 1px solid #fcd34d; border-radius: 10px; }
#bannerText { color: #92400e; }
#note { background: #fffbeb; border: 1px solid #fcd34d; border-radius: 8px; color: #92400e; padding: 9px 12px; }
#subtle { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; }
#toast { background: #0f172a; color: white; border-radius: 10px; padding: 12px 18px; }
#statusbar { background: white; border-top: 1px solid #e2e8f0; }
#statusbar QLabel { color: #64748b; font-size: 9pt; }
#curBox { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; }
#curBox[live="true"] { background: #fef2f2; border-color: #fca5a5; }
#curText { font-size: 12pt; }
#stat { background: white; border: 1px solid #e2e8f0; border-radius: 10px; }
#statNum { font-size: 17pt; font-weight: bold; }
#dlgTitle { color: white; font-size: 13pt; font-weight: bold; }
#dlgSub { color: #e2e8f0; font-size: 9pt; }
QDialog, QMessageBox { background: white; }
QMessageBox QPushButton { min-width: 84px; }
"""


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def _set_prop(w: QWidget, name: str, value) -> None:
    if w.property(name) != value:
        w.setProperty(name, value)
        _repolish(w)


def _logo_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C["primary"]))
    p.drawRoundedRect(0, 0, size, size, size * 0.24, size * 0.24)
    pen = QPen(QColor("white"))
    pen.setWidthF(size * 0.08)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    m = size * 0.22
    p.drawEllipse(int(m), int(m), int(size - 2 * m), int(size - 2 * m))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("white"))
    r = size * 0.11
    p.drawEllipse(int(size / 2 - r), int(size / 2 - r), int(2 * r), int(2 * r))
    p.end()
    return pm


def _glyph_icon(glyph: str) -> QIcon:
    """메뉴 아이콘: 글자 폭이 달라도 같은 크기·위치에 그려 정렬을 맞춘다 (선택 시 흰색)."""
    icon = QIcon()
    for color, state in ((C["side_text"], QIcon.Off), ("white", QIcon.On)):
        pm = QPixmap(40, 40)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(QColor(color))
        p.setFont(QFont("Segoe UI Symbol", 20))
        p.drawText(pm.rect(), Qt.AlignCenter, glyph)
        p.end()
        icon.addPixmap(pm, QIcon.Normal, state)
    return icon


def _check_image() -> str:
    """체크박스 체크 표시 이미지 (QSS 는 image: url() 로만 지정 가능)."""
    path = Path(tempfile.gettempdir()) / "tts_broadcast_check.png"
    pm = QPixmap(34, 34)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("white"))
    pen.setWidthF(4.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(8, 17.5), QPointF(14.5, 24), QPointF(26, 10)])
    p.end()
    pm.save(str(path))
    return path.as_posix()


def button(text: str, kind: str | None = None, slot=None, big: bool = False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if big:
        b.setProperty("big", True)
    b.setCursor(Qt.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def badge(text: str, fg: str = C["primary"], bg: str = C["primary_l"]) -> QLabel:
    lb = QLabel(text)
    lb.setStyleSheet(f"color:{fg}; background:{bg}; border-radius:6px; padding:2px 8px;"
                     f" font-size:9pt; font-weight:bold;")
    lb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lb


def card(title: str | None = None, desc: str | None = None) -> QFrame:
    """흰 바탕 카드. f.head 에 오른쪽 버튼을 붙이고 f.body 에 내용을 넣는다."""
    f = QFrame()
    f.setObjectName("card")
    v = QVBoxLayout(f)
    v.setContentsMargins(18, 14 if title else 18, 18, 18)
    v.setSpacing(12)
    f.head = None
    if title:
        h = QHBoxLayout()
        h.setSpacing(10)
        h.addWidget(label(title, "cardTitle"))
        if desc:
            h.addWidget(label(desc, "hint"))
        h.addStretch(1)
        v.addLayout(h)
        f.head = h
    f.body = v
    return f


def hrow(*widgets, spacing: int = 8, stretch_at: int | None = None) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    h.setContentsMargins(0, 0, 0, 0)
    for i, w in enumerate(widgets):
        if w is None:
            h.addStretch(1)
        elif isinstance(w, int):
            h.addSpacing(w)
        elif hasattr(w, "addWidget") and not isinstance(w, QWidget):
            h.addLayout(w)
        else:
            h.addWidget(w, 1 if i == stretch_at else 0)
    return h


class _Table(QTableWidget):
    def sizeHint(self):
        # 기본 권장 높이(192px)가 페이지를 불필요하게 늘리지 않도록 작게 → 남는 공간을 채움
        return QSize(super().sizeHint().width(), 110)


def table(headers, widths) -> QTableWidget:
    t = _Table(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.verticalHeader().setDefaultSectionSize(34)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setWordWrap(False)
    t.setFocusPolicy(Qt.StrongFocus)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    hh = t.horizontalHeader()
    hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    hh.setHighlightSections(False)
    for i, w in enumerate(widths):
        t.setColumnWidth(i, w)
    hh.setStretchLastSection(True)
    return t


def time_edit(value: str) -> QTimeEdit:
    w = QTimeEdit(QTime.fromString(value.strip(), "H:mm") if value else QTime(9, 0))
    w.setDisplayFormat("HH:mm")
    w.setAlignment(Qt.AlignCenter)
    w.setMinimumWidth(84)
    return w


class Segmented(QWidget):
    """한 개만 선택되는 버튼 묶음 (보통 | 높음 | 긴급)."""
    changed = Signal(str)

    def __init__(self, values, current: str, danger: str | None = None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for i, v in enumerate(values):
            b = button(v, "seg")
            b.setCheckable(True)
            b.setMinimumWidth(max(68, 16 * len(v) + 36))
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(values) - 1 else "mid")
            if v == danger:
                b.setProperty("danger", True)
            b.toggled.connect(lambda on, v=v: on and self.changed.emit(v))
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[v] = b
        self.set(current)

    def get(self) -> str:
        return next((v for v, b in self.buttons.items() if b.isChecked()), "")

    def set(self, value: str) -> None:
        if value in self.buttons:
            self.buttons[value].setChecked(True)


class ElideButton(QPushButton):
    """폭에 맞춰 글자를 '…'로 줄여 보여 주는 버튼 (전체 문구는 툴팁)."""

    def __init__(self, text: str, kind: str, slot):
        super().__init__(text)
        self.full = text
        self.setProperty("kind", kind)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(text)
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.clicked.connect(slot)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.setText(self.fontMetrics().elidedText(self.full, Qt.ElideRight, max(20, self.width() - 32)))


class _Bridge(QObject):
    """방송 스레드 → 화면 스레드 전달."""
    event = Signal(str, object, str)
    call = Signal(object)


class Toast(QLabel):
    """잠깐 떴다 사라지는 알림."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setTextFormat(Qt.RichText)
        self.hide()
        self.fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fx)
        self.anim = QPropertyAnimation(self.fx, b"opacity", self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.timer = QTimer(self, singleShot=True, timeout=self._fade_out)

    def show_message(self, msg: str, kind: str = "ok"):
        dot = {"ok": "#4ade80", "warn": "#fbbf24", "info": "#60a5fa"}.get(kind, "#4ade80")
        self.setText(f'<span style="color:{dot}">●</span>&nbsp;&nbsp;{html.escape(msg)}')
        self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 28, p.height() - self.height() - 56)
        self.raise_()
        self.show()
        self.anim.stop()
        try:
            self.anim.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.anim.setStartValue(self.fx.opacity() if self.isVisible() else 0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(2600)

    def _fade_out(self):
        self.anim.stop()
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.hide)
        self.anim.start()


class BroadcastWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.b = app.broadcaster
        self.bridge = _Bridge()
        self.bridge.event.connect(self._on_event)
        self.bridge.call.connect(lambda fn: fn())
        self.b.add_listener(lambda k, a, m: self.bridge.event.emit(k, a, m))
        self._force_close = False
        self.restart_requested = False
        self._cur_ann = None
        self._cur_started = 0.0
        self._pending_sig = None
        self._live = None
        self._blink = False
        self._stats = {"done": 0, "err": 0, "day": time.strftime("%Y%m%d")}

        self.setWindowTitle("TTS 자동 방송 송출 시스템")
        self.setWindowIcon(QIcon(_logo_pixmap(64)))
        self.resize(1300, 840)
        self.setMinimumSize(1120, 720)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())

        content = QWidget()
        content.setObjectName("content")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_header())
        self.banner = self._build_banner()
        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.setContentsMargins(28, 0, 28, 14)
        bl.addWidget(self.banner)
        self.banner_wrap = bw
        cv.addWidget(bw)
        self.stack = QStackedWidget()
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(28, 0, 14, 20)  # 오른쪽 14px + 페이지 여백 14px = 스크롤바 자리
        sl.addWidget(self.stack)
        cv.addWidget(sw, 1)
        cv.addWidget(self._build_statusbar())
        root.addWidget(content, 1)

        self.pages: dict[str, QWidget] = {}
        self._scrolls: dict[str, QScrollArea] = {}
        for key, builder in (("broadcast", self._build_broadcast_page), ("templates", self._build_template_page),
                             ("schedule", self._build_schedule_page), ("facility", self._build_facility_page),
                             ("engine", self._build_engine_page)):
            page = QWidget()
            page.setObjectName("page")
            builder(page)
            page.layout().setContentsMargins(0, 0, 14, 0)
            # 창이 작으면 글자·칸을 찌그러뜨리지 않고 스크롤
            scroll = QScrollArea()
            scroll.setObjectName("pageScroll")
            scroll.viewport().setObjectName("pageViewport")
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.pages[key] = page
            self._scrolls[key] = scroll
            self.stack.addWidget(scroll)
        self.toast = Toast(central)
        for i, (key, *_) in enumerate(PAGES, 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda k=key: self.show_page(k))
        self.show_page("broadcast")
        self._update_banner()

        if not disclosure_ok(app.config["facility"]):
            self._on_event("warning", None, "AI 음성 고지 미완료: [시설 설정]에서 게시용 안내문을 "
                                            "게시하고 확인 체크를 하세요")
        self._build_tray()
        self.timer = QTimer(self, interval=300, timeout=self._tick)
        self.timer.start()
        self._tick()
        if not app.config.get("license_accepted"):
            QTimer.singleShot(300, self._license_dialog)
        if app.config["active_engine"] != self.b.engine_key:
            QTimer.singleShot(600, lambda: self._warn(
                "엔진 오류",
                f"설정된 엔진 '{app.config['active_engine']}' 을(를) 시작할 수 없어\n"
                f"예비 엔진 '{self.b.engine_key}' 으로 방송합니다.\n\n"
                "원인은 logs\\broadcast.log 를 확인하세요."))

    # ------------------------------------------------------------ 메시지
    def _toast(self, msg: str, kind: str = "ok"):
        self.toast.show_message(msg, kind)

    def _box(self, icon, title: str, text: str, buttons=(("확인", "primary"),), default: int = 0) -> int:
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        made = []
        for name, kind in buttons:
            b = box.addButton(name, QMessageBox.AcceptRole if kind == "primary" else QMessageBox.RejectRole)
            if kind:
                b.setProperty("kind", kind)
            b.setCursor(Qt.PointingHandCursor)
            made.append(b)
        box.setDefaultButton(made[default])
        box.exec()
        return made.index(box.clickedButton()) if box.clickedButton() in made else len(made) - 1

    def _info(self, title, text):
        self._box(QMessageBox.Information, title, text)

    def _warn(self, title, text):
        self._box(QMessageBox.Warning, title, text)

    def _error(self, title, text):
        self._box(QMessageBox.Critical, title, text)

    def _ask(self, title, text, yes="예", no="아니오", danger=False) -> bool:
        return self._box(QMessageBox.Question, title, text,
                         ((no, None), (yes, "danger" if danger else "primary")), default=0) == 1

    def _dialog(self, title: str, subtitle: str, color: str, width: int = 580):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(width)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QFrame()
        head.setObjectName("dlgHead")
        head.setStyleSheet(f"#dlgHead {{ background: {color}; }}")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(24, 18, 24, 16)
        hv.setSpacing(4)
        hv.addWidget(label(title, "dlgTitle"))
        if subtitle:
            hv.addWidget(label(subtitle, "dlgSub", wrap=True))
        v.addWidget(head)
        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 8)
        body.setSpacing(10)
        v.addLayout(body, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(24, 12, 24, 20)
        foot.addStretch(1)
        v.addLayout(foot)
        return dlg, body, foot

    # ------------------------------------------------------------ 골격
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        v = QVBoxLayout(side)
        v.setContentsMargins(14, 22, 14, 18)
        v.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(_logo_pixmap(38 * 2).scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(label("TTS 방송", "brandTitle"))
        brand.addWidget(label("자동 방송 송출 시스템", "brandSub"))
        top = hrow(logo, brand, None, spacing=10)
        top.setContentsMargins(8, 0, 0, 0)
        v.addLayout(top)
        v.addSpacing(22)
        sec = label("메뉴", "navSection")
        sec.setContentsMargins(10, 0, 0, 4)
        v.addWidget(sec)
        self.nav_group = QButtonGroup(self)
        self.nav: dict[str, QPushButton] = {}
        for i, (key, icon, text, _) in enumerate(PAGES, 1):
            b = QPushButton(f"  {text}")
            b.setObjectName("nav")
            b.setIcon(_glyph_icon(icon))
            b.setIconSize(QSize(20, 20))
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"Ctrl+{i}")
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            self.nav[key] = b
            v.addWidget(b)
        v.addStretch(1)
        self.side_facility = label("", "sideFacility", wrap=True)
        self.side_facility.setContentsMargins(10, 0, 0, 0)
        v.addWidget(self.side_facility)
        ver = label(f"버전 {__version__}", "sideVersion")
        ver.setContentsMargins(10, 0, 0, 0)
        v.addWidget(ver)
        self._update_side_facility()
        return side

    def _update_side_facility(self):
        self.side_facility.setText(self.app.config["facility"].get("name") or "시설명 미설정")

    def _build_header(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(28, 22, 28, 16)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.page_title = label("", "pageTitle")
        self.page_sub = label("", "pageSub")
        left.addWidget(self.page_title)
        left.addWidget(self.page_sub)
        h.addLayout(left, 1)
        self.onair = label("", "onair")
        self.onair.setTextFormat(Qt.RichText)
        self.onair.setProperty("live", False)
        h.addWidget(self.onair, 0, Qt.AlignVCenter)
        h.addSpacing(14)
        self.clock = label("", "clock")
        h.addWidget(self.clock, 0, Qt.AlignVCenter)
        return w

    def _build_banner(self) -> QFrame:
        f = QFrame()
        f.setObjectName("banner")
        h = QHBoxLayout(f)
        h.setContentsMargins(16, 9, 12, 9)
        icon = label("⚠")
        icon.setStyleSheet(f"color:{C['warn']}; font-size:13pt;")
        h.addWidget(icon)
        h.addWidget(label("AI 음성 고지가 완료되지 않았습니다.  게시용 안내문을 게시하고 확인 체크를 해 주세요.",
                          "bannerText"), 1)
        h.addWidget(button("시설 설정으로 이동 →", "link", lambda: self.show_page("facility")))
        return f

    def _update_banner(self):
        self.banner_wrap.setVisible(not disclosure_ok(self.app.config["facility"]))

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statusbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(24, 7, 24, 7)
        h.setSpacing(26)
        self.sb_engine, self.sb_queue, self.sb_sched = QLabel(), QLabel(), QLabel()
        self.sb_engine.setTextFormat(Qt.RichText)
        for lb in (self.sb_engine, self.sb_queue, self.sb_sched):
            h.addWidget(lb)
        h.addStretch(1)
        extra = []
        if self.app.watcher:
            extra.append("감시 폴더 켜짐")
        if self.app.api:
            api = self.app.config["api"]
            extra.append(f"API {api['host']}:{api['port']}")
        h.addWidget(QLabel("   ·   ".join(extra)))
        return bar

    def show_page(self, key: str):
        self.nav[key].setChecked(True)
        _, _, title, sub = next(p for p in PAGES if p[0] == key)
        self.page_title.setText(title)
        self.page_sub.setText(sub)
        self.stack.setCurrentWidget(self._scrolls[key])
        if key == "broadcast":
            self.text.setFocus()
        elif key == "schedule":
            self._refresh_sched()

    # ------------------------------------------------------------ 방송
    def _build_broadcast_page(self, page: QWidget):
        g = QGridLayout(page)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(18)
        g.setColumnStretch(0, 3)
        g.setColumnStretch(1, 2)
        g.setColumnMinimumWidth(1, 360)
        g.setRowStretch(1, 1)

        comp = card("방송 문구", "Ctrl+Enter 로 바로 송출")
        self.char_count = label("", "hint")
        comp.head.addWidget(self.char_count)
        comp.head.addWidget(button("발음 사전", "ghost", lambda: self._lexicon_dialog(),
                                   tip="영문·약어·고유명사의 읽는 법을 등록"))
        comp.head.addWidget(button("읽기 확인", "ghost", self._show_reading,
                                   tip="숫자·영문·머리말이 실제로 어떻게 읽히는지 확인"))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("방송할 문구를 입력하세요")
        self.text.setFont(QFont("Malgun Gothic", 13))
        self.text.setFixedHeight(128)
        self.text.textChanged.connect(self._on_text_changed)
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(seq), self.text, activated=self._send, context=Qt.WidgetShortcut)
        comp.body.addWidget(self.text)
        self.eng_warn = QFrame()
        self.eng_warn.setObjectName("banner")
        ew = QHBoxLayout(self.eng_warn)
        ew.setContentsMargins(12, 6, 8, 6)
        self.eng_warn_text = label("", "bannerText", wrap=True)
        ew.addWidget(self.eng_warn_text, 1)
        ew.addWidget(button("발음 등록 →", "link", lambda: self._lexicon_dialog(self._eng_words)))
        self.eng_warn.hide()
        self._eng_words: list[str] = []
        comp.body.addWidget(self.eng_warn)

        self.prio = Segmented(["보통", "높음", "긴급"], "보통", danger="긴급")
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 10)
        self.repeat.setSuffix(" 회")
        self.repeat.setAlignment(Qt.AlignCenter)
        self.repeat.setMinimumWidth(80)
        self.chime = QCheckBox("차임벨")
        self.chime.setChecked(bool(self.app.config["broadcast"].get("chime_start", True)))
        og = QGridLayout()
        og.setHorizontalSpacing(14)
        og.setVerticalSpacing(8)
        og.addWidget(label("우선순위", "field"), 0, 0)
        og.addLayout(hrow(self.prio, None), 0, 1)
        og.addWidget(label("반복", "field"), 1, 0)
        og.addLayout(hrow(self.repeat, 18, self.chime, None), 1, 1)
        comp.body.addLayout(og)
        send = button("▶   방송 송출", "primary", self._send, big=True)
        emg = button("⚠   긴급 방송", "danger", lambda: self._send("긴급"), big=True,
                     tip="진행 중인 방송을 중단하고 즉시 송출")
        comp.body.addLayout(hrow(send, emg, spacing=10, stretch_at=0))

        presets = self.app.config.get("presets") or []
        if presets:
            comp.body.addSpacing(6)
            comp.body.addWidget(label("자주 쓰는 문구", "field"))
            pg = QGridLayout()
            pg.setSpacing(8)
            pg.setColumnStretch(0, 1)
            pg.setColumnStretch(1, 1)
            for i, p in enumerate(presets):
                chip = ElideButton(p, "chip", lambda _=False, t=p: self._fill(t))
                pg.addWidget(chip, i // 2, i % 2)
            comp.body.addLayout(pg)
        comp.body.addStretch(1)
        g.addWidget(comp, 0, 0)

        st = card("송출 상태")
        self.cur_box = QFrame()
        self.cur_box.setObjectName("curBox")
        cb = QVBoxLayout(self.cur_box)
        cb.setContentsMargins(16, 14, 16, 14)
        cb.setSpacing(6)
        self.cur_state = QLabel()
        self.cur_state.setTextFormat(Qt.RichText)
        self.cur_text = label("", "curText", wrap=True)
        self.cur_text.setMinimumHeight(48)
        self.cur_text.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.cur_meta = label("", "muted")
        for w in (self.cur_state, self.cur_text, self.cur_meta):
            cb.addWidget(w)
        st.body.addWidget(self.cur_box)
        self.stop_btn = button("■   현재 방송 중지", "outline", self.b.stop_current)
        st.body.addLayout(hrow(self.stop_btn, button("대기열 비우기", None, self._clear_queue), stretch_at=0))
        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.stat_labels = {}
        for k, text in (("queue", "대기"), ("done", "오늘 송출"), ("err", "오류")):
            box = QFrame()
            box.setObjectName("stat")
            bv = QVBoxLayout(box)
            bv.setContentsMargins(8, 10, 8, 10)
            bv.setSpacing(0)
            num = label("0", "statNum")
            num.setAlignment(Qt.AlignCenter)
            if k == "err":
                num.setStyleSheet(f"color:{C['danger']}")
            cap = label(text, "muted")
            cap.setAlignment(Qt.AlignCenter)
            bv.addWidget(num)
            bv.addWidget(cap)
            self.stat_labels[k] = num
            stats.addWidget(box)
        st.body.addLayout(stats)
        st.body.addStretch(1)
        g.addWidget(st, 0, 1)

        lg = card("방송 기록", "최근 500건")
        lg.head.addWidget(button("지우기", "ghost", lambda: self.log_table.setRowCount(0)))
        self.log_table = table(["시각", "구분", "우선", "출처", "내용"], [76, 104, 52, 104, 200])
        self.log_table.setMinimumHeight(110)
        lg.body.addWidget(self.log_table)
        g.addWidget(lg, 1, 0)

        qc = card("대기열")
        self.queue_badge = badge("0건", C["muted"], C["bg"])
        qc.head.addWidget(self.queue_badge)
        self.queue_stack = QStackedWidget()
        self.pending_table = table(["우선", "출처", "내용"], [58, 96, 200])
        empty = label("대기 중인 방송이 없습니다", "empty")
        empty.setAlignment(Qt.AlignCenter)
        self.queue_stack.addWidget(self.pending_table)
        self.queue_stack.addWidget(empty)
        qc.body.addWidget(self.queue_stack)
        g.addWidget(qc, 1, 1)
        self._on_text_changed()

    def _on_text_changed(self):
        text = self.text.toPlainText().strip()
        n = len(text)
        self.char_count.setText(f"{n}자 · 약 {max(1, round(n / 6))}초" if n else "")
        self._eng_words = english_leftovers(text) if text else []
        if self._eng_words:
            words = ", ".join(f"'{w}'" for w in self._eng_words[:4])
            self.eng_warn_text.setText(f"⚠  영문 {words} 은(는) 어색하게 읽힐 수 있습니다")
        self.eng_warn.setVisible(bool(self._eng_words))

    def _lexicon_dialog(self, prefill=()):
        """발음 사전: 표기 → 읽기. 저장하면 바로 모든 방송에 적용."""
        dlg, lay, foot = self._dialog("발음 사전", "영문·약어·고유명사를 어떻게 읽을지 등록합니다. "
                                               "영문은 대소문자를 가리지 않습니다.", C["primary"], 560)
        t = table(["표기 (문구에 쓰는 글자)", "읽기 (한글)"], [230, 230])
        t.setEditTriggers(QAbstractItemView.AllEditTriggers)
        t.setAlternatingRowColors(False)
        t.setMinimumHeight(300)
        entries = dict(self.app.config.get("pronunciations") or {})
        for w in prefill:
            entries.setdefault(w, "")
        for k, v in entries.items():
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, QTableWidgetItem(k))
            t.setItem(r, 1, QTableWidgetItem(v))
        lay.addWidget(t)

        def add_row():
            t.insertRow(t.rowCount())
            t.setCurrentCell(t.rowCount() - 1, 0)
            t.editItem(t.item(t.rowCount() - 1, 0) or QTableWidgetItem())

        def del_rows():
            for r in sorted({i.row() for i in t.selectedIndexes()}, reverse=True):
                t.removeRow(r)

        test_in = QLineEdit()
        test_in.setPlaceholderText("시험 문구 입력 → 아래에 실제 읽기가 표시됩니다")
        test_out = label("", "muted", wrap=True)

        def collect() -> dict:
            out = {}
            for r in range(t.rowCount()):
                k, v = t.item(r, 0), t.item(r, 1)
                k, v = (k.text().strip() if k else ""), (v.text().strip() if v else "")
                if k and v:
                    out[k] = v
            return out

        def preview():
            from .textnorm import set_lexicon
            set_lexicon(collect())
            try:
                test_out.setText("→ " + normalize(test_in.text()) if test_in.text().strip() else "")
            finally:
                set_lexicon(self.app.config.get("pronunciations"))

        test_in.textChanged.connect(preview)
        t.itemChanged.connect(lambda *_: preview())
        lay.addLayout(hrow(button("＋ 행 추가", None, add_row), button("선택 삭제", "outline", del_rows), None))
        lay.addWidget(test_in)
        lay.addWidget(test_out)
        if prefill:
            r = next((i for i in range(t.rowCount()) if t.item(i, 0).text() == prefill[0]), 0)
            QTimer.singleShot(0, lambda: (t.setCurrentCell(r, 1), t.editItem(t.item(r, 1))))
            test_in.setText(self.text.toPlainText().strip()[:80])

        foot.addWidget(button("취소", None, dlg.reject))
        foot.addWidget(button("저장", "primary", dlg.accept))
        if dlg.exec() == QDialog.Accepted:
            entries = collect()
            self.app.set_pronunciations(entries)
            self._on_text_changed()
            self._toast(f"발음 사전을 저장했습니다 ({len(entries)}건)")

    def _fill(self, text: str):
        self.text.setPlainText(text)
        self.text.setFocus()
        self.text.moveCursor(self.text.textCursor().MoveOperation.End)

    def _clear_queue(self):
        n = self.b.clear_queue()
        self._toast(f"대기열 {n}건을 비웠습니다" if n else "대기열이 비어 있습니다", "info")

    def _show_reading(self):
        text = self.text.toPlainText().strip()
        if not text:
            self._toast("방송 문구를 먼저 입력하세요", "warn")
            return
        ann = Announcement(text=text, priority=parse_priority(self.prio.get()), repeat=self.repeat.value())
        head, body, tail = self.b.compose_parts(ann)
        dlg, lay, foot = self._dialog("실제 송출 내용", "고지·머리말·숫자 읽기 변환이 적용된 최종 문구입니다.",
                                      C["primary"])
        view = QTextEdit()
        view.setReadOnly(True)
        view.setFont(QFont("Malgun Gothic", 12))
        parts = [f'<p>{html.escape(normalize(" ".join(p for p in (head, body) if p)))}</p>']
        for i in range(1, ann.repeat):
            parts.append(f'<p style="color:{C["muted"]}">({i + 1}회) {html.escape(normalize(body))}</p>')
        if tail:
            parts.append(f"<p>{html.escape(normalize(tail))}</p>")
        view.setHtml("".join(parts))
        view.setMinimumHeight(180)
        lay.addWidget(view)
        if ann.repeat > 1:
            lay.addWidget(label("※ 반복 시 고지·머리말은 처음 한 번, 맺음말은 마지막에 한 번만 나갑니다.", "hint"))
        left = english_leftovers(self.b.compose(ann))
        if left:
            lay.addWidget(label(f"⚠  영문 {', '.join(left)} 은(는) 정확히 읽히지 않을 수 있습니다. "
                                "[발음 사전]에 등록하세요.", "note", wrap=True))
        foot.addWidget(button("닫기", "primary", dlg.accept))
        dlg.exec()

    # ------------------------------------------------------------ 송출 전 점검
    def _review(self, text: str, priority: int) -> str | None:
        """위반 소지 점검. 송출할 최종 문구를 돌려주고, 취소하면 None."""
        findings = compliance_check(text)
        if priority > PRIORITY_EMERGENCY and in_quiet_hours(self.app.config["facility"]):
            findings.append(quiet_finding(self.app.config["facility"]))
        if not findings:
            return text
        blocked = any(f.level == "block" for f in findings)
        dlg, lay, foot = self._dialog(
            "방송 내용 점검",
            "송출할 수 없는 내용이 있습니다." if blocked
            else "라이선스·개인정보 위반 소지가 있는 내용이 있습니다. 확인 후 송출하세요.",
            C["danger"] if blocked else C["warn"])
        for f in findings:
            lv, color, light = LEVEL_LABELS[f.level]
            box = QFrame()
            box.setObjectName("finding")
            box.setStyleSheet(f"#finding {{ background:{light}; border:1px solid {C['border']};"
                              f" border-left:4px solid {color}; border-radius:8px; }}")
            bv = QVBoxLayout(box)
            bv.setContentsMargins(14, 10, 14, 10)
            bv.setSpacing(4)
            title = label(f.title)
            title.setStyleSheet("font-weight:bold;")
            bv.addLayout(hrow(badge(lv, "white", color), title, None))
            bv.addWidget(label(f.detail, wrap=True))
            bv.addWidget(label(f"근거: {f.clause}", "hint", wrap=True))
            lay.addWidget(box)
        lay.addWidget(label("※ 자동 점검은 보조 수단이며, 방송 내용의 책임은 운영자에게 있습니다.", "hint"))
        foot.addWidget(button("취소 (문구 수정)", None, dlg.reject))
        if not blocked:
            ok = button("확인했습니다. 그대로 송출", "primary", dlg.accept)
            foot.addWidget(ok)
        if dlg.exec() != QDialog.Accepted:
            return None
        log.warning("운영자 확인 후 송출 (%s): %s", ", ".join(f.title for f in findings), text[:80])
        return text

    def _confirm_emergency(self, text: str, repeat: int) -> bool:
        """긴급 방송은 실수로 누르지 않도록 한 번 더 확인 (기본 선택은 '취소')."""
        emg = self.app.config["broadcast"].get("emergency") or {}
        dlg, lay, foot = self._dialog("긴급 방송을 송출할까요?",
                                      "단지 전체에 경보음과 함께 즉시 방송됩니다. 내용을 다시 확인하세요.",
                                      C["danger"], 560)
        box = QFrame()
        box.setObjectName("emgBox")
        box.setStyleSheet(f"#emgBox {{ background:{C['danger_l']}; border:1px solid {C['border']};"
                          f" border-left:4px solid {C['danger']}; border-radius:8px; }}")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 12)
        msg = label(text, wrap=True)
        msg.setStyleSheet("font-size:12pt; font-weight:bold;")
        bv.addWidget(msg)
        lay.addWidget(box)
        rep = max(repeat, int(emg.get("min_repeat", 1)))
        facts = []
        cur = self.b.current
        if cur is not None:
            facts.append(f"지금 나가는 방송을 중단합니다: “{cur.text[:30]}{'…' if len(cur.text) > 30 else ''}”")
        if emg.get("chime_file"):
            facts.append("경보음이 먼저 울립니다")
        if emg.get("prefix"):
            facts.append(f"“{emg['prefix']}” 로 시작합니다")
        facts.append(f"{rep}회 반복 · 음량 {round(float(emg.get('volume', 1.0)) * 100)}%")
        facts.append("야간 방송 제한과 상관없이 송출됩니다")
        lay.addWidget(label("\n".join("•  " + f for f in facts), "muted", wrap=True))
        cancel = button("취소", None, dlg.reject)
        go = button("⚠   긴급 방송 송출", "danger", dlg.accept)
        foot.addWidget(cancel)
        foot.addWidget(go)
        for b in (cancel, go):
            b.setAutoDefault(False)
        cancel.setDefault(True)  # Enter 를 잘못 눌러도 송출되지 않게
        cancel.setFocus()
        ok = dlg.exec() == QDialog.Accepted
        log.info("긴급 방송 확인: %s", "송출" if ok else "취소")
        return ok

    def _submit(self, text: str, priority: int, repeat: int, chime: bool, source: str) -> bool:
        if priority == PRIORITY_EMERGENCY and not self._confirm_emergency(text, repeat):
            return False
        final = self._review(text, priority)
        if final is None:
            return False
        try:
            self.b.submit(Announcement(text=final, priority=priority, repeat=repeat,
                                       chime=chime, source=source, confirmed=True))
        except ValueError as e:
            self._error("방송 오류", str(e))
            return False
        emg = priority == PRIORITY_EMERGENCY
        self._toast("긴급 방송을 송출합니다" if emg else "방송을 대기열에 넣었습니다", "warn" if emg else "ok")
        return True

    def _send(self, priority=None):
        text = self.text.toPlainText().strip()
        if not text:
            self._toast("방송 문구를 입력하세요", "warn")
            self.text.setFocus()
            return
        if self._submit(text, parse_priority(priority or self.prio.get()), self.repeat.value(),
                        self.chime.isChecked(), "운영자"):
            self.text.clear()

    # ------------------------------------------------------------ 안내문 양식
    def _build_template_page(self, page: QWidget):
        h = QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(18)
        left = card("양식 목록")
        left.setFixedWidth(310)
        left.head.addWidget(button("↻", "ghost", self._load_templates, tip="templates.json 다시 불러오기"))
        self.tpl_search = QLineEdit()
        self.tpl_search.setPlaceholderText("이름 또는 내용으로 검색")
        self.tpl_search.setClearButtonEnabled(True)
        self.tpl_search.textChanged.connect(self._render_templates)
        left.body.addWidget(self.tpl_search)
        self.tpl_tree = QTreeWidget()
        self.tpl_tree.setHeaderHidden(True)
        self.tpl_tree.setIndentation(10)
        self.tpl_tree.itemSelectionChanged.connect(self._select_template)
        left.body.addWidget(self.tpl_tree, 1)
        h.addWidget(left)

        right = card()
        self.tpl_title = label("왼쪽 목록에서 양식을 선택하세요", "h2")
        right.body.addWidget(self.tpl_title)
        self.tpl_meta = QHBoxLayout()
        self.tpl_meta.setSpacing(6)
        right.body.addLayout(self.tpl_meta)
        right.body.addSpacing(6)
        right.body.addWidget(label("빈칸 채우기", "field"))
        self.tpl_fields_w = QWidget()
        self.tpl_fields = QGridLayout(self.tpl_fields_w)
        self.tpl_fields.setContentsMargins(0, 0, 0, 0)
        self.tpl_fields.setHorizontalSpacing(14)
        self.tpl_fields.setVerticalSpacing(8)
        self.tpl_fields.setColumnStretch(1, 1)
        right.body.addWidget(self.tpl_fields_w)
        right.body.addSpacing(6)
        right.body.addWidget(label("방송 문구 미리보기", "field"))
        self.tpl_preview = QTextEdit()
        self.tpl_preview.setReadOnly(True)
        self.tpl_preview.setFont(QFont("Malgun Gothic", 12))
        self.tpl_preview.setFixedHeight(140)
        right.body.addWidget(self.tpl_preview)
        right.body.addLayout(hrow(button("▶   바로 송출", "primary", self._send_template, big=True),
                                  button("방송 화면으로 보내기 (수정 후 송출)", None, self._template_to_broadcast),
                                  None, spacing=10))
        right.body.addStretch(1)
        right.body.addWidget(label("양식은 templates.json 에서 추가·수정할 수 있습니다. "
                                   "{이름} 부분이 빈칸이 됩니다.", "hint"))
        h.addWidget(right, 1)
        self.tpl_vars: dict[str, QLineEdit] = {}
        self.tpl_current = None
        self._load_templates()

    def _load_templates(self):
        path = resolve_path(self.app.config.get("templates_file", "templates.json"))
        try:
            with open(path, encoding="utf-8-sig") as fp:
                self.templates = json.load(fp)
        except (OSError, ValueError) as e:
            self.templates = []
            self._error("안내문 양식", f"양식 파일을 읽을 수 없습니다: {e}")
        self._render_templates()

    def _render_templates(self):
        q = self.tpl_search.text().strip()
        self.tpl_tree.clear()
        cats: dict[str, QTreeWidgetItem] = {}
        bold = QFont("Malgun Gothic", 9, QFont.Bold)
        for i, t in enumerate(self.templates):
            if q and q not in t["name"] and q not in t.get("text", "") and q not in t.get("category", ""):
                continue
            cat = t.get("category", "기타")
            if cat not in cats:
                it = QTreeWidgetItem([cat])
                it.setFlags(Qt.ItemIsEnabled)
                it.setFont(0, bold)
                it.setForeground(0, QColor(C["muted"]))
                self.tpl_tree.addTopLevelItem(it)
                cats[cat] = it
            child = QTreeWidgetItem([t["name"]])
            child.setData(0, Qt.UserRole, i)
            if parse_priority(t.get("priority")) == PRIORITY_EMERGENCY:
                child.setForeground(0, QColor(C["danger"]))
            cats[cat].addChild(child)
        self.tpl_tree.expandAll()

    def _select_template(self):
        items = self.tpl_tree.selectedItems()
        if not items or items[0].data(0, Qt.UserRole) is None:
            return
        t = self.templates[items[0].data(0, Qt.UserRole)]
        self.tpl_current = t
        self.tpl_title.setText(t["name"])
        while self.tpl_meta.count():
            w = self.tpl_meta.takeAt(0).widget()
            if w:
                w.deleteLater()
        prio = PRIORITY_NAMES.get(parse_priority(t.get("priority")), "보통")
        self.tpl_meta.addWidget(badge(t.get("category", "기타"), C["muted"], C["bg"]))
        self.tpl_meta.addWidget(badge(f"우선순위 {prio}", C["danger"], C["danger_l"]) if prio == "긴급"
                                else badge(f"우선순위 {prio}"))
        self.tpl_meta.addWidget(badge(f"반복 {t.get('repeat', 1)}회", C["muted"], C["bg"]))
        self.tpl_meta.addStretch(1)

        while self.tpl_fields.count():
            w = self.tpl_fields.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.tpl_vars = {}
        names = list(dict.fromkeys(re.findall(r"\{(\w+)\}", t["text"])))
        for r, name in enumerate(names):
            e = QLineEdit()
            e.setPlaceholderText(FIELD_HINTS.get(name, ""))
            e.textChanged.connect(self._update_preview)
            e.returnPressed.connect(self.focusNextChild)
            self.tpl_vars[name] = e
            self.tpl_fields.addWidget(label(name), r, 0)
            self.tpl_fields.addWidget(e, r, 1)
        if not names:
            self.tpl_fields.addWidget(label("채울 빈칸이 없습니다. 바로 송출할 수 있습니다.", "muted"), 0, 0, 1, 2)
        else:
            self.tpl_vars[names[0]].setFocus()
        self._update_preview()

    def _template_text(self) -> str:
        if not self.tpl_current:
            return ""
        return re.sub(r"\{(\w+)\}", lambda m: self.tpl_vars[m.group(1)].text().strip() or m.group(0),
                      self.tpl_current["text"])

    def _update_preview(self):
        text = html.escape(self._template_text())
        self.tpl_preview.setHtml(re.sub(
            r"\{(\w+)\}", lambda m: f'<span style="color:{C["danger"]}; background:{C["danger_l"]};">'
                                    f'{m.group(0)}</span>', text))

    def _template_ready(self) -> str | None:
        text = self._template_text()
        if not text:
            self._toast("먼저 양식을 선택하세요", "warn")
            return None
        missing = re.findall(r"\{(\w+)\}", text)
        if missing:
            self._toast("빈칸을 채워 주세요: " + ", ".join(missing), "warn")
            self.tpl_vars[missing[0]].setFocus()
            return None
        return text

    def _send_template(self):
        text = self._template_ready()
        if text:
            t = self.tpl_current
            self._submit(text, parse_priority(t.get("priority")), int(t.get("repeat", 1)),
                         self.chime.isChecked(), f"양식:{t['name']}")

    def _template_to_broadcast(self):
        text = self._template_ready()
        if text:
            t = self.tpl_current
            self._fill(text)
            self.prio.set(PRIORITY_NAMES.get(parse_priority(t.get("priority")), "보통"))
            self.repeat.setValue(int(t.get("repeat", 1)))
            self.show_page("broadcast")

    # ------------------------------------------------------------ 예약 방송
    def _build_schedule_page(self, page: QWidget):
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(18)
        lc = card("예약 목록", "더블클릭: 사용/중지  ·  Delete: 삭제  ·  오른쪽 클릭: 메뉴")
        for b in (button("사용/중지 전환", None, self._toggle_sched),
                  button("지금 송출(테스트)", None, self._fire_sched),
                  button("삭제", "outline", self._delete_sched),
                  button("↻", "ghost", self._refresh_sched, tip="새로고침")):
            lc.head.addWidget(b)
        self.sched_stack = QStackedWidget()
        self.tree = table(["상태", "이름", "일정", "우선", "문구"], [80, 140, 220, 56, 300])
        self.tree.setMinimumHeight(150)
        self.tree.itemDoubleClicked.connect(lambda *_: self._toggle_sched())
        QShortcut(QKeySequence.Delete, self.tree, activated=self._delete_sched, context=Qt.WidgetShortcut)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._sched_menu)
        empty = label("등록된 예약 방송이 없습니다.\n아래 [새 예약]에서 추가하세요.", "empty")
        empty.setAlignment(Qt.AlignCenter)
        self.sched_stack.addWidget(self.tree)
        self.sched_stack.addWidget(empty)
        lc.body.addWidget(self.sched_stack)
        v.addWidget(lc, 1)

        fc = card("새 예약")
        g = QGridLayout()
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(12)
        g.setColumnStretch(1, 1)
        fc.body.addLayout(g)
        self.s_name = QLineEdit()
        self.s_name.setPlaceholderText("예) 점심 안내")
        self.s_name.setFixedWidth(200)
        self.s_type = Segmented(["지정 시각", "일정 간격"], "지정 시각")
        self.s_prio = Segmented(["보통", "높음", "긴급"], "보통", danger="긴급")
        self.s_repeat = QSpinBox()
        self.s_repeat.setRange(1, 10)
        self.s_repeat.setSuffix(" 회")
        self.s_repeat.setAlignment(Qt.AlignCenter)
        self.s_repeat.setMinimumWidth(80)
        g.addWidget(label("이름", "field"), 0, 0)
        g.addLayout(hrow(self.s_name, 24, label("유형", "field"), self.s_type, None), 0, 1)

        self.s_when_label = label("시각", "field")
        g.addWidget(self.s_when_label, 1, 0)
        self.s_when = QStackedWidget()
        self.s_when.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tw = QWidget()
        self.s_time = time_edit("09:00")
        self.s_date_on = QCheckBox("특정 날짜에만")
        self.s_date = QDateEdit(QDate.currentDate())
        self.s_date.setDisplayFormat("yyyy-MM-dd")
        self.s_date.setCalendarPopup(True)
        self.s_date.setEnabled(False)
        self.s_date_on.toggled.connect(self.s_date.setEnabled)
        tw.setLayout(hrow(self.s_time, 24, self.s_date_on, self.s_date,
                          label("체크하지 않으면 선택한 요일마다 반복", "hint"), None, spacing=10))
        iw = QWidget()
        self.s_interval = QSpinBox()
        self.s_interval.setRange(1, 1440)
        self.s_interval.setValue(60)
        self.s_interval.setSuffix(" 분마다")
        self.s_interval.setMinimumWidth(120)
        self.s_start = time_edit("09:00")
        self.s_end = time_edit("18:00")
        iw.setLayout(hrow(self.s_interval, 24, label("운영 시간", "field"), self.s_start, label("~", "muted"),
                          self.s_end, None, spacing=10))
        self.s_when.addWidget(tw)
        self.s_when.addWidget(iw)
        self.s_type.changed.connect(self._sched_type_changed)
        g.addWidget(self.s_when, 1, 1)

        g.addWidget(label("요일", "field"), 2, 0)
        self.s_days: list[QPushButton] = []
        days = []
        for name in DAY_NAMES:
            b = button(name, "day")
            b.setCheckable(True)
            self.s_days.append(b)
            days.append(b)
        quick = [button(t, "ghost", lambda _=False, d=d: [b.setChecked(i in d) for i, b in enumerate(self.s_days)])
                 for t, d in (("매일", ()), ("평일", range(5)), ("주말", (5, 6)))]
        g.addLayout(hrow(*days, 12, *quick, label("선택하지 않으면 매일", "hint"), None, spacing=6), 2, 1)

        g.addWidget(label("우선순위", "field"), 3, 0)
        g.addLayout(hrow(self.s_prio, 24, label("반복", "field"), self.s_repeat, None), 3, 1)

        g.addWidget(label("문구", "field"), 4, 0)
        self.s_text = QLineEdit()
        self.s_text.setPlaceholderText("예약 방송 문구를 입력하세요")
        self.s_text.returnPressed.connect(self._add_sched)
        g.addLayout(hrow(self.s_text, button("＋  예약 추가", "primary", self._add_sched), spacing=10, stretch_at=0),
                    4, 1)
        v.addWidget(fc)
        self._refresh_sched()

    def _sched_type_changed(self, value: str):
        interval = value == "일정 간격"
        self.s_when.setCurrentIndex(1 if interval else 0)
        self.s_when_label.setText("간격" if interval else "시각")

    def _sched_menu(self, pos):
        if self.tree.itemAt(pos) is None:
            return
        m = QMenu(self)
        m.addAction("사용/중지 전환", self._toggle_sched)
        m.addAction("지금 송출(테스트)", self._fire_sched)
        m.addSeparator()
        m.addAction("삭제", self._delete_sched)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _refresh_sched(self):
        items = self.app.scheduler.items()
        t = self.tree
        t.setRowCount(0)
        for it in items:
            r = t.rowCount()
            t.insertRow(r)
            on = it.get("enabled", True)
            values = ("●  사용" if on else "○  중지", it.get("name", ""), describe(it),
                      PRIORITY_NAMES.get(parse_priority(it.get("priority")), ""), it.get("text", ""))
            for c, val in enumerate(values):
                cell = QTableWidgetItem(val)
                cell.setToolTip(val)
                if not on:
                    cell.setForeground(QColor(C["subtle"]))
                elif c == 0:
                    cell.setForeground(QColor(C["ok"]))
                t.setItem(r, c, cell)
            t.item(r, 0).setData(Qt.UserRole, it["id"])
        self.sched_stack.setCurrentIndex(0 if items else 1)

    def _selected(self) -> list[str]:
        rows = sorted({i.row() for i in self.tree.selectedItems()})
        if not rows:
            self._toast("목록에서 예약을 선택하세요", "warn")
        return [self.tree.item(r, 0).data(Qt.UserRole) for r in rows]

    def _toggle_sched(self):
        items = {i["id"]: i for i in self.app.scheduler.items()}
        for sid in self._selected():
            self.app.scheduler.update(sid, enabled=not items[sid].get("enabled", True))
        self._refresh_sched()

    def _delete_sched(self):
        sel = self._selected()
        if sel and self._ask("삭제", f"예약 {len(sel)}건을 삭제할까요?", "삭제", "취소", danger=True):
            for sid in sel:
                self.app.scheduler.remove(sid)
            self._refresh_sched()
            self._toast(f"예약 {len(sel)}건을 삭제했습니다", "info")

    def _fire_sched(self):
        items = {i["id"]: i for i in self.app.scheduler.items()}
        for sid in self._selected():
            try:
                self.app.scheduler.fire(items[sid])
                self._toast("예약 방송을 테스트 송출합니다", "info")
            except ValueError as e:
                self._warn("예약 송출", str(e))

    def _add_sched(self):
        text = self.s_text.text().strip()
        if not text:
            self._toast("예약할 문구를 입력하세요", "warn")
            self.s_text.setFocus()
            return
        findings = compliance_check(text)
        if any(f.level == "block" for f in findings):
            self._error("예약", "송출할 수 없는 내용이 있습니다:\n" +
                        "\n".join(f"- {f.title}: {f.detail}" for f in findings))
            return
        if findings and not self._ask(
                "예약 - 내용 점검",
                "위반 소지가 있는 내용이 있습니다. 예약 방송은 운영자 확인 없이 자동 송출됩니다.\n\n" +
                "\n".join(f"- {f.title}: {f.detail}" for f in findings) + "\n\n그래도 등록할까요?"):
            return
        item = {"name": self.s_name.text().strip(), "text": text,
                "days": [i for i, b in enumerate(self.s_days) if b.isChecked()],
                "priority": parse_priority(self.s_prio.get()),
                "repeat": self.s_repeat.value(), "chime": True}
        if self.s_type.get() == "일정 간격":
            item.update(type="interval", interval_min=self.s_interval.value(),
                        start=self.s_start.time().toString("HH:mm"), end=self.s_end.time().toString("HH:mm"))
        else:
            item.update(type="time", time=self.s_time.time().toString("HH:mm"),
                        date=self.s_date.date().toString("yyyy-MM-dd") if self.s_date_on.isChecked() else "")
        try:
            self.app.scheduler.add(item)
        except (ValueError, KeyError) as e:
            self._error("예약", f"입력 형식 오류: {e}")
            return
        self.s_text.clear()
        self.s_name.clear()
        self._refresh_sched()
        self._toast("예약 방송을 추가했습니다")

    # ------------------------------------------------------------ 시설 설정
    def _build_facility_page(self, page: QWidget):
        fac = self.app.config["facility"]
        q = fac.setdefault("quiet_hours", {"enabled": False, "start": "22:00", "end": "07:00"})
        g = QGridLayout(page)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(18)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        g.setRowStretch(3, 1)

        info = card("시설 정보 · 머리말 / 맺음말", "{시설} 은 시설명으로 바뀝니다")
        self.fac_name = QLineEdit(fac.get("name", ""))
        self.fac_name.setPlaceholderText("예) OO아파트 관리사무소")
        self.fac_intro_on = QCheckBox("머리말 사용")
        self.fac_intro_on.setChecked(fac.get("intro_enabled", True))
        self.fac_intro = QLineEdit(fac.get("intro", ""))
        self.fac_intro_emg = QCheckBox("긴급 방송에도 머리말 사용")
        self.fac_intro_emg.setChecked(fac.get("intro_on_emergency", True))
        self.fac_outro_on = QCheckBox("맺음말 사용")
        self.fac_outro_on.setChecked(fac.get("outro_enabled", False))
        self.fac_outro = QLineEdit(fac.get("outro", ""))
        for chk, deps in ((self.fac_intro_on, (self.fac_intro, self.fac_intro_emg)),
                          (self.fac_outro_on, (self.fac_outro,))):
            for d in deps:
                d.setEnabled(chk.isChecked())
                chk.toggled.connect(d.setEnabled)
        info.body.addWidget(label("시설명", "field"))
        info.body.addWidget(self.fac_name)
        info.body.addSpacing(4)
        for w in (self.fac_intro_on, self.fac_intro):
            info.body.addWidget(w)
        info.body.addSpacing(4)
        info.body.addWidget(self.fac_outro_on)
        info.body.addWidget(self.fac_outro)
        g.addWidget(info, 0, 0)

        qc = card("야간 방송 제한")
        self.fac_quiet_on = QCheckBox("사용")
        self.fac_quiet_on.setChecked(q.get("enabled", True))
        self.fac_quiet_start = time_edit(q.get("start", "22:00"))
        self.fac_quiet_end = time_edit(q.get("end", "07:00"))
        for d in (self.fac_quiet_start, self.fac_quiet_end):
            d.setEnabled(self.fac_quiet_on.isChecked())
            self.fac_quiet_on.toggled.connect(d.setEnabled)
        qc.body.addLayout(hrow(self.fac_quiet_on, 18, self.fac_quiet_start, label("~", "muted"),
                               self.fac_quiet_end, None))
        qc.body.addWidget(label("이 시간에는 긴급 방송만 자동 송출되고, 운영자 방송은 확인 후 송출됩니다.", "hint",
                                wrap=True))
        g.addWidget(qc, 1, 0)
        g.addWidget(self._build_emergency_card(), 2, 0)

        dc = card("AI 음성 고지", "라이선스 A(e) · AI 기본법")
        self.disc_badge = QLabel()
        dc.head.addWidget(self.disc_badge)
        self._update_disc_badge()
        dc.body.addWidget(label("고지 방식", "field"))
        self.fac_mode = QButtonGroup(self)
        mode = fac.get("disclosure_mode", "notice")
        for val, text in (("notice", "게시물로 대체 — 방송에는 고지 멘트 없음"),
                          ("daily_first", "하루 첫 방송에만 음성 고지"),
                          ("every", "매 방송 음성 고지")):
            rb = QRadioButton(text)
            rb.setProperty("value", val)
            rb.setChecked(val == mode)
            self.fac_mode.addButton(rb)
            dc.body.addWidget(rb)
        dc.body.addSpacing(4)
        dc.body.addWidget(label("음성 고지 문구", "field"))
        self.fac_disc_text = QLineEdit(fac.get("disclosure_text", "AI 음성 안내 방송입니다."))
        dc.body.addWidget(self.fac_disc_text)
        self.fac_mode.buttonToggled.connect(lambda *_: self.fac_disc_text.setEnabled(self._fac_mode() != "notice"))
        self.fac_disc_text.setEnabled(mode != "notice")

        post = QFrame()
        post.setObjectName("subtle")
        pv = QVBoxLayout(post)
        pv.setContentsMargins(16, 14, 16, 14)
        pv.setSpacing(8)
        pv.addWidget(label("게시용 안내문", "field"))
        pv.addWidget(label("①  안내문을 만들어 인쇄\n②  게시판·엘리베이터·출입구에 게시\n③  아래에 체크한 뒤 저장",
                           "hint", wrap=True))
        pv.addLayout(hrow(button("게시용 안내문 만들기 (인쇄)", None, self._make_notice), None))
        self.fac_posted = QCheckBox("안내문을 게시했습니다")
        self.fac_posted.setChecked(bool(fac.get("notice_posted")))
        pv.addWidget(self.fac_posted)
        dc.body.addSpacing(8)
        dc.body.addWidget(post)
        dc.body.addStretch(1)
        g.addWidget(dc, 0, 1, 3, 1)

        g.addLayout(hrow(None, button("라이선스 · 사용 제한 보기", None, lambda: self._license_dialog(True)),
                         button("저장", "primary", self._save_facility, big=True), spacing=10),
                    4, 0, 1, 2)

    def _build_emergency_card(self) -> QFrame:
        emg = self.app.config["broadcast"].setdefault("emergency", {})
        ec = card("긴급 방송", "일반 방송과 확실히 구분되도록")
        eg = QGridLayout()
        eg.setHorizontalSpacing(12)
        eg.setVerticalSpacing(8)
        eg.setColumnStretch(1, 1)
        ec.body.addLayout(eg)
        self.emg_chime = QComboBox()
        # 기본 경보음을 이름으로 먼저, 그다음 직접 넣은 WAV, 마지막에 '일반 차임'
        files = {p.name for p in resolve_path("assets/chimes").glob("*.wav")}
        for stem, (_fn, title) in ALERT_PRESETS.items():
            if f"{stem}.wav" in files:
                self.emg_chime.addItem(title, f"{stem}.wav")
        for name in sorted(files - {f"{s}.wav" for s in ALERT_PRESETS} - {f"{s}.wav" for s in CHIME_PRESETS}):
            self.emg_chime.addItem(name, name)
        self.emg_chime.addItem("(경보음 없이 일반 차임)", "")
        cur = emg.get("chime_file", "assets/chimes/emergency.wav")
        i = self.emg_chime.findData(Path(cur).name if cur else "")
        self.emg_chime.setCurrentIndex(max(0, i))
        self.emg_chime.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.emg_chime.setMinimumContentsLength(12)
        eg.addWidget(label("경보음", "field"), 0, 0)
        eg.addLayout(hrow(self.emg_chime, button("▶ 미리듣기", "ghost", lambda: self._preview_chime(
            self.emg_chime.currentData() or "", resolve_path("assets/chimes"))), spacing=8, stretch_at=0), 0, 1)
        self.emg_prefix = QLineEdit(emg.get("prefix", "긴급 안내 말씀 드립니다."))
        self.emg_prefix.setPlaceholderText("비우면 앞머리 문구 없음")
        eg.addWidget(label("앞머리 문구", "field"), 1, 0)
        eg.addWidget(self.emg_prefix, 1, 1)
        self.emg_repeat = QSpinBox()
        self.emg_repeat.setRange(1, 5)
        self.emg_repeat.setSuffix(" 회 이상")
        self.emg_repeat.setValue(int(emg.get("min_repeat", 2)))
        self.emg_volume = QSpinBox()
        self.emg_volume.setRange(100, 150)
        self.emg_volume.setSingleStep(10)
        self.emg_volume.setSuffix(" %")
        self.emg_volume.setValue(round(float(emg.get("volume", 1.3)) * 100))
        for sp in (self.emg_repeat, self.emg_volume):
            sp.setAlignment(Qt.AlignCenter)
            sp.setMinimumWidth(96)
        eg.addWidget(label("반복", "field"), 2, 0)
        eg.addLayout(hrow(self.emg_repeat, 18, label("음량", "field"), self.emg_volume, None), 2, 1)
        ec.body.addWidget(self.fac_intro_emg)
        ec.body.addWidget(label("긴급 방송은 진행 중인 방송을 끊고 바로 나가며, 야간 제한과 상관없이 송출됩니다. "
                                "음량 100% 초과는 찢어지지 않게 눌러서 더 크게 들리게 합니다.", "hint", wrap=True))
        return ec

    def _fac_mode(self) -> str:
        b = self.fac_mode.checkedButton()
        return b.property("value") if b else "notice"

    def _update_disc_badge(self):
        if disclosure_ok(self.app.config["facility"]):
            self.disc_badge.setText("✓ 고지 완료")
            fg, bg = C["ok"], C["ok_l"]
        else:
            self.disc_badge.setText("! 미완료")
            fg, bg = C["warn"], C["warn_l"]
        self.disc_badge.setStyleSheet(f"color:{fg}; background:{bg}; border-radius:6px; padding:2px 8px;"
                                      f" font-size:9pt; font-weight:bold;")

    def _save_facility(self):
        mode = self._fac_mode()
        if mode == "notice" and not self.fac_posted.isChecked() and not self._ask(
                "AI 음성 고지",
                "'게시물로 대체'를 선택했지만 안내문 게시 확인이 체크되지 않았습니다.\n\n"
                "음성 모델 라이선스(부속서 A(e))는 AI 생성 음성임을 알리도록 요구합니다. "
                "[게시용 안내문 만들기]로 인쇄해 게시한 뒤 체크해 주세요.\n\n일단 저장할까요?"):
            return
        fac = self.app.config["facility"]
        fac.update(name=self.fac_name.text().strip(), intro_enabled=self.fac_intro_on.isChecked(),
                   intro=self.fac_intro.text().strip(), intro_on_emergency=self.fac_intro_emg.isChecked(),
                   outro_enabled=self.fac_outro_on.isChecked(), outro=self.fac_outro.text().strip(),
                   disclosure_mode=mode,
                   disclosure_text=self.fac_disc_text.text().strip() or "AI 음성 안내 방송입니다.")
        if not self.fac_posted.isChecked():
            fac["notice_posted"] = ""
        elif not fac.get("notice_posted"):
            fac["notice_posted"] = time.strftime("%Y-%m-%d %H:%M:%S")
            log.info("AI 음성 안내문 게시 확인")
        fac["quiet_hours"] = {"enabled": self.fac_quiet_on.isChecked(),
                              "start": self.fac_quiet_start.time().toString("HH:mm"),
                              "end": self.fac_quiet_end.time().toString("HH:mm")}
        chime = self.emg_chime.currentData() or ""
        self.app.config["broadcast"]["emergency"] = {
            "chime_file": f"assets/chimes/{chime}" if chime else "",
            "prefix": self.emg_prefix.text().strip(),
            "min_repeat": self.emg_repeat.value(),
            "volume": round(self.emg_volume.value() / 100, 2),
        }
        self.b.reload_chimes()
        self.app.save()
        self._update_disc_badge()
        self._update_banner()
        self._update_side_facility()
        self._toast("시설 설정을 저장했습니다")

    def _make_notice(self):
        path = resolve_path("docs/게시용_AI음성_안내문.html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(notice_html(self.fac_name.text().strip()), encoding="utf-8")
        try:
            os.startfile(str(path))  # 기본 브라우저로 열기 → Ctrl+P 인쇄
        except OSError:
            pass
        self._info("게시용 안내문", f"안내문을 만들었습니다.\n{path}\n\n인쇄해서 게시한 뒤 "
                                  "'게시했습니다'에 체크하고 저장하세요.")

    # ------------------------------------------------------------ 라이선스 동의
    def _license_dialog(self, view_only: bool = False):
        dlg, lay, foot = self._dialog("AI 음성 모델 사용 제한 (Open RAIL-M)",
                                      "방송 프로그램을 사용하기 전에 아래 내용을 확인해 주세요.", C["side"], 720)
        txt = QPlainTextEdit(license_notice())
        txt.setReadOnly(True)
        txt.setMinimumHeight(420)
        lay.addWidget(txt)
        if view_only:
            foot.addWidget(button("닫기", "primary", dlg.accept))
            dlg.exec()
            return
        foot.addWidget(button("동의하지 않음 (종료)", None, dlg.reject))
        foot.addWidget(button("위 내용을 확인했으며 동의합니다", "primary", dlg.accept))
        if dlg.exec() == QDialog.Accepted:
            self.app.config["license_accepted"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.app.save()
            log.info("사용 제한 동의")
        else:
            self._force_close = True
            self.close()

    # ------------------------------------------------------------ 엔진 · 차임벨
    def _build_engine_page(self, page: QWidget):
        g = QGridLayout(page)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(18)
        g.setColumnStretch(0, 3)
        g.setColumnStretch(1, 2)
        g.setColumnMinimumWidth(1, 300)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(18)
        right.setSpacing(18)
        g.addLayout(left, 0, 0, Qt.AlignTop)
        g.addLayout(right, 0, 1, Qt.AlignTop)

        ec = card("음성 엔진")
        eg = QGridLayout()
        eg.setHorizontalSpacing(16)
        eg.setVerticalSpacing(10)
        eg.setColumnStretch(1, 1)
        ec.body.addLayout(eg)
        self.profile = QComboBox()
        self.profile.addItems(list(self.app.config["engines"]))
        self.profile.setCurrentText(self.app.config["active_engine"])
        self.profile.setMinimumWidth(170)
        self.profile.currentTextChanged.connect(lambda _: self._load_profile())
        self.type_badge = badge("")
        eg.addWidget(label("엔진 프로필", "field"), 0, 0)
        eg.addLayout(hrow(self.profile, self.type_badge, spacing=10, stretch_at=0), 0, 1)
        self.fallback_cb = QComboBox()
        self.fallback_cb.addItems(["(사용 안 함)"] + list(self.app.config["engines"]))
        self.fallback_cb.setCurrentText(self.app.config["broadcast"].get("fallback_engine") or "(사용 안 함)")
        self.fallback_cb.setMinimumWidth(170)
        eg.addWidget(label("예비 엔진", "field"), 1, 0)
        eg.addLayout(hrow(self.fallback_cb, button("예비 엔진 적용", None, self._apply_fallback),
                          spacing=8, stretch_at=0), 1, 1)
        eg.addWidget(label("주 엔진이 고장 나면 자동으로 예비 엔진으로 방송합니다.", "hint", wrap=True), 2, 1)
        ec.body.addWidget(label("⚠  Windows 음성(windows_*)의 상업 방송 이용 조건은 Microsoft 확인 중입니다 "
                                "(docs\\Microsoft_음성_라이선스_문의서.md)", "note", wrap=True))
        left.addWidget(ec)
        left.addWidget(self._build_voice_card())

        right.addWidget(self._build_chime_card())
        right.addWidget(self._build_settings_card())

        oc = card("엔진 옵션 (고급)", "JSON · 위 조절과 같은 값")
        self.opts = QPlainTextEdit()
        self.opts.setFont(QFont("Consolas", 10))
        self.opts.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.opts.setFixedHeight(190)
        oc.body.addWidget(self.opts)
        oc.body.addWidget(label("model_dir(모델 폴더)·lang(언어)은 바꾸지 마세요. 따옴표·쉼표·괄호가 "
                                "빠지면 저장되지 않고 기존 설정이 유지됩니다.", "hint", wrap=True))
        oc.body.addLayout(hrow(None, button("적용 및 저장", "primary", self._apply_engine)))
        right.addWidget(oc)

        ic = card("시스템 정보")
        cfg = self.app.config
        info = [("등록된 엔진", ", ".join(available_engines()))]
        if self.app.watcher:
            # 경로는 공백이 없어 줄바꿈되지 않으므로 \ 뒤에 줄바꿈 가능 지점(ZWSP) 삽입
            info.append(("감시 폴더", str(self.app.watcher.folder).replace("\\", "\\​")
                         + "\n(.txt 파일을 넣으면 자동 방송)"))
        if self.app.api:
            info.append(("HTTP API", f"http://{cfg['api']['host']}:{cfg['api']['port']}/"))
        info.append(("엔진 추가", "config.json 의 engines 에 프로필 추가, 또는 plugins 폴더에 .py 추가 (README 참고)"))
        info.append(("화면", "Qt for Python (PySide6, LGPL-3.0) — licenses 폴더 참고"))
        ig = QGridLayout()
        ig.setHorizontalSpacing(14)
        ig.setVerticalSpacing(8)
        ig.setColumnStretch(1, 1)
        for r, (k, val) in enumerate(info):
            ig.addWidget(label(k, "muted"), r, 0, Qt.AlignTop)
            v = label(val, wrap=True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            ig.addWidget(v, r, 1)
        ic.body.addLayout(ig)
        right.addWidget(ic)
        # 콤보 상자가 긴 항목(경로 등)에 맞춰 늘어나 화면을 밀어내지 않도록
        for cb in (self.profile, self.fallback_cb, self.voice, self.chime_start_cb, self.chime_end_cb):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(12)
        self._load_profile()

    def _build_voice_card(self) -> QFrame:
        vc = card("음성 조절", "목소리 · 빠르기 · 음높이 · 음량 · 음질 · 문장 간격")
        vg = QGridLayout()
        vg.setHorizontalSpacing(14)
        vg.setVerticalSpacing(2)
        vg.setColumnStretch(1, 1)
        vg.setColumnMinimumWidth(0, 64)
        self.voice = QComboBox()
        self.voice.setEditable(True)
        self.voice.setMinimumWidth(180)
        self.voice.currentTextChanged.connect(lambda _: self._set_option("voice", self._voice_value()))
        self.voice_btn = button("목록 불러오기", "ghost", self._load_voices)
        self.voice_label = label("목소리", "field")
        vg.addWidget(self.voice_label, 0, 0)
        vg.addLayout(hrow(self.voice, self.voice_btn, spacing=8, stretch_at=0), 0, 1, 1, 2)
        self.voice_hint = label("F = 여성, M = 남성. 직접 만든 목소리는 json 파일 경로를 입력", "hint", wrap=True)
        vg.addWidget(self.voice_hint, 1, 1, 1, 2)
        self.voice_sliders = []
        for i in range(max(len(s) for s in VOICE_CONTROLS.values())):
            r = 2 + i * 2
            name, val, hint = label("", "field"), label("", "sliderVal"), label("", "hint", wrap=True)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            sl = QSlider(Qt.Horizontal)
            sl.setPageStep(1)
            sl.valueChanged.connect(lambda v, i=i: self._on_voice_slider(i, v))
            vg.addWidget(name, r, 0)
            vg.addWidget(sl, r, 1)
            vg.addWidget(val, r, 2)
            vg.addWidget(hint, r + 1, 1, 1, 2)
            vg.setRowMinimumHeight(r, 34)
            self.voice_sliders.append((name, sl, val, hint))
        vc.body.addLayout(vg)
        self.voice_note = label("", "hint", wrap=True)
        vc.body.addWidget(self.voice_note)
        vc.body.addSpacing(6)
        vc.body.addWidget(label("시험 문구", "field"))
        self.test_text = QLineEdit("안내 말씀 드립니다. 방송 테스트 중입니다.")
        self.test_text.returnPressed.connect(self._apply_and_test)
        vc.body.addWidget(self.test_text)
        vc.body.addLayout(hrow(button("조절값 기본으로", "ghost", self._reset_voice), None,
                               button("▶   적용하고 들어보기", "primary", self._apply_and_test,
                                      tip="재생 중에 다시 누르면 즉시 끊고 바뀐 설정으로 다시 재생")))
        return vc

    def _voice_specs(self):
        prof = self.app.config["engines"][self.profile.currentText()]
        return VOICE_CONTROLS.get(prof["type"], [])

    def _voice_value(self) -> str:
        """목소리 칸의 실제 값 (목록 항목이면 F1 같은 키, 직접 입력이면 입력값)."""
        text = self.voice.currentText().strip()
        i = self.voice.findText(text)
        return self.voice.itemData(i) or text if i >= 0 else text

    def _load_voice_sliders(self, prof: dict):
        specs = VOICE_CONTROLS.get(prof["type"], [])
        opts = prof.get("options", {})
        has_voice = prof["type"] in VOICE_CONTROLS
        self.voice.blockSignals(True)
        self.voice.clear()
        if prof["type"] == "supertonic":
            for key, text in SUPERTONIC_VOICES:
                self.voice.addItem(text, key)
        cur = str(opts.get("voice", ""))
        i = self.voice.findData(cur)
        if i >= 0:
            self.voice.setCurrentIndex(i)
        else:
            self.voice.setEditText(cur)
        self.voice.blockSignals(False)
        for w in (self.voice_label, self.voice, self.voice_btn, self.voice_hint):
            w.setVisible(has_voice)
        self.voice_hint.setText("F = 여성, M = 남성. 직접 만든 목소리는 json 파일 경로를 입력"
                                if prof["type"] == "supertonic" else "비우면 한국어 기본 음성. [목록 불러오기]로 선택")
        for i, (name, sl, val, hint) in enumerate(self.voice_sliders):
            visible = i < len(specs)
            for w in (name, sl, val, hint):
                w.setVisible(visible)
            if not visible:
                continue
            key, text, lo, hi, default, scale, fmt, desc = specs[i]
            sl.blockSignals(True)
            name.setText(text)
            hint.setText(desc)
            sl.setRange(lo, hi)
            try:
                sl.setValue(round(float(opts.get(key, default / scale)) * scale))
            except (TypeError, ValueError):
                sl.setValue(default)
            val.setText(fmt(sl.value()))
            sl.blockSignals(False)
        self.voice_note.setVisible(not specs)
        self.voice_note.setText("이 엔진은 화면 조절을 지원하지 않습니다. 오른쪽 '엔진 옵션 (고급)'에서 조절하세요.")

    def _on_voice_slider(self, i: int, v: int):
        key, _, _, _, _, scale, fmt, _ = self._voice_specs()[i]
        self.voice_sliders[i][2].setText(fmt(v))
        self._set_option(key, v if scale == 1 else round(v / scale, 2))

    def _reset_voice(self):
        for spec, (_, sl, *_rest) in zip(self._voice_specs(), self.voice_sliders):
            sl.setValue(spec[4])

    def _apply_and_test(self):
        if self._apply_engine():
            self._test_broadcast()

    # ------------------------------------------------------------ 설정 백업 · 초기화
    def _build_settings_card(self) -> QFrame:
        sc = card("설정 관리", "저장 · 불러오기 · 초기화")
        sc.body.addLayout(hrow(button("저장", None, self._export_settings, tip="모든 설정을 zip 파일로 저장"),
                               button("불러오기", None, self._import_settings, tip="저장한 zip 파일로 복원"), None,
                               button("초기화…", "danger", self._reset_dialog)))
        sc.body.addWidget(label("불러오기·초기화 전 현재 설정은 backups 폴더에 자동 백업됩니다.", "hint", wrap=True))
        self.autostart_cb = QCheckBox("Windows 시작 시 자동 실행")
        self.autostart_cb.setChecked(autostart.is_enabled())
        self.autostart_cb.toggled.connect(self._set_autostart)
        sc.body.addWidget(self.autostart_cb)
        sc.body.addWidget(label("PC를 켜면 창 없이 트레이(작업 표시줄 오른쪽 아래)에서 방송을 시작합니다. "
                                "창을 닫아도 방송은 계속되며, 완전히 끄려면 트레이 아이콘 → 프로그램 종료.",
                                "hint", wrap=True))
        return sc

    def _export_settings(self):
        name = re.sub(r'[\\/:*?"<>|\s]+', "_", self.app.config["facility"].get("name", "")).strip("_")
        default = Path.home() / "Desktop" / f"TTS방송_설정_{name}_{time.strftime('%Y%m%d')}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "설정 저장", str(default), "설정 백업 (*.zip)")
        if not path:
            return
        try:
            backup.export_settings(Path(path), self.app.config_path)
        except OSError as e:
            self._error("설정 저장", f"저장하지 못했습니다:\n{e}")
            return
        self._toast("설정을 저장했습니다")
        log.info("설정 내보내기: %s", path)

    def _import_settings(self):
        start = backup.BACKUP_DIR if backup.BACKUP_DIR.is_dir() else Path.home() / "Desktop"
        path, _ = QFileDialog.getOpenFileName(self, "설정 불러오기", str(start), "설정 백업 (*.zip)")
        if not path:
            return
        try:
            m = backup.read_manifest(Path(path))
        except (OSError, ValueError) as e:
            self._error("설정 불러오기", str(e))
            return
        info = f"만든 시각: {m.get('created', '?')}  (버전 {m.get('version', '?')})"
        if m.get("note"):
            info += f"\n{m['note']}"
        if not self._ask("설정 불러오기", f"{Path(path).name}\n{info}\n\n현재 설정을 이 파일의 설정으로 바꾸고 "
                                       "프로그램을 다시 시작합니다.\n(현재 설정은 자동 백업됩니다)",
                         "불러오고 다시 시작", "취소"):
            return
        self._settings_change(lambda: backup.import_settings(Path(path), self.app.config_path), "불러오기")

    def _reset_dialog(self):
        dlg, lay, foot = self._dialog("설정 초기화", "선택한 항목을 처음 설치했을 때의 값으로 되돌립니다. "
                                                  "현재 설정은 자동 백업되므로 [설정 불러오기]로 되돌릴 수 있습니다.",
                                      C["danger"], 560)
        checks = {}
        for key, (title, desc, *_rest) in backup.RESET_SCOPES.items():
            cb = QCheckBox(title)
            cb.setChecked(True)
            checks[key] = cb
            lay.addWidget(cb)
            hint = label(desc, "hint", wrap=True)
            hint.setContentsMargins(28, 0, 0, 6)
            lay.addWidget(hint)
        foot.addWidget(button("취소", None, dlg.reject))
        go = button("초기화하고 다시 시작", "danger", dlg.accept)
        foot.addWidget(go)
        for cb in checks.values():
            cb.toggled.connect(lambda _: go.setEnabled(any(c.isChecked() for c in checks.values())))
        if dlg.exec() != QDialog.Accepted:
            return
        scopes = [k for k, cb in checks.items() if cb.isChecked()]
        self._settings_change(lambda: backup.reset_settings(self.app.config_path, scopes), "초기화")

    def _settings_change(self, fn, what: str):
        self.app.scheduler.stop()  # 예약 파일을 바꾸는 동안 덮어쓰지 않도록
        try:
            before = fn()
        except Exception as e:
            log.exception("설정 %s 실패", what)
            self.app.scheduler.start()
            self._error(f"설정 {what}", f"실패했습니다:\n{e}\n\n일부가 바뀌었다면 backups 폴더의 "
                                         "가장 최근 자동 백업을 [설정 불러오기]로 되돌리세요.")
            return
        log.info("설정 %s 완료 (이전 설정 백업: %s)", what, before)
        self._info(f"설정 {what}", f"완료했습니다. 프로그램을 다시 시작합니다.\n\n이전 설정 백업:\n{before}")
        self.restart_requested = True
        self._force_close = True
        self.close()

    def _build_chime_card(self) -> QFrame:
        cc = card("차임벨", "assets\\chimes 폴더의 WAV")
        s = self.app.config["broadcast"]
        self.chime_dir = resolve_path("assets/chimes")
        files = sorted(p.name for p in self.chime_dir.glob("*.wav"))
        none = "(사용 안 함)"
        self.chime_start_cb, self.chime_end_cb = QComboBox(), QComboBox()
        for cb in (self.chime_start_cb, self.chime_end_cb):
            cb.addItems([none] + files)
        self.chime_start_cb.setCurrentText(Path(s.get("chime_start_file", "")).name
                                           if s.get("chime_start", True) else none)
        self.chime_end_cb.setCurrentText(Path(s.get("chime_end_file", "")).name if s.get("chime_end", False) else none)
        cg = QGridLayout()
        cg.setHorizontalSpacing(10)
        cg.setVerticalSpacing(8)
        cg.setColumnStretch(1, 1)
        for r, (text, cb) in enumerate((("시작", self.chime_start_cb), ("종료", self.chime_end_cb))):
            cg.addWidget(label(text, "field"), r, 0)
            cg.addWidget(cb, r, 1)
            cg.addWidget(button("▶ 미리듣기", "ghost", lambda _=False, c=cb: self._preview_chime(c.currentText())), r, 2)
        cc.body.addLayout(cg)
        cc.body.addLayout(hrow(None, button("차임 적용", "primary", self._apply_chimes)))
        return cc

    def _test_broadcast(self):
        # 앞선 테스트가 재생·대기 중이면 즉시 끊고 바뀐 설정으로 다시 재생 (실제 방송은 건드리지 않음)
        cur = self.b.current
        restarted = self.b.cancel_source("테스트") or (cur is not None and cur.source == "테스트")
        try:
            self.b.submit(Announcement(text=self.test_text.text(), chime=False, source="테스트"))
            if restarted:
                self._toast("이전 테스트를 중단하고 바뀐 설정으로 다시 재생합니다", "info")
            elif cur is not None:
                self._toast("송출 중인 방송이 끝나면 테스트합니다", "info")
            else:
                self._toast("테스트 방송을 시작합니다", "info")
        except ValueError as e:
            self._warn("테스트 방송", str(e))

    def _preview_chime(self, name, folder: Path | None = None):
        path = (folder or self.chime_dir) / name
        if path.is_file():
            threading.Thread(target=play_wav, args=(path, threading.Event()), daemon=True).start()

    def _apply_chimes(self):
        s = self.app.config["broadcast"]
        start, end = self.chime_start_cb.currentText(), self.chime_end_cb.currentText()
        s["chime_start"] = (self.chime_dir / start).is_file()
        s["chime_end"] = (self.chime_dir / end).is_file()
        if s["chime_start"]:
            s["chime_start_file"] = f"assets/chimes/{start}"
        if s["chime_end"]:
            s["chime_end_file"] = f"assets/chimes/{end}"
        self.b.reload_chimes()
        self.chime.setChecked(s["chime_start"])
        self.app.save()
        self._toast("차임벨 설정을 저장했습니다")

    def _apply_fallback(self):
        value = self.fallback_cb.currentText()
        key = "" if value == "(사용 안 함)" else value
        if not key and not self._ask(
                "예비 엔진", "예비 엔진을 끄면 주 엔진이 실패할 때 방송이 오류로 중단됩니다.\n계속할까요?"):
            return
        self.app.set_fallback(key)
        self._toast(f"예비 엔진: {value}")

    def _load_profile(self):
        prof = self.app.config["engines"][self.profile.currentText()]
        self.type_badge.setText(prof["type"])
        self.opts.setPlainText(json.dumps(prof.get("options", {}), ensure_ascii=False, indent=2))
        self._load_voice_sliders(prof)

    def _read_opts(self) -> dict:
        return json.loads(self.opts.toPlainText().strip() or "{}")

    def _set_option(self, key, value):
        try:
            opts = self._read_opts()
        except ValueError:
            opts = {}
        opts[key] = value
        self.opts.setPlainText(json.dumps(opts, ensure_ascii=False, indent=2))

    def _load_voices(self):
        key = self.profile.currentText()
        self.voice_btn.setText("불러오는 중…")
        self.voice_btn.setEnabled(False)

        def done(fn):
            self.voice_btn.setText("음성 목록 불러오기")
            self.voice_btn.setEnabled(True)
            fn()

        def work():
            try:
                if key == self.b.engine_key:
                    voices = self.b.engine.list_voices()
                else:
                    engine = self.app.build_engine(key)
                    try:
                        voices = engine.list_voices()
                    finally:
                        engine.close()
                self.bridge.call.emit(lambda: done(lambda: self._set_voices(voices)))
            except Exception as e:
                msg = str(e)
                self.bridge.call.emit(lambda: done(lambda: self._error("음성 목록", msg)))

        threading.Thread(target=work, daemon=True).start()

    def _set_voices(self, voices):
        current = self._voice_value()
        names = dict(SUPERTONIC_VOICES)
        self.voice.blockSignals(True)
        self.voice.clear()
        for v in voices:
            self.voice.addItem(names.get(v, v), v)
        i = self.voice.findData(current)
        if i >= 0:
            self.voice.setCurrentIndex(i)
        else:
            self.voice.setEditText(current)
        self.voice.blockSignals(False)
        if voices:
            self._toast(f"음성 {len(voices)}개를 불러왔습니다", "info")
            self.voice.showPopup()
        else:
            self._info("음성 목록", "이 엔진은 음성 목록을 제공하지 않습니다.")

    def _apply_engine(self) -> bool:
        try:
            opts = self._read_opts()
        except ValueError as e:
            self._error("옵션 오류", f"JSON 형식이 올바르지 않습니다:\n{e}")
            return False
        try:
            self.app.switch_engine(self.profile.currentText(), opts)
            self._toast(f"'{self.profile.currentText()}' 엔진을 적용했습니다")
            return True
        except Exception as e:
            self._error("엔진 오류", f"엔진을 적용할 수 없습니다 (기존 엔진 유지):\n{e}")
            return False

    # ------------------------------------------------------------ 갱신
    def _on_event(self, kind: str, ann, msg: str):
        today = time.strftime("%Y%m%d")
        if self._stats["day"] != today:
            self._stats.update(done=0, err=0, day=today)
        if kind == "done":
            self._stats["done"] += 1
        elif kind in ("error", "rejected"):
            self._stats["err"] += 1
        values = (time.strftime("%H:%M:%S"), "●  " + EVENT_LABELS.get(kind, kind),
                  PRIORITY_NAMES.get(ann.priority, str(ann.priority)) if ann else "",
                  ann.source if ann else "",
                  (f"{ann.text.replace(chr(10), ' ')[:120]} {msg}" if ann else msg).strip())
        color = TAG_COLORS.get(EVENT_TAGS.get(kind, ""))
        t = self.log_table
        t.insertRow(0)
        for c, v in enumerate(values):
            it = QTableWidgetItem(v)
            if c == 4:
                it.setToolTip(v)
            if color and (c == 1 or EVENT_TAGS.get(kind) == "bad"):
                it.setForeground(QColor(color))
            t.setItem(0, c, it)
        if t.rowCount() > 500:
            t.removeRow(500)

    def _tick(self):
        cur = self.b.current
        if cur is not self._cur_ann:
            self._cur_ann = cur
            self._cur_started = time.time()
        self._blink = not self._blink
        live = cur is not None
        if live != self._live:
            self._live = live
            _set_prop(self.cur_box, "live", live)
            _set_prop(self.onair, "live", live)
            self.stop_btn.setEnabled(live)
            if self.tray:
                self.tray_stop.setEnabled(live)
                self.tray.setToolTip("TTS 방송 - 송출 중" if live else "TTS 방송 - 대기 중")
        if cur:
            emg = cur.priority == PRIORITY_EMERGENCY
            dot = "white" if self._blink else "#fca5a5"
            self.onair.setText(f'<span style="color:{dot}">●</span>&nbsp;&nbsp;ON AIR')
            sc = C["danger"] if (self._blink or not emg) else "#fca5a5"
            self.cur_state.setText(f'<b style="color:{sc}">●&nbsp;&nbsp;{"긴급 송출 중" if emg else "송출 중"}</b>')
            self.cur_text.setText(cur.text[:200])
            el = int(time.time() - self._cur_started)
            self.cur_meta.setText(f"{PRIORITY_NAMES.get(cur.priority, cur.priority)}  ·  {cur.source}  ·  "
                                  f"반복 {cur.repeat}회  ·  경과 {el // 60:02d}:{el % 60:02d}")
        else:
            self.onair.setText("○&nbsp;&nbsp;대기 중")
            self.cur_state.setText(f'<b style="color:{C["muted"]}">○&nbsp;&nbsp;대기 중</b>')
            self.cur_text.setText("현재 송출 중인 방송이 없습니다")
            self.cur_meta.setText("")

        pend = self.b.pending()
        sig = tuple(id(a) for a in pend)
        if sig != self._pending_sig:
            self._pending_sig = sig
            t = self.pending_table
            t.setRowCount(0)
            for a in pend:
                r = t.rowCount()
                t.insertRow(r)
                for c, v in enumerate((PRIORITY_NAMES.get(a.priority, str(a.priority)), a.source,
                                       a.text.replace("\n", " ")[:100])):
                    it = QTableWidgetItem(v)
                    if a.priority == PRIORITY_EMERGENCY:
                        it.setForeground(QColor(C["danger"]))
                    t.setItem(r, c, it)
            self.queue_stack.setCurrentIndex(0 if pend else 1)
        self.queue_badge.setText(f"{len(pend)}건")
        self.stat_labels["queue"].setText(str(len(pend)))
        self.stat_labels["done"].setText(str(self._stats["done"]))
        self.stat_labels["err"].setText(str(self._stats["err"]))

        lt = time.localtime()
        self.clock.setText(time.strftime(f"%Y-%m-%d ({DAY_NAMES[lt.tm_wday]})  %H:%M:%S", lt))
        normal = self.b.engine_key == self.app.config["active_engine"]
        self.sb_engine.setText(f'<span style="color:{C["ok"] if normal else C["warn"]}">●</span>&nbsp;&nbsp;'
                               f'엔진 {html.escape(self.b.engine_key)}{"" if normal else "  (예비 엔진)"}')
        self.sb_queue.setText(f"대기 {len(pend)}건")
        active = sum(1 for i in self.app.scheduler.items() if i.get("enabled", True))
        self.sb_sched.setText(f"예약 {active}건 사용 중")

    # ------------------------------------------------------------ 트레이 (창을 닫아도 방송 계속)
    def _build_tray(self):
        self.tray = None
        self.tray_autostart = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(_logo_pixmap(64)), self)
        self.tray.setToolTip("TTS 방송")
        menu = QMenu(self)
        menu.addAction("창 열기", self.show_window)
        self.tray_stop = menu.addAction("현재 방송 중지", self.b.stop_current)
        menu.addSeparator()
        self.tray_autostart = menu.addAction("Windows 시작 시 자동 실행")
        self.tray_autostart.setCheckable(True)
        self.tray_autostart.setChecked(autostart.is_enabled())
        self.tray_autostart.toggled.connect(self._set_autostart)
        menu.addSeparator()
        menu.addAction("프로그램 종료", self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_window() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
            else None)
        self.tray.show()
        self._tray_hint_shown = False

    def show_window(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _set_autostart(self, on: bool):
        try:
            autostart.set_enabled(on)
        except OSError as e:
            self._error("자동 실행", f"설정하지 못했습니다:\n{e}")
            on = autostart.is_enabled()
        for w in (self.tray_autostart, self.autostart_cb):
            if w is not None and w.isChecked() != on:
                w.blockSignals(True)
                w.setChecked(on)
                w.blockSignals(False)
        log.info("Windows 시작 시 자동 실행: %s", "켬" if on else "끔")
        self._toast("Windows 시작 시 자동 실행: " + ("켬 (트레이에서 조용히 시작)" if on else "끔"))

    def _quit(self):
        self.show_window()
        if self._ask("프로그램 종료", "방송 프로그램을 완전히 종료하면 예약 방송·감시 폴더·API 방송이 모두 중지됩니다.\n"
                                    "종료할까요?", "종료", "취소", danger=True):
            self._force_close = True
            self.close()

    def closeEvent(self, event):
        if self._force_close:
            self.timer.stop()
            if self.tray:
                self.tray.hide()
            event.accept()
            QTimer.singleShot(0, QApplication.quit)
            return
        if self.tray:
            # 창만 숨기고 방송은 계속 (완전 종료는 트레이 메뉴의 '프로그램 종료')
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage("TTS 방송", "창을 닫아도 예약·자동 방송은 계속됩니다.\n"
                                                 "다시 열려면 트레이 아이콘을 누르세요.",
                                      QSystemTrayIcon.Information, 4000)
            return
        if self._ask("종료", "방송 프로그램을 종료하면 예약/자동 방송도 중지됩니다.\n종료할까요?",
                     "종료", "취소", danger=True):
            self._force_close = True
            self.closeEvent(event)
        else:
            event.ignore()


class BroadcastGUI:
    """main.py 에서 사용하는 진입점 (gui.BroadcastGUI 와 같은 사용법).
    start_hidden=True 이면 창 없이 트레이에서 시작 (Windows 시작 시 자동 실행)."""

    def __init__(self, app, start_hidden: bool = False):
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TTSBroadcast.App")
            except Exception:
                pass
        self.qapp = QApplication.instance() or QApplication(sys.argv)
        self.qapp.setQuitOnLastWindowClosed(False)  # 창을 닫아도 트레이에서 계속 실행
        self.qapp.setFont(QFont("Malgun Gothic", 10))
        self.qapp.setStyle("Fusion")
        self.qapp.setStyleSheet(QSS.replace("%CHECK%", _check_image()))
        self.window = BroadcastWindow(app)
        self.start_hidden = start_hidden
        # 프로그램을 또 실행하면 새로 켜지 않고 이 창을 앞으로 불러옴 (instance.activate_running)
        self.server = QLocalServer()
        QLocalServer.removeServer(ACTIVATE_SERVER)
        if self.server.listen(ACTIVATE_SERVER):
            self.server.newConnection.connect(self._on_activate)

    def _on_activate(self):
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: (c.readAll(), self.window.show_window()))
            conn.disconnected.connect(conn.deleteLater)

    @property
    def restart_requested(self) -> bool:
        return self.window.restart_requested

    def run(self):
        w = self.window
        hidden = self.start_hidden and w.tray is not None and bool(w.app.config.get("license_accepted"))
        if hidden:
            w.tray.showMessage("TTS 방송", "트레이에서 실행 중입니다. 예약·자동 방송이 동작합니다.",
                               QSystemTrayIcon.Information, 4000)
            w._tray_hint_shown = True
        else:
            w.show()
        self.qapp.exec()
        self.server.close()
