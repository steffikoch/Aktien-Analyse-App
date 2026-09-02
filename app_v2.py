import streamlit as st
import yfinance as yf
from datetime import datetime

st.set_page_config(
    page_title="Aktien-Analyse V2",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Aktien-Analyse V2")
st.caption("Modul 1 + 2 – Aktiensuche & Datenbasis")


# -----------------------------
# Hilfsfunktionen
# -----------------------------

def text_or_dash(value):
    if value is None or value == "":
        return "–"
    return str(value)


def format_number(value):
    if value is None:
        return "–"

    try:
        value = float(value)

        if abs(value) >= 1_000_000_000_000:
            return f"{value / 1_000_000_000_000:,.2f} Bio."

        if abs(value) >= 1_000_000_000:
            return f"{value / 1_000_000_000:,.2f} Mrd."

        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:,.2f} Mio."

        return f"{value:,.2f}"

    except Exception:
        return "–"


def format_money(value, currency):
    if value is None:
        return "–"

    formatted = format_number(value)

    if formatted == "–":
        return "–"

    return f"{formatted} {currency}"


def format_eps(value, currency):
    if value is None:
        return "–"

    try:
        return f"{float(value):,.2f} {currency}"
    except Exception:
        return "–"


def format_date(timestamp):
    if timestamp is None:
        return "–"

    try:
        date_value = datetime.fromtimestamp(timestamp)
        return date_value.strftime("%d.%m.%Y")
    except Exception:
        return "–"


def find_stock(search_text):
    query = search_text.strip()

    if not query:
        return None

    search = yf.Search(
        query,
        max_results=10,
        news_count=0
    )

    quotes = search.quotes or []

    if not quotes:
        return None

    equities = [
        item for item in quotes
        if str(item.get("quoteType", "")).upper() == "EQUITY"
    ]

    candidates = equities if equities else quotes

    query_upper = query.upper()

    # Exakten Ticker bevorzugen
    for item in candidates:
        symbol = str(item.get("symbol", "")).upper()

        if symbol == query_upper:
            return item

    # Sonst besten Suchtreffer verwenden
    return candidates[0]


# -----------------------------
# Daten laden
# -----------------------------

@st.cache_data(ttl=900, show_spinner=False)
def load_stock(search_text):

    result = find_stock(search_text)

    if not result:
        return None

    symbol = result.get("symbol")

    if not symbol:
        return None

    ticker = yf.Ticker(symbol)
    info = ticker.info or {}

    name = (
        info.get("longName")
        or info.get("shortName")
        or result.get("longname")
        or result.get("shortname")
        or symbol
    )

    price = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )

    earnings_timestamp = (
        info.get("earningsTimestamp")
        or info.get("earningsTimestampStart")
    )

    return {
        "name": name,
        "symbol": symbol,

        "quote_type": (
            info.get("quoteType")
            or result.get("quoteType")
        ),

        "exchange": (
            info.get("exchange")
            or result.get("exchange")
        ),

        "exchange_name": (
            info.get("fullExchangeName")
            or result.get("exchDisp")
            or result.get("exchange")
        ),

        "price": price,
        "currency": info.get("currency"),

        "sector": info.get("sector"),
        "industry": info.get("industry"),

        # Bewertungs-Daten
        "market_cap": info.get("marketCap"),
        "trailing_eps": info.get("trailingEps"),
        "forward_eps": info.get("forwardEps"),

        # Unternehmens-Daten
        "revenue": info.get("totalRevenue"),
        "net_income": info.get("netIncomeToCommon"),
        "free_cashflow": info.get("freeCashflow"),

        # Bilanz
        "cash": info.get("totalCash"),
        "debt": info.get("totalDebt"),

        # Wachstum
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),

        # Profitabilität
        "profit_margin": info.get("profitMargins"),
        "roe": info.get("returnOnEquity"),

        # Termine
        "earnings_timestamp": earnings_timestamp
    }


# -----------------------------
# Suche
# -----------------------------

search_text = st.text_input(
    "Aktie suchen",
    placeholder="z. B. Microsoft, MSFT, Volkswagen, Allianz oder ALB"
).strip()


if search_text:

    with st.spinner("Aktie wird gesucht und Daten werden geladen..."):

        try:

            data = load_stock(search_text)

            if not data:

                st.error(
                    "Aktie konnte nicht eindeutig gefunden werden."
                )

            else:

                currency = text_or_dash(data["currency"])

                st.success("Aktie gefunden")

                st.header(data["name"])

                if search_text.upper() != str(data["symbol"]).upper():

                    st.info(
                        f"„{search_text}“ → "
                        f"{data['symbol']} automatisch erkannt"
                    )

                # -----------------------------
                # Unternehmensübersicht
                # -----------------------------

                col1, col2 = st.columns(2)

                with col1:

                    st.write(
                        f"**Ticker:** "
                        f"{text_or_dash(data['symbol'])}"
                    )

                    st.write(
                        f"**Typ:** "
                        f"{text_or_dash(data['quote_type'])}"
                    )

                    st.write(
                        f"**Börse:** "
                        f"{text_or_dash(data['exchange_name'])}"
                    )

                with col2:

                    st.write(
                        f"**Währung:** "
                        f"{currency}"
                    )

                    st.write(
                        f"**Sektor:** "
                        f"{text_or_dash(data['sector'])}"
                    )

                    st.write(
                        f"**Branche:** "
                        f"{text_or_dash(data['industry'])}"
                    )

                st.divider()

                # -----------------------------
                # Kurs
                # -----------------------------

                st.subheader("Aktueller Kurs")

                if data["price"] is not None:

                    st.metric(
                        label="Kurs",
                        value=f"{data['price']:,.2f} {currency}"
                    )

                else:

                    st.warning(
                        "Aktueller Kurs nicht verfügbar."
                    )

                st.divider()

                # -----------------------------
                # Datenbasis
                # -----------------------------

                st.subheader("📋 Datenbasis für die Bewertung")

                col1, col2 = st.columns(2)

                with col1:

                    st.metric(
                        "Marktkapitalisierung",
                        format_money(
                            data["market_cap"],
                            currency
                        )
                    )

                    st.metric(
                        "EPS aktuell (TTM)",
                        format_eps(
                            data["trailing_eps"],
                            currency
                        )
                    )

                    st.metric(
                        "EPS erwartet (Forward)",
                        format_eps(
                            data["forward_eps"],
                            currency
                        )
                    )

                    st.metric(
                        "Umsatz",
                        format_money(
                            data["revenue"],
                            currency
                        )
                    )

                with col2:

                    st.metric(
                        "Nettogewinn",
                        format_money(
                            data["net_income"],
                            currency
                        )
                    )

                    st.metric(
                        "Free Cashflow",
                        format_money(
                            data["free_cashflow"],
                            currency
                        )
                    )

                    st.metric(
                        "Liquide Mittel",
                        format_money(
                            data["cash"],
                            currency
                        )
                    )

                    st.metric(
                        "Gesamtschulden",
                        format_money(
                            data["debt"],
                            currency
                        )
                    )

                st.divider()

                # -----------------------------
                # Wachstum & Profitabilität
                # -----------------------------

                st.subheader("Wachstum & Profitabilität")

                col1, col2 = st.columns(2)

                with col1:

                    if data["revenue_growth"] is not None:
                        st.metric(
                            "Umsatzwachstum",
                            f"{data['revenue_growth'] * 100:.1f} %"
                        )
                    else:
                        st.metric(
                            "Umsatzwachstum",
                            "–"
                        )

                    if data["profit_margin"] is not None:
                        st.metric(
                            "Nettomarge",
                            f"{data['profit_margin'] * 100:.1f} %"
                        )
                    else:
                        st.metric(
                            "Nettomarge",
                            "–"
                        )

                with col2:

                    if data["earnings_growth"] is not None:
                        st.metric(
                            "Gewinnwachstum",
                            f"{data['earnings_growth'] * 100:.1f} %"
                        )
                    else:
                        st.metric(
                            "Gewinnwachstum",
                            "–"
                        )

                    if data["roe"] is not None:
                        st.metric(
                            "Eigenkapitalrendite",
                            f"{data['roe'] * 100:.1f} %"
                        )
                    else:
                        st.metric(
                            "Eigenkapitalrendite",
                            "–"
                        )

                st.divider()

                # -----------------------------
                # Quartalszahlen
                # -----------------------------

                st.subheader("📅 Nächste Quartalszahlen")

                earnings_date = format_date(
                    data["earnings_timestamp"]
                )

                if earnings_date != "–":

                    st.info(
                        f"Voraussichtlicher Termin: "
                        f"**{earnings_date}**"
                    )

                else:

                    st.write(
                        "Termin derzeit nicht verfügbar."
                    )

                st.divider()

                # -----------------------------
                # Börsenplatz
                # -----------------------------

                st.subheader("Börsenplatz")

                st.write(
                    f"**Ticker:** "
                    f"{text_or_dash(data['symbol'])}"
                )

                st.write(
                    f"**Börse:** "
                    f"{text_or_dash(data['exchange_name'])}"
                )

                st.write(
                    f"**Börsen-Code:** "
                    f"{text_or_dash(data['exchange'])}"
                )

                exchange_code = str(
                    data["exchange"] or ""
                ).upper()

                symbol_upper = str(
                    data["symbol"] or ""
                ).upper()

                if exchange_code in [
                    "NMS",
                    "NGM",
                    "NCM"
                ]:

                    st.success(
                        "✓ US-Hauptbörse / Nasdaq erkannt"
                    )

                elif exchange_code == "NYQ":

                    st.success(
                        "✓ US-Hauptbörse / NYSE erkannt"
                    )

                elif symbol_upper.endswith(".DE"):

                    st.success(
                        "✓ Deutsche Börsennotierung erkannt"
                    )

                else:

                    st.info(
                        "Börsenplatz erkannt. "
                        "Die automatische Prüfung der "
                        "Hauptnotierung wird später "
                        "noch erweitert."
                    )

                st.caption(
                    "Fehlende Yahoo-Daten werden mit „–“ "
                    "angezeigt und führen nicht zu einem Fehler."
                )

        except Exception:

            st.error(
                "Die Aktie konnte nicht geladen werden."
            )

            st.caption(
                "Bitte Suchbegriff prüfen "
                "und erneut versuchen."
                             )
