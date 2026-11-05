"""설정 백업(내보내기) · 복원(불러오기) · 초기화.

백업 파일(.zip) 구성:
  manifest.json   프로그램 버전, 만든 시각
  config.json     모든 설정 (엔진·음성 조절·차임·시설·발음 사전·자주 쓰는 문구 …)
  schedules.json  예약 방송
  templates.json  안내문 양식
  files/…         설정이 가리키는 프로그램 폴더 안의 사용자 파일 (직접 넣은 차임 WAV, 목소리 json 등)

복원·초기화 전에는 항상 현재 상태를 backups 폴더에 자동 백업하므로 되돌릴 수 있습니다.
"""
from __future__ import annotations

import copy
import json
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import __version__
from .audio import BUILTIN_CHIMES as CHIME_PRESETS
from .config import DEFAULTS, ROOT, load_config, resolve_path, save_config

BACKUP_DIR = ROOT / "backups"
FACTORY_DIR = ROOT / "assets" / "defaults"
KEEP_AUTO = 20
_FILE_TYPES = {".wav", ".json"}

# 초기화 범위: (이름, 설명, config 키들, 별도 파일)
RESET_SCOPES = {
    "voice": ("음성 · 방송 설정", "엔진, 음성 조절(빠르기·음높이·음량), 차임벨, 예비 엔진, 감시 폴더, API",
              ["active_engine", "engines", "broadcast", "watch_folder", "api"], None),
    "facility": ("시설 설정", "시설 이름, 머리말·맺음말, AI 음성 고지, 야간 방송 제한", ["facility"], None),
    "phrases": ("발음 사전 · 자주 쓰는 문구", "등록한 발음, 방송 화면의 자주 쓰는 문구",
                ["pronunciations", "presets"], None),
    "schedules": ("예약 방송", "등록한 예약을 처음 제공된 예시로 되돌림", [], "schedules_file"),
    "templates": ("안내문 양식", "안내문 양식을 처음 제공된 내용으로 되돌림", [], "templates_file"),
}


def _user_files(cfg: dict) -> list[str]:
    """설정이 가리키는 프로그램 폴더 안의 사용자 파일 (상대 경로, 기본 차임 제외)."""
    refs = [cfg["broadcast"].get("chime_start_file", ""), cfg["broadcast"].get("chime_end_file", "")]
    refs += [str(p.get("options", {}).get("voice", "")) for p in cfg.get("engines", {}).values()]
    chimes = ROOT / "assets" / "chimes"
    if chimes.is_dir():
        refs += [f"assets/chimes/{p.name}" for p in chimes.glob("*.wav") if p.stem not in CHIME_PRESETS]
    out = []
    for r in refs:
        if not r or Path(r).suffix.lower() not in _FILE_TYPES or Path(r).is_absolute():
            continue
        rel = PurePosixPath(Path(r).as_posix())
        if ".." in rel.parts or Path(rel.name).stem in CHIME_PRESETS:
            continue
        if (ROOT / rel).is_file() and str(rel) not in out:
            out.append(str(rel))
    return out


def export_settings(dest: Path, config_path: Path, note: str = "") -> Path:
    cfg = load_config(config_path)
    files = _user_files(cfg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({
            "app": "TTS 방송", "version": __version__, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": note, "files": files}, ensure_ascii=False, indent=2))
        z.writestr("config.json", json.dumps(cfg, ensure_ascii=False, indent=2))
        for name, key in (("schedules.json", "schedules_file"), ("templates.json", "templates_file")):
            p = resolve_path(cfg[key])
            if p.is_file():
                z.write(p, name)
        for rel in files:
            z.write(ROOT / rel, f"files/{rel}")
    tmp.replace(dest)
    return dest


def auto_backup(config_path: Path, reason: str) -> Path:
    """복원·초기화 직전 자동 백업 (최근 KEEP_AUTO 개만 보관)."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = BACKUP_DIR / f"자동백업_{stamp}_{reason}.zip"
    n = 2
    while path.exists():  # 같은 초에 여러 번 백업해도 덮어쓰지 않음
        path = BACKUP_DIR / f"자동백업_{stamp}_{reason}_{n}.zip"
        n += 1
    export_settings(path, config_path, note=f"자동 백업 ({reason} 전)")
    autos = sorted(BACKUP_DIR.glob("자동백업_*.zip"))
    for old in autos[:-KEEP_AUTO]:
        old.unlink(missing_ok=True)
    return path


def read_manifest(src: Path) -> dict:
    """백업 파일 확인 (올바르지 않으면 ValueError)."""
    try:
        with zipfile.ZipFile(src) as z:
            if "config.json" not in z.namelist() or "manifest.json" not in z.namelist():
                raise ValueError("TTS 방송 설정 백업 파일이 아닙니다")
            json.loads(z.read("config.json").decode("utf-8-sig"))
            return json.loads(z.read("manifest.json").decode("utf-8-sig"))
    except zipfile.BadZipFile as e:
        raise ValueError("손상되었거나 zip 형식이 아닌 파일입니다") from e


def import_settings(src: Path, config_path: Path) -> Path:
    """백업 파일로 복원. 반환값은 복원 전 자동 백업 경로."""
    read_manifest(src)
    before = auto_backup(config_path, "불러오기")
    with zipfile.ZipFile(src) as z:
        cfg = json.loads(z.read("config.json").decode("utf-8-sig"))
        cfg["license_accepted"] = load_config(config_path).get("license_accepted", "")
        names = z.namelist()
        for name in names:
            if not name.startswith("files/") or name.endswith("/"):
                continue
            rel = PurePosixPath(name[len("files/"):])
            # 프로그램 폴더 밖이나 허용하지 않은 형식은 풀지 않음
            if rel.is_absolute() or ".." in rel.parts or rel.suffix.lower() not in _FILE_TYPES:
                continue
            target = ROOT / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
        merged = load_config(config_path) | cfg
        for name, key in (("schedules.json", "schedules_file"), ("templates.json", "templates_file")):
            if name in names:
                _write_atomic(resolve_path(merged[key]), z.read(name))
    save_config(config_path, cfg)
    return before


def reset_settings(config_path: Path, scopes: list[str]) -> Path:
    """선택한 범위를 처음 설치 상태로 되돌림. 반환값은 초기화 전 자동 백업 경로."""
    before = auto_backup(config_path, "초기화")
    cfg = load_config(config_path)
    for scope in scopes:
        _, _, keys, file_key = RESET_SCOPES[scope]
        for k in keys:
            cfg[k] = copy.deepcopy(DEFAULTS[k])
        if file_key:
            factory = FACTORY_DIR / Path(DEFAULTS[file_key]).name
            target = resolve_path(cfg[file_key])
            if factory.is_file():
                shutil.copyfile(factory, target)
            elif file_key == "schedules_file":
                _write_atomic(target, b"[]")
    save_config(config_path, cfg)
    return before


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
