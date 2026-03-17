# © 2026 donghapro. All Rights Reserved.
"""
텔레그램 가격 알림 모듈
ATR 기반 손절/익절선, RSI 과매수/과매도, 급등락 등 도달 시 텔레그램 알림 발송.
"""
import urllib.request
import urllib.parse
import json
import ssl
import streamlit as st
from datetime import datetime

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def send_telegram_message(bot_token: str, chat_id: str, message: str) -> bool:
    """텔레그램 봇으로 메시지 발송"""
    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        resp = urllib.request.urlopen(req, timeout=10, context=_SSL_CTX)
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("ok", False)
    except Exception:
        return False


def check_alerts(results: list) -> list:
    """분석 결과에서 알림 조건 체크. 트리거된 알림 목록 반환."""
    alerts = []

    for r in results:
        if "error" in r:
            continue

        name = r["name"]
        price = r["current_price"]
        ind = r.get("indicators", {})

        # 1. ATR 손절/익절 도달
        atr = ind.get("atr", {})
        if atr.get("stop_loss") and price <= atr["stop_loss"]:
            alerts.append({
                "type": "stop_loss",
                "stock": name,
                "message": f"*{name}* 손절선 도달\n현재가: {price:,} <= 손절: {atr['stop_loss']:,}",
                "severity": "high",
            })
        if atr.get("take_profit") and price >= atr["take_profit"]:
            alerts.append({
                "type": "take_profit",
                "stock": name,
                "message": f"*{name}* 익절선 도달\n현재가: {price:,} >= 익절: {atr['take_profit']:,}",
                "severity": "medium",
            })

        # 2. RSI 과매수/과매도
        rsi = ind.get("rsi", {}).get("value")
        if rsi and rsi >= 75:
            alerts.append({
                "type": "rsi_overbought",
                "stock": name,
                "message": f"*{name}* RSI 과매수 ({rsi})\n매도 타이밍 검토",
                "severity": "medium",
            })
        elif rsi and rsi <= 25:
            alerts.append({
                "type": "rsi_oversold",
                "stock": name,
                "message": f"*{name}* RSI 과매도 ({rsi})\n반등 가능성 주시",
                "severity": "medium",
            })

        # 3. 급등락 (일간 수익률 5% 이상 변동)
        if "df" in r and len(r["df"]) >= 2:
            prev_close = r["df"]["종가"].iloc[-2]
            daily_change = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0
            if daily_change >= 5:
                alerts.append({
                    "type": "surge",
                    "stock": name,
                    "message": f"*{name}* 급등 +{daily_change:.1f}%\n현재가: {price:,}",
                    "severity": "low",
                })
            elif daily_change <= -5:
                alerts.append({
                    "type": "plunge",
                    "stock": name,
                    "message": f"*{name}* 급락 {daily_change:.1f}%\n현재가: {price:,}",
                    "severity": "high",
                })

        # 4. MACD 크로스
        macd_class = ind.get("macd", {}).get("classification", "")
        if "골든크로스" in macd_class:
            alerts.append({
                "type": "golden_cross",
                "stock": name,
                "message": f"*{name}* MACD 골든크로스 발생\n매수 신호 확인",
                "severity": "low",
            })
        elif "데드크로스" in macd_class:
            alerts.append({
                "type": "dead_cross",
                "stock": name,
                "message": f"*{name}* MACD 데드크로스 발생\n매도 신호 확인",
                "severity": "medium",
            })

    return alerts


def send_alerts(results: list, bot_token: str, chat_id: str) -> int:
    """분석 결과 기반 알림 체크 및 텔레그램 발송. 발송 건수 반환."""
    alerts = check_alerts(results)
    if not alerts:
        return 0

    sent = 0
    header = f"📊 *Stock Memory 알림* ({datetime.now().strftime('%H:%M')})\n\n"

    # 알림을 하나의 메시지로 묶어서 발송
    severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    lines = [header]
    for a in alerts:
        icon = severity_icon.get(a["severity"], "⚪")
        lines.append(f"{icon} {a['message']}\n")

    message = "\n".join(lines)
    if send_telegram_message(bot_token, chat_id, message):
        sent = len(alerts)

    return sent
