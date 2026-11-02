"""Separate, read-only Eulerpool API screener diagnostic for Aktien-Analyse V2.

The suggested field names are NOT confirmed equivalent to the website preset.
This tool intentionally does not write company data or change the valuation engine.
"""
import json
import os
from datetime import datetime, timezone

import requests
import streamlit as st

API_ROOT = "https://api.eulerpool.com/api/1"


def get_key():
    value = str(os.getenv("EULERPOOL_API_KEY") or "").strip()
    if value:
        return value
    try:
        return str(st.secrets.get("EULERPOOL_API_KEY", "") or "").strip()
    except Exception:
        return ""


def call(method, path, key, body=None):
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        response = requests.request(method, API_ROOT + path, headers=headers, json=body, timeout=20)
        try:
            data = response.json()
        except ValueError:
            data = None
        return response.status_code, data
    except requests.exceptions.RequestException:
        return None, None


def rows_from(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for field in ("results", "data", "items", "rows", "stocks"):
            candidate = payload.get(field)
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, dict):
                nested = rows_from(candidate)
                if nested:
                    return nested
    return []


def diagnostic_summary(status, payload):
    rows = rows_from(payload)
    total = None
    if isinstance(payload, dict):
        for field in ("total", "totalCount", "count", "totalElements"):
            value = payload.get(field)
            if isinstance(value, (int, float)):
                total = int(value)
                break
    names = []
    for record in rows[:5]:
        if isinstance(record, dict):
            names.append({field: record.get(field) for field in
                          ("name", "ticker", "isin", "country") if field in record})
    return {"http_status": status, "payload_type": type(payload).__name__,
            "response_keys": list(payload.keys())[:25] if isinstance(payload, dict) else [],
            "rows_on_page": len(rows), "reported_total": total, "sample": names}


def screen(key, filters):
    payload = {"filters": filters, "page": 0, "size": 10}
    status, data = call("POST", "/screener/screen", key, payload)
    return diagnostic_summary(status, data)


st.title("Eulerpool – Screener-Test")
st.caption("Getrennte Diagnose für die Aktien-Analyse V2. Keine Änderung an der Bewertungslogik.")
st.write("**Unser Ziel:** den Eulerpool-Schnellfilter 'Idealer Einstieg' automatisch abrufen.")
st.write("Webseiten-Kriterien: **AAQS ≥ 8**, **Fair Value Gewinn ≥ 15 %**, **KGV 1 bis 25**.")

key = get_key()
if not key:
    st.error("Eulerpool-Key fehlt in Streamlit-Secrets / EULERPOOL_API_KEY. "
             "Bitte niemals API-Schlüssel im Chat oder auf GitHub veröffentlichen.")
    st.stop()
st.success("Bestehender Eulerpool-Zugang gefunden. Der Schlüssel wird nicht angezeigt.")

with st.expander("Technischer Test: mögliche API-Feldnamen (noch nicht bestätigt)"):
    score_field = st.text_input("AAQS", "aaqs")
    fair_field = st.text_input("Fair Value Gewinn", "fairValueUpside")
    pe_field = st.text_input("KGV", "peRatio")

names = [score_field.strip(), fair_field.strip(), pe_field.strip()]
if len(set(names)) != 3 or any(not name or not name.replace("_", "").isalnum() for name in names):
    st.error("Die Feldnamen müssen verschieden sein und nur Buchstaben, Ziffern und _ enthalten.")
    st.stop()

if st.button("Eulerpool-Verbindung testen", type="primary"):
    with st.spinner("Prüfe Eulerpool-API ..."):
        metadata_status, metadata = call("GET", "/screener/metadata", key)
        control = screen(key, [{"id": "marketCap", "value": 1000000000, "equality": ">="}])
        candidate = screen(key, [
            {"id": names[0], "value": 8, "equality": ">="},
            {"id": names[1], "value": 15, "equality": ">="},
            {"id": names[2], "value": 1, "equality": ">="},
            {"id": names[2], "value": 25, "equality": "<="},
        ])
        impossible = screen(key, [{"id": names[0], "value": 9999, "equality": ">="}])
        result = {
            "test_date_utc": datetime.now(timezone.utc).isoformat(),
            "target_web_filter": "AAQS >= 8; Fair Value Gewinn >= 15%; KGV 1..25",
            "candidate_api_filter_fields_unverified": names,
            "metadata": diagnostic_summary(metadata_status, metadata),
            "known_market_cap_control": control,
            "three_filters_test": candidate,
            "impossible_aaqs_control": impossible,
        }
    st.subheader("Diagnose")
    st.json(result, expanded=False)
    st.warning("Wichtig: Ein HTTP-Status 200 beweist NICHT, dass der Webseiten-Schnellfilter "
               "identisch angewandt wurde. Das müssen wir anhand der Feldnamen und "
               "eines Vergleichs mit echten Eulerpool-Treffern prüfen.")
    st.download_button(
        "Diagnose-Datei herunterladen (ohne API-Schlüssel)",
        data=json.dumps(result, ensure_ascii=False, indent=2),
        file_name="eulerpool_screener_diagnose.json", mime="application/json",
    )
    st.caption("Diese JSON-Datei kannst du mir hier schicken. Dein API-Schlüssel steht nicht darin.")
