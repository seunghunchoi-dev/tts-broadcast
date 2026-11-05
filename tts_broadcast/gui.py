"""운영자용 화면 (tkinter, 표준 라이브러리)."""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from . import __version__
from .audio import play_wav
from .broadcaster import PRIORITY_EMERGENCY, PRIORITY_NAMES, Announcement, parse_priority
from .compliance import check as compliance_check
from .compliance import disclosure_ok, in_quiet_hours, license_notice, notice_html, quiet_finding
from .config import resolve_path
from .engines import available_engines
from .scheduler import DAY_NAMES, describe
from .textnorm import normalize

log = logging.getLogger(__name__)

EVENT_LABELS = {"queued": "대기", "start": "송출 시작", "done": "송출 완료",
                "interrupted": "중단(긴급)", "stopped": "중지", "error": "오류",
                "engine": "엔진", "cleared": "대기열 삭제", "fallback": "예비 엔진 사용",
                "warning": "점검 경고", "rejected": "송출 거부"}
FIELD_HINTS = {"차량번호": "예) 12가 3456 또는 3456", "날짜": "예) 11월 3일", "시작날짜": "예) 11월 3일",
               "종료날짜": "예) 11월 10일", "시작시각": "예) 오전 10시 / 14:00",
               "종료시각": "예) 오후 3시 / 17:30", "대상": "예) 101동 전 세대", "위치": "예) 지하 1층 주차장",
               "월": "예) 11", "물품": "예) 검정색 지갑", "인상착의": "예) 노란 우비를 입은 7살 남자",
               "회의명": "예) 입주자대표회의", "공사내용": "예) 외벽 도색", "내용": "예) 폭염 경보"}

FONT = "Malgun Gothic"
MONO = "Consolas"
C = {"bg": "#f1f5f9", "card": "#ffffff", "border": "#e2e8f0", "border_d": "#cbd5e1",
     "text": "#0f172a", "muted": "#64748b", "subtle": "#94a3b8", "input": "#f8fafc",
     "side": "#0f172a", "side_hover": "#1e293b", "side_text": "#94a3b8",
     "primary": "#2563eb", "primary_d": "#1d4ed8", "primary_l": "#eff6ff",
     "danger": "#dc2626", "danger_d": "#b91c1c", "danger_l": "#fef2f2",
     "warn": "#d97706", "warn_l": "#fffbeb", "ok": "#16a34a", "ok_l": "#f0fdf4"}
LEVEL_LABELS = {"block": ("차단", C["danger"], C["danger_l"]), "warn": ("경고", C["warn"], C["warn_l"]),
                "confirm": ("확인", C["primary"], C["primary_l"])}
EVENT_TAGS = {"error": "bad", "fallback": "bad", "rejected": "bad", "warning": "warn",
              "interrupted": "warn", "stopped": "warn", "done": "ok", "start": "live", "queued": "dim"}
PAGES = (("broadcast", "◉", "방송", "문구를 입력해 송출합니다. 긴급 방송은 진행 중인 방송을 끊고 즉시 나갑니다."),
         ("templates", "☰", "안내문 양식", "자주 쓰는 안내문의 빈칸만 채워 바로 송출합니다."),
         ("schedule", "◷", "예약 방송", "지정 시각이나 일정 간격으로 자동 송출합니다."),
         ("facility", "⌂", "시설 설정", "머리말·맺음말, 긴급 방송, AI 음성 고지, 야간 방송 제한을 설정합니다."),
         ("engine", "⚙", "엔진 · 차임벨", "음성 엔진, 예비 엔진, 차임벨을 관리합니다."))


def _enable_dpi_awareness() -> None:
    """고해상도 모니터에서 글자가 흐리게 보이지 않도록 (Windows)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class BroadcastGUI:
    def __init__(self, app):
        self.app = app
        self.b = app.broadcaster
        self.events: queue.Queue = queue.Queue()
        self.b.add_listener(lambda k, a, m: self.events.put((k, a, m)))
        self._toast_win = None
        self._cur_ann = None
        self._cur_started = 0.0
        self._pending_sig = None
        self._blink = False

        _enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("TTS 자동 방송 송출 시스템")
        self.scale = self.root.winfo_fpixels("1i") / 96
        self.root.geometry(f"{self._px(1240)}x{self._px(800)}")
        self.root.minsize(self._px(1040), self._px(680))
        self.root.configure(bg=C["bg"])
        self._setup_style()

        self._build_sidebar()
        main = tk.Frame(self.root, bg=C["bg"])
        main.pack(side="left", fill="both", expand=True)
        self._build_header(main)
        self._build_statusbar(main)
        self.banner = tk.Frame(main, bg=C["warn_l"], highlightthickness=1, highlightbackground="#fcd34d")
        self.pages_host = tk.Frame(main, bg=C["bg"])
        self.pages_host.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        self.pages_host.rowconfigure(0, weight=1)
        self.pages_host.columnconfigure(0, weight=1)

        self.pages: dict[str, ttk.Frame] = {}
        for key, *_ in PAGES:
            page = ttk.Frame(self.pages_host, style="Page.TFrame")
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        self.tab_broadcast = self.pages["broadcast"]
        self._build_broadcast_tab(self.pages["broadcast"])
        self._build_template_tab(self.pages["templates"])
        self._build_schedule_tab(self.pages["schedule"])
        self._build_facility_tab(self.pages["facility"])
        self._build_engine_tab(self.pages["engine"])
        self._show_page("broadcast")
        for i, (key, *_) in enumerate(PAGES, 1):
            self.root.bind_all(f"<Control-Key-{i}>", lambda e, k=key: self._show_page(k))

        if not app.config.get("license_accepted"):
            self.root.after(300, self._license_dialog)
        self._update_banner()
        if not disclosure_ok(app.config["facility"]):
            self.events.put(("warning", None, "AI 음성 고지 미완료: [시설 설정]에서 게시용 안내문을 "
                                              "게시하고 확인 체크를 하세요"))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._poll)
        if app.config["active_engine"] != self.b.engine_key:
            self.root.after(500, lambda: messagebox.showwarning(
                "엔진 오류",
                f"설정된 엔진 '{app.config['active_engine']}' 을(를) 시작할 수 없어\n"
                f"예비 엔진 '{self.b.engine_key}' 으로 방송합니다.\n\n"
                "원인은 logs\\broadcast.log 를 확인하세요."))

    # ------------------------------------------------------------ 테마 / 공통 위젯
    def _px(self, n: float) -> int:
        return int(n * self.scale)

    def _setup_style(self):
        root = self.root
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=FONT, size=10)
            except tk.TclError:
                pass
        root.option_add("*TCombobox*Listbox.font", (FONT, 10))
        root.option_add("*TCombobox*Listbox.selectBackground", C["primary"])
        root.option_add("*Menu.font", (FONT, 10))

        st = ttk.Style(root)
        st.theme_use("clam")
        st.configure(".", font=(FONT, 10), background=C["card"], foreground=C["text"],
                     bordercolor=C["border"], lightcolor=C["card"], darkcolor=C["card"],
                     troughcolor=C["bg"], focuscolor=C["card"], selectbackground=C["primary"],
                     selectforeground="white", fieldbackground=C["input"], insertcolor=C["text"])
        st.configure("Page.TFrame", background=C["bg"])
        st.configure("Muted.TLabel", foreground=C["muted"])
        st.configure("Hint.TLabel", foreground=C["subtle"], font=(FONT, 9))
        st.configure("Field.TLabel", foreground="#334155", font=(FONT, 10, "bold"))
        st.configure("CardTitle.TLabel", font=(FONT, 11, "bold"))
        st.configure("H2.TLabel", font=(FONT, 14, "bold"))
        st.configure("PageTitle.TLabel", background=C["bg"], font=(FONT, 18, "bold"))
        st.configure("PageSub.TLabel", background=C["bg"], foreground=C["muted"])

        # 버튼
        st.configure("TButton", padding=(14, 7), relief="flat", background=C["card"],
                     bordercolor=C["border_d"], lightcolor=C["card"], darkcolor=C["card"])
        st.map("TButton", background=[("disabled", C["bg"]), ("pressed", C["border"]), ("active", C["bg"])],
               foreground=[("disabled", C["subtle"])])
        for name, base, dark in (("Primary", C["primary"], C["primary_d"]),
                                 ("Danger", C["danger"], C["danger_d"])):
            st.configure(f"{name}.TButton", background=base, foreground="white", bordercolor=base,
                         lightcolor=base, darkcolor=base, font=(FONT, 10, "bold"))
            st.map(f"{name}.TButton",
                   background=[("disabled", C["border_d"]), ("pressed", dark), ("active", dark)],
                   bordercolor=[("disabled", C["border_d"]), ("active", dark)],
                   lightcolor=[("active", dark)], darkcolor=[("active", dark)])
            st.configure(f"Big.{name}.TButton", padding=(22, 12), font=(FONT, 12, "bold"))
        st.configure("Outline.TButton", foreground=C["danger"], bordercolor="#fca5a5")
        st.map("Outline.TButton", background=[("pressed", "#fee2e2"), ("active", C["danger_l"])])
        st.configure("Ghost.TButton", background=C["card"], bordercolor=C["card"], foreground=C["muted"],
                     padding=(8, 4))
        st.map("Ghost.TButton", background=[("active", C["bg"])], foreground=[("active", C["text"])])
        st.configure("Chip.TButton", background=C["input"], bordercolor=C["border"], padding=(10, 6),
                     anchor="w")
        st.map("Chip.TButton", background=[("active", C["primary_l"])], foreground=[("active", C["primary"])],
               bordercolor=[("active", "#93c5fd")])

        # 토글(세그먼트·칩)
        for name in ("Seg.Toolbutton", "Day.Toolbutton"):
            st.configure(name, background=C["input"], bordercolor=C["border_d"], padding=(14, 6),
                         relief="flat", lightcolor=C["input"], darkcolor=C["input"], anchor="center")
            st.map(name, background=[("selected", C["primary"]), ("active", C["primary_l"])],
                   foreground=[("selected", "white")],
                   bordercolor=[("selected", C["primary"])],
                   lightcolor=[("selected", C["primary"])], darkcolor=[("selected", C["primary"])])
        st.configure("Day.Toolbutton", padding=(9, 5))

        # 입력
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            st.configure(name, padding=(8, 6), fieldbackground=C["input"], bordercolor=C["border_d"],
                         lightcolor=C["input"], darkcolor=C["input"], arrowcolor=C["muted"],
                         background=C["input"])
            st.map(name, bordercolor=[("focus", C["primary"])], lightcolor=[("focus", C["primary"])],
                   fieldbackground=[("readonly", C["input"]), ("disabled", C["bg"])],
                   foreground=[("disabled", C["subtle"])], selectbackground=[("readonly", C["input"])],
                   selectforeground=[("readonly", C["text"])])
        for name in ("TCheckbutton", "TRadiobutton"):
            st.configure(name, background=C["card"], indicatorbackground="white",
                         indicatorforeground="white", indicatormargin=(0, 0, 8, 0), padding=(0, 4))
            st.map(name, background=[("active", C["card"])],
                   indicatorbackground=[("selected", C["primary"]), ("active", C["primary_l"])])

        # 표
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Treeview", background=C["card"], fieldbackground=C["card"], borderwidth=0,
                     rowheight=self._px(32), font=(FONT, 10))
        st.map("Treeview", background=[("selected", C["primary_l"])],
               foreground=[("selected", C["text"])])
        st.configure("Treeview.Heading", background=C["input"], foreground=C["muted"], relief="flat",
                     font=(FONT, 9, "bold"), padding=(8, 7), bordercolor=C["border"])
        st.map("Treeview.Heading", background=[("active", C["border"])])
        st.configure("Nav.Treeview", rowheight=self._px(30))

        # 스크롤바 (화살표 없는 얇은 형태)
        st.layout("Slim.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
            "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})], "sticky": "ns"})])
        st.configure("Slim.Vertical.TScrollbar", troughcolor=C["card"], background=C["border_d"],
                     bordercolor=C["card"], lightcolor=C["border_d"], darkcolor=C["border_d"],
                     arrowsize=self._px(9), gripcount=0)
        st.map("Slim.Vertical.TScrollbar", background=[("active", C["subtle"])])

    def _card(self, parent, title: str | None = None, desc: str | None = None, pad: int = 16):
        """흰 바탕 카드. outer.head 에 오른쪽 정렬 버튼 등을 붙일 수 있음."""
        outer = tk.Frame(parent, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["border"], highlightcolor=C["border"])
        outer.head = None
        if title:
            head = ttk.Frame(outer, padding=(pad, pad - 4, pad - 8, 0))
            head.pack(fill="x")
            ttk.Label(head, text=title, style="CardTitle.TLabel").pack(side="left")
            if desc:
                ttk.Label(head, text=desc, style="Hint.TLabel").pack(side="left", padx=(10, 0), pady=(3, 0))
            outer.head = head
        body = ttk.Frame(outer, padding=(pad, 10 if title else pad, pad, pad))
        body.pack(fill="both", expand=True)
        return outer, body

    def _textbox(self, parent, height: int, size: int = 11, mono: bool = False, **kw) -> tk.Text:
        return tk.Text(parent, height=height, wrap="word", relief="flat", bd=0, padx=12, pady=10,
                       font=(MONO if mono else FONT, size), bg=C["input"], fg=C["text"],
                       insertbackground=C["text"], selectbackground=C["primary"],
                       highlightthickness=1, highlightbackground=C["border_d"],
                       highlightcolor=C["primary"], **kw)

    def _badge(self, parent, text: str, fg: str = None, bg: str = None) -> tk.Label:
        return tk.Label(parent, text=text, fg=fg or C["primary"], bg=bg or C["primary_l"],
                        font=(FONT, 9, "bold"), padx=8, pady=2)

    def _tree(self, parent, cols, heads, widths, height=8, stretch_last=True):
        wrap = ttk.Frame(parent)
        tree = ttk.Treeview(wrap, columns=cols, show="headings", height=height)
        for i, (c, t, w) in enumerate(zip(cols, heads, widths)):
            tree.heading(c, text=t, anchor="w")
            tree.column(c, width=self._px(w), minwidth=self._px(40), anchor="w",
                        stretch=stretch_last and i == len(cols) - 1)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview, style="Slim.Vertical.TScrollbar")
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tree.tag_configure("odd", background="#fafbfd")
        for tag, color in (("bad", C["danger"]), ("warn", C["warn"]), ("ok", C["ok"]),
                           ("live", C["primary"]), ("dim", C["muted"]), ("off", C["subtle"])):
            tree.tag_configure(tag, foreground=color)
        return wrap, tree

    def _center(self, dlg):
        dlg.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dlg.winfo_reqheight()) // 3
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _toast(self, msg: str, kind: str = "ok"):
        """잠깐 떴다 사라지는 알림 (확인 버튼 누를 필요 없음)."""
        if self._toast_win is not None:
            try:
                self._toast_win.destroy()
            except tk.TclError:
                pass
        color = {"ok": "#4ade80", "warn": "#fbbf24", "info": "#60a5fa"}.get(kind, "#4ade80")
        t = self._toast_win = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        f = tk.Frame(t, bg=C["side"], padx=16, pady=11)
        f.pack()
        tk.Label(f, text="●", fg=color, bg=C["side"], font=(FONT, 10)).pack(side="left", padx=(0, 8))
        tk.Label(f, text=msg, fg="white", bg=C["side"], font=(FONT, 10)).pack(side="left")
        t.update_idletasks()
        x = self.root.winfo_rootx() + self.root.winfo_width() - t.winfo_reqwidth() - self._px(28)
        y = self.root.winfo_rooty() + self.root.winfo_height() - t.winfo_reqheight() - self._px(52)
        t.geometry(f"+{x}+{y}")
        t.after(2600, lambda: t.winfo_exists() and t.destroy())

    # ------------------------------------------------------------ 골격: 사이드바 / 헤더 / 상태바
    def _build_sidebar(self):
        side = tk.Frame(self.root, bg=C["side"], width=self._px(220))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=C["side"], padx=20, pady=22)
        brand.pack(fill="x")
        logo = tk.Label(brand, text="◉", fg="white", bg=C["primary"], font=(FONT, 13, "bold"),
                        width=2, pady=2)
        logo.pack(side="left")
        bt = tk.Frame(brand, bg=C["side"])
        bt.pack(side="left", padx=(10, 0))
        tk.Label(bt, text="TTS 방송", fg="white", bg=C["side"], font=(FONT, 13, "bold")).pack(anchor="w")
        tk.Label(bt, text="자동 방송 송출 시스템", fg=C["side_text"], bg=C["side"],
                 font=(FONT, 8)).pack(anchor="w")
        tk.Label(side, text="메뉴", fg="#475569", bg=C["side"], font=(FONT, 8, "bold"),
                 anchor="w", padx=22).pack(fill="x", pady=(6, 4))

        self.nav: dict[str, tuple] = {}
        for i, (key, icon, label, _) in enumerate(PAGES, 1):
            row = tk.Frame(side, bg=C["side"], cursor="hand2")
            row.pack(fill="x", padx=10, pady=1)
            bar = tk.Frame(row, bg=C["side"], width=3)
            bar.pack(side="left", fill="y")
            ic = tk.Label(row, text=icon, fg=C["side_text"], bg=C["side"], font=("Segoe UI Symbol", 12),
                          width=2, pady=9)
            ic.pack(side="left", padx=(10, 6))
            tx = tk.Label(row, text=label, fg=C["side_text"], bg=C["side"], font=(FONT, 10), anchor="w")
            tx.pack(side="left", fill="x", expand=True)
            kb = tk.Label(row, text=f"Ctrl+{i}", fg="#475569", bg=C["side"], font=(FONT, 8))
            kb.pack(side="right", padx=10)
            widgets = (row, bar, ic, tx, kb)
            self.nav[key] = widgets
            for w in (row, ic, tx, kb):
                w.bind("<Button-1>", lambda e, k=key: self._show_page(k))
                w.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))

        foot = tk.Frame(side, bg=C["side"], padx=20, pady=16)
        foot.pack(side="bottom", fill="x")
        self.side_facility = tk.Label(foot, text="", fg="#cbd5e1", bg=C["side"], font=(FONT, 9, "bold"),
                                      anchor="w", wraplength=self._px(180), justify="left")
        self.side_facility.pack(fill="x")
        tk.Label(foot, text=f"버전 {__version__}", fg="#475569", bg=C["side"], font=(FONT, 8),
                 anchor="w").pack(fill="x")
        self._update_side_facility()

    def _update_side_facility(self):
        self.side_facility.configure(text=self.app.config["facility"].get("name") or "시설명 미설정")

    def _nav_hover(self, key, on):
        if key == getattr(self, "current_page", None):
            return
        bg = C["side_hover"] if on else C["side"]
        row, bar, ic, tx, kb = self.nav[key]
        for w in (row, bar, ic, tx, kb):
            w.configure(bg=bg)

    def _show_page(self, key):
        self.current_page = key
        for k, (row, bar, ic, tx, kb) in self.nav.items():
            active = k == key
            bg = C["side_hover"] if active else C["side"]
            for w in (row, ic, tx, kb):
                w.configure(bg=bg)
            bar.configure(bg=C["primary"] if active else C["side"])
            ic.configure(fg="white" if active else C["side_text"])
            tx.configure(fg="white" if active else C["side_text"],
                         font=(FONT, 10, "bold") if active else (FONT, 10))
        _, _, title, sub = next(p for p in PAGES if p[0] == key)
        self.page_title.set(title)
        self.page_sub.set(sub)
        self.pages[key].tkraise()
        if key == "broadcast":
            self.text.focus_set()
        elif key == "schedule":
            self._refresh_sched()

    def _build_header(self, parent):
        head = ttk.Frame(parent, style="Page.TFrame", padding=(24, 20, 24, 14))
        head.pack(fill="x")
        left = ttk.Frame(head, style="Page.TFrame")
        left.pack(side="left", fill="x", expand=True)
        self.page_title = tk.StringVar()
        self.page_sub = tk.StringVar()
        ttk.Label(left, textvariable=self.page_title, style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(left, textvariable=self.page_sub, style="PageSub.TLabel").pack(anchor="w", pady=(2, 0))

        right = tk.Frame(head, bg=C["bg"])
        right.pack(side="right")
        self.clock = tk.Label(right, bg=C["bg"], fg=C["muted"], font=(FONT, 10))
        self.clock.pack(side="right", padx=(14, 0))
        self.onair = tk.Label(right, font=(FONT, 10, "bold"), padx=14, pady=6)
        self.onair.pack(side="right")

    def _build_statusbar(self, parent):
        bar = tk.Frame(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["border"])
        bar.pack(side="bottom", fill="x")
        inner = tk.Frame(bar, bg=C["card"], padx=20, pady=6)
        inner.pack(fill="x")

        def item(side="left"):
            lbl = tk.Label(inner, bg=C["card"], fg=C["muted"], font=(FONT, 9))
            lbl.pack(side=side, padx=(0, 22) if side == "left" else (22, 0))
            return lbl

        self.sb_engine = item()
        self.sb_queue = item()
        self.sb_sched = item()
        extra = []
        if self.app.watcher:
            extra.append("감시 폴더 켜짐")
        if self.app.api:
            api = self.app.config["api"]
            extra.append(f"API {api['host']}:{api['port']}")
        self.sb_extra = item("right")
        self.sb_extra.configure(text="   ·   ".join(extra))

    def _update_banner(self):
        for w in self.banner.winfo_children():
            w.destroy()
        if disclosure_ok(self.app.config["facility"]):
            self.banner.pack_forget()
            return
        inner = tk.Frame(self.banner, bg=C["warn_l"], padx=16, pady=9)
        inner.pack(fill="x")
        tk.Label(inner, text="⚠", fg=C["warn"], bg=C["warn_l"], font=("Segoe UI Symbol", 12)).pack(side="left")
        tk.Label(inner, text="AI 음성 고지가 완료되지 않았습니다.  게시용 안내문을 게시하고 확인 체크를 해 주세요.",
                 fg="#92400e", bg=C["warn_l"], font=(FONT, 10)).pack(side="left", padx=(8, 0))
        link = tk.Label(inner, text="시설 설정으로 이동 →", fg=C["primary"], bg=C["warn_l"],
                        font=(FONT, 10, "bold"), cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: self._show_page("facility"))
        self.banner.pack(fill="x", padx=24, pady=(0, 14), before=self.pages_host)

    # ------------------------------------------------------------ 방송 탭
    def _build_broadcast_tab(self, f):
        f.columnconfigure(0, weight=3)
        f.columnconfigure(1, weight=2, minsize=self._px(340))
        f.rowconfigure(1, weight=1)

        comp, body = self._card(f, "방송 문구", "Ctrl+Enter 로 바로 송출")
        comp.grid(row=0, column=0, sticky="nsew", padx=(0, 16), pady=(0, 16))
        self.char_count = ttk.Label(comp.head, style="Hint.TLabel")
        self.char_count.pack(side="right", padx=(0, 8))
        self.text = self._textbox(body, height=5, size=13)
        self.text.pack(fill="x")
        self.text.bind("<Control-Return>", lambda e: (self._send(), "break")[1])
        self.text.bind("<<Modified>>", self._on_text_modified)
        self._on_text_modified()

        opt = ttk.Frame(body)
        opt.pack(fill="x", pady=(12, 0))
        ttk.Label(opt, text="우선순위", style="Field.TLabel").pack(side="left", padx=(0, 8))
        self.prio = tk.StringVar(value="보통")
        for name in ("보통", "높음", "긴급"):
            ttk.Radiobutton(opt, text=name, value=name, variable=self.prio,
                            style="Seg.Toolbutton").pack(side="left")
        ttk.Label(opt, text="반복", style="Field.TLabel").pack(side="left", padx=(20, 8))
        self.repeat_var = tk.StringVar(value="1")
        self.repeat = ttk.Spinbox(opt, from_=1, to=10, width=3, textvariable=self.repeat_var,
                                  state="readonly")
        self.repeat.pack(side="left")
        ttk.Label(opt, text="회", style="Muted.TLabel").pack(side="left", padx=(4, 20))
        self.chime = tk.BooleanVar(value=bool(self.app.config["broadcast"].get("chime_start", True)))
        ttk.Checkbutton(opt, text="차임벨", variable=self.chime).pack(side="left")
        ttk.Button(opt, text="읽기 확인", style="Ghost.TButton",
                   command=self._show_reading).pack(side="right")

        act = ttk.Frame(body)
        act.pack(fill="x", pady=(14, 0))
        ttk.Button(act, text="▶  방송 송출", style="Big.Primary.TButton",
                   command=self._send).pack(side="left", fill="x", expand=True)
        ttk.Button(act, text="⚠  긴급 방송", style="Big.Danger.TButton",
                   command=lambda: self._send("긴급")).pack(side="left", padx=(10, 0))

        presets = self.app.config.get("presets") or []
        if presets:
            ttk.Label(body, text="자주 쓰는 문구", style="Field.TLabel").pack(anchor="w", pady=(18, 6))
            pf = ttk.Frame(body)
            pf.pack(fill="x")
            for i, p in enumerate(presets):
                label = p if len(p) <= 20 else p[:19] + "…"
                ttk.Button(pf, text=label, style="Chip.TButton", command=lambda t=p: self._fill(t)).grid(
                    row=i // 3, column=i % 3, sticky="ew", padx=(0, 6), pady=(0, 6))
            for c in range(3):
                pf.columnconfigure(c, weight=1, uniform="preset")

        # 송출 상태
        cur, cb = self._card(f, "송출 상태")
        cur.grid(row=0, column=1, sticky="nsew", pady=(0, 16))
        self.cur_box = tk.Frame(cb, bg=C["input"], highlightthickness=1, highlightbackground=C["border"])
        self.cur_box.pack(fill="x")
        cin = tk.Frame(self.cur_box, bg=C["input"], padx=14, pady=12)
        cin.pack(fill="x")
        self.cur_state = tk.Label(cin, bg=C["input"], font=(FONT, 10, "bold"), anchor="w")
        self.cur_state.pack(fill="x")
        self.cur_var = tk.StringVar(value="현재 송출 중인 방송이 없습니다")
        self.cur_text = tk.Label(cin, textvariable=self.cur_var, bg=C["input"], fg=C["text"],
                                 font=(FONT, 12), anchor="w", justify="left", wraplength=self._px(290))
        self.cur_text.pack(fill="x", pady=(6, 2))
        self.cur_meta = tk.Label(cin, bg=C["input"], fg=C["muted"], font=(FONT, 9), anchor="w")
        self.cur_meta.pack(fill="x")
        cbtn = ttk.Frame(cb)
        cbtn.pack(fill="x", pady=(12, 0))
        self.stop_btn = ttk.Button(cbtn, text="■  현재 방송 중지", style="Outline.TButton",
                                   command=self.b.stop_current)
        self.stop_btn.pack(side="left", fill="x", expand=True)
        ttk.Button(cbtn, text="대기열 비우기", command=self._clear_queue).pack(side="left", padx=(8, 0))

        stats = ttk.Frame(cb)
        stats.pack(fill="x", pady=(14, 0))
        self.stat_vars = {}
        for i, (k, label) in enumerate((("queue", "대기"), ("done", "오늘 송출"), ("err", "오류"))):
            box = tk.Frame(stats, bg=C["card"], highlightthickness=1, highlightbackground=C["border"])
            box.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            stats.columnconfigure(i, weight=1, uniform="stat")
            v = tk.StringVar(value="0")
            self.stat_vars[k] = v
            tk.Label(box, textvariable=v, bg=C["card"], fg=C["danger"] if k == "err" else C["text"],
                     font=(FONT, 16, "bold")).pack(pady=(8, 0))
            tk.Label(box, text=label, bg=C["card"], fg=C["muted"], font=(FONT, 9)).pack(pady=(0, 8))
        self._stats = {"done": 0, "err": 0, "day": time.strftime("%Y%m%d")}

        # 방송 기록
        lf, lb = self._card(f, "방송 기록", "최근 500건")
        lf.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        ttk.Button(lf.head, text="지우기", style="Ghost.TButton",
                   command=lambda: self.log_list.delete(*self.log_list.get_children())).pack(side="right")
        wrap, self.log_list = self._tree(lb, ("time", "kind", "prio", "src", "text"),
                                         ("시각", "구분", "우선", "출처", "내용"), (76, 96, 56, 96, 400))
        wrap.pack(fill="both", expand=True)

        # 대기열
        qf, qb = self._card(f, "대기열")
        qf.grid(row=1, column=1, sticky="nsew")
        self.queue_count = self._badge(qf.head, "0건", fg=C["muted"], bg=C["bg"])
        self.queue_count.pack(side="right", padx=(0, 8))
        wrap, self.pending_list = self._tree(qb, ("prio", "src", "text"), ("우선", "출처", "내용"),
                                             (56, 86, 200), height=5)
        wrap.pack(fill="both", expand=True)
        self.pending_empty = tk.Label(qb, text="대기 중인 방송이 없습니다", bg=C["card"], fg=C["subtle"],
                                      font=(FONT, 9))
        self.pending_empty.place(relx=0.5, rely=0.55, anchor="center")

    def _on_text_modified(self, _event=None):
        text = self.text.get("1.0", "end").strip()
        n = len(text)
        self.char_count.configure(text=f"{n}자 · 약 {max(1, round(n / 6))}초" if n else "")
        self.text.edit_modified(False)

    def _clear_queue(self):
        n = self.b.clear_queue()
        if n:
            self._toast(f"대기열 {n}건을 비웠습니다", "info")

    def _show_reading(self):
        text = self.text.get("1.0", "end").strip()
        if not text:
            self._toast("방송 문구를 먼저 입력하세요", "warn")
            return
        ann = Announcement(text=text, priority=parse_priority(self.prio.get()))
        reading = normalize(self.b.compose(ann))
        dlg, body, footer = self._dialog("실제 송출 내용", "머리말·숫자 읽기 변환이 적용된 최종 문구입니다.",
                                         C["primary"])
        txt = self._textbox(body, height=8, size=12, width=60)
        txt.insert("1.0", reading)
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)
        ttk.Button(footer, text="닫기", style="Primary.TButton", command=dlg.destroy).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        self._center(dlg)
        dlg.grab_set()

    def _dialog(self, title: str, subtitle: str, color: str):
        """색 띠 머리글이 있는 모달 대화상자 골격."""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.configure(bg=C["card"])
        head = tk.Frame(dlg, bg=color, padx=22, pady=16)
        head.pack(fill="x")
        tk.Label(head, text=title, bg=color, fg="white", font=(FONT, 13, "bold"), anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(head, text=subtitle, bg=color, fg="#e2e8f0", font=(FONT, 9), anchor="w",
                     justify="left").pack(fill="x", pady=(3, 0))
        body = ttk.Frame(dlg, padding=(22, 18, 22, 6))
        body.pack(fill="both", expand=True)
        footer = ttk.Frame(dlg, padding=(22, 10, 22, 18))
        footer.pack(fill="x", side="bottom")
        return dlg, body, footer

    # ------------------------------------------------------------ 송출 전 점검
    def _review(self, text: str, priority: int) -> str | None:
        """위반 소지 점검. 송출할 최종 문구를 돌려주고, 취소하면 None."""
        findings = compliance_check(text)
        if priority > PRIORITY_EMERGENCY and in_quiet_hours(self.app.config["facility"]):
            findings.append(quiet_finding(self.app.config["facility"]))
        if not findings:
            return text
        blocked = any(f.level == "block" for f in findings)
        result = {"text": None}

        dlg, body, footer = self._dialog(
            "방송 내용 점검",
            "송출할 수 없는 내용이 있습니다." if blocked
            else "라이선스·개인정보 위반 소지가 있는 내용이 있습니다. 확인 후 송출하세요.",
            C["danger"] if blocked else C["warn"])
        dlg.resizable(False, False)
        for f in findings:
            label, color, light = LEVEL_LABELS[f.level]
            box = tk.Frame(body, bg=light, highlightthickness=1, highlightbackground=C["border"])
            box.pack(fill="x", pady=(0, 8))
            tk.Frame(box, bg=color, width=4).pack(side="left", fill="y")
            inner = tk.Frame(box, bg=light, padx=12, pady=10)
            inner.pack(side="left", fill="both", expand=True)
            top = tk.Frame(inner, bg=light)
            top.pack(fill="x")
            tk.Label(top, text=label, bg=color, fg="white", font=(FONT, 8, "bold"), padx=6).pack(side="left")
            tk.Label(top, text=f.title, bg=light, fg=C["text"], font=(FONT, 10, "bold")).pack(side="left", padx=8)
            tk.Label(inner, text=f.detail, bg=light, fg="#334155", wraplength=self._px(500), justify="left",
                     anchor="w").pack(fill="x", pady=(6, 0))
            tk.Label(inner, text=f"근거: {f.clause}", bg=light, fg=C["muted"], font=(FONT, 9),
                     anchor="w").pack(fill="x", pady=(4, 0))
        ttk.Label(body, text="※ 자동 점검은 보조 수단이며, 방송 내용의 책임은 운영자에게 있습니다.",
                  style="Hint.TLabel").pack(anchor="w", pady=(4, 0))

        def done(value):
            result["text"] = value
            dlg.destroy()

        if not blocked:
            ttk.Button(footer, text="확인했습니다. 그대로 송출", style="Primary.TButton",
                       command=lambda: done(text)).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="취소 (문구 수정)", command=lambda: done(None)).pack(side="right")
        dlg.bind("<Escape>", lambda e: done(None))
        self._center(dlg)
        dlg.grab_set()
        dlg.wait_window()
        if result["text"] is not None:
            log.warning("운영자 확인 후 송출 (%s): %s",
                        ", ".join(f.title for f in findings), result["text"][:80])
        return result["text"]

    def _submit(self, text: str, priority: int, repeat: int, chime: bool, source: str) -> bool:
        final = self._review(text, priority)
        if final is None:
            return False
        try:
            self.b.submit(Announcement(text=final, priority=priority, repeat=repeat,
                                       chime=chime, source=source, confirmed=True))
            self._toast("긴급 방송을 송출합니다" if priority == PRIORITY_EMERGENCY
                        else "방송을 대기열에 넣었습니다", "warn" if priority == PRIORITY_EMERGENCY else "ok")
            return True
        except ValueError as e:
            messagebox.showerror("방송 오류", str(e))
            return False

    def _fill(self, text):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.focus_set()

    def _send(self, priority=None):
        text = self.text.get("1.0", "end").strip()
        if not text:
            self._toast("방송 문구를 입력하세요", "warn")
            self.text.focus_set()
            return
        if self._submit(text, parse_priority(priority or self.prio.get()),
                        int(self.repeat.get()), self.chime.get(), "운영자"):
            self.text.delete("1.0", "end")

    # ------------------------------------------------------------ 안내문 양식 탭
    def _build_template_tab(self, f):
        f.columnconfigure(1, weight=1)
        f.rowconfigure(0, weight=1)
        left, lb = self._card(f, "양식 목록")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        ttk.Button(left.head, text="↻ 다시 불러오기", style="Ghost.TButton",
                   command=self._load_templates).pack(side="right")
        self.tpl_search = tk.StringVar()
        se = ttk.Entry(lb, textvariable=self.tpl_search, width=28)
        se.pack(fill="x", pady=(0, 10))
        self._placeholder(se, self.tpl_search, "이름 또는 내용으로 검색")
        self.tpl_search.trace_add("write", lambda *a: self._render_templates())
        wrap = ttk.Frame(lb)
        wrap.pack(fill="both", expand=True)
        self.tpl_tree = ttk.Treeview(wrap, show="tree", selectmode="browse", style="Nav.Treeview")
        self.tpl_tree.column("#0", width=self._px(250))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tpl_tree.yview, style="Slim.Vertical.TScrollbar")
        self.tpl_tree.configure(yscrollcommand=sb.set)
        self.tpl_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tpl_tree.tag_configure("cat", font=(FONT, 10, "bold"), foreground=C["muted"])
        self.tpl_tree.bind("<<TreeviewSelect>>", lambda e: self._select_template())

        right, rb = self._card(f)
        right.grid(row=0, column=1, sticky="nsew")
        self.tpl_title = tk.StringVar(value="왼쪽 목록에서 양식을 선택하세요")
        ttk.Label(rb, textvariable=self.tpl_title, style="H2.TLabel").pack(anchor="w")
        self.tpl_meta = ttk.Frame(rb)
        self.tpl_meta.pack(fill="x", pady=(8, 0))

        ttk.Label(rb, text="빈칸 채우기", style="Field.TLabel").pack(anchor="w", pady=(20, 8))
        self.tpl_fields = ttk.Frame(rb)
        self.tpl_fields.pack(fill="x")
        self.tpl_fields.columnconfigure(1, weight=1)

        ttk.Label(rb, text="방송 문구 미리보기", style="Field.TLabel").pack(anchor="w", pady=(20, 8))
        self.tpl_preview = self._textbox(rb, height=6, size=12, state="disabled")
        self.tpl_preview.tag_configure("blank", foreground=C["danger"], background=C["danger_l"])
        self.tpl_preview.pack(fill="x")

        bf = ttk.Frame(rb)
        bf.pack(fill="x", pady=(16, 0))
        self.tpl_send_btn = ttk.Button(bf, text="▶  바로 송출", style="Big.Primary.TButton",
                                       command=self._send_template)
        self.tpl_send_btn.pack(side="left")
        ttk.Button(bf, text="방송 화면으로 보내기 (수정 후 송출)",
                   command=self._template_to_broadcast).pack(side="left", padx=10)
        ttk.Label(rb, text="양식은 templates.json 에서 추가·수정할 수 있습니다. {이름} 부분이 빈칸이 됩니다.",
                  style="Hint.TLabel").pack(anchor="w", side="bottom")
        self.tpl_vars: dict[str, tk.StringVar] = {}
        self.tpl_current = None
        self._load_templates()

    def _placeholder(self, entry: ttk.Entry, var: tk.StringVar, hint: str):
        """빈 입력란에 흐린 안내 문구 표시."""
        lbl = tk.Label(entry, text=hint, bg=C["input"], fg=C["subtle"], font=(FONT, 10), cursor="xterm")

        def sync(*_):
            if var.get() or entry.focus_get() is entry:
                lbl.place_forget()
            else:
                lbl.place(x=self._px(9), rely=0.5, anchor="w")

        lbl.bind("<Button-1>", lambda e: entry.focus_set())
        entry.bind("<FocusIn>", sync, add="+")
        entry.bind("<FocusOut>", sync, add="+")
        var.trace_add("write", sync)
        sync()

    def _load_templates(self):
        path = resolve_path(self.app.config.get("templates_file", "templates.json"))
        try:
            with open(path, encoding="utf-8-sig") as fp:
                self.templates = json.load(fp)
        except (OSError, ValueError) as e:
            self.templates = []
            messagebox.showerror("안내문 양식", f"양식 파일을 읽을 수 없습니다: {e}")
        self._render_templates()

    def _render_templates(self):
        q = self.tpl_search.get().strip()
        self.tpl_tree.delete(*self.tpl_tree.get_children())
        cats = {}
        for i, t in enumerate(self.templates):
            if q and q not in t["name"] and q not in t.get("text", "") and q not in t.get("category", ""):
                continue
            cat = t.get("category", "기타")
            if cat not in cats:
                cats[cat] = self.tpl_tree.insert("", "end", text=cat, open=True, tags=("cat",))
            self.tpl_tree.insert(cats[cat], "end", iid=f"t{i}", text=f"   {t['name']}")

    def _select_template(self):
        sel = self.tpl_tree.selection()
        if not sel or not sel[0].startswith("t"):
            return
        t = self.templates[int(sel[0][1:])]
        self.tpl_current = t
        self.tpl_title.set(t["name"])
        for w in self.tpl_meta.winfo_children():
            w.destroy()
        prio = PRIORITY_NAMES.get(parse_priority(t.get("priority")), "보통")
        self._badge(self.tpl_meta, t.get("category", "기타"), fg=C["muted"], bg=C["bg"]).pack(side="left")
        if prio == "긴급":
            self._badge(self.tpl_meta, f"우선순위 {prio}", C["danger"], C["danger_l"]).pack(side="left", padx=6)
        else:
            self._badge(self.tpl_meta, f"우선순위 {prio}").pack(side="left", padx=6)
        self._badge(self.tpl_meta, f"반복 {t.get('repeat', 1)}회", fg=C["muted"], bg=C["bg"]).pack(side="left")

        for w in self.tpl_fields.winfo_children():
            w.destroy()
        self.tpl_vars = {}
        names = list(dict.fromkeys(re.findall(r"\{(\w+)\}", t["text"])))
        first = None
        for r, name in enumerate(names):
            var = tk.StringVar()
            var.trace_add("write", lambda *a: self._update_preview())
            self.tpl_vars[name] = var
            ttk.Label(self.tpl_fields, text=name).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 14))
            e = ttk.Entry(self.tpl_fields, textvariable=var)
            e.grid(row=r, column=1, sticky="ew", pady=4)
            e.bind("<Return>", lambda ev: ev.widget.tk_focusNext().focus_set())
            first = first or e
            ttk.Label(self.tpl_fields, text=FIELD_HINTS.get(name, ""), style="Hint.TLabel").grid(
                row=r, column=2, sticky="w", padx=(12, 0))
        if not names:
            ttk.Label(self.tpl_fields, text="채울 빈칸이 없습니다. 바로 송출할 수 있습니다.",
                      style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        if first:
            first.focus_set()
        self._update_preview()

    def _template_text(self) -> str:
        if not self.tpl_current:
            return ""
        return re.sub(r"\{(\w+)\}", lambda m: self.tpl_vars[m.group(1)].get().strip() or m.group(0),
                      self.tpl_current["text"])

    def _update_preview(self):
        text = self._template_text()
        self.tpl_preview.configure(state="normal")
        self.tpl_preview.delete("1.0", "end")
        self.tpl_preview.insert("1.0", text)
        for m in re.finditer(r"\{(\w+)\}", text):
            self.tpl_preview.tag_add("blank", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        self.tpl_preview.configure(state="disabled")

    def _template_ready(self) -> str | None:
        text = self._template_text()
        if not text:
            self._toast("먼저 양식을 선택하세요", "warn")
            return None
        missing = re.findall(r"\{(\w+)\}", text)
        if missing:
            self._toast("빈칸을 채워 주세요: " + ", ".join(missing), "warn")
            return None
        return text

    def _send_template(self):
        text = self._template_ready()
        if text:
            t = self.tpl_current
            self._submit(text, parse_priority(t.get("priority")), int(t.get("repeat", 1)),
                         self.chime.get(), f"양식:{t['name']}")

    def _template_to_broadcast(self):
        text = self._template_ready()
        if text:
            t = self.tpl_current
            self._fill(text)
            self.prio.set(PRIORITY_NAMES.get(parse_priority(t.get("priority")), "보통"))
            self.repeat_var.set(str(t.get("repeat", 1)))
            self._show_page("broadcast")

    # ------------------------------------------------------------ 시설 설정 탭
    def _build_facility_tab(self, f):
        fac = self.app.config["facility"]
        q = fac.setdefault("quiet_hours", {"enabled": False, "start": "22:00", "end": "07:00"})
        self.fac_name = tk.StringVar(value=fac.get("name", ""))
        self.fac_intro_on = tk.BooleanVar(value=fac.get("intro_enabled", True))
        self.fac_intro = tk.StringVar(value=fac.get("intro", ""))
        self.fac_intro_emg = tk.BooleanVar(value=fac.get("intro_on_emergency", True))
        self.fac_outro_on = tk.BooleanVar(value=fac.get("outro_enabled", False))
        self.fac_outro = tk.StringVar(value=fac.get("outro", ""))
        self.fac_quiet_on = tk.BooleanVar(value=q.get("enabled", True))
        self.fac_quiet_start = tk.StringVar(value=q.get("start", "22:00"))
        self.fac_quiet_end = tk.StringVar(value=q.get("end", "07:00"))
        f.columnconfigure(0, weight=1, uniform="fac")
        f.columnconfigure(1, weight=1, uniform="fac")
        f.rowconfigure(1, weight=1)

        gc, g = self._card(f, "시설 정보 · 머리말 / 맺음말", "{시설} 은 시설명으로 바뀝니다")
        gc.grid(row=0, column=0, sticky="nsew", padx=(0, 16), pady=(0, 16))
        g.columnconfigure(0, weight=1)
        ttk.Label(g, text="시설명", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(g, textvariable=self.fac_name).grid(row=1, column=0, sticky="ew", pady=(4, 12))
        ttk.Checkbutton(g, text="머리말 사용", variable=self.fac_intro_on).grid(row=2, column=0, sticky="w")
        ttk.Entry(g, textvariable=self.fac_intro).grid(row=3, column=0, sticky="ew", pady=(2, 2))
        ttk.Checkbutton(g, text="긴급 방송에도 머리말 사용", variable=self.fac_intro_emg).grid(
            row=4, column=0, sticky="w", pady=(0, 10))
        ttk.Checkbutton(g, text="맺음말 사용", variable=self.fac_outro_on).grid(row=5, column=0, sticky="w")
        ttk.Entry(g, textvariable=self.fac_outro).grid(row=6, column=0, sticky="ew", pady=(2, 0))

        qc, qf = self._card(f, "야간 방송 제한")
        qc.grid(row=1, column=0, sticky="new", padx=(0, 16))
        row = ttk.Frame(qf)
        row.pack(fill="x")
        ttk.Checkbutton(row, text="사용", variable=self.fac_quiet_on).pack(side="left", padx=(0, 16))
        ttk.Entry(row, textvariable=self.fac_quiet_start, width=7, justify="center").pack(side="left")
        ttk.Label(row, text="  ~  ", style="Muted.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.fac_quiet_end, width=7, justify="center").pack(side="left")
        ttk.Label(qf, text="이 시간에는 긴급 방송만 자동 송출되고, 운영자 방송은 확인 후 송출됩니다.",
                  style="Hint.TLabel").pack(anchor="w", pady=(10, 0))

        self.fac_mode = tk.StringVar(value=fac.get("disclosure_mode", "notice"))
        self.fac_disc_text = tk.StringVar(value=fac.get("disclosure_text", "AI 음성 안내 방송입니다."))
        self.fac_posted = tk.BooleanVar(value=bool(fac.get("notice_posted")))
        dc, df = self._card(f, "AI 음성 고지", "음성 모델 라이선스 부속서 A(e) / AI 기본법")
        dc.grid(row=0, column=1, rowspan=2, sticky="nsew", pady=(0, 0))
        self.disc_badge = tk.Label(dc.head, font=(FONT, 9, "bold"), padx=8, pady=2)
        self.disc_badge.pack(side="right", padx=(0, 8))
        self._update_disc_badge()
        ttk.Label(df, text="고지 방식", style="Field.TLabel").pack(anchor="w", pady=(0, 4))
        for val, label in (("notice", "게시물로 대체 — 방송에는 고지 멘트 없음"),
                           ("daily_first", "하루 첫 방송에만 음성 고지"),
                           ("every", "매 방송 음성 고지")):
            ttk.Radiobutton(df, text=label, value=val, variable=self.fac_mode).pack(anchor="w")
        ttk.Label(df, text="음성 고지 문구", style="Field.TLabel").pack(anchor="w", pady=(14, 4))
        ttk.Entry(df, textvariable=self.fac_disc_text).pack(fill="x")

        post = tk.Frame(df, bg=C["card"], highlightthickness=1, highlightbackground=C["border"])
        post.pack(fill="x", pady=(18, 0))
        pin = ttk.Frame(post, padding=14)
        pin.pack(fill="x")
        ttk.Label(pin, text="게시용 안내문", style="Field.TLabel").pack(anchor="w")
        ttk.Label(pin, text="① 안내문을 만들어 인쇄  →  ② 게시판·엘리베이터·출입구에 게시  →  ③ 아래에 체크 후 저장",
                  style="Hint.TLabel", wraplength=self._px(420)).pack(anchor="w", pady=(4, 10))
        ttk.Button(pin, text="게시용 안내문 만들기 (인쇄)", command=self._make_notice).pack(anchor="w")
        ttk.Checkbutton(pin, text="안내문을 게시판·엘리베이터·출입구 등에 게시했습니다",
                        variable=self.fac_posted).pack(anchor="w", pady=(10, 0))

        bf = ttk.Frame(f, style="Page.TFrame")
        bf.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Button(bf, text="저장", style="Big.Primary.TButton", command=self._save_facility).pack(side="right")
        ttk.Button(bf, text="라이선스 · 사용 제한 보기",
                   command=lambda: self._license_dialog(view_only=True)).pack(side="right", padx=10)

    def _update_disc_badge(self):
        if disclosure_ok(self.app.config["facility"]):
            self.disc_badge.configure(text="✓ 고지 완료", fg=C["ok"], bg=C["ok_l"])
        else:
            self.disc_badge.configure(text="! 미완료", fg=C["warn"], bg=C["warn_l"])

    def _save_facility(self):
        intro_on, intro = self.fac_intro_on.get(), self.fac_intro.get().strip()
        mode = self.fac_mode.get()
        if mode == "notice" and not self.fac_posted.get() and not messagebox.askyesno(
                "AI 음성 고지",
                "'게시물로 대체'를 선택했지만 안내문 게시 확인이 체크되지 않았습니다.\n\n"
                "음성 모델 라이선스(부속서 A(e))는 AI 생성 음성임을 알리도록 요구합니다. "
                "[게시용 안내문 만들기]로 인쇄해 게시한 뒤 체크해 주세요.\n\n일단 저장할까요?"):
            return
        for v in (self.fac_quiet_start.get(), self.fac_quiet_end.get()):
            if not re.fullmatch(r"\d{1,2}:\d{2}", v.strip()):
                messagebox.showerror("시설 설정", f"시각 형식이 올바르지 않습니다: {v} (예: 22:00)")
                return
        fac = self.app.config["facility"]
        fac.update(name=self.fac_name.get().strip(), intro_enabled=intro_on, intro=intro,
                   intro_on_emergency=self.fac_intro_emg.get(),
                   outro_enabled=self.fac_outro_on.get(), outro=self.fac_outro.get().strip(),
                   disclosure_mode=mode,
                   disclosure_text=self.fac_disc_text.get().strip() or "AI 음성 안내 방송입니다.")
        if not self.fac_posted.get():
            fac["notice_posted"] = ""
        elif not fac.get("notice_posted"):
            fac["notice_posted"] = time.strftime("%Y-%m-%d %H:%M:%S")
            log.info("AI 음성 안내문 게시 확인")
        fac["quiet_hours"] = {"enabled": self.fac_quiet_on.get(),
                              "start": self.fac_quiet_start.get().strip(),
                              "end": self.fac_quiet_end.get().strip()}
        self.app.save()
        self._update_disc_badge()
        self._update_banner()
        self._update_side_facility()
        self._toast("시설 설정을 저장했습니다")

    def _make_notice(self):
        path = resolve_path("docs/게시용_AI음성_안내문.html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(notice_html(self.fac_name.get().strip()), encoding="utf-8")
        try:
            os.startfile(str(path))  # 기본 브라우저로 열기 → Ctrl+P 인쇄
        except OSError:
            pass
        messagebox.showinfo("게시용 안내문", f"안내문을 만들었습니다.\n{path}\n\n인쇄해서 게시한 뒤 "
                                         "'게시했습니다'에 체크하고 저장하세요.")

    # ------------------------------------------------------------ 라이선스 동의
    def _license_dialog(self, view_only: bool = False):
        dlg, body, footer = self._dialog("AI 음성 모델 사용 제한 (Open RAIL-M)",
                                         "방송 프로그램을 사용하기 전에 아래 내용을 확인해 주세요.",
                                         C["side"])
        wrap = ttk.Frame(body)
        wrap.pack(fill="both", expand=True)
        txt = self._textbox(wrap, height=22, size=10, width=76)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=txt.yview, style="Slim.Vertical.TScrollbar")
        txt.configure(yscrollcommand=sb.set)
        txt.insert("1.0", license_notice())
        txt.configure(state="disabled")
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        if view_only:
            ttk.Button(footer, text="닫기", style="Primary.TButton", command=dlg.destroy).pack(side="right")
            dlg.bind("<Escape>", lambda e: dlg.destroy())
        else:
            def accept():
                self.app.config["license_accepted"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self.app.save()
                log.info("사용 제한 동의")
                dlg.destroy()

            ttk.Button(footer, text="위 내용을 확인했으며 동의합니다", style="Primary.TButton",
                       command=accept).pack(side="right", padx=(8, 0))
            ttk.Button(footer, text="동의하지 않음 (종료)", command=self.root.destroy).pack(side="right")
            dlg.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self._center(dlg)
        dlg.grab_set()

    # ------------------------------------------------------------ 예약 탭
    def _build_schedule_tab(self, f):
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        lc, lb = self._card(f, "예약 목록", "더블클릭: 사용/중지  ·  Delete: 삭제  ·  오른쪽 클릭: 메뉴")
        lc.grid(row=0, column=0, sticky="nsew", pady=(0, 16))
        for text, cmd, style in (("↻", self._refresh_sched, "Ghost.TButton"),
                                 ("삭제", self._delete_sched, "Outline.TButton"),
                                 ("지금 송출(테스트)", self._fire_sched, "TButton"),
                                 ("사용/중지 전환", self._toggle_sched, "TButton")):
            ttk.Button(lc.head, text=text, style=style, command=cmd).pack(side="right", padx=(6, 0))
        wrap, self.tree = self._tree(lb, ("on", "name", "when", "prio", "text"),
                                     ("상태", "이름", "일정", "우선", "문구"), (80, 140, 230, 60, 380))
        wrap.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._toggle_sched())
        self.tree.bind("<Delete>", lambda e: self._delete_sched())
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="사용/중지 전환", command=self._toggle_sched)
        menu.add_command(label="지금 송출(테스트)", command=self._fire_sched)
        menu.add_separator()
        menu.add_command(label="삭제", command=self._delete_sched)

        def popup(e):
            row = self.tree.identify_row(e.y)
            if row:
                if row not in self.tree.selection():
                    self.tree.selection_set(row)
                menu.tk_popup(e.x_root, e.y_root)

        self.tree.bind("<Button-3>", popup)
        self.sched_empty = tk.Label(lb, text="등록된 예약 방송이 없습니다.\n아래 [새 예약]에서 추가하세요.",
                                    bg=C["card"], fg=C["subtle"], font=(FONT, 10))

        fc, form = self._card(f, "새 예약")
        fc.grid(row=1, column=0, sticky="ew")
        self.s_name = tk.StringVar()
        self.s_type = tk.StringVar(value="지정 시각")
        self.s_time = tk.StringVar(value="09:00")
        self.s_date = tk.StringVar()
        self.s_interval = tk.StringVar(value="60")
        self.s_start = tk.StringVar(value="09:00")
        self.s_end = tk.StringVar(value="18:00")
        self.s_prio = tk.StringVar(value="보통")
        self.s_repeat = tk.StringVar(value="1")
        self.s_days = [tk.BooleanVar() for _ in DAY_NAMES]
        form.columnconfigure(1, weight=1)

        def label(r, text):
            ttk.Label(form, text=text, style="Field.TLabel").grid(row=r, column=0, sticky="w", pady=6,
                                                                   padx=(0, 16))

        label(0, "이름 · 유형")
        r0 = ttk.Frame(form)
        r0.grid(row=0, column=1, sticky="ew")
        ttk.Entry(r0, textvariable=self.s_name, width=18).pack(side="left", padx=(0, 16))
        for name in ("지정 시각", "일정 간격"):
            ttk.Radiobutton(r0, text=name, value=name, variable=self.s_type,
                            style="Seg.Toolbutton").pack(side="left")
        ttk.Label(r0, text="우선순위", style="Field.TLabel").pack(side="left", padx=(24, 8))
        for name in ("보통", "높음", "긴급"):
            ttk.Radiobutton(r0, text=name, value=name, variable=self.s_prio,
                            style="Seg.Toolbutton").pack(side="left")
        ttk.Label(r0, text="반복", style="Field.TLabel").pack(side="left", padx=(24, 8))
        ttk.Spinbox(r0, from_=1, to=10, width=3, textvariable=self.s_repeat, state="readonly").pack(side="left")
        ttk.Label(r0, text="회", style="Muted.TLabel").pack(side="left", padx=4)

        self.s_when_label = tk.StringVar()
        ttk.Label(form, textvariable=self.s_when_label, style="Field.TLabel").grid(
            row=1, column=0, sticky="w", pady=6, padx=(0, 16))
        host = ttk.Frame(form)
        host.grid(row=1, column=1, sticky="ew")
        self.s_time_row = ttk.Frame(host)
        ttk.Entry(self.s_time_row, textvariable=self.s_time, width=7, justify="center").pack(side="left")
        ttk.Label(self.s_time_row, text="날짜", style="Field.TLabel").pack(side="left", padx=(20, 8))
        ttk.Entry(self.s_time_row, textvariable=self.s_date, width=12, justify="center").pack(side="left")
        ttk.Label(self.s_time_row, text="YYYY-MM-DD · 비우면 요일마다 반복",
                  style="Hint.TLabel").pack(side="left", padx=10)
        self.s_interval_row = ttk.Frame(host)
        ttk.Entry(self.s_interval_row, textvariable=self.s_interval, width=5,
                  justify="center").pack(side="left")
        ttk.Label(self.s_interval_row, text="분마다", style="Muted.TLabel").pack(side="left", padx=(6, 20))
        ttk.Label(self.s_interval_row, text="운영 시간", style="Field.TLabel").pack(side="left", padx=(0, 8))
        ttk.Entry(self.s_interval_row, textvariable=self.s_start, width=7, justify="center").pack(side="left")
        ttk.Label(self.s_interval_row, text="  ~  ", style="Muted.TLabel").pack(side="left")
        ttk.Entry(self.s_interval_row, textvariable=self.s_end, width=7, justify="center").pack(side="left")
        self.s_type.trace_add("write", lambda *a: self._sched_type_changed())
        self._sched_type_changed()

        label(2, "요일")
        r2 = ttk.Frame(form)
        r2.grid(row=2, column=1, sticky="ew")
        for name, var in zip(DAY_NAMES, self.s_days):
            ttk.Checkbutton(r2, text=name, variable=var, style="Day.Toolbutton").pack(side="left", padx=(0, 4))
        for text, days in (("매일", ()), ("평일", range(5)), ("주말", (5, 6))):
            ttk.Button(r2, text=text, style="Ghost.TButton",
                       command=lambda d=days: [v.set(i in d) for i, v in enumerate(self.s_days)]).pack(
                side="left", padx=(8 if text == "매일" else 0, 0))
        ttk.Label(r2, text="선택하지 않으면 매일", style="Hint.TLabel").pack(side="left", padx=10)

        label(3, "문구")
        r3 = ttk.Frame(form)
        r3.grid(row=3, column=1, sticky="ew")
        ttk.Button(r3, text="＋  예약 추가", style="Primary.TButton", command=self._add_sched).pack(side="right")
        self.s_text = ttk.Entry(r3, font=(FONT, 11))
        self.s_text.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.s_text.bind("<Return>", lambda e: self._add_sched())
        self._refresh_sched()

    def _sched_type_changed(self):
        interval = self.s_type.get() == "일정 간격"
        self.s_when_label.set("간격" if interval else "시각")
        (self.s_time_row if interval else self.s_interval_row).pack_forget()
        (self.s_interval_row if interval else self.s_time_row).pack(fill="x")

    def _refresh_sched(self):
        self.tree.delete(*self.tree.get_children())
        items = self.app.scheduler.items()
        for n, it in enumerate(items):
            on = it.get("enabled", True)
            tags = ("odd",) if n % 2 else ()
            self.tree.insert("", "end", iid=it["id"], tags=tags + (() if on else ("off",)), values=(
                "●  사용" if on else "○  중지", it.get("name", ""), describe(it),
                PRIORITY_NAMES.get(parse_priority(it.get("priority")), ""), it.get("text", "")))
        if items:
            self.sched_empty.place_forget()
        else:
            self.sched_empty.place(relx=0.5, rely=0.55, anchor="center")

    def _selected(self):
        sel = list(self.tree.selection())
        if not sel:
            self._toast("목록에서 예약을 선택하세요", "warn")
        return sel

    def _toggle_sched(self):
        items = {i["id"]: i for i in self.app.scheduler.items()}
        for sid in self._selected():
            self.app.scheduler.update(sid, enabled=not items[sid].get("enabled", True))
        self._refresh_sched()

    def _delete_sched(self):
        sel = self._selected()
        if sel and messagebox.askyesno("삭제", f"{len(sel)}건을 삭제할까요?"):
            for sid in sel:
                self.app.scheduler.remove(sid)
            self._refresh_sched()
            self._toast(f"예약 {len(sel)}건을 삭제했습니다", "info")

    def _fire_sched(self):
        items = {i["id"]: i for i in self.app.scheduler.items()}
        for sid in self._selected():
            try:
                self.app.scheduler.fire(items[sid])
            except ValueError as e:
                messagebox.showwarning("예약 송출", str(e))

    def _add_sched(self):
        text = self.s_text.get().strip()
        if not text:
            self._toast("예약할 문구를 입력하세요", "warn")
            self.s_text.focus_set()
            return
        findings = compliance_check(text)
        if any(f.level == "block" for f in findings):
            messagebox.showerror("예약", "송출할 수 없는 내용이 있습니다:\n" +
                                 "\n".join(f"- {f.title}: {f.detail}" for f in findings))
            return
        if findings and not messagebox.askyesno(
                "예약 - 내용 점검",
                "위반 소지가 있는 내용이 있습니다. 예약 방송은 운영자 확인 없이 자동 송출됩니다.\n\n" +
                "\n".join(f"- {f.title}: {f.detail}" for f in findings) + "\n\n그래도 등록할까요?"):
            return
        item = {"name": self.s_name.get().strip(), "text": text,
                "days": [i for i, v in enumerate(self.s_days) if v.get()],
                "priority": parse_priority(self.s_prio.get()),
                "repeat": int(self.s_repeat.get() or 1), "chime": True}
        try:
            if self.s_type.get() == "일정 간격":
                item.update(type="interval", interval_min=int(self.s_interval.get()),
                            start=self.s_start.get().strip(), end=self.s_end.get().strip())
            else:
                item.update(type="time", time=self.s_time.get().strip(), date=self.s_date.get().strip())
            self.app.scheduler.add(item)
        except (ValueError, KeyError) as e:
            messagebox.showerror("예약", f"입력 형식 오류: {e}")
            return
        self.s_text.delete(0, "end")
        self.s_name.set("")
        self._refresh_sched()
        self._toast("예약 방송을 추가했습니다")

    # ------------------------------------------------------------ 엔진 탭
    def _build_engine_tab(self, f):
        f.columnconfigure(0, weight=3)
        f.columnconfigure(1, weight=2, minsize=self._px(360))
        f.rowconfigure(1, weight=1)

        ec, eb = self._card(f, "음성 엔진")
        ec.grid(row=0, column=0, sticky="nsew", padx=(0, 16), pady=(0, 16))
        eb.columnconfigure(1, weight=1)
        ttk.Label(eb, text="엔진 프로필", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 16))
        top = ttk.Frame(eb)
        top.grid(row=0, column=1, sticky="ew", pady=4)
        self.profile = ttk.Combobox(top, values=list(self.app.config["engines"]), state="readonly", width=26)
        self.profile.set(self.app.config["active_engine"])
        self.profile.pack(side="left")
        self.profile.bind("<<ComboboxSelected>>", lambda e: self._load_profile())
        self.type_var = tk.StringVar()
        tk.Label(top, textvariable=self.type_var, fg=C["primary"], bg=C["primary_l"],
                 font=(FONT, 9, "bold"), padx=8, pady=2).pack(side="left", padx=10)

        ttk.Label(eb, text="음성", style="Field.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 16))
        vf = ttk.Frame(eb)
        vf.grid(row=1, column=1, sticky="ew", pady=4)
        self.voice = ttk.Combobox(vf, width=40)
        self.voice.pack(side="left", fill="x", expand=True)
        self.voice.bind("<<ComboboxSelected>>", lambda e: self._set_option("voice", self.voice.get()))
        self.voice_btn = ttk.Button(vf, text="음성 목록 불러오기", command=self._load_voices)
        self.voice_btn.pack(side="left", padx=(8, 0))

        ttk.Label(eb, text="예비 엔진", style="Field.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 16))
        ff = ttk.Frame(eb)
        ff.grid(row=2, column=1, sticky="ew", pady=4)
        self.fallback_cb = ttk.Combobox(ff, values=["(사용 안 함)"] + list(self.app.config["engines"]),
                                        state="readonly", width=26)
        self.fallback_cb.set(self.app.config["broadcast"].get("fallback_engine") or "(사용 안 함)")
        self.fallback_cb.pack(side="left")
        ttk.Button(ff, text="예비 엔진 적용", command=self._apply_fallback).pack(side="left", padx=(8, 0))
        ttk.Label(ff, text="주 엔진 실패 시 자동 전환", style="Hint.TLabel").pack(side="left", padx=10)

        note = tk.Frame(eb, bg=C["warn_l"], highlightthickness=1, highlightbackground="#fcd34d")
        note.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        tk.Label(note, text="⚠  Windows 음성(windows_*)의 상업 방송 이용 조건은 Microsoft 확인 중입니다 "
                            "(docs\\Microsoft_음성_라이선스_문의서.md)",
                 bg=C["warn_l"], fg="#92400e", font=(FONT, 9), anchor="w", justify="left",
                 wraplength=self._px(600), padx=12, pady=8).pack(fill="x")

        oc, ob = self._card(f, "엔진 옵션 (고급)", "JSON 형식 · 엔진마다 항목이 다릅니다")
        oc.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        self.opts = self._textbox(ob, height=10, size=10, mono=True)
        self.opts.configure(wrap="none")
        self.opts.pack(fill="both", expand=True)
        bf = ttk.Frame(ob)
        bf.pack(fill="x", pady=(12, 0))
        ttk.Button(bf, text="적용 및 저장", style="Primary.TButton", command=self._apply_engine).pack(side="right")

        tc, tb = self._card(f, "테스트 방송")
        tc.grid(row=0, column=1, sticky="nsew", pady=(0, 16))
        self.test_text = ttk.Entry(tb)
        self.test_text.insert(0, "안내 말씀 드립니다. 방송 테스트 중입니다.")
        self.test_text.pack(fill="x")
        ttk.Button(tb, text="▶  테스트 방송", command=self._test_broadcast).pack(anchor="e", pady=(10, 0))

        right = ttk.Frame(f, style="Page.TFrame")
        right.grid(row=1, column=1, sticky="nsew")
        self._build_chime_frame(right)
        cfg = self.app.config
        ic, ib = self._card(right, "시스템 정보")
        ic.pack(fill="both", expand=True, pady=(16, 0))
        info = [("등록된 엔진", ", ".join(available_engines()))]
        if self.app.watcher:
            info.append(("감시 폴더", f"{self.app.watcher.folder}  (.txt 넣으면 자동 방송)"))
        if self.app.api:
            info.append(("HTTP API", f"http://{cfg['api']['host']}:{cfg['api']['port']}/"))
        info.append(("엔진 추가", "config.json 의 engines 에 프로필 추가, 또는 plugins 폴더에 .py 추가 (README 참고)"))
        for r, (k, v) in enumerate(info):
            ttk.Label(ib, text=k, style="Muted.TLabel").grid(row=r, column=0, sticky="nw", padx=(0, 12), pady=2)
            ttk.Label(ib, text=v, wraplength=self._px(250), justify="left").grid(row=r, column=1, sticky="w", pady=2)
        self._load_profile()

    def _test_broadcast(self):
        self.b.submit(Announcement(text=self.test_text.get(), chime=False, source="테스트"))
        self._toast("테스트 방송을 대기열에 넣었습니다", "info")

    def _build_chime_frame(self, parent):
        cf, cb = self._card(parent, "차임벨", "assets\\chimes 폴더의 WAV")
        cf.pack(fill="x")
        s = self.app.config["broadcast"]
        self.chime_dir = resolve_path("assets/chimes")
        files = sorted(p.name for p in self.chime_dir.glob("*.wav"))
        none = "(사용 안 함)"
        self.chime_start_cb = ttk.Combobox(cb, values=[none] + files, state="readonly", width=22)
        self.chime_end_cb = ttk.Combobox(cb, values=[none] + files, state="readonly", width=22)
        self.chime_start_cb.set(Path(s.get("chime_start_file", "")).name if s.get("chime_start", True) else none)
        self.chime_end_cb.set(Path(s.get("chime_end_file", "")).name if s.get("chime_end", False) else none)
        cb.columnconfigure(1, weight=1)
        for r, (label, combo) in enumerate((("시작", self.chime_start_cb), ("종료", self.chime_end_cb))):
            ttk.Label(cb, text=label, style="Field.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 12))
            combo.grid(row=r, column=1, sticky="ew", pady=4)
            ttk.Button(cb, text="▶ 미리듣기", style="Ghost.TButton",
                       command=lambda c=combo: self._preview_chime(c.get())).grid(row=r, column=2, padx=(6, 0))
        ttk.Button(cb, text="차임 적용", style="Primary.TButton", command=self._apply_chimes).grid(
            row=2, column=0, columnspan=3, sticky="e", pady=(10, 0))

    def _preview_chime(self, name):
        path = self.chime_dir / name
        if path.exists():
            threading.Thread(target=play_wav, args=(path, threading.Event()), daemon=True).start()

    def _apply_chimes(self):
        s = self.app.config["broadcast"]
        start, end = self.chime_start_cb.get(), self.chime_end_cb.get()
        s["chime_start"] = (self.chime_dir / start).exists()
        s["chime_end"] = (self.chime_dir / end).exists()
        if s["chime_start"]:
            s["chime_start_file"] = f"assets/chimes/{start}"
        if s["chime_end"]:
            s["chime_end_file"] = f"assets/chimes/{end}"
        self.b.reload_chimes()
        self.chime.set(s["chime_start"])
        self.app.save()
        self._toast("차임벨 설정을 저장했습니다")

    def _apply_fallback(self):
        value = self.fallback_cb.get()
        key = "" if value == "(사용 안 함)" else value
        if not key and not messagebox.askyesno(
                "예비 엔진", "예비 엔진을 끄면 주 엔진이 실패할 때 방송이 오류로 중단됩니다.\n계속할까요?"):
            return
        self.app.set_fallback(key)
        self._toast(f"예비 엔진: {value}")

    def _load_profile(self):
        prof = self.app.config["engines"][self.profile.get()]
        self.type_var.set(prof["type"])
        self.opts.delete("1.0", "end")
        self.opts.insert("1.0", json.dumps(prof.get("options", {}), ensure_ascii=False, indent=2))
        self.voice.set(prof.get("options", {}).get("voice", ""))

    def _read_opts(self) -> dict:
        return json.loads(self.opts.get("1.0", "end").strip() or "{}")

    def _set_option(self, key, value):
        try:
            opts = self._read_opts()
        except ValueError:
            opts = {}
        opts[key] = value
        self.opts.delete("1.0", "end")
        self.opts.insert("1.0", json.dumps(opts, ensure_ascii=False, indent=2))

    def _load_voices(self):
        key = self.profile.get()
        self.voice_btn.configure(text="불러오는 중…", state="disabled")

        def finish(fn):
            self.voice_btn.configure(text="음성 목록 불러오기", state="normal")
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
                self.root.after(0, lambda: finish(lambda: self._set_voices(voices)))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: finish(lambda: messagebox.showerror("음성 목록", msg)))

        threading.Thread(target=work, daemon=True).start()

    def _set_voices(self, voices):
        self.voice["values"] = voices
        if voices:
            self._toast(f"음성 {len(voices)}개를 불러왔습니다", "info")
        else:
            messagebox.showinfo("음성 목록", "이 엔진은 음성 목록을 제공하지 않습니다.")

    def _apply_engine(self):
        try:
            opts = self._read_opts()
        except ValueError as e:
            messagebox.showerror("옵션 오류", f"JSON 형식이 올바르지 않습니다:\n{e}")
            return
        try:
            self.app.switch_engine(self.profile.get(), opts)
            self._toast(f"'{self.profile.get()}' 엔진을 적용했습니다")
        except Exception as e:
            messagebox.showerror("엔진 오류", f"엔진을 적용할 수 없습니다 (기존 엔진 유지):\n{e}")

    # ------------------------------------------------------------ 공통
    def _poll(self):
        today = time.strftime("%Y%m%d")
        if self._stats["day"] != today:
            self._stats.update(done=0, err=0, day=today)
        while True:
            try:
                kind, ann, msg = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "done":
                self._stats["done"] += 1
            elif kind in ("error", "rejected"):
                self._stats["err"] += 1
            values = (time.strftime("%H:%M:%S"), EVENT_LABELS.get(kind, kind),
                      PRIORITY_NAMES.get(ann.priority, ann.priority) if ann else "",
                      ann.source if ann else "",
                      (f"{ann.text.replace(chr(10), ' ')[:90]} {msg}" if ann else msg).strip())
            tag = EVENT_TAGS.get(kind)
            self.log_list.insert("", 0, values=values, tags=(tag,) if tag else ())
            children = self.log_list.get_children()
            if len(children) > 500:
                self.log_list.delete(*children[500:])

        cur = self.b.current
        if cur is not self._cur_ann:
            self._cur_ann = cur
            self._cur_started = time.time()
        self._blink = not self._blink
        if cur:
            emg = cur.priority == PRIORITY_EMERGENCY
            self.cur_var.set(cur.text[:160])
            self.cur_state.configure(text=("●  긴급 송출 중" if emg else "●  송출 중"),
                                     fg=C["danger"] if (self._blink or not emg) else "#fca5a5")
            el = int(time.time() - self._cur_started)
            self.cur_meta.configure(text=f"{PRIORITY_NAMES.get(cur.priority, cur.priority)}  ·  {cur.source}"
                                         f"  ·  경과 {el // 60:02d}:{el % 60:02d}")
            self.cur_box.configure(highlightbackground="#fca5a5")
            self.onair.configure(text="●  ON AIR", bg=C["danger"],
                                 fg="white" if self._blink else "#fecaca")
            self.stop_btn.state(["!disabled"])
        else:
            self.cur_var.set("현재 송출 중인 방송이 없습니다")
            self.cur_state.configure(text="○  대기 중", fg=C["muted"])
            self.cur_meta.configure(text="")
            self.cur_box.configure(highlightbackground=C["border"])
            self.onair.configure(text="○  대기 중", bg=C["border"], fg=C["muted"])
            self.stop_btn.state(["disabled"])

        pend = self.b.pending()
        sig = tuple(id(a) for a in pend)
        if sig != self._pending_sig:
            self._pending_sig = sig
            self.pending_list.delete(*self.pending_list.get_children())
            for a in pend:
                self.pending_list.insert("", "end", values=(
                    PRIORITY_NAMES.get(a.priority, a.priority), a.source, a.text.replace("\n", " ")[:80]),
                    tags=("bad",) if a.priority == PRIORITY_EMERGENCY else ())
            if pend:
                self.pending_empty.place_forget()
            else:
                self.pending_empty.place(relx=0.5, rely=0.55, anchor="center")
        self.queue_count.configure(text=f"{len(pend)}건")
        self.stat_vars["queue"].set(str(len(pend)))
        self.stat_vars["done"].set(str(self._stats["done"]))
        self.stat_vars["err"].set(str(self._stats["err"]))

        lt = time.localtime()
        self.clock.configure(text=time.strftime(f"%Y-%m-%d ({DAY_NAMES[lt.tm_wday]})  %H:%M:%S", lt))
        normal = self.b.engine_key == self.app.config["active_engine"]
        self.sb_engine.configure(text=f"●  엔진 {self.b.engine_key}" + ("" if normal else "  (예비 엔진)"),
                                 fg=C["ok"] if normal else C["warn"])
        self.sb_queue.configure(text=f"대기 {len(pend)}건")
        active = sum(1 for i in self.app.scheduler.items() if i.get("enabled", True))
        self.sb_sched.configure(text=f"예약 {active}건 사용 중")
        self.root.after(300, self._poll)

    def _on_close(self):
        if messagebox.askokcancel("종료", "방송 프로그램을 종료하면 예약/자동 방송도 중지됩니다.\n종료할까요?"):
            self.root.destroy()

    def run(self):
        self.root.mainloop()
