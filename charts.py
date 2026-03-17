# © 2026 donghapro. All Rights Reserved.
"""
2단계: 차트 시각화 모듈
캔들차트 + 이동평균선 + 볼린저밴드 + 거래량 + 보조지표
"""
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd


def create_stock_chart(df: pd.DataFrame, name: str, indicators: dict, mas: dict) -> go.Figure:
    """종합 주식 차트 생성 (캔들 + 볼린저 + 이평 + 거래량 + MACD + RSI)"""

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.5, 0.15, 0.15, 0.2],
        subplot_titles=(name, "RSI", "MACD", "거래량"),
    )

    dates = df.index

    # --- Row 1: 캔들차트 ---
    fig.add_trace(
        go.Candlestick(
            x=dates,
            open=df["시가"],
            high=df["고가"],
            low=df["저가"],
            close=df["종가"],
            name="캔들",
            increasing_line_color="#00ff88",
            decreasing_line_color="#ff4444",
        ),
        row=1, col=1,
    )

    # 이동평균선
    ma_colors = {5: "#FFD700", 10: "#FF6B6B", 20: "#4ECDC4", 50: "#9B59B6"}
    close = df["종가"]
    for period, color in ma_colors.items():
        if len(close) >= period:
            ma = close.rolling(period).mean()
            fig.add_trace(
                go.Scatter(
                    x=dates, y=ma, name=f"MA{period}",
                    line=dict(color=color, width=1),
                ),
                row=1, col=1,
            )

    # 볼린저 밴드
    bb = indicators.get("bollinger", {})
    if "upper_series" in bb:
        fig.add_trace(
            go.Scatter(
                x=dates, y=bb["upper_series"], name="BB Upper",
                line=dict(color="rgba(173,216,230,0.3)", width=1, dash="dot"),
                showlegend=False,
            ),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=dates, y=bb["lower_series"], name="BB Lower",
                line=dict(color="rgba(173,216,230,0.3)", width=1, dash="dot"),
                fill="tonexty",
                fillcolor="rgba(173,216,230,0.05)",
                showlegend=False,
            ),
            row=1, col=1,
        )

    # 매매 신호 마킹 (MACD 크로스)
    macd_data = indicators.get("macd", {})
    if "histogram_series" in macd_data:
        hist = macd_data["histogram_series"]
        for i in range(1, len(hist)):
            if pd.isna(hist.iloc[i]) or pd.isna(hist.iloc[i - 1]):
                continue
            if hist.iloc[i - 1] < 0 and hist.iloc[i] >= 0:
                fig.add_annotation(
                    x=dates[i], y=df["저가"].iloc[i] * 0.98,
                    text="▲", showarrow=False,
                    font=dict(color="#00ff88", size=14),
                    row=1, col=1,
                )
            elif hist.iloc[i - 1] > 0 and hist.iloc[i] <= 0:
                fig.add_annotation(
                    x=dates[i], y=df["고가"].iloc[i] * 1.02,
                    text="▼", showarrow=False,
                    font=dict(color="#ff4444", size=14),
                    row=1, col=1,
                )

    # --- Row 2: RSI ---
    rsi_data = indicators.get("rsi", {})
    if "series" in rsi_data:
        fig.add_trace(
            go.Scatter(
                x=dates, y=rsi_data["series"], name="RSI",
                line=dict(color="#FFD700", width=1.5),
            ),
            row=2, col=1,
        )
        # 과매수/과매도 라인
        fig.add_hline(y=70, line_dash="dash", line_color="rgba(255,68,68,0.5)", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="rgba(0,255,136,0.5)", row=2, col=1)
        fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,68,68,0.05)", line_width=0, row=2, col=1)
        fig.add_hrect(y0=0, y1=30, fillcolor="rgba(0,255,136,0.05)", line_width=0, row=2, col=1)

    # --- Row 3: MACD ---
    if "macd_series" in macd_data:
        fig.add_trace(
            go.Scatter(
                x=dates, y=macd_data["macd_series"], name="MACD",
                line=dict(color="#4ECDC4", width=1.5),
            ),
            row=3, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=dates, y=macd_data["signal_series"], name="Signal",
                line=dict(color="#FF6B6B", width=1.5),
            ),
            row=3, col=1,
        )
        # 히스토그램
        colors = ["#00ff88" if v >= 0 else "#ff4444" for v in macd_data["histogram_series"]]
        fig.add_trace(
            go.Bar(
                x=dates, y=macd_data["histogram_series"], name="Histogram",
                marker_color=colors,
                opacity=0.5,
            ),
            row=3, col=1,
        )

    # --- Row 4: 거래량 ---
    vol_colors = []
    for i in range(len(df)):
        if i == 0:
            vol_colors.append("#888888")
        elif df["종가"].iloc[i] >= df["종가"].iloc[i - 1]:
            vol_colors.append("#00ff88")
        else:
            vol_colors.append("#ff4444")

    fig.add_trace(
        go.Bar(
            x=dates, y=df["거래량"], name="거래량",
            marker_color=vol_colors,
            opacity=0.7,
        ),
        row=4, col=1,
    )

    # --- 레이아웃 ---
    fig.update_layout(
        template="plotly_dark",
        height=800,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=10),
        ),
        margin=dict(l=50, r=50, t=80, b=30),
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
    )

    # x축 설정
    for i in range(1, 5):
        fig.update_xaxes(
            gridcolor="rgba(255,255,255,0.05)",
            row=i, col=1,
        )
        fig.update_yaxes(
            gridcolor="rgba(255,255,255,0.05)",
            row=i, col=1,
        )

    return fig


def create_mini_chart(df: pd.DataFrame, name: str) -> go.Figure:
    """미니 캔들차트 (Expander 내부용, 간단 버전)"""
    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["시가"],
            high=df["고가"],
            low=df["저가"],
            close=df["종가"],
            increasing_line_color="#00ff88",
            decreasing_line_color="#ff4444",
        )
    )

    # 20일 이평
    if len(df) >= 20:
        ma20 = df["종가"].rolling(20).mean()
        fig.add_trace(
            go.Scatter(
                x=df.index, y=ma20, name="MA20",
                line=dict(color="#4ECDC4", width=1),
            )
        )

    fig.update_layout(
        template="plotly_dark",
        height=250,
        showlegend=False,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig
