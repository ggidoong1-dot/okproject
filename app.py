# © 2026 donghapro. All Rights Reserved.
# Unauthorized copying or distribution is strictly prohibited.

import streamlit as st
import pandas as pd
import re
import hashlib
import hmac
from datetime import datetime, timedelta
from pykrx import stock as pykrx_stock
import yfinance as yf
import json
import time
from indicators import calc_all_indicators
from charts import create_stock_chart
from portfolio import (
    calc_portfolio_summary, create_weight_chart, create_profit_bar_chart,
    calc_mdd, calc_sharpe_ratio, calc_correlation_matrix,
    create_correlation_heatmap, calc_kelly_criterion, calc_breakeven,
    suggest_rebalancing, analyze_sector_diversification,
    calc_portfolio_level_analysis,
)
from fundamental import analyze_fundamental, classify_valuation, calc_srim, calc_simple_dcf
from telegram_alert import check_alerts, send_alerts
from strategies import check_minervini, check_canslim, check_turtle, calc_scorecard
from econews_bridge import get_news_for_stock, format_news_for_ai
from data_store import (
    save_daily_ohlcv, save_price_snapshot, get_db_stats,
    needs_backfill,
    analyze_day_of_week_pattern, analyze_monthly_pattern,
    analyze_intraday_pattern, analyze_time_snapshot_pattern,
)

# --- 페이지 설정 ---
st.set_page_config(
    page_title="Stock Memory",
    page_icon="🔍",
    layout="wide",
)

# --- OG 메타 태그 (카카오톡 공유용) ---
# OG_IMAGE_URL을 실제 배포 URL로 변경하세요
OG_IMAGE_URL = "https://raw.githubusercontent.com/ggidoong1-dot/okproject/main/static/og_image.png"
st.markdown(f"""
<meta property="og:title" content="오크밸리 - 주식 분석 & 포트폴리오" />
<meta property="og:description" content="기술적 지표 · 전략 스코어 · AI 진단" />
<meta property="og:image" content="{OG_IMAGE_URL}" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta property="og:type" content="website" />
""", unsafe_allow_html=True)

# --- 전역 폰트 크기 +2pt ---
st.markdown("""
<style>
html, body, [class*="css"] {
    font-size: 16px !important;
}
h1 { font-size: 2.2rem !important; }
h2 { font-size: 1.8rem !important; }
h3 { font-size: 1.5rem !important; }
h4 { font-size: 1.25rem !important; }
p, li, td, th, span, label, div, input, textarea, select, button {
    font-size: 16px !important;
}
.stMetricValue { font-size: 1.6rem !important; }
.stMetricLabel { font-size: 0.95rem !important; }
.stCaption p { font-size: 14px !important; }
</style>
""", unsafe_allow_html=True)

# =============================================================
# 인증 (로그인 벽)
# =============================================================

def _sanitize_html(text: str) -> str:
    """HTML 태그 제거 (XSS 방어)"""
    if not isinstance(text, str):
        return str(text)
    return re.sub(r"<(?!/?(?:span|b|strong|em|br)\b)[^>]+>", "", text)


def _safe_markdown(text: str, **kwargs):
    """안전한 마크다운 렌더링 (script/iframe 등 위험 태그 제거)"""
    sanitized = _sanitize_html(text)
    st.markdown(sanitized, **kwargs)


# 로그인 시도 제한용
if "login_attempts" not in st.session_state:
    st.session_state.login_attempts = 0
if "login_locked_until" not in st.session_state:
    st.session_state.login_locked_until = None

# Gemini API 호출 제한 추적
if "gemini_call_times" not in st.session_state:
    st.session_state.gemini_call_times = []  # 최근 호출 타임스탬프 목록


def check_auth() -> bool:
    """아이디/비밀번호 기반 인증 (brute-force 방어 포함)"""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.markdown("## Stock Memory")
    st.markdown("접근 권한이 필요합니다.")

    # brute-force 잠금 체크
    if st.session_state.login_locked_until:
        remaining = (st.session_state.login_locked_until - datetime.now()).total_seconds()
        if remaining > 0:
            st.error(f"로그인 시도 초과. {int(remaining)}초 후 다시 시도해주세요.")
            return False
        else:
            st.session_state.login_locked_until = None
            st.session_state.login_attempts = 0

    correct_id = st.secrets.get("APP_USERNAME", "")
    correct_pw = st.secrets.get("APP_PASSWORD", "")

    if not correct_id or not correct_pw:
        st.error("secrets.toml에 APP_USERNAME/APP_PASSWORD를 설정해주세요.")
        return False

    username = st.text_input("아이디")
    password = st.text_input("비밀번호", type="password")
    if st.button("로그인", type="primary"):
        # 상수 시간 비교 (타이밍 공격 방어)
        id_match = hmac.compare_digest(username, correct_id)
        pw_match = hmac.compare_digest(password, correct_pw)

        if id_match and pw_match:
            st.session_state.authenticated = True
            st.session_state.login_attempts = 0
            st.rerun()
        else:
            st.session_state.login_attempts += 1
            remaining = 5 - st.session_state.login_attempts
            if st.session_state.login_attempts >= 5:
                st.session_state.login_locked_until = datetime.now() + timedelta(minutes=5)
                st.error("5회 실패. 5분간 잠금됩니다.")
            else:
                st.error(f"아이디 또는 비밀번호가 틀렸습니다. (남은 시도: {remaining}회)")

    st.caption("© 2026 donghapro. All Rights Reserved. 무단 복제 및 배포를 금지합니다.")
    return False


# --- 인증 체크 (로컬 개발 중 비활성화) ---
# if not check_auth():
#     st.stop()

# --- 세션 스테이트 초기화 ---
if "portfolio" not in st.session_state:
    st.session_state.portfolio = []
if "analysis_results" not in st.session_state:
    st.session_state.analysis_results = []
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "expand_all" not in st.session_state:
    st.session_state.expand_all = True


# =============================================================
# 한국/해외 자동 구분
# =============================================================

def is_korean_stock(ticker: str) -> bool:
    """종목코드가 한국 주식인지 판별 (숫자 6자리 = 한국)"""
    return ticker.strip().isdigit() and len(ticker.strip()) == 6


# =============================================================
# 데이터 수집 함수
# =============================================================

@st.cache_data(ttl=300)
def get_stock_name(ticker: str) -> str:
    """종목코드로 종목명 조회"""
    if is_korean_stock(ticker):
        try:
            name = pykrx_stock.get_market_ticker_name(ticker)
            return name if name else ticker
        except Exception:
            return ticker
    else:
        try:
            t = yf.Ticker(ticker)
            name = t.info.get("shortName") or t.info.get("longName") or ticker
            return name
        except Exception:
            return ticker


@st.cache_data(ttl=300)
def get_stock_data(ticker: str, days: int = 120) -> pd.DataFrame:
    """종목의 최근 N일 OHLCV 데이터 조회 (한국/해외 자동)"""
    if is_korean_stock(ticker):
        return _get_kr_stock_data(ticker, days)
    else:
        return _get_global_stock_data(ticker, days)


def _get_kr_stock_data(ticker: str, days: int) -> pd.DataFrame:
    """한국 주식 OHLCV (pykrx)"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    try:
        df = pykrx_stock.get_market_ohlcv_by_date(start, end, ticker)
        if df.empty:
            return pd.DataFrame()
        return df.tail(days)
    except Exception:
        return pd.DataFrame()


def _get_global_stock_data(ticker: str, days: int) -> pd.DataFrame:
    """해외 주식 OHLCV (yfinance) → 한국 주식과 동일한 컬럼명으로 변환"""
    try:
        t = yf.Ticker(ticker)
        period = "6mo" if days <= 120 else "1y"
        df = t.history(period=period)
        if df.empty:
            return pd.DataFrame()

        # 컬럼명 통일 (한국 형식으로)
        df = df.rename(columns={
            "Open": "시가",
            "High": "고가",
            "Low": "저가",
            "Close": "종가",
            "Volume": "거래량",
        })
        df = df[["시가", "고가", "저가", "종가", "거래량"]]

        # 소수점 주가 → 반올림
        for col in ["시가", "고가", "저가", "종가"]:
            df[col] = df[col].round(2)
        df["거래량"] = df["거래량"].astype(int)

        # timezone 제거
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        return df.tail(days)
    except Exception:
        return pd.DataFrame()


def calc_moving_averages(df: pd.DataFrame) -> dict:
    """이동평균선 계산 (5, 10, 20, 50일)"""
    close = df["종가"]
    mas = {}
    for period in [5, 10, 20, 50]:
        if len(close) >= period:
            mas[period] = round(close.rolling(period).mean().iloc[-1], 2)
        else:
            mas[period] = None
    return mas


def calc_volume_averages(df: pd.DataFrame) -> dict:
    """거래량 평균 계산 (현재, 10, 30, 50일)"""
    vol = df["거래량"]
    vols = {"현재": int(vol.iloc[-1]) if len(vol) > 0 else None}
    for period in [10, 30, 50]:
        if len(vol) >= period:
            vols[period] = round(vol.tail(period).mean())
        else:
            vols[period] = None
    return vols


# =============================================================
# 분류 로직
# =============================================================

def classify_ma(current_price: int, mas: dict) -> tuple:
    """이평 배열 분류"""
    values = {"현재가": current_price}
    for k, v in mas.items():
        if v is not None:
            values[f"이평({k})"] = v

    sorted_items = sorted(values.items(), key=lambda x: x[1], reverse=True)
    arrangement = " > ".join([item[0] for item in sorted_items])

    keys_order = [item[0] for item in sorted_items]

    # 정배열: 현재가 > 이평5 > 이평10 > 이평20 > 이평50
    perfect_bull = ["현재가", "이평(5)", "이평(10)", "이평(20)", "이평(50)"]
    # 역배열: 이평50 > 이평20 > 이평10 > 이평5 > 현재가
    perfect_bear = ["이평(50)", "이평(20)", "이평(10)", "이평(5)", "현재가"]

    if keys_order == perfect_bull:
        classification = "[정배열] 강한 상승 추세"
    elif keys_order == perfect_bear:
        classification = "[역배열] 강한 하락 추세"
    else:
        # 부분 정배열/역배열 판단
        bull_score = 0
        if "현재가" in keys_order and keys_order.index("현재가") <= 1:
            bull_score += 1
        if "이평(50)" in keys_order and keys_order.index("이평(50)") >= len(keys_order) - 2:
            bull_score += 1
        if "이평(5)" in keys_order and "이평(20)" in keys_order:
            if keys_order.index("이평(5)") < keys_order.index("이평(20)"):
                bull_score += 1

        if bull_score >= 2:
            classification = "[혼조세] 정배열 전환 초입"
        elif bull_score == 0:
            classification = "[혼조세] 역배열 전환 초입"
        else:
            classification = "[혼조세] 방향성 탐색 구간"

    return arrangement, classification


def classify_volume(vols: dict) -> tuple:
    """거래량 배열 분류"""
    labels = {
        "거래량(현재)": vols.get("현재"),
        "거래량(10)": vols.get(10),
        "거래량(30)": vols.get(30),
        "거래량(50)": vols.get(50),
    }
    valid = {k: v for k, v in labels.items() if v is not None}

    if not valid:
        return "데이터 부족", "분류 불가"

    sorted_items = sorted(valid.items(), key=lambda x: x[1], reverse=True)
    arrangement = " > ".join([item[0] for item in sorted_items])

    current = vols.get("현재", 0)
    avg10 = vols.get(10, 0)
    avg30 = vols.get(30, 0)
    avg50 = vols.get(50, 0)

    if current and avg10 and avg30 and avg50:
        if current > avg10 and current > avg30 and current > avg50:
            classification = "거래량 폭증 (과열/돌파 가능)"
        elif avg10 > avg30 > avg50 > current:
            classification = "단기 과열 후 휴식 (관망)"
        elif current > avg50 and avg10 > avg50:
            classification = "거래량 훈조 (추세 탐색)"
        elif avg30 > avg10 > current:
            classification = "거래량 감소 추세"
        else:
            classification = "거래량 혼조 (추세 탐색)"
    else:
        classification = "데이터 부족"

    return arrangement, classification


def classify_overall(ma_class: str, vol_class: str) -> str:
    """종합 분류"""
    if "정배열" in ma_class and ("폭증" in vol_class or "훈조" in vol_class):
        return "[매수 고려] 상승 추세 + 거래량 뒷받침"
    elif "역배열" in ma_class and "감소" in vol_class:
        return "[매도 고려] 하락 추세 + 거래량 이탈"
    elif "정배열" in ma_class:
        return "[보유] 상승 추세 유지 중"
    elif "역배열" in ma_class:
        return "[주의] 하락 추세 진행 중"
    else:
        return "[관망] 확실한 신호 대기"


# =============================================================
# 벤치마크 대비 상대 수익률 (알파)
# =============================================================

@st.cache_data(ttl=3600)
def _calc_benchmark_alpha(ticker: str, avg_price: float, current_price: float, market: str) -> dict:
    """벤치마크(S&P500/KOSPI) 대비 초과 수익률(알파) 계산

    매입가 기준 동일 기간 벤치마크 수익률과 비교.
    """
    benchmark_ticker = "^KS11" if market == "KR" else "^GSPC"
    benchmark_name = "KOSPI" if market == "KR" else "S&P500"

    try:
        # 종목의 과거 데이터로 매입 시점 추정 (평균단가에 가장 가까운 날짜)
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
        if hist.empty or avg_price <= 0:
            return None

        # 평균단가와 가장 가까운 날짜 찾기
        hist["diff"] = (hist["Close"] - avg_price).abs()
        buy_date = hist["diff"].idxmin()

        # 벤치마크 동일 기간 수익률
        bench = yf.download(benchmark_ticker, start=buy_date.strftime("%Y-%m-%d"), progress=False)
        if bench.empty or len(bench) < 2:
            return None

        # 멀티레벨 컬럼 처리
        if isinstance(bench.columns, pd.MultiIndex):
            bench_close = bench["Close"].iloc[:, 0]
        else:
            bench_close = bench["Close"]

        bench_start = float(bench_close.iloc[0])
        bench_end = float(bench_close.iloc[-1])
        if bench_start <= 0:
            return None

        benchmark_return = round((bench_end / bench_start - 1) * 100, 2)
        stock_return = round((current_price / avg_price - 1) * 100, 2)
        alpha = round(stock_return - benchmark_return, 2)

        return {
            "benchmark_ticker": benchmark_ticker,
            "benchmark_name": benchmark_name,
            "benchmark_return": benchmark_return,
            "stock_return": stock_return,
            "alpha": alpha,
            "buy_date_est": buy_date.strftime("%Y-%m-%d"),
        }
    except Exception:
        return None


# =============================================================
# 종목 분석 실행
# =============================================================

@st.cache_data(ttl=600)
def _get_yf_info(ticker: str) -> dict:
    """yfinance 종목 정보 캐시"""
    try:
        return yf.Ticker(ticker).info
    except Exception:
        return {}


def _analyze_fundamental_global(ticker: str, df: pd.DataFrame, current_price: float) -> dict:
    """해외 주식 펀더멘털 분석 (yfinance)"""
    info = _get_yf_info(ticker)

    per = round(info.get("trailingPE") or 0, 2) or None
    pbr = round(info.get("priceToBook") or 0, 2) or None
    eps = round(info.get("trailingEps") or 0, 2) or None
    bps = round(info.get("bookValue") or 0, 2) or None
    div_yield = round((info.get("dividendYield") or 0) * 100, 2) or None
    high_52w = info.get("fiftyTwoWeekHigh")
    low_52w = info.get("fiftyTwoWeekLow")

    # 성장주 밸류에이션용 추가 지표
    psr = round(info.get("priceToSalesTrailing12Months") or 0, 2) or None
    ev_ebitda = round(info.get("enterpriseToEbitda") or 0, 2) or None
    payout_ratio = info.get("payoutRatio")
    if payout_ratio is not None:
        payout_ratio = round(payout_ratio * 100, 1)
    else:
        payout_ratio = None

    # ROE
    roe = None
    if per and pbr and per > 0:
        roe = pbr / per

    # S-RIM
    srim = calc_srim(int(bps) if bps else None, roe)

    # 밸류에이션 분류
    val_class = classify_valuation(per, pbr, current_price, srim)

    # 간이 DCF
    earnings_growth = info.get("earningsGrowth") or info.get("revenueGrowth")
    dcf_data = calc_simple_dcf(eps, earnings_growth) if eps and eps > 0 else None

    # 52주 위치
    position_pct = None
    if high_52w and low_52w and high_52w > low_52w:
        position_pct = round((current_price - low_52w) / (high_52w - low_52w) * 100, 1)

    return {
        "per": per,
        "pbr": pbr,
        "eps": eps,
        "bps": int(bps) if bps else None,
        "div_yield": div_yield,
        "roe": round(roe * 100, 2) if roe else None,
        "psr": psr,
        "ev_ebitda": ev_ebitda,
        "payout_ratio": payout_ratio,
        "srim": srim,
        "dcf": dcf_data,
        "valuation_class": val_class,
        "investor": None,  # 해외는 수급 데이터 없음
        "supply_class": "해외 주식은 수급 데이터 미제공",
        "week52": {
            "high": int(high_52w) if high_52w else None,
            "low": int(low_52w) if low_52w else None,
            "current": round(current_price, 2),
            "position_pct": position_pct,
        },
    }


def analyze_stock(ticker: str, avg_price: float, quantity: int) -> dict:
    """단일 종목 전체 분석"""
    name = get_stock_name(ticker)
    df = get_stock_data(ticker)

    error_result = {"name": name, "ticker": ticker}

    if df.empty:
        error_result["error"] = "데이터 조회 실패"
        return error_result

    # DataFrame 컬럼 검증
    required_cols = ["종가", "고가", "저가", "시가", "거래량"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        error_result["error"] = f"필수 컬럼 누락: {', '.join(missing_cols)}"
        return error_result

    if len(df) < 5:
        error_result["error"] = f"데이터 부족 ({len(df)}일분)"
        return error_result

    kr = is_korean_stock(ticker)
    try:
        current_price = round(float(df["종가"].iloc[-1]), 2)
    except (ValueError, IndexError):
        error_result["error"] = "현재가 파싱 실패"
        return error_result

    if kr:
        current_price = int(current_price)
    profit_rate = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0

    mas = calc_moving_averages(df)
    vols = calc_volume_averages(df)

    ma_arrangement, ma_class = classify_ma(current_price, mas)
    vol_arrangement, vol_class = classify_volume(vols)
    overall = classify_overall(ma_class, vol_class)

    # 2단계: 기술적 지표 계산 (ma_class 전달로 충돌 해석 포함)
    tech_indicators = calc_all_indicators(df, ma_class)

    # 4단계: 펀더멘털 분석
    if kr:
        fund_data = analyze_fundamental(ticker, df, current_price)
    else:
        fund_data = _analyze_fundamental_global(ticker, df, current_price)

    # 5단계: 전략 시그널
    minervini = check_minervini(df, current_price)
    canslim = check_canslim(df, fund_data, fund_data.get("investor"))
    turtle = check_turtle(df, current_price)

    # 결과 딕셔너리 먼저 구성 (스코어카드 계산에 필요)
    ticker_display = f"KRX:{ticker}" if kr else ticker
    market = "KR" if kr else "US"
    result = {
        "name": name,
        "ticker": ticker_display,
        "ticker_raw": ticker,
        "market": market,
        "current_price": current_price,
        "avg_price": round(avg_price),
        "quantity": quantity,
        "profit_rate": round(profit_rate, 2),
        "ma": mas,
        "ma_arrangement": ma_arrangement,
        "ma_classification": ma_class,
        "vol": vols,
        "vol_arrangement": vol_arrangement,
        "vol_classification": vol_class,
        "overall": overall,
        "indicators": tech_indicators,
        "fundamental": fund_data,
        "minervini": minervini,
        "canslim": canslim,
        "turtle": turtle,
        "df": df,
    }

    # 데이터 축적 (접속할 때마다 자동 저장)
    try:
        # 첫 접속 시 3년치 일봉 한번에 백필
        if needs_backfill(ticker):
            df_backfill = get_stock_data(ticker, days=750)
            save_daily_ohlcv(ticker, df_backfill)
        else:
            save_daily_ohlcv(ticker, df)
        vol_now = int(df["거래량"].iloc[-1]) if len(df) > 0 else 0
        save_price_snapshot(ticker, name, current_price, vol_now)
    except Exception:
        pass

    # 글로벌 뉴스 조회
    try:
        result["global_news"] = get_news_for_stock(ticker, name)
    except Exception:
        result["global_news"] = {"available": False, "direct": [], "sector": [], "sentiment_summary": {}}

    # 뉴스 감성 점수 (스코어카드용)
    result["news_sentiment_score"] = result["global_news"].get("sentiment_summary", {}).get("score", 50)

    # 벤치마크 대비 알파
    try:
        result["benchmark"] = _calc_benchmark_alpha(
            ticker, avg_price, current_price, market
        )
    except Exception:
        result["benchmark"] = None

    # 종합 스코어카드
    result["scorecard"] = calc_scorecard(result)

    return result


# =============================================================
# UI 렌더링
# =============================================================

def render_stock_table(result: dict):
    """종목 분석 결과를 key-value 테이블로 렌더링"""
    if "error" in result:
        st.error(f"{result['name']}: {result['error']}")
        return

    profit_color = "red" if result["profit_rate"] < 0 else "green" if result["profit_rate"] > 0 else "white"
    kr = result.get("market") == "KR"
    currency = "원" if kr else "$"

    def fmt_price(val):
        if val is None:
            return "N/A"
        if kr:
            return f"{int(val):,}"
        return f"{val:,.2f}"

    rows = [
        (result["name"], result["ticker"]),
        ("현재가", f"{fmt_price(result['current_price'])}{currency}"),
        ("평균단가", f"{fmt_price(result['avg_price'])}{currency}"),
        ("수량", f"{result['quantity']}"),
        ("수익률", f"{result['profit_rate']}%"),
    ]

    # 벤치마크 대비 알파
    bench = result.get("benchmark")
    if bench:
        alpha_sign = "+" if bench["alpha"] >= 0 else ""
        rows.append((
            f"vs {bench['benchmark_name']}",
            f"알파 {alpha_sign}{bench['alpha']}%p  (종목 {bench['stock_return']}% vs 지수 {bench['benchmark_return']}%)"
        ))

    # 이평선
    for period in [5, 10, 20, 50]:
        val = result["ma"].get(period)
        rows.append((f"이평({period})", f"{fmt_price(val)}" if val else "N/A"))
    rows.append(("이평 배열", result["ma_arrangement"]))
    rows.append(("이평 분류", result["ma_classification"]))

    # 거래량
    for key, label in [("현재", "거래량(현재)"), (10, "거래량(10)"), (30, "거래량(30)"), (50, "거래량(50)")]:
        val = result["vol"].get(key)
        rows.append((label, f"{val:,}" if val else "N/A"))
    rows.append(("거래량 배열", result["vol_arrangement"]))
    rows.append(("거래량 분류", result["vol_classification"]))

    rows.append(("종합 분류", result["overall"]))

    # 테이블 렌더링 (HTML)
    html = '<table style="width:100%; border-collapse:collapse;">'
    html += '<tr style="border-bottom:1px solid #333;"><th style="text-align:left;padding:8px;color:#888;width:30%;">key</th><th style="text-align:left;padding:8px;color:#888;">value</th></tr>'

    for key, value in rows:
        style = ""
        if key == "평균단가":
            style = 'style="color:red;"'
        elif key == "수익률":
            style = f'style="color:{profit_color};"'
        elif key.startswith("vs "):
            bench_data = result.get("benchmark")
            if bench_data:
                a_color = "#00ff88" if bench_data["alpha"] >= 0 else "#ff4444"
                style = f'style="color:{a_color};"'
        elif key in ("이평 분류", "거래량 분류", "종합 분류"):
            if "매수" in str(value) or "정배열" in str(value) or "상승" in str(value):
                style = 'style="color:#00ff88;"'
            elif "매도" in str(value) or "역배열" in str(value) or "하락" in str(value):
                style = 'style="color:#ff4444;"'
            elif "관망" in str(value) or "혼조" in str(value):
                style = 'style="color:#ffaa00;"'

        key_style = ""
        if key in ("평균단가", "수익률"):
            key_style = 'style="color:red;"'

        safe_key = _sanitize_html(str(key))
        safe_value = _sanitize_html(str(value))
        html += f'<tr style="border-bottom:1px solid #222;"><td style="padding:8px;" {key_style}>{safe_key}</td><td style="padding:8px;" {style}>{safe_value}</td></tr>'

    html += '</table>'
    st.markdown(html, unsafe_allow_html=True)


def render_portfolio_dashboard(results: list):
    """3단계: 포트폴리오 대시보드 렌더링"""
    summary = calc_portfolio_summary(results)
    if summary["count"] == 0:
        return

    st.markdown("## 포트폴리오 대시보드")

    # 요약 카드 (4열)
    col1, col2, col3, col4 = st.columns(4)

    profit_color = "#00ff88" if summary["total_profit"] >= 0 else "#ff4444"
    with col1:
        st.metric("총 투자금", f"{summary['total_invested']:,.0f}원")
    with col2:
        st.metric("총 평가금", f"{summary['total_value']:,.0f}원")
    with col3:
        st.metric(
            "총 손익",
            f"{summary['total_profit']:,.0f}원",
            delta=f"{summary['total_profit_rate']}%",
        )
    with col4:
        st.metric("보유 종목", f"{summary['count']}개")

    # 차트 (2열: 비중 파이 + 수익률 바)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 종목별 비중")
        fig = create_weight_chart(summary["holdings"])
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.markdown("#### 종목별 수익률")
        fig = create_profit_bar_chart(summary["holdings"])
        st.plotly_chart(fig, use_container_width=True)

    # 리스크 분석 (Expander)
    with st.expander("📊 리스크 분석", expanded=False):
        risk_tab1, risk_tab2, risk_tab3, risk_tab4, risk_tab5, risk_tab6 = st.tabs(
            ["MDD/샤프", "상관계수", "켈리 공식", "리밸런싱", "섹터 분산", "포트폴리오 건강"]
        )

        with risk_tab1:
            for r in results:
                if "error" in r or "df" not in r:
                    continue
                mdd_data = calc_mdd(r["df"])
                sharpe = calc_sharpe_ratio(r["df"])
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown(f"**{r['name']}**")
                with col2:
                    mdd_color = "#ff4444" if mdd_data["mdd"] < -20 else "#ffaa00" if mdd_data["mdd"] < -10 else "#00ff88"
                    st.markdown(f"MDD: <span style='color:{mdd_color}'>{mdd_data['mdd']}%</span>", unsafe_allow_html=True)
                with col3:
                    if sharpe is not None:
                        sharpe_color = "#00ff88" if sharpe > 1 else "#ffaa00" if sharpe > 0 else "#ff4444"
                        st.markdown(f"샤프: <span style='color:{sharpe_color}'>{sharpe}</span>", unsafe_allow_html=True)
                    else:
                        st.markdown("샤프: N/A")

        with risk_tab2:
            corr_matrix, _ = calc_correlation_matrix(results)
            if corr_matrix is not None:
                fig = create_correlation_heatmap(corr_matrix)
                st.plotly_chart(fig, use_container_width=True)
                # 높은 상관관계 경고
                for i in range(len(corr_matrix)):
                    for j in range(i + 1, len(corr_matrix)):
                        val = corr_matrix.iloc[i, j]
                        if val > 0.8:
                            st.warning(
                                f"⚠️ {corr_matrix.index[i]}와 {corr_matrix.columns[j]}의 "
                                f"상관계수가 {val:.2f}로 높습니다. 분산 효과가 제한적입니다."
                            )
            else:
                st.info("상관계수 분석에는 2개 이상 종목이 필요합니다.")

        with risk_tab3:
            for r in results:
                if "error" in r or "df" not in r:
                    continue
                kelly = calc_kelly_criterion(r["df"])
                if kelly["kelly"] is not None:
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.markdown(f"**{r['name']}**")
                    with col2:
                        st.markdown(f"승률: `{kelly['win_rate']}%`")
                    with col3:
                        st.markdown(f"켈리: `{kelly['kelly']}%`")
                    with col4:
                        st.markdown(f"Half-Kelly: `{kelly['half_kelly']}%`")

        with risk_tab4:
            suggestions = suggest_rebalancing(summary["holdings"])
            if suggestions:
                for s in suggestions:
                    color = "#ff4444" if s["severity"] == "high" else "#ffaa00"
                    st.markdown(
                        f"<span style='color:{color}'>**{s['name']}**: "
                        f"현재 {s['current_weight']}% → 목표 {s['target_weight']}% "
                        f"({s['action']})</span>",
                        unsafe_allow_html=True,
                    )
            else:
                st.success("포트폴리오 비중이 균형적입니다.")

        with risk_tab5:
            sector_data = analyze_sector_diversification(results)
            if sector_data["sectors"]:
                for s in sector_data["sectors"]:
                    stocks_str = ", ".join(s["stocks"])
                    st.markdown(
                        f"**{s['sector']}**: {s['weight_pct']}% ({stocks_str})"
                    )
                    st.progress(min(s["weight_pct"] / 100, 1.0))
                for w in sector_data["warnings"]:
                    st.warning(w)
                if not sector_data["warnings"]:
                    st.success("섹터 분산이 양호합니다.")
            else:
                st.info("섹터 분석 데이터를 조회할 수 없습니다.")

        with risk_tab6:
            port_analysis = calc_portfolio_level_analysis(results)
            if port_analysis:
                col1, col2, col3 = st.columns(3)
                with col1:
                    hhi_color = "#ff4444" if port_analysis["hhi"] > 2500 else "#ffaa00" if port_analysis["hhi"] > 1500 else "#00ff88"
                    st.metric("HHI (집중도)", f"{port_analysis['hhi']}")
                    st.markdown(f"<span style='color:{hhi_color}'>{port_analysis['hhi_class']}</span>", unsafe_allow_html=True)
                with col2:
                    if port_analysis["portfolio_beta"] is not None:
                        beta_color = "#ff4444" if port_analysis["portfolio_beta"] > 1.2 else "#00ff88" if port_analysis["portfolio_beta"] < 0.8 else "#ffaa00"
                        st.metric("포트폴리오 베타", f"{port_analysis['portfolio_beta']}")
                        st.markdown(f"<span style='color:{beta_color}'>{port_analysis['beta_class']}</span>", unsafe_allow_html=True)
                    else:
                        st.metric("포트폴리오 베타", "N/A")
                with col3:
                    sc_color = "#00ff88" if port_analysis["weighted_score"] >= 65 else "#ffaa00" if port_analysis["weighted_score"] >= 40 else "#ff4444"
                    st.metric("가중평균 점수", f"{port_analysis['weighted_score']}/100")
                    st.markdown(f"<span style='color:{sc_color}'>{port_analysis['stock_count']}개 종목 기준</span>", unsafe_allow_html=True)

                st.divider()
                st.caption(
                    "HHI: 10000=단일종목, 2500↑=고집중, 1500↓=적절 분산 | "
                    "베타: 1.0=시장동일, >1.2=공격적, <0.8=방어적"
                )
            else:
                st.info("포트폴리오 분석에 필요한 데이터가 부족합니다.")


def render_indicators(result: dict):
    """기술적 지표 탭 렌더링"""
    if "error" in result or "indicators" not in result:
        st.warning("지표 데이터가 없습니다.")
        return

    ind = result["indicators"]
    if not ind or not isinstance(ind, dict):
        st.warning("지표 데이터가 비어 있습니다.")
        return

    def indicator_color(classification: str) -> str:
        if not classification:
            return "#ffaa00"
        if any(w in classification for w in ["과매수", "과다 유입", "하락", "분산", "데드"]):
            return "#ff4444"
        elif any(w in classification for w in ["과매도", "과다 유출", "상승", "매집", "골든", "강세"]):
            return "#00ff88"
        else:
            return "#ffaa00"

    # RSI + MFI (2열)
    col1, col2 = st.columns(2)
    with col1:
        rsi = ind["rsi"]
        color = indicator_color(rsi["classification"])
        st.markdown(f"**RSI (14)**: `{rsi['value']}`")
        st.markdown(f"<span style='color:{color}'>{rsi['classification']}</span>", unsafe_allow_html=True)
    with col2:
        mfi = ind["mfi"]
        color = indicator_color(mfi["classification"])
        st.markdown(f"**MFI (14)**: `{mfi['value']}`")
        st.markdown(f"<span style='color:{color}'>{mfi['classification']}</span>", unsafe_allow_html=True)

    st.divider()

    # MACD
    macd = ind["macd"]
    color = indicator_color(macd["classification"])
    st.markdown(f"**MACD**: `{macd['macd']}` | Signal: `{macd['signal']}` | Histogram: `{macd['histogram']}`")
    st.markdown(f"<span style='color:{color}'>{macd['classification']}</span>", unsafe_allow_html=True)

    st.divider()

    # 볼린저 밴드
    bb = ind["bollinger"]
    color = indicator_color(bb["classification"])
    st.markdown(f"**볼린저 밴드**: Upper `{bb['upper']:,}` | Middle `{bb['middle']:,}` | Lower `{bb['lower']:,}`")
    if bb["bandwidth"]:
        st.markdown(f"밴드폭: `{bb['bandwidth']}%`{'  **⚠️ 스퀴즈 감지!**' if bb['squeeze'] else ''}")
    st.markdown(f"<span style='color:{color}'>{bb['classification']}</span>", unsafe_allow_html=True)

    st.divider()

    # 스토캐스틱 + ADX (2열)
    col1, col2 = st.columns(2)
    with col1:
        stoch = ind["stochastic"]
        color = indicator_color(stoch["classification"])
        st.markdown(f"**스토캐스틱**: %K `{stoch['k']}` | %D `{stoch['d']}`")
        st.markdown(f"<span style='color:{color}'>{stoch['classification']}</span>", unsafe_allow_html=True)
    with col2:
        adx = ind["adx"]
        color = indicator_color(adx["classification"])
        st.markdown(f"**ADX**: `{adx['adx']}` | +DI `{adx['plus_di']}` | -DI `{adx['minus_di']}`")
        st.markdown(f"<span style='color:{color}'>{adx['classification']}</span>", unsafe_allow_html=True)

    st.divider()

    # ATR + OBV (2열)
    col1, col2 = st.columns(2)
    with col1:
        atr = ind["atr"]
        st.markdown(f"**ATR (14)**: `{atr['atr']:,}` ({atr['atr_pct']}%)")
        if atr["stop_loss"] and atr["take_profit"]:
            st.markdown(f"손절 라인: `{atr['stop_loss']:,}` | 익절 라인: `{atr['take_profit']:,}`")
    with col2:
        obv = ind["obv"]
        color = indicator_color(obv["classification"])
        st.markdown(f"**OBV**: `{obv['obv']:,}`")
        st.markdown(f"<span style='color:{color}'>{obv['classification']}</span>", unsafe_allow_html=True)

    # 지표 충돌 종합 해석
    conflict = ind.get("conflict_interpretation")
    if conflict:
        st.divider()
        conf_color = {"높음": "#00ff88", "중간": "#ffaa00", "낮음": "#ff4444"}.get(conflict["confidence"], "#ffaa00")
        st.markdown(
            f"**종합 해석** <span style='color:{conf_color}'>[신뢰도: {conflict['confidence']}]</span>",
            unsafe_allow_html=True,
        )
        st.info(conflict["interpretation"])


def render_fundamental(result: dict):
    """펀더멘털/수급 탭 렌더링"""
    if "error" in result or "fundamental" not in result:
        st.warning("펀더멘털 데이터가 없습니다.")
        return

    fund = result["fundamental"]

    # 밸류에이션
    st.markdown("**밸류에이션**")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("PER", f"{fund['per']}" if fund['per'] else "N/A")
    with col2:
        st.metric("PBR", f"{fund['pbr']}" if fund['pbr'] else "N/A")
    with col3:
        st.metric("ROE", f"{fund['roe']}%" if fund['roe'] else "N/A")
    with col4:
        st.metric("배당수익률", f"{fund['div_yield']}%" if fund['div_yield'] else "N/A")
    with col5:
        peg = fund.get("peg", {})
        if peg and peg.get("peg"):
            peg_color = "#00ff88" if peg["peg"] < 1 else "#ffaa00" if peg["peg"] <= 1.5 else "#ff4444"
            st.metric("PEG", f"{peg['peg']}")
        else:
            st.metric("PEG", "N/A")

    # S-RIM 적정주가
    srim = fund.get("srim", {})
    if srim.get("neutral"):
        st.markdown("**S-RIM 적정주가**")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("낙관적", f"{srim['optimistic']:,}원")
        with col2:
            st.metric("중립적", f"{srim['neutral']:,}원")
        with col3:
            st.metric("비관적", f"{srim['pessimistic']:,}원")

        current = result["current_price"]
        neutral = srim["neutral"]
        gap_pct = round((neutral - current) / current * 100, 1)
        if gap_pct > 0:
            st.markdown(f"현재가 대비 **<span style='color:#00ff88'>{gap_pct}% 상승 여력</span>** (중립 기준)", unsafe_allow_html=True)
        else:
            st.markdown(f"현재가 대비 **<span style='color:#ff4444'>{abs(gap_pct)}% 고평가</span>** (중립 기준)", unsafe_allow_html=True)

    # 간이 DCF (해외주식)
    dcf = fund.get("dcf")
    if dcf:
        st.markdown("**간이 DCF 적정주가**")
        st.caption("EPS 기반 5년 할인현금흐름. 참고 수치이며 정밀 DCF가 아닙니다.")
        col1, col2, col3 = st.columns(3)
        current = result["current_price"]
        for col, key in zip([col1, col2, col3], ["optimistic", "neutral", "pessimistic"]):
            with col:
                d = dcf[key]
                gap = round((d["fair_value"] - current) / current * 100, 1)
                gap_color = "#00ff88" if gap > 0 else "#ff4444"
                st.metric(f"{d['label']} (성장률 {d['growth_rate']}%)", f"${d['fair_value']:,}")
                st.markdown(f"<span style='color:{gap_color}'>{'+' if gap > 0 else ''}{gap}%</span>", unsafe_allow_html=True)

    # 밸류에이션 종합
    val_color = "#00ff88" if "저평가" in fund["valuation_class"] else "#ff4444" if "고평가" in fund["valuation_class"] else "#ffaa00"
    st.markdown(f"밸류에이션 판단: <span style='color:{val_color}'>{fund['valuation_class']}</span>", unsafe_allow_html=True)

    st.divider()

    # 수급
    st.markdown("**외국인/기관 수급**")
    investor = fund.get("investor")
    if investor:
        col1, col2 = st.columns(2)
        with col1:
            fg = investor.get("foreigner")
            if fg:
                fg_color = "#00ff88" if fg["trend"] == "순매수" else "#ff4444"
                st.markdown(f"외국인: <span style='color:{fg_color}'>{fg['trend']}</span>", unsafe_allow_html=True)
                st.markdown(f"- 최근 1일: {fg['recent_1d']:,}원")
                st.markdown(f"- 최근 5일: {fg['recent_5d']:,}원")
                if abs(fg["consecutive"]) >= 2:
                    st.markdown(f"- **{abs(fg['consecutive'])}일 연속 {'순매수' if fg['consecutive'] > 0 else '순매도'}**")
        with col2:
            inst = investor.get("institution")
            if inst:
                inst_color = "#00ff88" if inst["trend"] == "순매수" else "#ff4444"
                st.markdown(f"기관: <span style='color:{inst_color}'>{inst['trend']}</span>", unsafe_allow_html=True)
                st.markdown(f"- 최근 1일: {inst['recent_1d']:,}원")
                st.markdown(f"- 최근 5일: {inst['recent_5d']:,}원")
                if abs(inst["consecutive"]) >= 2:
                    st.markdown(f"- **{abs(inst['consecutive'])}일 연속 {'순매수' if inst['consecutive'] > 0 else '순매도'}**")

        supply_color = "#00ff88" if "매수" in fund["supply_class"] else "#ff4444" if "매도" in fund["supply_class"] else "#ffaa00"
        st.markdown(f"수급 판단: <span style='color:{supply_color}'>{fund['supply_class']}</span>", unsafe_allow_html=True)
    else:
        st.info("수급 데이터를 조회할 수 없습니다.")

    st.divider()

    # 52주 위치
    w52 = fund.get("week52", {})
    if w52.get("position_pct") is not None:
        st.markdown("**52주 고저 위치**")
        st.markdown(f"52주 최고: {w52['high']:,} | 52주 최저: {w52['low']:,}")
        st.progress(w52["position_pct"] / 100)
        st.markdown(f"현재 위치: 상위 **{100 - w52['position_pct']:.0f}%**")

    st.divider()

    # PEG 분류
    peg = fund.get("peg", {})
    if peg and peg.get("peg"):
        peg_color = "#00ff88" if "저평가" in peg["classification"] else "#ff4444" if "고평가" in peg["classification"] else "#ffaa00"
        st.markdown(f"**PEG 비율**: {peg['peg']} (이익성장률: {peg.get('earnings_growth', 'N/A')}%)")
        st.markdown(f"PEG 판단: <span style='color:{peg_color}'>{peg['classification']}</span>", unsafe_allow_html=True)

    # 업종 평균 비교
    sector_comp = fund.get("sector_comparison", {})
    if sector_comp and sector_comp.get("sector_name"):
        st.divider()
        st.markdown(f"**업종 비교** ({sector_comp['sector_name']})")
        col1, col2 = st.columns(2)
        with col1:
            if sector_comp.get("sector_per"):
                st.markdown(f"업종 평균 PER: `{sector_comp['sector_per']}`")
        with col2:
            if sector_comp.get("sector_pbr"):
                st.markdown(f"업종 평균 PBR: `{sector_comp['sector_pbr']}`")
        comp_color = "#00ff88" if "저평가" in sector_comp.get("classification", "") else "#ff4444" if "고평가" in sector_comp.get("classification", "") else "#ffaa00"
        st.markdown(f"업종 대비: <span style='color:{comp_color}'>{sector_comp['classification']}</span>", unsafe_allow_html=True)

    # DART 공시
    dart = fund.get("dart", [])
    if dart:
        st.divider()
        st.markdown("**DART 공시**")
        for d in dart:
            title = _sanitize_html(d.get('title', ''))
            date_str = f" ({d['date']})" if d.get('date') else ""
            reporter_str = f" - {_sanitize_html(d.get('reporter', ''))}" if d.get('reporter') else ""
            if d.get("link"):
                st.markdown(f"- [{title}]({d['link']}){reporter_str}{date_str}")
            else:
                st.markdown(f"- {title}{reporter_str}{date_str}")



def render_news(result: dict):
    """뉴스 탭 렌더링"""
    fund = result.get("fundamental", {})

    # 펀더멘털 뉴스 피드
    news = fund.get("news", [])
    if news:
        st.markdown("**최근 뉴스**")
        for article in news:
            title = _sanitize_html(article.get('title', ''))
            date_str = f" ({article['date']})" if article['date'] else ""
            source_str = f" - {_sanitize_html(article.get('source', ''))}" if article['source'] else ""
            if article.get("link"):
                st.markdown(f"- [{title}]({article['link']}){source_str}{date_str}")
            else:
                st.markdown(f"- {title}{source_str}{date_str}")

    # 글로벌 뉴스 (Google News RSS 실시간 크롤링)
    global_news = result.get("global_news", {})
    if global_news.get("available"):
        if news:
            st.divider()
        st.markdown("**관련 뉴스** (Google News)")

        # 테마 키워드 표시
        keywords_used = global_news.get("keywords_used", [])
        if keywords_used:
            kw_str = " / ".join([f"`{kw}`" for kw in keywords_used])
            st.markdown(f"테마 키워드: {kw_str}")

        ss = global_news.get("sentiment_summary", {})
        if ss.get("total", 0) > 0:
            st.markdown(f"수집 뉴스: **{ss['total']}건**")

        # 뉴스 감성 점수 표시
        news_score = result.get("news_sentiment_score")
        if news_score is not None:
            if news_score >= 60:
                score_color = "#00ff88"
                label = "긍정적"
            elif news_score >= 40:
                score_color = "#ffaa00"
                label = "중립"
            else:
                score_color = "#ff4444"
                label = "부정적"
            st.markdown(f"뉴스 감성: <span style='color:{score_color}'>**{label}** ({news_score}점)</span>", unsafe_allow_html=True)

        # 종목 직접 뉴스
        direct = global_news.get("direct", [])
        if direct:
            with st.expander(f"종목 뉴스 ({len(direct)}건)", expanded=True):
                for article in direct:
                    title = _sanitize_html(article.get("title", ""))
                    source = _sanitize_html(article.get("source", ""))
                    date_str = article.get("published_at", "")[:10]
                    link = article.get("link", "")
                    header = f"[{title}]({link})" if link else title
                    source_label = f" ({source})" if source else ""
                    date_label = f" {date_str}" if date_str else ""
                    st.markdown(f"- {header}{source_label}{date_label}")

        # 테마/기술 관련 뉴스
        sector = global_news.get("sector", [])
        if sector:
            with st.expander(f"테마/기술 뉴스 ({len(sector)}건)", expanded=True):
                for article in sector:
                    title = _sanitize_html(article.get("title", ""))
                    source = _sanitize_html(article.get("source", ""))
                    kw = _sanitize_html(article.get("keyword", ""))
                    date_str = article.get("published_at", "")[:10]
                    link = article.get("link", "")
                    header = f"[{title}]({link})" if link else title
                    source_label = f" ({source})" if source else ""
                    kw_label = f" `{kw}`" if kw else ""
                    st.markdown(f"- {header}{source_label}{kw_label}")
    elif not news:
        st.info("뉴스 데이터가 없습니다.")


def render_strategy(result: dict):
    """전략/스코어카드 탭 렌더링"""
    if "error" in result:
        st.warning("데이터가 없습니다.")
        return

    # === 종합 스코어카드 ===
    sc = result.get("scorecard", {})
    if sc:
        type_label = sc.get("stock_type_label", "일반")
        type_colors = {"성장주": "#00bfff", "가치주": "#ffa500", "배당주": "#00ff88", "일반": "#aaaaaa"}
        type_color = type_colors.get(type_label, "#aaaaaa")
        st.markdown(
            f"### 종합 점수: {sc['total']}/100  {sc['grade']}  "
            f"<span style='background:{type_color};color:#000;padding:2px 8px;border-radius:4px;font-size:0.8em'>"
            f"{type_label}</span>",
            unsafe_allow_html=True,
        )

        # 카테고리별 점수 바
        for cat, score in sc.get("scores", {}).items():
            weight = sc.get("weights", {}).get(cat, 0)
            col1, col2, col3 = st.columns([2, 5, 1])
            with col1:
                st.markdown(f"**{cat}** ({int(weight*100)}%)")
            with col2:
                st.progress(score / 100)
            with col3:
                color = "#00ff88" if score >= 65 else "#ffaa00" if score >= 40 else "#ff4444"
                st.markdown(f"<span style='color:{color}'>{score}</span>", unsafe_allow_html=True)

    st.divider()

    # === 미너비니 추세 템플릿 ===
    minervini = result.get("minervini", {})
    if minervini:
        st.markdown(f"**미너비니 추세 템플릿**: {minervini['passed']}/{minervini['total']} 조건 충족 ({minervini['score']}점)")
        for condition, passed in minervini.get("conditions", {}).items():
            if passed is None:
                icon = "⚪"
            elif passed:
                icon = "✅"
            else:
                icon = "❌"
            st.markdown(f"  {icon} {condition}")

    st.divider()

    # === 한국형 CANSLIM ===
    canslim = result.get("canslim", {})
    if canslim:
        grade_color = "#00ff88" if canslim["grade"] in ("A", "B") else "#ffaa00" if canslim["grade"] == "C" else "#ff4444"
        st.markdown(f"**한국형 CANSLIM**: <span style='color:{grade_color}'>등급 {canslim['grade']}</span> ({canslim['total']}점)", unsafe_allow_html=True)
        for item, data in canslim.get("scores", {}).items():
            bar_color = "#00ff88" if data["score"] >= 70 else "#ffaa00" if data["score"] >= 50 else "#ff4444"
            st.markdown(f"  - **{item}**: {data['detail']} (<span style='color:{bar_color}'>{data['score']}점</span>)", unsafe_allow_html=True)

    st.divider()

    # === 터틀 트레이딩 ===
    turtle = result.get("turtle", {})
    if turtle:
        turtle_color = "#00ff88" if "매수" in turtle["classification"] else "#ff4444" if "매도" in turtle["classification"] else "#ffaa00"
        st.markdown(f"**터틀 트레이딩**: <span style='color:{turtle_color}'>{turtle['classification']}</span>", unsafe_allow_html=True)
        for signal, active in turtle.get("signals", {}).items():
            icon = "🟢" if active else "⚫"
            st.markdown(f"  {icon} {signal}")
        if turtle.get("position_size"):
            st.markdown(f"  ATR 기반 적정 매수량: **{turtle['position_size']:,}주** (1억 기준, 1% 리스크)")


def render_chart(result: dict):
    """차트 탭 렌더링"""
    if "error" in result or "df" not in result:
        st.warning("차트 데이터가 없습니다.")
        return

    ticker_raw = result.get("ticker_raw", "")
    chart_key = f"chart_period_{ticker_raw}"

    # 기간 선택 버튼
    periods = {"1주": 5, "1개월": 20, "3개월": 60, "6개월": 120, "1년": 250}
    cols = st.columns(len(periods))
    for i, (label, days) in enumerate(periods.items()):
        with cols[i]:
            if st.button(label, key=f"{chart_key}_{label}", use_container_width=True):
                st.session_state[chart_key] = days

    selected_days = st.session_state.get(chart_key, 120)

    # 선택된 기간에 맞는 데이터
    df_full = result["df"]
    if len(df_full) > selected_days:
        df_chart = df_full.tail(selected_days)
    else:
        # 더 많은 데이터가 필요하면 재조회
        if selected_days > len(df_full):
            df_extended = get_stock_data(ticker_raw, days=selected_days)
            df_chart = df_extended if not df_extended.empty else df_full
        else:
            df_chart = df_full

    # 선택 기간용 지표 재계산
    chart_indicators = calc_all_indicators(df_chart, result.get("ma_classification", ""))

    fig = create_stock_chart(
        df_chart,
        result["name"],
        chart_indicators,
        result.get("ma", {}),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_pattern(result: dict):
    """패턴 분석 탭 렌더링 (축적 데이터 기반)"""
    if "error" in result:
        st.warning("데이터가 없습니다.")
        return

    ticker = result.get("ticker_raw", "")
    name = result.get("name", "")

    # DB 축적 현황
    stats = get_db_stats()
    st.caption(
        f"축적 현황: 일봉 {stats['daily_rows']:,}건 ({stats['daily_tickers']}종목) | "
        f"스냅샷 {stats['snapshot_rows']:,}건 ({stats['snapshot_tickers']}종목)"
    )
    st.caption("접속할 때마다 데이터가 자동 축적됩니다. 데이터가 쌓일수록 패턴이 정확해집니다.")

    st.markdown("---")

    # 1. 요일별 패턴
    st.markdown("**요일별 수익률 패턴**")
    dow_pattern = analyze_day_of_week_pattern(ticker)
    if dow_pattern:
        cols = st.columns(len(dow_pattern))
        for i, (day, data) in enumerate(dow_pattern.items()):
            with cols[i]:
                color = "#00ff88" if data["avg_return"] > 0 else "#ff4444" if data["avg_return"] < 0 else "#888"
                st.markdown(
                    f"<div style='text-align:center'>"
                    f"<b>{day}요일</b><br>"
                    f"<span style='color:{color};font-size:1.2em'>{data['avg_return']:+.3f}%</span><br>"
                    f"승률 {data['win_rate']}%<br>"
                    f"<span style='color:#888;font-size:0.8em'>{data['count']}일</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        # 요약
        best_day = max(dow_pattern.items(), key=lambda x: x[1]["avg_return"])
        worst_day = min(dow_pattern.items(), key=lambda x: x[1]["avg_return"])
        st.markdown(
            f"강세 요일: **{best_day[0]}요일** ({best_day[1]['avg_return']:+.3f}%) | "
            f"약세 요일: **{worst_day[0]}요일** ({worst_day[1]['avg_return']:+.3f}%)"
        )
    else:
        st.info("일봉 데이터가 60일 이상 축적되면 분석 가능합니다.")

    st.markdown("---")

    # 2. 월별 계절성
    st.markdown("**월별 수익률 패턴 (계절성)**")
    monthly_pattern = analyze_monthly_pattern(ticker)
    if monthly_pattern:
        months = list(monthly_pattern.keys())
        avg_returns = [monthly_pattern[m]["avg_return"] for m in months]
        colors = ["#00ff88" if r > 0 else "#ff4444" for r in avg_returns]

        import plotly.graph_objects as go
        fig = go.Figure(go.Bar(
            x=months, y=avg_returns,
            marker_color=colors,
            text=[f"{r:+.2f}%" for r in avg_returns],
            textposition="outside",
        ))
        fig.update_layout(
            template="plotly_dark",
            height=300,
            margin=dict(l=40, r=40, t=30, b=30),
            yaxis_title="평균 수익률 (%)",
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
        )
        st.plotly_chart(fig, use_container_width=True)

        best_month = max(monthly_pattern.items(), key=lambda x: x[1]["avg_return"])
        worst_month = min(monthly_pattern.items(), key=lambda x: x[1]["avg_return"])
        st.markdown(
            f"강세 월: **{best_month[0]}** ({best_month[1]['avg_return']:+.2f}%) | "
            f"약세 월: **{worst_month[0]}** ({worst_month[1]['avg_return']:+.2f}%)"
        )
    else:
        st.info("6개월 이상 데이터가 축적되면 월별 패턴을 분석합니다.")

    st.markdown("---")

    # 3. 장중 패턴 (시가 vs 종가)
    st.markdown("**장중 패턴 (갭/장중 흐름)**")
    intra = analyze_intraday_pattern(ticker)
    if intra:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("평균 갭", f"{intra['avg_gap']:+.3f}%")
            st.metric("장중 상승 비율", f"{intra['intraday_up_rate']}%")
        with col2:
            gu = intra["gap_up_then_close"]
            st.markdown(f"**갭 상승 후** ({gu['count']}일)")
            st.markdown(f"- 장중 평균: {gu['avg_intraday']:+.3f}%")
            st.markdown(f"- 갭 메움 비율: {gu['fill_rate']}%")
        with col3:
            gd = intra["gap_down_then_close"]
            st.markdown(f"**갭 하락 후** ({gd['count']}일)")
            st.markdown(f"- 장중 평균: {gd['avg_intraday']:+.3f}%")
            st.markdown(f"- 갭 메움 비율: {gd['fill_rate']}%")

        st.caption(f"분석 기간: {intra['total_days']}거래일 | 평균 윗꼬리: {intra['avg_upper_wick']:.3f}% | 평균 아래꼬리: {intra['avg_lower_wick']:.3f}%")
    else:
        st.info("60일 이상 데이터가 축적되면 장중 패턴을 분석합니다.")

    st.markdown("---")

    # 4. 시간대별 스냅샷 패턴
    st.markdown("**시간대별 가격 변동 (스냅샷 기반)**")
    time_pattern = analyze_time_snapshot_pattern(ticker)
    if time_pattern:
        for hour, data in time_pattern.items():
            color = "#00ff88" if data["avg_change"] > 0 else "#ff4444" if data["avg_change"] < 0 else "#888"
            st.markdown(
                f"- **{hour}**: 평균 변동 <span style='color:{color}'>{data['avg_change']:+.3f}%</span> "
                f"(상승 확률 {data['win_rate']}%, {data['count']}건)",
                unsafe_allow_html=True,
            )
    else:
        st.info(
            "스냅샷 데이터가 20건 이상 축적되면 시간대별 패턴을 분석합니다.\n\n"
            "하루 중 다른 시간대에 접속하면 더 풍부한 데이터가 쌓입니다."
        )


def _build_export_data(results: list) -> dict:
    """AI 분석용 JSON 데이터 구조 생성"""
    export = {
        "export_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "portfolio": [],
    }
    for r in results:
        if "error" in r:
            continue
        stock = {
            "name": r["name"],
            "ticker": r.get("ticker_raw", r["ticker"]),
            "market": r.get("market", ""),
            "current_price": r["current_price"],
            "avg_price": r["avg_price"],
            "quantity": r["quantity"],
            "profit_rate": r["profit_rate"],
            "technical": {
                "ma_classification": r["ma_classification"],
                "vol_classification": r["vol_classification"],
                "overall": r["overall"],
            },
            "fundamental": {},
            "scorecard": r.get("scorecard", {}),
            "news": {},
        }
        # 기술적 지표
        if "indicators" in r:
            ind = r["indicators"]
            stock["technical"]["rsi"] = {"value": ind["rsi"]["value"], "classification": ind["rsi"]["classification"]}
            stock["technical"]["macd"] = ind["macd"]["classification"]
            stock["technical"]["bollinger"] = ind["bollinger"]["classification"]
            stock["technical"]["stochastic"] = ind["stochastic"]["classification"]
            stock["technical"]["adx"] = ind["adx"]["classification"]
            stock["technical"]["obv"] = ind["obv"]["classification"]
            stock["technical"]["mfi"] = {"value": ind["mfi"]["value"], "classification": ind["mfi"]["classification"]}
            if ind["atr"]["stop_loss"]:
                stock["technical"]["atr_stop_loss"] = ind["atr"]["stop_loss"]
                stock["technical"]["atr_take_profit"] = ind["atr"]["take_profit"]
            conflict = ind.get("conflict_interpretation")
            if conflict:
                stock["technical"]["interpretation"] = conflict
        # 벤치마크
        if r.get("benchmark"):
            stock["benchmark"] = r["benchmark"]
        # 펀더멘털
        if "fundamental" in r:
            fund = r["fundamental"]
            stock["fundamental"] = {
                "per": fund.get("per"),
                "pbr": fund.get("pbr"),
                "roe": fund.get("roe"),
                "div_yield": fund.get("div_yield"),
                "valuation_class": fund.get("valuation_class"),
                "supply_class": fund.get("supply_class"),
            }
            if fund.get("psr"):
                stock["fundamental"]["psr"] = fund["psr"]
            if fund.get("ev_ebitda"):
                stock["fundamental"]["ev_ebitda"] = fund["ev_ebitda"]
            if fund.get("payout_ratio") is not None:
                stock["fundamental"]["payout_ratio"] = fund["payout_ratio"]
            if fund.get("srim", {}).get("neutral"):
                stock["fundamental"]["srim"] = fund["srim"]
            if fund.get("peg", {}).get("peg"):
                stock["fundamental"]["peg"] = fund["peg"]
            if fund.get("week52", {}).get("position_pct") is not None:
                stock["fundamental"]["week52"] = fund["week52"]
            if fund.get("sector_comparison", {}).get("classification"):
                stock["fundamental"]["sector_comparison"] = fund["sector_comparison"]
        # 전략
        for key in ("minervini", "canslim", "turtle"):
            if r.get(key):
                stock[key] = r[key]
        # 뉴스
        gn = r.get("global_news", {})
        if gn.get("available"):
            stock["news"] = {
                "sentiment_score": r.get("news_sentiment_score"),
                "sentiment_summary": gn.get("sentiment_summary", {}),
                "keywords_used": gn.get("keywords_used", []),
                "direct": [{"title": a["title"], "source": a.get("source", ""), "date": a.get("published_at", ""), "link": a.get("link", "")} for a in gn.get("direct", [])[:10]],
                "sector": [{"title": a["title"], "source": a.get("source", ""), "keyword": a.get("keyword", ""), "link": a.get("link", "")} for a in gn.get("sector", [])[:10]],
            }
        # OHLCV 최근 데이터
        if "df" in r:
            df = r["df"].tail(30)
            stock["ohlcv_recent_30d"] = []
            for idx, row in df.iterrows():
                stock["ohlcv_recent_30d"].append({
                    "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                    "open": float(row["시가"]),
                    "high": float(row["고가"]),
                    "low": float(row["저가"]),
                    "close": float(row["종가"]),
                    "volume": int(row["거래량"]),
                })
        export["portfolio"].append(stock)

    # AI 리포트
    if st.session_state.get("ai_report"):
        export["ai_report"] = st.session_state["ai_report"]
    return export


def _build_export_markdown(results: list) -> str:
    """AI 분석용 Markdown 데이터 생성"""
    lines = [f"# 포트폴리오 분석 리포트", f"분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]

    for r in results:
        if "error" in r:
            continue
        lines.append(f"## {r['name']} ({r.get('ticker_raw', r['ticker'])})")
        lines.append(f"- 현재가: {r['current_price']:,} | 평균단가: {r['avg_price']:,} | 수량: {r['quantity']}주")
        lines.append(f"- 수익률: {r['profit_rate']}%")
        lines.append(f"- 이평 분류: {r['ma_classification']} | 거래량 분류: {r['vol_classification']}")
        lines.append(f"- 종합: {r['overall']}")

        if "indicators" in r:
            ind = r["indicators"]
            lines.append(f"\n### 기술적 지표")
            lines.append(f"- RSI: {ind['rsi']['value']} ({ind['rsi']['classification']})")
            lines.append(f"- MACD: {ind['macd']['classification']}")
            lines.append(f"- 볼린저: {ind['bollinger']['classification']}")
            lines.append(f"- 스토캐스틱: {ind['stochastic']['classification']}")
            lines.append(f"- ADX: {ind['adx']['classification']}")
            lines.append(f"- OBV: {ind['obv']['classification']}")
            lines.append(f"- MFI: {ind['mfi']['value']} ({ind['mfi']['classification']})")
            if ind['atr']['stop_loss']:
                lines.append(f"- ATR 손절: {ind['atr']['stop_loss']:,} / 익절: {ind['atr']['take_profit']:,}")
            conflict = ind.get("conflict_interpretation")
            if conflict:
                lines.append(f"- 종합 해석: {conflict['interpretation']} [신뢰도: {conflict['confidence']}]")

        bench = r.get("benchmark")
        if bench:
            alpha_sign = "+" if bench["alpha"] >= 0 else ""
            lines.append(f"\n### 벤치마크")
            lines.append(f"- {bench['benchmark_name']}: 종목 {bench['stock_return']}% vs 지수 {bench['benchmark_return']}% → 알파 {alpha_sign}{bench['alpha']}%p")

        if "fundamental" in r:
            fund = r["fundamental"]
            lines.append(f"\n### 펀더멘털")
            if fund.get("per"):
                lines.append(f"- PER: {fund['per']} | PBR: {fund['pbr']} | ROE: {fund.get('roe')}%")
            if fund.get("srim", {}).get("neutral"):
                lines.append(f"- S-RIM 적정가(중립): {fund['srim']['neutral']:,}")
            lines.append(f"- 밸류에이션: {fund['valuation_class']}")
            lines.append(f"- 수급: {fund['supply_class']}")
            if fund.get("peg", {}).get("peg"):
                lines.append(f"- PEG: {fund['peg']['peg']} ({fund['peg']['classification']})")
            if fund.get("week52", {}).get("position_pct") is not None:
                lines.append(f"- 52주 위치: 상위 {100 - fund['week52']['position_pct']:.0f}%")

        sc = r.get("scorecard", {})
        if sc:
            type_label = sc.get("stock_type_label", "일반")
            lines.append(f"\n### 스코어카드: {sc['total']}/100 {sc['grade']} [{type_label}]")
            for cat, score in sc.get("scores", {}).items():
                weight = sc.get("weights", {}).get(cat, 0)
                lines.append(f"- {cat}: {score}점 (가중치 {weight*100:.0f}%)")

        gn = r.get("global_news", {})
        if gn.get("available"):
            lines.append(f"\n### 뉴스 (감성 점수: {r.get('news_sentiment_score', 'N/A')})")
            ss = gn.get("sentiment_summary", {})
            lines.append(f"- 긍정: {ss.get('counts', {}).get('Positive', 0)}건 | 부정: {ss.get('counts', {}).get('Negative', 0)}건 | 중립: {ss.get('counts', {}).get('Neutral', 0)}건")
            for a in gn.get("direct", [])[:5]:
                lines.append(f"- [{a.get('source', '')}] {a['title']}")
            for a in gn.get("sector", [])[:5]:
                lines.append(f"- [{a.get('source', '')}] {a['title']} (키워드: {a.get('keyword', '')})")

        # OHLCV 최근 10일
        if "df" in r:
            df = r["df"].tail(10)
            lines.append(f"\n### 최근 주가 (10일)")
            lines.append("| 날짜 | 시가 | 고가 | 저가 | 종가 | 거래량 |")
            lines.append("|------|------|------|------|------|--------|")
            for idx, row in df.iterrows():
                date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
                lines.append(f"| {date_str} | {int(row['시가']):,} | {int(row['고가']):,} | {int(row['저가']):,} | {int(row['종가']):,} | {int(row['거래량']):,} |")

        lines.append("")

    if st.session_state.get("ai_report"):
        lines.append("## AI 종합 리포트")
        lines.append(st.session_state["ai_report"])

    return "\n".join(lines)


def build_ai_context(results: list) -> str:
    """AI 질의응답용 컨텍스트 생성"""
    context = "아래는 사용자의 보유 주식 포트폴리오 분석 결과입니다.\n\n"
    for r in results:
        if "error" in r:
            continue
        context += f"## {r['name']} ({r['ticker']})\n"
        context += f"- 현재가: {r['current_price']:,}원\n"
        context += f"- 평균단가: {r['avg_price']:,}원\n"
        context += f"- 수량: {r['quantity']}주\n"
        context += f"- 수익률: {r['profit_rate']}%\n"
        context += f"- 이평 배열: {r['ma_arrangement']}\n"
        context += f"- 이평 분류: {r['ma_classification']}\n"
        context += f"- 거래량 배열: {r['vol_arrangement']}\n"
        context += f"- 거래량 분류: {r['vol_classification']}\n"
        context += f"- 종합 분류: {r['overall']}\n"
        # 2단계 지표 추가
        if "indicators" in r:
            ind = r["indicators"]
            context += f"- RSI: {ind['rsi']['value']} ({ind['rsi']['classification']})\n"
            context += f"- MACD: {ind['macd']['classification']}\n"
            context += f"- 볼린저: {ind['bollinger']['classification']}\n"
            context += f"- 스토캐스틱: {ind['stochastic']['classification']}\n"
            context += f"- ADX: {ind['adx']['classification']}\n"
            context += f"- OBV: {ind['obv']['classification']}\n"
            context += f"- MFI: {ind['mfi']['value']} ({ind['mfi']['classification']})\n"
            if ind['atr']['stop_loss']:
                context += f"- ATR 손절라인: {ind['atr']['stop_loss']:,} / 익절라인: {ind['atr']['take_profit']:,}\n"
            conflict = ind.get("conflict_interpretation")
            if conflict:
                context += f"- 종합 해석: {conflict['interpretation']} [신뢰도: {conflict['confidence']}]\n"
        bench = r.get("benchmark")
        if bench:
            alpha_sign = "+" if bench["alpha"] >= 0 else ""
            context += f"- 벤치마크({bench['benchmark_name']}): 알파 {alpha_sign}{bench['alpha']}%p\n"
        # 4단계 펀더멘털
        if "fundamental" in r:
            fund = r["fundamental"]
            if fund.get("per"):
                context += f"- PER: {fund['per']} / PBR: {fund['pbr']} / ROE: {fund.get('roe')}%\n"
            if fund.get("srim", {}).get("neutral"):
                context += f"- S-RIM 적정가(중립): {fund['srim']['neutral']:,}원\n"
            context += f"- 밸류에이션: {fund['valuation_class']}\n"
            context += f"- 수급: {fund['supply_class']}\n"
            peg = fund.get("peg", {})
            if peg and peg.get("peg"):
                context += f"- PEG: {peg['peg']} ({peg['classification']})\n"
            sector_comp = fund.get("sector_comparison", {})
            if sector_comp and sector_comp.get("classification"):
                context += f"- 업종 비교: {sector_comp['classification']}\n"
            w52 = fund.get("week52", {})
            if w52.get("position_pct") is not None:
                context += f"- 52주 위치: 상위 {100 - w52['position_pct']:.0f}%\n"
        # 5단계 스코어카드
        sc = r.get("scorecard", {})
        if sc:
            type_label = sc.get("stock_type_label", "일반")
            context += f"- 종목 유형: {type_label}\n"
            context += f"- 종합 점수: {sc['total']}/100 {sc['grade']}\n"
        canslim = r.get("canslim", {})
        if canslim:
            context += f"- CANSLIM 등급: {canslim['grade']} ({canslim['total']}점)\n"
        minervini = r.get("minervini", {})
        if minervini:
            context += f"- 미너비니: {minervini['passed']}/{minervini['total']} 조건 충족\n"
        turtle = r.get("turtle", {})
        if turtle:
            context += f"- 터틀: {turtle['classification']}\n"
        # 글로벌 뉴스 감성
        global_news = r.get("global_news", {})
        if global_news.get("available"):
            context += format_news_for_ai(global_news) + "\n"
        context += "\n"
    return context


# =============================================================
# 매매일지 자동 기록
# =============================================================

JOURNAL_FILE = "trading_journal.json"


def _load_journal() -> list:
    """매매일지 파일 로드"""
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_journal(entries: list):
    """매매일지 파일 저장"""
    with open(JOURNAL_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def save_journal_entry(result: dict, action: str, memo: str = ""):
    """매매일지 엔트리 저장 — 매매 시점의 시장 상황 + 지표 스냅샷"""
    if "error" in result:
        return

    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "name": result["name"],
        "ticker": result.get("ticker_raw", result["ticker"]),
        "price": result["current_price"],
        "avg_price": result["avg_price"],
        "quantity": result["quantity"],
        "profit_rate": result["profit_rate"],
        "memo": memo,
        "snapshot": {
            "ma_class": result["ma_classification"],
            "vol_class": result["vol_classification"],
            "overall": result["overall"],
        },
    }

    # 기술적 지표 스냅샷
    if "indicators" in result:
        ind = result["indicators"]
        entry["snapshot"]["rsi"] = ind["rsi"]["value"]
        entry["snapshot"]["macd"] = ind["macd"]["classification"]
        entry["snapshot"]["bollinger"] = ind["bollinger"]["classification"]
        entry["snapshot"]["adx"] = ind["adx"]["adx"]

    # 펀더멘털 스냅샷
    if "fundamental" in result:
        fund = result["fundamental"]
        entry["snapshot"]["per"] = fund.get("per")
        entry["snapshot"]["pbr"] = fund.get("pbr")
        entry["snapshot"]["valuation"] = fund.get("valuation_class")
        entry["snapshot"]["supply"] = fund.get("supply_class")

    # 스코어카드
    sc = result.get("scorecard", {})
    if sc:
        entry["snapshot"]["score"] = sc.get("total")
        entry["snapshot"]["grade"] = sc.get("grade")
        entry["snapshot"]["stock_type"] = sc.get("stock_type_label", "일반")

    entries = _load_journal()
    entries.insert(0, entry)  # 최신이 위로
    _save_journal(entries)

    return entry


def render_journal():
    """매매일지 UI 렌더링"""
    entries = _load_journal()

    if not entries:
        st.info("매매일지가 비어 있습니다. 종목 분석 후 기록 버튼을 눌러주세요.")
        return

    for i, entry in enumerate(entries[:20]):  # 최근 20건
        action_color = "#00ff88" if entry["action"] == "매수" else "#ff4444" if entry["action"] == "매도" else "#ffaa00"
        with st.expander(
            f"{entry['timestamp']} | **{entry['name']}** | "
            f"<span style='color:{action_color}'>{entry['action']}</span> | "
            f"{entry['price']:,}원",
            expanded=(i == 0),
        ):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown(f"**가격**: {entry['price']:,}원")
                st.markdown(f"**평균단가**: {entry['avg_price']:,}원")
            with col2:
                st.markdown(f"**수량**: {entry['quantity']}주")
                st.markdown(f"**수익률**: {entry['profit_rate']}%")
            with col3:
                snap = entry.get("snapshot", {})
                if snap.get("score"):
                    st.markdown(f"**종합점수**: {snap['score']}/100 {snap.get('grade', '')}")
                st.markdown(f"**종합분류**: {snap.get('overall', 'N/A')}")

            if entry.get("memo"):
                st.markdown(f"**메모**: {entry['memo']}")

            # 지표 스냅샷 상세
            snap = entry.get("snapshot", {})
            details = []
            if snap.get("rsi"):
                details.append(f"RSI: {snap['rsi']}")
            if snap.get("macd"):
                details.append(f"MACD: {snap['macd']}")
            if snap.get("per"):
                details.append(f"PER: {snap['per']}")
            if snap.get("valuation"):
                details.append(f"밸류: {snap['valuation']}")
            if snap.get("supply"):
                details.append(f"수급: {snap['supply']}")
            if details:
                st.markdown(f"**지표**: {' | '.join(details)}")


# =============================================================
# Google Sheets 연동
# =============================================================

GSHEET_CREDS_FILE = "okproject-490417-2c793ce833c2.json"


def load_from_google_sheets(sheet_url: str, credentials_json: str = None) -> list:
    """Google Sheets에서 포트폴리오 로드
    시트 형식: 종목코드 | 평균단가 | 수량
    credentials_json이 없으면 로컬 JSON 파일 자동 사용
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        # 로컬 JSON 파일 우선, 없으면 직접 입력값 사용
        import os
        if os.path.exists(GSHEET_CREDS_FILE):
            creds = Credentials.from_service_account_file(GSHEET_CREDS_FILE, scopes=scopes)
        elif credentials_json:
            creds_dict = json.loads(credentials_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        else:
            st.error("서비스 계정 JSON 파일을 찾을 수 없습니다.")
            return []
        gc = gspread.authorize(creds)
        gc = gspread.authorize(creds)

        sh = gc.open_by_url(sheet_url)
        ws = sh.sheet1
        records = ws.get_all_records()

        portfolio = []
        for row in records:
            ticker = str(row.get("종목코드", row.get("ticker", ""))).strip()
            # 숫자만 있는 경우 6자리로 자동 패딩 (시트에서 앞자리 0 누락 대응)
            if ticker.isdigit() and len(ticker) < 6:
                ticker = ticker.zfill(6)
            avg_price = float(row.get("평균단가", row.get("avg_price", 0)))
            qty = int(row.get("수량", row.get("quantity", 0)))
            if ticker and avg_price > 0 and qty > 0:
                portfolio.append({
                    "ticker": ticker,
                    "avg_price": avg_price,
                    "quantity": qty,
                })
        return portfolio
    except Exception as e:
        st.error(f"Google Sheets 연동 오류: {e}")
        return []


# =============================================================
# 메인 앱
# =============================================================

def main():
    # --- 사이드바: 텔레그램 알림 설정 ---
    with st.sidebar:
        st.markdown("### 텔레그램 알림")
        tg_token = st.text_input("Bot Token", type="password", key="tg_token",
                                  value=st.secrets.get("TELEGRAM_BOT_TOKEN", ""))
        tg_chat_id = st.text_input("Chat ID", key="tg_chat_id",
                                    value=st.secrets.get("TELEGRAM_CHAT_ID", ""))

        if st.session_state.get("analysis_results"):
            alerts = check_alerts(st.session_state.analysis_results)
            if alerts:
                st.markdown(f"**{len(alerts)}건의 알림 감지**")
                for a in alerts:
                    icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(a["severity"], "⚪")
                    st.markdown(f"{icon} **{a['stock']}**: {a['type']}")

                if tg_token and tg_chat_id:
                    if st.button("알림 발송", use_container_width=True):
                        sent = send_alerts(st.session_state.analysis_results, tg_token, tg_chat_id)
                        if sent > 0:
                            st.success(f"{sent}건 발송 완료")
                        else:
                            st.error("발송 실패. Token/Chat ID를 확인하세요.")
                else:
                    st.caption("Bot Token과 Chat ID를 입력하면 알림을 발송할 수 있습니다.")
            else:
                st.caption("현재 알림 조건에 해당하는 종목이 없습니다.")
        else:
            st.caption("분석 결과가 없습니다. 먼저 종목을 분석해주세요.")

        st.divider()

    # --- 상단: 데이터 입력 영역 ---
    col_btn, col_space = st.columns([1, 3])

    with col_btn:
        input_method = st.selectbox(
            "데이터 입력 방식",
            ["직접 입력", "Google Sheets", "한국투자증권 (KIS)"],
            label_visibility="collapsed",
        )

    # --- 직접 입력 모드 ---
    if input_method == "직접 입력":
        st.markdown("#### 보유 종목 입력")
        st.caption("종목코드는 6자리 숫자입니다. (예: 삼성전자 = 005930)")

        # 기본 예시 데이터 (한국 + 해외)
        default_data = [
            {"ticker": "005930", "avg_price": 188338, "quantity": 121},
            {"ticker": "402340", "avg_price": 0, "quantity": 23},
            {"ticker": "000660", "avg_price": 0, "quantity": 3},
            {"ticker": "AAPL", "avg_price": 230, "quantity": 10},
            {"ticker": "TSLA", "avg_price": 280, "quantity": 5},
        ]

        if not st.session_state.portfolio:
            st.session_state.portfolio = default_data

        edited_df = st.data_editor(
            pd.DataFrame(st.session_state.portfolio),
            column_config={
                "ticker": st.column_config.TextColumn("종목코드", width="medium"),
                "avg_price": st.column_config.NumberColumn("평균단가", min_value=0, format="%d"),
                "quantity": st.column_config.NumberColumn("수량", min_value=0, format="%d"),
            },
            num_rows="dynamic",
            use_container_width=True,
        )

        if st.button("📊 분석 시작", type="primary", use_container_width=True):
            portfolio = edited_df.to_dict("records")
            st.session_state.portfolio = portfolio

            with st.spinner("주가 데이터 수집 및 분석 중..."):
                results = []
                for item in portfolio:
                    ticker = str(item.get("ticker", "")).strip()
                    avg_price = max(float(item.get("avg_price", 0)), 0)
                    qty = max(int(item.get("quantity", 0)), 0)
                    # 숫자만 있는 경우 6자리로 자동 패딩 (Google Sheets 앞자리 0 누락 대응)
                    if ticker.isdigit() and len(ticker) < 6:
                        ticker = ticker.zfill(6)
                    # 종목코드 형식 검증 (한국 6자리 숫자 또는 영문 1~10자)
                    if not ticker:
                        continue
                    if not re.match(r"^\d{6}$|^[A-Za-z]{1,10}$", ticker):
                        st.warning(f"⚠️ '{ticker}' — 유효하지 않은 종목코드 (건너뜀)")
                        continue
                    if qty <= 0:
                        continue
                    result = analyze_stock(ticker, avg_price, qty)
                    results.append(result)
                st.session_state.analysis_results = results

    # --- Google Sheets 모드 ---
    elif input_method == "Google Sheets":
        st.markdown("#### Google Sheets 연동")
        st.caption("시트 형식: `종목코드 | 평균단가 | 수량` (첫 행은 헤더)")

        import os
        has_local_creds = os.path.exists(GSHEET_CREDS_FILE)

        # 저장된 시트 목록 관리 (세션 내에서만 유지, 새로고침 시 초기화)
        if "saved_sheets" not in st.session_state:
            st.session_state.saved_sheets = {}
        if "current_sheet_url" not in st.session_state:
            st.session_state.current_sheet_url = ""

        saved_sheets = st.session_state.saved_sheets
        sheet_names = list(saved_sheets.keys())

        # 시트 선택 또는 새로 입력
        col_select, col_new = st.columns([3, 1])
        with col_select:
            options = ["새 시트 입력"] + sheet_names
            selected = st.selectbox(
                "시트 선택",
                options,
                label_visibility="collapsed",
            )
        with col_new:
            if selected != "새 시트 입력" and st.button("삭제", use_container_width=True):
                del st.session_state.saved_sheets[selected]
                st.rerun()

        if selected == "새 시트 입력":
            sheet_url = st.text_input(
                "Google Sheet URL",
                placeholder="https://docs.google.com/spreadsheets/d/...",
            )
            sheet_label = st.text_input(
                "시트 이름 (저장용)",
                placeholder="예: 동하 포트폴리오, 영수 포트폴리오",
            )
        else:
            sheet_url = saved_sheets[selected]
            st.caption(f"URL: `{sheet_url[:60]}...`")
            sheet_label = None

        if not has_local_creds:
            creds_json = st.text_area(
                "서비스 계정 JSON",
                placeholder='{"type": "service_account", ...}',
                height=100,
            )
        else:
            creds_json = None
            st.caption(f"인증: `{GSHEET_CREDS_FILE}` 자동 사용")

        if st.button("📊 Google Sheet 불러오기", type="primary", use_container_width=True):
            if sheet_url:
                # 새 시트면 세션에 저장 (새로고침 시 초기화)
                if selected == "새 시트 입력" and sheet_label and sheet_label.strip():
                    st.session_state.saved_sheets[sheet_label.strip()] = sheet_url
                st.session_state.current_sheet_url = sheet_url

                portfolio = load_from_google_sheets(sheet_url, creds_json)
                if portfolio:
                    st.session_state.portfolio = portfolio
                    with st.spinner("주가 데이터 수집 및 분석 중..."):
                        results = []
                        for item in portfolio:
                            result = analyze_stock(
                                item["ticker"], item["avg_price"], item["quantity"]
                            )
                            results.append(result)
                        st.session_state.analysis_results = results
                else:
                    st.warning("시트에서 데이터를 불러올 수 없습니다. 시트 공유 설정을 확인해주세요.")
            else:
                st.warning("Sheet URL을 입력해주세요.")

    # --- KIS API 모드 ---
    elif input_method == "한국투자증권 (KIS)":
        st.markdown("#### 한국투자증권 KIS API 연동")
        st.caption("`.streamlit/secrets.toml`에 KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO를 설정해주세요.")

        kis_configured = bool(st.secrets.get("KIS_APP_KEY", ""))
        if not kis_configured:
            st.warning("KIS API 키가 설정되지 않았습니다. secrets.toml을 확인해주세요.")
        else:
            if st.button("🏦 보유종목 불러오기", type="primary", use_container_width=True):
                from kis_api import load_portfolio_from_kis
                portfolio = load_portfolio_from_kis()
                if portfolio:
                    st.session_state.portfolio = portfolio
                    with st.spinner("주가 데이터 수집 및 분석 중..."):
                        results = []
                        for item in portfolio:
                            result = analyze_stock(
                                item["ticker"], item["avg_price"], item["quantity"]
                            )
                            results.append(result)
                        st.session_state.analysis_results = results
                else:
                    st.warning("보유종목을 불러올 수 없습니다. API 설정을 확인해주세요.")

    # --- 분석 결과 표시 ---
    if st.session_state.analysis_results:
        st.markdown("---")

        # ===== 3단계: 포트폴리오 대시보드 =====
        render_portfolio_dashboard(st.session_state.analysis_results)

        st.markdown("---")

        # 헤더 + 모두 접기/펼치기
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown("## Objects")
        with col2:
            if st.button("모두 접기", use_container_width=True):
                st.session_state.expand_all = False
                st.rerun()
        with col3:
            if st.button("모두 펼치기", use_container_width=True):
                st.session_state.expand_all = True
                st.rerun()

        # 종목별 Expander
        for result in st.session_state.analysis_results:
            name = result.get("name", result.get("ticker", "Unknown"))
            sc = result.get("scorecard", {})
            type_label = f"[{sc.get('stock_type_label', '')}]" if sc.get("stock_type_label") else ""
            score_label = f" | {sc['total']}점 {sc['grade']}" if sc else ""
            with st.expander(f"**{name}** {type_label}{score_label}", expanded=st.session_state.expand_all):
                tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
                    ["📋 기본 분석", "📈 기술적 지표", "💰 펀더멘털/수급", "📰 뉴스", "🎯 전략/스코어", "📊 차트", "🔄 패턴"]
                )

                with tab1:
                    render_stock_table(result)

                with tab2:
                    render_indicators(result)

                with tab3:
                    render_fundamental(result)

                with tab4:
                    render_news(result)

                with tab5:
                    render_strategy(result)

                with tab6:
                    render_chart(result)

                with tab7:
                    render_pattern(result)

                # 매매일지 기록 버튼
                jcol1, jcol2, jcol3 = st.columns([1, 1, 3])
                with jcol1:
                    if st.button("📗 매수 기록", key=f"buy_{result.get('ticker_raw', name)}"):
                        save_journal_entry(result, "매수")
                        st.success(f"{name} 매수 기록 완료")
                with jcol2:
                    if st.button("📕 매도 기록", key=f"sell_{result.get('ticker_raw', name)}"):
                        save_journal_entry(result, "매도")
                        st.success(f"{name} 매도 기록 완료")

        # --- AI 종합 리포트 ---
        st.markdown("---")
        if st.button("📝 AI 종합 리포트 생성", use_container_width=True):
            with st.spinner("AI가 전 종목 분석 리포트를 작성 중입니다..."):
                context = build_ai_context(st.session_state.analysis_results)
                report = generate_ai_report(context)
                if report:
                    st.session_state["ai_report"] = report

        if st.session_state.get("ai_report"):
            with st.expander("📋 AI 종합 리포트", expanded=True):
                st.markdown(st.session_state["ai_report"])

        # --- 분석 데이터 내보내기 ---
        st.markdown("---")
        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            if st.button("📥 AI 분석용 데이터 내보내기 (JSON)", use_container_width=True):
                export = _build_export_data(st.session_state.analysis_results)
                st.session_state["export_json"] = export
        with exp_col2:
            if st.button("📥 AI 분석용 데이터 내보내기 (Markdown)", use_container_width=True):
                export_md = _build_export_markdown(st.session_state.analysis_results)
                st.session_state["export_md"] = export_md

        if st.session_state.get("export_json"):
            import json as _json
            json_str = _json.dumps(st.session_state["export_json"], ensure_ascii=False, indent=2, default=str)
            st.download_button(
                "💾 JSON 다운로드",
                data=json_str,
                file_name=f"portfolio_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                use_container_width=True,
            )
        if st.session_state.get("export_md"):
            st.download_button(
                "💾 Markdown 다운로드",
                data=st.session_state["export_md"],
                file_name=f"portfolio_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
                use_container_width=True,
            )

        # --- AI 고급 분석 (와이코프/엘리어트) ---
        st.markdown("---")
        st.markdown("### AI 고급 분석")
        adv_col1, adv_col2 = st.columns(2)

        with adv_col1:
            wyckoff_target = st.selectbox(
                "와이코프 분석 종목",
                [r["name"] for r in st.session_state.analysis_results if "error" not in r],
                key="wyckoff_select",
            )
            if st.button("🔍 와이코프 단계 분석", use_container_width=True):
                target_result = next(
                    (r for r in st.session_state.analysis_results if r.get("name") == wyckoff_target),
                    None,
                )
                if target_result:
                    with st.spinner("AI가 와이코프 단계를 분석 중..."):
                        context = build_ai_context([target_result])
                        wyckoff_prompt = (
                            f"{wyckoff_target}의 차트 데이터(가격, 거래량, 이평선, 기술적 지표)를 기반으로 "
                            "와이코프(Wyckoff) 방법론에 따라 현재 어떤 단계에 있는지 분석해주세요.\n\n"
                            "1. 현재 단계 판단 (매집/마크업/분배/마크다운 중)\n"
                            "2. 판단 근거 (가격 패턴, 거래량, 지지/저항)\n"
                            "3. 다음 예상 단계와 주의할 신호"
                        )
                        response = get_ai_response(context, wyckoff_prompt)
                        st.session_state["wyckoff_result"] = response

        with adv_col2:
            elliott_target = st.selectbox(
                "엘리어트 분석 종목",
                [r["name"] for r in st.session_state.analysis_results if "error" not in r],
                key="elliott_select",
            )
            if st.button("🌊 엘리어트 파동 분석", use_container_width=True):
                target_result = next(
                    (r for r in st.session_state.analysis_results if r.get("name") == elliott_target),
                    None,
                )
                if target_result:
                    with st.spinner("AI가 엘리어트 파동을 분석 중..."):
                        context = build_ai_context([target_result])
                        elliott_prompt = (
                            f"{elliott_target}의 차트 데이터(가격, 거래량, 이평선, 기술적 지표)를 기반으로 "
                            "엘리어트 파동 이론에 따라 현재 위치를 분석해주세요.\n\n"
                            "1. 현재 파동 위치 추정 (상승 5파/하락 3파 중 어디)\n"
                            "2. 판단 근거 (가격 구조, 되돌림 비율, 거래량 패턴)\n"
                            "3. 다음 파동 예상 방향과 주요 가격대"
                        )
                        response = get_ai_response(context, elliott_prompt)
                        st.session_state["elliott_result"] = response

        if st.session_state.get("wyckoff_result"):
            with st.expander("🔍 와이코프 분석 결과", expanded=True):
                st.markdown(st.session_state["wyckoff_result"])

        if st.session_state.get("elliott_result"):
            with st.expander("🌊 엘리어트 파동 분석 결과", expanded=True):
                st.markdown(st.session_state["elliott_result"])

        # --- AI 질의응답 ---
        st.markdown("---")
        st.markdown("### 위 데이터 기반 질의응답")

        # 채팅 히스토리 표시
        for msg in st.session_state.chat_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # 채팅 입력
        if prompt := st.chat_input("질문해보세요!"):
            st.session_state.chat_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # AI 응답
            with st.chat_message("assistant"):
                context = build_ai_context(st.session_state.analysis_results)
                ai_response = get_ai_response(context, prompt)
                st.markdown(ai_response)
                st.session_state.chat_messages.append({"role": "assistant", "content": ai_response})

        # --- 매매일지 ---
        st.markdown("---")
        with st.expander("📒 매매일지", expanded=False):
            render_journal()


MAX_GEMINI_RPM = 10  # 분당 최대 호출 횟수 (무료 티어 기준 여유 있게)
GEMINI_MAX_RETRIES = 2  # 429 에러 시 최대 재시도 횟수


def _check_gemini_rate_limit() -> tuple[bool, int]:
    """Gemini API 호출 가능 여부 확인. (허용 여부, 대기 초) 반환"""
    now = datetime.now()
    one_min_ago = now - timedelta(seconds=60)
    # 1분 이내 호출만 유지
    st.session_state.gemini_call_times = [
        t for t in st.session_state.gemini_call_times if t > one_min_ago
    ]
    if len(st.session_state.gemini_call_times) >= MAX_GEMINI_RPM:
        oldest = st.session_state.gemini_call_times[0]
        wait_sec = int((oldest + timedelta(seconds=60) - now).total_seconds()) + 1
        return False, max(wait_sec, 1)
    return True, 0


def _record_gemini_call():
    """Gemini API 호출 시각 기록"""
    st.session_state.gemini_call_times.append(datetime.now())


def _call_gemini_with_retry(generate_fn, max_retries: int = GEMINI_MAX_RETRIES):
    """Gemini API 호출 + 429 에러 시 exponential backoff 재시도"""
    for attempt in range(max_retries + 1):
        try:
            _record_gemini_call()
            return generate_fn()
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = "429" in err_str or "resource" in err_str or "quota" in err_str
            if is_rate_limit and attempt < max_retries:
                wait = 2 ** (attempt + 1)  # 2초, 4초
                time.sleep(wait)
                continue
            raise


def _get_gemini_client():
    """Gemini 클라이언트 초기화 (새 google-genai SDK, 구버전 폴백)"""
    api_key = st.secrets.get("GOOGLE_API_KEY", "")
    if not api_key:
        return None
    try:
        # 새 SDK (google-genai)
        import google.genai as genai
        return genai.Client(api_key=api_key)
    except (ImportError, AttributeError):
        pass
    try:
        # 구 SDK 폴백 (google-generativeai)
        import google.generativeai as genai_old
        genai_old.configure(api_key=api_key)
        return {"_legacy": True, "_module": genai_old}
    except (ImportError, AttributeError) as e:
        st.warning(f"Gemini 초기화 실패: google-genai 또는 google-generativeai 패키지를 설치해주세요.\n`pip install google-genai`")
        return None


def _gemini_generate(client, prompt: str, system_instruction: str = None):
    """새 SDK / 구 SDK 자동 분기 호출"""
    if isinstance(client, dict) and client.get("_legacy"):
        # 구 SDK (google-generativeai)
        genai_old = client["_module"]
        if system_instruction:
            model = genai_old.GenerativeModel(
                "gemini-2.5-flash",
                system_instruction=system_instruction,
            )
        else:
            model = genai_old.GenerativeModel("gemini-2.5-flash")
        return model.generate_content(prompt)
    else:
        # 새 SDK (google-genai)
        kwargs = {"model": "gemini-2.5-flash", "contents": prompt}
        if system_instruction:
            from google.genai import types
            kwargs["config"] = types.GenerateContentConfig(
                system_instruction=system_instruction,
            )
        return client.models.generate_content(**kwargs)


def generate_ai_report(context: str) -> str:
    """AI 종합 리포트 자동 생성 (Gemini API)"""
    client = _get_gemini_client()

    if not client:
        return (
            "AI 리포트 생성에는 Google API 키가 필요합니다.\n\n"
            "`.streamlit/secrets.toml`에 `GOOGLE_API_KEY`를 설정해주세요."
        )

    # Rate limit 체크
    allowed, wait_sec = _check_gemini_rate_limit()
    if not allowed:
        return (
            f"⏳ API 호출 제한에 도달했습니다. **{wait_sec}초 후** 다시 시도해주세요.\n\n"
            f"_(분당 최대 {MAX_GEMINI_RPM}회 호출 가능)_"
        )

    try:
        prompt = (
            "당신은 전문 주식 애널리스트입니다. 아래 포트폴리오 데이터를 분석하여 종합 리포트를 작성해주세요.\n\n"
            "【리포트 구성】\n"
            "1. **포트폴리오 총평** — 전체 포트폴리오 상태 요약 (2~3문장)\n"
            "2. **종목별 핵심 분석** — 각 종목의 기술적/밸류에이션/수급 핵심 포인트\n"
            "3. **주요 리스크 요인** — 주의해야 할 위험 요소\n"
            "4. **전략 제안** — 데이터 기반 전략적 시사점\n\n"
            "【규칙】\n"
            "- 한국어로 작성\n"
            "- 데이터 수치를 인용하며 근거 제시\n"
            "- 매수/매도 직접 권유 금지, 데이터 기반 분석만 제공\n"
            "- 마지막에 '※ 본 리포트는 데이터 기반 참고 자료이며, 투자 판단은 본인의 책임입니다.' 포함\n\n"
            f"아래 포트폴리오를 분석해주세요:\n\n{context}"
        )

        response = _call_gemini_with_retry(
            lambda: _gemini_generate(client, prompt)
        )
        return response.text
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "resource" in err_str or "quota" in err_str:
            return (
                "⚠️ Gemini API 호출 한도를 초과했습니다.\n\n"
                "- 무료 티어: 분당 ~10회, 일일 ~1,500회 제한\n"
                "- 잠시 후 다시 시도하거나, [Google AI Studio](https://aistudio.google.com/)에서 유료 플랜으로 업그레이드하세요."
            )
        return f"리포트 생성 중 오류가 발생했습니다: {str(e)}"


def get_ai_response(context: str, question: str) -> str:
    """AI 질의응답 (Gemini API 사용)"""
    client = _get_gemini_client()

    if not client:
        return _simple_ai_response(context, question)

    # Rate limit 체크
    allowed, wait_sec = _check_gemini_rate_limit()
    if not allowed:
        return (
            f"⏳ API 호출 제한에 도달했습니다. **{wait_sec}초 후** 다시 시도해주세요.\n\n"
            f"_(분당 최대 {MAX_GEMINI_RPM}회 호출 가능)_"
        )

    try:
        system_instruction = (
            "당신은 주식 및 경제 분석 전문가입니다. 반드시 아래 규칙을 따르세요:\n\n"
            "【역할】\n"
            "- 한국 주식시장, 글로벌 경제, 기술적 분석, 기본적 분석, 포트폴리오 관리에 대한 질문에만 답변합니다.\n"
            "- 아래 제공된 포트폴리오 데이터를 기반으로 데이터 중심의 객관적 분석을 제공합니다.\n"
            "- 한국어로 답변합니다.\n\n"
            "【금지 사항】\n"
            "- 주식, 경제, 금융, 투자와 무관한 질문에는 '저는 주식·경제 분석 전용 AI입니다. "
            "주식이나 경제 관련 질문을 해주세요.'라고 답변하세요.\n"
            "- 특정 종목의 매수/매도를 직접 권유하지 마세요. 데이터 기반 분석만 제공하세요.\n"
            "- 확정적 수익률 예측이나 보장 발언을 하지 마세요.\n\n"
            "【답변 스타일】\n"
            "- 기술적 지표(RSI, MACD, 볼린저밴드 등)와 기본적 지표(PER, PBR, ROE 등)를 활용해 근거를 제시하세요.\n"
            "- 가능한 경우 수치와 데이터를 인용하세요.\n"
            "- 답변 마지막에 '※ 본 분석은 데이터 기반 참고 자료이며, 투자 판단은 본인의 책임입니다.'를 포함하세요.\n\n"
            f"【포트폴리오 데이터】\n{context}"
        )

        # 이전 대화 내역을 컨텍스트에 포함
        history_text = ""
        recent_history = st.session_state.chat_messages[-10:]
        for msg in recent_history:
            role = "사용자" if msg["role"] == "user" else "AI"
            history_text += f"\n{role}: {msg['content']}\n"

        user_prompt = question
        if history_text.strip():
            user_prompt = f"【이전 대화】\n{history_text}\n\n사용자: {question}"

        response = _call_gemini_with_retry(
            lambda: _gemini_generate(client, user_prompt, system_instruction=system_instruction)
        )
        return response.text
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "resource" in err_str or "quota" in err_str:
            return (
                "⚠️ Gemini API 호출 한도를 초과했습니다. 잠시 후 다시 시도해주세요.\n\n"
                "_(무료 티어: 분당 ~10회, 일일 ~1,500회 제한)_"
            )
        return _simple_ai_response(context, question)


def _simple_ai_response(context: str, question: str) -> str:
    """AI API 키가 없을 때 기본 룰 기반 응답"""

    # 컨텍스트에서 종목 정보 추출
    results = st.session_state.analysis_results
    if not results:
        return "분석 데이터가 없습니다. 먼저 종목을 분석해주세요."

    # 특정 종목 언급 확인
    mentioned = None
    for r in results:
        if "error" not in r and (r["name"] in question or r["ticker"] in question):
            mentioned = r
            break

    if mentioned:
        return (
            f"**{mentioned['name']}** 분석 요약:\n\n"
            f"- 현재가: {mentioned['current_price']:,}원 (평균단가 대비 {mentioned['profit_rate']}%)\n"
            f"- 이평 분류: {mentioned['ma_classification']}\n"
            f"- 거래량 분류: {mentioned['vol_classification']}\n"
            f"- **종합: {mentioned['overall']}**\n\n"
            f"_더 정확한 AI 분석을 원하시면 Google API 키를 설정해주세요._"
        )

    # 전체 포트폴리오 요약
    summary = "**포트폴리오 요약:**\n\n"
    for r in results:
        if "error" not in r:
            emoji = "🟢" if r["profit_rate"] > 0 else "🔴" if r["profit_rate"] < 0 else "⚪"
            summary += f"{emoji} **{r['name']}**: {r['profit_rate']}% | {r['overall']}\n"

    summary += "\n_더 정확한 AI 분석을 원하시면 Google API 키를 설정해주세요._"
    return summary


if __name__ == "__main__":
    main()
