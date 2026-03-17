# © 2026 donghapro. All Rights Reserved.
"""
2단계: 기술적 분석 지표 계산 모듈
RSI, MACD, 볼린저 밴드, 스토캐스틱, ADX, ATR, OBV, MFI
"""
import pandas as pd
import numpy as np


def calc_rsi(df: pd.DataFrame, period: int = 14) -> dict:
    """RSI (상대강도지수) 계산"""
    close = df["종가"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_value = round(rsi.iloc[-1], 2) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else None

    if rsi_value is None:
        classification = "데이터 부족"
    elif rsi_value >= 70:
        classification = "과매수 구간 (매도 주의)"
    elif rsi_value >= 60:
        classification = "강세 구간"
    elif rsi_value >= 40:
        classification = "중립 구간"
    elif rsi_value >= 30:
        classification = "약세 구간"
    else:
        classification = "과매도 구간 (반등 가능)"

    return {
        "value": rsi_value,
        "series": rsi,
        "classification": classification,
    }


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD 계산"""
    close = df["종가"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    macd_val = round(macd_line.iloc[-1], 2) if not pd.isna(macd_line.iloc[-1]) else None
    signal_val = round(signal_line.iloc[-1], 2) if not pd.isna(signal_line.iloc[-1]) else None
    hist_val = round(histogram.iloc[-1], 2) if not pd.isna(histogram.iloc[-1]) else None

    # 크로스 판단 (최근 5일 내, 가장 최근 크로스 우선)
    cross = "없음"
    if len(histogram) >= 5:
        recent = histogram.tail(5)
        for i in range(len(recent) - 1, 0, -1):  # 최신부터 역순 탐색
            prev = recent.iloc[i - 1]
            curr = recent.iloc[i]
            if pd.isna(prev) or pd.isna(curr):
                continue
            if prev < 0 and curr >= 0:
                cross = "골든크로스 발생"
                break
            elif prev > 0 and curr <= 0:
                cross = "데드크로스 발생"
                break

    if macd_val is None:
        classification = "데이터 부족"
    elif cross != "없음":
        classification = cross
    elif hist_val and hist_val > 0:
        classification = "상승 모멘텀"
    elif hist_val and hist_val < 0:
        classification = "하락 모멘텀"
    else:
        classification = "모멘텀 전환 중"

    return {
        "macd": macd_val,
        "signal": signal_val,
        "histogram": hist_val,
        "cross": cross,
        "macd_series": macd_line,
        "signal_series": signal_line,
        "histogram_series": histogram,
        "classification": classification,
    }


def calc_bollinger(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0) -> dict:
    """볼린저 밴드 계산"""
    close = df["종가"]
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std

    current_price = close.iloc[-1]
    upper_val = round(upper.iloc[-1]) if not pd.isna(upper.iloc[-1]) else None
    middle_val = round(sma.iloc[-1]) if not pd.isna(sma.iloc[-1]) else None
    lower_val = round(lower.iloc[-1]) if not pd.isna(lower.iloc[-1]) else None

    # 밴드폭 (스퀴즈 감지)
    bandwidth = None
    squeeze = False
    if upper_val and lower_val and middle_val and middle_val > 0:
        bandwidth = round((upper_val - lower_val) / middle_val * 100, 2)
        # 최근 120일 밴드폭과 비교
        bw_series = (upper - lower) / sma * 100
        if len(bw_series.dropna()) >= 20:
            avg_bw = bw_series.tail(120).mean()
            if bandwidth < avg_bw * 0.5:
                squeeze = True

    # 위치 판단
    if upper_val and lower_val:
        if current_price >= upper_val:
            position = "상단밴드 이탈 (과매수)"
        elif current_price <= lower_val:
            position = "하단밴드 이탈 (과매도)"
        elif middle_val and current_price >= middle_val:
            position = "중심선 위 (강세)"
        else:
            position = "중심선 아래 (약세)"
    else:
        position = "데이터 부족"

    classification = position
    if squeeze:
        classification += " + 스퀴즈 (큰 움직임 임박)"

    return {
        "upper": upper_val,
        "middle": middle_val,
        "lower": lower_val,
        "bandwidth": bandwidth,
        "squeeze": squeeze,
        "upper_series": upper,
        "middle_series": sma,
        "lower_series": lower,
        "classification": classification,
    }


def calc_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> dict:
    """스토캐스틱 계산"""
    high = df["고가"]
    low = df["저가"]
    close = df["종가"]

    low_min = low.rolling(k_period).min()
    high_max = high.rolling(k_period).max()

    denom = high_max - low_min
    k = ((close - low_min) / denom.replace(0, np.nan)) * 100
    d = k.rolling(d_period).mean()

    k_val = round(k.iloc[-1], 2) if not pd.isna(k.iloc[-1]) else None
    d_val = round(d.iloc[-1], 2) if not pd.isna(d.iloc[-1]) else None

    # 크로스 판단
    cross = "없음"
    if len(k) >= 5 and len(d) >= 5:
        for i in range(-4, 0):
            if k.iloc[i - 1] < d.iloc[i - 1] and k.iloc[i] >= d.iloc[i]:
                cross = "골든크로스"
            elif k.iloc[i - 1] > d.iloc[i - 1] and k.iloc[i] <= d.iloc[i]:
                cross = "데드크로스"

    if k_val is None:
        classification = "데이터 부족"
    elif k_val >= 80:
        classification = "과매수 구간"
    elif k_val <= 20:
        classification = "과매도 구간"
    else:
        classification = "중립 구간"

    if cross != "없음":
        classification += f" ({cross})"

    return {
        "k": k_val,
        "d": d_val,
        "cross": cross,
        "k_series": k,
        "d_series": d,
        "classification": classification,
    }


def calc_adx(df: pd.DataFrame, period: int = 14) -> dict:
    """ADX (평균방향지수) 계산"""
    high = df["고가"]
    low = df["저가"]
    close = df["종가"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > 0) & (plus_dm > minus_dm), 0.0)
    minus_dm = minus_dm.where((minus_dm > 0) & (minus_dm > plus_dm), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)

    di_sum = plus_di + minus_di
    dx = (plus_di - minus_di).abs() / di_sum.replace(0, np.nan) * 100
    adx = dx.ewm(span=period, adjust=False).mean()

    adx_val = round(adx.iloc[-1], 2) if not pd.isna(adx.iloc[-1]) else None
    plus_di_val = round(plus_di.iloc[-1], 2) if not pd.isna(plus_di.iloc[-1]) else None
    minus_di_val = round(minus_di.iloc[-1], 2) if not pd.isna(minus_di.iloc[-1]) else None

    if adx_val is None:
        classification = "데이터 부족"
    elif adx_val >= 25:
        direction = "상승" if plus_di_val and minus_di_val and plus_di_val > minus_di_val else "하락"
        classification = f"강한 {direction} 추세 (ADX {adx_val})"
    elif adx_val >= 20:
        classification = f"약한 추세 (ADX {adx_val})"
    else:
        classification = f"횡보/추세 없음 (ADX {adx_val})"

    return {
        "adx": adx_val,
        "plus_di": plus_di_val,
        "minus_di": minus_di_val,
        "adx_series": adx,
        "plus_di_series": plus_di,
        "minus_di_series": minus_di,
        "classification": classification,
    }


def calc_atr(df: pd.DataFrame, period: int = 14) -> dict:
    """ATR (평균진폭) 계산"""
    high = df["고가"]
    low = df["저가"]
    close = df["종가"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    raw_atr = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else None
    atr_val = round(raw_atr) if raw_atr is not None else None

    current_price = close.iloc[-1]
    atr_pct = round(raw_atr / current_price * 100, 2) if raw_atr and current_price else None

    # 손절/익절 라인
    stop_loss = round(current_price - 2 * raw_atr) if raw_atr else None
    take_profit = round(current_price + 3 * raw_atr) if raw_atr else None

    return {
        "atr": atr_val,
        "atr_pct": atr_pct,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "atr_series": atr,
        "classification": f"일평균 변동폭 {atr_pct}%" if atr_pct else "데이터 부족",
    }


def calc_obv(df: pd.DataFrame) -> dict:
    """OBV (On Balance Volume) 계산"""
    close = df["종가"]
    volume = df["거래량"]

    obv = pd.Series(0, index=df.index, dtype=float)
    for i in range(1, len(df)):
        if close.iloc[i] > close.iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] + volume.iloc[i]
        elif close.iloc[i] < close.iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] - volume.iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i - 1]

    # OBV 추세 판단 (20일 이평 비교)
    obv_ma = obv.rolling(20).mean()
    obv_val = obv.iloc[-1]
    obv_ma_val = obv_ma.iloc[-1] if not pd.isna(obv_ma.iloc[-1]) else None

    if obv_ma_val is not None:
        if obv_val > obv_ma_val:
            # 가격과 OBV 방향 비교
            price_up = close.iloc[-1] > close.iloc[-20] if len(close) >= 20 else True
            if price_up:
                classification = "OBV 상승 + 가격 상승 (추세 확인)"
            else:
                classification = "OBV 상승 + 가격 하락 (매집 가능성)"
        else:
            price_down = close.iloc[-1] < close.iloc[-20] if len(close) >= 20 else True
            if price_down:
                classification = "OBV 하락 + 가격 하락 (추세 확인)"
            else:
                classification = "OBV 하락 + 가격 상승 (분산 가능성)"
    else:
        classification = "데이터 부족"

    return {
        "obv": int(obv_val),
        "obv_series": obv,
        "obv_ma_series": obv_ma,
        "classification": classification,
    }


def calc_mfi(df: pd.DataFrame, period: int = 14) -> dict:
    """MFI (자금흐름지수) 계산"""
    high = df["고가"]
    low = df["저가"]
    close = df["종가"]
    volume = df["거래량"]

    tp = (high + low + close) / 3
    raw_mf = tp * volume

    tp_diff = tp.diff()
    pos_mf = raw_mf.where(tp_diff > 0, 0.0).rolling(period).sum()
    neg_mf = raw_mf.where(tp_diff < 0, 0.0).rolling(period).sum()

    mfr = pos_mf / neg_mf.replace(0, np.nan)
    mfi = 100 - (100 / (1 + mfr))

    mfi_val = round(mfi.iloc[-1], 2) if not pd.isna(mfi.iloc[-1]) else None

    if mfi_val is None:
        classification = "데이터 부족"
    elif mfi_val >= 80:
        classification = "자금 과다 유입 (과매수)"
    elif mfi_val >= 60:
        classification = "자금 유입 중 (강세)"
    elif mfi_val >= 40:
        classification = "자금 흐름 중립"
    elif mfi_val >= 20:
        classification = "자금 유출 중 (약세)"
    else:
        classification = "자금 과다 유출 (과매도)"

    return {
        "value": mfi_val,
        "series": mfi,
        "classification": classification,
    }


def interpret_indicator_conflicts(indicators: dict, ma_class: str) -> dict:
    """복수 기술적 지표가 상충할 때 우선순위 트리로 종합 판정

    Returns:
        {"interpretation": 해석 문장, "confidence": 높음/중간/낮음}
    """
    rsi_val = indicators.get("rsi", {}).get("value")
    macd_class = indicators.get("macd", {}).get("classification", "")
    obv_class = indicators.get("obv", {}).get("classification", "")
    mfi_val = indicators.get("mfi", {}).get("value")
    adx_val = indicators.get("adx", {}).get("adx")
    bollinger_class = indicators.get("bollinger", {}).get("classification", "")

    is_ma_up = "정배열" in ma_class
    is_ma_down = "역배열" in ma_class
    is_golden = "골든크로스" in macd_class
    is_dead = "데드크로스" in macd_class
    is_obv_up = "상승" in obv_class
    is_obv_down = "하락" in obv_class
    is_rsi_over = rsi_val and rsi_val > 70
    is_rsi_under = rsi_val and rsi_val < 30
    is_mfi_over = mfi_val and mfi_val > 80
    is_mfi_under = mfi_val and mfi_val < 20
    is_adx_weak = adx_val and adx_val < 20
    vol_down = "거래량 감소" in indicators.get("obv", {}).get("classification", "") or "분산" in obv_class

    # --- 우선순위 트리 (상충 패턴부터 매칭) ---

    # 1. 횡보 구간 (ADX < 20 + 지표 중립)
    if is_adx_weak and not is_golden and not is_dead and not is_rsi_over and not is_rsi_under:
        return {
            "interpretation": "방향성 부재 — 횡보 구간, 관망 권장",
            "confidence": "중간",
        }

    # 2. 역배열 + 골든크로스 + OBV 상승 → 반등 시도
    if is_ma_down and is_golden and is_obv_up:
        return {
            "interpretation": "하락 추세 내 반등 시도 구간 — 단기 매수 기회 탐색, 추세 전환 미확인",
            "confidence": "낮음",
        }

    # 3. 골든크로스 + 거래량 감소 → 신뢰도 낮은 크로스
    if is_golden and (vol_down or is_obv_down):
        return {
            "interpretation": "신뢰도 낮은 골든크로스 — 거래량 확인 후 진입 권장",
            "confidence": "낮음",
        }

    # 4. 정배열 + RSI 과매수 + MFI 과매수 → 과열
    if is_ma_up and is_rsi_over and is_mfi_over:
        return {
            "interpretation": "과열 구간 — 추격 매수 자제, 분할 매도 검토",
            "confidence": "높음",
        }

    # 5. 정배열 + RSI 과매수 (MFI는 아직) → 주의
    if is_ma_up and is_rsi_over:
        return {
            "interpretation": "상승 추세이나 단기 과매수 — 신규 매수보다 보유 관점",
            "confidence": "중간",
        }

    # 6. 역배열 + RSI 과매도 + OBV 하락 → 강한 하락
    if is_ma_down and is_rsi_under and is_obv_down:
        return {
            "interpretation": "강한 하락 추세 — 손절 기준 엄격 관리, 신규 매수 자제",
            "confidence": "높음",
        }

    # 7. 역배열 + RSI 과매도 (OBV 중립/상승) → 기술적 반등 가능
    if is_ma_down and is_rsi_under:
        return {
            "interpretation": "하락 추세 과매도 — 기술적 반등 가능하나 추세 전환 확인 필요",
            "confidence": "중간",
        }

    # 8. 데드크로스 + 볼린저 하단 이탈 → 낙폭 과대
    if is_dead and "하단밴드" in bollinger_class:
        return {
            "interpretation": "낙폭 과대 구간 — 기술적 반등 가능하나 추세 역행 매매 주의",
            "confidence": "중간",
        }

    # 9. 정배열 + 골든크로스 + OBV 상승 → 강한 매수 신호
    if is_ma_up and is_golden and is_obv_up:
        return {
            "interpretation": "복수 지표 매수 신호 일치 — 강한 상승 모멘텀",
            "confidence": "높음",
        }

    # 10. 역배열 + 데드크로스 + OBV 하락 → 강한 매도 신호
    if is_ma_down and is_dead and is_obv_down:
        return {
            "interpretation": "복수 지표 매도 신호 일치 — 강한 하락 모멘텀",
            "confidence": "높음",
        }

    # 11. 정배열 + 상승 모멘텀 (기본 상승)
    if is_ma_up:
        return {
            "interpretation": "상승 추세 유지 — 보유 지속, 이탈 시 대응",
            "confidence": "중간",
        }

    # 12. 역배열 (기본 하락)
    if is_ma_down:
        return {
            "interpretation": "하락 추세 — 반등 시도 주시, 추세 전환 신호 대기",
            "confidence": "중간",
        }

    # 기본
    return {
        "interpretation": "혼조세 — 뚜렷한 방향성 없음, 추가 신호 대기",
        "confidence": "낮음",
    }


def calc_all_indicators(df: pd.DataFrame, ma_class: str = "") -> dict:
    """모든 기술적 지표를 한번에 계산"""
    indicators = {
        "rsi": calc_rsi(df),
        "macd": calc_macd(df),
        "bollinger": calc_bollinger(df),
        "stochastic": calc_stochastic(df),
        "adx": calc_adx(df),
        "atr": calc_atr(df),
        "obv": calc_obv(df),
        "mfi": calc_mfi(df),
    }

    # 지표 충돌 해석
    indicators["conflict_interpretation"] = interpret_indicator_conflicts(indicators, ma_class)

    return indicators
