"""방송 문구 정규화: 숫자·기호·영문을 한국어 읽기로 변환 (모든 엔진 공통).

예) "오후 2시 30분 B1층"      → "오후 두 시 삼십 분 지하 일 층"
    "2026.10.31 14:00"        → "이천이십육 년 시월 삼십일 일 오후 두 시"
    "09:00~18:00 단수"        → "오전 아홉 시부터 오후 여섯 시까지 단수"
    "11/3(월) 소독"           → "십일 월 삼 일 월요일 소독"
    "1,500원 / 3~4명 / 25.5%" → "천오백 원, 세 명에서 네 명, 이십오 점 오 퍼센트"
    "010-1234-5678, 119"      → "공일공에 일이삼사에 오육칠팔, 일일구"
    "12가 3456, 3456 차량"     → "일이가 삼사오육, 삼사오육 차량"
    "Wi-Fi, A/S, 30km/h"      → "와이파이, 에이에스, 시속 삼십 킬로미터"
발음 사전(set_lexicon)에 등록한 표기는 가장 먼저 바꾼다.
"""
from __future__ import annotations

import re

_SINO_DIGITS = "영일이삼사오육칠팔구"
_PHONE_DIGITS = "공일이삼사오육칠팔구"

# 고유어 수사 (관형형: 한/두/세/네/스무)
_NATIVE_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]

# 고유어로 읽는 단위 (1~99)
NATIVE_COUNTERS = [
    "시간", "시", "개", "명", "살", "마리", "번째", "대", "권", "잔", "병", "장", "곳",
    "군데", "가지", "사람", "그릇", "켤레", "벌", "척", "채", "통", "줄", "송이", "달",
]
# 한자어로 읽는 단위 (고유어 단위와 앞부분이 겹치는 것 포함 → 긴 것 우선 매칭)
SINO_COUNTERS = [
    "개월", "개국", "개소", "채널", "시즌", "병동", "번지", "번", "분", "초", "층", "년",
    "월", "일", "원", "호", "동", "도", "회", "차", "주년", "주", "인", "명분", "페이지",
    "쪽", "퍼센트", "프로", "배", "점", "위", "등", "세", "킬로미터", "킬로그램", "미터",
    "센티미터", "밀리미터", "리터", "밀리리터", "톤", "그램", "킬로와트", "와트", "볼트",
    "게이트", "단계", "구역", "라인", "출구", "호선", "호실", "학년", "반",
    "건", "가구", "세대", "평", "제곱미터",
]
_TIME_COUNTERS = {"년", "월", "일", "시", "분", "초"}
_COUNTERS = sorted(set(NATIVE_COUNTERS) | set(SINO_COUNTERS), key=len, reverse=True)
_COUNTER_RE = "|".join(map(re.escape, _COUNTERS))
_COUNTER_NO_BEON = "|".join(re.escape(c) for c in _COUNTERS if c != "번")
_NATIVE_SET = set(NATIVE_COUNTERS)

_UNITS = {"km": "킬로미터", "kg": "킬로그램", "cm": "센티미터", "mm": "밀리미터", "m": "미터",
          "ml": "밀리리터", "mL": "밀리리터", "L": "리터", "l": "리터", "t": "톤", "g": "그램",
          "kW": "킬로와트", "kw": "킬로와트", "W": "와트", "V": "볼트", "%": "퍼센트",
          "℃": "도", "°C": "도", "°": "도", "㎡": "제곱미터", "m²": "제곱미터", "㎞": "킬로미터",
          "㎏": "킬로그램", "㎝": "센티미터", "㎜": "밀리미터", "㎖": "밀리리터", "ℓ": "리터"}

# 영문 단어 → 우리말 표기 (대소문자 무시). 글자 이름으로 읽으면 어색한 것 위주.
_WORDS = {"wi-fi": "와이파이", "wifi": "와이파이", "e-mail": "이메일", "email": "이메일", "app": "앱",
          "ok": "오케이", "okay": "오케이", "online": "온라인", "offline": "오프라인", "internet": "인터넷",
          "web": "웹", "homepage": "홈페이지", "kakaotalk": "카카오톡", "kakao": "카카오", "naver": "네이버",
          "google": "구글", "youtube": "유튜브", "zoom": "줌", "band": "밴드", "cafe": "카페", "mart": "마트",
          "golf": "골프", "fitness": "피트니스", "lounge": "라운지", "center": "센터", "tel": "전화",
          "fax": "팩스", "vs": "대", "etc": "등", "iot": "아이오티", "covid-19": "코로나 일구",
          "covid": "코로나", "samsung": "삼성", "hyundai": "현대", "lotte": "롯데", "coupang": "쿠팡",
          "apt": "아파트", "iphone": "아이폰", "galaxy": "갤럭시", "ktx": "케이티엑스", "srt": "에스알티"}
_WORDS_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(map(re.escape, sorted(_WORDS, key=len, reverse=True)))
                       + r")(?![A-Za-z])", re.I)

_DAY = "월화수목금토일"
_TIME_PREFIX = r"(?:오전|오후|낮|밤|새벽|아침|저녁)"

# 운영자가 등록한 발음 사전 {표기: 읽기}
_lexicon: dict[str, str] = {}
_lexicon_re: re.Pattern | None = None


def set_lexicon(entries: dict[str, str] | None) -> None:
    """발음 사전 적용. 영문 표기는 대소문자를 가리지 않고 단어 단위로 바꾼다."""
    global _lexicon, _lexicon_re
    _lexicon = {k.strip(): v.strip() for k, v in (entries or {}).items() if k.strip() and v.strip()}
    if not _lexicon:
        _lexicon_re = None
        return
    parts = []
    for k in sorted(_lexicon, key=len, reverse=True):
        p = re.escape(k)
        if re.fullmatch(r"[A-Za-z0-9 .\-&/]+", k):
            p = rf"(?<![A-Za-z]){p}(?![A-Za-z])"
        parts.append(p)
    _lexicon_re = re.compile("|".join(parts), re.I)


def _apply_lexicon(t: str) -> str:
    if not _lexicon_re:
        return t
    low = {k.lower(): v for k, v in _lexicon.items()}
    return _lexicon_re.sub(lambda m: _lexicon.get(m.group(0)) or low.get(m.group(0).lower(), m.group(0)), t)


def english_leftovers(text: str) -> list[str]:
    """변환 후에도 남는 영문 단어 (엔진이 어색하게 읽을 수 있음 → 발음 사전 등록 권장)."""
    return list(dict.fromkeys(re.findall(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]|[A-Za-z]", normalize(text))))

_LETTERS = {"A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프", "G": "지",
            "H": "에이치", "I": "아이", "J": "제이", "K": "케이", "L": "엘", "M": "엠",
            "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알", "S": "에스", "T": "티",
            "U": "유", "V": "브이", "W": "더블유", "X": "엑스", "Y": "와이", "Z": "제트"}

# 관용 읽기가 글자 이름과 다른 약어
_ACRONYMS = {"CCTV": "씨씨티비", "TV": "티비", "DVD": "디브이디", "VR": "브이알"}

# 차량번호: [지역] 12가 3456 / 123가 4567
_PLATE_CHARS = "가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주아바사자배하허호육해공국합"
_REGIONS = "서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주"
PLATE_RE = re.compile(rf"(?<!\d)(?:({_REGIONS})\s*)?(\d{{2,3}})\s*([{_PLATE_CHARS}])\s*(\d{{4}})(?!\d)")
# 뒷번호만 쓴 경우: "3456 차량", "3456번 차량 차주"
PLATE_TAIL_RE = re.compile(r"(?<![\d가-힣])(\d{4})(?=\s*(?:번\s*)?(?:차량|차주))")


def mask_plates(text: str) -> str:
    """전체 차량번호를 뒷자리 4자리로 줄임: '12가 3456 차량' → '3456 차량'"""
    return PLATE_RE.sub(lambda m: m.group(4), text)


# 숫자 하나하나 읽는 특수 번호
_SPECIAL_NUMBERS = {"112", "119", "114", "110", "120", "1330", "182", "1366", "1388"}


def sino(n: int) -> str:
    """한자어 수: 12345 → 만이천삼백사십오"""
    if n == 0:
        return "영"
    if n < 0:
        return "마이너스 " + sino(-n)
    big_units = ["", "만", "억", "조", "경"]
    out = []
    idx = 0
    while n > 0:
        group = n % 10000
        n //= 10000
        if group:
            s = _four(group)
            if idx == 1 and group == 1:
                s = ""  # "일만" → "만"
            out.append(s + big_units[idx])
        idx += 1
    return "".join(reversed(out))


def _four(n: int) -> str:
    s = ""
    for unit, value in (("천", 1000), ("백", 100), ("십", 10)):
        d = n // value % 10
        if d:
            s += ("" if d == 1 else _SINO_DIGITS[d]) + unit
    d = n % 10
    if d:
        s += _SINO_DIGITS[d]
    return s


def native(n: int) -> str:
    """고유어 관형형 (1~99): 1→한, 20→스무, 21→스물한"""
    if n == 20:
        return "스무"
    return _NATIVE_TENS[n // 10] + _NATIVE_ONES[n % 10]


def _read_number(num: str, counter: str = "") -> str:
    num = num.replace(",", "")
    if "." in num:
        whole, frac = num.split(".", 1)
        text = sino(int(whole or "0")) + " 점 " + "".join(_SINO_DIGITS[int(c)] for c in frac)
        return f"{text} {counter}".strip()
    if len(num) > 1 and num.startswith("0"):
        return f"{_digits(num)} {counter}".strip()  # 007 → 공공칠
    n = int(num)
    if counter in _NATIVE_SET and 1 <= n < 100:
        if counter == "번째" and n == 1:
            return "첫 번째"
        return f"{native(n)} {counter}"
    if counter == "월" and n in (6, 10):
        return "유월" if n == 6 else "시월"
    return f"{sino(n)} {counter}".strip()


def _digits(s: str) -> str:
    return "".join(_PHONE_DIGITS[int(c)] for c in s if c.isdigit())


def _prefix_before(m: re.Match) -> str:
    """시각 앞에 이미 붙어 있는 오전/오후 등."""
    p = re.search(rf"({_TIME_PREFIX})\s*$", m.string[:m.start()])
    return p.group(1) if p else ""


def _clock(h: int, prefix: str) -> str:
    """24시간제 → 방송용 12시간제: 18 → '오후 6시' (앞에 오전/오후가 있으면 붙이지 않음)."""
    if prefix:
        return f"{h - 12 if h > 12 else h}시"
    if h in (0, 24):
        return "밤 12시"
    if h < 12:
        return f"오전 {h}시"
    return "낮 12시" if h == 12 else f"오후 {h - 12}시"


def _symbols(t: str) -> str:
    """읽으면 어색한 기호 정리 (괄호·글머리표·가운뎃점 등)."""
    t = re.sub(r"^\s*(?:[-•·*]\s+|[▶▷■□●○◆◇★☆※]+\s*)", "", t, flags=re.M)
    t = re.sub(r"[※★☆■□◆◇▶▷●○]", " ", t)
    t = re.sub(r"[\[【<〈「『]\s*([^\]】>〉」』]{1,30}?)\s*[\]】>〉」』]", r"\1, ", t)
    t = re.sub(r"(?<=[가-힣])\s*[·ㆍ/]\s*(?=[가-힣])", ", ", t)
    t = re.sub(r"\s+/\s+", ", ", t)
    t = re.sub(r"\.{3,}|…", ", ", t)
    t = re.sub(r"\s*\n+\s*", ". ", t.strip())
    return t


def _range(m: re.Match) -> str:
    """'3~4명' → '3명에서 4명', '9시~18시' → '9시부터 18시까지'."""
    lnum, lc, lday, rp, rnum, rc, rest, rday_tail, rday = m.groups()
    rc = rc or ""
    left = f"{lnum}{lc or rc}" if lnum else lday
    right = f"{rp or ''}{rnum}{rc}{rest or ''}{rday_tail or ''}" if rnum else rday
    timeish = bool(lday or rday or rday_tail) or (lc or rc) in _TIME_COUNTERS
    if not timeish:
        return f"{left}에서 {right}"
    tail = m.string[m.end():]
    end = "" if re.match(r"\s*(?:까지|사이|중|동안|간)", tail) else "까지"
    return f"{left}부터 {right}{end}"


def normalize(text: str, letters: bool = True) -> str:
    t = _apply_lexicon(text)
    t = _symbols(t)
    # 영문 단어·표기 (Wi-Fi, A/S, Q&A, 3pm, 30km/h, 1F, No.3)
    t = _WORDS_RE.sub(lambda m: _WORDS[m.group(1).lower()], t)
    t = re.sub(r"(?<![A-Za-z])([A-Z])\s*/\s*([A-Z])(?![A-Za-z])", r"\1\2", t)
    t = re.sub(r"(?<=[A-Za-z])\s*&\s*(?=[A-Za-z])", "앤", t)
    t = re.sub(r"(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?(?![A-Za-z])",
               lambda m: ("오전 " if m.group(3) in "Aa" else "오후 ") + m.group(1)
               + (f":{m.group(2)}" if m.group(2) else "시"), t)
    t = re.sub(r"(?<![A-Za-z])(AM|PM|am|pm)\s*(?=\d)", lambda m: "오전 " if m.group(1) in ("AM", "am") else "오후 ", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*km/h", r"시속 \1킬로미터", t, flags=re.I)
    t = re.sub(r"(?<![A-Za-z])No\.\s*(\d+)", r"\1번", t, flags=re.I)
    t = re.sub(r"(?<![A-Za-z\d])(\d{1,3})\s*F(?![A-Za-z])", r"\1층", t)
    t = re.sub(r"(?<![A-Za-z])B(\d)(?=\s*주차장)", r"지하 \1층", t)
    # 차량번호는 한 자리씩: 12가 3456 → 일이가 삼사오육
    t = PLATE_RE.sub(lambda m: f"{(m.group(1) + ' ') if m.group(1) else ''}"
                               f"{_digits(m.group(2))}{m.group(3)} {_digits(m.group(4))}", t)
    t = PLATE_TAIL_RE.sub(lambda m: _digits(m.group(1)), t)
    # 1,000 → 1000
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)
    # 전화번호 (010-1234-5678, 010.1234.5678, 01012345678, 02-123-4567, 1588-1234)
    t = re.sub(r"(?<![\d\-.])(0\d{1,2}|1[5-9]\d{2})[-.](\d{3,4})(?:[-.](\d{4}))?(?![\d\-.])",
               lambda m: "에 ".join(_digits(g) for g in m.groups() if g), t)
    t = re.sub(r"(?<!\d)(01[016789])(\d{3,4})(\d{4})(?!\d)",
               lambda m: "에 ".join(_digits(g) for g in m.groups()), t)
    # 날짜 2026-10-31 / 2026.10.31 / 2026/10/31
    def _date(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        return f"{y}년 {mo}월 {d}일"
    t = re.sub(r"(?<!\d)(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\.?(?!\d)", _date, t)
    # 월/일 표기는 요일이 붙었거나 기간(~)일 때만 날짜로 본다: 11/3(월), 11.3~11.10
    def _md(m):
        mo, d = int(m.group(1)), int(m.group(2))
        return f"{mo}월 {d}일" if 1 <= mo <= 12 and 1 <= d <= 31 else m.group(0)
    t = re.sub(rf"(?<![\d.])(\d{{1,2}})[./](\d{{1,2}})(?=\s*\(\s*[{_DAY}])", _md, t)
    t = re.sub(r"(?<![\d.])(\d{1,2})[./](\d{1,2})(?=\s*[~∼〜]\s*\d{1,2}[./]\d{1,2}(?!\d))", _md, t)
    t = re.sub(r"(?<=[~∼〜])\s*(\d{1,2})[./](\d{1,2})(?![\d.])", lambda m: " " + _md(m), t)
    # 요일: (월) → 월요일, (월~금) → 월요일부터 금요일까지
    t = re.sub(rf"\(\s*([{_DAY}])\s*[~∼〜\-]\s*([{_DAY}])\s*\)", r" \1요일~\2요일", t)
    t = re.sub(rf"\(\s*([{_DAY}])\s*\)", r" \1요일", t)
    t = re.sub(rf"(?<![가-힣])([{_DAY}])\s*[~∼〜]\s*([{_DAY}])(?![가-힣])", r"\1요일~\2요일", t)
    # 시각 14:30 / 09:05:10 → 오후 2시 30분
    def _time(m):
        h, mi, se = int(m.group(1)), int(m.group(2)), m.group(3)
        if h > 24 or mi > 59:
            return m.group(0)
        s = _clock(h, _prefix_before(m)) + (f" {mi}분" if mi else "")
        return s + (f" {int(se)}초" if se and int(se) else "")
    t = re.sub(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])", _time, t)
    # 13시~23시 → 오후 1시~11시 ('24시간', '시청' 등은 제외)
    t = re.sub(r"(?<![\d.:])(1[3-9]|2[0-3])\s*시(?=$|[^가-힣]|에|까지|부터|경|쯤|이후|이전|전|후|반|정각|사이)",
               lambda m: _clock(int(m.group(1)), _prefix_before(m)), t)
    # 지하층 B1층 → 지하 1층
    t = re.sub(r"(?<![A-Za-z])B(\d+)\s*층", r"지하 \1층", t)
    # 영하 온도 -5℃ / -5도
    t = re.sub(r"(?<![\d\w])-(\d+(?:\.\d+)?)\s*(℃|°C|도)", r"영하 \1도", t)
    # 단위 기호 (숫자 뒤)
    unit_re = "|".join(map(re.escape, sorted(_UNITS, key=len, reverse=True)))
    t = re.sub(rf"(\d)\s*({unit_re})(?![A-Za-z])", lambda m: m.group(1) + _UNITS[m.group(2)], t)
    # 범위: 2~3층 → 2층에서 3층 / 9시~오후 6시 → 9시부터 오후 6시까지 / 월요일~금요일
    num = r"\d+(?:\.\d+)?"
    t = re.sub(
        rf"(?:({num})\s*({_COUNTER_RE})?|([{_DAY}]요일))\s*[~∼〜]\s*"
        rf"(?:({_TIME_PREFIX}\s*)?({num})\s*({_COUNTER_RE})?((?:\s*\d+\s*(?:월|일|시|분|초))*)"
        rf"(\s*[{_DAY}]요일)?|([{_DAY}]요일))", _range, t)
    t = re.sub(r"[~∼〜]", " ", t)
    # 숫자 사이 하이픈: 101-1502 → 101 다시 1502
    t = re.sub(r"(?<=\d)\s*-\s*(?=\d)", " 다시 ", t)
    # 1+1 → 1 플러스 1
    t = re.sub(r"\s*\+\s*", " 플러스 ", t)
    # 긴급번호 등 자리 읽기 (119 → 일일구, "119번"도 동일 / "119명"은 제외)
    t = re.sub(rf"(?<![\d.])(\d{{3,4}})(?![\d.])(?!\s*(?:{_COUNTER_NO_BEON}))",
               lambda m: _digits(m.group(1)) if m.group(1) in _SPECIAL_NUMBERS else m.group(1), t)
    # 1만 원 → 만 원, 1천 → 천 (일만·일천으로 읽지 않음)
    t = re.sub(r"(?<![\d.])1\s*(?=[천만])", "", t)
    # 영문 대문자 약어 (B동, KTX, CCTV) / 알파벳+숫자 (A3 → 에이 3)
    if letters:
        t = re.sub(r"(?<![A-Za-z])([A-Z]{1,5})(?![A-Za-z])",
                   lambda m: _ACRONYMS.get(m.group(1))
                   or "".join(_LETTERS[c] for c in m.group(1)), t)
        t = re.sub(r"(?<=[가-힣])\s*-\s*(?=\d)", " ", t)
    # 일반 숫자 (+단위) — 단위가 없으면 뒤 띄어쓰기를 그대로 둔다
    t = re.sub(rf"(\d+(?:\.\d+)?)(?:\s*({_COUNTER_RE}))?",
               lambda m: _read_number(m.group(1), m.group(2) or ""), t)
    t = re.sub(r"\s+([,.!?])", r"\1", t)
    t = re.sub(r",(\s*,)+", ",", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip(" ,")
