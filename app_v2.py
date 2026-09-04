import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

st.set_page_config(
    page_title="Aktien-Analyse V2",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Aktien-Analyse V2")
st.caption(
    "Modul 1 + 2 + 3 + 4 + 5 – Suche, Datenbasis, "
    "Unternehmenstyp, EPS-Normalisierung & Multiple Score – Schritt 4"
)


# =========================================================
# Hilfsfunktionen
# =========================================================

def text_or_dash(value):
    if value is None or value == "":
        return "–"
    return str(value)


def format_number(value):
    if value is None:
        return "–"

    try:
        value = float(value)

        if pd.isna(value):
            return "–"

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
    formatted = format_number(value)

    if formatted == "–":
        return "–"

    return f"{formatted} {currency}"


def format_eps(value, currency):
    if value is None:
        return "–"

    try:
        value = float(value)

        if pd.isna(value):
            return "–"

        return f"{value:,.2f} {currency}"

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


def safe_float(value):
    try:
        value = float(value)

        if pd.isna(value):
            return None

        return value

    except Exception:
        return None


# =========================================================
# Modul 5 – Multiple Score: Wachstum
# =========================================================

def growth_points(value):
    value = safe_float(value)

    if value is None:
        return None

    if value >= 0.20:
        return 15

    if value >= 0.15:
        return 13

    if value >= 0.10:
        return 11

    if value >= 0.05:
        return 8

    if value >= 0.00:
        return 5

    if value >= -0.05:
        return 2

    return 0


def calculate_growth_score(
    revenue_growth,
    earnings_growth
):

    revenue_points = growth_points(
        revenue_growth
    )

    earnings_points = growth_points(
        earnings_growth
    )

    available = [
        points
        for points in [
            revenue_points,
            earnings_points
        ]
        if points is not None
    ]

    if not available:

        return {
            "score": None,
            "revenue_points": None,
            "earnings_points": None,
            "confidence": "Niedrig",
            "note": (
                "Keine ausreichenden Wachstumsdaten verfügbar."
            )
        }

    if len(available) == 2:

        score = (
            revenue_points +
            earnings_points
        )

        confidence = "Hoch"

        note = (
            "Umsatz- und Gewinnwachstum vollständig berücksichtigt."
        )

    else:

        score = available[0]
        confidence = "Mittel"

        note = (
            "Nur eine Wachstumskennzahl verfügbar. "
            "Es werden nur die tatsächlich belegten Punkte "
            "vergeben; fehlende Daten werden nicht hochgerechnet."
        )

    return {
        "score": score,
        "revenue_points": revenue_points,
        "earnings_points": earnings_points,
        "confidence": confidence,
        "note": note
    }


# =========================================================
# Modul 5 – Multiple Score: Profitabilität
# =========================================================

def profitability_margin_points(
    company_type,
    profit_margin
):
    margin = safe_float(profit_margin)

    if margin is None:
        return None

    type_name = str(
        company_type.get("type", "")
    ).lower()

    if (
        "bank" in type_name
        or "versicherung" in type_name
        or "reit" in type_name
        or "immobilien" in type_name
        or "biotechnologie" in type_name
    ):
        return None

    if "software" in type_name:
        thresholds = [
            (0.30, 15),
            (0.20, 13),
            (0.12, 10),
            (0.07, 7),
            (0.00, 4)
        ]

    elif "halbleiter" in type_name:
        thresholds = [
            (0.30, 15),
            (0.22, 13),
            (0.15, 10),
            (0.08, 7),
            (0.00, 4)
        ]

    elif (
        "defensiver konsum" in type_name
        or "pharma" in type_name
    ):
        thresholds = [
            (0.20, 15),
            (0.15, 13),
            (0.10, 10),
            (0.06, 7),
            (0.00, 4)
        ]

    elif "zyklisch" in type_name:
        thresholds = [
            (0.12, 15),
            (0.08, 13),
            (0.05, 10),
            (0.03, 7),
            (0.00, 4)
        ]

    else:
        thresholds = [
            (0.15, 15),
            (0.10, 13),
            (0.07, 10),
            (0.04, 7),
            (0.00, 4)
        ]

    for threshold, points in thresholds:
        if margin >= threshold:
            return points

    return 0


def profitability_roe_points(
    company_type,
    roe
):
    roe_value = safe_float(roe)

    if roe_value is None:
        return None

    type_name = str(
        company_type.get("type", "")
    ).lower()

    if (
        "bank" in type_name
        or "versicherung" in type_name
        or "reit" in type_name
        or "immobilien" in type_name
        or "biotechnologie" in type_name
    ):
        return None

    if "zyklisch" in type_name:
        thresholds = [
            (0.25, 15),
            (0.18, 13),
            (0.12, 10),
            (0.08, 7),
            (0.00, 4)
        ]
    else:
        thresholds = [
            (0.30, 15),
            (0.22, 13),
            (0.15, 10),
            (0.10, 7),
            (0.00, 4)
        ]

    for threshold, points in thresholds:
        if roe_value >= threshold:
            return points

    return 0


def calculate_profitability_score(
    company_type,
    profit_margin,
    roe,
    earnings_growth
):
    margin_points = profitability_margin_points(
        company_type,
        profit_margin
    )

    roe_points = profitability_roe_points(
        company_type,
        roe
    )

    type_name = str(
        company_type.get("type", "")
    ).lower()

    special_model = (
        "bank" in type_name
        or "versicherung" in type_name
        or "reit" in type_name
        or "immobilien" in type_name
        or "biotechnologie" in type_name
    )

    if special_model:
        return {
            "score": None,
            "raw_score": None,
            "margin_points": None,
            "roe_points": None,
            "confidence": "Sondermodell",
            "brake_active": False,
            "brake_text": (
                "Für diesen Unternehmenstyp wird später "
                "eine eigene Profitabilitätslogik verwendet."
            )
        }

    available = [
        points
        for points in [
            margin_points,
            roe_points
        ]
        if points is not None
    ]

    if not available:
        return {
            "score": None,
            "raw_score": None,
            "margin_points": None,
            "roe_points": None,
            "confidence": "Niedrig",
            "brake_active": False,
            "brake_text": (
                "Keine ausreichenden Profitabilitätsdaten verfügbar."
            )
        }

    if len(available) == 2:
        raw_score = (
            margin_points +
            roe_points
        )
        confidence = "Hoch"
    else:
        raw_score = available[0]
        confidence = "Mittel"

    score = raw_score
    brake_active = False
    brake_text = (
        "Keine Verschlechterungsbremse aktiv."
    )

    growth = safe_float(
        earnings_growth
    )

    if growth is None:
        if confidence == "Hoch":
            confidence = "Mittel"

        brake_text = (
            "Gewinnentwicklung nicht verfügbar; "
            "Verschlechterungsbremse konnte nicht geprüft werden."
        )

    elif growth <= -0.30:
        limit = 18
        score = min(
            score,
            limit
        )
        brake_active = (
            score < raw_score
        )

        if brake_active:
            brake_text = (
                f"Starker Gewinnrückgang von "
                f"{growth * 100:.1f} % erkannt. "
                f"Die Verschlechterungsbremse begrenzt "
                f"den Profitabilitäts-Score auf "
                f"maximal {limit}/30 Punkte."
            )
        else:
            brake_text = (
                f"Starker Gewinnrückgang von "
                f"{growth * 100:.1f} % erkannt. "
                f"Der aktuelle Profitabilitäts-Score "
                f"von {raw_score}/30 liegt bereits "
                f"unter der Obergrenze von "
                f"{limit}/30 – keine weitere Kürzung."
            )

    elif growth <= -0.15:
        limit = 22
        score = min(
            score,
            limit
        )
        brake_active = (
            score < raw_score
        )

        if brake_active:
            brake_text = (
                f"Deutlicher Gewinnrückgang von "
                f"{growth * 100:.1f} % erkannt. "
                f"Die Verschlechterungsbremse begrenzt "
                f"den Profitabilitäts-Score auf "
                f"maximal {limit}/30 Punkte."
            )
        else:
            brake_text = (
                f"Deutlicher Gewinnrückgang von "
                f"{growth * 100:.1f} % erkannt. "
                f"Der aktuelle Profitabilitäts-Score "
                f"von {raw_score}/30 liegt bereits "
                f"unter der Obergrenze von "
                f"{limit}/30 – keine weitere Kürzung."
            )

    elif growth <= -0.05:
        limit = 26
        score = min(
            score,
            limit
        )
        brake_active = (
            score < raw_score
        )

        if brake_active:
            brake_text = (
                f"Gewinnrückgang von "
                f"{growth * 100:.1f} % erkannt. "
                f"Die Verschlechterungsbremse begrenzt "
                f"den Profitabilitäts-Score auf "
                f"maximal {limit}/30 Punkte."
            )
        else:
            brake_text = (
                f"Gewinnrückgang von "
                f"{growth * 100:.1f} % erkannt. "
                f"Der aktuelle Profitabilitäts-Score "
                f"von {raw_score}/30 liegt bereits "
                f"unter der Obergrenze von "
                f"{limit}/30 – keine weitere Kürzung."
            )

    return {
        "score": score,
        "raw_score": raw_score,
        "margin_points": margin_points,
        "roe_points": roe_points,
        "confidence": confidence,
        "brake_active": brake_active,
        "brake_text": brake_text
    }


# =========================================================
# Modul 5 – Multiple Score: Free Cashflow
# =========================================================

def is_special_fcf_model(company_type):
    type_name = str(
        company_type.get("type", "")
    ).lower()

    special_terms = [
        "bank",
        "versicherung",
        "reit",
        "immobilien",
        "autohersteller"
    ]

    return any(
        term in type_name
        for term in special_terms
    )


def fcf_margin_points(fcf_margin):
    margin = safe_float(fcf_margin)

    if margin is None:
        return None

    if margin >= 0.20:
        return 25
    if margin >= 0.15:
        return 22
    if margin >= 0.10:
        return 19
    if margin >= 0.07:
        return 16
    if margin >= 0.04:
        return 13
    if margin >= 0.00:
        return 9
    if margin >= -0.05:
        return 4

    return 0


def calculate_fcf_score(
    company_type,
    revenue,
    current_fcf,
    historical_fcf
):
    if is_special_fcf_model(company_type):
        return {
            "score": None,
            "raw_score": None,
            "fcf_margin": None,
            "confidence": "Sondermodell",
            "status": "special",
            "note": (
                "Für diesen Unternehmenstyp wird der normale "
                "Yahoo-Free-Cashflow bewusst nicht bewertet. "
                "Hier ist später eine eigene Cashflow-Logik nötig."
            )
        }

    revenue_value = safe_float(revenue)
    fcf_value = safe_float(current_fcf)

    if revenue_value is None or revenue_value <= 0 or fcf_value is None:
        return {
            "score": None,
            "raw_score": None,
            "fcf_margin": None,
            "confidence": "Niedrig",
            "status": "missing",
            "note": "Keine ausreichenden aktuellen Daten für den FCF-Score verfügbar."
        }

    fcf_margin = fcf_value / revenue_value
    raw_score = fcf_margin_points(fcf_margin)
    score = raw_score

    history = []
    if historical_fcf:
        source_values = (
            list(historical_fcf.values())
            if isinstance(historical_fcf, dict)
            else list(historical_fcf)
        )

        for item in source_values:
            if isinstance(item, dict):
                value = item.get("value")
            else:
                value = item

            number = safe_float(value)

            if number is not None:
                history.append(number)

    if len(history) >= 3:
        confidence = "Hoch"
    elif len(history) >= 1:
        confidence = "Mittel"
    else:
        confidence = "Niedrig"

    status = "normal"
    note = (
        "Aktuelle FCF-Marge bestimmt die Ausgangspunkte. "
        "Die Mehrjahreswerte dienen als Stabilitäts- und Trendkontrolle."
    )

    type_name = str(company_type.get("type", "")).lower()
    is_cyclical = (
        "zyklisch" in type_name
        or "rohstoffe" in type_name
        or "lithium" in type_name
        or "öl" in type_name
        or "gas" in type_name
        or "bergbau" in type_name
    )

    if len(history) >= 2:
        positive_years = sum(1 for value in history if value > 0)
        negative_years = sum(1 for value in history if value < 0)

        if is_cyclical and positive_years >= 1 and negative_years >= 1:
            cycle_limit = 19
            score = min(score, cycle_limit)
            status = "cyclical"
            if score < raw_score:
                note = (
                    "⚠️ Zyklischer FCF: Die historischen Free-Cashflows wechseln "
                    "zwischen positiv und negativ. Die aktuelle Stärke wird daher "
                    f"auf maximal {cycle_limit}/25 Punkte begrenzt."
                )
            else:
                note = (
                    "⚠️ Zyklischer FCF: Die historischen Free-Cashflows wechseln "
                    "zwischen positiv und negativ. Der aktuelle Score liegt bereits "
                    f"unter der Obergrenze von {cycle_limit}/25."
                )
        elif fcf_value < 0 and positive_years >= 2:
            status = "deterioration"
            note = (
                "⚠️ Free Cashflow aktuell negativ, obwohl mehrere historische Jahre "
                "positiv waren. Die guten Vorjahre erhöhen den aktuellen FCF-Score nicht."
            )
        elif fcf_value > 0 and negative_years >= 2:
            status = "recovery"
            note = (
                "↗️ FCF-Erholung erkennbar: Der aktuelle Free Cashflow ist positiv, "
                "nachdem mehrere historische Jahre negativ waren. "
                "Dafür werden keine Zusatzpunkte vergeben."
            )

    return {
        "score": score,
        "raw_score": raw_score,
        "fcf_margin": fcf_margin,
        "confidence": confidence,
        "status": status,
        "note": note
    }


# =========================================================
# Modul 5 – Multiple Score: Bilanz / Verschuldung
# =========================================================

def is_special_balance_model(company_type):
    type_name = str(
        company_type.get("type", "")
    ).lower()

    special_terms = [
        "bank",
        "versicherung",
        "reit",
        "immobilien",
        "autohersteller"
    ]

    return any(
        term in type_name
        for term in special_terms
    )


def balance_debt_points(net_debt_to_fcf):
    ratio = safe_float(net_debt_to_fcf)

    if ratio is None:
        return None

    if ratio < 1.0:
        return 14
    if ratio < 1.5:
        return 12
    if ratio < 2.5:
        return 9
    if ratio < 3.5:
        return 6
    if ratio < 4.5:
        return 3

    return 0


def calculate_balance_score(
    company_type,
    cash,
    debt,
    current_fcf,
    historical_fcf
):
    if is_special_balance_model(company_type):
        return {
            "score": None,
            "net_debt": None,
            "net_debt_to_fcf": None,
            "confidence": "Sondermodell",
            "status": "special",
            "note": (
                "Für diesen Unternehmenstyp wird die normale "
                "Netto-Schulden/FCF-Logik bewusst nicht verwendet. "
                "Hier ist später ein eigenes Bilanzmodell nötig."
            )
        }

    cash_value = safe_float(cash)
    debt_value = safe_float(debt)
    fcf_value = safe_float(current_fcf)

    if cash_value is None or debt_value is None:
        return {
            "score": None,
            "net_debt": None,
            "net_debt_to_fcf": None,
            "confidence": "Niedrig",
            "status": "missing",
            "note": (
                "Liquide Mittel oder Gesamtschulden fehlen. "
                "Es werden keine Bilanzpunkte geschätzt."
            )
        }

    net_debt = debt_value - cash_value

    if net_debt <= 0:
        return {
            "score": 15,
            "net_debt": net_debt,
            "net_debt_to_fcf": 0.0,
            "confidence": "Hoch",
            "status": "net_cash",
            "note": (
                "Netto-Cash: Die liquiden Mittel decken die "
                "Gesamtschulden vollständig."
            )
        }

    if fcf_value is None or fcf_value <= 0:
        return {
            "score": None,
            "net_debt": net_debt,
            "net_debt_to_fcf": None,
            "confidence": "Niedrig",
            "status": "fcf_unusable",
            "note": (
                "Nettoschulden sind vorhanden, aber der aktuelle "
                "Free Cashflow ist nicht positiv bzw. nicht verfügbar. "
                "Eine Netto-Schulden/FCF-Kennzahl wäre nicht belastbar."
            )
        }

    ratio = net_debt / fcf_value
    score = balance_debt_points(ratio)

    history = []
    if historical_fcf:
        source_values = (
            list(historical_fcf.values())
            if isinstance(historical_fcf, dict)
            else list(historical_fcf)
        )

        for item in source_values:
            if isinstance(item, dict):
                value = item.get("value")
            else:
                value = item

            number = safe_float(value)
            if number is not None:
                history.append(number)

    if len(history) >= 3:
        confidence = "Hoch"
    elif len(history) >= 1:
        confidence = "Mittel"
    else:
        confidence = "Niedrig"

    type_name = str(
        company_type.get("type", "")
    ).lower()

    is_cyclical = (
        "zyklisch" in type_name
        or "rohstoffe" in type_name
        or "lithium" in type_name
        or "öl" in type_name
        or "gas" in type_name
        or "bergbau" in type_name
    )

    positive_years = sum(
        1 for value in history if value > 0
    )
    negative_years = sum(
        1 for value in history if value < 0
    )

    status = "normal"
    note = (
        "Bilanzpunkte basieren auf Nettoschulden im Verhältnis "
        "zum aktuellen positiven Free Cashflow."
    )

    if (
        is_cyclical
        and positive_years >= 1
        and negative_years >= 1
    ):
        confidence = "Mittel"
        status = "cyclical"
        note = (
            "⚠️ Zyklische Cashflows: Die aktuelle "
            "Netto-Schulden/FCF-Kennzahl ist günstig, "
            "aber historisch nicht durchgehend stabil. "
            "Die Bilanzpunkte werden nicht erhöht; "
            "die Datensicherheit wird auf Mittel begrenzt."
        )

    return {
        "score": score,
        "net_debt": net_debt,
        "net_debt_to_fcf": ratio,
        "confidence": confidence,
        "status": status,
        "note": note
    }


# =========================================================
# Unternehmen klassifizieren
# =========================================================

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

    # -----------------------------------------------------
    # Spezifische Untertypen zuerst
    # -----------------------------------------------------

    # Defense / Rheinmetall
    defense_terms = [
        "aerospace & defense",
        "aerospace and defense",
        "defense",
        "defence"
    ]

    if (
        symbol_text in ["RHM.DE", "RNMBY", "RNMBF"]
        or "rheinmetall" in name_text
        or any(term in industry_text for term in defense_terms)
    ):
        return {
            "type": "Defense / stark wachsend",
            "method": (
                "Forward EPS + KGV + "
                "Auftrags-/Visibilitätskontrolle"
            ),
            "confidence_cap": "Mittel bis Hoch"
        }

    # ASML / Halbleiterausrüstung / Lithografie
    if (
        symbol_text in ["ASML", "ASML.AS"]
        or "asml" in name_text
        or "semiconductor equipment" in industry_text
    ):
        return {
            "type": "Halbleiterausrüstung / Lithografie",
            "method": (
                "Forward EPS + KGV + "
                "Auftrags-/Visibilitätskontrolle"
            ),
            "confidence_cap": "Mittel bis Hoch"
        }

    # Nvidia / Fabless / AI
    if (
        symbol_text == "NVDA"
        or "nvidia" in name_text
    ):
        return {
            "type": "Halbleiter / Fabless / AI-Wachstum",
            "method": (
                "Forward EPS + KGV + "
                "Wachstumsdauer-/Margenkontrolle"
            ),
            "confidence_cap": "Mittel bis Hoch"
        }

    # TSMC / Foundry
    if (
        symbol_text in ["TSM", "2330.TW"]
        or "taiwan semiconductor" in name_text
        or "semiconductor foundry" in industry_text
        or "foundries" in industry_text
    ):
        return {
            "type": "Halbleiter / Foundry",
            "method": (
                "Forward/normalisiertes EPS + KGV + "
                "CapEx-/geopolitische Risikokontrolle"
            ),
            "confidence_cap": "Mittel bis Hoch"
        }

    # Albemarle
    if (
        symbol_text == "ALB"
        or "albemarle" in name_text
    ):
        return {
            "type": "Rohstoffe / Lithium / zyklisch",
            "method": "Zyklus-normalisierte Gewinne + FCF",
            "confidence_cap": "Mittel"
        }

    # Banken
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

    # Versicherungen
    if (
        "insurance" in industry_text
        or "insurer" in combined
    ):
        return {
            "type": "Versicherung",
            "method": "Core EPS + KGV + ROE / KBV",
            "confidence_cap": "Mittel bis Hoch"
        }

    # REIT
    if (
        "reit" in industry_text
        or "reit" in sector_text
    ):
        return {
            "type": "REIT / Immobilien",
            "method": "P/AFFO bzw. P/FFO",
            "confidence_cap": "Mittel bis Hoch"
        }

    # Autohersteller
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

    # Öl & Gas
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

    # Bergbau / Rohstoffe
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

    # Biotechnologie
    if "biotechnology" in industry_text:
        return {
            "type": "Biotechnologie",
            "method": "Gewinnmodell oder Cash + Pipeline / rNPV",
            "confidence_cap": "Niedrig bis Mittel"
        }

    # Pharma
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

    # Übrige Halbleiter
    semiconductor_terms = [
        "semiconductor",
        "semiconductors"
    ]

    if any(
        term in industry_text
        for term in semiconductor_terms
    ):
        return {
            "type": "Halbleiter / Untertyp noch nicht eindeutig",
            "method": (
                "Untertyp bestimmen, bevor ein "
                "Bewertungs-Korridor verwendet wird"
            ),
            "confidence_cap": "Niedrig"
        }

    # Software
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

    # Telekom
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

    # Versorger
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

    # Defensiver Konsum
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

    # Industrie
    if "industrials" in sector_text:
        return {
            "type": "Industrie / Untertyp noch nicht eindeutig",
            "method": (
                "Untertyp bestimmen, bevor ein "
                "Bewertungs-Korridor verwendet wird"
            ),
            "confidence_cap": "Niedrig"
        }

    # Standard
    return {
        "type": "Standard-Unternehmen",
        "method": "Normalisiertes EPS + KGV + FCF-Kontrolle",
        "confidence_cap": "Mittel"
    }


# =========================================================
# Aktiensuche
# =========================================================

def find_stock(search_text):

    query = search_text.strip()

    if not query:
        return None

    query_upper = query.upper()

    # Eindeutiger TSMC-Fall:
    # "TSMC" bedeutet Heimatnotierung Taiwan.
    # Direkt eingegebene Ticker wie "TSM" oder "2330.TW"
    # werden weiterhin unverändert respektiert.
    if query_upper == "TSMC":
        return {
            "symbol": "2330.TW",
            "quoteType": "EQUITY",
            "longname": (
                "Taiwan Semiconductor Manufacturing "
                "Company Limited"
            ),
            "exchange": "TAI"
        }

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

    candidates = equities if equities else quotes
    query_upper = query.upper()

    for item in candidates:

        symbol = str(
            item.get("symbol", "")
        ).upper()

        if symbol == query_upper:
            return item

    # Bekannte Unternehmen mit klarer Heimat-/Hauptnotierung
    preferred_primary_symbols = {
        "TSMC": "2330.TW",
        "TAIWAN SEMICONDUCTOR": "2330.TW",
        "TAIWAN SEMICONDUCTOR MANUFACTURING": "2330.TW",
        "TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY": "2330.TW",
    }

    normalized_query = " ".join(query_upper.split())

    for key, preferred_symbol in preferred_primary_symbols.items():
        if key in normalized_query:
            for item in candidates:
                symbol = str(item.get("symbol", "")).upper()
                if symbol == preferred_symbol:
                    return item

            return {
                "symbol": preferred_symbol,
                "quoteType": "EQUITY",
                "longname": "Taiwan Semiconductor Manufacturing Company Limited",
                "exchange": "TAI"
            }

    # Allgemeine Priorisierung:
    # Heimat-/größere Primärmärkte vor Nebenbörsen/Depositary Receipts.
    preferred_exchange_order = {
        "NMS": 100,
        "NGM": 95,
        "NCM": 90,
        "NYQ": 100,
        "ASE": 85,
        "GER": 90,
        "FRA": 85,
        "LSE": 90,
        "AMS": 90,
        "PAR": 90,
        "MIL": 90,
        "STO": 90,
        "CPH": 90,
        "OSL": 90,
        "HEL": 90,
        "SWX": 90,
        "TAI": 100,
        "HKG": 95,
        "JPX": 95,
        "TOR": 95,
        "ASX": 95,
        "SAO": 40
    }

    def candidate_score(item):
        symbol = str(item.get("symbol", "")).upper()
        exchange = str(item.get("exchange", "")).upper()
        longname = str(
            item.get("longname")
            or item.get("shortname")
            or ""
        ).upper()

        score = preferred_exchange_order.get(exchange, 50)

        # Namensnähe
        query_words = [
            word for word in normalized_query.split()
            if len(word) >= 3
        ]
        if query_words:
            matches = sum(
                1 for word in query_words
                if word in longname
            )
            score += matches * 10

        # Nebenbörsen-Symbole leicht abwerten
        secondary_suffixes = [
            ".F", ".BE", ".MU", ".DU", ".HM", ".HA", ".SG",
            ".VI", ".MX", ".SA"
        ]
        if any(symbol.endswith(suffix) for suffix in secondary_suffixes):
            score -= 25

        return score

    return max(
        candidates,
        key=candidate_score
    )


# =========================================================
# Historische Daten
# =========================================================

def get_row_values(statement, possible_names):

    if statement is None:
        return []

    if statement.empty:
        return []

    for row_name in possible_names:

        if row_name in statement.index:

            row = statement.loc[row_name]

            values = []

            for date, value in row.items():

                number = safe_float(value)

                if number is not None:

                    values.append({
                        "date": date,
                        "value": number
                    })

            values.sort(
                key=lambda item: item["date"],
                reverse=True
            )

            return values

    return []


def build_historical_data(ticker):

    try:
        income = ticker.income_stmt
    except Exception:
        income = pd.DataFrame()

    try:
        cashflow = ticker.cashflow
    except Exception:
        cashflow = pd.DataFrame()

    net_income_values = get_row_values(
        income,
        [
            "Net Income",
            "Net Income Common Stockholders",
            "Net Income Continuous Operations"
        ]
    )

    diluted_eps_values = get_row_values(
        income,
        [
            "Diluted EPS",
            "Basic EPS"
        ]
    )

    free_cashflow_values = get_row_values(
        cashflow,
        [
            "Free Cash Flow"
        ]
    )

    operating_cashflow_values = get_row_values(
        cashflow,
        [
            "Operating Cash Flow",
            "Total Cash From Operating Activities"
        ]
    )

    capex_values = get_row_values(
        cashflow,
        [
            "Capital Expenditure",
            "Capital Expenditures"
        ]
    )

    if (
        not free_cashflow_values
        and operating_cashflow_values
        and capex_values
    ):

        ocf_by_year = {
            item["date"]: item["value"]
            for item in operating_cashflow_values
        }

        capex_by_year = {
            item["date"]: item["value"]
            for item in capex_values
        }

        calculated_fcf = []

        for date, ocf in ocf_by_year.items():

            if date in capex_by_year:

                calculated_fcf.append({
                    "date": date,
                    "value": (
                        ocf +
                        capex_by_year[date]
                    )
                })

        calculated_fcf.sort(
            key=lambda item: item["date"],
            reverse=True
        )

        free_cashflow_values = calculated_fcf

    net_income_values = net_income_values[:5]
    diluted_eps_values = diluted_eps_values[:5]
    free_cashflow_values = free_cashflow_values[:5]

    available_years = max(
        len(net_income_values),
        len(diluted_eps_values),
        len(free_cashflow_values)
    )

    if available_years >= 4:
        data_quality = "Hoch"

    elif available_years >= 3:
        data_quality = "Mittel"

    else:
        data_quality = "Niedrig"

    return {
        "net_income": net_income_values,
        "eps": diluted_eps_values,
        "fcf": free_cashflow_values,
        "available_years": available_years,
        "data_quality": data_quality
    }


# =========================================================
# EPS normalisieren
# =========================================================

def normalize_eps(
    company_type,
    trailing_eps,
    forward_eps,
    historical_eps,
    revenue_growth,
    earnings_growth
):

    trailing = safe_float(trailing_eps)
    forward = safe_float(forward_eps)

    history = [
        safe_float(item["value"])
        for item in historical_eps
    ]

    history = [
        value
        for value in history
        if value is not None
    ]

    type_name = str(
        company_type.get("type", "")
    ).lower()

    if "zyklisch" in type_name:

        if len(history) >= 3:

            series = pd.Series(history)

            median_eps = float(
                series.median()
            )

            mean_eps = float(
                series.mean()
            )

            cycle_basis = (
                0.60 * median_eps +
                0.40 * mean_eps
            )

            if forward is not None:

                denominator = max(
                    abs(cycle_basis),
                    1.0
                )

                forward_difference = (
                    abs(
                        forward -
                        cycle_basis
                    )
                    / denominator
                )

                if forward_difference > 0.75:

                    normalized = (
                        0.85 * cycle_basis +
                        0.15 * forward
                    )

                    method = (
                        "Zyklus-EPS aus Median und "
                        "Durchschnitt; Forward-EPS "
                        "wegen starker Abweichung "
                        "nur mit 15 % gewichtet"
                    )

                else:

                    normalized = (
                        0.70 * cycle_basis +
                        0.30 * forward
                    )

                    method = (
                        "Zyklus-EPS aus Median und "
                        "Durchschnitt plus 30 % "
                        "Forward-EPS"
                    )

            else:

                normalized = cycle_basis

                method = (
                    "Zyklus-EPS aus 60 % Median "
                    "und 40 % Durchschnitt"
                )

            confidence = "Mittel"

            return {
                "normalized_eps": normalized,
                "method": method,
                "confidence": confidence,
                "cycle_basis": cycle_basis
            }

        if trailing is not None and forward is not None:

            normalized = (
                0.60 * trailing +
                0.40 * forward
            )

            return {
                "normalized_eps": normalized,
                "method": (
                    "Nur eingeschränkte Mehrjahresdaten; "
                    "60 % TTM-EPS + 40 % Forward-EPS"
                ),
                "confidence": "Niedrig",
                "cycle_basis": None
            }

        return {
            "normalized_eps": (
                trailing
                if trailing is not None
                else forward
            ),
            "method": (
                "Zu wenige Daten für eine "
                "zuverlässige Zyklus-Normalisierung"
            ),
            "confidence": "Niedrig",
            "cycle_basis": None
        }

    if (
        trailing is not None
        and forward is not None
        and trailing > 0
        and forward > 0
    ):

        rev_growth = (
            revenue_growth
            if revenue_growth is not None
            else 0
        )

        earn_growth = (
            earnings_growth
            if earnings_growth is not None
            else 0
        )

        if (
            rev_growth >= 0.15
            and earn_growth >= 0.15
        ):

            trailing_weight = 0.25
            forward_weight = 0.75

            method = (
                "25 % TTM-EPS + 75 % Forward-EPS "
                "bei starkem profitablem Wachstum"
            )

        elif (
            rev_growth >= 0.08
            or earn_growth >= 0.10
        ):

            trailing_weight = 0.30
            forward_weight = 0.70

            method = (
                "30 % TTM-EPS + 70 % Forward-EPS "
                "bei normalem Wachstum"
            )

        else:

            trailing_weight = 0.40
            forward_weight = 0.60

            method = (
                "40 % TTM-EPS + 60 % Forward-EPS "
                "bei stabilem Unternehmen"
            )

        normalized = (
            trailing_weight * trailing +
            forward_weight * forward
        )

        if len(history) >= 3:
            confidence = "Hoch"
        else:
            confidence = "Mittel"

        return {
            "normalized_eps": normalized,
            "method": method,
            "confidence": confidence,
            "cycle_basis": None
        }

    if forward is not None and forward > 0:

        return {
            "normalized_eps": forward,
            "method": (
                "Nur Forward-EPS verwendbar"
            ),
            "confidence": "Niedrig",
            "cycle_basis": None
        }

    if trailing is not None and trailing > 0:

        return {
            "normalized_eps": trailing,
            "method": (
                "Nur TTM-EPS verwendbar"
            ),
            "confidence": "Niedrig",
            "cycle_basis": None
        }

    return {
        "normalized_eps": None,
        "method": (
            "Keine zuverlässige EPS-Normalisierung möglich"
        ),
        "confidence": "Niedrig",
        "cycle_basis": None
    }


# =========================================================
# Hauptdaten laden
# =========================================================

CACHE_VERSION = "m5_s4_tsmc_direct_v1"

@st.cache_data(
    ttl=900,
    show_spinner=False
)
def load_stock(search_text, cache_version):

    _ = cache_version

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

    historical = build_historical_data(
        ticker
    )

    eps_normalization = normalize_eps(
        company_type,
        info.get("trailingEps"),
        info.get("forwardEps"),
        historical["eps"],
        info.get("revenueGrowth"),
        info.get("earningsGrowth")
    )

    growth_score = calculate_growth_score(
        info.get("revenueGrowth"),
        info.get("earningsGrowth")
    )

    profitability_score = calculate_profitability_score(
        company_type,
        info.get("profitMargins"),
        info.get("returnOnEquity"),
        info.get("earningsGrowth")
    )

    fcf_score = calculate_fcf_score(
        company_type,
        info.get("totalRevenue"),
        info.get("freeCashflow"),
        historical.get("fcf", [])
    )

    balance_score = calculate_balance_score(
        company_type,
        info.get("totalCash"),
        info.get("totalDebt"),
        info.get("freeCashflow"),
        historical.get("fcf", [])
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

        "company_type": company_type,
        "historical": historical,
        "eps_normalization": eps_normalization,
        "growth_score": growth_score,
        "profitability_score": profitability_score,
        "fcf_score": fcf_score,
        "balance_score": balance_score
    }


# =========================================================
# Historische Tabelle
# =========================================================

def historical_table(historical, currency):

    years = {}

    for item in historical["net_income"]:

        year = item["date"].year
        years.setdefault(year, {})

        years[year]["Nettogewinn"] = (
            format_money(
                item["value"],
                currency
            )
        )

    for item in historical["eps"]:

        year = item["date"].year
        years.setdefault(year, {})

        years[year]["EPS"] = (
            format_eps(
                item["value"],
                currency
            )
        )

    for item in historical["fcf"]:

        year = item["date"].year
        years.setdefault(year, {})

        years[year]["Free Cashflow"] = (
            format_money(
                item["value"],
                currency
            )
        )

    rows = []

    for year in sorted(
        years.keys(),
        reverse=True
    )[:5]:

        values = years[year]

        rows.append({
            "Jahr": year,
            "EPS": values.get(
                "EPS",
                "–"
            ),
            "Nettogewinn": values.get(
                "Nettogewinn",
                "–"
            ),
            "Free Cashflow": values.get(
                "Free Cashflow",
                "–"
            )
        })

    return pd.DataFrame(rows)


# =========================================================
# Benutzeroberfläche
# =========================================================

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

            data = load_stock(
                search_text,
                CACHE_VERSION
            )

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

                st.divider()

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

                st.subheader(
                    "Wachstum & Profitabilität"
                )

                col1, col2 = st.columns(2)

                with col1:

                    if data[
                        "revenue_growth"
                    ] is not None:

                        st.metric(
                            "Umsatzwachstum",
                            f"{data['revenue_growth'] * 100:.1f} %"
                        )

                    else:

                        st.metric(
                            "Umsatzwachstum",
                            "–"
                        )

                    if data[
                        "profit_margin"
                    ] is not None:

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

                    if data[
                        "earnings_growth"
                    ] is not None:

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

                st.subheader(
                    "📚 Historische Datenbasis"
                )

                historical = data[
                    "historical"
                ]

                st.write(
                    f"**Verfügbare Geschäftsjahre:** "
                    f"{historical['available_years']}"
                )

                quality = historical[
                    "data_quality"
                ]

                if quality == "Hoch":

                    st.success(
                        "Datenqualität für die "
                        "Mehrjahresanalyse: Hoch"
                    )

                elif quality == "Mittel":

                    st.warning(
                        "Datenqualität für die "
                        "Mehrjahresanalyse: Mittel"
                    )

                else:

                    st.error(
                        "Datenqualität für die "
                        "Mehrjahresanalyse: Niedrig"
                    )

                history_df = historical_table(
                    historical,
                    currency
                )

                if not history_df.empty:

                    st.dataframe(
                        history_df,
                        hide_index=True,
                        use_container_width=True
                    )

                else:

                    st.warning(
                        "Keine ausreichenden historischen "
                        "Finanzdaten verfügbar."
                    )

                st.divider()

                st.subheader(
                    "🧮 EPS-Normalisierung"
                )

                eps_result = data[
                    "eps_normalization"
                ]

                normalized_eps = eps_result[
                    "normalized_eps"
                ]

                if normalized_eps is not None:

                    st.metric(
                        "Normalisiertes EPS",
                        format_eps(
                            normalized_eps,
                            currency
                        )
                    )

                else:

                    st.warning(
                        "Kein zuverlässiges normalisiertes "
                        "EPS berechenbar."
                    )

                st.write(
                    f"**Verwendete Methode:** "
                    f"{eps_result['method']}"
                )

                confidence = eps_result[
                    "confidence"
                ]

                if confidence == "Hoch":

                    st.success(
                        "EPS-Normalisierung: "
                        "**Hohe Sicherheit**"
                    )

                elif confidence == "Mittel":

                    st.warning(
                        "EPS-Normalisierung: "
                        "**Mittlere Sicherheit**"
                    )

                else:

                    st.error(
                        "EPS-Normalisierung: "
                        "**Niedrige Sicherheit**"
                    )

                if (
                    eps_result["cycle_basis"]
                    is not None
                ):

                    st.write(
                        "**Zyklus-Basis vor "
                        "Forward-Anpassung:** "
                        f"{format_eps(
                            eps_result['cycle_basis'],
                            currency
                        )}"
                    )

                st.caption(
                    "Dieser Wert ist noch kein Fair Value. "
                    "Er bildet nur die Gewinnbasis für die "
                    "spätere Bewertung."
                )

                st.divider()

                st.subheader(
                    "📊 Multiple Score – Wachstum"
                )

                growth_result = data[
                    "growth_score"
                ]

                if growth_result["score"] is not None:

                    st.metric(
                        "Wachstums-Score",
                        f"{growth_result['score']}/30 Punkte"
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        revenue_points = growth_result[
                            "revenue_points"
                        ]

                        if revenue_points is not None:

                            st.write(
                                f"**Umsatzwachstum:** "
                                f"{revenue_points}/15 Punkte"
                            )

                        else:

                            st.write(
                                "**Umsatzwachstum:** "
                                "nicht verfügbar"
                            )

                    with col2:

                        earnings_points = growth_result[
                            "earnings_points"
                        ]

                        if earnings_points is not None:

                            st.write(
                                f"**Gewinnwachstum:** "
                                f"{earnings_points}/15 Punkte"
                            )

                        else:

                            st.write(
                                "**Gewinnwachstum:** "
                                "nicht verfügbar"
                            )

                    if growth_result[
                        "confidence"
                    ] == "Hoch":

                        st.success(
                            "Datengrundlage Wachstum: "
                            "**Hoch**"
                        )

                    else:

                        st.warning(
                            "Datengrundlage Wachstum: "
                            "**Mittel**"
                        )

                    st.caption(
                        growth_result["note"]
                    )

                else:

                    st.warning(
                        "Wachstums-Score derzeit "
                        "nicht berechenbar."
                    )

                st.caption(
                    "Modul 5 wird schrittweise aufgebaut. "
                    "Wachstum liefert maximal 30 Punkte. "
                    "Danach folgt die Profitabilität. "
                    "Noch kein Fair Value."
                )

                st.divider()

                st.subheader(
                    "📈 Multiple Score – Profitabilität"
                )

                profitability_result = data[
                    "profitability_score"
                ]

                if profitability_result["score"] is not None:

                    st.metric(
                        "Profitabilitäts-Score",
                        f"{profitability_result['score']}/30 Punkte"
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        margin_points = profitability_result[
                            "margin_points"
                        ]

                        if margin_points is not None:

                            st.write(
                                f"**Nettomarge:** "
                                f"{margin_points}/15 Punkte"
                            )

                        else:

                            st.write(
                                "**Nettomarge:** "
                                "nicht verfügbar"
                            )

                    with col2:

                        roe_points = profitability_result[
                            "roe_points"
                        ]

                        if roe_points is not None:

                            st.write(
                                f"**ROE:** "
                                f"{roe_points}/15 Punkte"
                            )

                        else:

                            st.write(
                                "**ROE:** "
                                "nicht verfügbar"
                            )

                    earnings_growth_value = safe_float(
                        data.get("earnings_growth")
                    )

                    if profitability_result[
                        "brake_active"
                    ]:

                        st.warning(
                            "⚠️ Verschlechterungsbremse aktiv"
                        )

                    elif (
                        earnings_growth_value is not None
                        and earnings_growth_value <= -0.05
                    ):

                        st.warning(
                            "⚠️ Gewinnrückgang erkannt"
                        )

                    else:

                        st.success(
                            "✓ Keine Verschlechterungsbremse aktiv"
                        )

                    st.caption(
                        profitability_result[
                            "brake_text"
                        ]
                    )

                    growth_total = data[
                        "growth_score"
                    ]["score"]

                    if growth_total is not None:

                        interim_score = (
                            growth_total +
                            profitability_result["score"]
                        )

                        st.info(
                            f"Zwischenstand Multiple Score: "
                            f"**{interim_score}/60 Punkte** "
                            f"(Wachstum + Profitabilität)"
                        )

                else:

                    st.info(
                        profitability_result[
                            "brake_text"
                        ]
                    )

                st.caption(
                    "Die Profitabilität basiert derzeit auf "
                    "aktueller Nettomarge und aktuellem ROE. "
                    "Historische Margen werden später ergänzt "
                    "und dürfen aktuelle Verschlechterungen "
                    "nicht verdecken."
                )

                st.divider()

                st.subheader(
                    "💵 Multiple Score – Free Cashflow"
                )

                fcf_result = data[
                    "fcf_score"
                ]

                if fcf_result["score"] is not None:

                    st.metric(
                        "FCF-Score",
                        f"{fcf_result['score']}/25 Punkte"
                    )

                    st.write(
                        "**Aktuelle FCF-Marge:** "
                        f"{fcf_result['fcf_margin'] * 100:.1f} %"
                    )

                    st.write(
                        "**Datengrundlage FCF:** "
                        f"{fcf_result['confidence']}"
                    )

                    if fcf_result[
                        "status"
                    ] == "deterioration":

                        st.warning(
                            "⚠️ FCF-Verschlechterung erkannt"
                        )

                    elif fcf_result[
                        "status"
                    ] == "cyclical":

                        st.warning(
                            "⚠️ Zyklischer FCF erkannt"
                        )

                    elif fcf_result[
                        "status"
                    ] == "recovery":

                        st.info(
                            "↗️ FCF-Erholung erkannt"
                        )

                    else:

                        st.success(
                            "✓ Keine FCF-Warnung"
                        )

                    st.caption(
                        fcf_result[
                            "note"
                        ]
                    )

                    growth_total = data[
                        "growth_score"
                    ]["score"]

                    profitability_total = data[
                        "profitability_score"
                    ]["score"]

                    if (
                        growth_total is not None
                        and profitability_total is not None
                    ):
                        interim_score_85 = (
                            growth_total
                            + profitability_total
                            + fcf_result["score"]
                        )

                        st.info(
                            f"Zwischenstand Multiple Score: "
                            f"**{interim_score_85}/85 Punkte** "
                            f"(Wachstum + Profitabilität + FCF)"
                        )

                else:

                    if fcf_result[
                        "confidence"
                    ] == "Sondermodell":

                        st.warning(
                            "⚠️ FCF-Sondermodell erforderlich"
                        )

                    else:

                        st.info(
                            "FCF-Score derzeit nicht verfügbar"
                        )

                    st.caption(
                        fcf_result[
                            "note"
                        ]
                    )

                st.caption(
                    "Die FCF-Punkte basieren auf der aktuellen "
                    "Free-Cashflow-Marge. Historische FCF-Werte "
                    "dienen als Trendkontrolle und dürfen einen "
                    "schwachen aktuellen Cashflow nicht schönrechnen."
                )

                st.divider()

                st.subheader(
                    "🏦 Multiple Score – Bilanz / Verschuldung"
                )

                balance_result = data[
                    "balance_score"
                ]

                if balance_result["score"] is not None:

                    st.metric(
                        "Bilanz-Score",
                        f"{balance_result['score']}/15 Punkte"
                    )

                    st.write(
                        "**Nettoschulden:** "
                        f"{format_money(
                            balance_result['net_debt'],
                            currency
                        )}"
                    )

                    if balance_result[
                        "status"
                    ] == "net_cash":

                        st.success(
                            "✓ Netto-Cash / praktisch schuldenfrei"
                        )

                    else:

                        ratio_value = balance_result[
                            "net_debt_to_fcf"
                        ]

                        if ratio_value is not None:
                            st.write(
                                "**Netto-Schulden / FCF:** "
                                f"{ratio_value:.2f}×"
                            )

                        if balance_result[
                            "status"
                        ] == "cyclical":

                            st.warning(
                                "⚠️ Zyklische FCF-Basis"
                            )

                        else:

                            st.success(
                                "✓ Normale Bilanzlogik anwendbar"
                            )

                    st.write(
                        "**Datengrundlage Bilanz:** "
                        f"{balance_result['confidence']}"
                    )

                    st.caption(
                        balance_result[
                            "note"
                        ]
                    )

                    growth_total = data[
                        "growth_score"
                    ]["score"]

                    profitability_total = data[
                        "profitability_score"
                    ]["score"]

                    fcf_total = data[
                        "fcf_score"
                    ]["score"]

                    if (
                        growth_total is not None
                        and profitability_total is not None
                        and fcf_total is not None
                    ):
                        total_score_100 = (
                            growth_total
                            + profitability_total
                            + fcf_total
                            + balance_result["score"]
                        )

                        st.success(
                            f"Multiple Score gesamt: "
                            f"**{total_score_100}/100 Punkte**"
                        )

                else:

                    if balance_result[
                        "confidence"
                    ] == "Sondermodell":

                        st.warning(
                            "⚠️ Bilanz-Sondermodell erforderlich"
                        )

                    else:

                        st.info(
                            "Bilanz-Score derzeit nicht verfügbar"
                        )

                    if balance_result[
                        "net_debt"
                    ] is not None:

                        st.write(
                            "**Nettoschulden:** "
                            f"{format_money(
                                balance_result['net_debt'],
                                currency
                            )}"
                        )

                    st.caption(
                        balance_result[
                            "note"
                        ]
                    )

                st.caption(
                    "Bilanzpunkte: Netto-Cash 15/15; "
                    "sonst Bewertung über Netto-Schulden/FCF. "
                    "Banken, Versicherungen, REIT/Immobilien "
                    "und Autohersteller benötigen Sondermodelle."
                )

                st.divider()

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
