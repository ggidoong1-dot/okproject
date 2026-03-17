# © 2026 donghapro. All Rights Reserved.
# 토스페이먼츠 결제 연동 모듈

import streamlit as st
import urllib.request
import urllib.parse
import json
import ssl
import base64
import uuid
from datetime import datetime


# =============================================================
# 설정
# =============================================================

TOSS_CLIENT_KEY = lambda: st.secrets.get("TOSS_CLIENT_KEY", "")
TOSS_SECRET_KEY = lambda: st.secrets.get("TOSS_SECRET_KEY", "")

# 상품 정보
PLANS = {
    "monthly": {
        "name": "오크밸리 프리미엄 (월간)",
        "amount": 9900,
        "months": 1,
        "description": "AI 진단, 전략 시그널, 패턴 분석 등 전체 기능",
    },
    "yearly": {
        "name": "오크밸리 프리미엄 (연간)",
        "amount": 99000,
        "months": 12,
        "description": "월간 대비 17% 할인",
    },
}


# =============================================================
# 결제 요청 (클라이언트 → 토스)
# =============================================================

def create_payment_widget(plan_key: str, user_email: str):
    """토스페이먼츠 결제 위젯 HTML 생성 (iframe 방식)"""
    plan = PLANS.get(plan_key)
    if not plan:
        st.error("유효하지 않은 플랜입니다.")
        return

    client_key = TOSS_CLIENT_KEY()
    if not client_key:
        st.error("토스페이먼츠 클라이언트 키가 설정되지 않았습니다.")
        return

    order_id = f"okvalley_{plan_key}_{uuid.uuid4().hex[:12]}"

    # 세션에 주문 정보 저장 (승인 시 사용)
    st.session_state.pending_order = {
        "order_id": order_id,
        "plan_key": plan_key,
        "amount": plan["amount"],
        "months": plan["months"],
    }

    # 토스페이먼츠 결제 위젯 HTML
    payment_html = f"""
    <div id="payment-widget"></div>
    <div id="agreement"></div>
    <button id="payment-button" style="
        margin-top: 16px;
        padding: 12px 32px;
        background: #3182f6;
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        cursor: pointer;
        width: 100%;
    ">결제하기</button>

    <script src="https://js.tosspayments.com/v2/standard"></script>
    <script>
        async function initPayment() {{
            const tossPayments = TossPayments("{client_key}");
            const widgets = tossPayments.widgets({{
                customerKey: "{user_email}",
            }});

            await widgets.setAmount({{
                currency: "KRW",
                value: {plan["amount"]},
            }});

            await widgets.renderPaymentMethods({{
                selector: "#payment-widget",
                variantKey: "DEFAULT",
            }});

            await widgets.renderAgreement({{
                selector: "#agreement",
                variantKey: "AGREEMENT",
            }});

            document.getElementById("payment-button").addEventListener("click", async () => {{
                try {{
                    await widgets.requestPayment({{
                        orderId: "{order_id}",
                        orderName: "{plan['name']}",
                        customerEmail: "{user_email}",
                        successUrl: window.location.href + "?payment=success&orderId={order_id}",
                        failUrl: window.location.href + "?payment=fail",
                    }});
                }} catch (error) {{
                    if (error.code === "USER_CANCEL") {{
                        // 사용자 취소
                    }} else {{
                        alert("결제 중 오류가 발생했습니다: " + error.message);
                    }}
                }}
            }});
        }}
        initPayment();
    </script>
    """

    st.components.v1.html(payment_html, height=500)


# =============================================================
# 결제 승인 (서버 → 토스)
# =============================================================

def confirm_payment(payment_key: str, order_id: str, amount: int) -> dict:
    """토스페이먼츠 결제 승인 요청"""
    secret_key = TOSS_SECRET_KEY()
    if not secret_key:
        return {"success": False, "message": "토스페이먼츠 시크릿 키가 없습니다."}

    # Basic Auth 인코딩
    auth_string = base64.b64encode(f"{secret_key}:".encode()).decode()

    url = "https://api.tosspayments.com/v1/payments/confirm"
    data = json.dumps({
        "paymentKey": payment_key,
        "orderId": order_id,
        "amount": amount,
    }).encode("utf-8")

    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {auth_string}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return {
                "success": True,
                "payment_key": result.get("paymentKey"),
                "order_id": result.get("orderId"),
                "amount": result.get("totalAmount"),
                "method": result.get("method"),
                "status": result.get("status"),
                "raw": result,
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            err = json.loads(body)
            return {"success": False, "message": err.get("message", "결제 승인 실패")}
        except json.JSONDecodeError:
            return {"success": False, "message": f"결제 승인 실패 (HTTP {e.code})"}
    except Exception as e:
        return {"success": False, "message": f"결제 오류: {str(e)}"}


# =============================================================
# 결제 콜백 처리
# =============================================================

def handle_payment_callback():
    """URL 쿼리 파라미터로 결제 결과 처리"""
    params = st.query_params

    payment_status = params.get("payment")
    if not payment_status:
        return None

    if payment_status == "success":
        payment_key = params.get("paymentKey", "")
        order_id = params.get("orderId", "")
        amount_str = params.get("amount", "0")

        try:
            amount = int(amount_str)
        except ValueError:
            amount = 0

        if payment_key and order_id and amount > 0:
            # 결제 승인
            result = confirm_payment(payment_key, order_id, amount)
            # 쿼리 파라미터 제거
            st.query_params.clear()
            return result

    elif payment_status == "fail":
        st.query_params.clear()
        return {"success": False, "message": params.get("message", "결제가 취소되었습니다.")}

    return None


# =============================================================
# 결제 UI
# =============================================================

def render_pricing_page(user_email: str):
    """요금제 선택 + 결제 UI"""
    st.markdown("## 프리미엄 플랜")
    st.markdown("모든 기능을 제한 없이 사용하세요.")

    col1, col2 = st.columns(2)

    with col1:
        plan = PLANS["monthly"]
        st.markdown(f"""
        <div style="border:1px solid #333; border-radius:12px; padding:24px; text-align:center;">
            <h3>월간 플랜</h3>
            <p style="font-size:2em; color:#3182f6; margin:8px 0;"><b>{plan['amount']:,}원</b>/월</p>
            <p style="color:#888;">{plan['description']}</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("월간 결제", key="pay_monthly", use_container_width=True):
            st.session_state.selected_plan = "monthly"

    with col2:
        plan = PLANS["yearly"]
        st.markdown(f"""
        <div style="border:2px solid #3182f6; border-radius:12px; padding:24px; text-align:center;">
            <span style="background:#3182f6; color:white; padding:4px 12px; border-radius:12px; font-size:0.8em;">BEST</span>
            <h3>연간 플랜</h3>
            <p style="font-size:2em; color:#3182f6; margin:8px 0;"><b>{plan['amount']:,}원</b>/년</p>
            <p style="color:#888;">{plan['description']}</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("연간 결제", key="pay_yearly", use_container_width=True):
            st.session_state.selected_plan = "yearly"

    # 프리미엄 기능 목록
    st.markdown("---")
    st.markdown("### 프리미엄 포함 기능")
    features = [
        "무제한 종목 분석",
        "AI 종합 진단 리포트",
        "미너비니 / CANSLIM / 터틀 전략 시그널",
        "패턴 분석 (요일별, 월별, 장중)",
        "데이터 내보내기 (JSON/Markdown)",
        "텔레그램 알림 설정",
        "포트폴리오 리스크 분석",
    ]
    for f in features:
        st.markdown(f"- {f}")

    # 결제 위젯 표시
    selected = st.session_state.get("selected_plan")
    if selected:
        st.markdown("---")
        st.markdown(f"### 결제 진행: {PLANS[selected]['name']}")
        create_payment_widget(selected, user_email)
