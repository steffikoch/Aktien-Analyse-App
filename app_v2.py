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
    "Unternehmen oder Ticker suchen",
    placeholder="z. B. Microsoft oder MSFT",
)

if suchbegriff:
    st.info(f"Suche nach: {suchbegriff}")
