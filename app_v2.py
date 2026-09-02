import streamlit as st
import yfinance as yf
from datetime import datetime

st.set_page_config(
    page_title="Aktien-Analyse V2",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Aktien-Analyse V2")
st.caption("Modul 1 + 2 + 3 – Suche, Datenbasis & Unternehmenstyp")


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
        return None

    try:
        date_value = datetime.fromtimestamp(timestamp)

        if date_value.date() < datetime.now().date():
            return None

        return date_value.strftime("%d.%m.%Y")

    except Exception:
        return None


# -----------------------------
# Unternehmen klassifizieren
# -----------------------------

def classify_company(name, symbol, sector, industry):

    name_text = str(name or "").lower()
    symbol_text = str(symbol or "").upper()
    sector_text = str(sector or "").lower()
    industry_text = str(industry or "").lower()

    combined = (
        name_text + " " +
        sector_text + " " +
        industry_text
    )

    # -------------------------
    # Bekannte Spezialfälle
    # -------------------------

    # Albemarle:
    # Yahoo führt ALB als Specialty Chemicals.
    # Für die Bewertung behandeln wir das Unternehmen
    # wegen der starken Lithium-/Rohstoffabhängigkeit
    # als zyklischen Rohstoffwert.

    if (
        symbol_text == "ALB"
        or "albemarle" in name_text
    ):
        return {
            "type": "Rohstoffe / Lithium / zyklisch",
            "method": "Zyklus-normalisierte Gewinne + FCF",
            "confidence_cap": "Mittel"
        }

    # -------------------------
    # Banken
    # -------------------------

    if (
        "bank" in industry_text
        or "banks" in industry_text
        or "banking" in industry_text
    ):
        return {
            "type": "Bank",
            "method": "KBV / Eigenkapital + normalisiertes KGV",
            "confidence_cap": "Mittel bis Hoch"
        }

    # -------------------------
    # Versicherungen
    # -------------------------

    if (
        "insurance" in industry_text
        or "insurer" in combined
    ):
        return {
            "type": "Versicherung",
            "method": "Core EPS + KGV + ROE / KBV",
            "confidence_cap": "Mittel bis Hoch"
        }

    # -------------------------
    # REIT / Immobilien
    # -------------------------

    if (
        "reit" in industry_text
        or "reit" in sector_text
    ):
        return {
            "type": "REIT / Immobilien",
            "method": "P/AFFO bzw. P/FFO",
            "confidence_cap": "Mittel bis Hoch"
        }

    # -------------------------
    # Autohersteller
    # -------------------------

    auto_terms = [
        "auto manufacturers",
        "automobile",
        "automotive",
        "car manufacturer"
    ]

    if any(
        term in industry_text
        for term in auto_terms
    ):
        return {
            "type": "Autohersteller / zyklisch",
            "method": "Normalisiertes Mehrjahres-EPS + KGV",
            "confidence_cap": "Mittel"
        }

    # -------------------------
    # Öl & Gas
    # -------------------------

    oil_terms = [
        "oil & gas",
        "oil and gas",
        "integrated oil",
        "energy - fossil"
    ]

    if any(
        term in combined
        for term in oil_terms
    ):
        return {
            "type": "Öl & Gas / zyklisch",
            "method": "Normalisierte Gewinne + FCF + Verschuldung",
            "confidence_cap": "Mittel"
        }

    # -------------------------
    # Bergbau / Rohstoffe
    # -------------------------

    mining_terms = [
        "gold",
        "silver",
        "copper",
        "lithium",
        "mining",
        "industrial metals",
        "other industrial metals"
    ]

    if any(
        term in industry_text
        for term in mining_terms
    ):
        return {
            "type": "Rohstoffe / Bergbau / zyklisch",
            "method": "Zyklus-normalisierte Gewinne + FCF",
            "confidence_cap": "Mittel"
        }

    # -------------------------
    # Biotechnologie
    # -------------------------

    if "biotechnology" in industry_text:
        return {
            "type": "Biotechnologie",
            "method": "Gewinnmodell oder Cash + Pipeline / rNPV",
            "confidence_cap": "Niedrig bis Mittel"
        }

    # -------------------------
    # Pharma
    # -------------------------

    pharma_terms = [
        "drug manufacturers",
        "pharmaceutical"
    ]

    if any(
        term in industry_text
        for term in pharma_terms
    ):
        return {
            "type": "Pharma",
            "method": "Normalisiertes EPS + KGV",
            "confidence_cap": "Mittel bis Hoch"
        }

    # -------------------------
    # Halbleiter
    # -------------------------

    semiconductor_terms = [
        "semiconductor",
        "semiconductors"
    ]

    if any(
        term in industry_text
        for term in semiconductor_terms
    ):
        return {
            "type": "Halbleiter / Wachstum",
            "method": "Forward EPS + qualitätsbereinigtes KGV",
            "confidence_cap": "Mittel bis Hoch"
        }

    # -------------------------
    # Software
    # -------------------------

    software_terms = [
        "software",
        "information technology services"
    ]

    if any(
        term in industry_text
        for term in software_terms
    ):
        return {
            "type": "Etablierte Software / Technologie",
            "method": "Normalisiertes EPS + qualitätsbereinigtes KGV",
            "confidence_cap": "Hoch"
        }

    # -------------------------
    # Telekommunikation
    # -------------------------

    telecom_terms = [
        "telecom",
        "telecommunication"
    ]

    if any(
        term in combined
        for term in telecom_terms
    ):
        return {
            "type": "Telekommunikation",
            "method": "Adjusted EPS + FCF + Verschuldung",
            "confidence_cap": "Mittel bis Hoch"
        }

    # -------------------------
    # Versorger
    # -------------------------

    utility_terms = [
        "utilities",
        "utility"
    ]

    if any(
        term in combined
        for term in utility_terms
    ):
        return {
            "type": "Versorger",
            "method": "KGV bzw. EV/EBITDA + Verschuldung",
            "confidence_cap": "Mittel bis Hoch"
        }

    # -------------------------
    # Defensiver Konsum
    # -------------------------

    staples_terms = [
        "consumer defensive",
        "beverages - non-alcoholic",
        "household & personal products",
        "packaged foods"
    ]

    if any(
        term in combined
        for term in staples_terms
    ):
        return {
            "type": "Defensiver Konsum",
            "method": "Normalisiertes EPS + KGV",
            "confidence_cap": "Hoch"
        }

    # -------------------------
    # Industrie
    # -------------------------

    if "industrials" in sector_text:
        return {
            "type": "Industrie",
            "method": "Normalisiertes EPS + KGV + FCF",
            "confidence_cap": "Mittel bis Hoch"
        }

    # -------------------------
    # Standard
    # -------------------------

    return {
        "type": "Standard-Unternehmen",
        "method": "Normalisiertes EPS + KGV + FCF-Kontrolle",
        "confidence_cap": "Mittel"
    }


# -----------------------------
# Aktiensuche
# -----------------------------

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
        if str(
            item.get("quoteType", "")
        ).upper() == "EQUITY"
    ]

    candidates = (
        equities
        if equities
        else quotes
    )

    query_upper = query.upper()

    for item in candidates:

        symbol = str(
            item.get("symbol", "")
        ).upper()

        if symbol == query_upper:
            return item

    return candidates[0]


# -----------------------------
# Daten laden
# -----------------------------

@st.cache_data(
    ttl=900,
    show_spinner=False
)
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

    company_type = classify_company(
        name,
        symbol,
        info.get("sector"),
        info.get("industry")
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

        "market_cap": info.get("marketCap"),
        "trailing_eps": info.get("trailingEps"),
        "forward_eps": info.get("forwardEps"),

        "revenue": info.get("totalRevenue"),
        "net_income": info.get("netIncomeToCommon"),
        "free_cashflow": info.get("freeCashflow"),

        "cash": info.get("totalCash"),
        "debt": info.get("totalDebt"),

        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),

        "profit_margin": info.get("profitMargins"),
        "roe": info.get("returnOnEquity"),

        "earnings_timestamp": earnings_timestamp,

        "company_type": company_type
    }


# -----------------------------
# Benutzeroberfläche
# -----------------------------

search_text = st.text_input(
    "Aktie suchen",
    placeholder=(
        "z. B. Microsoft, MSFT, Volkswagen, "
        "Allianz oder ALB"
    )
).strip()


if search_text:

    with st.spinner(
        "Aktie wird gesucht und Daten werden geladen..."
    ):

        try:

            data = load_stock(search_text)

            if not data:

                st.error(
                    "Aktie konnte nicht eindeutig "
                    "gefunden werden."
                )

            else:

                currency = text_or_dash(
                    data["currency"]
                )

                st.success("Aktie gefunden")

                st.header(data["name"])

                if search_text.upper() != str(
                    data["symbol"]
                ).upper():

                    st.info(
                        f"„{search_text}“ → "
                        f"{data['symbol']} "
                        f"automatisch erkannt"
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
                        f"**Währung:** {currency}"
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
                # Unternehmenstyp
                # -----------------------------

                st.subheader(
                    "🧭 Automatische "
                    "Unternehmens-Klassifizierung"
                )

                company_type = data[
                    "company_type"
                ]

                st.success(
                    f"Unternehmenstyp: "
                    f"**{company_type['type']}**"
                )

                st.write(
                    f"**Spätere Bewertungsmethode:** "
                    f"{company_type['method']}"
                )

                st.write(
                    f"**Maximale Bewertungssicherheit:** "
                    f"{company_type['confidence_cap']}"
                )

                st.caption(
                    "Die Klassifizierung bestimmt später, "
                    "welches Bewertungsmodell verwendet wird."
                )

                st.divider()

                # -----------------------------
                # Kurs
                # -----------------------------

                st.subheader("Aktueller Kurs")

                if data["price"] is not None:

                    st.metric(
                        "Kurs",
                        f"{data['price']:,.2f} "
                        f"{currency}"
                    )

                else:

                    st.warning(
                        "Aktueller Kurs nicht verfügbar."
                    )

                st.divider()

                # -----------------------------
                # Datenbasis
                # -----------------------------

                st.subheader(
                    "📋 Datenbasis für die Bewertung"
                )

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

                st.subheader(
                    "Wachstum & Profitabilität"
                )

                col1, col2 = st.columns(2)

                with col1:

                    if (
                        data["revenue_growth"]
                        is not None
                    ):
                        st.metric(
                            "Umsatzwachstum",
                            f"{data['revenue_growth'] * 100:.1f} %"
                        )
                    else:
                        st.metric(
                            "Umsatzwachstum",
                            "–"
                        )

                    if (
                        data["profit_margin"]
                        is not None
                    ):
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

                    if (
                        data["earnings_growth"]
                        is not None
                    ):
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

                st.subheader(
                    "📅 Nächste Quartalszahlen"
                )

                earnings_date = format_date(
                    data["earnings_timestamp"]
                )

                if earnings_date:

                    st.info(
                        f"Voraussichtlicher Termin: "
                        f"**{earnings_date}**"
                    )

                else:

                    st.write(
                        "Kein zukünftiger Termin verfügbar."
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
                        "Hauptnotierung wird später erweitert."
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
