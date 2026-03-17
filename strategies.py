# © 2026 donghapro. All Rights Reserved.
"""
5단계: 고급 전략 시그널 + 종합 스코어카드
- 미너비니 추세 템플릿
- 한국형 CANSLIM
- 터틀 트레이딩 시그널
- 종합 스코어카드 (100점 만점)
"""
import pandas as pd
import numpy as np


# =============================================================
# 미너비니 추세 템플릿
# =============================================================

def check_minervini(df: pd.DataFrame, current_price: int) -> dict:
    """미너비니 추세 템플릿 8개 조건 체크"""
    close = df["종가"]
    conditions = {}

    # 장기 이평 계산
    ma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None
    ma150 = close.rolling(min(150, len(close))).mean().iloc[-1] if len(close) >= 50 else None
    ma200 = close.rolling(min(200, len(close))).mean().iloc[-1] if len(close) >= 50 else None

    # 200일 이평 1개월 전
    try:
        ma200_series = close.rolling(min(200, len(close))).mean()
        ma200_1m = ma200_series.iloc[-20] if len(ma200_series) >= 20 and len(close) >= 70 else None
        if ma200_1m is not None and pd.isna(ma200_1m):
            ma200_1m = None
    except (IndexError, KeyError):
        ma200_1m = None

    # 52주 고저
    high_52w = close.max()
    low_52w = close.min()

    # 1. 현재가 > 150일 이평
    conditions["현재가 > MA150"] = (
        current_price > ma150 if ma150 else None
    )

    # 2. 150일 이평 > 200일 이평
    conditions["MA150 > MA200"] = (
        ma150 > ma200 if ma150 and ma200 else None
    )

    # 3. 200일 이평 최소 1개월간 상승
    conditions["MA200 1개월 상승"] = (
        ma200 > ma200_1m if ma200 and ma200_1m else None
    )

    # 4. 50일 이평 > 150일 이평 > 200일 이평
    conditions["MA50 > MA150 > MA200"] = (
        ma50 > ma150 > ma200 if ma50 and ma150 and ma200 else None
    )

    # 5. 현재가 > 50일 이평
    conditions["현재가 > MA50"] = (
        current_price > ma50 if ma50 else None
    )

    # 6. 현재가 > 52주 최저가 +30%
    conditions["52주 저가 +30% 이상"] = (
        current_price > low_52w * 1.3 if low_52w else None
    )

    # 7. 현재가 > 52주 최고가 -25%
    conditions["52주 고가 -25% 이내"] = (
        current_price > high_52w * 0.75 if high_52w else None
    )

    # 8. 상대강도 (RSI 기반 간이 판단)
    if len(close) >= 14:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean().iloc[-1]
        rs = gain / loss if loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))
        conditions["RS 강도 70+"] = rsi >= 50  # 완화된 기준 (한국 시장)
    else:
        conditions["RS 강도 70+"] = None

    # 집계
    valid = {k: v for k, v in conditions.items() if v is not None}
    passed = sum(1 for v in valid.values() if v)
    total = len(valid)

    score = round(passed / total * 100) if total > 0 else 0

    return {
        "conditions": conditions,
        "passed": passed,
        "total": total,
        "score": score,
    }


# =============================================================
# 한국형 CANSLIM
# =============================================================

def check_canslim(df: pd.DataFrame, fundamental: dict, investor: dict) -> dict:
    """한국형 CANSLIM 체크 (데이터 기반 간이 평가)"""
    scores = {}

    # C - 당기순이익 (EPS > 0 여부로 간이 판단)
    eps = fundamental.get("eps")
    if eps and eps > 0:
        scores["C (당기이익)"] = {"score": 80, "detail": f"EPS {eps:,}원 (양수)"}
    elif eps:
        scores["C (당기이익)"] = {"score": 20, "detail": f"EPS {eps:,}원 (적자)"}
    else:
        scores["C (당기이익)"] = {"score": 50, "detail": "데이터 없음"}

    # A - 연간 이익 (ROE 기반)
    roe = fundamental.get("roe")
    if roe and roe > 15:
        scores["A (연간이익)"] = {"score": 90, "detail": f"ROE {roe}% (우수)"}
    elif roe and roe > 8:
        scores["A (연간이익)"] = {"score": 60, "detail": f"ROE {roe}% (보통)"}
    elif roe:
        scores["A (연간이익)"] = {"score": 30, "detail": f"ROE {roe}% (저조)"}
    else:
        scores["A (연간이익)"] = {"score": 50, "detail": "데이터 없음"}

    # N - 신고가 근접 (52주 위치)
    close = df["종가"]
    high_52w = close.max()
    current = close.iloc[-1]
    pct_from_high = (current / high_52w * 100) if high_52w > 0 else 0
    if pct_from_high >= 90:
        scores["N (신고가)"] = {"score": 90, "detail": f"52주 고가의 {pct_from_high:.0f}%"}
    elif pct_from_high >= 75:
        scores["N (신고가)"] = {"score": 60, "detail": f"52주 고가의 {pct_from_high:.0f}%"}
    else:
        scores["N (신고가)"] = {"score": 30, "detail": f"52주 고가의 {pct_from_high:.0f}%"}

    # S - 수급 (외국인+기관)
    if investor:
        fg = investor.get("foreigner", {})
        inst = investor.get("institution", {})
        fg_buy = fg.get("recent_5d", 0) > 0 if fg else False
        inst_buy = inst.get("recent_5d", 0) > 0 if inst else False
        if fg_buy and inst_buy:
            scores["S (수급)"] = {"score": 90, "detail": "외국인+기관 순매수"}
        elif fg_buy or inst_buy:
            scores["S (수급)"] = {"score": 60, "detail": "일부 순매수"}
        else:
            scores["S (수급)"] = {"score": 30, "detail": "순매도 우위"}
    else:
        scores["S (수급)"] = {"score": 50, "detail": "데이터 없음"}

    # L - 업종 내 상대강도 (RSI 비교 간이)
    if len(close) >= 20:
        ret_20d = (close.iloc[-1] / close.iloc[-20] - 1) * 100
        if ret_20d > 5:
            scores["L (선도주)"] = {"score": 80, "detail": f"20일 수익률 {ret_20d:.1f}%"}
        elif ret_20d > 0:
            scores["L (선도주)"] = {"score": 55, "detail": f"20일 수익률 {ret_20d:.1f}%"}
        else:
            scores["L (선도주)"] = {"score": 30, "detail": f"20일 수익률 {ret_20d:.1f}%"}
    else:
        scores["L (선도주)"] = {"score": 50, "detail": "데이터 부족"}

    # M - 시장 방향 (KOSPI 대용 → 종목 자체 추세)
    if len(close) >= 50:
        ma50 = close.rolling(50).mean().iloc[-1]
        if current > ma50:
            scores["M (시장방향)"] = {"score": 70, "detail": "50일 이평 위 (상승 추세)"}
        else:
            scores["M (시장방향)"] = {"score": 30, "detail": "50일 이평 아래 (하락 추세)"}
    else:
        scores["M (시장방향)"] = {"score": 50, "detail": "데이터 부족"}

    # 종합 점수
    total = round(sum(s["score"] for s in scores.values()) / len(scores))

    # 등급
    if total >= 80:
        grade = "A"
    elif total >= 65:
        grade = "B"
    elif total >= 50:
        grade = "C"
    elif total >= 35:
        grade = "D"
    else:
        grade = "F"

    return {
        "scores": scores,
        "total": total,
        "grade": grade,
    }


# =============================================================
# 터틀 트레이딩
# =============================================================

def check_turtle(df: pd.DataFrame, current_price: int) -> dict:
    """터틀 트레이딩 시그널"""
    close = df["종가"]
    high = df["고가"]
    low = df["저가"]

    signals = {}

    # 20일 돌파 (단기)
    if len(high) >= 20:
        high_20 = high.tail(20).max()
        low_10 = low.tail(10).min() if len(low) >= 10 else low.min()
        signals["단기 진입 (20일 고가 돌파)"] = current_price >= high_20
        signals["단기 청산 (10일 저가 이탈)"] = current_price <= low_10

    # 55일 돌파 (장기)
    if len(high) >= 55:
        high_55 = high.tail(55).max()
        low_20 = low.tail(20).min()
        signals["장기 진입 (55일 고가 돌파)"] = current_price >= high_55
        signals["장기 청산 (20일 저가 이탈)"] = current_price <= low_20

    # ATR 기반 포지션 사이징
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(20).mean().iloc[-1] if len(tr) >= 20 else None

    position_size = None
    if atr and atr > 0:
        # 계좌의 1% 리스크 기준 (가상 계좌 1억원)
        account_size = 100_000_000
        risk_per_trade = account_size * 0.01
        position_size = int(risk_per_trade / atr)

    active_signals = [k for k, v in signals.items() if v and "진입" in k]

    if any("장기 진입" in s for s in active_signals):
        classification = "장기 돌파 시그널 (강한 매수)"
    elif any("단기 진입" in s for s in active_signals):
        classification = "단기 돌파 시그널 (매수 고려)"
    elif any("청산" in k for k, v in signals.items() if v):
        classification = "청산 시그널 (매도 고려)"
    else:
        classification = "대기 (시그널 없음)"

    return {
        "signals": signals,
        "atr": round(atr) if atr else None,
        "position_size": position_size,
        "classification": classification,
    }


# =============================================================
# 종목 유형 자동 분류 (Phase 1)
# =============================================================

# 유형별 스코어카드 가중치 프리셋
WEIGHT_PRESETS = {
    "growth": {
        "기술적 분석": 0.25,
        "밸류에이션": 0.10,
        "수급": 0.15,
        "리스크": 0.15,
        "전략 시그널": 0.15,
        "뉴스 감성": 0.20,
    },
    "value": {
        "기술적 분석": 0.20,
        "밸류에이션": 0.30,
        "수급": 0.15,
        "리스크": 0.10,
        "전략 시그널": 0.10,
        "뉴스 감성": 0.15,
    },
    "dividend": {
        "기술적 분석": 0.15,
        "밸류에이션": 0.25,
        "수급": 0.10,
        "리스크": 0.10,
        "전략 시그널": 0.10,
        "뉴스 감성": 0.10,
        "배당 품질": 0.20,
    },
    "other": {  # 기본 (기존과 동일)
        "기술적 분석": 0.25,
        "밸류에이션": 0.25,
        "수급": 0.15,
        "리스크": 0.10,
        "전략 시그널": 0.10,
        "뉴스 감성": 0.15,
    },
}

STOCK_TYPE_LABELS = {
    "growth": "성장주",
    "value": "가치주",
    "dividend": "배당주",
    "other": "일반",
}


def classify_stock_type(fund: dict) -> str:
    """종목 유형 자동 분류: growth / value / dividend / other

    분류 기준:
    - 성장주: PER >= 30 AND 배당수익률 < 1%
    - 가치주: PBR < 1.5 AND PER < 15 AND 배당수익률 < 3%
    - 배당주: 배당수익률 >= 3%
    - 기타: 위 조건 미충족
    """
    per = fund.get("per")
    pbr = fund.get("pbr")
    div_yield = fund.get("div_yield") or 0

    # 배당주 우선 판정 (배당수익률이 가장 명확한 기준)
    if div_yield >= 3:
        return "dividend"

    # 성장주
    if per and per >= 30 and div_yield < 1:
        return "growth"

    # 가치주
    if pbr and pbr < 1.5 and per and per < 15 and div_yield < 3:
        return "value"

    return "other"


def _redistribute_weights(weights: dict, exclude_keys: list) -> dict:
    """제거할 항목을 빼고 나머지 가중치를 비례 재분배"""
    filtered = {k: v for k, v in weights.items() if k not in exclude_keys}
    total = sum(filtered.values())
    if total <= 0:
        return filtered
    return {k: round(v / total, 4) for k, v in filtered.items()}


# =============================================================
# 성장주 밸류에이션 (PEG / PSR / EV-EBITDA 섹터 비교)
# =============================================================

def calc_growth_valuation_score(fund: dict) -> int:
    """성장주용 밸류에이션 점수 (0~100)

    PEG, PSR(매출 대비), EV/EBITDA를 섹터 평균 대비로 평가.
    yfinance info에서 가져온 값이 fund에 포함되어 있어야 함.
    """
    sub_scores = []

    # PEG
    peg = fund.get("peg", {})
    peg_val = peg.get("peg") if isinstance(peg, dict) else None
    if peg_val and peg_val > 0:
        if peg_val < 0.5:
            sub_scores.append(90)
        elif peg_val < 1.0:
            sub_scores.append(75)
        elif peg_val <= 1.5:
            sub_scores.append(55)
        elif peg_val <= 2.0:
            sub_scores.append(35)
        else:
            sub_scores.append(20)

    # PSR (Price-to-Sales)
    psr = fund.get("psr")
    if psr and psr > 0:
        if psr < 3:
            sub_scores.append(80)
        elif psr < 8:
            sub_scores.append(60)
        elif psr < 15:
            sub_scores.append(40)
        else:
            sub_scores.append(20)

    # EV/EBITDA
    ev_ebitda = fund.get("ev_ebitda")
    if ev_ebitda and ev_ebitda > 0:
        if ev_ebitda < 10:
            sub_scores.append(80)
        elif ev_ebitda < 20:
            sub_scores.append(60)
        elif ev_ebitda < 35:
            sub_scores.append(40)
        else:
            sub_scores.append(20)

    if not sub_scores:
        return 50  # 데이터 없으면 중립

    return round(sum(sub_scores) / len(sub_scores))


def calc_dividend_quality_score(fund: dict) -> int:
    """배당주용 배당 품질 점수 (0~100)

    배당수익률, 배당성향(payout ratio) 등을 종합 평가.
    """
    score = 50

    div_yield = fund.get("div_yield") or 0
    if div_yield >= 5:
        score += 25
    elif div_yield >= 3:
        score += 15
    elif div_yield >= 2:
        score += 5

    payout = fund.get("payout_ratio")
    if payout is not None:
        if 30 <= payout <= 60:
            score += 15  # 건전한 배당성향
        elif payout < 30:
            score += 5   # 낮지만 성장 재투자 가능
        elif payout > 80:
            score -= 10  # 과도한 배당

    return max(0, min(100, score))


# =============================================================
# 종합 스코어카드
# =============================================================

def calc_scorecard(result: dict) -> dict:
    """종합 스코어카드 계산 (100점 만점)

    Phase 1 개선:
    - 종목 유형(성장주/가치주/배당주)에 따라 가중치 자동 전환
    - 성장주: S-RIM 대신 PEG/PSR/EV-EBITDA 상대 비교
    - 수급 데이터 없으면 해당 항목 제거 후 가중치 재분배
    """
    scores = {}
    fund = result.get("fundamental", {})

    # --- 종목 유형 분류 ---
    stock_type = classify_stock_type(fund)

    # --- 기술적 분석 ---
    tech_score = 50

    ma_class = result.get("ma_classification", "")
    if "정배열" in ma_class:
        tech_score += 20
    elif "역배열" in ma_class:
        tech_score -= 20
    elif "정배열 전환" in ma_class:
        tech_score += 10

    ind = result.get("indicators", {})
    rsi = ind.get("rsi", {}).get("value")
    if rsi:
        if 40 <= rsi <= 60:
            tech_score += 5
        elif rsi < 30:
            tech_score += 15
        elif rsi > 70:
            tech_score -= 10

    macd = ind.get("macd", {})
    if "골든크로스" in macd.get("classification", ""):
        tech_score += 15
    elif "데드크로스" in macd.get("classification", ""):
        tech_score -= 15
    elif "상승" in macd.get("classification", ""):
        tech_score += 5

    tech_score = max(0, min(100, tech_score))
    scores["기술적 분석"] = tech_score

    # --- 밸류에이션 (유형별 분기) ---
    if stock_type == "growth":
        val_score = calc_growth_valuation_score(fund)
    else:
        # 가치주 / 배당주 / 기타 → 기존 S-RIM + PER/PBR 로직
        val_score = 50
        per = fund.get("per")
        if per:
            if per < 10:
                val_score += 20
            elif per < 15:
                val_score += 10
            elif per > 30:
                val_score -= 15

        pbr = fund.get("pbr")
        if pbr:
            if pbr < 1:
                val_score += 15
            elif pbr < 2:
                val_score += 5
            elif pbr > 4:
                val_score -= 10

        srim = fund.get("srim", {})
        if srim.get("neutral") and result.get("current_price"):
            gap = (srim["neutral"] - result["current_price"]) / result["current_price"]
            if gap > 0.2:
                val_score += 15
            elif gap > 0:
                val_score += 5
            elif gap < -0.2:
                val_score -= 15

        val_score = max(0, min(100, val_score))

    scores["밸류에이션"] = val_score

    # --- 수급 ---
    supply_class = fund.get("supply_class", "")
    has_supply_data = "미제공" not in supply_class and "없음" not in supply_class

    if has_supply_data:
        supply_score = 50
        if "순매수" in supply_class and "연속" in supply_class:
            supply_score += 25
        elif "매수 우위" in supply_class:
            supply_score += 15
        elif "매도 우위" in supply_class:
            supply_score -= 15
        elif "연속" in supply_class and "순매도" in supply_class:
            supply_score -= 25
        supply_score = max(0, min(100, supply_score))
        scores["수급"] = supply_score

    # --- 리스크 ---
    risk_score = 50
    w52 = fund.get("week52", {})
    if w52.get("position_pct") is not None:
        pos = w52["position_pct"]
        if 30 <= pos <= 70:
            risk_score += 10
        elif pos > 90:
            risk_score -= 10
        elif pos < 10:
            risk_score -= 5

    risk_score = max(0, min(100, risk_score))
    scores["리스크"] = risk_score

    # --- 전략 시그널 ---
    strategy_score = 50
    minervini = result.get("minervini", {})
    if minervini.get("score") is not None:
        strategy_score = (strategy_score + minervini["score"]) // 2
    canslim = result.get("canslim", {})
    if canslim.get("total") is not None:
        strategy_score = (strategy_score + canslim["total"]) // 2
    scores["전략 시그널"] = max(0, min(100, strategy_score))

    # --- 뉴스 감성 ---
    news_score = result.get("news_sentiment_score", 50)
    scores["뉴스 감성"] = max(0, min(100, news_score))

    # --- 배당 품질 (배당주 전용) ---
    if stock_type == "dividend":
        scores["배당 품질"] = calc_dividend_quality_score(fund)

    # --- 가중치 결정 ---
    weights = dict(WEIGHT_PRESETS.get(stock_type, WEIGHT_PRESETS["other"]))

    # 수급 데이터 없으면 동적 제거 후 재분배
    exclude = []
    if not has_supply_data:
        exclude.append("수급")
    # 배당 품질은 배당주가 아니면 가중치에 없으므로 scores에서도 제거 불필요
    if stock_type != "dividend" and "배당 품질" in weights:
        exclude.append("배당 품질")

    if exclude:
        weights = _redistribute_weights(weights, exclude)

    # scores에 없는 가중치 항목 제거 (안전장치)
    weights = {k: v for k, v in weights.items() if k in scores}
    # 재정규화
    w_total = sum(weights.values())
    if w_total > 0 and abs(w_total - 1.0) > 0.001:
        weights = {k: round(v / w_total, 4) for k, v in weights.items()}

    # --- 가중 평균 ---
    total = sum(scores[k] * weights[k] for k in weights)
    total = round(total)

    # 등급
    if total >= 80:
        grade = "★★★★★"
    elif total >= 65:
        grade = "★★★★☆"
    elif total >= 50:
        grade = "★★★☆☆"
    elif total >= 35:
        grade = "★★☆☆☆"
    else:
        grade = "★☆☆☆☆"

    return {
        "stock_type": stock_type,
        "stock_type_label": STOCK_TYPE_LABELS[stock_type],
        "scores": scores,
        "weights": weights,
        "total": total,
        "grade": grade,
    }
