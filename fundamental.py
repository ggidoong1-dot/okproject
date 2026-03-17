# © 2026 donghapro. All Rights Reserved.
"""
4단계: 펀더멘털 + 수급 + 뉴스 모듈
- PER, PBR, EPS, BPS, 배당수익률, PEG (네이버 금융 API)
- S-RIM 적정주가
- 외국인/기관 수급 (네이버 금융 API)
- 52주 고저 위치 (네이버 금융 API)
- DART 공시 피드 (DART OpenAPI)
- 종목 뉴스 피드 (네이버 금융 API)
- 업종 평균 PER/PBR 비교
"""
import pandas as pd
import numpy as np
import ssl
import urllib.request
import json
import re
import streamlit as st


# SSL 설정
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# API 호출 속도 제한 (초당 최대 5회)
import time as _time
_last_api_call = 0
_API_MIN_INTERVAL = 0.2  # 200ms 간격


def _fetch_naver_api(url: str) -> dict:
    """네이버 금융 모바일 API 호출 (속도 제한 적용)"""
    global _last_api_call
    elapsed = _time.time() - _last_api_call
    if elapsed < _API_MIN_INTERVAL:
        _time.sleep(_API_MIN_INTERVAL - elapsed)
    _last_api_call = _time.time()

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10, context=_SSL_CTX)
        return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def _parse_number(text: str) -> float:
    """'188,700' → 188700, '28.75배' → 28.75, '+928,815' → 928815"""
    if not text:
        return 0
    cleaned = re.sub(r"[^\d.+-]", "", text.replace(",", ""))
    try:
        return float(cleaned) if cleaned else 0
    except ValueError:
        return 0


# =============================================================
# 네이버 금융 데이터 수집
# =============================================================

@st.cache_data(ttl=600)
def get_naver_stock_data(ticker: str) -> dict:
    """네이버 금융 통합 API에서 펀더멘털+수급+52주 데이터 조회"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/integration"
    data = _fetch_naver_api(url)

    if not data or "totalInfos" not in data:
        return {}

    # totalInfos 파싱
    info = {}
    for item in data.get("totalInfos", []):
        info[item.get("code", "")] = item.get("value", "")

    # 수급 (dealTrendInfos)
    deal_trends = data.get("dealTrendInfos", [])

    return {
        "info": info,
        "deal_trends": deal_trends,
        "raw": data,
    }


def get_fundamental_data(ticker: str) -> dict:
    """PER, PBR, EPS, BPS, 배당수익률 조회"""
    naver = get_naver_stock_data(ticker)
    info = naver.get("info", {})

    if not info:
        return {"per": None, "pbr": None, "eps": None, "bps": None, "div_yield": None}

    per = _parse_number(info.get("per", ""))
    pbr = _parse_number(info.get("pbr", ""))
    eps = _parse_number(info.get("eps", ""))
    bps = _parse_number(info.get("bps", ""))
    div_yield = _parse_number(info.get("dividendYieldRatio", ""))

    # 52주 고저
    high_52w = _parse_number(info.get("highPriceOf52Weeks", ""))
    low_52w = _parse_number(info.get("lowPriceOf52Weeks", ""))

    return {
        "per": round(per, 2) if per > 0 else None,
        "pbr": round(pbr, 2) if pbr > 0 else None,
        "eps": int(eps) if eps != 0 else None,
        "bps": int(bps) if bps > 0 else None,
        "div_yield": round(div_yield, 2) if div_yield > 0 else None,
        "high_52w": int(high_52w) if high_52w > 0 else None,
        "low_52w": int(low_52w) if low_52w > 0 else None,
    }


# =============================================================
# PEG 비율
# =============================================================

def calc_peg(per: float, earnings_growth: float = None) -> dict:
    """PEG 비율 계산 (PER ÷ 이익성장률)"""
    if not per or per <= 0:
        return {"peg": None, "classification": "데이터 부족"}

    if earnings_growth is None or earnings_growth == 0:
        return {"peg": None, "classification": "성장률 데이터 부족"}

    peg = round(per / earnings_growth, 2)

    if peg < 0:
        classification = "적자 전환 또는 역성장"
    elif peg < 0.5:
        classification = "매우 저평가"
    elif peg < 1.0:
        classification = "저평가"
    elif peg <= 1.5:
        classification = "적정 수준"
    elif peg <= 2.0:
        classification = "다소 고평가"
    else:
        classification = "고평가"

    return {"peg": peg, "earnings_growth": earnings_growth, "classification": classification}


def _estimate_earnings_growth(ticker: str) -> float:
    """네이버 금융에서 EPS 기반 이익성장률 추정"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/finance/annual"
    data = _fetch_naver_api(url)

    if not data or not isinstance(data, list):
        return None

    # 최근 2개년 EPS로 성장률 계산
    eps_list = []
    for item in data:
        eps_val = item.get("eps")
        if eps_val:
            eps_list.append(_parse_number(str(eps_val)))

    if len(eps_list) >= 2 and eps_list[1] != 0:
        growth = (eps_list[0] - eps_list[1]) / abs(eps_list[1]) * 100
        return round(growth, 2)

    return None


# =============================================================
# S-RIM 적정주가
# =============================================================

def calc_srim(bps: int, roe: float = None, required_return: float = 0.08) -> dict:
    """S-RIM 적정주가 계산"""
    if not bps or bps <= 0:
        return {"optimistic": None, "neutral": None, "pessimistic": None}

    if roe is None:
        roe = 0.10

    excess_return = roe - required_return

    if excess_return <= 0:
        return {
            "optimistic": bps,
            "neutral": bps,
            "pessimistic": round(bps * 0.8),
        }

    excess_earnings = excess_return * bps

    return {
        "optimistic": round(bps + excess_earnings / required_return),
        "neutral": round(bps + excess_earnings / (required_return + 0.10)),
        "pessimistic": round(bps + excess_earnings / (required_return + 0.20)),
    }


def classify_valuation(per: float, pbr: float, current_price: int, srim: dict) -> str:
    """밸류에이션 종합 분류"""
    signals = []

    if per:
        if per < 10:
            signals.append("PER 저평가")
        elif per > 30:
            signals.append("PER 고평가")

    if pbr:
        if pbr < 1:
            signals.append("PBR 저평가 (자산가치 이하)")
        elif pbr > 3:
            signals.append("PBR 고평가")

    if srim.get("neutral") and current_price:
        gap = (srim["neutral"] - current_price) / current_price * 100
        if gap > 20:
            signals.append(f"S-RIM 대비 {gap:.0f}% 저평가")
        elif gap < -20:
            signals.append(f"S-RIM 대비 {abs(gap):.0f}% 고평가")

    if not signals:
        return "적정 수준"

    return " / ".join(signals)


# =============================================================
# 수급 분석 (네이버 API)
# =============================================================

def get_investor_trading(ticker: str) -> dict:
    """외국인/기관/개인 수급 데이터 (네이버 금융)"""
    naver = get_naver_stock_data(ticker)
    deal_trends = naver.get("deal_trends", [])

    if not deal_trends:
        return None

    # 외국인, 기관, 개인 데이터 추출
    fg_values = []
    inst_values = []
    individual_values = []

    for item in deal_trends:
        fg_values.append(_parse_number(item.get("foreignerPureBuyQuant", "0")))
        inst_values.append(_parse_number(item.get("organPureBuyQuant", "0")))
        individual_values.append(_parse_number(item.get("individualPureBuyQuant", "0")))

    def _analyze_series(values: list) -> dict:
        if not values:
            return None
        recent_1d = int(values[0])  # 최근 1일 (리스트 첫 번째가 최신)
        recent_5d = int(sum(values[:5]))
        total = int(sum(values))
        trend = "순매수" if recent_5d > 0 else "순매도"

        # 연속 일수
        consecutive = 0
        if values:
            sign = 1 if values[0] > 0 else -1
            for v in values:
                if (v > 0 and sign > 0) or (v < 0 and sign < 0):
                    consecutive += 1
                else:
                    break
            consecutive *= sign

        return {
            "total": total,
            "recent_5d": recent_5d,
            "recent_1d": recent_1d,
            "trend": trend,
            "consecutive": consecutive,
        }

    result = {}
    fg = _analyze_series(fg_values)
    if fg:
        result["foreigner"] = fg
    inst = _analyze_series(inst_values)
    if inst:
        result["institution"] = inst
    indiv = _analyze_series(individual_values)
    if indiv:
        result["individual"] = indiv

    return result if result else None


def classify_supply_demand(investor_data: dict) -> str:
    """수급 종합 판단"""
    if not investor_data:
        return "수급 데이터 없음"

    signals = []
    fg = investor_data.get("foreigner")
    inst = investor_data.get("institution")

    if fg:
        if fg["consecutive"] >= 3:
            signals.append(f"외국인 {fg['consecutive']}일 연속 순매수")
        elif fg["consecutive"] <= -3:
            signals.append(f"외국인 {abs(fg['consecutive'])}일 연속 순매도")

    if inst:
        if inst["consecutive"] >= 3:
            signals.append(f"기관 {inst['consecutive']}일 연속 순매수")
        elif inst["consecutive"] <= -3:
            signals.append(f"기관 {abs(inst['consecutive'])}일 연속 순매도")

    if not signals:
        if fg and inst:
            if fg["trend"] == "순매수" and inst["trend"] == "순매수":
                return "외국인+기관 매수 우위"
            elif fg["trend"] == "순매도" and inst["trend"] == "순매도":
                return "외국인+기관 매도 우위"
            else:
                return "수급 엇갈림"
        return "수급 보통"

    return " / ".join(signals)


# =============================================================
# 52주 고저
# =============================================================

def calc_52week_position(current_price: int, high_52w: int, low_52w: int) -> dict:
    """52주 신고가/신저가 대비 현재 위치"""
    if not high_52w or not low_52w:
        return {"high": None, "low": None, "position_pct": None}

    range_val = high_52w - low_52w
    position_pct = round((current_price - low_52w) / range_val * 100, 1) if range_val > 0 else 50

    return {
        "high": high_52w,
        "low": low_52w,
        "current": current_price,
        "position_pct": position_pct,
    }


# =============================================================
# DART 공시 피드
# =============================================================

@st.cache_data(ttl=600)
def get_dart_disclosures(corp_code: str = None, ticker: str = None, count: int = 5) -> list:
    """DART OpenAPI 최근 공시 목록 조회"""
    dart_api_key = st.secrets.get("DART_API_KEY", "")
    if not dart_api_key:
        return []

    # ticker → corp_code 변환이 필요한 경우
    if not corp_code and ticker:
        corp_code = _get_dart_corp_code(ticker, dart_api_key)
        if not corp_code:
            return []

    url = (
        f"https://opendart.fss.or.kr/api/list.json"
        f"?crtfc_key={dart_api_key}"
        f"&corp_code={corp_code}"
        f"&page_count={count}"
        f"&sort=date&sort_mth=desc"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10, context=_SSL_CTX)
        data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    if data.get("status") != "000":
        return []

    disclosures = []
    for item in data.get("list", [])[:count]:
        rcept_no = item.get("rcept_no", "")
        disclosures.append({
            "title": item.get("report_nm", ""),
            "date": item.get("rcept_dt", ""),
            "reporter": item.get("flr_nm", ""),
            "link": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else "",
        })

    return disclosures


@st.cache_data(ttl=86400)
def _get_dart_corp_code(ticker: str, dart_api_key: str) -> str:
    """종목코드 → DART 고유번호 변환"""
    import zipfile
    import io
    import xml.etree.ElementTree as ET

    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={dart_api_key}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=30, context=_SSL_CTX)
        zip_data = resp.read()

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            xml_name = zf.namelist()[0]
            with zf.open(xml_name) as f:
                tree = ET.parse(f)
                root = tree.getroot()

                for corp in root.findall("list"):
                    stock_code = corp.findtext("stock_code", "").strip()
                    if stock_code == ticker:
                        return corp.findtext("corp_code", "").strip()
    except Exception:
        pass

    return None


# =============================================================
# 네이버 뉴스 피드
# =============================================================

@st.cache_data(ttl=600)
def get_stock_news(ticker: str, count: int = 5) -> list:
    """네이버 금융 종목 뉴스 조회"""
    url = f"https://m.stock.naver.com/api/news/stock/{ticker}?pageSize={count}"
    data = _fetch_naver_api(url)

    if not data:
        return []

    articles = data if isinstance(data, list) else data.get("items", data.get("news", []))

    news_list = []
    for item in articles[:count]:
        title = item.get("title", item.get("articleTitle", ""))
        link = item.get("link", item.get("url", ""))
        date = item.get("datetime", item.get("publishedAt", item.get("date", "")))
        source = item.get("officeName", item.get("source", ""))

        if title:
            # HTML 태그 제거
            title = re.sub(r"<[^>]+>", "", title)
            news_list.append({
                "title": title,
                "link": link,
                "date": date[:10] if date else "",
                "source": source,
            })

    return news_list


# =============================================================
# 업종 평균 PER/PBR 비교
# =============================================================

@st.cache_data(ttl=3600)
def get_sector_valuation(ticker: str) -> dict:
    """동일 업종 평균 PER/PBR 조회 (네이버 금융)"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/industry"
    data = _fetch_naver_api(url)

    if not data:
        return None

    sector_name = data.get("industryName", data.get("sectorName", ""))
    sector_per = _parse_number(str(data.get("industryPer", data.get("sectorPer", ""))))
    sector_pbr = _parse_number(str(data.get("industryPbr", data.get("sectorPbr", ""))))

    if not sector_name and not sector_per:
        # 대체 경로 시도
        url2 = f"https://m.stock.naver.com/api/stock/{ticker}/basic"
        data2 = _fetch_naver_api(url2)
        if data2:
            sector_name = data2.get("industryName", "")
            sector_per = _parse_number(str(data2.get("industryPer", "")))
            sector_pbr = _parse_number(str(data2.get("industryPbr", "")))

    return {
        "sector_name": sector_name,
        "sector_per": round(sector_per, 2) if sector_per else None,
        "sector_pbr": round(sector_pbr, 2) if sector_pbr else None,
    }


def compare_sector_valuation(per: float, pbr: float, sector: dict) -> dict:
    """업종 평균 대비 저평가/고평가 판단"""
    if not sector:
        return {"classification": "업종 데이터 없음"}

    result = {
        "sector_name": sector.get("sector_name", ""),
        "sector_per": sector.get("sector_per"),
        "sector_pbr": sector.get("sector_pbr"),
        "signals": [],
    }

    if per and sector.get("sector_per") and sector["sector_per"] > 0:
        ratio = per / sector["sector_per"]
        if ratio < 0.7:
            result["signals"].append(f"PER 업종 대비 {(1 - ratio) * 100:.0f}% 저평가")
        elif ratio > 1.3:
            result["signals"].append(f"PER 업종 대비 {(ratio - 1) * 100:.0f}% 고평가")
        else:
            result["signals"].append("PER 업종 평균 수준")
        result["per_ratio"] = round(ratio, 2)

    if pbr and sector.get("sector_pbr") and sector["sector_pbr"] > 0:
        ratio = pbr / sector["sector_pbr"]
        if ratio < 0.7:
            result["signals"].append(f"PBR 업종 대비 {(1 - ratio) * 100:.0f}% 저평가")
        elif ratio > 1.3:
            result["signals"].append(f"PBR 업종 대비 {(ratio - 1) * 100:.0f}% 고평가")
        else:
            result["signals"].append("PBR 업종 평균 수준")
        result["pbr_ratio"] = round(ratio, 2)

    result["classification"] = " / ".join(result["signals"]) if result["signals"] else "비교 불가"
    return result


# =============================================================
# 전체 펀더멘털 분석
# =============================================================

# =============================================================
# 간이 DCF 밸류에이션
# =============================================================

def calc_simple_dcf(eps: float, growth_rate: float = None, discount_rate: float = 0.10,
                    terminal_growth: float = 0.03, years: int = 5) -> dict:
    """간이 DCF (EPS 기반 할인현금흐름)

    3단계 시나리오: 낙관/중립/비관
    - 낙관: 성장률 그대로
    - 중립: 성장률 * 0.7
    - 비관: 성장률 * 0.4
    """
    if not eps or eps <= 0:
        return None
    if growth_rate is None:
        growth_rate = 0.10  # 기본 10%

    # 음수 성장률이면 DCF 부적합
    if growth_rate <= -0.5:
        return None

    scenarios = {
        "optimistic": growth_rate,
        "neutral": growth_rate * 0.7,
        "pessimistic": growth_rate * 0.4,
    }
    labels = {"optimistic": "낙관", "neutral": "중립", "pessimistic": "비관"}

    result = {}
    for key, g in scenarios.items():
        # 향후 N년 EPS 예측 → 현재가치 할인
        dcf_sum = 0
        projected_eps = eps
        for y in range(1, years + 1):
            projected_eps *= (1 + g)
            dcf_sum += projected_eps / ((1 + discount_rate) ** y)

        # 잔존가치 (터미널 밸류)
        terminal_eps = projected_eps * (1 + terminal_growth)
        terminal_value = terminal_eps / (discount_rate - terminal_growth)
        terminal_pv = terminal_value / ((1 + discount_rate) ** years)

        fair_value = round(dcf_sum + terminal_pv)
        result[key] = {
            "label": labels[key],
            "growth_rate": round(g * 100, 1),
            "fair_value": fair_value,
        }

    return result


def analyze_fundamental(ticker: str, df: pd.DataFrame, current_price: int) -> dict:
    """종목의 전체 펀더멘털 분석"""
    fund = get_fundamental_data(ticker)

    # S-RIM
    roe = None
    if fund["per"] and fund["pbr"] and fund["per"] > 0:
        roe = fund["pbr"] / fund["per"]  # ROE ≈ PBR/PER
    srim = calc_srim(fund.get("bps"), roe)

    # PEG 비율
    earnings_growth = _estimate_earnings_growth(ticker)
    peg_data = calc_peg(fund["per"], earnings_growth)

    # 밸류에이션 분류
    val_class = classify_valuation(fund["per"], fund["pbr"], current_price, srim)

    # 수급
    investor = get_investor_trading(ticker)
    supply_class = classify_supply_demand(investor)

    # 52주 위치 (네이버 API 데이터 우선, 없으면 df에서)
    high_52w = fund.get("high_52w")
    low_52w = fund.get("low_52w")
    if not high_52w or not low_52w:
        close = df["종가"]
        high_52w = int(close.max()) if len(close) >= 5 else None
        low_52w = int(close.min()) if len(close) >= 5 else None
    week52 = calc_52week_position(current_price, high_52w, low_52w)

    # 뉴스 피드
    news = get_stock_news(ticker)

    # DART 공시
    dart_disclosures = get_dart_disclosures(ticker=ticker)

    # 업종 평균 비교
    sector_val = get_sector_valuation(ticker)
    sector_comp = compare_sector_valuation(fund["per"], fund["pbr"], sector_val)

    return {
        "per": fund["per"],
        "pbr": fund["pbr"],
        "eps": fund["eps"],
        "bps": fund["bps"],
        "div_yield": fund["div_yield"],
        "roe": round(roe * 100, 2) if roe else None,
        "peg": peg_data,
        "srim": srim,
        "valuation_class": val_class,
        "investor": investor,
        "supply_class": supply_class,
        "week52": week52,
        "news": news,
        "dart": dart_disclosures,
        "sector_comparison": sector_comp,
    }
