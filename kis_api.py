# © 2026 donghapro. All Rights Reserved.
"""
한국투자증권 KIS OpenAPI 연동 모듈
- OAuth 토큰 발급
- 보유종목 조회
- 현재가 조회
"""
import urllib.request
import json
import ssl
import streamlit as st
from datetime import datetime


_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _kis_request(url: str, headers: dict, body: dict = None, method: str = "GET") -> dict:
    """KIS API 공통 요청"""
    try:
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        resp = urllib.request.urlopen(req, timeout=10, context=_SSL_CTX)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def _get_kis_config() -> dict:
    """secrets.toml에서 KIS API 설정 로드"""
    return {
        "app_key": st.secrets.get("KIS_APP_KEY", ""),
        "app_secret": st.secrets.get("KIS_APP_SECRET", ""),
        "account_no": st.secrets.get("KIS_ACCOUNT_NO", ""),  # 계좌번호 (8자리-2자리)
        "is_mock": st.secrets.get("KIS_IS_MOCK", True),  # 모의투자 여부
    }


def _get_base_url(is_mock: bool = True) -> str:
    """API 기본 URL"""
    if is_mock:
        return "https://openapivts.koreainvestment.com:29443"
    return "https://openapi.koreainvestment.com:9443"


@st.cache_data(ttl=86400)
def get_access_token() -> str:
    """OAuth 접근 토큰 발급"""
    config = _get_kis_config()
    if not config["app_key"] or not config["app_secret"]:
        return ""

    base_url = _get_base_url(config["is_mock"])
    url = f"{base_url}/oauth2/tokenP"

    body = {
        "grant_type": "client_credentials",
        "appkey": config["app_key"],
        "appsecret": config["app_secret"],
    }
    headers = {"Content-Type": "application/json"}

    result = _kis_request(url, headers, body, method="POST")
    return result.get("access_token", "")


def get_current_price(ticker: str) -> dict:
    """주식 현재가 조회"""
    config = _get_kis_config()
    token = get_access_token()
    if not token:
        return {"error": "KIS API 토큰 없음"}

    base_url = _get_base_url(config["is_mock"])
    url = (
        f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        f"?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD={ticker}"
    )

    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config["app_key"],
        "appsecret": config["app_secret"],
        "tr_id": "FHKST01010100",
    }

    result = _kis_request(url, headers)
    output = result.get("output", {})

    if not output:
        return {"error": "데이터 조회 실패"}

    return {
        "ticker": ticker,
        "name": output.get("hts_kor_isnm", ""),
        "current_price": int(output.get("stck_prpr", 0)),
        "change": int(output.get("prdy_vrss", 0)),
        "change_rate": float(output.get("prdy_ctrt", 0)),
        "volume": int(output.get("acml_vol", 0)),
        "high": int(output.get("stck_hgpr", 0)),
        "low": int(output.get("stck_lwpr", 0)),
        "open": int(output.get("stck_oprc", 0)),
    }


def get_holdings() -> list:
    """보유종목 조회"""
    config = _get_kis_config()
    token = get_access_token()
    if not token:
        return []

    account_parts = config["account_no"].split("-") if "-" in config["account_no"] else [config["account_no"][:8], config["account_no"][8:]]
    if len(account_parts) != 2:
        return []

    base_url = _get_base_url(config["is_mock"])

    # 모의투자 vs 실전
    tr_id = "VTTC8434R" if config["is_mock"] else "TTTC8434R"

    url = (
        f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        f"?CANO={account_parts[0]}&ACNT_PRDT_CD={account_parts[1]}"
        f"&AFHR_FLPR_YN=N&OFL_YN=&INQR_DVSN=02&UNPR_DVSN=01"
        f"&FUND_STTL_ICLD_YN=N&FNCG_AMT_AUTO_RDPT_YN=N&PRCS_DVSN=01"
        f"&CTX_AREA_FK100=&CTX_AREA_NK100="
    )

    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config["app_key"],
        "appsecret": config["app_secret"],
        "tr_id": tr_id,
    }

    result = _kis_request(url, headers)
    output1 = result.get("output1", [])

    holdings = []
    for item in output1:
        qty = int(item.get("hldg_qty", 0))
        if qty <= 0:
            continue

        holdings.append({
            "ticker": item.get("pdno", ""),
            "name": item.get("prdt_name", ""),
            "quantity": qty,
            "avg_price": float(item.get("pchs_avg_pric", 0)),
            "current_price": int(item.get("prpr", 0)),
            "profit_rate": float(item.get("evlu_pfls_rt", 0)),
            "profit_amount": int(item.get("evlu_pfls_amt", 0)),
            "eval_amount": int(item.get("evlu_amt", 0)),
        })

    return holdings


def load_portfolio_from_kis() -> list:
    """KIS API에서 포트폴리오 로드 (app.py의 portfolio 형식으로 변환)"""
    holdings = get_holdings()
    if not holdings:
        return []

    portfolio = []
    for h in holdings:
        portfolio.append({
            "ticker": h["ticker"],
            "avg_price": h["avg_price"],
            "quantity": h["quantity"],
        })

    return portfolio
