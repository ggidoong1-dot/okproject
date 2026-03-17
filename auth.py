# © 2026 donghapro. All Rights Reserved.
# Supabase Auth 기반 인증 + 구독 관리 모듈

import streamlit as st
from supabase import create_client, Client
from datetime import datetime, timezone


def _get_supabase() -> Client:
    """Supabase 클라이언트 (캐싱)"""
    if "supabase_client" not in st.session_state:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        st.session_state.supabase_client = create_client(url, key)
    return st.session_state.supabase_client


def _get_supabase_admin() -> Client:
    """Supabase 서비스 역할 클라이언트 (구독 업데이트용)"""
    if "supabase_admin" not in st.session_state:
        url = st.secrets["SUPABASE_URL"]
        service_key = st.secrets.get("SUPABASE_SERVICE_KEY", st.secrets["SUPABASE_KEY"])
        st.session_state.supabase_admin = create_client(url, service_key)
    return st.session_state.supabase_admin


# =============================================================
# 회원가입
# =============================================================

def sign_up(email: str, password: str) -> dict:
    """이메일/비밀번호 회원가입 → 7일 무료 체험 자동 시작"""
    sb = _get_supabase()
    try:
        res = sb.auth.sign_up({"email": email, "password": password})
        if res.user:
            return {"success": True, "message": "회원가입 완료! 이메일 인증 후 로그인해주세요."}
        return {"success": False, "message": "회원가입에 실패했습니다."}
    except Exception as e:
        msg = str(e)
        if "already registered" in msg.lower() or "already been registered" in msg.lower():
            return {"success": False, "message": "이미 등록된 이메일입니다."}
        if "password" in msg.lower() and "short" in msg.lower():
            return {"success": False, "message": "비밀번호는 6자 이상이어야 합니다."}
        return {"success": False, "message": f"오류: {msg}"}


# =============================================================
# 로그인 / 로그아웃
# =============================================================

def sign_in(email: str, password: str) -> dict:
    """이메일/비밀번호 로그인"""
    sb = _get_supabase()
    try:
        res = sb.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            st.session_state.user = {
                "id": res.user.id,
                "email": res.user.email,
            }
            st.session_state.access_token = res.session.access_token
            # 체험판 만료 체크
            _check_trial_expiry(res.user.id)
            return {"success": True}
        return {"success": False, "message": "로그인에 실패했습니다."}
    except Exception as e:
        msg = str(e)
        if "invalid" in msg.lower() or "credentials" in msg.lower():
            return {"success": False, "message": "이메일 또는 비밀번호가 올바르지 않습니다."}
        if "not confirmed" in msg.lower():
            return {"success": False, "message": "이메일 인증이 필요합니다. 메일함을 확인해주세요."}
        return {"success": False, "message": f"로그인 오류: {msg}"}


def sign_out():
    """로그아웃"""
    sb = _get_supabase()
    try:
        sb.auth.sign_out()
    except Exception:
        pass
    for key in ["user", "access_token", "subscription", "supabase_client", "supabase_admin"]:
        st.session_state.pop(key, None)


def get_current_user() -> dict | None:
    """현재 로그인된 사용자 반환"""
    return st.session_state.get("user")


def is_authenticated() -> bool:
    """로그인 상태 확인"""
    return get_current_user() is not None


# =============================================================
# 구독/플랜 관리
# =============================================================

def _check_trial_expiry(user_id: str):
    """체험판 만료 체크 및 자동 전환"""
    sb = _get_supabase_admin()
    try:
        res = sb.table("subscriptions").select("*").eq("user_id", user_id).single().execute()
        sub = res.data
        if not sub:
            return

        # 체험판 만료 → free로 전환
        if sub["plan"] == "trial" and sub["trial_ends_at"]:
            trial_end = datetime.fromisoformat(sub["trial_ends_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > trial_end:
                sb.table("subscriptions").update({
                    "plan": "free",
                    "status": "expired",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("user_id", user_id).execute()
    except Exception:
        pass


def get_subscription() -> dict:
    """현재 사용자의 구독 정보 반환"""
    user = get_current_user()
    if not user:
        return {"plan": "free", "status": "none", "is_premium": False, "trial_remaining": 0}

    # 캐시 확인
    if "subscription" in st.session_state:
        return st.session_state.subscription

    sb = _get_supabase_admin()
    try:
        res = sb.table("subscriptions").select("*").eq("user_id", user["id"]).single().execute()
        sub = res.data
        if not sub:
            result = {"plan": "free", "status": "none", "is_premium": False, "trial_remaining": 0}
            st.session_state.subscription = result
            return result

        plan = sub["plan"]
        status = sub["status"]

        # 체험판 남은 일수
        trial_remaining = 0
        if plan == "trial" and sub.get("trial_ends_at"):
            trial_end = datetime.fromisoformat(sub["trial_ends_at"].replace("Z", "+00:00"))
            remaining = (trial_end - datetime.now(timezone.utc)).total_seconds()
            trial_remaining = max(0, int(remaining / 86400))

        # 프리미엄 만료 체크
        if plan == "premium" and sub.get("expires_at"):
            exp = datetime.fromisoformat(sub["expires_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                plan = "free"
                status = "expired"

        is_premium = (plan in ("trial", "premium")) and status == "active"

        result = {
            "plan": plan,
            "status": status,
            "is_premium": is_premium,
            "trial_remaining": trial_remaining,
            "trial_ends_at": sub.get("trial_ends_at"),
            "expires_at": sub.get("expires_at"),
            "paid_at": sub.get("paid_at"),
        }
        st.session_state.subscription = result
        return result

    except Exception:
        result = {"plan": "free", "status": "error", "is_premium": False, "trial_remaining": 0}
        st.session_state.subscription = result
        return result


def activate_premium(user_id: str, payment_key: str, order_id: str, amount: int, months: int = 1):
    """결제 완료 후 프리미엄 활성화"""
    sb = _get_supabase_admin()
    now = datetime.now(timezone.utc)

    # 구독 업데이트
    sb.table("subscriptions").update({
        "plan": "premium",
        "status": "active",
        "paid_at": now.isoformat(),
        "expires_at": (now + __import__("datetime").timedelta(days=30 * months)).isoformat(),
        "toss_payment_key": payment_key,
        "toss_order_id": order_id,
        "amount": amount,
        "updated_at": now.isoformat(),
    }).eq("user_id", user_id).execute()

    # 결제 이력 저장
    sb.table("payment_history").insert({
        "user_id": user_id,
        "toss_payment_key": payment_key,
        "toss_order_id": order_id,
        "amount": amount,
        "status": "DONE",
        "paid_at": now.isoformat(),
    }).execute()

    # 캐시 초기화
    st.session_state.pop("subscription", None)


# =============================================================
# 기능 접근 제어
# =============================================================

# 무료 플랜 제한
FREE_LIMITS = {
    "max_stocks": 1,           # 분석 가능 종목 수
    "ai_diagnosis": False,     # AI 진단
    "strategy_signals": False, # 전략 시그널 (미너비니, CANSLIM 등)
    "pattern_analysis": False, # 패턴 분석
    "export_data": False,      # 데이터 내보내기
    "telegram_alert": False,   # 텔레그램 알림
}

PREMIUM_LIMITS = {
    "max_stocks": 999,
    "ai_diagnosis": True,
    "strategy_signals": True,
    "pattern_analysis": True,
    "export_data": True,
    "telegram_alert": True,
}


def check_feature(feature: str) -> bool:
    """기능 접근 가능 여부 확인"""
    sub = get_subscription()
    limits = PREMIUM_LIMITS if sub["is_premium"] else FREE_LIMITS
    return limits.get(feature, False)


def check_stock_limit(count: int) -> bool:
    """종목 수 제한 확인"""
    sub = get_subscription()
    limits = PREMIUM_LIMITS if sub["is_premium"] else FREE_LIMITS
    return count <= limits["max_stocks"]


def show_upgrade_prompt(feature_name: str = "이 기능"):
    """프리미엄 업그레이드 안내 표시"""
    sub = get_subscription()
    if sub["plan"] == "trial":
        st.warning(
            f"{feature_name}은 체험 기간 종료 후 프리미엄 전용입니다. "
            f"남은 체험 기간: **{sub['trial_remaining']}일**"
        )
    else:
        st.info(
            f"{feature_name}은 **프리미엄** 전용 기능입니다. "
            f"프리미엄으로 업그레이드하면 모든 기능을 이용할 수 있습니다."
        )
