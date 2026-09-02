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
# Aktiensuche
# -----------------------------

suchbegriff = st.text_input(
    "Ticker eingeben",
    placeholder="z. B. MSFT, VOW3.DE, ALB oder BP.L"
).strip()

if suchbegriff:

    ticker_symbol = suchbegriff.upper()

    with st.spinner("Aktie wird geladen..."):

        try:
            aktie = yf.Ticker(ticker_symbol)
            info = aktie.info

            name = info.get("longName") or info.get("shortName")
            kurs = info.get("currentPrice")
            waehrung = info.get("currency", "–")
            boerse = info.get("exchange", "–")
            boersenname = info.get("fullExchangeName", "–")
            sektor = info.get("sector", "–")
            branche = info.get("industry", "–")
            typ = info.get("quoteType", "–")

            if not name:
                st.error("Aktie konnte nicht eindeutig gefunden werden.")

            else:
                st.success("Aktie gefunden")

                st.header(name)

                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**Ticker:** {ticker_symbol}")
                    st.write(f"**Typ:** {typ}")
                    st.write(f"**Börse:** {boersenname}")

                with col2:
                    st.write(f"**Währung:** {waehrung}")
                    st.write(f"**Sektor:** {sektor}")
                    st.write(f"**Branche:** {branche}")

                st.divider()

                st.subheader("Aktueller Kurs")

                if kurs is not None:
                    st.metric(
                        label="Kurs",
                        value=f"{kurs:,.2f} {waehrung}"
                    )
                else:
                    st.warning("Aktueller Kurs nicht verfügbar.")

                st.divider()

                st.subheader("Börsenplatz")

                st.write(f"**Ticker:** {ticker_symbol}")
                st.write(f"**Börse:** {boersenname}")
                st.write(f"**Börsen-Code:** {boerse}")

                if boerse in ["NMS", "NGM", "NCM"]:
                    st.success("✓ US-Hauptbörse / Nasdaq erkannt")

                elif boerse in ["NYQ"]:
                    st.success("✓ US-Hauptbörse / NYSE erkannt")

                elif ticker_symbol.endswith(".DE"):
                    st.info(
                        "Deutscher Börsenplatz erkannt. "
                        "Bei internationalen Unternehmen prüfen wir später "
                        "automatisch, ob eine Hauptnotierung mit besseren "
                        "Fundamentaldaten verfügbar ist."
                    )

                st.caption(
                    "V2 wird später automatisch die Hauptnotierung bevorzugen "
                    "und alternative Börsenplätze kennzeichnen."
                )

        except Exception as e:
            st.error("Die Aktie konnte nicht geladen werden.")
            st.caption("Bitte Ticker prüfen und erneut versuchen.")
