import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Aktien-Analyse-App", layout="centered")
st.title("Aktien-Analyse-App")
st.caption("Automatische Fundamentalanalyse mit Daten von Yahoo Finance")

SAVE_FILE = Path("analysen.csv")

ISIN_MAP = {
    "US2561631068": "DOCU",
    "US5738741041": "MRVL",
    "DE0007664039": "VOW3.DE",
    "DE0007030009": "RHM.DE",
    "US0126531013": "ALB",
    "US4227041062": "HL",
    "DE0007164600": "SAP.DE",
    "DE0005140008": "DBK.DE",
    "DE0008404005": "ALV.DE",
    "DE0005557508": "DTE.DE",
}

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# Häufige Kurzformen / Firmennamen
ALIAS_MAP = {
    "VW": "VOW3.DE",
    "VOLKSWAGEN": "VOW3.DE",
    "VOLKSWAGEN AG": "VOW3.DE",
    "VOW3": "VOW3.DE",
    "SAP": "SAP.DE",
    "DEUTSCHE BANK": "DBK.DE",
    "ALLIANZ": "ALV.DE",
    "DEUTSCHE TELEKOM": "DTE.DE",
    "TELEKOM": "DTE.DE",
    "RHEINMETALL": "RHM.DE",
    "DOCUSIGN": "DOCU",
    "MARVELL": "MRVL",
    "ALBEMARLE": "ALB",
    "HECLA MINING": "HL",
}


def fmt_number(value, decimals=2):
    if value is None or pd.isna(value):
        return "n.v."
    return f"{value:.{decimals}f}"


def fmt_billions(value, currency=""):
    if value is None or pd.isna(value):
        return "n.v."
    return f"{value / 1_000_000_000:.2f} Mrd. {currency}".strip()


def fmt_percent(value, decimals=2):
    if value is None or pd.isna(value):
        return "n.v."
    return f"{value:.{decimals}f} %"


def first_valid(*values):
    for value in values:
        if value is not None and not pd.isna(value):
            return value
    return None


def resolve_query(query):
    q = query.strip()
    upper = q.upper()

    if upper in ISIN_MAP:
        return [(ISIN_MAP[upper], f"{upper} → {ISIN_MAP[upper]}")]

    if upper in ALIAS_MAP:
        symbol = ALIAS_MAP[upper]
        return [(symbol, f"{q} → {symbol}")]

    looks_like_ticker = (
        len(q) <= 12
        and " " not in q
        and not ISIN_RE.match(upper)
        and re.match(r"^[A-Za-z0-9.\-^=]+$", q)
    )

    candidates = []
    if looks_like_ticker:
        candidates.append((upper, upper))

    try:
        search = yf.Search(q, max_results=8)
        for item in getattr(search, "quotes", []) or []:
            symbol = item.get("symbol")
            if not symbol:
                continue
            quote_type = item.get("quoteType", "")
            if quote_type not in {"EQUITY", ""}:
                continue
            name = (
                item.get("shortname")
                or item.get("longname")
                or item.get("displayName")
                or symbol
            )
            exchange = item.get("exchDisp") or item.get("exchange") or ""
            label = f"{name} ({symbol})"
            if exchange:
                label += f" – {exchange}"
            candidates.append((symbol, label))
    except Exception:
        pass

    unique = {}
    for symbol, label in candidates:
        unique[symbol] = label
    return [(symbol, label) for symbol, label in unique.items()]


def get_target_pe(sector, industry):
    sector = (sector or "").lower()
    industry = (industry or "").lower()

    if any(x in industry for x in ["auto manufacturer", "automobile", "auto & truck"]):
        return 8.0, "Autohersteller"
    if any(x in industry for x in ["bank", "banks"]):
        return 11.0, "Bank"
    if "insurance" in industry:
        return 12.0, "Versicherung"
    if any(x in industry for x in ["semiconductor", "software", "information technology"]):
        return 25.0, "Technologie"
    if any(x in industry for x in ["gold", "silver", "copper", "mining", "specialty chemicals"]):
        return 12.0, "Rohstoffe / Bergbau"

    sector_map = {
        "technology": (25.0, "Technologie"),
        "communication services": (20.0, "Kommunikation"),
        "consumer cyclical": (18.0, "Zyklischer Konsum"),
        "consumer defensive": (20.0, "Defensiver Konsum"),
        "industrials": (18.0, "Industrie"),
        "healthcare": (22.0, "Gesundheit"),
        "financial services": (12.0, "Finanzwerte"),
        "energy": (12.0, "Energie"),
        "basic materials": (12.0, "Grundstoffe"),
        "utilities": (15.0, "Versorger"),
        "real estate": (15.0, "Immobilien"),
    }
    return sector_map.get(sector, (18.0, "Standard"))


def sanitize_growth(value):
    if value is None or pd.isna(value):
        return None, False
    pct = value * 100 if abs(value) <= 10 else value
    if pct < -100 or pct > 200:
        return pct, True
    return pct, False


def calc_quality_score(
    net_margin_pct,
    revenue_growth_pct,
    earnings_growth_pct,
    earnings_growth_special,
    fcf_margin_pct,
    net_debt_fcf,
    roe_pct,
):
    score = 0

    if net_margin_pct is not None:
        if net_margin_pct >= 20:
            score += 20
        elif net_margin_pct >= 10:
            score += 15
        elif net_margin_pct >= 5:
            score += 10
        elif net_margin_pct > 0:
            score += 5

    if revenue_growth_pct is not None:
        if revenue_growth_pct >= 15:
            score += 15
        elif revenue_growth_pct >= 5:
            score += 10
        elif revenue_growth_pct >= 0:
            score += 5

    if earnings_growth_pct is not None and not earnings_growth_special:
        if earnings_growth_pct >= 15:
            score += 15
        elif earnings_growth_pct >= 5:
            score += 10
        elif earnings_growth_pct >= 0:
            score += 5

    if fcf_margin_pct is not None:
        if fcf_margin_pct >= 20:
            score += 20
        elif fcf_margin_pct >= 10:
            score += 15
        elif fcf_margin_pct >= 5:
            score += 10
        elif fcf_margin_pct > 0:
            score += 5

    if net_debt_fcf is not None:
        if net_debt_fcf <= 0:
            score += 15
        elif net_debt_fcf <= 1:
            score += 12
        elif net_debt_fcf <= 2:
            score += 8
        elif net_debt_fcf <= 3:
            score += 4

    if roe_pct is not None:
        if roe_pct >= 20:
            score += 15
        elif roe_pct >= 15:
            score += 12
        elif roe_pct >= 10:
            score += 8
        elif roe_pct > 0:
            score += 4

    return max(0, min(100, int(round(score))))


def load_saved():
    if SAVE_FILE.exists():
        try:
            return pd.read_csv(SAVE_FILE)
        except Exception:
            pass
    return pd.DataFrame()


query = st.text_input("Aktie suchen (Name, Ticker oder ISIN):", value="SAP.DE")

security_margin = st.number_input(
    "Sicherheitsmarge (%)",
    min_value=0.0,
    max_value=50.0,
    value=15.0,
    step=1.0,
)

if query.strip():
    candidates = resolve_query(query)

    if not candidates:
        st.error("Keine passende Aktie gefunden.")
        st.stop()

    if len(candidates) == 1:
        ticker_symbol = candidates[0][0]
    else:
        labels = [label for _, label in candidates]
        selected_label = st.selectbox("Passende Aktie auswählen:", labels)
        ticker_symbol = candidates[labels.index(selected_label)][0]

    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info or {}
        fast = getattr(ticker, "fast_info", {}) or {}

        company_name = info.get("longName") or info.get("shortName") or ticker_symbol
        currency = info.get("currency") or fast.get("currency") or ""

        current_price = first_valid(
            info.get("currentPrice"),
            info.get("regularMarketPrice"),
            fast.get("last_price"),
        )
        eps = first_valid(info.get("trailingEps"), info.get("epsTrailingTwelveMonths"))
        pe = first_valid(
            info.get("trailingPE"),
            (current_price / eps if current_price and eps and eps > 0 else None),
        )

        revenue = info.get("totalRevenue")
        net_income = first_valid(info.get("netIncomeToCommon"), info.get("netIncome"))
        net_margin = info.get("profitMargins")
        revenue_growth_raw = info.get("revenueGrowth")
        earnings_growth_raw = info.get("earningsGrowth")
        free_cash_flow = info.get("freeCashflow")
        total_cash = info.get("totalCash")
        total_debt = info.get("totalDebt")
        market_cap = first_valid(info.get("marketCap"), fast.get("market_cap"))
        dividend_yield_raw = info.get("dividendYield")
        roe_raw = info.get("returnOnEquity")
        shares = first_valid(info.get("sharesOutstanding"), info.get("impliedSharesOutstanding"))
        sector = info.get("sector") or ""
        industry = info.get("industry") or ""

        revenue_growth_pct = revenue_growth_raw * 100 if revenue_growth_raw is not None else None
        earnings_growth_pct, earnings_growth_special = sanitize_growth(earnings_growth_raw)
        net_margin_pct = net_margin * 100 if net_margin is not None else None
        roe_pct = roe_raw * 100 if roe_raw is not None else None

        if dividend_yield_raw is None or pd.isna(dividend_yield_raw):
            dividend_yield_pct = 0.0
        else:
            dividend_yield_pct = dividend_yield_raw * 100 if dividend_yield_raw <= 1 else dividend_yield_raw

        fcf_margin_pct = None
        if free_cash_flow is not None and revenue not in (None, 0):
            fcf_margin_pct = free_cash_flow / revenue * 100

        net_debt = None
        net_cash = None
        if total_debt is not None or total_cash is not None:
            debt = total_debt or 0
            cash = total_cash or 0
            net_debt = debt - cash
            net_cash = max(cash - debt, 0)

        net_cash_per_share = 0.0
        if net_cash is not None and shares not in (None, 0):
            net_cash_per_share = net_cash / shares

        net_debt_fcf = None
        if net_debt is not None and free_cash_flow is not None and free_cash_flow > 0:
            net_debt_fcf = net_debt / free_cash_flow

        auto_target_pe, pe_reason = get_target_pe(sector, industry)

        with st.expander("Fair-Value-Annahmen"):
            st.caption(
                f"Automatische Einstufung: {pe_reason}"
                + (f" | Sektor: {sector}" if sector else "")
                + (f" | Branche: {industry}" if industry else "")
            )
            target_pe = st.number_input(
                "Ziel-KGV",
                min_value=1.0,
                max_value=60.0,
                value=float(auto_target_pe),
                step=0.5,
            )

        fair_value_pe = None
        fair_value = None
        if eps is not None and eps > 0:
            fair_value_pe = eps * target_pe
            fair_value = fair_value_pe + net_cash_per_share

        quality_score = calc_quality_score(
            net_margin_pct,
            revenue_growth_pct,
            earnings_growth_pct,
            earnings_growth_special,
            fcf_margin_pct,
            net_debt_fcf,
            roe_pct,
        )

        st.markdown(f"## {company_name}")
        st.metric("Aktueller Kurs", f"{fmt_number(current_price)} {currency}")
        st.metric("KGV", fmt_number(pe))
        st.metric("Gewinn je Aktie (EPS)", f"{fmt_number(eps)} {currency}")
        st.metric("Umsatz", fmt_billions(revenue, currency))
        st.metric("Nettogewinn", fmt_billions(net_income, currency))
        st.metric("Nettomarge", fmt_percent(net_margin_pct))
        st.metric("Umsatzwachstum", fmt_percent(revenue_growth_pct))

        if earnings_growth_special:
            st.metric("Gewinnwachstum", "Sondereffekt")
            st.caption(
                f"Yahoo meldet {fmt_percent(earnings_growth_pct)}. "
                "Dieser extreme Wert wird nicht im Qualitätsscore berücksichtigt."
            )
        else:
            st.metric("Gewinnwachstum", fmt_percent(earnings_growth_pct))

        st.metric("Free-Cashflow-Marge", fmt_percent(fcf_margin_pct))

        st.divider()
        st.subheader("Cashflow & Bilanz")
        st.metric("Free Cashflow", fmt_billions(free_cash_flow, currency))
        st.metric("Nettoverschuldung", fmt_billions(net_debt, currency))
        st.metric("Net Debt / FCF", fmt_number(net_debt_fcf))
        st.metric("Marktkapitalisierung", fmt_billions(market_cap, currency))
        st.metric("Dividendenrendite", fmt_percent(dividend_yield_pct))
        st.metric("Eigenkapitalrendite (ROE)", fmt_percent(roe_pct))

        st.divider()
        st.subheader("Fair Value")

        if fair_value is None or current_price is None:
            st.warning(
                "Für diese Aktie kann aktuell kein belastbarer KGV-Fair-Value berechnet werden, "
                "z. B. wegen fehlendem oder negativem EPS."
            )
            potential_pct = None
            buy_10 = buy_15 = buy_20 = personal_limit = None
        else:
            buy_10 = fair_value * 0.90
            buy_15 = fair_value * 0.85
            buy_20 = fair_value * 0.80
            personal_limit = fair_value * (1 - security_margin / 100)
            potential_pct = (fair_value / current_price - 1) * 100

            st.metric("Fair Value", f"{fair_value:.2f} {currency}")
            st.metric("KGV-Basiswert", f"{fair_value_pe:.2f} {currency}")
            st.metric("Netto-Cash je Aktie", f"{net_cash_per_share:.2f} {currency}")
            st.metric("Kaufzone -10 %", f"{buy_10:.2f} {currency}")
            st.metric("Kaufzone -15 %", f"{buy_15:.2f} {currency}")
            st.metric("Kaufzone -20 %", f"{buy_20:.2f} {currency}")
            st.metric(
                f"Persönliche Kaufgrenze ({security_margin:.0f} %)",
                f"{personal_limit:.2f} {currency}",
            )
            st.metric("Potenzial zum Fair Value", f"{potential_pct:.2f} %")

            st.markdown("### 5-Jahres-Chart")
            try:
                hist = ticker.history(period="5y", auto_adjust=True)
                if not hist.empty and "Close" in hist:
                    chart_df = pd.DataFrame(index=hist.index)
                    chart_df["Kurs"] = hist["Close"]
                    chart_df["Fair Value"] = fair_value
                    chart_df["Kaufzone -10 %"] = buy_10
                    chart_df["Kaufzone -15 %"] = buy_15
                    chart_df["Kaufzone -20 %"] = buy_20
                    st.line_chart(chart_df)
                else:
                    st.info("Für den 5-Jahres-Chart sind keine Kursdaten verfügbar.")
            except Exception:
                st.info("Der 5-Jahres-Chart konnte aktuell nicht geladen werden.")

        st.divider()
        st.subheader("Qualität & Urteil")
        st.metric("Qualitätsscore", f"{quality_score}/100")

        if potential_pct is None:
            verdict = "⚪ Keine Bewertung möglich"
        elif potential_pct >= 10:
            verdict = f"🟢 Unterbewertet (+{potential_pct:.1f} %)"
        elif potential_pct <= -10:
            verdict = f"🔴 Überbewertet ({potential_pct:.1f} %)"
        else:
            verdict = f"🟡 Fair bewertet ({potential_pct:+.1f} %)"

        st.metric("Bewertung", verdict)

        if quality_score < 30 and potential_pct is not None and potential_pct >= 10:
            st.warning(
                "Achtung: Rechnerisch unterbewertet, aber sehr niedriger Qualitätsscore. "
                "Mögliches Value-Trap-Risiko."
            )

        st.caption(
            "Hinweis: Der Fair Value ist eine Modellschätzung und keine Anlageberatung. "
            "Sektorabhängige Ziel-KGVs sind Startwerte und werden in der Testphase geprüft."
        )

        if st.button("Analyse speichern"):
            row = {
                "Datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Ticker": ticker_symbol,
                "Unternehmen": company_name,
                "Kurs": current_price,
                "Währung": currency,
                "Ziel-KGV": target_pe,
                "Fair Value": fair_value,
                "Potenzial %": potential_pct,
                "Qualitätsscore": quality_score,
                "Bewertung": verdict,
            }
            old = load_saved()
            new = pd.concat([old, pd.DataFrame([row])], ignore_index=True)
            new.to_csv(SAVE_FILE, index=False)
            st.success("Analyse gespeichert.")

        st.divider()
        st.subheader("Gespeicherte Analysen")
        saved = load_saved()
        if saved.empty:
            st.caption("Noch keine Analysen gespeichert.")
        else:
            st.dataframe(saved, hide_index=True, width="stretch")

    except Exception as exc:
        st.error("Die Aktie konnte nicht vollständig geladen werden.")
        st.caption(f"Technischer Hinweis: {exc}")
