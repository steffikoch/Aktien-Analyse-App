import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="Aktien-Analyse V2",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Aktien-Analyse V2")
st.caption("Modul 1 – Aktiensuche")


# -----------------------------
# Hilfsfunktionen
# -----------------------------

def text_or_dash(value):
    if value is None or value == "":
        return "–"
    return str(value)


def find_stock(search_text):
    """
    Sucht nach Firmenname oder Ticker.
    Exakte Ticker-Treffer werden bevorzugt.
    """

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

    # Nur Aktien bevorzugen
    equities = [
        item for item in quotes
        if str(item.get("quoteType", "")).upper() == "EQUITY"
    ]

    candidates = equities if equities else quotes

    query_upper = query.upper()

    # Exakten Ticker zuerst nehmen
    for item in candidates:
        symbol = str(item.get("symbol", "")).upper()

        if symbol == query_upper:
            return item

    # Sonst den relevantesten Suchtreffer nehmen
    return candidates[0]


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
    }


# -----------------------------
# Aktiensuche
# -----------------------------

search_text = st.text_input(
    "Aktie suchen",
    placeholder="z. B. Microsoft, MSFT, Volkswagen, Allianz oder ALB"
).strip()


if search_text:

    with st.spinner("Aktie wird gesucht..."):

        try:

            data = load_stock(search_text)

            if not data:

                st.error(
                    "Aktie konnte nicht eindeutig gefunden werden."
                )

            else:

                st.success("Aktie gefunden")

                st.header(data["name"])

                # Zeigt an, welchen Ticker die Namenssuche gefunden hat
                if search_text.upper() != str(data["symbol"]).upper():

                    st.info(
                        f"„{search_text}“ → "
                        f"{data['symbol']} automatisch erkannt"
                    )

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
                        f"{text_or_dash(data['currency'])}"
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
                # Aktueller Kurs
                # -----------------------------

                st.subheader("Aktueller Kurs")

                if data["price"] is not None:

                    st.metric(
                        label="Kurs",
                        value=(
                            f"{data['price']:,.2f} "
                            f"{text_or_dash(data['currency'])}"
                        )
                    )

                else:

                    st.warning(
                        "Aktueller Kurs nicht verfügbar."
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
                        "Hauptnotierung bauen wir in V2 "
                        "noch weiter aus."
                    )

                st.caption(
                    "Die Suche akzeptiert jetzt "
                    "Firmenname oder Ticker."
                )

        except Exception:

            st.error(
                "Die Aktie konnte nicht geladen werden."
            )

            st.caption(
                "Bitte Suchbegriff prüfen "
                "und erneut versuchen."
            )
