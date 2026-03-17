# © 2026 donghapro. All Rights Reserved.
"""
3단계: 포트폴리오 대시보드 + 리스크 관리 모듈
- 포트폴리오 요약 (총 투자금, 평가금, 수익률)
- 종목별 비중 파이차트
- MDD (최대낙폭)
- 샤프 비율
- 종목 간 상관계수 히트맵
- 켈리 공식
- 섹터 분산 분석
- 리밸런싱 제안
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
from pykrx import stock as pykrx_stock


def calc_portfolio_summary(results: list) -> dict:
    """포트폴리오 전체 요약"""
    total_invested = 0
    total_value = 0
    holdings = []

    for r in results:
        if "error" in r:
            continue
        invested = r["avg_price"] * r["quantity"]
        value = r["current_price"] * r["quantity"]
        total_invested += invested
        total_value += value
        holdings.append({
            "name": r["name"],
            "ticker": r.get("ticker_raw", r["ticker"]),
            "invested": invested,
            "value": value,
            "profit": value - invested,
            "profit_rate": r["profit_rate"],
            "weight": value,  # 나중에 비중 계산
            "quantity": r["quantity"],
            "current_price": r["current_price"],
            "avg_price": r["avg_price"],
        })

    # 비중 계산
    for h in holdings:
        h["weight_pct"] = round(h["value"] / total_value * 100, 2) if total_value > 0 else 0

    total_profit = total_value - total_invested
    total_profit_rate = round((total_profit / total_invested * 100), 2) if total_invested > 0 else 0

    return {
        "total_invested": total_invested,
        "total_value": total_value,
        "total_profit": total_profit,
        "total_profit_rate": total_profit_rate,
        "holdings": holdings,
        "count": len(holdings),
    }


def create_weight_chart(holdings: list) -> go.Figure:
    """종목별 비중 도넛 차트"""
    names = [h["name"] for h in holdings]
    values = [h["value"] for h in holdings]
    colors = px.colors.qualitative.Set2[:len(names)]

    fig = go.Figure(data=[go.Pie(
        labels=names,
        values=values,
        hole=0.5,
        textinfo="label+percent",
        textfont_size=12,
        marker=dict(colors=colors),
    )])

    fig.update_layout(
        template="plotly_dark",
        height=350,
        margin=dict(l=20, r=20, t=30, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=True,
        legend=dict(font=dict(size=10)),
    )

    return fig


def create_profit_bar_chart(holdings: list) -> go.Figure:
    """종목별 수익률 바 차트"""
    names = [h["name"] for h in holdings]
    rates = [h["profit_rate"] for h in holdings]
    colors = ["#00ff88" if r >= 0 else "#ff4444" for r in rates]

    fig = go.Figure(data=[go.Bar(
        x=names,
        y=rates,
        marker_color=colors,
        text=[f"{r}%" for r in rates],
        textposition="outside",
    )])

    fig.update_layout(
        template="plotly_dark",
        height=300,
        margin=dict(l=20, r=20, t=30, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title="수익률 (%)",
        xaxis_title="",
    )

    return fig


def calc_mdd(df: pd.DataFrame) -> dict:
    """MDD (최대낙폭) 계산"""
    close = df["종가"]
    cummax = close.cummax()
    drawdown = (close - cummax) / cummax * 100
    mdd = round(drawdown.min(), 2)
    mdd_date = drawdown.idxmin()

    return {
        "mdd": mdd,
        "mdd_date": str(mdd_date.date()) if hasattr(mdd_date, 'date') else str(mdd_date),
        "drawdown_series": drawdown,
    }


def calc_sharpe_ratio(df: pd.DataFrame, risk_free_rate: float = 0.03) -> float:
    """샤프 비율 계산"""
    close = df["종가"]
    returns = close.pct_change().dropna()

    if len(returns) < 20:
        return None

    annual_return = returns.mean() * 252
    annual_std = returns.std() * np.sqrt(252)

    if annual_std == 0:
        return None

    return round((annual_return - risk_free_rate) / annual_std, 2)


def calc_correlation_matrix(results: list) -> tuple:
    """종목 간 상관계수 매트릭스"""
    returns_dict = {}
    for r in results:
        if "error" in r or "df" not in r:
            continue
        close = r["df"]["종가"]
        daily_returns = close.pct_change().dropna()
        returns_dict[r["name"]] = daily_returns

    if len(returns_dict) < 2:
        return None, None

    returns_df = pd.DataFrame(returns_dict)
    # 인덱스 정렬 후 공통 인덱스만 사용
    returns_df = returns_df.dropna()
    corr_matrix = returns_df.corr()

    return corr_matrix, returns_df


def create_correlation_heatmap(corr_matrix: pd.DataFrame) -> go.Figure:
    """상관계수 히트맵"""
    fig = go.Figure(data=go.Heatmap(
        z=corr_matrix.values,
        x=corr_matrix.columns,
        y=corr_matrix.index,
        colorscale="RdBu_r",
        zmin=-1,
        zmax=1,
        text=corr_matrix.round(2).values,
        texttemplate="%{text}",
        textfont={"size": 12},
    ))

    fig.update_layout(
        template="plotly_dark",
        height=350,
        margin=dict(l=20, r=20, t=30, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig


def calc_kelly_criterion(df: pd.DataFrame, period: int = 60) -> dict:
    """켈리 공식 - 최적 투자비중 계산"""
    close = df["종가"].tail(period)
    returns = close.pct_change().dropna()

    wins = returns[returns > 0]
    losses = returns[returns < 0]

    if len(wins) == 0 or len(losses) == 0:
        return {"kelly": None, "win_rate": None, "avg_win": None, "avg_loss": None}

    win_rate = len(wins) / len(returns)
    avg_win = wins.mean()
    avg_loss = abs(losses.mean())

    if avg_loss == 0:
        kelly = 1.0
    else:
        kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win

    # Half-Kelly (보수적)
    half_kelly = kelly / 2

    return {
        "kelly": round(kelly * 100, 1),
        "half_kelly": round(half_kelly * 100, 1),
        "win_rate": round(win_rate * 100, 1),
        "avg_win": round(avg_win * 100, 2),
        "avg_loss": round(avg_loss * 100, 2),
    }


def calc_breakeven(current_price: float, avg_price: float, quantity: int) -> dict:
    """손익분기점 및 목표가 계산"""
    if not avg_price or avg_price <= 0:
        return {"breakeven": 0, "targets": {}}

    targets = {}
    for rate in [5, 10, 15, 20, 30, 50]:
        targets[f"+{rate}%"] = round(avg_price * (1 + rate / 100))
        targets[f"-{rate}%"] = round(avg_price * (1 - rate / 100))

    return {
        "breakeven": round(avg_price),
        "targets": targets,
    }


def analyze_sector_diversification(results: list) -> dict:
    """섹터(업종) 분산 분석"""
    sector_map = {}

    for r in results:
        if "error" in r:
            continue
        ticker = r.get("ticker_raw", r["ticker"])
        market = r.get("market", "KR")
        sector = "기타"

        if market == "KR":
            try:
                sector = pykrx_stock.get_market_ticker_name(ticker)
                # pykrx 업종 조회
                from pykrx import stock
                sector_info = stock.get_market_ticker_and_name("ALL")
                # KRX 업종 분류 시도
                sector = _get_krx_sector(ticker) or "기타"
            except Exception:
                sector = "기타"
        else:
            try:
                import yfinance as yf
                info = yf.Ticker(ticker).info
                sector = info.get("sector", "기타")
            except Exception:
                sector = "기타"

        value = r["current_price"] * r["quantity"]
        if sector not in sector_map:
            sector_map[sector] = {"value": 0, "stocks": []}
        sector_map[sector]["value"] += value
        sector_map[sector]["stocks"].append(r["name"])

    total_value = sum(s["value"] for s in sector_map.values())

    sectors = []
    warnings = []
    for name, data in sector_map.items():
        pct = round(data["value"] / total_value * 100, 1) if total_value > 0 else 0
        sectors.append({
            "sector": name,
            "weight_pct": pct,
            "stocks": data["stocks"],
            "value": data["value"],
        })
        if pct > 50:
            warnings.append(f"⚠️ '{name}' 섹터 비중 {pct}% — 편중 위험")
        elif pct > 35:
            warnings.append(f"⚡ '{name}' 섹터 비중 {pct}% — 다소 집중")

    sectors.sort(key=lambda x: x["weight_pct"], reverse=True)

    return {
        "sectors": sectors,
        "count": len(sectors),
        "warnings": warnings,
    }


def _get_krx_sector(ticker: str) -> str:
    """KRX 업종 분류 조회"""
    try:
        from pykrx import stock
        # KOSPI 업종 확인
        for market in ["KOSPI", "KOSDAQ"]:
            tickers_by_sector = {}
            sector_list = stock.get_index_ticker_list(market=market)
            for idx in sector_list:
                name = stock.get_index_ticker_name(idx)
                comps = stock.get_index_portfolio_deposit_file(idx)
                if ticker in comps:
                    return name
    except Exception:
        pass
    return None


def calc_portfolio_level_analysis(results: list) -> dict:
    """포트폴리오 레벨 종합 분석

    - HHI (허핀달-허쉬만 지수): 집중도
    - 포트폴리오 베타: 시장 민감도
    - 가중평균 스코어카드
    """
    valid = [r for r in results if "error" not in r]
    if not valid:
        return None

    # 1. 종목별 비중 계산
    total_value = sum(r["current_price"] * r["quantity"] for r in valid)
    if total_value <= 0:
        return None

    weights = []
    for r in valid:
        w = r["current_price"] * r["quantity"] / total_value
        weights.append({"name": r["name"], "weight": w})

    # 2. HHI (허핀달-허쉬만 지수)
    # HHI = 비중^2 의 합 * 10000. 10000=독점, 1500 이하=분산
    hhi = round(sum(w["weight"] ** 2 for w in weights) * 10000)
    if hhi > 2500:
        hhi_class = "고집중 (단일 종목 편중)"
    elif hhi > 1500:
        hhi_class = "중간 집중"
    else:
        hhi_class = "적절히 분산"

    # 3. 포트폴리오 베타 (가중평균)
    betas = []
    for r in valid:
        w = r["current_price"] * r["quantity"] / total_value
        if "df" in r and len(r["df"]) >= 60:
            try:
                import yfinance as yf_mod
                bench_ticker = "^KS11" if r.get("market") == "KR" else "^GSPC"
                bench = yf_mod.download(bench_ticker, period="1y", progress=False)
                if isinstance(bench.columns, pd.MultiIndex):
                    bench_close = bench["Close"].iloc[:, 0]
                else:
                    bench_close = bench["Close"]
                bench_ret = bench_close.pct_change().dropna()
                stock_ret = r["df"]["종가"].pct_change().dropna()

                # 공통 인덱스
                common = stock_ret.index.intersection(bench_ret.index)
                if len(common) >= 30:
                    sr = stock_ret.loc[common]
                    br = bench_ret.loc[common]
                    cov = np.cov(sr, br)
                    beta = round(cov[0, 1] / cov[1, 1], 2) if cov[1, 1] != 0 else 1.0
                    betas.append((w, beta))
            except Exception:
                betas.append((w, 1.0))
        else:
            betas.append((w, 1.0))

    port_beta = round(sum(w * b for w, b in betas), 2) if betas else None
    if port_beta is not None:
        if port_beta > 1.2:
            beta_class = "공격적 (시장보다 변동성 큼)"
        elif port_beta > 0.8:
            beta_class = "중립적 (시장과 유사)"
        else:
            beta_class = "방어적 (시장보다 안정적)"
    else:
        beta_class = "데이터 부족"

    # 4. 가중평균 스코어카드
    weighted_score = 0
    for r in valid:
        w = r["current_price"] * r["quantity"] / total_value
        sc = r.get("scorecard", {})
        weighted_score += w * sc.get("total", 50)
    weighted_score = round(weighted_score)

    return {
        "hhi": hhi,
        "hhi_class": hhi_class,
        "portfolio_beta": port_beta,
        "beta_class": beta_class,
        "weighted_score": weighted_score,
        "stock_count": len(valid),
    }


def suggest_rebalancing(holdings: list, max_weight: float = 30.0) -> list:
    """리밸런싱 제안 - 비중 초과 종목 경고"""
    suggestions = []
    equal_weight = 100 / len(holdings) if holdings else 0

    for h in holdings:
        if h["weight_pct"] > max_weight:
            suggestions.append({
                "name": h["name"],
                "current_weight": h["weight_pct"],
                "target_weight": round(equal_weight, 1),
                "action": "비중 축소 권장",
                "severity": "high",
            })
        elif h["weight_pct"] < equal_weight * 0.3:
            suggestions.append({
                "name": h["name"],
                "current_weight": h["weight_pct"],
                "target_weight": round(equal_weight, 1),
                "action": "비중 확대 고려",
                "severity": "low",
            })

    return suggestions
