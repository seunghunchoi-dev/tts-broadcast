"""방송 문구 사전 점검 — AI 음성 모델 라이선스(Open RAIL-M 부속서 A) 및 개인정보보호법 위반 소지 경고.

키워드·패턴 기반 보조 장치입니다. 모든 위반을 잡아내지는 못하므로 최종 판단과 책임은 운영자에게 있습니다.
라이선스·법률 위반에 해당할 수 있는 경우만 보고하고, 단순 권장 사항(차량번호 전체 송출 등)은 제한하지 않습니다.
수준:
  block   : 송출 차단 (주민등록번호 — 방송할 정당한 용도가 없는 법률 위반)
  warn    : 위반 가능성 고지 후 운영자가 선택
  confirm : 시설 정책 확인 (야간 방송 제한을 켠 경우)
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime



@dataclass
class Finding:
    level: str
    title: str
    detail: str
    clause: str
    fix: str = ""   # 자동 수정 가능 시 수정 종류 ("mask_plates")


_RULES: list[tuple[str, re.Pattern, str, str, str]] = [
    ("block", re.compile(r"(?<!\d)\d{6}\s*-\s*[1-4]\d{6}(?!\d)"),
     "주민등록번호 송출 금지",
     "주민등록번호는 어떤 경우에도 방송할 수 없습니다.",
     "개인정보보호법 / 라이선스 부속서 A (a)(d)"),
    ("warn", re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)"),
     "개인 휴대전화번호 송출",
     "본인 동의 없이 개인 연락처를 공개하면 개인정보보호법 위반입니다. 본인 동의가 있으면 송출해도 됩니다.",
     "개인정보보호법 / 부속서 A (d)"),
    ("warn", re.compile(r"(?:\d+\s*동\s*)?\d{3,4}\s*호[^.!?]{0,30}(미납|체납|연체|민원|위반|불법|소음|무단|신고|경고|벌금|과태료)"
                        r"|(미납|체납|연체|민원|위반|불법|소음|무단|과태료)[^.!?]{0,30}\d{3,4}\s*호"),
     "특정 세대를 지목한 부정적 내용",
     "동·호수를 밝혀 미납·민원·위반 등을 방송하면 명예훼손·개인정보 침해 소지가 있습니다. "
     "세대를 특정하지 않는 일반 안내로 바꾸세요.",
     "부속서 A (d)(f) / 형법 명예훼손"),
    ("warn", re.compile(r"(경찰서|경찰청|파출소|지구대|소방서|소방본부|구청|시청|군청|주민센터|행정복지센터|"
                        r"검찰|법원|국세청|세무서|우체국|은행|한국전력|가스공사)\s*(입니다|에서\s*(알려|안내|말씀|전해))"),
     "기관 명의 방송",
     "다른 기관 명의로 방송하는 경우 해당 기관의 요청·동의가 있는지 확인하세요. 사칭은 금지됩니다.",
     "부속서 A (g) 사칭 금지"),
    ("warn", re.compile(r"복용|처방|진단|투약|약을\s*드시|치료\s*(하|받으)|해열제|진통제"),
     "의료 조언",
     "약 복용·진단·치료에 관한 조언은 방송할 수 없습니다. '의료기관에 문의하라'는 안내만 하세요.",
     "부속서 A (l) 의료 조언 금지"),
    ("warn", re.compile(r"(외국인|장애인|노인|어르신|임대\s*(세대|주민|동|아파트)|임차인|세입자|다문화|"
                        r"중국인|조선족|흑인|성소수자)[^.!?]{0,20}(금지|사절|불가|제한|들어오지|출입하지|이용하지)"),
     "차별 소지",
     "특정 집단의 이용·출입을 제한하는 방송은 차별에 해당할 수 있습니다.",
     "부속서 A (i)(k) 차별 금지"),
    ("warn", re.compile(r"미친|병신|개념\s*없|몰상식|바보|멍청|쓰레기\s*같|진상|무개념|한심"),
     "비방·모욕 표현",
     "비방·모욕 표현은 방송할 수 없습니다.",
     "부속서 A (f) 비방·괴롭힘 금지"),
    ("warn", re.compile(r"(아이|어린이|아동|학생|미성년)[^.!?]{0,15}(이름|학교|주소|사는\s*곳|연락처)"),
     "아동 개인정보",
     "만 14세 미만 아동의 개인정보는 보호자 동의가 필요합니다. 미아 찾기처럼 보호자가 요청한 경우는 송출해도 됩니다.",
     "부속서 A (b)(d)"),
    ("warn", re.compile(r"불법\s*체류|출입국|전과|범죄\s*경력|용의자|범죄자"),
     "사법·출입국 관련 정보",
     "범죄·출입국 판단에 쓰일 수 있는 정보는 방송할 수 없습니다. 수사기관 요청이면 해당 기관 절차를 따르세요.",
     "부속서 A (m)"),
]


def check(text: str) -> list[Finding]:
    """라이선스·법률 위반에 해당할 수 있는 경우만 보고 (단순 권장 사항은 제한하지 않음)."""
    return [Finding(level, title, detail, clause)
            for level, pattern, title, detail, clause in _RULES if pattern.search(text)]


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_quiet_hours(facility: dict, now: datetime | None = None) -> bool:
    q = facility.get("quiet_hours") or {}
    if not q.get("enabled"):
        return False
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    start, end = _minutes(q.get("start", "22:00")), _minutes(q.get("end", "07:00"))
    return start <= cur < end if start < end else (cur >= start or cur < end)


def quiet_finding(facility: dict) -> Finding:
    q = facility.get("quiet_hours") or {}
    return Finding("confirm", "야간 방송 제한 시간",
                   f"지금은 야간 방송 제한 시간({q.get('start')}~{q.get('end')})입니다. "
                   "긴급하지 않은 방송은 입주민 수면을 방해할 수 있습니다.",
                   "시설 운영 규정")


def disclosure_ok(facility: dict) -> bool:
    """AI 음성 고지가 갖춰져 있는지 (음성 고지 사용 또는 게시물 게시 확인)."""
    mode = facility.get("disclosure_mode", "notice")
    return mode in ("every", "daily_first") or bool(facility.get("notice_posted"))


def notice_html(facility_name: str) -> str:
    """게시용 AI 음성 안내문 (A4 인쇄용, 외부 리소스 없음)."""
    name = html.escape(facility_name or "본 시설")
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>AI 음성 안내방송 운영 안내</title>
<style>
@page {{ size: A4; margin: 18mm; }}
body {{ font-family: 'Malgun Gothic', sans-serif; color: #111; margin: 0; }}
.sheet {{ border: 3px solid #1f3a5f; border-radius: 14px; padding: 22mm 16mm; text-align: center;
          min-height: 230mm; box-sizing: border-box; display: flex; flex-direction: column; justify-content: center; }}
.badge {{ display: inline-block; background: #1f3a5f; color: #fff; font-size: 20pt; font-weight: 700;
          padding: 6px 28px; border-radius: 40px; letter-spacing: 4px; margin: 0 auto 14mm; }}
h1 {{ font-size: 34pt; margin: 0 0 14mm; color: #1f3a5f; word-break: keep-all; }}
p {{ font-size: 19pt; line-height: 1.7; margin: 0 0 8mm; word-break: keep-all; }}
.em {{ font-weight: 700; color: #1f3a5f; }}
.from {{ margin-top: 16mm; font-size: 22pt; font-weight: 700; }}
.note {{ margin-top: 10mm; font-size: 11pt; color: #666; }}
.hint {{ font-size: 11pt; color: #888; text-align: center; margin: 6px 0; }}
@media print {{ .hint {{ display: none; }} }}
</style></head><body>
<div class="hint">인쇄(Ctrl+P)하여 게시판·엘리베이터·출입구 등 잘 보이는 곳에 게시하세요.</div>
<div class="sheet">
  <div class="badge">안 내</div>
  <h1>AI 음성 안내방송 운영 안내</h1>
  <p>{name}의 안내방송은<br><span class="em">인공지능(AI) 음성 합성 기술로 생성된 음성</span>으로 송출됩니다.</p>
  <p>방송 내용은 {name}에서 직접 작성하고 확인하여 송출합니다.</p>
  <p>방송 내용에 대한 문의는 {name}로 연락해 주시기 바랍니다.</p>
  <div class="from">{name}</div>
  <div class="note">본 안내는 AI 생성 음성임을 알리기 위한 고지입니다.</div>
</div>
</body></html>
"""


def license_notice() -> str:
    return (
        "이 프로그램의 음성 엔진(Supertonic 3)은 Open RAIL-M 라이선스로 제공되며, "
        "다음 용도로 사용할 수 없습니다.\n\n"
        " (a) 법령 위반\n (b) 미성년자 착취·위해\n (c) 해를 끼칠 목적의 허위 정보 유포\n"
        " (d) 해를 끼칠 수 있는 개인식별정보 생성·유포\n"
        " (e) 기계 생성임을 밝히지 않은 콘텐츠 게시 → [시설 설정]의 AI 음성 고지(안내문 게시 또는 음성 고지)를 유지하세요\n"
        " (f) 명예훼손·비방·괴롭힘\n (g) 동의 없는 타인 사칭\n"
        " (h) 법적 권리에 불리한 완전 자동화 의사결정\n (i)(k) 차별\n"
        " (j) 취약 계층의 취약성을 이용한 위해\n (l) 의료 조언·결과 해석\n"
        " (m) 사법·법 집행·출입국·난민 심사용 정보 생성\n\n"
        "방송 전 문구를 자동 점검해 위반 소지가 있으면 경고하지만, 모든 위반을 찾아내지는 못합니다. "
        "방송 내용에 대한 책임은 운영자에게 있습니다.\n"
        "전문: models\\supertonic3\\LICENSE, docs\\ 폴더 참고"
    )
