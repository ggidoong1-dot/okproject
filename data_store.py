# © 2026 donghapro. All Rights Reserved.
"""
데이터 축적 모듈
접속할 때마다 주가 데이터를 SQLite에 저장하여 시간별/요일별 패턴 분석 가능.
"""
import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "stock_data.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """테이블 생성 (최초 1회)"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_ohlcv (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, date)
        );

        CREATE TABLE IF NOT EXISTS price_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT,
            captured_at TEXT NOT NULL,
            price REAL NOT NULL,
            volume INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_snapshot_ticker_time
        ON price_snapshots (ticker, captured_at);

        CREATE INDEX IF NOT EXISTS idx_daily_ticker
        ON daily_ohlcv (ticker, date);
    """)
    conn.close()


# =============================================================
# 데이터 저장
# =============================================================

def save_daily_ohlcv(ticker: str, df: pd.DataFrame):
    """일봉 OHLCV를 DB에 저장 (중복 무시)"""
    if df.empty:
        return
    conn = _get_conn()
    rows = []
    for idx, row in df.iterrows():
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        rows.append((
            ticker, date_str,
            float(row["시가"]), float(row["고가"]),
            float(row["저가"]), float(row["종가"]),
            int(row["거래량"]),
        ))
    conn.executemany(
        "INSERT OR IGNORE INTO daily_ohlcv (ticker, date, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def needs_backfill(ticker: str, min_days: int = 700) -> bool:
    """해당 종목의 축적 데이터가 충분한지 확인"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM daily_ohlcv WHERE ticker = ?", (ticker,))
    count = cur.fetchone()[0]
    conn.close()
    return count < min_days


def save_price_snapshot(ticker: str, name: str, price: float, volume: int = 0):
    """현재 시점의 가격 스냅샷 저장 (접속할 때마다 호출)"""
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO price_snapshots (ticker, name, captured_at, price, volume) "
        "VALUES (?, ?, ?, ?, ?)",
        (ticker, name, now, price, volume),
    )
    conn.commit()
    conn.close()


# =============================================================
# 데이터 조회
# =============================================================

def get_daily_ohlcv(ticker: str, days: int = 365) -> pd.DataFrame:
    """축적된 일봉 데이터 조회"""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume "
        "FROM daily_ohlcv WHERE ticker = ? AND date >= ? ORDER BY date",
        conn, params=(ticker, cutoff),
    )
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df = df.rename(columns={"open": "시가", "high": "고가", "low": "저가", "close": "종가", "volume": "거래량"})
    return df


def get_snapshots(ticker: str, days: int = 90) -> pd.DataFrame:
    """가격 스냅샷 조회"""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    df = pd.read_sql_query(
        "SELECT captured_at, price, volume FROM price_snapshots "
        "WHERE ticker = ? AND captured_at >= ? ORDER BY captured_at",
        conn, params=(ticker, cutoff),
    )
    conn.close()
    if not df.empty:
        df["captured_at"] = pd.to_datetime(df["captured_at"])
    return df


def get_db_stats() -> Dict:
    """DB 축적 현황"""
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(DISTINCT ticker) FROM daily_ohlcv")
    daily_tickers = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM daily_ohlcv")
    daily_rows = cur.fetchone()[0]
    cur.execute("SELECT MIN(date), MAX(date) FROM daily_ohlcv")
    daily_range = cur.fetchone()

    cur.execute("SELECT COUNT(DISTINCT ticker) FROM price_snapshots")
    snap_tickers = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM price_snapshots")
    snap_rows = cur.fetchone()[0]
    cur.execute("SELECT MIN(captured_at), MAX(captured_at) FROM price_snapshots")
    snap_range = cur.fetchone()

    conn.close()
    return {
        "daily_tickers": daily_tickers,
        "daily_rows": daily_rows,
        "daily_range": (daily_range[0] or "-", daily_range[1] or "-"),
        "snapshot_tickers": snap_tickers,
        "snapshot_rows": snap_rows,
        "snapshot_range": (snap_range[0] or "-", snap_range[1] or "-"),
    }


# =============================================================
# 패턴 분석
# =============================================================

def analyze_day_of_week_pattern(ticker: str) -> Optional[Dict]:
    """요일별 수익률 패턴 분석"""
    df = get_daily_ohlcv(ticker, days=365 * 3)
    if len(df) < 60:
        return None

    df["daily_return"] = df["종가"].pct_change() * 100
    df["day_of_week"] = df.index.dayofweek  # 0=월 ~ 4=금

    day_names = {0: "월", 1: "화", 2: "수", 3: "목", 4: "금"}
    result = {}
    for dow in range(5):
        day_data = df[df["day_of_week"] == dow]["daily_return"].dropna()
        if len(day_data) < 10:
            continue
        result[day_names[dow]] = {
            "avg_return": round(day_data.mean(), 3),
            "win_rate": round((day_data > 0).sum() / len(day_data) * 100, 1),
            "count": len(day_data),
            "best": round(day_data.max(), 2),
            "worst": round(day_data.min(), 2),
        }
    return result if result else None


def analyze_monthly_pattern(ticker: str) -> Optional[Dict]:
    """월별 수익률 패턴 분석"""
    df = get_daily_ohlcv(ticker, days=365 * 3)
    if len(df) < 60:
        return None

    # 월별 수익률 계산
    monthly = df["종가"].resample("ME").last().pct_change() * 100
    monthly = monthly.dropna()
    if len(monthly) < 6:
        return None

    monthly_df = pd.DataFrame({"return": monthly})
    monthly_df["month"] = monthly_df.index.month

    month_names = {1: "1월", 2: "2월", 3: "3월", 4: "4월", 5: "5월", 6: "6월",
                   7: "7월", 8: "8월", 9: "9월", 10: "10월", 11: "11월", 12: "12월"}
    result = {}
    for m in range(1, 13):
        m_data = monthly_df[monthly_df["month"] == m]["return"]
        if len(m_data) < 1:
            continue
        result[month_names[m]] = {
            "avg_return": round(m_data.mean(), 2),
            "win_rate": round((m_data > 0).sum() / len(m_data) * 100, 1),
            "count": len(m_data),
        }
    return result if result else None


def analyze_intraday_pattern(ticker: str) -> Optional[Dict]:
    """시가 vs 종가 장중 패턴 분석 (일봉 기반)"""
    df = get_daily_ohlcv(ticker, days=365 * 3)
    if len(df) < 60:
        return None

    # 갭 (전일 종가 → 당일 시가)
    df["gap"] = (df["시가"] / df["종가"].shift(1) - 1) * 100
    # 장중 (시가 → 종가)
    df["intraday"] = (df["종가"] / df["시가"] - 1) * 100
    # 상/하 꼬리
    df["upper_wick"] = (df["고가"] / df[["시가", "종가"]].max(axis=1) - 1) * 100
    df["lower_wick"] = (1 - df["저가"] / df[["시가", "종가"]].min(axis=1)) * 100

    df = df.dropna(subset=["gap", "intraday"])
    if len(df) < 30:
        return None

    gap_up_days = df[df["gap"] > 0.3]
    gap_down_days = df[df["gap"] < -0.3]

    return {
        "avg_gap": round(df["gap"].mean(), 3),
        "avg_intraday": round(df["intraday"].mean(), 3),
        "gap_up_then_close": {
            "count": len(gap_up_days),
            "avg_intraday": round(gap_up_days["intraday"].mean(), 3) if len(gap_up_days) > 0 else 0,
            "fill_rate": round((gap_up_days["intraday"] < 0).sum() / len(gap_up_days) * 100, 1) if len(gap_up_days) > 0 else 0,
        },
        "gap_down_then_close": {
            "count": len(gap_down_days),
            "avg_intraday": round(gap_down_days["intraday"].mean(), 3) if len(gap_down_days) > 0 else 0,
            "fill_rate": round((gap_down_days["intraday"] > 0).sum() / len(gap_down_days) * 100, 1) if len(gap_down_days) > 0 else 0,
        },
        "avg_upper_wick": round(df["upper_wick"].mean(), 3),
        "avg_lower_wick": round(df["lower_wick"].mean(), 3),
        "intraday_up_rate": round((df["intraday"] > 0).sum() / len(df) * 100, 1),
        "total_days": len(df),
    }


def analyze_time_snapshot_pattern(ticker: str) -> Optional[Dict]:
    """스냅샷 기반 시간대별 가격 변동 패턴 (데이터 축적 후 사용 가능)"""
    snapshots = get_snapshots(ticker, days=90)
    if len(snapshots) < 20:
        return None

    snapshots["hour"] = snapshots["captured_at"].dt.hour
    snapshots["price_change"] = snapshots["price"].pct_change() * 100

    result = {}
    for hour in range(9, 16):  # 장 시간대
        h_data = snapshots[snapshots["hour"] == hour]["price_change"].dropna()
        if len(h_data) < 3:
            continue
        result[f"{hour}시"] = {
            "avg_change": round(h_data.mean(), 3),
            "win_rate": round((h_data > 0).sum() / len(h_data) * 100, 1),
            "count": len(h_data),
        }
    return result if result else None


# 앱 시작 시 DB 초기화
init_db()
