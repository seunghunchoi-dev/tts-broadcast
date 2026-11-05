"""빌드 환경의 Python 패키지 라이선스 원문을 배포 폴더로 모은다.

사용: python tools/collect_licenses.py <배포 폴더의 licenses/third_party 경로>
라이선스 파일을 찾지 못한 패키지가 있으면 오류로 멈춰 고지 누락을 막는다.
"""
from __future__ import annotations

import importlib.metadata as metadata
import re
import shutil
import sys
from pathlib import Path

ROOTS = ["supertonic", "PySide6-Essentials", "Pillow", "certifi",
         "charset-normalizer", "Brotli", "pywin32"]
# 패키지에 라이선스 파일이 없어 licenses/Apache-2.0.txt 로 고지하는 패키지
NO_LICENSE_FILE = {"flatbuffers"}
PATTERN = re.compile(r"(licen[cs]e|copying|notice)", re.I)


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def walk(name: str, seen: dict) -> None:
    key = norm(name)
    if key in seen:
        return
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return  # 이 Python 버전에서는 필요 없는 선택 의존성
    seen[key] = dist
    for req in dist.requires or []:
        if "extra ==" not in req:
            walk(re.match(r"[A-Za-z0-9_.-]+", req).group(0), seen)


def main() -> int:
    dest = Path(sys.argv[1])
    seen: dict = {}
    for root in ROOTS:
        walk(root, seen)
    missing = []
    for key, dist in sorted(seen.items()):
        files = [f for f in dist.files or [] if PATTERN.search(Path(str(f)).name)]
        if not files:
            if key not in NO_LICENSE_FILE:
                missing.append(key)
            continue
        target = dest / f"{key}-{dist.version}"
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            name = re.sub(r"^.*?\.dist-info[/\\](licenses[/\\])?", "", str(f))
            shutil.copy2(f.locate(), target / re.sub(r"[/\\]", "_", name))

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    nuitka = metadata.distribution("Nuitka")
    runtime = [f for f in nuitka.files if Path(str(f)).name == "LICENSE-RUNTIME.txt"]
    if not python_license.exists() or not runtime:
        missing.append("python 또는 nuitka 런타임")
    else:
        (dest / "python").mkdir(parents=True, exist_ok=True)
        shutil.copy2(python_license, dest / "python" / "LICENSE.txt")
        (dest / "nuitka-runtime").mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime[0].locate(), dest / "nuitka-runtime" / "LICENSE-RUNTIME.txt")

    if missing:
        print("라이선스 파일을 찾지 못함:", ", ".join(missing), file=sys.stderr)
        return 1
    print(f"라이선스 수집 완료: {len(seen)}개 패키지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
