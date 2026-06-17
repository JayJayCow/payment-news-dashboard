#!/usr/bin/env python3
"""
간편결제 뉴스 수집 스크립트
- 네이버 뉴스 Search API 사용
- 매일 실행하여 data/news.json에 누적 저장 (90일 보관)
"""

import os
import json
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

# ─── 설정 ─────────────────────────────────────────────
CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
DATA_FILE     = Path(__file__).parent.parent / "data" / "news.json"
KEEP_DAYS     = 90

SEARCH_QUERIES = [
    "네이버페이",
    "네이버파이낸셜",
    "카카오페이",
    "토스페이 토스페이먼츠",
    "토스플레이스",
    "토스 간편결제",
    "페이코 간편결제",
    "쿠팡페이",
    "삼성페이 삼성월렛",
    "애플페이",
    "간편결제",
]

PROVIDERS = {
    "네이버페이": ["네이버페이", "네이버파이낸셜", "네이버 페이", "npay", "naver pay"],
    "카카오페이": ["카카오페이", "카카오 페이", "kakaopay"],
    "토스페이":  ["토스페이", "토스페이먼츠", "토스플레이스", "토스", "toss pay", "tosspay"],
    "페이코":    ["페이코", "payco"],
    "쿠팡페이":  ["쿠팡페이", "coupangpay"],
    "삼성페이":  ["삼성페이", "삼성월렛", "삼성 월렛", "samsung pay", "samsung wallet"],
    "애플페이":  ["애플페이", "애플 페이", "apple pay"],
}

SOURCE_MAP = {
    "hankyung.com": "한국경제", "mk.co.kr": "매일경제", "chosun.com": "조선일보",
    "joongang.co.kr": "중앙일보", "donga.com": "동아일보", "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문", "yna.co.kr": "연합뉴스", "newsis.com": "뉴시스",
    "news1.kr": "뉴스1", "etnews.com": "전자신문", "zdnet.co.kr": "ZDNet",
    "edaily.co.kr": "이데일리", "inews24.com": "아이뉴스24", "mt.co.kr": "머니투데이",
    "fnnews.com": "파이낸셜뉴스", "sedaily.com": "서울경제", "biz.chosun.com": "조선비즈",
    "heraldcorp.com": "헤럴드경제", "asiae.co.kr": "아시아경제", "newspim.com": "뉴스핌",
    "thebell.co.kr": "더벨", "bloter.net": "블로터", "venturebeat.com": "VentureBeat",
    "techcrunch.com": "TechCrunch", "m.etnews.com": "전자신문", "news.naver.com": "네이버뉴스",
    "financialpost.co.kr": "파이낸셜포스트",
}
# ──────────────────────────────────────────────────────


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def parse_pub_date(s: str) -> str:
    try:
        dt = parsedate_to_datetime(s)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s).isoformat()
    except Exception:
        return s


def classify(title: str) -> str:
    t = title.lower()
    for cat, keywords in PROVIDERS.items():
        if any(k.lower() in t for k in keywords):
            return cat
    # 제목에 결제 관련 키워드가 있어야만 간편결제로 분류 (본문에만 있는 기사 제외)
    if any(k in t for k in ["간편결제", "핀테크", "간편 결제", "결제 서비스", "결제 시장", "결제 업계", "결제 플랫폼"]):
        return "간편결제"
    return ""  # 무관 기사


_domain_name_cache: dict[str, str] = {}


def fetch_site_name(url: str) -> str:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        host = host.lstrip("www.")
        if host in _domain_name_cache:
            return _domain_name_cache[host]
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read(8192).decode("utf-8", errors="ignore")
        m = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\'](.*?)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:site_name["\']', html, re.I)
        name = m.group(1).strip() if m else ""
        _domain_name_cache[host] = name
        return name
    except Exception:
        return ""


def extract_source(url: str) -> str:
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        host = host.lstrip("www.")
        if host in SOURCE_MAP:
            return SOURCE_MAP[host]
        name = fetch_site_name(url)
        if name:
            SOURCE_MAP[host] = name
            return name
        parts = host.split(".")
        KR_2ND = {"co.kr", "or.kr", "go.kr", "ac.kr", "ne.kr", "re.kr", "pe.kr", "mil.kr"}
        if len(parts) >= 3 and ".".join(parts[-2:]) in KR_2ND:
            return parts[-3]
        return parts[-2] if len(parts) >= 2 else host
    except Exception:
        return ""


def search_naver(query: str, display: int = 100) -> list[dict]:
    url = (
        "https://openapi.naver.com/v1/search/news.json?"
        + urllib.parse.urlencode({"query": query, "display": display, "sort": "date"})
    )
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("items", [])
    except Exception as e:
        print(f"  [WARN] 검색 실패 '{query}': {e}")
        return []


def make_id(item: dict) -> str:
    return item.get("originallink") or item.get("link") or item.get("title", "")


def collect_all() -> list[dict]:
    seen_ids: set[str] = set()
    articles: list[dict] = []

    for q in SEARCH_QUERIES:
        print(f"  검색: {q}")
        items = search_naver(q)
        for item in items:
            aid = make_id(item)
            if aid in seen_ids:
                continue
            seen_ids.add(aid)

            title = strip_html(item.get("title", ""))
            category = classify(title)
            if not category:
                continue  # 무관 기사 제외

            articles.append({
                "title":        title,
                "link":         item.get("link", ""),
                "originallink": item.get("originallink", ""),
                "description":  strip_html(item.get("description", "")),
                "pubDate":      parse_pub_date(item.get("pubDate", "")),
                "category":     category,
                "source":       extract_source(item.get("originallink", "") or item.get("link", "")),
            })

    print(f"  수집 완료: {len(articles)}건 (중복 제거 후)")
    return articles


def load_existing() -> tuple[list[dict], str | None]:
    if not DATA_FILE.exists():
        return [], None
    try:
        with DATA_FILE.open(encoding="utf-8") as f:
            d = json.load(f)
        return d.get("articles", []), d.get("lastFetch")
    except Exception as e:
        print(f"  [WARN] 기존 데이터 로드 실패: {e}")
        return [], None


def merge_and_prune(existing: list[dict], new_items: list[dict]) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    id_map: dict[str, dict] = {}

    for a in existing:
        aid = a.get("originallink") or a.get("link") or a.get("title", "")
        id_map[aid] = a

    added = 0
    for a in new_items:
        aid = a.get("originallink") or a.get("link") or a.get("title", "")
        if aid not in id_map:
            id_map[aid] = a
            added += 1

    def is_recent(a: dict) -> bool:
        try:
            dt = datetime.fromisoformat(a.get("pubDate", ""))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= cutoff
        except Exception:
            return True

    result = [a for a in id_map.values() if is_recent(a)]
    result.sort(key=lambda a: a.get("pubDate", ""), reverse=True)
    print(f"  +{added}건 추가 / 총 {len(result)}건 보관")
    return result


def save(articles: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump({"articles": articles, "lastFetch": now_iso}, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료 → {DATA_FILE}  ({len(articles)}건, lastFetch={now_iso})")


def main():
    print("=== 간편결제 뉴스 수집 시작 ===")
    existing, last_fetch = load_existing()
    print(f"  기존 데이터: {len(existing)}건  (마지막 수집: {last_fetch})")

    new_items = collect_all()
    merged = merge_and_prune(existing, new_items)
    save(merged)
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
