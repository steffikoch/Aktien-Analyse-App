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
    "Unternehmenstyp, EPS-Normalisierung & Ziel-KGV"
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


def clamp(value, minimum, maximum):
    return max(
        minimum,
        min(maximum, value)
    )


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

    # Halbleiter

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
            "type": "Industrie",
            "method": "Normalisiertes EPS + KGV + FCF",
            "confidence_cap": "Mittel bis Hoch"
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

    return candidates[0]


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

    # Zyklische Unternehmen

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

            return {
                "normalized_eps": normalized,
                "method": method,
                "confidence": "Mittel",
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

    # Nicht-zyklische profitable Unternehmen

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
            "method": "Nur Forward-EPS verwendbar",
            "confidence": "Niedrig",
            "cycle_basis": None
        }

    if trailing is not None and trailing > 0:

        return {
            "normalized_eps": trailing,
            "method": "Nur TTM-EPS verwendbar",
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
# NEU: KGV-Korridor
# =========================================================

def get_multiple_corridor(company_type):

    type_name = str(
        company_type.get("type", "")
    )

    corridors = {
        "Etablierte Software / Technologie": (20, 28),
        "Autohersteller / zyklisch": (6, 10),
        "Rohstoffe / Lithium / zyklisch": (8, 14),
        "Rohstoffe / Bergbau / zyklisch": (8, 14),
        "Öl & Gas / zyklisch": (8, 13),
        "Pharma": (13, 19),
        "Halbleiter / Wachstum": (22, 32),
        "Telekommunikation": (11, 16),
        "Defensiver Konsum": (18, 26),
        "Industrie": (15, 22),
        "Versorger": (10, 15),
        "Standard-Unternehmen": (12, 20)
    }

    if type_name in corridors:

        lower, upper = corridors[type_name]

        return {
            "available": True,
            "lower": lower,
            "upper": upper
        }

    return {
        "available": False,
        "lower": None,
        "upper": None
    }


# =========================================================
# NEU: Multiple-Score
# =========================================================

def calculate_multiple_score(
    company_type,
    revenue_growth,
    earnings_growth,
    profit_margin,
    roe,
    free_cashflow,
    revenue,
    cash,
    debt
):

    type_name = str(
        company_type.get("type", "")
    )

    corridor = get_multiple_corridor(
        company_type
    )

    if not corridor["available"]:

        return {
            "available": False,
            "reason": (
                "Für diesen Unternehmenstyp wird später "
                "eine spezielle Bewertungsmethode verwendet."
            )
        }

    rev_growth = safe_float(
        revenue_growth
    )

    earn_growth = safe_float(
        earnings_growth
    )

    margin = safe_float(
        profit_margin
    )

    roe_value = safe_float(
        roe
    )

    fcf = safe_float(
        free_cashflow
    )

    revenue_value = safe_float(
        revenue
    )

    cash_value = safe_float(
        cash
    )

    debt_value = safe_float(
        debt
    )

    # -----------------------------------------------------
    # 1. Wachstum – maximal 30 Punkte
    # -----------------------------------------------------

    growth_score = 0.0

    if rev_growth is not None:

        if rev_growth >= 0.20:
            growth_score += 15

        elif rev_growth >= 0.12:
            growth_score += 13

        elif rev_growth >= 0.07:
            growth_score += 10

        elif rev_growth >= 0.03:
            growth_score += 7

        elif rev_growth >= 0:
            growth_score += 5

        elif rev_growth >= -0.05:
            growth_score += 2

    if earn_growth is not None:

        if earn_growth >= 0.25:
            growth_score += 15

        elif earn_growth >= 0.15:
            growth_score += 13

        elif earn_growth >= 0.08:
            growth_score += 10

        elif earn_growth >= 0.03:
            growth_score += 7

        elif earn_growth >= 0:
            growth_score += 5

        elif earn_growth >= -0.10:
            growth_score += 2

    else:
        # Fehlendes Gewinnwachstum soll nicht automatisch
        # wie stark negatives Wachstum behandelt werden.
        growth_score += 5

    growth_score = clamp(
        growth_score,
        0,
        30
    )

    # -----------------------------------------------------
    # 2. Profitabilität – maximal 30 Punkte
    # -----------------------------------------------------

    profitability_score = 0.0

    if margin is not None:

        if margin >= 0.25:
            profitability_score += 15

        elif margin >= 0.15:
            profitability_score += 13

        elif margin >= 0.10:
            profitability_score += 10

        elif margin >= 0.05:
            profitability_score += 7

        elif margin > 0:
            profitability_score += 4

    if roe_value is not None:

        if roe_value >= 0.25:
            profitability_score += 15

        elif roe_value >= 0.18:
            profitability_score += 13

        elif roe_value >= 0.12:
            profitability_score += 10

        elif roe_value >= 0.08:
            profitability_score += 7

        elif roe_value > 0:
            profitability_score += 4

    profitability_score = clamp(
        profitability_score,
        0,
        30
    )

    # -----------------------------------------------------
    # 3. Free Cashflow – maximal 25 Punkte
    # -----------------------------------------------------

    fcf_score = 0.0
    fcf_margin = None

    if (
        fcf is not None
        and revenue_value is not None
        and revenue_value != 0
    ):

        fcf_margin = (
            fcf /
            revenue_value
        )

        if fcf_margin >= 0.20:
            fcf_score = 25

        elif fcf_margin >= 0.15:
            fcf_score = 22

        elif fcf_margin >= 0.10:
            fcf_score = 19

        elif fcf_margin >= 0.07:
            fcf_score = 16

        elif fcf_margin >= 0.04:
            fcf_score = 13

        elif fcf_margin > 0:
            fcf_score = 9

        elif fcf_margin > -0.05:
            fcf_score = 4

        else:
            fcf_score = 0

    elif fcf is not None:

        if fcf > 0:
            fcf_score = 10

    fcf_score = clamp(
        fcf_score,
        0,
        25
    )

    # -----------------------------------------------------
    # 4. Bilanz – maximal 15 Punkte
    # -----------------------------------------------------

    balance_score = 0.0
    balance_note = ""

    if type_name == "Autohersteller / zyklisch":

        # WICHTIG:
        # Bei Autoherstellern verzerren Finanzierungs-
        # gesellschaften die konsolidierte Verschuldung.
        # Deshalb keine normale Cash-minus-Debt-Bewertung.

        balance_score = 8

        balance_note = (
            "Neutrale Bilanzbewertung: Bei Autoherstellern "
            "wird die konsolidierte Verschuldung wegen der "
            "Finanzsparte nicht wie bei normalen Unternehmen "
            "bewertet."
        )

    elif (
        cash_value is not None
        and debt_value is not None
    ):

        if debt_value <= 0:

            balance_score = 15

        elif cash_value >= debt_value:

            balance_score = 15

        else:

            net_debt = (
                debt_value -
                cash_value
            )

            if (
                fcf is not None
                and fcf > 0
            ):

                debt_to_fcf = (
                    net_debt /
                    fcf
                )

                if debt_to_fcf <= 1.0:
                    balance_score = 13

                elif debt_to_fcf <= 2.0:
                    balance_score = 11

                elif debt_to_fcf <= 3.0:
                    balance_score = 8

                elif debt_to_fcf <= 4.0:
                    balance_score = 5

                else:
                    balance_score = 2

            else:

                balance_score = 4

        balance_note = (
            "Bilanzbewertung aus liquiden Mitteln, "
            "Schulden und Free Cashflow."
        )

    else:

        # Fehlende Daten bekommen einen neutral-vorsichtigen
        # Wert und nicht automatisch null Punkte.

        balance_score = 7

        balance_note = (
            "Bilanzdaten nicht vollständig; "
            "vorsichtige neutrale Bewertung."
        )

    balance_score = clamp(
        balance_score,
        0,
        15
    )

    # -----------------------------------------------------
    # Gesamt-Score
    # -----------------------------------------------------

    total_score = (
        growth_score +
        profitability_score +
        fcf_score +
        balance_score
    )

    total_score = clamp(
        total_score,
        0,
        100
    )

    lower = corridor["lower"]
    upper = corridor["upper"]

    target_multiple = (
        lower +
        (
            upper - lower
        ) *
        (
            total_score / 100
        )
    )

    # -----------------------------------------------------
    # Kurze Begründung
    # -----------------------------------------------------

    reasons = []

    if growth_score >= 24:
        reasons.append("starkes Wachstum")
    elif growth_score >= 16:
        reasons.append("solides Wachstum")
    elif growth_score < 10:
        reasons.append("schwaches bzw. zyklisches Wachstum")

    if profitability_score >= 24:
        reasons.append("hohe Profitabilität")
    elif profitability_score >= 16:
        reasons.append("solide Profitabilität")
    elif profitability_score < 10:
        reasons.append("niedrige Profitabilität")

    if fcf_score >= 19:
        reasons.append("starker Free Cashflow")
    elif fcf_score >= 10:
        reasons.append("positiver Free Cashflow")
    else:
        reasons.append("schwacher Free Cashflow")

    if balance_score >= 12:
        reasons.append("starke Bilanz")
    elif balance_score <= 5:
        reasons.append("erhöhte Bilanzbelastung")

    reason_text = ", ".join(reasons)

    return {
        "available": True,
        "lower": lower,
        "upper": upper,
        "growth_score": round(
            growth_score,
            1
        ),
        "profitability_score": round(
            profitability_score,
            1
        ),
        "fcf_score": round(
            fcf_score,
            1
        ),
        "balance_score": round(
            balance_score,
            1
        ),
        "total_score": round(
            total_score,
            1
        ),
        "target_multiple": round(
            target_multiple,
            1
        ),
        "fcf_margin": fcf_margin,
        "balance_note": balance_note,
        "reason": reason_text
    }


# =========================================================
# Hauptdaten laden
# =========================================================

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

    multiple_result = calculate_multiple_score(
        company_type,
        info.get("revenueGrowth"),
        info.get("earningsGrowth"),
        info.get("profitMargins"),
        info.get("returnOnEquity"),
        info.get("freeCashflow"),
        info.get("totalRevenue"),
        info.get("totalCash"),
        info.get("totalDebt")
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
        "multiple_result": multiple_result
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

                # Unternehmensübersicht

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

                # Klassifizierung

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

                # Kurs

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

                # Aktuelle Datenbasis

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

                # Wachstum

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

                # Historische Daten

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

                # EPS-Normalisierung

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

                    cycle_basis_text = format_eps(
                        eps_result["cycle_basis"],
                        currency
                    )

                    st.write(
                        f"**Zyklus-Basis vor "
                        f"Forward-Anpassung:** "
                        f"{cycle_basis_text}"
                    )

                st.caption(
                    "Dieser Wert ist noch kein Fair Value. "
                    "Er bildet nur die Gewinnbasis für die "
                    "spätere Bewertung."
                )

                st.divider()

                # -----------------------------------------
                # NEU: Fundamentales Ziel-KGV
                # -----------------------------------------

                st.subheader(
                    "🎯 Fundamentales Ziel-KGV"
                )

                multiple = data[
                    "multiple_result"
                ]

                if multiple["available"]:

                    st.write(
                        f"**KGV-Korridor:** "
                        f"{multiple['lower']:.0f}× bis "
                        f"{multiple['upper']:.0f}×"
                    )

                    st.metric(
                        "Fundamentaler Multiple-Score",
                        f"{multiple['total_score']:.0f} / 100"
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        st.metric(
                            "Wachstum",
                            f"{multiple['growth_score']:.0f} / 30"
                        )

                        st.metric(
                            "Profitabilität",
                            f"{multiple['profitability_score']:.0f} / 30"
                        )

                    with col2:

                        st.metric(
                            "Free Cashflow",
                            f"{multiple['fcf_score']:.0f} / 25"
                        )

                        st.metric(
                            "Bilanz",
                            f"{multiple['balance_score']:.0f} / 15"
                        )

                    st.metric(
                        "Ermitteltes Ziel-KGV",
                        f"{multiple['target_multiple']:.1f}×"
                    )

                    if multiple["fcf_margin"] is not None:

                        st.write(
                            f"**FCF-Marge:** "
                            f"{multiple['fcf_margin'] * 100:.1f} %"
                        )

                    st.write(
                        f"**Begründung:** "
                        f"{multiple['reason']}"
                    )

                    st.caption(
                        multiple["balance_note"]
                    )

                    st.info(
                        "Das Ziel-KGV ist noch kein Fair Value. "
                        "Zuerst prüfen wir, ob der automatisch "
                        "ermittelte Multiple bei verschiedenen "
                        "Unternehmen plausibel ist."
                    )

                else:

                    st.info(
                        multiple["reason"]
                    )

                st.divider()

                # Quartalszahlen

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

                # Börsenplatz

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
