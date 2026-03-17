-- =====================================================
-- 오크밸리 인증/구독 테이블 (Supabase SQL Editor에서 실행)
-- =====================================================

-- 1. 사용자 프로필 테이블 (Supabase Auth의 auth.users와 연동)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
    email TEXT NOT NULL,
    nickname TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 2. 구독 테이블 (유료 플랜 관리)
CREATE TABLE IF NOT EXISTS public.subscriptions (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',           -- 'free', 'trial', 'premium'
    status TEXT NOT NULL DEFAULT 'active',        -- 'active', 'expired', 'cancelled'
    trial_started_at TIMESTAMPTZ,                -- 7일 무료 체험 시작일
    trial_ends_at TIMESTAMPTZ,                   -- 7일 무료 체험 종료일
    paid_at TIMESTAMPTZ,                         -- 결제 완료 시각
    expires_at TIMESTAMPTZ,                      -- 구독 만료일
    toss_payment_key TEXT,                       -- 토스페이먼츠 결제 키
    toss_order_id TEXT,                          -- 토스페이먼츠 주문 ID
    amount INTEGER DEFAULT 0,                    -- 결제 금액
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id)
);

-- 3. 결제 이력 테이블
CREATE TABLE IF NOT EXISTS public.payment_history (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    toss_payment_key TEXT,
    toss_order_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL,                         -- 'DONE', 'CANCELED', 'FAILED'
    method TEXT,                                  -- 'CARD', 'TRANSFER', 'VIRTUAL_ACCOUNT'
    paid_at TIMESTAMPTZ,
    raw_response JSONB,                          -- 토스 응답 원본
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 4. RLS (Row Level Security) 활성화
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_history ENABLE ROW LEVEL SECURITY;

-- 5. RLS 정책: 사용자는 본인 데이터만 접근
CREATE POLICY "Users can view own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

CREATE POLICY "Users can view own subscription"
    ON public.subscriptions FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can view own payments"
    ON public.payment_history FOR SELECT
    USING (auth.uid() = user_id);

-- 6. 서비스 역할용 정책 (서버에서 구독 업데이트용)
CREATE POLICY "Service can manage subscriptions"
    ON public.subscriptions FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Service can manage payments"
    ON public.payment_history FOR ALL
    USING (true)
    WITH CHECK (true);

-- 7. 회원가입 시 자동으로 프로필 + 구독(trial) 생성하는 트리거
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    -- 프로필 생성
    INSERT INTO public.profiles (id, email)
    VALUES (NEW.id, NEW.email);

    -- 7일 무료 체험 구독 생성
    INSERT INTO public.subscriptions (user_id, plan, status, trial_started_at, trial_ends_at)
    VALUES (
        NEW.id,
        'trial',
        'active',
        now(),
        now() + INTERVAL '7 days'
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 기존 트리거 제거 후 재생성
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 8. 만료된 체험판 자동 처리용 함수
CREATE OR REPLACE FUNCTION public.check_trial_expiry()
RETURNS void AS $$
BEGIN
    UPDATE public.subscriptions
    SET plan = 'free', status = 'expired'
    WHERE plan = 'trial'
      AND trial_ends_at < now()
      AND status = 'active';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
