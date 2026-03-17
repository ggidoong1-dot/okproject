# © 2026 donghapro. All Rights Reserved.
"""
글로벌 뉴스 실시간 크롤링 모듈
Google News RSS를 통해 종목/테마 관련 뉴스를 수집합니다.
Supabase 의존성 제거 — HTTP 요청만 사용 (Gemini API 호출 0회).
"""
import streamlit as st
import urllib.request
import urllib.parse
import ssl
import xml.etree.ElementTree as ET
import re
import time
import threading
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Dict


# SSL 설정
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False

# RSS 요청 속도 제한 (Google 차단 방지)
_RSS_MIN_INTERVAL = 2.0  # 요청 간 최소 간격 (초)
_RSS_BURST_PAUSE = 10.0  # 연속 요청 후 쉬는 시간 (초)
_RSS_BURST_COUNT = 5     # 이만큼 요청 후 쉼
_rss_last_request = 0.0
_rss_request_count = 0
_rss_lock = threading.Lock()
_SSL_CTX.verify_mode = ssl.CERT_NONE


# =============================================================
# 종목 → 테마/기술 키워드 매핑
# =============================================================

# 종목코드 → (종목 영문명, [테마 키워드 5개])
TICKER_THEME_KEYWORDS = {
    # 반도체
    "005930": ("Samsung Electronics", ["반도체 HBM", "삼성전자 파운드리", "AI 반도체", "삼성전자 실적", "갤럭시 AI"]),
    "000660": ("SK Hynix", ["HBM AI 메모리", "SK하이닉스 DRAM", "고대역폭메모리", "SK하이닉스 실적", "엔비디아 HBM"]),
    # 2차전지
    "373220": ("LG Energy Solution", ["전고체 배터리", "LG에너지 북미", "EV 배터리 공급망", "LG에너지솔루션 실적", "배터리 IRA"]),
    "006400": ("Samsung SDI", ["삼성SDI 전고체", "배터리 양극재", "유럽 배터리", "삼성SDI 실적", "전기차 배터리 시장"]),
    "247540": ("Ecopro BM", ["에코프로 양극재", "2차전지 소재", "배터리 리사이클링", "에코프로비엠 실적", "양극재 가격"]),
    "086520": ("Ecopro", ["에코프로 2차전지", "양극재 시장", "배터리 밸류체인", "에코프로 주가", "리튬 가격"]),
    # 자동차
    "005380": ("Hyundai Motor", ["현대차 전기차", "자율주행 기술", "수소차 시장", "현대자동차 실적", "현대차 미국 공장"]),
    "000270": ("Kia", ["기아 EV", "전기차 판매", "모빌리티 플랫폼", "기아 실적", "기아 EV6 EV9"]),
    # 바이오
    "207940": ("Samsung Biologics", ["삼성바이오 CMO", "바이오시밀러", "위탁생산 시장", "삼성바이오로직스 실적", "바이오 CDMO"]),
    "068270": ("Celltrion", ["셀트리온 바이오시밀러", "항체 치료제", "FDA 승인", "셀트리온 실적", "셀트리온 신약"]),
    # IT/인터넷
    "035420": ("Naver", ["네이버 AI", "하이퍼클로바", "검색 광고 시장", "네이버 실적", "네이버 클라우드"]),
    "035720": ("Kakao", ["카카오 AI", "플랫폼 규제", "카카오 핀테크", "카카오 실적", "카카오톡 광고"]),
    # 금융
    "105560": ("KB Financial", ["KB금융 실적", "은행 금리", "밸류업 프로그램", "KB금융 배당", "금융지주 자사주"]),
    "055550": ("Shinhan Financial", ["신한금융 배당", "금융지주 실적", "금리 인하", "신한금융 밸류업", "은행 순이자마진"]),
    # 조선
    "329180": ("HD Hyundai Heavy", ["HD현대중공업 수주", "LNG 운반선", "조선 슈퍼사이클", "HD현대중공업 실적", "방산 함정 수주"]),
    "009540": ("HD Korea Shipbuilding", ["한국조선해양 수주", "친환경 선박", "해양플랜트", "HD한국조선해양 실적", "조선업 수주잔고"]),
    # 화학/정유
    "051910": ("LG Chem", ["LG화학 배터리소재", "석유화학 다운사이클", "양극재 분리", "LG화학 실적", "LG화학 분할"]),
    "096770": ("SK Innovation", ["SK이노 배터리", "정유 마진", "SK온 IPO", "SK이노베이션 실적", "배터리 적자"]),
    # 철강
    "005490": ("POSCO Holdings", ["포스코 리튬", "2차전지 소재", "철강 탄소중립", "포스코홀딩스 실적", "포스코 아르헨티나 리튬"]),
    # 방산
    "012450": ("Hanwha Aerospace", ["한화에어로 K방산", "우주항공 산업", "방산 수출", "한화에어로스페이스 실적", "K9 자주포 수출"]),
    "079550": ("LIG Nex1", ["LIG넥스원 미사일", "방산 수주", "무인무기체계", "LIG넥스원 실적", "천궁 미사일"]),
    # 원자력
    "034020": ("Doosan Enerbility", ["두산에너빌리티 원전", "소형모듈원자로 SMR", "원자력 르네상스", "두산에너빌리티 실적", "체코 원전 수주"]),
    # 엔터
    "352820": ("HYBE", ["하이브 BTS", "K-pop 글로벌", "위버스 플랫폼", "하이브 실적", "하이브 아일릿"]),
    # SK텔레콤, 카카오뱅크 등
    "017670": ("SK Telecom", ["SKT AI", "AI 인프라", "통신 AI 서비스", "SKT 실적", "에이닷 AI"]),
    "323410": ("KakaoBank", ["카카오뱅크 실적", "인터넷은행", "핀테크 시장", "카카오뱅크 대출", "디지털 금융"]),
    # SK스퀘어
    "402340": ("SK Square", ["SK스퀘어 투자", "SK하이닉스 지분", "반도체 밸류체인", "SK스퀘어 실적", "SK스퀘어 NAV"]),
}


# =============================================================
# Google News RSS 크롤링
# =============================================================

def _fetch_rss(url: str, timeout: int = 10) -> str:
    """URL에서 RSS XML 텍스트를 가져옵니다. 속도 제한 적용."""
    global _rss_last_request, _rss_request_count
    try:
        with _rss_lock:
            # 요청 간 최소 2초 간격
            now = time.monotonic()
            elapsed = now - _rss_last_request
            if elapsed < _RSS_MIN_INTERVAL:
                time.sleep(_RSS_MIN_INTERVAL - elapsed)

            # 5회 연속 요청 후 10초 휴식
            _rss_request_count += 1
            if _rss_request_count >= _RSS_BURST_COUNT:
                time.sleep(_RSS_BURST_PAUSE)
                _rss_request_count = 0

            _rss_last_request = time.monotonic()

        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
        })
        resp = urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
        return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            # Too Many Requests — 30초 대기 후 1회 재시도
            time.sleep(30)
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                })
                resp = urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
                return resp.read().decode("utf-8")
            except Exception:
                return ""
        return ""
    except Exception:
        return ""


def _parse_rss_items(xml_text: str, limit: int = 30, max_age_days: int = 30) -> List[Dict]:
    """RSS XML에서 뉴스 항목을 파싱합니다. max_age_days 이내 기사만 반환."""
    if not xml_text:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    articles = []
    try:
        root = ET.fromstring(xml_text)
        items = root.findall(".//item")

        for item in items:
            if len(articles) >= limit:
                break

            title_raw = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            source_el = item.find("source")
            source = source_el.text if source_el is not None else ""

            # HTML 태그 제거
            title = re.sub(r"<[^>]+>", "", title_raw).strip()
            if not title:
                continue

            # 날짜 파싱 + 1달 이내 필터
            published_at = ""
            if pub_date:
                try:
                    dt = parsedate_to_datetime(pub_date)
                    if dt < cutoff:
                        continue
                    published_at = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    published_at = pub_date

            articles.append({
                "title": title,
                "title_ko": None,
                "summary_ai": None,
                "sentiment": None,
                "source": source,
                "published_at": published_at,
                "link": link,
                "quality_score": None,
            })
    except ET.ParseError:
        pass

    return articles


def _google_news_rss(query: str, lang: str = "ko", limit: int = 5) -> List[Dict]:
    """Google News RSS에서 키워드 검색 결과를 가져옵니다. 최근 1달 이내만."""
    encoded_q = urllib.parse.quote(f"{query} when:30d")
    if lang == "ko":
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl=ko&gl=KR&ceid=KR:ko"
    else:
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en&gl=US&ceid=US:en"

    xml_text = _fetch_rss(url)
    return _parse_rss_items(xml_text, limit=limit, max_age_days=30)


# =============================================================
# 키워드 자동 생성
# =============================================================

def _build_theme_keywords(ticker: str, name: str) -> List[str]:
    """
    종목에 대한 테마/기술 키워드 5개를 반환합니다.
    매핑 테이블에 있으면 사용, 없으면 yfinance 정보로 자동 생성.
    """
    # 1. 매핑 테이블에서 조회
    if ticker in TICKER_THEME_KEYWORDS:
        _, keywords = TICKER_THEME_KEYWORDS[ticker]
        return keywords[:5]

    # 2. 해외 주식: yfinance info에서 sector/industry 추출
    if not ticker.isdigit():
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info
            sector = info.get("sector", "")
            industry = info.get("industry", "")
            company = info.get("shortName", name)
            keywords = []
            if company:
                keywords.append(f"{company} stock")
                keywords.append(f"{company} earnings")
            if industry:
                keywords.append(industry)
            if sector:
                keywords.append(f"{sector} market")
            keywords.append(f"{ticker} analysis")
            return keywords[:5] if keywords else [f"{ticker} stock", name, f"{name} earnings"]
        except Exception:
            return [f"{ticker} stock", name, f"{name} earnings", f"{name} analysis", f"{name} forecast"]

    # 3. 한국 주식인데 매핑에 없는 경우: 종목명 기반
    return [name, f"{name} 실적", f"{name} 전망", f"{name} 주가", f"{name} 투자"]


def _get_stock_english_name(ticker: str, name: str) -> str:
    """영문 종목명 반환 (Google 영문 검색용)"""
    if ticker in TICKER_THEME_KEYWORDS:
        return TICKER_THEME_KEYWORDS[ticker][0]
    if not ticker.isdigit():
        return ticker  # 해외 주식은 티커 자체가 영문
    return name


# =============================================================
# 공개 API (app.py 호환 인터페이스)
# =============================================================

@st.cache_data(ttl=600)
def fetch_global_news(ticker: str, name: str, limit: int = 50) -> List[Dict]:
    """
    Google News에서 종목 관련 뉴스를 실시간 크롤링합니다.
    한국어 + 영어 뉴스 모두 대량 수집.
    """
    all_articles = []
    seen_titles = set()

    # 종목 직접 검색 (한국어) — 최대 30건
    kr_query = name if name else ticker
    kr_articles = _google_news_rss(kr_query, lang="ko", limit=30)
    for a in kr_articles:
        if a["title"] not in seen_titles:
            seen_titles.add(a["title"])
            all_articles.append(a)

    # 종목 직접 검색 (영어) — 최대 20건
    en_name = _get_stock_english_name(ticker, name)
    en_articles = _google_news_rss(en_name, lang="en", limit=20)
    for a in en_articles:
        if a["title"] not in seen_titles:
            seen_titles.add(a["title"])
            all_articles.append(a)

    return all_articles[:limit]


@st.cache_data(ttl=600)
def fetch_theme_news(ticker: str, name: str, limit: int = 80) -> List[Dict]:
    """
    종목의 테마/기술 키워드 5개로 관련 뉴스를 대량 수집합니다.
    """
    keywords = _build_theme_keywords(ticker, name)
    all_articles = []
    seen_titles = set()

    for kw in keywords[:5]:
        # 한국어 검색 — 키워드당 최대 20건
        articles = _google_news_rss(kw, lang="ko", limit=20)
        for a in articles:
            if a["title"] not in seen_titles:
                seen_titles.add(a["title"])
                a["keyword"] = kw
                all_articles.append(a)

        # 영어 검색 (영문 키워드인 경우) — 키워드당 최대 10건
        if re.match(r"^[A-Za-z\s]+$", kw):
            en_articles = _google_news_rss(kw, lang="en", limit=10)
            for a in en_articles:
                if a["title"] not in seen_titles:
                    seen_titles.add(a["title"])
                    a["keyword"] = kw
                    all_articles.append(a)

    return all_articles[:limit]


# =============================================================
# 뉴스 제목 기반 감성 분석
# =============================================================

_POSITIVE_KW = [
    # 한국어
    "상승", "급등", "신고가", "호실적", "흑자", "순매수", "성장", "수주", "돌파",
    "최대", "호재", "반등", "강세", "확대", "개선", "회복", "상향", "기대",
    "수혜", "낙관", "호조", "증가", "턴어라운드",
    # 영어
    "surge", "rally", "jump", "soar", "gain", "rise", "bullish", "upgrade",
    "beat", "record", "high", "growth", "profit", "boost", "optimis",
    "outperform", "buy", "positive", "strong",
]
_NEGATIVE_KW = [
    # 한국어
    "하락", "급락", "폭락", "적자", "순매도", "감소", "위기", "우려", "리스크",
    "약세", "하향", "부진", "손실", "악재", "침체", "둔화", "매도", "축소",
    "불안", "경고", "제재", "규제", "소송", "파산",
    # 영어
    "fall", "drop", "plunge", "crash", "decline", "loss", "bear", "downgrade",
    "miss", "low", "risk", "warning", "sell", "negative", "weak", "cut",
    "recession", "layoff", "bankrupt",
]


# 주요 경제지/통신사 (소스 가중치 1.5x)
_MAJOR_SOURCES = [
    "reuters", "bloomberg", "cnbc", "wsj", "wall street journal",
    "financial times", "barron", "investing.com",
    "매일경제", "매경", "한국경제", "한경", "조선비즈", "서울경제",
    "이데일리", "머니투데이", "뉴스1", "연합뉴스", "연합인포맥스",
]


def _calc_article_weight(article: Dict) -> float:
    """기사별 가중치 계산 (시간 + 소스)"""
    weight = 1.0

    # 시간 가중치: 7일 이내 1.5x, 7~30일 1.0x, 30일 초과 0.5x
    pub = article.get("published_at", "")
    if pub:
        try:
            pub_date = datetime.strptime(pub[:10], "%Y-%m-%d")
            days_ago = (datetime.now() - pub_date).days
            if days_ago <= 7:
                weight *= 1.5
            elif days_ago > 30:
                weight *= 0.5
            # 7~30일은 기본 1.0x
        except (ValueError, TypeError):
            pass

    # 소스 가중치: 주요 경제지 1.5x
    source = (article.get("source") or "").lower()
    if source and any(major in source for major in _MAJOR_SOURCES):
        weight *= 1.5

    return weight


def _analyze_sentiment(articles: List[Dict]) -> Dict:
    """뉴스 제목 키워드 기반 감성 분석. 시간/소스 가중치 적용. 0~100 점수 반환."""
    if not articles:
        return {"dominant": "N/A", "counts": {"Positive": 0, "Negative": 0, "Neutral": 0}, "score": 50}

    pos_w, neg_w, neu_w = 0.0, 0.0, 0.0
    pos_c, neg_c, neu_c = 0, 0, 0

    for article in articles:
        title = (article.get("title") or "").lower()
        w = _calc_article_weight(article)

        p = sum(1 for kw in _POSITIVE_KW if kw in title)
        n = sum(1 for kw in _NEGATIVE_KW if kw in title)

        if p > n:
            pos_w += w
            pos_c += 1
        elif n > p:
            neg_w += w
            neg_c += 1
        else:
            neu_w += w
            neu_c += 1

    total_w = pos_w + neg_w + neu_w
    # 가중 점수: 긍정 비율 기반 0~100 (중립은 50으로 취급)
    score = round(((pos_w * 100) + (neu_w * 50) + (neg_w * 0)) / total_w) if total_w > 0 else 50

    if pos_w > neg_w:
        dominant = "Positive"
    elif neg_w > pos_w:
        dominant = "Negative"
    else:
        dominant = "Neutral"

    return {
        "dominant": dominant,
        "counts": {"Positive": pos_c, "Negative": neg_c, "Neutral": neu_c},
        "score": score,
    }


_FALLBACK_SUFFIXES_KR = ["산업", "시장 전망", "투자 의견", "목표주가", "분석"]
_FALLBACK_SUFFIXES_EN = ["outlook", "forecast", "investor", "market", "trend"]

_MIN_NEWS_TARGET = 50  # 최소 목표 수집 건수


def get_news_for_stock(ticker: str, name: str) -> Dict:
    """
    종목 관련 뉴스 종합 조회 (직접 + 테마 키워드).
    부족하면 자동으로 검색어를 확장하여 최소 50건 이상 수집.
    """
    direct = fetch_global_news(ticker, name)
    theme = fetch_theme_news(ticker, name)

    # 직접 뉴스와 중복 제거
    direct_titles = {a["title"] for a in direct}
    theme = [a for a in theme if a["title"] not in direct_titles]

    # 사용된 키워드
    keywords_used = list(_build_theme_keywords(ticker, name))

    all_news = direct + theme

    # 부족하면 추가 키워드로 확장 수집
    if len(all_news) < _MIN_NEWS_TARGET:
        seen_titles = {a["title"] for a in all_news}
        en_name = _get_stock_english_name(ticker, name)
        extra_queries = []

        for suffix in _FALLBACK_SUFFIXES_KR:
            extra_queries.append((f"{name} {suffix}", "ko"))
        if en_name != name:
            for suffix in _FALLBACK_SUFFIXES_EN:
                extra_queries.append((f"{en_name} {suffix}", "en"))

        for query, lang in extra_queries:
            if len(all_news) >= _MIN_NEWS_TARGET:
                break
            articles = _google_news_rss(query, lang=lang, limit=15)
            added = False
            for a in articles:
                if a["title"] not in seen_titles:
                    seen_titles.add(a["title"])
                    a["keyword"] = query
                    theme.append(a)
                    all_news.append(a)
                    added = True
            if added and query not in keywords_used:
                keywords_used.append(query)

    total = len(all_news)

    # 키워드 기반 감성 분석
    sentiment_result = _analyze_sentiment(all_news)

    sentiment_summary = {
        "dominant": sentiment_result["dominant"],
        "counts": sentiment_result["counts"],
        "total": total,
        "score": sentiment_result["score"],
    }

    return {
        "direct": direct,
        "sector": theme,
        "keywords_used": keywords_used,
        "sentiment_summary": sentiment_summary,
        "available": total > 0,
    }


def format_news_for_ai(news_data: Dict) -> str:
    """AI 컨텍스트용 뉴스 텍스트 생성 (리포트 생성 시 Gemini에 전달)"""
    if not news_data.get("available"):
        return ""

    lines = ["[관련 뉴스]"]

    # 사용된 테마 키워드
    keywords = news_data.get("keywords_used", [])
    if keywords:
        lines.append(f"- 테마 키워드: {', '.join(keywords)}")

    lines.append(f"- 수집 뉴스: {news_data['sentiment_summary']['total']}건")

    # 직접 관련 뉴스
    direct = news_data.get("direct", [])
    if direct:
        lines.append("- [종목 뉴스]")
        for a in direct[:5]:
            source = a.get("source", "")
            title = a.get("title", "")
            date = a.get("published_at", "")[:10]
            lines.append(f"  - [{source}] {title} ({date})")

    # 테마 뉴스
    sector = news_data.get("sector", [])
    if sector:
        lines.append("- [테마/기술 뉴스]")
        for a in sector[:5]:
            source = a.get("source", "")
            title = a.get("title", "")
            kw = a.get("keyword", "")
            date = a.get("published_at", "")[:10]
            lines.append(f"  - [{source}] {title} (키워드: {kw}, {date})")

    return "\n".join(lines)
