import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="Aktien-Analyse V2",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Aktien-Analyse V2")
st.caption("Modul 1 – Aktiensuche")

suchbegriff = st.text_input(
    "Ticker eingeben",
    placeholder="z. B. MSFT, VOW3.DE oder ALB",
).strip()

if suchbegriff:
    ticker_symbol = suchbegriff.upper()

    with st.spinner("Aktie wird geladen..."):
        try:
            aktie = yf.Ticker(ticker_symbol)
            info = aktie.info

            name = info.get("longName") or info.get("shortName")
            kurs = info.get("currentPrice")
            waehrung = info.get("currency")
            boerse = info.get("exchange")
            sektor = info.get("sector")
            branche = info.get("industry")
            quote_type = info.get("quoteType")

            if not name:
                st.error(
                    "Aktie konnte nicht eindeutig gefunden werden. "
                    "Bitte den Ticker prüfen."
                )
            else:
                st.success("Aktie gefunden")

                st.subheader(name)
                st.write(f"**Ticker:** {ticker_symbol}")

                if quote_type:
                    st.write(f"**Typ:** {quote_type}")

                if boerse:
                    st.write(f"**Börse:** {boerse}")

                if kurs is not None:
                    if waehrung:
                        st.metric(
                            "Aktueller Kurs",
                            f"{kurs:,.2f} {waehrung}"
                        )
                    else:
                        st.metric(
                            "Aktueller Kurs",
                            f"{kurs:,.2f}"
                        )

                if sektor:
                    st.write(f"**Sektor:** {sektor}")

                if branche:
                    st.write(f"**Branche:** {branche}")

        except Exception as fehler:
            st.error(
                "Die Daten konnten momentan nicht geladen werden. "
                "Bitte später erneut versuchen."
            )
