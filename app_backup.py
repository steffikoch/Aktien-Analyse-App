import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path

st.set_page_config(page_title="Aktien-Analyse-App", layout="wide")
st.title("Aktien-Analyse-App")
st.caption("Automatische Fundamentalanalyse mit Daten von Yahoo Finance")

SAVE_FILE = Path("analysen.csv")

def fmt_number(value, decimals=2):
    if value is None or pd.isna(value):
        return "n.v."
    return f"{value:.{decimals}f}"

def fmt_billions(value, currency=""):
    if value is None or pd.isna(value):
        return "n.v."
    return f"{value / 1_000_000_000:.2f} Mrd. {currency}".strip()

def get_row_value(df, row_name, col_index=0):
    try:
        if df is None or df.empty or row_name not in df.index or df.shape[1] <= col_index:
            return None
        value = df.loc[row_name].iloc[col_index]
        return None if pd.isna(value) else float(value)
    except Exception:
        return None

def first_available(df, names, col_index=0):
    for name in names:
        value = get_row_value(df, name, col_index)
        if value is not None:
            return value
    return None

def safe_growth(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return ((current / previous) - 1) * 100

def safe_margin(part, total):
    if part is None or total is None or total == 0:
        return None
    return (part / total) * 100

def clamp(value, low, high):
    return max(low, min(high, value))

ticker = st.text_input("Aktien-Ticker eingeben:", "SAP.DE").strip().upper()

with st.sidebar:
    st.header("Fair-Value-Annahmen")
    target_pe = st.number_input("Ziel-KGV", 5.0, 60.0, 25.0, 0.5)
    target_fcf_yield = st.number_input("Ziel-Free-Cashflow-Rendite (%)", 1.0, 15.0, 4.0, 0.25)
safety_margin = st.number_input("Sicherheitsmarge (%)", 0.0, 50.0, 15.0, step=1.0)
if ticker:
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(period="5d")
        if history.empty or "Close" not in history.columns:
            st.error("Für diesen Ticker konnten keine Kursdaten geladen werden.")
            st.stop()

        price = float(history["Close"].dropna().iloc[-1])

        try:
            info = stock.info or {}
        except Exception:
            info = {}

        try:
            income = stock.income_stmt
            
        except Exception:
            income = pd.DataFrame()

        try:
            balance = stock.balance_sheet
        except Exception:
            balance = pd.DataFrame()

        try:
            cashflow = stock.cashflow
        except Exception:
            cashflow = pd.DataFrame()

        name = info.get("longName") or info.get("shortName") or ticker
        sector = info.get("sector", "")
        industry = info.get("industry", "")
        is_financial = sector == "Financial Services"
        currency = info.get("currency") or ""

        eps = first_available(income, ["Diluted EPS", "Basic EPS"])
        revenue = first_available(income, ["Total Revenue", "Operating Revenue"])
        revenue_prev = first_available(income, ["Total Revenue", "Operating Revenue"], 1)

        net_income_names = [
            "Net Income",
            "Net Income Common Stockholders",
            "Net Income From Continuing Operation Net Minority Interest",
        ]
        
        net_income = first_available(income, net_income_names)
        net_income_prev = first_available(income, net_income_names, 1)
        
        revenue_growth = safe_growth(revenue, revenue_prev)
        earnings_growth = safe_growth(net_income, net_income_prev)
        net_margin = safe_margin(net_income, revenue)
        kgv = price / eps if eps is not None and eps > 0 else None

        free_cash_flow = first_available(cashflow, ["Free Cash Flow"])
        operating_cf = first_available(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        capex = first_available(cashflow, ["Capital Expenditure", "Capital Expenditures"])
        if free_cash_flow is None and operating_cf is not None and capex is not None:
            free_cash_flow = operating_cf + capex if capex < 0 else operating_cf - capex

        fcf_margin = safe_margin(free_cash_flow, revenue)

        total_debt = first_available(balance, ["Total Debt", "Long Term Debt And Capital Lease Obligation"])
        cash = first_available(balance, [
            "Cash Cash Equivalents And Short Term Investments",
            "Cash And Cash Equivalents",
            "Cash",
        ])
        

        net_debt = total_debt - cash if total_debt is not None and cash is not None else None
        st.write("Netto-Cash:" if net_debt < 0 else "Nettoverschuldung:", f"{abs(net_debt) / 1_000_000_000:.2f} Mrd.EUR")
        net_debt_to_fcf = (
            net_debt / free_cash_flow
            if net_debt is not None and free_cash_flow is not None and free_cash_flow > 0
            else None
        )

        market_cap = info.get("marketCap")
        shares = info.get("sharesOutstanding")
        dividend_yield = info.get("dividendYield")
        roe = info.get("returnOnEquity")
        if roe is not None:
            roe *= 100

        effective_pe = 12 if is_financial else target_pe
        fair_value_pe =eps * effective_pe if eps is not None and eps > 0 else None
        fair_value_fcf = None
        if not is_financial and free_cash_flow is not None and shares and shares > 0:
            fcf_per_share = free_cash_flow / shares
            fair_value_fcf = fcf_per_share / (target_fcf_yield / 100)

        fair_values = [x for x in [fair_value_pe, fair_value_fcf] if x is not None and x > 0]
        fair_value = sum(fair_values) / len(fair_values) if fair_values else None
        net_cash_per_share = (-net_debt / shares) if net_debt is not None and net_debt < 0 and shares else 0
        if fair_value is not None and not is_financial:
            fair_value += net_cash_per_share
        buy_price = fair_value * (1 - safety_margin / 100) if fair_value is not None else None
        buy_price_10 = fair_value * 0.90 if fair_value is not None else None
        buy_price_15 = fair_value * 0.85 if fair_value is not None else None
        buy_price_20 = fair_value * 0.80 if fair_value is not None else None
        st.write("Netto-Cash je Aktie:", f"{net_cash_per_share:.2f} EUR")
        upside = ((fair_value / price) - 1) * 100 if fair_value is not None and price > 0 else None

        score = 0
        if net_margin is not None:
            score += 20 if net_margin >= 20 else 15 if net_margin >= 10 else 10 if net_margin >= 5 else 5 if net_margin > 0 else 0
        if revenue_growth is not None:
            score += 20 if revenue_growth >= 15 else 15 if revenue_growth >= 8 else 10 if revenue_growth >= 3 else 5 if revenue_growth > 0 else 0
        if earnings_growth is not None:
            score += 20 if earnings_growth >= 15 else 15 if earnings_growth >= 8 else 10 if earnings_growth >= 3 else 5 if earnings_growth > 0 else 0
        if fcf_margin is not None:
            score += 20 if fcf_margin >= 20 else 15 if fcf_margin >= 10 else 10 if fcf_margin >= 5 else 5 if fcf_margin > 0 else 0
        if net_debt_to_fcf is not None:
            score += 20 if net_debt_to_fcf <= 0 else 15 if net_debt_to_fcf <= 1 else 10 if net_debt_to_fcf <= 2 else 5 if net_debt_to_fcf <= 3 else 0
        elif net_debt is not None and net_debt <= 0:
            score += 20

        score = int(clamp(score, 0, 100))

        if fair_value is None or buy_price_10 is None or buy_price_15 is None or buy_price_20 is None:
           verdict = "Daten prüfen"
        elif price <= buy_price_20:
            verdict = "\U0001F7E2 Starker Kauf" 
        elif price <= buy_price_15:
            verdict = "\U0001F7E1 Kaufen"
        elif price <= buy_price_10:
            verdict = "\U0001F7E0 Beobachten"
        else:
            verdict = "\U0001F535 Neutral / abwarten"    

        st.subheader(name)

        c1, c2, c3 = st.columns(3)
        c1.metric("Aktueller Kurs", f"{price:.2f} {currency}")
        c2.metric("KGV", fmt_number(kgv))
        c3.metric("Gewinn je Aktie (EPS)", f"{fmt_number(eps)} {currency}")

        c4, c5, c6 = st.columns(3)
        c4.metric("Umsatz", fmt_billions(revenue, currency))
        c5.metric("Nettogewinn", fmt_billions(net_income, currency))
        c6.metric("Nettomarge", f"{fmt_number(net_margin)} %")

        c7, c8, c9 = st.columns(3)
        c7.metric("Umsatzwachstum", f"{fmt_number(revenue_growth)} %")
        c8.metric("Gewinnwachstum", f"{fmt_number(earnings_growth)} %")
        c9.metric("Free-Cashflow-Marge", f"{fmt_number(fcf_margin)} %")

        st.divider()
        st.subheader("Cashflow & Bilanz")

        b1, b2, b3 = st.columns(3)
        b1.metric("Free Cashflow", fmt_billions(free_cash_flow, currency))
        b2.metric("Nettoverschuldung", fmt_billions(net_debt, currency))
        b3.metric("Net Debt / FCF", fmt_number(net_debt_to_fcf))

        b4, b5, b6 = st.columns(3)
        b4.metric("Marktkapitalisierung", fmt_billions(market_cap, currency))
        b5.metric("Dividendenrendite", f"{fmt_number(dividend_yield)} %")
        b6.metric("Eigenkapitalrendite (ROE)", f"{fmt_number(roe)} %")

        st.divider()
        st.subheader("Fair Value")

        f1, f2, f3 = st.columns(3)
        f1.metric("Fair Value – KGV-Methode", f"{fmt_number(fair_value_pe)} {currency}")
        f2.metric("Fair Value – FCF-Methode", f"{fmt_number(fair_value_fcf)} {currency}")
        f3.metric("Fair Value – Durchschnitt", f"{fmt_number(fair_value)} {currency}")
        k1, k2, k3 = st.columns(3)
        k1.metric("Kaufzone -10 %", f"{fmt_number(buy_price_10)} {currency}")
        k2.metric("Kaufzone -15 %", f"{fmt_number(buy_price_15)} {currency}")
        k3.metric("Kaufzone -20 %", f"{fmt_number(buy_price_20)} {currency}")
        if upside is not None:
            st.metric("Potenzial zum Fair Value", f"{upside:.2f} %")

        st.subheader("Qualität & Urteil")
        q1, q2 = st.columns(2)
        q1.metric("Qualitätsscore", f"{score}/100")
        q2.metric("Bewertung", verdict)

        st.caption("Hinweis: Der Fair Value ist eine Modellschätzung und keine Anlageberatung.")

        analysis_row = pd.DataFrame([{
            "Zeitpunkt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Ticker": ticker,
            "Unternehmen": name,
            "Währung": currency,
            "Kurs": price,
            "EPS": eps,
            "KGV": kgv,
            "Umsatz": revenue,
            "Nettogewinn": net_income,
            "Nettomarge_%": net_margin,
            "Umsatzwachstum_%": revenue_growth,
            "Gewinnwachstum_%": earnings_growth,
            "Free_Cashflow": free_cash_flow,
            "FCF_Marge_%": fcf_margin,
            "Nettoverschuldung": net_debt,
            "Net_Debt_zu_FCF": net_debt_to_fcf,
            "Dividendenrendite_%": dividend_yield,
            "ROE_%": roe,
            "Ziel_KGV": target_pe,
            "Ziel_FCF_Rendite_%": target_fcf_yield,
            "Fair_Value_KGV": fair_value_pe,
            "Fair_Value_FCF": fair_value_fcf,
            "Fair_Value": fair_value,
            "Potenzial_%": upside,
            "Qualitätsscore": score,
            "Bewertung": verdict,
        }])

        st.divider()
        st.subheader("Analyse speichern")

        if st.button("Analyse dauerhaft speichern"):
            if SAVE_FILE.exists():
                old = pd.read_csv(SAVE_FILE)
                combined = pd.concat([old, analysis_row], ignore_index=True)
            else:
                combined = analysis_row
            combined.to_csv(SAVE_FILE, index=False)
            st.success("Analyse wurde in 'analysen.csv' gespeichert.")

        st.download_button(
            "Aktuelle Analyse als CSV herunterladen",
            data=analysis_row.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{ticker}_analyse.csv",
            mime="text/csv",
        )

        if SAVE_FILE.exists():
            st.subheader("Gespeicherte Analysen")
            st.dataframe(pd.read_csv(SAVE_FILE), use_container_width=True)

    except Exception as e:
        st.error("Beim Laden oder Berechnen der Daten ist ein Fehler aufgetreten.")
        st.exception(e)