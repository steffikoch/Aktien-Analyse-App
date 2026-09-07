import streamlit as st
import yfinance as yf
import pandas as pd
import math
from datetime import datetime

st.set_page_config(
    page_title="Aktien-Analyse V2",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Aktien-Analyse V2")
st.caption(
    "Modul 1–7 – Suche, Datenbasis, Unternehmenstyp, EPS-Normalisierung, "
    "Multiple Score, Bewertungs-Korridor, Fair Value & Signal-Engine"
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


def build_currency_context(
    quote_currency,
    financial_currency=None,
    fx_conversion=None
):
    """
    Keep trading/quote currency separate from the currency of fundamentals.

    Examples:
    - UK shares can trade in GBp while fundamentals are in GBP.
    - A German secondary listing can trade in EUR while the verified primary
      fundamental source reports in USD. In that case an explicit FX factor
      is required for Fair-Value/price comparisons.

    No currency mismatch is silently treated as 1:1.
    """
    raw_quote = str(quote_currency or "").strip()
    raw_financial = str(
        financial_currency or raw_quote or ""
    ).strip()

    if raw_quote.upper() == "GBX":
        raw_quote = "GBp"

    if raw_financial.upper() == "GBX":
        raw_financial = "GBp"

    # Explicit UK pence handling.
    if raw_quote == "GBp" and raw_financial == "GBP":
        return {
            "quote_currency": "GBp",
            "financial_currency": "GBP",
            "valuation_currency": "GBP",
            "mixed_units": True,
            "conversion_available": True,
            "conversion_kind": "gbp_pence",
            "financial_to_quote_factor": 100.0,
            "quote_to_financial_factor": 0.01,
            "fx_symbol": None,
            "note": (
                "Britische Pence-Notierung erkannt: Der Aktienkurs wird "
                "in GBp (Pence) geführt, während EPS und die fundamentalen "
                "Finanzkennzahlen in GBP (Pfund Sterling) geführt werden. "
                "Für den Fair-Value/Kurs-Vergleich wird ausdrücklich "
                "1 GBP = 100 GBp verwendet."
            )
        }

    # Same currency: no conversion required.
    if raw_quote and raw_financial and raw_quote == raw_financial:
        return {
            "quote_currency": raw_quote,
            "financial_currency": raw_financial,
            "valuation_currency": raw_financial,
            "mixed_units": False,
            "conversion_available": True,
            "conversion_kind": "same_currency",
            "financial_to_quote_factor": 1.0,
            "quote_to_financial_factor": 1.0,
            "fx_symbol": None,
            "note": None
        }

    fx = fx_conversion if isinstance(fx_conversion, dict) else {}
    factor = safe_float(fx.get("factor"))

    if (
        raw_quote
        and raw_financial
        and factor is not None
        and factor > 0
    ):
        inverse = 1.0 / factor
        fx_symbol = fx.get("symbol")

        return {
            "quote_currency": raw_quote,
            "financial_currency": raw_financial,
            "valuation_currency": raw_financial,
            "mixed_units": True,
            "conversion_available": True,
            "conversion_kind": "fx",
            "financial_to_quote_factor": factor,
            "quote_to_financial_factor": inverse,
            "fx_symbol": fx_symbol,
            "note": (
                f"Getrennte Handels- und Finanzwährung erkannt: Kurs in "
                f"{raw_quote}, Fundamentaldaten in {raw_financial}. Für "
                f"Bewertungen wird ausdrücklich 1 {raw_financial} = "
                f"{factor:.6f} {raw_quote} verwendet"
                + (f" ({fx_symbol})." if fx_symbol else ".")
            )
        }

    # Mismatch without a verified conversion: keep it visible and block
    # currency-dependent valuation steps instead of assuming parity.
    return {
        "quote_currency": raw_quote or quote_currency,
        "financial_currency": raw_financial or financial_currency,
        "valuation_currency": raw_financial or financial_currency,
        "mixed_units": bool(raw_quote and raw_financial and raw_quote != raw_financial),
        "conversion_available": False,
        "conversion_kind": "unavailable",
        "financial_to_quote_factor": None,
        "quote_to_financial_factor": None,
        "fx_symbol": None,
        "note": (
            "Kurs- und Finanzwährung weichen voneinander ab. Eine belastbare "
            "Währungsumrechnung konnte nicht geladen werden; abhängige "
            "Bewertungsschritte werden deshalb gesperrt."
        ) if raw_quote != raw_financial else None
    }


def sanitize_profit_margin(
    raw_margin,
    net_income,
    revenue
):
    """
    Treat a demonstrably contradictory Yahoo 0.0 margin as missing.

    A real zero remains valid when the reported net income is also zero.
    No replacement margin is estimated from other values.
    """
    margin = safe_float(raw_margin)
    net_income_value = safe_float(net_income)
    revenue_value = safe_float(revenue)

    if margin is None:
        return None, None

    if (
        margin == 0.0
        and revenue_value is not None
        and revenue_value > 0
        and net_income_value is not None
        and net_income_value != 0.0
    ):
        return (
            None,
            (
                "Yahoo meldet 0,0 % Nettomarge, obwohl gleichzeitig "
                "ein von null abweichender Nettogewinn ausgewiesen wird. "
                "Der widersprüchliche Margenwert wird deshalb als fehlend "
                "behandelt und erhält keine Punkte."
            )
        )

    return margin, None


def apply_eps_confidence_brake(
    base_confidence,
    trailing_eps,
    forward_eps
):
    """
    Reduce EPS-normalization confidence when positive TTM and forward EPS
    diverge strongly. The EPS calculation itself is not changed.
    """
    trailing = safe_float(trailing_eps)
    forward = safe_float(forward_eps)

    if (
        trailing is None
        or forward is None
        or trailing <= 0
        or forward <= 0
    ):
        return base_confidence, None, None

    deviation = abs(forward / trailing - 1.0)

    confidence_rank = {
        "Niedrig": 0,
        "Mittel": 1,
        "Hoch": 2
    }

    if deviation >= 1.50:
        confidence_cap = "Niedrig"
    elif deviation >= 0.50:
        confidence_cap = "Mittel"
    else:
        return base_confidence, None, deviation

    base_rank = confidence_rank.get(
        base_confidence,
        0
    )
    cap_rank = confidence_rank[
        confidence_cap
    ]

    confidence = (
        base_confidence
        if base_rank <= cap_rank
        else confidence_cap
    )

    note = (
        "TTM-EPS und Forward-EPS weichen um "
        f"{deviation * 100:.1f} % voneinander ab. "
        "Die EPS-Berechnung bleibt unverändert; "
        f"die angezeigte Sicherheit wird höchstens als {confidence_cap} eingestuft."
    )

    return confidence, note, deviation


def build_eps_result(
    normalized_eps,
    method,
    confidence,
    cycle_basis,
    trailing_eps,
    forward_eps,
    metadata=None
):
    adjusted_confidence, confidence_note, deviation = (
        apply_eps_confidence_brake(
            confidence,
            trailing_eps,
            forward_eps
        )
    )

    result = {
        "normalized_eps": normalized_eps,
        "method": method,
        "confidence": adjusted_confidence,
        "cycle_basis": cycle_basis,
        "confidence_note": confidence_note,
        "ttm_forward_deviation": deviation
    }

    if isinstance(metadata, dict):
        result.update(metadata)

    return result


def has_usable_positive_earnings_basis(
    eps_normalization
):
    if not isinstance(
        eps_normalization,
        dict
    ):
        return False

    normalized_eps = safe_float(
        eps_normalization.get(
            "normalized_eps"
        )
    )

    return (
        normalized_eps is not None
        and normalized_eps > 0
    )


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
        "autohersteller",
        "midstream"
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

    if fcf_margin < 0:
        status = "negative"
        note = (
            "⚠️ Aktueller Free Cashflow ist negativ. "
            "Die FCF-Punkte bleiben ausschließlich von der aktuellen "
            "FCF-Marge abhängig; historische Werte erhöhen den Score nicht."
        )
    else:
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
        "autohersteller",
        "midstream"
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

    # BETA Technologies: elektrische Luftfahrt / Early Growth,
    # nicht automatisch klassisches Defense-Unternehmen.
    if (
        symbol_text == "BETA"
        or "beta technologies" in name_text
    ):
        return {
            "type": "Aerospace / elektrische Luftfahrt / Early Growth",
            "method": (
                "Reifegrad-/Projektbewertung; "
                "kein Standard-KGV"
            ),
            "confidence_cap": "Niedrig"
        }

    # Legal & General: Finanzkonzern mit Versicherung und Asset Management.
    if (
        symbol_text == "LGEN.L"
        or "legal & general" in name_text
        or "legal and general" in name_text
    ):
        return {
            "type": "Versicherung / Asset Management / Finanzkonzern",
            "method": (
                "Core Earnings + ROE/Book Value + "
                "Solvency-/Kapitalprüfung"
            ),
            "confidence_cap": "Mittel"
        }

    # Midstream-Infrastruktur: Yahoo-Branche Oil & Gas Midstream wird
    # generell vor der normalen Öl-&-Gas-Logik geroutet. Kinder Morgan
    # bleibt zusätzlich über Ticker/Name eindeutig abgesichert.
    if (
        symbol_text == "KMI"
        or "kinder morgan" in name_text
        or "oil & gas midstream" in industry_text
        or "oil and gas midstream" in industry_text
    ):
        return {
            "type": "Öl & Gas / Midstream",
            "method": (
                "EV/EBITDA + distributable Cashflow + "
                "Verschuldung"
            ),
            "confidence_cap": "Mittel"
        }

    # USA Rare Earth: Projekt-/Aufbauphase, kein normaler zyklischer Produzent.
    if (
        symbol_text == "USAR"
        or "usa rare earth" in name_text
    ):
        return {
            "type": "Rohstoffe / Early-Stage Mining / Projektentwicklung",
            "method": (
                "Projekt-/Asset-basierte Bewertung; "
                "kein Standard-KGV"
            ),
            "confidence_cap": "Niedrig"
        }

    # IPG Photonics: industrielle Photonik/Lasersysteme,
    # nicht automatisch Lithografie oder klassisches SemiCap.
    if (
        symbol_text == "IPGP"
        or "ipg photonics" in name_text
    ):
        return {
            "type": "Industrie / Photonik & Lasersysteme",
            "method": (
                "Normalisiertes EPS + FCF; "
                "Peer-Set später festlegen"
            ),
            "confidence_cap": "Mittel"
        }

    # Software-Untertypen aus dem Testlauf.
    if (
        symbol_text == "DOCU"
        or "docusign" in name_text
    ):
        return {
            "type": "Software / reifes SaaS / moderates Wachstum",
            "method": (
                "Normalisiertes EPS + FCF; "
                "eigenes SaaS-KGV später festlegen"
            ),
            "confidence_cap": "Mittel"
        }

    if (
        symbol_text == "TOST"
        or "toast, inc" in name_text
        or name_text == "toast"
    ):
        return {
            "type": "Software / Vertical SaaS + Payments / Wachstum",
            "method": (
                "EV/Sales bzw. EV/FCF + "
                "Wachstum/Profitabilität"
            ),
            "confidence_cap": "Mittel"
        }

    if (
        symbol_text == "DBX"
        or "dropbox" in name_text
    ):
        return {
            "type": "Software / reifes SaaS / langsames Wachstum",
            "method": (
                "Normalisiertes EPS + FCF; "
                "eigener SaaS-Korridor später festlegen"
            ),
            "confidence_cap": "Mittel"
        }

    # Rheinmetall bleibt bewusst im bereits getesteten Defense-Modell.
    if (
        symbol_text in ["RHM.DE", "RNMBY", "RNMBF"]
        or "rheinmetall" in name_text
    ):
        return {
            "type": "Defense / stark wachsend",
            "method": (
                "Normalisiertes EPS + KGV + "
                "Auftrags-/Visibilitätskontrolle"
            ),
            "confidence_cap": "Mittel bis Hoch"
        }

    # Weitere klar erkennbare Defense-Fälle.
    defense_name_terms = [
        "defense",
        "defence",
        "military",
        "ordnance"
    ]
    known_defense_symbols = [
        "KTOS",
        "BA.L",
        "LDO.MI",
        "HO.PA",
        "SAAB-B.ST"
    ]

    if (
        symbol_text in known_defense_symbols
        or any(term in name_text for term in defense_name_terms)
    ):
        return {
            "type": "Defense / stark wachsend",
            "method": (
                "Normalisiertes EPS + KGV + "
                "Auftrags-/Visibilitätskontrolle"
            ),
            "confidence_cap": "Mittel bis Hoch"
        }

    # Aerospace & Defense als Yahoo-Branche allein reicht nicht mehr
    # für die Zuordnung zum klassischen Defense-Modell.
    aerospace_defense_terms = [
        "aerospace & defense",
        "aerospace and defense"
    ]

    if any(
        term in industry_text
        for term in aerospace_defense_terms
    ):
        return {
            "type": "Aerospace & Defense / Untertyp noch nicht eindeutig",
            "method": (
                "Geschäftsmodell bestimmen, bevor ein "
                "Bewertungs-Korridor verwendet wird"
            ),
            "confidence_cap": "Niedrig"
        }

    # ASML / Lithografie nur noch über eindeutige Identifikation.
    if (
        symbol_text in ["ASML", "ASML.AS"]
        or "asml" in name_text
    ):
        return {
            "type": "Halbleiterausrüstung / Lithografie",
            "method": (
                "Normalisiertes EPS + KGV + "
                "Auftrags-/Visibilitätskontrolle"
            ),
            "confidence_cap": "Mittel bis Hoch"
        }

    # Andere Halbleiterausrüster werden nicht automatisch als Lithografie gewertet.
    if "semiconductor equipment" in industry_text:
        return {
            "type": "Halbleiterausrüstung / Untertyp noch nicht eindeutig",
            "method": (
                "Untertyp bestimmen, bevor ein "
                "Bewertungs-Korridor verwendet wird"
            ),
            "confidence_cap": "Niedrig"
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

    # Öl & Gas – nach dem spezifischen Midstream-Router.
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

    # Bergbau / Rohstoffe – nach dem spezifischen Early-Stage-Router.
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

    # Bewusst bestätigte etablierte Software-/Technologie-Unternehmen.
    established_software_symbols = [
        "MSFT",
        "ORCL",
        "SAP",
        "SAP.DE",
        "CRM",
        "ADBE",
        "IBM"
    ]
    established_software_names = [
        "microsoft",
        "oracle",
        "sap se",
        "salesforce",
        "adobe",
        "international business machines"
    ]

    if (
        symbol_text in established_software_symbols
        or any(term in name_text for term in established_software_names)
    ):
        return {
            "type": "Etablierte Software / Technologie",
            "method": "Normalisiertes EPS + qualitätsbereinigtes KGV",
            "confidence_cap": "Hoch"
        }

    # Andere Software wird nicht mehr automatisch in den Premium-Korridor geroutet.
    software_terms = [
        "software",
        "information technology services"
    ]

    if any(
        term in industry_text
        for term in software_terms
    ):
        return {
            "type": "Software / Untertyp noch nicht eindeutig",
            "method": (
                "Software-Untertyp bestimmen, bevor ein "
                "Bewertungs-Korridor verwendet wird"
            ),
            "confidence_cap": "Niedrig"
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
    normalized_query = " ".join(query_upper.split())

    # Eindeutige Hauptnotierungen für bekannte Suchnamen.
    # Kurze bzw. mehrdeutige Firmennamen werden bewusst vor der
    # allgemeinen Yahoo-Suche geroutet, damit keine ähnlich
    # benannten Nebenwerte gewählt werden. Direkt eingegebene
    # Ticker wie CS.PA oder MUV2.DE bleiben unverändert respektiert.
    primary_name_routes = {
        "AXA": {
            "symbol": "CS.PA",
            "quoteType": "EQUITY",
            "longname": "AXA SA",
            "exchange": "PAR"
        },
        "AXA SA": {
            "symbol": "CS.PA",
            "quoteType": "EQUITY",
            "longname": "AXA SA",
            "exchange": "PAR"
        },
        "MUNICH RE": {
            "symbol": "MUV2.DE",
            "quoteType": "EQUITY",
            "longname": (
                "Münchener Rückversicherungs-Gesellschaft "
                "Aktiengesellschaft in München"
            ),
            "exchange": "GER"
        },
        "MUNICHRE": {
            "symbol": "MUV2.DE",
            "quoteType": "EQUITY",
            "longname": (
                "Münchener Rückversicherungs-Gesellschaft "
                "Aktiengesellschaft in München"
            ),
            "exchange": "GER"
        },
        "MÜNCHENER RÜCK": {
            "symbol": "MUV2.DE",
            "quoteType": "EQUITY",
            "longname": (
                "Münchener Rückversicherungs-Gesellschaft "
                "Aktiengesellschaft in München"
            ),
            "exchange": "GER"
        },
        "MUENCHENER RUECK": {
            "symbol": "MUV2.DE",
            "quoteType": "EQUITY",
            "longname": (
                "Münchener Rückversicherungs-Gesellschaft "
                "Aktiengesellschaft in München"
            ),
            "exchange": "GER"
        },
        "MÜNCHENER RÜCKVERSICHERUNG": {
            "symbol": "MUV2.DE",
            "quoteType": "EQUITY",
            "longname": (
                "Münchener Rückversicherungs-Gesellschaft "
                "Aktiengesellschaft in München"
            ),
            "exchange": "GER"
        },
        "MUENCHENER RUECKVERSICHERUNG": {
            "symbol": "MUV2.DE",
            "quoteType": "EQUITY",
            "longname": (
                "Münchener Rückversicherungs-Gesellschaft "
                "Aktiengesellschaft in München"
            ),
            "exchange": "GER"
        },
        "ING": {
            "symbol": "INGA.AS",
            "quoteType": "EQUITY",
            "longname": "ING Groep N.V.",
            "exchange": "AMS"
        },
        "ING GROEP": {
            "symbol": "INGA.AS",
            "quoteType": "EQUITY",
            "longname": "ING Groep N.V.",
            "exchange": "AMS"
        },
        "ING GROEP N.V.": {
            "symbol": "INGA.AS",
            "quoteType": "EQUITY",
            "longname": "ING Groep N.V.",
            "exchange": "AMS"
        }
    }

    if normalized_query in primary_name_routes:
        return primary_name_routes[normalized_query]

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
# Aktiensuche – Vorschläge / Autocomplete
# =========================================================

@st.cache_data(
    ttl=900,
    show_spinner=False
)
def search_stock_suggestions(search_text):
    """
    Lightweight search for the selection window.

    Only Yahoo search results are loaded here. Full company/financial data
    are requested only after the user explicitly selects a stock.
    """
    query = str(search_text or "").strip()

    if len(query) < 2:
        return []

    query_upper = query.upper()
    normalized_query = " ".join(query_upper.split())

    suggestions = []

    # Known main listings are injected as suggestions when the typed text
    # already clearly points toward the company. This preserves our tested
    # primary-listing routing without auto-loading the analysis.
    preferred_aliases = [
        {
            "aliases": ["AXA", "AXA SA"],
            "symbol": "CS.PA",
            "quoteType": "EQUITY",
            "longname": "AXA SA",
            "exchange": "PAR",
            "exchDisp": "Paris",
            "_preferred": True,
        },
        {
            "aliases": [
                "MUNICH RE",
                "MUNICHRE",
                "MÜNCHENER RÜCK",
                "MUENCHENER RUECK",
                "MÜNCHENER RÜCKVERSICHERUNG",
                "MUENCHENER RUECKVERSICHERUNG",
            ],
            "symbol": "MUV2.DE",
            "quoteType": "EQUITY",
            "longname": (
                "Münchener Rückversicherungs-Gesellschaft "
                "Aktiengesellschaft in München"
            ),
            "exchange": "GER",
            "exchDisp": "XETRA",
            "_preferred": True,
        },
        {
            "aliases": [
                "TSMC",
                "TAIWAN SEMICONDUCTOR",
                "TAIWAN SEMICONDUCTOR MANUFACTURING",
                "TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY",
            ],
            "symbol": "2330.TW",
            "quoteType": "EQUITY",
            "longname": "Taiwan Semiconductor Manufacturing Company Limited",
            "exchange": "TAI",
            "exchDisp": "Taiwan",
            "_preferred": True,
        },
        {
            "aliases": [
                "MICROSOFT",
                "MICROSOFT CORPORATION",
            ],
            "symbol": "MSFT",
            "quoteType": "EQUITY",
            "longname": "Microsoft Corporation",
            "exchange": "NMS",
            "exchDisp": "NASDAQ",
            "_preferred": True,
        },
        {
            "aliases": [
                "ING",
                "ING GROEP",
                "ING GROEP N.V.",
            ],
            "symbol": "INGA.AS",
            "quoteType": "EQUITY",
            "longname": "ING Groep N.V.",
            "exchange": "AMS",
            "exchDisp": "Amsterdam",
            "_preferred": True,
        },
    ]

    for preferred in preferred_aliases:
        matches_alias = any(
            alias.startswith(normalized_query)
            or normalized_query.startswith(alias)
            for alias in preferred["aliases"]
        )

        if matches_alias:
            suggestions.append(
                {
                    key: value
                    for key, value in preferred.items()
                    if key != "aliases"
                }
            )

    try:
        search = yf.Search(
            query,
            max_results=25,
            news_count=0
        )
        quotes = search.quotes or []
    except Exception:
        quotes = []

    equities = [
        item for item in quotes
        if str(item.get("quoteType", "")).upper() == "EQUITY"
    ]

    for yahoo_rank, item in enumerate(equities):
        row = dict(item)
        row["_preferred"] = False
        row["_yahoo_rank"] = yahoo_rank
        suggestions.append(row)

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
        "SAO": 40,
    }

    secondary_suffixes = [
        ".F", ".BE", ".MU", ".DU", ".HM", ".HA", ".SG",
        ".VI", ".MX", ".SA"
    ]

    def suggestion_score(item):
        symbol = str(item.get("symbol", "")).upper()
        exchange = str(item.get("exchange", "")).upper()
        name = str(
            item.get("longname")
            or item.get("shortname")
            or ""
        ).upper()

        score = preferred_exchange_order.get(exchange, 50)

        # 1) Tested main listings / aliases have top priority.
        #    This deliberately outranks an exact ticker match when the
        #    exact ticker is an ADR/secondary listing (for example ING
        #    on NYSE versus INGA.AS in Amsterdam). The user still has to
        #    select the result explicitly.
        if item.get("_preferred"):
            score += 2600

        # 2) Exact ticker matches remain a very strong signal, but below
        #    a deliberately defined primary/home listing.
        if symbol == query_upper:
            score += 1400
        elif symbol.startswith(query_upper):
            score += 180

        # 3) Name-prefix matches are more useful than a match somewhere
        #    inside the company name. This improves short 2–3 letter input.
        if name == normalized_query:
            score += 800
        elif name.startswith(normalized_query):
            score += 360
        elif normalized_query and normalized_query in name:
            score += 120

        name_words = [
            word for word in name.replace("-", " ").split()
            if word
        ]
        if normalized_query and any(
            word.startswith(normalized_query)
            for word in name_words
        ):
            score += 180

        query_words = [
            word for word in normalized_query.split()
            if len(word) >= 2
        ]
        score += sum(
            18 for word in query_words
            if word in name
        )

        # 4) Preserve some of Yahoo's own relevance order as a tie-breaker.
        yahoo_rank = item.get("_yahoo_rank")
        if yahoo_rank is not None:
            try:
                score += max(0, 80 - int(yahoo_rank) * 4)
            except Exception:
                pass

        # 5) Secondary/local side listings remain slightly less preferred.
        if any(
            symbol.endswith(suffix)
            for suffix in secondary_suffixes
        ):
            score -= 25

        return score

    # Highest-quality result wins for duplicate symbols.
    by_symbol = {}
    for item in suggestions:
        symbol = str(item.get("symbol", "")).upper().strip()
        if not symbol:
            continue

        if (
            symbol not in by_symbol
            or suggestion_score(item) > suggestion_score(by_symbol[symbol])
        ):
            by_symbol[symbol] = item

    ranked = sorted(
        by_symbol.values(),
        key=suggestion_score,
        reverse=True
    )

    clean_results = []
    for item in ranked[:8]:
        clean_results.append({
            "symbol": str(item.get("symbol", "")).upper(),
            "name": (
                item.get("longname")
                or item.get("shortname")
                or item.get("symbol")
                or "Unbekannt"
            ),
            "exchange": (
                item.get("exchDisp")
                or item.get("exchange")
                or "–"
            ),
            "currency": item.get("currency"),
        })

    return clean_results


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
# Structural-Break-Kontrolle für zyklische EPS-Historien
# =========================================================

VERIFIED_STRUCTURAL_BREAKS = {
    # Newmont completed the Newcrest acquisition on 06.11.2023. The 2023
    # fiscal year is therefore a transition year and older years describe a
    # materially different portfolio. Only full years from 2024 onward are
    # eligible for a post-break cyclical EPS history.
    "NEM": {
        "event_name": "Newcrest-Übernahme",
        "event_date": "06.11.2023",
        "break_year": 2023,
        "first_full_comparable_year": 2024,
        "minimum_full_post_break_years": 3,
        "source_name": "Newmont – Abschluss der Newcrest-Übernahme",
        "source_note": (
            "Newmont schloss die Übernahme von Newcrest am 06.11.2023 ab. "
            "2023 gilt deshalb als Übergangsjahr; frühere Geschäftsjahre "
            "werden für die zyklische EPS-Normalisierung des heutigen "
            "Konzerns nicht gleichgewichtet weiterverwendet."
        ),
    },
}


def resolve_structural_break(symbol, company_type):
    """Return only explicitly verified material structural breaks.

    V2.12 deliberately does not infer M&A, spin-offs or portfolio changes from
    Yahoo ratios. Unknown companies receive no structural-break adjustment.
    """
    type_name = str((company_type or {}).get("type", "")).lower()
    if "zyklisch" not in type_name:
        return {"active": False}

    symbol_text = str(symbol or "").upper().strip()
    event = VERIFIED_STRUCTURAL_BREAKS.get(symbol_text)
    if not isinstance(event, dict):
        return {"active": False}

    return {"active": True, **event}


def _eps_history_rows(historical_eps):
    rows = []
    for item in historical_eps or []:
        if not isinstance(item, dict):
            continue
        value = safe_float(item.get("value"))
        date_value = item.get("date")
        year = getattr(date_value, "year", None)
        if value is None or year is None:
            continue
        rows.append({
            "year": int(year),
            "value": value,
        })
    return rows


# =========================================================
# EPS normalisieren
# =========================================================

def normalize_eps(
    company_type,
    trailing_eps,
    forward_eps,
    historical_eps,
    revenue_growth,
    earnings_growth,
    structural_break=None
):

    trailing = safe_float(trailing_eps)
    forward = safe_float(forward_eps)

    history_rows = _eps_history_rows(historical_eps)
    history = [row["value"] for row in history_rows]

    type_name = str(
        company_type.get("type", "")
    ).lower()

    if (
        "early-stage mining" in type_name
        or "projektentwicklung" in type_name
    ):
        return build_eps_result(
            None,
            (
                "Early-Stage-/Projektunternehmen: "
                "keine belastbare EPS-Normalisierung für "
                "eine KGV-Bewertung"
            ),
            "Niedrig",
            None,
            trailing,
            forward
        )

    if "zyklisch" in type_name:

        break_control = (
            structural_break
            if isinstance(structural_break, dict)
            else {"active": False}
        )
        structural_metadata = {
            "structural_break": break_control,
            "structural_break_active": bool(break_control.get("active", False)),
            "normalization_blocked_by_structural_break": False,
            "comparable_full_years": [],
            "excluded_history_years": [],
            "comparable_full_years_count": 0,
            "minimum_full_post_break_years": None,
            "diagnostic_post_break_cycle_basis": None,
        }

        if break_control.get("active", False):
            first_year = int(break_control.get("first_full_comparable_year") or 0)
            minimum_years = int(break_control.get("minimum_full_post_break_years") or 3)

            comparable_rows = [
                row for row in history_rows
                if row["year"] >= first_year
            ]
            excluded_rows = [
                row for row in history_rows
                if row["year"] < first_year
            ]

            history = [row["value"] for row in comparable_rows]
            comparable_years = sorted({row["year"] for row in comparable_rows}, reverse=True)
            excluded_years = sorted({row["year"] for row in excluded_rows}, reverse=True)

            diagnostic_basis = None
            if len(history) >= 2:
                diagnostic_series = pd.Series(history)
                diagnostic_basis = float(
                    0.60 * diagnostic_series.median()
                    + 0.40 * diagnostic_series.mean()
                )

            structural_metadata.update({
                "comparable_full_years": comparable_years,
                "excluded_history_years": excluded_years,
                "comparable_full_years_count": len(comparable_years),
                "minimum_full_post_break_years": minimum_years,
                "diagnostic_post_break_cycle_basis": diagnostic_basis,
            })

            if len(comparable_years) < minimum_years:
                structural_metadata["normalization_blocked_by_structural_break"] = True
                method = (
                    f"Structural-Break-Kontrolle: {break_control.get('event_name', 'wesentlicher Strukturbruch')} "
                    f"am {break_control.get('event_date', '–')}; nur {len(comparable_years)} vollständig "
                    f"vergleichbare Geschäftsjahre nach dem Strukturbruch, benötigt werden mindestens "
                    f"{minimum_years}. Keine Zyklus-EPS-Bewertungsbasis freigegeben."
                )
                return build_eps_result(
                    None,
                    method,
                    "Niedrig",
                    None,
                    trailing,
                    forward,
                    structural_metadata
                )

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

            if structural_metadata.get("structural_break_active"):
                method = "Strukturbruch-bereinigt: " + method

            return build_eps_result(
                normalized,
                method,
                "Mittel",
                cycle_basis,
                trailing,
                forward,
                structural_metadata
            )

        if trailing is not None and forward is not None:

            normalized = (
                0.60 * trailing +
                0.40 * forward
            )

            return build_eps_result(
                normalized,
                (
                    "Nur eingeschränkte Mehrjahresdaten; "
                    "60 % TTM-EPS + 40 % Forward-EPS"
                ),
                "Niedrig",
                None,
                trailing,
                forward,
                structural_metadata
            )

        normalized = (
            trailing
            if trailing is not None
            else forward
        )

        return build_eps_result(
            normalized,
            (
                "Zu wenige Daten für eine "
                "zuverlässige Zyklus-Normalisierung"
            ),
            "Niedrig",
            None,
            trailing,
            forward,
            structural_metadata
        )

    if (
        trailing is not None
        and forward is not None
        and trailing > 0
        and forward > 0
    ):

        # Missing growth data stay missing. They are not converted to 0.
        rev_growth = safe_float(
            revenue_growth
        )
        earn_growth = safe_float(
            earnings_growth
        )

        classification_strong_growth = (
            "defense / stark wachsend" in type_name
        )

        strong_growth = (
            classification_strong_growth
            or (
                rev_growth is not None
                and earn_growth is not None
                and rev_growth >= 0.15
                and earn_growth >= 0.15
            )
        )

        normal_growth = (
            (
                rev_growth is not None
                and rev_growth >= 0.08
            )
            or (
                earn_growth is not None
                and earn_growth >= 0.10
            )
        )

        if strong_growth:

            trailing_weight = 0.25
            forward_weight = 0.75

            method = (
                "25 % TTM-EPS + 75 % Forward-EPS "
                "bei starkem profitablem Wachstum"
            )

        elif normal_growth:

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

        return build_eps_result(
            normalized,
            method,
            confidence,
            None,
            trailing,
            forward
        )

    if forward is not None and forward > 0:

        return build_eps_result(
            forward,
            "Nur Forward-EPS verwendbar",
            "Niedrig",
            None,
            trailing,
            forward
        )

    if trailing is not None and trailing > 0:

        return build_eps_result(
            trailing,
            "Nur TTM-EPS verwendbar",
            "Niedrig",
            None,
            trailing,
            forward
        )

    return build_eps_result(
        None,
        "Keine zuverlässige EPS-Normalisierung möglich",
        "Niedrig",
        None,
        trailing,
        forward
    )


# =========================================================
# Versicherungs-Sondermodell V1 – Datenbasis / Plausibilitätscheck
# =========================================================

def build_insurance_special_model(
    company_type,
    info,
    price,
    currency_context
):
    """
    Conservative insurer-specific data block.

    It does not create a new score, valuation multiple or fair value.
    It only prepares insurer-relevant Yahoo fields, checks obvious
    unit/plausibility conflicts and makes GBp/GBP handling explicit.
    Core earnings and solvency/capital ratios are not estimated.
    """
    type_name = str(
        company_type.get("type", "")
    ).lower()

    if "versicherung" not in type_name:
        return {
            "applicable": False
        }

    quote_price = safe_float(price)
    quote_to_financial = safe_float(
        currency_context.get(
            "quote_to_financial_factor",
            1.0
        )
    )

    if quote_to_financial is None:
        quote_to_financial = 1.0

    price_financial = (
        quote_price * quote_to_financial
        if quote_price is not None
        else None
    )

    book_value = safe_float(
        info.get("bookValue")
    )
    roe = safe_float(
        info.get("returnOnEquity")
    )
    trailing_eps = safe_float(
        info.get("trailingEps")
    )
    forward_eps = safe_float(
        info.get("forwardEps")
    )
    raw_dividend_yield = safe_float(
        info.get("dividendYield")
    )
    trailing_annual_dividend_yield = safe_float(
        info.get("trailingAnnualDividendYield")
    )
    dividend_rate = safe_float(
        info.get("dividendRate")
    )
    payout_ratio = safe_float(
        info.get("payoutRatio")
    )
    yahoo_price_to_book = safe_float(
        info.get("priceToBook")
    )

    # -----------------------------------------------------
    # KBV: nur anzeigen, wenn Kurs/Buchwert und Yahoo-KBV
    # als zweiter Anker ausreichend gut zusammenpassen.
    # -----------------------------------------------------
    calculated_price_to_book = None
    if (
        price_financial is not None
        and price_financial > 0
        and book_value is not None
        and book_value > 0
    ):
        calculated_price_to_book = (
            price_financial / book_value
        )

    pb_display_value = None
    pb_consistency_status = "unverified"
    pb_consistency_note = None

    if calculated_price_to_book is None:
        pb_consistency_note = (
            "KBV konnte aus Kurs und Buchwert je Aktie nicht "
            "belastbar berechnet werden. Es wird kein Wert geschätzt."
        )

    elif (
        yahoo_price_to_book is not None
        and yahoo_price_to_book > 0
    ):
        pb_deviation = abs(
            calculated_price_to_book
            / yahoo_price_to_book
            - 1.0
        )

        if pb_deviation <= 0.20:
            pb_display_value = calculated_price_to_book
            pb_consistency_status = "plausible"
            pb_consistency_note = (
                "KBV-Plausibilitätscheck bestanden: Das aus Kurs und "
                "Buchwert je Aktie berechnete KBV liegt innerhalb von "
                "20 % des separat gemeldeten Yahoo-KBV. Der Wert bleibt "
                "trotzdem nur eine Datenbasis und erzeugt noch keine Bewertung."
            )
        else:
            pb_consistency_status = "conflict"
            pb_consistency_note = (
                "⚠️ KBV-Einheiten/Plausibilität widersprüchlich: Das aus "
                "Kurs und Buchwert je Aktie berechnete KBV weicht um mehr "
                "als 20 % vom separat gemeldeten Yahoo-KBV ab. Deshalb wird "
                "das KBV nicht als belastbare Kennzahl angezeigt und nicht "
                "für eine Bewertung verwendet."
            )

    else:
        pb_consistency_note = (
            "KBV konnte zwar aus Kurs und Buchwert je Aktie berechnet werden, "
            "aber ein zweiter Yahoo-KBV-Anker fehlt. Der Wert wird deshalb "
            "nicht als belastbar angezeigt und nicht für eine Bewertung verwendet."
        )

    # -----------------------------------------------------
    # KGV-Referenzen: reine Datenbasis, keine Bewertung.
    # -----------------------------------------------------
    calculated_forward_pe = None
    if (
        price_financial is not None
        and price_financial > 0
        and forward_eps is not None
        and forward_eps > 0
    ):
        calculated_forward_pe = (
            price_financial / forward_eps
        )

    calculated_trailing_pe = None
    if (
        price_financial is not None
        and price_financial > 0
        and trailing_eps is not None
        and trailing_eps > 0
    ):
        calculated_trailing_pe = (
            price_financial / trailing_eps
        )

    # -----------------------------------------------------
    # Dividendenrendite: Yahoo liefert je nach Feld/Version
    # teils Verhältniswerte, teils bereits Prozentzahlen.
    # Wir normalisieren nur, wenn die Darstellung eindeutig
    # oder durch DividendRate/Kurs plausibilisiert ist.
    # Bei unklaren/absurden Werten bleibt die Kennzahl leer.
    # -----------------------------------------------------
    calculated_dividend_yield = None
    if (
        dividend_rate is not None
        and dividend_rate >= 0
        and price_financial is not None
        and price_financial > 0
    ):
        candidate = dividend_rate / price_financial
        if 0 <= candidate <= 0.25:
            calculated_dividend_yield = candidate

    def dividend_yield_candidates(raw_value):
        value = safe_float(raw_value)
        if value is None or value < 0:
            return []

        candidates = []

        # Eindeutiger Verhältniswert: z. B. 0.074 = 7.4 %.
        if value <= 0.25:
            candidates.append((
                "ratio",
                value
            ))

        # Mögliche bereits-prozentuale Yahoo-Darstellung:
        # z. B. 7.41 = 7.41 % -> 0.0741.
        if value <= 25.0:
            percent_candidate = value / 100.0
            if percent_candidate <= 0.25:
                candidates.append((
                    "percent",
                    percent_candidate
                ))

        return candidates

    raw_yield_candidates = dividend_yield_candidates(
        raw_dividend_yield
    )
    trailing_yield_candidates = dividend_yield_candidates(
        trailing_annual_dividend_yield
    )

    dividend_yield = None
    dividend_yield_source = None
    dividend_yield_note = None

    # Primär: DividendRate/Kurs als unabhängiger Plausibilitätsanker.
    if calculated_dividend_yield is not None:
        all_candidates = (
            raw_yield_candidates
            + trailing_yield_candidates
        )

        matching_candidates = []
        for candidate_type, candidate_value in all_candidates:
            absolute_difference = abs(
                candidate_value
                - calculated_dividend_yield
            )
            relative_difference = (
                absolute_difference
                / max(
                    calculated_dividend_yield,
                    0.01
                )
            )

            if (
                absolute_difference <= 0.005
                or relative_difference <= 0.20
            ):
                matching_candidates.append((
                    candidate_type,
                    candidate_value
                ))

        if matching_candidates:
            dividend_yield = calculated_dividend_yield
            dividend_yield_source = (
                "DividendRate/Kurs + Yahoo-Rendite plausibilisiert"
            )

            used_percent_format = any(
                candidate_type == "percent"
                for candidate_type, _ in matching_candidates
            )

            if used_percent_format:
                dividend_yield_note = (
                    "Yahoo liefert die Dividendenrendite in diesem Fall "
                    "offenbar bereits als Prozentzahl. Die Anzeige wurde "
                    "nicht blind mit 100 multipliziert, sondern über "
                    "Dividendenrate/Kurs plausibilisiert und auf einen "
                    "einheitlichen Verhältniswert normalisiert."
                )
            else:
                dividend_yield_note = (
                    "Dividendenrendite wurde über Dividendenrate/Kurs "
                    "plausibilisiert."
                )

        elif (
            raw_dividend_yield is None
            and trailing_annual_dividend_yield is None
        ):
            dividend_yield = calculated_dividend_yield
            dividend_yield_source = "DividendRate/Kurs"
            dividend_yield_note = (
                "Yahoo liefert keine separate Dividendenrendite. Die "
                "Rendite wird transparent aus Yahoo-Dividendenrate und "
                "dem für Verhältniskennzahlen angeglichenen Kurs berechnet."
            )

        else:
            dividend_yield_note = (
                "⚠️ Dividendenrendite nicht belastbar: Die Yahoo-Rendite "
                "passt weder als Verhältniswert noch als Prozentdarstellung "
                "ausreichend zur Dividendenrate/Kurs-Plausibilisierung. "
                "Der Wert wird deshalb als fehlend behandelt."
            )

    # Ohne DividendRate/Kurs nur eindeutig plausible Verhältniswerte zulassen.
    elif (
        raw_dividend_yield is not None
        and 0 <= raw_dividend_yield <= 0.25
    ):
        dividend_yield = raw_dividend_yield
        dividend_yield_source = "Yahoo dividendYield"
        dividend_yield_note = (
            "Yahoo-Dividendenrendite liegt als plausibler Verhältniswert vor."
        )

    elif (
        raw_dividend_yield is not None
        or trailing_annual_dividend_yield is not None
    ):
        dividend_yield_note = (
            "⚠️ Dividendenrendite nicht belastbar: Die Yahoo-Darstellung "
            "ist ohne einen unabhängigen Dividendenrate/Kurs-Anker nicht "
            "eindeutig als Verhältnis- oder Prozentwert interpretierbar. "
            "Es wird nicht geraten oder automatisch durch 100 geteilt."
        )

    # -----------------------------------------------------
    # Ausschüttungsquote: auffällige Werte markieren,
    # aber niemals automatisch verändern.
    # -----------------------------------------------------
    payout_ratio_note = None
    if payout_ratio is not None:
        if payout_ratio > 1.0:
            payout_ratio_note = (
                "⚠️ Ausschüttungsquote über 100 % erkannt. Der Yahoo-Wert "
                "wird unverändert angezeigt, aber nicht als normal oder "
                "nachhaltig interpretiert und nicht automatisch korrigiert."
            )
        elif payout_ratio < 0:
            payout_ratio_note = (
                "⚠️ Negative Ausschüttungsquote erkannt. Der Wert wird "
                "unverändert angezeigt und nicht automatisch interpretiert."
            )

    anchor_values = [
        roe,
        book_value,
        pb_display_value,
        calculated_forward_pe
    ]
    available_anchors = sum(
        value is not None
        for value in anchor_values
    )

    readiness = (
        "Teilweise"
        if available_anchors >= 3
        else "Unvollständig"
    )

    return {
        "applicable": True,
        "price_financial": price_financial,
        "book_value_per_share": book_value,
        "roe": roe,
        "dividend_yield": dividend_yield,
        "dividend_yield_raw": raw_dividend_yield,
        "dividend_yield_source": dividend_yield_source,
        "dividend_yield_note": dividend_yield_note,
        "dividend_rate": dividend_rate,
        "payout_ratio": payout_ratio,
        "payout_ratio_note": payout_ratio_note,
        "calculated_price_to_book": calculated_price_to_book,
        "display_price_to_book": pb_display_value,
        "yahoo_price_to_book": yahoo_price_to_book,
        "pb_consistency_status": pb_consistency_status,
        "calculated_forward_pe": calculated_forward_pe,
        "calculated_trailing_pe": calculated_trailing_pe,
        "pb_consistency_note": pb_consistency_note,
        "readiness": readiness,
        "core_earnings_available": False,
        "solvency_capital_available": False,
        "note": (
            "Versicherungs-Sondermodell V1 bleibt ein reiner Daten- und "
            "Plausibilitätsblock. Dividendenrendite und KBV werden nur "
            "angezeigt, wenn ihre Einheit/Datenbasis ausreichend plausibel "
            "ist. Core Earnings und Solvency-/Kapitalquote werden in der "
            "aktuellen Datenquelle nicht separat geladen und deshalb nicht "
            "geschätzt oder durch andere Kennzahlen ersetzt. Noch keine "
            "Versicherungspunkte, kein Bewertungs-Multiple und kein Fair Value."
        )
    }


# =========================================================
# Banken-Sondermodell V1 – Datenbasis / Plausibilitätscheck
# =========================================================

def build_bank_special_model(
    company_type,
    info,
    price,
    currency_context
):
    """
    Conservative bank-specific data block.

    It does not create a new score, valuation multiple or fair value.
    It only prepares bank-relevant Yahoo fields and checks whether
    book-value and P/E references are unit-consistent. RoTE, tangible
    book value and CET1 are not estimated or replaced by proxies.
    """
    type_name = str(
        company_type.get("type", "")
    ).lower()

    if "bank" not in type_name:
        return {
            "applicable": False
        }

    quote_price = safe_float(price)
    quote_to_financial = safe_float(
        currency_context.get(
            "quote_to_financial_factor",
            1.0
        )
    )

    if quote_to_financial is None:
        quote_to_financial = 1.0

    price_financial = (
        quote_price * quote_to_financial
        if quote_price is not None
        else None
    )

    book_value = safe_float(
        info.get("bookValue")
    )
    roe = safe_float(
        info.get("returnOnEquity")
    )
    trailing_eps = safe_float(
        info.get("trailingEps")
    )
    forward_eps = safe_float(
        info.get("forwardEps")
    )
    yahoo_price_to_book = safe_float(
        info.get("priceToBook")
    )
    yahoo_forward_pe = safe_float(
        info.get("forwardPE")
    )
    if yahoo_forward_pe is None:
        yahoo_forward_pe = safe_float(
            info.get("forwardPe")
        )

    # -----------------------------------------------------
    # KBV: Kurs/Buchwert nur dann anzeigen, wenn Yahoo-KBV
    # als zweiter Anker innerhalb 20 % bestätigt.
    # -----------------------------------------------------
    calculated_price_to_book = None
    if (
        price_financial is not None
        and price_financial > 0
        and book_value is not None
        and book_value > 0
    ):
        calculated_price_to_book = (
            price_financial / book_value
        )

    pb_display_value = None
    pb_consistency_status = "unverified"
    pb_consistency_note = None

    if calculated_price_to_book is None:
        pb_consistency_note = (
            "KBV konnte aus Kurs und Buchwert je Aktie nicht "
            "belastbar berechnet werden. Es wird kein Wert geschätzt."
        )

    elif (
        yahoo_price_to_book is not None
        and yahoo_price_to_book > 0
    ):
        pb_deviation = abs(
            calculated_price_to_book
            / yahoo_price_to_book
            - 1.0
        )

        if pb_deviation <= 0.20:
            pb_display_value = calculated_price_to_book
            pb_consistency_status = "plausible"
            pb_consistency_note = (
                "KBV-Plausibilitätscheck bestanden: Das aus Kurs und "
                "Buchwert je Aktie berechnete KBV liegt innerhalb von "
                "20 % des separat gemeldeten Yahoo-KBV. Der Wert bleibt "
                "nur eine Datenbasis und erzeugt noch keine Bankbewertung."
            )
        else:
            pb_consistency_status = "conflict"
            pb_consistency_note = (
                "⚠️ KBV-Einheiten/Plausibilität widersprüchlich: Das aus "
                "Kurs und Buchwert je Aktie berechnete KBV weicht um mehr "
                "als 20 % vom separat gemeldeten Yahoo-KBV ab. Deshalb wird "
                "das KBV nicht als belastbare Kennzahl angezeigt."
            )

    else:
        pb_consistency_note = (
            "KBV konnte zwar aus Kurs und Buchwert je Aktie berechnet werden, "
            "aber ein zweiter Yahoo-KBV-Anker fehlt. Der Wert wird deshalb "
            "nicht als belastbar angezeigt und nicht für eine Bewertung verwendet."
        )

    # -----------------------------------------------------
    # Forward-KGV: ebenfalls nur als Referenz und nur bei
    # ausreichender Übereinstimmung mit Yahoo-forwardPE.
    # -----------------------------------------------------
    calculated_forward_pe = None
    if (
        price_financial is not None
        and price_financial > 0
        and forward_eps is not None
        and forward_eps > 0
    ):
        calculated_forward_pe = (
            price_financial / forward_eps
        )

    forward_pe_display = None
    forward_pe_status = "unverified"
    forward_pe_note = None

    if calculated_forward_pe is None:
        forward_pe_note = (
            "Forward-KGV konnte aus Kurs und Forward-EPS nicht belastbar "
            "berechnet werden. Es wird kein Wert geschätzt."
        )

    elif (
        yahoo_forward_pe is not None
        and yahoo_forward_pe > 0
    ):
        pe_deviation = abs(
            calculated_forward_pe
            / yahoo_forward_pe
            - 1.0
        )

        if pe_deviation <= 0.20:
            forward_pe_display = calculated_forward_pe
            forward_pe_status = "plausible"
            forward_pe_note = (
                "Forward-KGV-Plausibilitätscheck bestanden: Kurs/Forward-EPS "
                "und Yahoo-forwardPE liegen innerhalb von 20 % beieinander. "
                "Das KGV bleibt eine reine Referenz und erzeugt noch keine Bewertung."
            )
        else:
            forward_pe_status = "conflict"
            forward_pe_note = (
                "⚠️ Forward-KGV nicht belastbar: Das aus Kurs und Forward-EPS "
                "berechnete KGV weicht um mehr als 20 % vom Yahoo-forwardPE ab. "
                "Der Wert wird deshalb nicht für das Sondermodell verwendet."
            )

    else:
        forward_pe_note = (
            "Forward-KGV konnte berechnet werden, aber ein separater Yahoo-"
            "forwardPE-Anker fehlt. Der Wert wird deshalb nicht als belastbar "
            "angezeigt und nicht für eine Bewertung verwendet."
        )

    calculated_trailing_pe = None
    if (
        price_financial is not None
        and price_financial > 0
        and trailing_eps is not None
        and trailing_eps > 0
    ):
        calculated_trailing_pe = (
            price_financial / trailing_eps
        )

    anchor_values = [
        roe,
        pb_display_value,
        forward_pe_display
    ]
    available_anchors = sum(
        value is not None
        for value in anchor_values
    )

    readiness = (
        "Teilweise"
        if available_anchors >= 2
        else "Unvollständig"
    )

    return {
        "applicable": True,
        "price_financial": price_financial,
        "book_value_per_share": book_value,
        "roe": roe,
        "calculated_price_to_book": calculated_price_to_book,
        "display_price_to_book": pb_display_value,
        "yahoo_price_to_book": yahoo_price_to_book,
        "pb_consistency_status": pb_consistency_status,
        "pb_consistency_note": pb_consistency_note,
        "calculated_forward_pe": calculated_forward_pe,
        "display_forward_pe": forward_pe_display,
        "yahoo_forward_pe": yahoo_forward_pe,
        "forward_pe_status": forward_pe_status,
        "forward_pe_note": forward_pe_note,
        "calculated_trailing_pe": calculated_trailing_pe,
        "readiness": readiness,
        "rote_available": False,
        "tangible_book_value_available": False,
        "cet1_available": False,
        "note": (
            "Banken-Sondermodell V1 bleibt ein reiner Daten- und "
            "Plausibilitätsblock. ROE, Buchwert/KBV und Forward-KGV werden "
            "nur als belastbare Basiskennzahlen angezeigt. RoTE, Tangible "
            "Book Value und CET1 werden in der aktuellen Datenquelle nicht "
            "separat belastbar geladen und deshalb nicht geschätzt oder durch "
            "ROE bzw. normalen Buchwert ersetzt. Noch keine Bankpunkte, kein "
            "Bewertungs-Multiple und kein Fair Value."
        )
    }


# =========================================================
# Midstream-Sondermodell V1 – Datenbasis / Plausibilitätscheck
# =========================================================

def build_midstream_special_model(
    company_type,
    info,
    price,
    currency_context
):
    """
    Conservative midstream-specific data block.

    It does not create a score, valuation multiple or fair value.
    It only prepares EV/EBITDA and leverage references from Yahoo
    and keeps distributable cash flow separate from standard FCF.
    Distributable cash flow is not estimated from FCF or OCF.
    """
    type_name = str(
        company_type.get("type", "")
    ).lower()

    if "midstream" not in type_name:
        return {
            "applicable": False
        }

    enterprise_value = safe_float(
        info.get("enterpriseValue")
    )
    ebitda = safe_float(
        info.get("ebitda")
    )
    yahoo_ev_to_ebitda = safe_float(
        info.get("enterpriseToEbitda")
    )
    total_cash = safe_float(
        info.get("totalCash")
    )
    total_debt = safe_float(
        info.get("totalDebt")
    )
    operating_cashflow = safe_float(
        info.get("operatingCashflow")
    )
    free_cashflow_reference = safe_float(
        info.get("freeCashflow")
    )

    # -----------------------------------------------------
    # EV/EBITDA: nur anzeigen, wenn die selbst berechnete
    # Kennzahl und Yahoo-enterpriseToEbitda ausreichend
    # gut zusammenpassen. So vermeiden wir Einheitenfehler.
    # -----------------------------------------------------
    calculated_ev_to_ebitda = None
    if (
        enterprise_value is not None
        and enterprise_value > 0
        and ebitda is not None
        and ebitda > 0
    ):
        calculated_ev_to_ebitda = (
            enterprise_value / ebitda
        )

    ev_to_ebitda_display = None
    ev_to_ebitda_status = "unverified"
    ev_to_ebitda_note = None

    if calculated_ev_to_ebitda is None:
        ev_to_ebitda_note = (
            "EV/EBITDA konnte aus Enterprise Value und EBITDA nicht "
            "belastbar berechnet werden. Es wird kein Wert geschätzt."
        )

    elif (
        yahoo_ev_to_ebitda is not None
        and yahoo_ev_to_ebitda > 0
    ):
        ev_deviation = abs(
            calculated_ev_to_ebitda
            / yahoo_ev_to_ebitda
            - 1.0
        )

        if ev_deviation <= 0.20:
            ev_to_ebitda_display = calculated_ev_to_ebitda
            ev_to_ebitda_status = "plausible"
            ev_to_ebitda_note = (
                "EV/EBITDA-Plausibilitätscheck bestanden: Die aus "
                "Enterprise Value und EBITDA berechnete Kennzahl liegt "
                "innerhalb von 20 % des separat gemeldeten Yahoo-"
                "enterpriseToEbitda. Der Wert bleibt eine reine "
                "Datenbasis und erzeugt noch keine Bewertung."
            )
        else:
            ev_to_ebitda_status = "conflict"
            ev_to_ebitda_note = (
                "⚠️ EV/EBITDA nicht belastbar: Die selbst berechnete "
                "Kennzahl weicht um mehr als 20 % vom separat gemeldeten "
                "Yahoo-enterpriseToEbitda ab. Deshalb wird EV/EBITDA "
                "nicht als belastbare Referenz angezeigt."
            )

    else:
        ev_to_ebitda_note = (
            "EV/EBITDA konnte zwar aus Enterprise Value und EBITDA "
            "berechnet werden, aber ein separater Yahoo-Anker fehlt. "
            "Der Wert wird deshalb nicht als belastbar angezeigt."
        )

    # -----------------------------------------------------
    # Verschuldung: Midstream wird über EBITDA statt über
    # normalen FCF betrachtet. Die Kennzahl bleibt in V1
    # reine Datenbasis und erhält keine Punkte.
    # -----------------------------------------------------
    net_debt = None
    if (
        total_debt is not None
        and total_cash is not None
    ):
        net_debt = total_debt - total_cash

    net_debt_to_ebitda = None
    if (
        net_debt is not None
        and net_debt > 0
        and ebitda is not None
        and ebitda > 0
    ):
        net_debt_to_ebitda = (
            net_debt / ebitda
        )

    available_anchors = sum(
        value is not None
        for value in [
            ev_to_ebitda_display,
            net_debt_to_ebitda,
            operating_cashflow
        ]
    )

    readiness = (
        "Teilweise"
        if available_anchors >= 2
        else "Unvollständig"
    )

    return {
        "applicable": True,
        "enterprise_value": enterprise_value,
        "ebitda": ebitda,
        "calculated_ev_to_ebitda": calculated_ev_to_ebitda,
        "display_ev_to_ebitda": ev_to_ebitda_display,
        "yahoo_ev_to_ebitda": yahoo_ev_to_ebitda,
        "ev_to_ebitda_status": ev_to_ebitda_status,
        "ev_to_ebitda_note": ev_to_ebitda_note,
        "total_cash": total_cash,
        "total_debt": total_debt,
        "net_debt": net_debt,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "operating_cashflow": operating_cashflow,
        "free_cashflow_reference": free_cashflow_reference,
        "distributable_cashflow_available": False,
        "readiness": readiness,
        "note": (
            "Midstream-Sondermodell V1 bleibt ein reiner Daten- und "
            "Plausibilitätsblock. EV/EBITDA und Netto-Schulden/EBITDA "
            "werden nur als Referenz gezeigt. Distributable Cash Flow "
            "wird in der aktuellen Datenquelle nicht separat belastbar "
            "geladen und deshalb nicht aus Yahoo-Free-Cashflow oder "
            "Operating Cashflow abgeleitet. Noch keine Midstream-Punkte, "
            "kein Bewertungs-Multiple und kein Fair Value."
        )
    }


# =========================================================
# Autohersteller-Sondermodell V1 – Datenbasis / Plausibilitätscheck
# =========================================================

def build_auto_special_model(
    company_type,
    info,
    eps_normalization,
    currency_context
):
    """
    Conservative auto-manufacturer data block.

    It does not create a score, valuation multiple or fair value.
    Consolidated Yahoo cash flow and debt can mix the industrial
    automotive business with captive financial services, so V1
    never treats them as automotive industrial FCF/net debt.
    """
    type_name = str(
        company_type.get("type", "")
    ).lower()

    if "autohersteller" not in type_name:
        return {
            "applicable": False
        }

    enterprise_value = safe_float(
        info.get("enterpriseValue")
    )
    ebitda = safe_float(
        info.get("ebitda")
    )
    yahoo_ev_to_ebitda = safe_float(
        info.get("enterpriseToEbitda")
    )
    operating_cashflow = safe_float(
        info.get("operatingCashflow")
    )
    free_cashflow_reference = safe_float(
        info.get("freeCashflow")
    )
    total_cash_reference = safe_float(
        info.get("totalCash")
    )
    total_debt_reference = safe_float(
        info.get("totalDebt")
    )

    normalized_eps = None
    eps_method = None
    eps_confidence = None
    if isinstance(eps_normalization, dict):
        normalized_eps = safe_float(
            eps_normalization.get("normalized_eps")
        )
        eps_method = eps_normalization.get("method")
        eps_confidence = eps_normalization.get("confidence")

    calculated_ev_to_ebitda = None
    if (
        enterprise_value is not None
        and enterprise_value > 0
        and ebitda is not None
        and ebitda > 0
    ):
        calculated_ev_to_ebitda = (
            enterprise_value / ebitda
        )

    display_ev_to_ebitda = None
    ev_to_ebitda_status = "unverified"
    ev_to_ebitda_note = None

    if calculated_ev_to_ebitda is None:
        ev_to_ebitda_note = (
            "EV/EBITDA konnte aus Enterprise Value und EBITDA nicht "
            "belastbar berechnet werden. Es wird kein Wert geschätzt."
        )
    elif (
        yahoo_ev_to_ebitda is not None
        and yahoo_ev_to_ebitda > 0
    ):
        deviation = abs(
            calculated_ev_to_ebitda
            / yahoo_ev_to_ebitda
            - 1.0
        )
        if deviation <= 0.20:
            display_ev_to_ebitda = calculated_ev_to_ebitda
            ev_to_ebitda_status = "plausible"
            ev_to_ebitda_note = (
                "EV/EBITDA-Plausibilitätscheck bestanden: Die aus "
                "Enterprise Value und EBITDA berechnete Kennzahl liegt "
                "innerhalb von 20 % des separat gemeldeten Yahoo-"
                "enterpriseToEbitda. Bei Autoherstellern bleibt dieser "
                "Wert trotzdem nur Konzern-Kontext, weil Finanzdienstleistungen "
                "die Konzernkennzahlen beeinflussen können."
            )
        else:
            ev_to_ebitda_status = "conflict"
            ev_to_ebitda_note = (
                "⚠️ EV/EBITDA nicht belastbar: Die selbst berechnete "
                "Kennzahl weicht um mehr als 20 % vom separat gemeldeten "
                "Yahoo-enterpriseToEbitda ab. Deshalb wird sie nicht als "
                "belastbare Referenz angezeigt."
            )
    else:
        ev_to_ebitda_note = (
            "EV/EBITDA konnte zwar aus Enterprise Value und EBITDA "
            "berechnet werden, aber ein separater Yahoo-Anker fehlt. "
            "Der Wert wird deshalb nicht als belastbar angezeigt."
        )

    available_anchors = sum(
        value is not None
        for value in [
            normalized_eps,
            display_ev_to_ebitda,
            operating_cashflow
        ]
    )

    readiness = (
        "Teilweise"
        if available_anchors >= 2
        else "Unvollständig"
    )

    return {
        "applicable": True,
        "normalized_eps": normalized_eps,
        "eps_method": eps_method,
        "eps_confidence": eps_confidence,
        "enterprise_value": enterprise_value,
        "ebitda": ebitda,
        "calculated_ev_to_ebitda": calculated_ev_to_ebitda,
        "display_ev_to_ebitda": display_ev_to_ebitda,
        "yahoo_ev_to_ebitda": yahoo_ev_to_ebitda,
        "ev_to_ebitda_status": ev_to_ebitda_status,
        "ev_to_ebitda_note": ev_to_ebitda_note,
        "operating_cashflow": operating_cashflow,
        "free_cashflow_reference": free_cashflow_reference,
        "total_cash_reference": total_cash_reference,
        "total_debt_reference": total_debt_reference,
        "automotive_fcf_available": False,
        "industrial_net_debt_available": False,
        "financial_services_split_available": False,
        "readiness": readiness,
        "note": (
            "Autohersteller-Sondermodell V1 bleibt ein reiner Daten- und "
            "Plausibilitätsblock. Yahoo-Free-Cashflow, Cash und Schulden "
            "werden bei Autoherstellern nicht als Automotive-Industrie-FCF "
            "oder Industrie-Netto-Schulden interpretiert, weil konsolidierte "
            "Werte häufig das Finanzdienstleistungsgeschäft enthalten. "
            "Automotive Free Cash Flow, Industrie-Netto-Cash/-Schulden und "
            "der Finanzdienstleistungs-Anteil werden nicht geschätzt. Noch "
            "keine Auto-Punkte, kein Bewertungs-Multiple und kein Fair Value."
        )
    }


# =========================================================
# REIT-/Immobilien-Sondermodell V1 – Datenbasis / Plausibilitätscheck
# =========================================================

def build_reit_special_model(
    company_type,
    info,
    price,
    currency_context
):
    """
    Conservative REIT / real-estate data block.

    It does not create a score, valuation multiple or fair value.
    FFO/AFFO are only used when Yahoo exposes them directly. V1 never
    reconstructs FFO/AFFO from net income, depreciation, standard FCF
    or operating cash flow. Leverage is shown via EBITDA-based context.
    """
    type_name = str(
        company_type.get("type", "")
    ).lower()

    if (
        "reit" not in type_name
        and "immobilien" not in type_name
    ):
        return {
            "applicable": False
        }

    quote_price = safe_float(price)
    quote_to_financial = safe_float(
        currency_context.get(
            "quote_to_financial_factor",
            1.0
        )
    )

    if quote_to_financial is None:
        quote_to_financial = 1.0

    price_financial = (
        quote_price * quote_to_financial
        if quote_price is not None
        else None
    )

    def first_direct_value(keys):
        for key in keys:
            value = safe_float(info.get(key))
            if value is not None:
                return value, key
        return None, None

    # Direct Yahoo fields only. No FFO/AFFO reconstruction.
    ffo_total, ffo_total_source = first_direct_value([
        "fundsFromOperations",
        "fundsFromOperationsTTM",
        "ffo"
    ])
    ffo_per_share, ffo_per_share_source = first_direct_value([
        "fundsFromOperationsPerShare",
        "ffoPerShare",
        "trailingFfoPerShare"
    ])
    affo_total, affo_total_source = first_direct_value([
        "adjustedFundsFromOperations",
        "adjustedFundsFromOperationsTTM",
        "affo"
    ])
    affo_per_share, affo_per_share_source = first_direct_value([
        "adjustedFundsFromOperationsPerShare",
        "affoPerShare",
        "trailingAffoPerShare"
    ])

    price_to_ffo = None
    if (
        price_financial is not None
        and price_financial > 0
        and ffo_per_share is not None
        and ffo_per_share > 0
    ):
        price_to_ffo = (
            price_financial / ffo_per_share
        )

    price_to_affo = None
    if (
        price_financial is not None
        and price_financial > 0
        and affo_per_share is not None
        and affo_per_share > 0
    ):
        price_to_affo = (
            price_financial / affo_per_share
        )

    if ffo_per_share is not None:
        ffo_note = (
            "FFO je Aktie wurde als direkt gemeldetes Yahoo-Feld erkannt. "
            "P/FFO wird daraus transparent als reine Datenreferenz berechnet; "
            "es entsteht noch keine Bewertung."
        )
    else:
        ffo_note = (
            "FFO je Aktie ist in der aktuellen Yahoo-Datenquelle nicht "
            "separat belastbar verfügbar. Es wird nicht aus Nettogewinn, "
            "Abschreibungen, Standard-FCF oder Operating Cashflow rekonstruiert."
        )

    if affo_per_share is not None:
        affo_note = (
            "AFFO je Aktie wurde als direkt gemeldetes Yahoo-Feld erkannt. "
            "P/AFFO wird daraus transparent als reine Datenreferenz berechnet; "
            "es entsteht noch keine Bewertung."
        )
    else:
        affo_note = (
            "AFFO je Aktie ist in der aktuellen Yahoo-Datenquelle nicht "
            "separat belastbar verfügbar. Es wird nicht aus FFO, Standard-FCF "
            "oder anderen Kennzahlen geschätzt."
        )

    enterprise_value = safe_float(
        info.get("enterpriseValue")
    )
    ebitda = safe_float(
        info.get("ebitda")
    )
    yahoo_ev_to_ebitda = safe_float(
        info.get("enterpriseToEbitda")
    )
    total_cash = safe_float(
        info.get("totalCash")
    )
    total_debt = safe_float(
        info.get("totalDebt")
    )

    calculated_ev_to_ebitda = None
    if (
        enterprise_value is not None
        and enterprise_value > 0
        and ebitda is not None
        and ebitda > 0
    ):
        calculated_ev_to_ebitda = (
            enterprise_value / ebitda
        )

    display_ev_to_ebitda = None
    ev_to_ebitda_status = "unverified"
    ev_to_ebitda_note = None

    if calculated_ev_to_ebitda is None:
        ev_to_ebitda_note = (
            "EV/EBITDA konnte aus Enterprise Value und EBITDA nicht "
            "belastbar berechnet werden. Es wird kein Wert geschätzt."
        )
    elif (
        yahoo_ev_to_ebitda is not None
        and yahoo_ev_to_ebitda > 0
    ):
        deviation = abs(
            calculated_ev_to_ebitda
            / yahoo_ev_to_ebitda
            - 1.0
        )

        if deviation <= 0.20:
            display_ev_to_ebitda = calculated_ev_to_ebitda
            ev_to_ebitda_status = "plausible"
            ev_to_ebitda_note = (
                "EV/EBITDA-Plausibilitätscheck bestanden: Die aus "
                "Enterprise Value und EBITDA berechnete Kennzahl liegt "
                "innerhalb von 20 % des separat gemeldeten Yahoo-"
                "enterpriseToEbitda. Bei REITs bleibt sie nur eine "
                "Verschuldungs-/Unternehmenswert-Referenz und ersetzt "
                "kein P/FFO- oder P/AFFO-Modell."
            )
        else:
            ev_to_ebitda_status = "conflict"
            ev_to_ebitda_note = (
                "⚠️ EV/EBITDA nicht belastbar: Die selbst berechnete "
                "Kennzahl weicht um mehr als 20 % vom separat gemeldeten "
                "Yahoo-enterpriseToEbitda ab. Deshalb wird sie nicht als "
                "belastbare Referenz angezeigt."
            )
    else:
        ev_to_ebitda_note = (
            "EV/EBITDA konnte zwar aus Enterprise Value und EBITDA "
            "berechnet werden, aber ein separater Yahoo-Anker fehlt. "
            "Der Wert wird deshalb nicht als belastbar angezeigt."
        )

    net_debt = None
    if (
        total_debt is not None
        and total_cash is not None
    ):
        net_debt = total_debt - total_cash

    net_debt_to_ebitda = None
    if (
        net_debt is not None
        and net_debt > 0
        and ebitda is not None
        and ebitda > 0
    ):
        net_debt_to_ebitda = (
            net_debt / ebitda
        )

    available_anchors = sum(
        value is not None
        for value in [
            ffo_total,
            ffo_per_share,
            affo_total,
            affo_per_share,
            display_ev_to_ebitda,
            net_debt_to_ebitda
        ]
    )

    readiness = (
        "Teilweise"
        if available_anchors >= 2
        else "Unvollständig"
    )

    return {
        "applicable": True,
        "price_financial": price_financial,
        "ffo_total": ffo_total,
        "ffo_total_source": ffo_total_source,
        "ffo_per_share": ffo_per_share,
        "ffo_per_share_source": ffo_per_share_source,
        "affo_total": affo_total,
        "affo_total_source": affo_total_source,
        "affo_per_share": affo_per_share,
        "affo_per_share_source": affo_per_share_source,
        "price_to_ffo": price_to_ffo,
        "price_to_affo": price_to_affo,
        "ffo_note": ffo_note,
        "affo_note": affo_note,
        "enterprise_value": enterprise_value,
        "ebitda": ebitda,
        "calculated_ev_to_ebitda": calculated_ev_to_ebitda,
        "display_ev_to_ebitda": display_ev_to_ebitda,
        "yahoo_ev_to_ebitda": yahoo_ev_to_ebitda,
        "ev_to_ebitda_status": ev_to_ebitda_status,
        "ev_to_ebitda_note": ev_to_ebitda_note,
        "total_cash": total_cash,
        "total_debt": total_debt,
        "net_debt": net_debt,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "nav_available": False,
        "property_value_available": False,
        "readiness": readiness,
        "note": (
            "REIT-/Immobilien-Sondermodell V1 bleibt ein reiner Daten- und "
            "Plausibilitätsblock. FFO und AFFO werden ausschließlich verwendet, "
            "wenn sie direkt separat verfügbar sind; sie werden nicht aus "
            "Nettogewinn, Abschreibungen, Standard-FCF oder Operating Cashflow "
            "rekonstruiert. NAV/EPRA NTA bzw. Immobilienwerte werden in der "
            "aktuellen Datenquelle nicht separat belastbar geladen und nicht "
            "geschätzt. Noch keine REIT-Punkte, kein Bewertungs-Multiple und "
            "kein Fair Value."
        )
    }


# =========================================================
# Modul 6 – Schritt 1: Bewertungs-Korridor & Fundamental-Multiple
# =========================================================

def get_valuation_corridor(company_type):
    type_name = str(
        company_type.get("type", "")
    ).lower()

    corridors = [
        (
            "halbleiterausrüstung / lithografie",
            22.0,
            32.0,
            "Forward/normalisiertes KGV"
        ),
        (
            "halbleiter / fabless / ai-wachstum",
            22.0,
            35.0,
            "Forward/normalisiertes KGV"
        ),
        (
            "halbleiter / foundry",
            15.0,
            24.0,
            "Forward/normalisiertes KGV"
        ),
        (
            "defense / stark wachsend",
            18.0,
            30.0,
            "KGV auf normalisiertem EPS"
        ),
        (
            "etablierte software / technologie",
            20.0,
            30.0,
            "Normalisiertes/Forward-KGV"
        ),
        (
            "autohersteller / zyklisch",
            6.0,
            10.0,
            "Zyklus-normalisiertes KGV"
        ),
        (
            "rohstoffe / lithium / zyklisch",
            8.0,
            14.0,
            "Zyklus-normalisiertes KGV"
        ),
        (
            "rohstoffe / bergbau / zyklisch",
            7.0,
            12.0,
            "Zyklus-normalisiertes KGV"
        ),
        (
            "öl & gas / zyklisch",
            8.0,
            13.0,
            "Zyklus-normalisiertes KGV"
        ),
        (
            "telekommunikation",
            11.0,
            16.0,
            "Adjusted/normalisiertes KGV"
        ),
        (
            "defensiver konsum",
            18.0,
            26.0,
            "Normalisiertes KGV"
        ),
        (
            "standard-unternehmen",
            12.0,
            24.0,
            "KGV auf normalisiertem EPS"
        ),
        (
            "pharma",
            13.0,
            19.0,
            "Normalisiertes/Business-KGV"
        )
    ]

    for key, lower, upper, method in corridors:
        if key in type_name:
            if key == "standard-unternehmen":
                note = (
                    "Der Standard-Korridor ist bewusst konservativ. "
                    "Die FCF-Kontrolle ist bereits im 100-Punkte-Multiple-"
                    "Score enthalten und wird nicht ein zweites Mal als "
                    "separate Multiple-Anpassung angerechnet."
                )
            else:
                note = (
                    "Der Bewertungs-Korridor wird durch den "
                    "Unternehmenstyp bestimmt."
                )

            return {
                "available": True,
                "lower": lower,
                "upper": upper,
                "method": method,
                "note": note
            }

    special_or_unresolved_terms = [
        "bank",
        "versicherung",
        "reit",
        "immobilien",
        "biotechnologie",
        "untertyp noch nicht eindeutig",
        "versorger",
        "midstream",
        "early-stage mining",
        "projektentwicklung",
        "photonik",
        "elektrische luftfahrt",
        "reifes saas",
        "vertical saas"
    ]

    if any(
        term in type_name
        for term in special_or_unresolved_terms
    ):
        return {
            "available": False,
            "lower": None,
            "upper": None,
            "method": None,
            "note": (
                "Für diesen Unternehmenstyp ist noch kein "
                "ausreichend belastbarer Bewertungs-Korridor "
                "implementiert. Es wird kein Multiple geschätzt."
            )
        }

    return {
        "available": False,
        "lower": None,
        "upper": None,
        "method": None,
        "note": (
            "Für diesen Unternehmenstyp ist noch kein "
            "Bewertungs-Korridor hinterlegt."
        )
    }


def calculate_total_multiple_score(
    growth_score,
    profitability_score,
    fcf_score,
    balance_score
):
    components = [
        growth_score.get("score"),
        profitability_score.get("score"),
        fcf_score.get("score"),
        balance_score.get("score")
    ]

    if any(
        value is None
        for value in components
    ):
        return None

    return sum(components)


def calculate_fundamental_multiple(
    company_type,
    growth_score,
    profitability_score,
    fcf_score,
    balance_score,
    eps_normalization
):
    corridor = get_valuation_corridor(
        company_type
    )

    total_score = calculate_total_multiple_score(
        growth_score,
        profitability_score,
        fcf_score,
        balance_score
    )

    if not corridor["available"]:
        return {
            "available": False,
            "score": total_score,
            "corridor": corridor,
            "multiple": None,
            "earnings_basis_usable": (
                has_usable_positive_earnings_basis(
                    eps_normalization
                )
            ),
            "note": corridor["note"]
        }

    method_name = str(
        corridor.get("method", "")
    ).lower()

    earnings_basis_usable = (
        has_usable_positive_earnings_basis(
            eps_normalization
        )
    )

    if (
        "kgv" in method_name
        and not earnings_basis_usable
    ):
        blocked_corridor = {
            "available": False,
            "lower": None,
            "upper": None,
            "method": None,
            "note": (
                "KGV-Bewertung gesperrt: Es liegt keine "
                "positive und verwertbare normalisierte "
                "Gewinnbasis vor. Deshalb werden weder "
                "KGV-Korridor noch Fundamental-Multiple "
                "berechnet."
            )
        }

        return {
            "available": False,
            "score": total_score,
            "corridor": blocked_corridor,
            "multiple": None,
            "earnings_basis_usable": False,
            "note": blocked_corridor["note"]
        }

    if total_score is None:
        return {
            "available": False,
            "score": None,
            "corridor": corridor,
            "multiple": None,
            "earnings_basis_usable": earnings_basis_usable,
            "note": (
                "Der vollständige Multiple Score ist nicht "
                "verfügbar. Fehlende Komponenten werden nicht "
                "hochgerechnet; daher wird kein Fundamental-"
                "Multiple berechnet."
            )
        }

    lower = corridor["lower"]
    upper = corridor["upper"]

    multiple = (
        lower
        + (upper - lower)
        * total_score / 100.0
    )

    return {
        "available": True,
        "score": total_score,
        "corridor": corridor,
        "multiple": multiple,
        "earnings_basis_usable": earnings_basis_usable,
        "note": (
            "Das Fundamental-Multiple wird linear innerhalb "
            "des unternehmenstypischen Korridors aus dem "
            "Multiple Score abgeleitet. Der Peer-Check bleibt "
            "ein separater Realitätscheck; der Fair Value wird "
            "erst im nachfolgenden Fair-Value-Schritt berechnet."
        )
    }


# =========================================================
# Modul 6 – Schritt 2A: Peer-Gruppe festlegen
# =========================================================

def get_peer_group(company_type, symbol):
    type_name = str(
        company_type.get("type", "")
    ).lower()

    peer_groups = [
        (
            "halbleiterausrüstung / lithografie",
            [
                ("AMAT", "Applied Materials"),
                ("LRCX", "Lam Research"),
                ("KLAC", "KLA Corporation"),
            ]
        ),
        (
            "halbleiter / fabless / ai-wachstum",
            [
                ("AVGO", "Broadcom"),
                ("AMD", "Advanced Micro Devices"),
                ("QCOM", "Qualcomm"),
                ("MRVL", "Marvell Technology"),
            ]
        ),
        (
            "halbleiter / foundry",
            [
                ("UMC", "United Microelectronics"),
                ("GFS", "GlobalFoundries"),
            ]
        ),
        (
            "defense / stark wachsend",
            [
                ("BA.L", "BAE Systems"),
                ("LDO.MI", "Leonardo"),
                ("HO.PA", "Thales"),
                ("SAAB-B.ST", "Saab"),
            ]
        ),
        (
            "etablierte software / technologie",
            [
                ("GOOGL", "Alphabet"),
                ("ORCL", "Oracle"),
                ("SAP", "SAP"),
                ("CRM", "Salesforce"),
                ("IBM", "IBM"),
            ]
        ),
        (
            "rohstoffe / lithium / zyklisch",
            [
                ("SQM", "Sociedad Química y Minera"),
                ("1772.HK", "Ganfeng Lithium"),
                ("002466.SZ", "Tianqi Lithium"),
            ]
        ),
        (
            "autohersteller / zyklisch",
            [
                ("BMW.DE", "BMW"),
                ("MBG.DE", "Mercedes-Benz Group"),
                ("STLAM.MI", "Stellantis"),
                ("7203.T", "Toyota Motor"),
            ]
        ),
        (
            "öl & gas / zyklisch",
            [
                ("SHEL", "Shell"),
                ("XOM", "Exxon Mobil"),
                ("CVX", "Chevron"),
                ("TTE", "TotalEnergies"),
            ]
        ),
        (
            "telekommunikation",
            [
                ("VZ", "Verizon"),
                ("T", "AT&T"),
                ("VOD.L", "Vodafone"),
                ("ORAN", "Orange"),
            ]
        ),
        (
            "defensiver konsum",
            [
                ("PG", "Procter & Gamble"),
                ("KO", "Coca-Cola"),
                ("PEP", "PepsiCo"),
                ("NESN.SW", "Nestlé"),
            ]
        ),
        (
            "pharma",
            [
                ("NVS", "Novartis"),
                ("GSK", "GSK"),
                ("AZN", "AstraZeneca"),
                ("SNY", "Sanofi"),
            ]
        ),
    ]

    own_symbol = str(symbol or "").upper()

    for key, peers in peer_groups:
        if key in type_name:
            filtered = [
                {
                    "symbol": peer_symbol,
                    "name": peer_name
                }
                for peer_symbol, peer_name in peers
                if peer_symbol.upper() != own_symbol
            ]

            return {
                "available": len(filtered) > 0,
                "peers": filtered,
                "count": len(filtered),
                "note": (
                    "Peer-Gruppe automatisch aus dem "
                    "Unternehmenstyp ausgewählt. In Schritt 2A "
                    "werden noch keine Peer-Kennzahlen geladen "
                    "und das Fundamental-Multiple bleibt "
                    "unverändert."
                )
            }

    if "standard-unternehmen" in type_name:
        return {
            "available": False,
            "peers": [],
            "count": 0,
            "note": (
                "Standard-Unternehmen bilden keine homogene Peer-Gruppe. "
                "Deshalb wird ohne branchenspezifische Zuordnung keine "
                "automatische Peer-Anpassung erzwungen. Das Fundamental-"
                "Multiple bleibt unverändert und kann als Fair-Value-Basis "
                "verwendet werden."
            )
        }

    return {
        "available": False,
        "peers": [],
        "count": 0,
        "note": (
            "Für diesen Unternehmenstyp ist noch keine "
            "automatische Peer-Gruppe hinterlegt."
        )
    }


# =========================================================
# Modul 6 – Schritt 2B: Peer-Daten, Median & ±5-%-Kontrolle
# =========================================================

def peer_forward_pe_is_supported(company_type):
    type_name = str(
        company_type.get("type", "")
    ).lower()

    # Für zyklische Unternehmen ist ein einfaches aktuelles
    # Forward-KGV als Peer-Maßstab nicht belastbar genug.
    unsupported_terms = [
        "zyklisch",
        "autohersteller",
        "rohstoffe",
        "lithium",
        "öl & gas",
        "midstream",
        "bank",
        "versicherung",
        "reit",
        "immobilien",
        "biotechnologie",
        "untertyp noch nicht eindeutig",
        "early-stage",
        "projektentwicklung",
        "photonik",
        "elektrische luftfahrt",
        "reifes saas",
        "vertical saas"
    ]

    return not any(
        term in type_name
        for term in unsupported_terms
    )


@st.cache_data(ttl=900)
def load_peer_forward_pe(peer_symbol, cache_version):

    try:
        peer_ticker = yf.Ticker(peer_symbol)
        peer_info = peer_ticker.info or {}

        forward_pe = peer_info.get("forwardPE")

        if forward_pe is None:
            forward_pe = peer_info.get("forwardPe")

        try:
            forward_pe = float(forward_pe)
        except (TypeError, ValueError):
            forward_pe = None

        if (
            forward_pe is None
            or forward_pe <= 0
            or forward_pe > 100
        ):
            return {
                "usable": False,
                "forward_pe": None,
                "reason": (
                    "Kein plausibles positives "
                    "Forward-KGV verfügbar."
                )
            }

        return {
            "usable": True,
            "forward_pe": forward_pe,
            "reason": None
        }

    except Exception:
        return {
            "usable": False,
            "forward_pe": None,
            "reason": (
                "Peer-Daten konnten nicht zuverlässig "
                "geladen werden."
            )
        }


def calculate_peer_check(
    company_type,
    peer_group,
    fundamental_multiple,
    cache_version,
    earnings_basis_usable=True
):
    result = {
        "method_supported": False,
        "peer_rows": [],
        "usable_count": 0,
        "peer_median": None,
        "adjustment_pct": 0.0,
        "adjusted_multiple": None,
        "applied": False,
        "note": None
    }

    if not peer_group.get("available"):
        type_name = str(
            company_type.get("type", "")
        ).lower()

        if "standard-unternehmen" in type_name:
            result["note"] = (
                "Kein automatischer Peer-Check für den Sammeltyp "
                "Standard-Unternehmen. Der Peer-Check ist hier optional "
                "und blockiert den Fair Value nicht; verwendet wird das "
                "unveränderte Fundamental-Multiple."
            )
        else:
            result["note"] = (
                "Keine automatische Peer-Gruppe verfügbar."
            )
        return result

    if not peer_forward_pe_is_supported(company_type):
        result["note"] = (
            "Für diesen Unternehmenstyp wird kein einfaches "
            "Forward-KGV-Peerverfahren verwendet. Zyklische "
            "und Sondermodelle benötigen eine eigene "
            "normalisierte Peer-Bewertung."
        )
        return result

    if not earnings_basis_usable:
        result["note"] = (
            "KGV-Peer-Check gesperrt: Für die Aktie liegt "
            "keine positive und verwertbare normalisierte "
            "Gewinnbasis vor. Es werden deshalb keine "
            "Peer-KGVs geladen oder angewendet."
        )
        return result

    result["method_supported"] = True

    for peer in peer_group.get("peers", []):

        peer_data = load_peer_forward_pe(
            peer["symbol"],
            cache_version
        )

        row = {
            "symbol": peer["symbol"],
            "name": peer["name"],
            "usable": peer_data["usable"],
            "forward_pe": peer_data["forward_pe"],
            "reason": peer_data["reason"]
        }

        result["peer_rows"].append(row)

    usable_values = [
        row["forward_pe"]
        for row in result["peer_rows"]
        if row["usable"]
    ]

    result["usable_count"] = len(
        usable_values
    )

    if result["usable_count"] < 3:
        result["note"] = (
            "Weniger als 3 brauchbare Peer-KGVs verfügbar. "
            "Nach unserer Regel erfolgt deshalb keine "
            "automatische Peer-Anpassung."
        )

        if fundamental_multiple is not None:
            result["adjusted_multiple"] = (
                fundamental_multiple
            )

        return result

    peer_median = float(
        pd.Series(usable_values).median()
    )

    result["peer_median"] = peer_median

    if (
        fundamental_multiple is None
        or fundamental_multiple <= 0
    ):
        result["note"] = (
            "Peer-Median vorhanden, aber kein belastbares "
            "Fundamental-Multiple als Ausgangsbasis."
        )
        return result

    raw_difference = (
        peer_median / fundamental_multiple
        - 1.0
    )

    adjustment_pct = max(
        -0.05,
        min(0.05, raw_difference)
    )

    adjusted_multiple = (
        fundamental_multiple
        * (1.0 + adjustment_pct)
    )

    result["adjustment_pct"] = (
        adjustment_pct
    )
    result["adjusted_multiple"] = (
        adjusted_multiple
    )
    result["applied"] = True

    if abs(raw_difference) <= 0.05:
        result["note"] = (
            "Der Peer-Median liegt nahe am eigenen "
            "Fundamental-Multiple. Die tatsächliche "
            "Abweichung wird vollständig berücksichtigt."
        )
    else:
        result["note"] = (
            "Der Abstand zum Peer-Median ist größer als "
            "5 %. Die automatische Peer-Anpassung wird "
            "deshalb strikt auf maximal ±5 % begrenzt."
        )

    return result


# =========================================================
# Modul 6 – Schritt 3A: Spezialkontroll-Router
# =========================================================

def get_special_control(company_type, symbol):
    type_name = str(
        company_type.get("type", "")
    ).lower()

    symbol_text = str(
        symbol or ""
    ).upper()

    # Dieser Router erkennt ausschließlich bereits
    # fachlich vereinbarte Spezialkontrollen.
    # Er lädt noch keine Spezialdaten und verändert
    # weder Multiple Score noch Bewertungs-Multiple.

    if (
        "defense / stark wachsend" in type_name
        or symbol_text in ["RHM.DE", "RNMBY", "RNMBF"]
    ):
        return {
            "required": True,
            "control_key": "defense_order_visibility",
            "control_name": (
                "Defense / Auftrags- & "
                "Visibilitätskontrolle"
            ),
            "planned_checks": [
                "Backlog",
                "Fixed Orders",
                "Book-to-Bill",
                "Revenue Coverage",
                "Margentrend"
            ],
            "status": "Router aktiv",
            "note": (
                "Die eigentliche Auftrags-/Visibilitätsprüfung erfolgt "
                "im nachfolgenden Schritt 3B. Dort werden ausschließlich "
                "verifizierte Spezialdaten verwendet."
            )
        }

    if "halbleiterausrüstung / lithografie" in type_name:
        return {
            "required": True,
            "control_key": "semicap_order_visibility",
            "control_name": (
                "Halbleiterausrüstung / Auftrags- & "
                "Visibilitätskontrolle"
            ),
            "planned_checks": [],
            "status": "Router aktiv",
            "note": (
                "Die konkreten ASML-Prüfkennzahlen werden "
                "erst in einem späteren kontrollierten Schritt "
                "fachlich festgelegt und implementiert."
            )
        }

    if "halbleiter / fabless / ai-wachstum" in type_name:
        return {
            "required": True,
            "control_key": "ai_growth_margin",
            "control_name": (
                "AI-Wachstumsdauer- / Margenkontrolle"
            ),
            "planned_checks": [],
            "status": "Router aktiv",
            "note": (
                "Die konkrete Nvidia-Spezialkontrolle wird "
                "erst später fachlich definiert und mit "
                "belastbaren Daten umgesetzt."
            )
        }

    if "halbleiter / foundry" in type_name:
        return {
            "required": True,
            "control_key": "foundry_capex_geopolitics",
            "control_name": (
                "Foundry / CapEx- & geopolitische "
                "Risikokontrolle"
            ),
            "planned_checks": [],
            "status": "Router aktiv",
            "note": (
                "Die konkrete TSMC-Spezialkontrolle wird "
                "erst später fachlich definiert und mit "
                "belastbaren Daten umgesetzt."
            )
        }

    if "rohstoffe / lithium / zyklisch" in type_name:
        return {
            "required": True,
            "control_key": "lithium_cycle",
            "control_name": (
                "Lithium- / Zykluskontrolle"
            ),
            "planned_checks": [],
            "status": "Router aktiv",
            "note": (
                "Die konkrete Lithium-Zykluskontrolle wird "
                "erst später fachlich definiert. Aktuelle "
                "Forward-KGVs werden dabei nicht ungeprüft "
                "als Zyklusmaßstab verwendet."
            )
        }

    if "rohstoffe / bergbau / zyklisch" in type_name:
        return {
            "required": True,
            "control_key": "mining_cycle_quality",
            "control_name": (
                "Bergbau / Zyklus-, Cashflow- & operative Minenkontrolle"
            ),
            "planned_checks": [
                "Mehrjahres-/Zyklus-EPS",
                "Structural-Break-Kontrolle der EPS-Historie",
                "Structural-Break-Fallback über Rohstoffmarge, Produktion & FCF",
                "Peak-Cycle-Abstand",
                "FCF-Stabilität",
                "Bilanzpuffer",
                "Produktions-/Kostenvisibilität",
                "Rohstoffpreis-/Preiszyklus-Normalisierung",
                "Überleitung Preiszyklus → normalisierte Ertragskraft",
                "Reserve-/Minenlebensdauer- & NAV-Kontrolle",
                "Normalisierter Mine-NAV (Run-rate DCF / LOM-Kontrolle)",
                "Life-of-Mine-Profil & NAV-Freigabe-Gate",
                "Portfolio-Abdeckungslogik (Gesamt / gemanagt operativ / NAV-fähig)",
                "Portfolio-Completeness-Gate (Managed Operations / JVs / Entwicklungsprojekte)",
                "Asset-NAV-Normalisierung Phase 2 + Cashflow-Horizon-&-Closure-Tail-Gate (Gold / Nebenprodukte / Eigentum / Diskont)",
                "Discount-Rate & Portfolio-Aggregation Policy (Native-TRS-SOTP / 8%-Vergleich)",
                "Managed-Operations Source Coverage Map (offene Assets / Quellenalter / Sondermodelle)",
                "Allgemeiner Primärrohstoff-Router"
            ],
            "status": "Router aktiv – V2.17.1 Managed-Operations Source Coverage Map + V2.16 Discount-Rate/Portfolio-Aggregation",
            "note": (
                "V2.17.1 ergänzt das Bergbaumodell um eine Managed-Operations Source Coverage Map für die sieben noch offenen Reserve-Assetgruppen. Die V2.16 Discount-Rate-&-Portfolio-Aggregation-Policy bleibt unverändert aktiv. Asset-spezifische offizielle TRS-After-Tax-Diskontsätze dürfen für einen heterogenen Sum-of-the-Parts-Ansatz beibehalten werden, sofern Bewertungsstichtag, Währung, Eigentumsanteil und Rohstoffpreis-Normalisierung konsistent sind. Die 8-%-Re-Diskontierung bleibt eine separate Vergleichsschicht und ist nicht mehr das bindende 90-%-Portfolio-Gate. Das Cashflow-Horizon-/Closure-Tail-Gate bleibt für echte Re-Diskontierungen aktiv. Zusätzlich bleiben Portfolio-Completeness, Structural-Break-Fallback, Reserve-/NAV-Snapshot und der konservative allgemeine "
                "Primärrohstoff-Router für eindeutige Branchen wie Gold, Silber und "
                "Kupfer. Unspezifische Mischbranchen bleiben gesperrt. Das bestehende "
                "V2.7-Life-of-Mine-Gate bleibt unverändert aktiv. Zusätzlich darf ein später bestandener "
                "Managed-Operations-Gate den Gesamt-Fair-Value nicht allein freigeben: Nicht gemanagte JVs und "
                "Entwicklungsprojekte benötigen jeweils einen belastbaren Wert oder einen ausdrücklich konservativen Nullansatz. "
                "Das Gate verlangt weiterhin eine hohe Reserveabdeckung, aktuelle technische "
                "Minenpläne und belastbare "
                "mine-spezifische LOM-Kosten-/CapEx-Profile. Ein einzelnes "
                "Guidance-Jahr bleibt ausdrücklich nur Run-rate-Kontrolle; bei "
                "unvollständiger LOM-Abdeckung bleibt der Fair Value gesperrt."
            )
        }

    if "autohersteller" in type_name:
        return {
            "required": True,
            "control_key": "auto_cycle_industrial_cashflow",
            "control_name": (
                "Autohersteller / Zyklus-, Industrie-Cashflow- & "
                "Finanzdienstleistungsprüfung"
            ),
            "planned_checks": [
                "Zyklus-normalisiertes EPS",
                "Automotive Free Cash Flow",
                "Industrie-Netto-Cash / -Schulden",
                "EV / EBITDA",
                "Finanzdienstleistungs-Anteil"
            ],
            "status": "Router aktiv – V1 Datenbasis vorhanden",
            "note": (
                "V1 lädt nur belastbare Konzern-Basiskennzahlen. "
                "Automotive Free Cash Flow, Industrie-Netto-Cash/-Schulden "
                "und der Finanzdienstleistungs-Anteil werden nicht aus "
                "konsolidierten Yahoo-Werten geschätzt. Das Sondermodell "
                "verändert noch keinen Score und kein Bewertungs-Multiple."
            )
        }

    if "midstream" in type_name:
        return {
            "required": True,
            "control_key": "midstream_cashflow_leverage",
            "control_name": (
                "Midstream / Cashflow-, EV/EBITDA- & Verschuldungsprüfung"
            ),
            "planned_checks": [
                "EV / EBITDA",
                "Distributable Cash Flow",
                "Netto-Schulden / EBITDA",
                "Ausschüttungsdeckung"
            ],
            "status": "Router aktiv – V1 Datenbasis vorhanden",
            "note": (
                "V1 lädt nur belastbare Midstream-Basiskennzahlen aus der "
                "aktuellen Datenquelle. Distributable Cash Flow und "
                "Ausschüttungsdeckung werden nicht aus Standard-FCF oder "
                "anderen Kennzahlen geschätzt. Das Sondermodell verändert "
                "noch keinen Score und kein Bewertungs-Multiple."
            )
        }

    if (
        "reit" in type_name
        or "immobilien" in type_name
    ):
        return {
            "required": True,
            "control_key": "reit_ffo_affo_leverage",
            "control_name": (
                "REIT / FFO-, AFFO- & Verschuldungsprüfung"
            ),
            "planned_checks": [
                "FFO / AFFO je Aktie",
                "P/FFO bzw. P/AFFO",
                "Netto-Schulden / EBITDA",
                "NAV / Immobilienwert",
                "Ausschüttungsdeckung"
            ],
            "status": "Router aktiv – V1 Datenbasis vorhanden",
            "note": (
                "V1 nutzt FFO/AFFO nur, wenn Yahoo sie direkt separat "
                "liefert. FFO/AFFO, NAV und Immobilienwerte werden nicht "
                "aus Standardkennzahlen rekonstruiert oder geschätzt. "
                "EV/EBITDA und Netto-Schulden/EBITDA bleiben reine "
                "Datenreferenzen. Das Sondermodell verändert noch keinen "
                "Score und kein Bewertungs-Multiple."
            )
        }

    if "bank" in type_name:
        return {
            "required": True,
            "control_key": "bank_book_capital",
            "control_name": (
                "Bank / Buchwert-, Ertrags- & Kapitalprüfung"
            ),
            "planned_checks": [
                "Normalisiertes / Core EPS",
                "RoTE / ROE",
                "Tangible Book Value / KBV",
                "CET1-Kapitalquote"
            ],
            "status": "Router aktiv – V1 Datenbasis vorhanden",
            "note": (
                "V1 lädt nur belastbare Basiskennzahlen aus der aktuellen "
                "Datenquelle. RoTE, Tangible Book Value und CET1 werden "
                "nicht geschätzt oder durch ungeeignete Standardkennzahlen "
                "ersetzt. Das Sondermodell verändert noch keinen Score und "
                "kein Bewertungs-Multiple."
            )
        }

    if "versicherung" in type_name:
        return {
            "required": True,
            "control_key": "insurance_core_capital",
            "control_name": (
                "Versicherung / Core-Earnings- & Kapitalprüfung"
            ),
            "planned_checks": [
                "Core Earnings",
                "ROE",
                "Buchwert / KBV",
                "Solvency- / Kapitalquote",
                "Ausschüttungsquote"
            ],
            "status": "Router aktiv – V1 Datenbasis vorhanden",
            "note": (
                "V1 lädt nur belastbare Basiskennzahlen aus der aktuellen "
                "Datenquelle. Core Earnings und Solvency-/Kapitalquote "
                "werden nicht geschätzt. Das Sondermodell verändert noch "
                "keinen Score und kein Bewertungs-Multiple."
            )
        }

    return {
        "required": False,
        "control_key": None,
        "control_name": None,
        "planned_checks": [],
        "status": "Keine Spezialkontrolle hinterlegt",
        "note": (
            "Für diesen Unternehmenstyp ist in Schritt 3A "
            "noch keine separate Spezialkontrolle fachlich "
            "vereinbart. Es wird nichts geschätzt oder erfunden."
        )
    }


# =========================================================
# Modul 6 – Schritt 3B: Defense-Auftrags- & Visibilitätskontrolle
# =========================================================

def get_verified_defense_snapshot(symbol):
    """
    Curated, explicitly dated official-data snapshot for Defense V1.

    V1 deliberately does not scrape investor-relations pages at runtime.
    Only values that were verified from an official company publication are
    stored. The snapshot expires at the next scheduled reporting date so a
    stale special-control dataset cannot silently release a Fair Value.
    """

    symbol_text = str(symbol or "").upper()

    if symbol_text not in ["RHM.DE", "RHM.F", "RNMBY", "RNMBF"]:
        return None

    return {
        "company": "Rheinmetall AG",
        "published_date": "06.08.2026",
        "as_of_date": "30.06.2026",
        "valid_until": "05.11.2026",
        "source_name": "Rheinmetall Q2/H1 2026",
        "source_note": (
            "Offizielle Rheinmetall-H1/Q2-2026-Daten. "
            "Backlog enthält feste Aufträge plus erwartete Abrufe aus "
            "bestehenden Rahmenverträgen."
        ),
        "backlog_current": 80.467e9,
        "backlog_previous": 55.972e9,
        "fixed_order_backlog_current": 56.342e9,
        "fixed_order_backlog_previous": 32.266e9,
        "frame_backlog_current": 24.126e9,
        "revenue_guidance_low": 13.7e9,
        "revenue_guidance_high": 14.2e9,
        # Rheinmetall reported "above 3". 3.0 is stored only as a
        # conservative lower bound; the display retains the > qualifier.
        "book_to_bill_lower_bound": 3.0,
        "book_to_bill_is_lower_bound": True,
        "book_to_bill_period": "Q2 2026",
        "near_term_fixed_coverage_pct": 90.0,
        "near_term_horizon": "<2,5 Jahre",
        "current_margin": 15.0,
        "comparable_previous_margin": 12.1,
        "latest_quarter_margin": 17.1,
        "previous_full_year_margin": 18.5,
        "guidance_margin": 19.0,
    }


def _defense_backlog_status(growth_pct):
    if growth_pct is None:
        return "Daten unzureichend"
    if growth_pct >= 15.0:
        return "Stark"
    if growth_pct >= 0.0:
        return "Positiv"
    if growth_pct > -10.0:
        return "Leicht rückläufig"
    return "Schwach"


def _defense_coverage_status(value):
    if value is None:
        return "Daten unzureichend"
    if value >= 3.0:
        return "Sehr stark"
    if value >= 2.0:
        return "Stark"
    if value >= 1.0:
        return "Ausreichend"
    return "Schwach"


def _defense_fixed_orders_status(share_pct):
    if share_pct is None:
        return "Daten unzureichend"
    if share_pct >= 70.0:
        return "Sehr stark"
    if share_pct >= 60.0:
        return "Stark"
    if share_pct >= 50.0:
        return "Ausreichend"
    return "Schwach"


def _defense_book_to_bill_status(value):
    if value is None:
        return "Daten unzureichend"
    if value >= 1.5:
        return "Sehr stark"
    if value >= 1.2:
        return "Stark"
    if value >= 1.0:
        return "Ausreichend"
    return "Schwach"


def _defense_near_term_status(value):
    if value is None:
        return "Daten unzureichend"
    if value >= 80.0:
        return "Sehr stark"
    if value >= 65.0:
        return "Stark"
    if value >= 50.0:
        return "Ausreichend"
    return "Schwach"


def evaluate_defense_margin_trend(
    current_margin=None,
    comparable_previous_margin=None,
    latest_quarter_margin=None,
    previous_full_year_margin=None,
    guidance_margin=None,
):
    result = {
        "current_margin": safe_float(current_margin),
        "previous_margin": safe_float(comparable_previous_margin),
        "margin_change_pp": None,
        "latest_quarter_margin": safe_float(latest_quarter_margin),
        "previous_full_year_margin": safe_float(previous_full_year_margin),
        "guidance_margin": safe_float(guidance_margin),
        "guidance_change_pp": None,
        "historical_trend": "Daten unzureichend",
        "guidance_trend": "Daten unzureichend",
        "overall_status": "Daten unzureichend",
    }

    current = result["current_margin"]
    previous = result["previous_margin"]

    if current is not None and previous is not None:
        change = current - previous
        result["margin_change_pp"] = change

        if change >= 2.0:
            result["historical_trend"] = "Sehr stark"
        elif change >= 0.5:
            result["historical_trend"] = "Stark"
        elif change > -0.5:
            result["historical_trend"] = "Stabil"
        elif change > -2.0:
            result["historical_trend"] = "Leicht rückläufig"
        else:
            result["historical_trend"] = "Schwach"

    guidance = result["guidance_margin"]
    previous_full_year = result["previous_full_year_margin"]

    if guidance is not None and previous_full_year is not None:
        change = guidance - previous_full_year
        result["guidance_change_pp"] = change

        if change >= 1.0:
            result["guidance_trend"] = "Steigend"
        elif change >= -0.5:
            result["guidance_trend"] = "Stabil bis steigend"
        elif change > -1.5:
            result["guidance_trend"] = "Leicht rückläufig"
        else:
            result["guidance_trend"] = "Schwach"

    hist = result["historical_trend"]
    guide = result["guidance_trend"]

    if hist == "Sehr stark" and guide in ["Steigend", "Stabil bis steigend"]:
        result["overall_status"] = "Sehr stark"
    elif hist in ["Sehr stark", "Stark"] and guide != "Schwach":
        result["overall_status"] = "Stark"
    elif hist == "Stabil" and guide in ["Steigend", "Stabil bis steigend"]:
        result["overall_status"] = "Ausreichend"
    elif hist in ["Leicht rückläufig", "Schwach"]:
        result["overall_status"] = "Schwach"

    return result


def build_defense_special_control(base_control, company_type, symbol):
    """Enrich the 3A router result with Defense step 3B when verified data exist."""

    control = dict(base_control or {})
    control.setdefault("router_status", control.get("status"))
    control.setdefault("router_note", control.get("note"))

    if control.get("control_key") != "defense_order_visibility":
        control.setdefault("implemented", False)
        control.setdefault("released", False)
        return control

    snapshot = get_verified_defense_snapshot(symbol)

    if snapshot is None:
        control.update({
            "implemented": False,
            "released": False,
            "confidence_cap": "Niedrig",
            "step3b_status": "Schritt 3B Daten fehlen",
            "note": (
                "Die Defense-Logik ist fachlich implementiert, aber für diese "
                "Aktie liegt noch kein verifizierter offizieller Spezialdaten-"
                "Snapshot vor. Es wird nichts geschätzt; Fair Value bleibt gesperrt."
            ),
        })
        return control

    try:
        valid_until = datetime.strptime(
            snapshot["valid_until"], "%d.%m.%Y"
        ).date()
        snapshot_fresh = datetime.now().date() <= valid_until
    except Exception:
        snapshot_fresh = False

    backlog_current = safe_float(snapshot.get("backlog_current"))
    backlog_previous = safe_float(snapshot.get("backlog_previous"))
    revenue_low = safe_float(snapshot.get("revenue_guidance_low"))
    revenue_high = safe_float(snapshot.get("revenue_guidance_high"))

    backlog_growth_pct = None
    if backlog_current is not None and backlog_previous not in [None, 0]:
        backlog_growth_pct = (backlog_current / backlog_previous - 1.0) * 100.0

    revenue_base = None
    if revenue_low is not None and revenue_high is not None:
        revenue_base = (revenue_low + revenue_high) / 2.0

    revenue_coverage = None
    if backlog_current is not None and revenue_base not in [None, 0]:
        revenue_coverage = backlog_current / revenue_base

    fixed_current = safe_float(snapshot.get("fixed_order_backlog_current"))
    fixed_previous = safe_float(snapshot.get("fixed_order_backlog_previous"))

    fixed_share_pct = None
    if fixed_current is not None and backlog_current not in [None, 0]:
        fixed_share_pct = fixed_current / backlog_current * 100.0

    fixed_previous_share_pct = None
    if fixed_previous is not None and backlog_previous not in [None, 0]:
        fixed_previous_share_pct = fixed_previous / backlog_previous * 100.0

    fixed_share_change_pp = None
    if fixed_share_pct is not None and fixed_previous_share_pct is not None:
        fixed_share_change_pp = fixed_share_pct - fixed_previous_share_pct

    book_to_bill = safe_float(snapshot.get("book_to_bill_lower_bound"))
    near_term_coverage = safe_float(snapshot.get("near_term_fixed_coverage_pct"))

    margin = evaluate_defense_margin_trend(
        snapshot.get("current_margin"),
        snapshot.get("comparable_previous_margin"),
        snapshot.get("latest_quarter_margin"),
        snapshot.get("previous_full_year_margin"),
        snapshot.get("guidance_margin"),
    )

    checks = {
        "backlog": {
            "value": backlog_current,
            "previous": backlog_previous,
            "growth_pct": backlog_growth_pct,
            "status": _defense_backlog_status(backlog_growth_pct),
        },
        "revenue_coverage": {
            "value": revenue_coverage,
            "revenue_base": revenue_base,
            "status": _defense_coverage_status(revenue_coverage),
        },
        "fixed_orders": {
            "value": fixed_current,
            "share_pct": fixed_share_pct,
            "previous_share_pct": fixed_previous_share_pct,
            "share_change_pp": fixed_share_change_pp,
            "status": _defense_fixed_orders_status(fixed_share_pct),
        },
        "book_to_bill": {
            "value": book_to_bill,
            "is_lower_bound": bool(snapshot.get("book_to_bill_is_lower_bound")),
            "period": snapshot.get("book_to_bill_period"),
            "status": _defense_book_to_bill_status(book_to_bill),
        },
        "near_term_fixed_coverage": {
            "value_pct": near_term_coverage,
            "horizon": snapshot.get("near_term_horizon"),
            "status": _defense_near_term_status(near_term_coverage),
        },
        "margin_trend": margin,
    }

    core_statuses = [
        checks["backlog"]["status"],
        checks["revenue_coverage"]["status"],
        checks["fixed_orders"]["status"],
        checks["book_to_bill"]["status"],
        checks["margin_trend"]["overall_status"],
    ]

    insufficient_count = core_statuses.count("Daten unzureichend")
    weak_count = core_statuses.count("Schwach")
    strong_count = sum(
        status in ["Stark", "Sehr stark", "Positiv"]
        for status in core_statuses
    )

    if not snapshot_fresh:
        overall_status = "Daten veraltet"
        released = False
        confidence_cap = "Niedrig"
    elif insufficient_count >= 2:
        overall_status = "Nicht freigegeben"
        released = False
        confidence_cap = "Niedrig"
    elif weak_count >= 1:
        overall_status = "Warnung"
        released = True
        confidence_cap = "Mittel"
    elif strong_count >= 4:
        overall_status = "Stark"
        released = True
        confidence_cap = "Hoch"
    else:
        overall_status = "Ausreichend"
        released = True
        confidence_cap = "Mittel"

    control.update({
        "implemented": True,
        "released": released,
        "confidence_cap": confidence_cap,
        "step3b_status": (
            "Schritt 3B vollständig – Fair Value freigegeben"
            if released
            else "Schritt 3B nicht freigegeben"
        ),
        "overall_status": overall_status,
        "snapshot_fresh": snapshot_fresh,
        "snapshot": snapshot,
        "checks": checks,
        "note": (
            "Die Defense-Spezialkontrolle prüft Backlog, Revenue Coverage, "
            "Fixed Orders, Book-to-Bill und Margentrend. Sie verändert den "
            "100-Punkte-Multiple-Score nicht."
        ),
    })

    return control


# =========================================================
# Modul 6 – Schritt 3B: Bergbau-/Rohstoff-Zykluskontrolle V2
# =========================================================

def _extract_numeric_history(items):
    values = []
    for item in items or []:
        if isinstance(item, dict):
            value = safe_float(item.get("value"))
        else:
            value = safe_float(item)
        if value is not None:
            values.append(value)
    return values


def _extract_dated_numeric_history(items):
    """Return year/value rows without inventing dates for undated history."""
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        value = safe_float(item.get("value"))
        date_value = item.get("date")
        year = getattr(date_value, "year", None)
        if value is None or year is None:
            continue
        rows.append({"year": int(year), "value": value})
    return rows


def get_verified_mining_snapshot(symbol):
    """
    Curated, explicitly dated official-data snapshots for Mining V2.

    Operating mine KPIs are never inferred from Yahoo summary data. A snapshot
    is added only after production/cost guidance was verified from an official
    company publication or filing. The refresh deadline is an internal safety
    deadline so stale operating guidance cannot silently release a Fair Value.
    """

    symbol_text = str(symbol or "").upper()

    if symbol_text == "NEM":
        # Newmont Q2 2026 / unchanged FY2026 guidance, published 23 Jul 2026.
        # Guidance metrics are company-reported +/-5%; low/high bounds below are
        # derived only from that explicit tolerance for internal midpoint/status
        # calculations and are not independent forecasts.
        return {
            "company": "Newmont Corporation",
            "published_date": "23.07.2026",
            "as_of_date": "30.06.2026",
            "valid_until": "31.10.2026",
            "source_name": "Newmont Q2 2026 Results / FY2026 Guidance",
            "source_note": (
                "Offizielle Newmont-Q2-2026-Daten. Newmont bestätigte die bereits "
                "veröffentlichte 2026-Guidance von 5,26 Mio. zurechenbaren Goldunzen "
                "(±5 %) und Gold By-Product AISC von 1.680 USD/oz (±5 %). Q2-Gold-AISC "
                "lag bei 1.621 USD/oz. Die Guidance basiert auf Unternehmensannahmen "
                "einschließlich eines hohen Goldpreisumfelds; deshalb bleibt sie eine "
                "aktuelle Kostenbasis und kein Life-of-Mine-Kostenprofil."
            ),
            "production_guidance_label": "2026 Gold-Produktions-Guidance",
            "production_guidance_unit": "Mio. oz",
            "production_guidance_display": "5.26 Mio. oz (±5 %)",
            "previous_production_guidance_display": "5.26 Mio. oz (±5 %)",
            "production_guidance_current_low": 4.997,
            "production_guidance_current_high": 5.523,
            "production_guidance_previous_low": 4.997,
            "production_guidance_previous_high": 5.523,
            "q2_primary_production": 1.3,
            "q2_primary_production_unit": "Mio. oz",
            "aisc_guidance_label": "2026 Gold-AISC-Guidance",
            "aisc_unit": "USD/oz",
            "aisc_guidance_display": "1,680 USD/oz (±5 %)",
            "previous_aisc_guidance_display": "1,680 USD/oz (±5 %)",
            "actual_aisc_label": "Q2 Gold AISC",
            "actual_aisc_display": "1,621 USD/oz",
            "commodity_aisc_guidance_current_low": 1596.0,
            "commodity_aisc_guidance_current_high": 1764.0,
            "commodity_aisc_guidance_previous_low": 1596.0,
            "commodity_aisc_guidance_previous_high": 1764.0,
            "q2_commodity_aisc": 1621.0,
            "commodity_cost_basis_price_assumption": 4500.0,
            "commodity_cost_basis_note": (
                "Newmonts 2026-Kostenguidance basiert u. a. auf einer Goldpreisannahme "
                "von 4.500 USD/oz. Höhere Goldpreise erhöhen Royalties und Produktionssteuern. "
                "Die AISC-Basis von 1.680 USD/oz wird deshalb gegenüber dem normalisierten "
                "Goldpreis nur als konservative Run-rate-Kontrolle verwendet, nicht als "
                "preisunabhängiges Life-of-Mine-Kostenprofil."
            ),
            "gold_byproduct_cas_guidance": 1055.0,
            "q2_gold_byproduct_cas": 1043.0,
            "sustaining_capital_guidance_musd": 1950.0,
            "development_capital_guidance_musd": 1400.0,
            "guidance_comment": (
                "Full-Year-Guidance gegenüber Februar unverändert. Newmont erwartet "
                "rund 51 % der 2026-Goldproduktion im zweiten Halbjahr. Die aktuelle "
                "AISC-Guidance enthält Sustaining Capital und By-Product-Effekte und "
                "wird nur als verifizierte Run-rate-Kostenbasis verwendet."
            ),
        }

    if symbol_text != "HL":
        return None

    return {
        "company": "Hecla Mining Company",
        "published_date": "04.08.2026",
        "as_of_date": "30.06.2026",
        "valid_until": "15.11.2026",
        "source_name": "Hecla Q2 2026 Results / SEC Exhibit 99.1",
        "source_note": (
            "Offizielle Hecla-Q2-2026-Daten. Die AISC-Werte verstehen sich "
            "nach Nebenproduktgutschriften. Die konsolidierte Silver-AISC-"
            "Guidance umfasst Greens Creek und Lucky Friday; Keno Hill ist "
            "weiterhin vor kommerzieller Produktion und deshalb darin nicht enthalten."
        ),
        "production_guidance_current_low_moz": 15.1,
        "production_guidance_current_high_moz": 16.1,
        "production_guidance_previous_low_moz": 15.1,
        "production_guidance_previous_high_moz": 16.5,
        "q2_silver_production_moz": 4.2,
        "silver_aisc_guidance_current_low": 12.50,
        "silver_aisc_guidance_current_high": 13.50,
        "silver_aisc_guidance_previous_low": 15.00,
        "silver_aisc_guidance_previous_high": 16.25,
        "q2_silver_aisc": 6.07,
        "greens_creek_guidance_low_moz": 8.0,
        "greens_creek_guidance_high_moz": 8.3,
        "lucky_friday_guidance_low_moz": 4.9,
        "lucky_friday_guidance_high_moz": 5.2,
        "keno_hill_guidance_low_moz": 2.2,
        "keno_hill_guidance_high_moz": 2.6,
        # Q2-2026 guidance reconciliation used by Mining V2.7. Values are
        # company-published guidance inputs, not inferred from Yahoo data.
        "nav_model_discount_rate_pct": 5.0,
        "ytd_income_tax_provision_musd": 69.667,
        "ytd_income_from_continuing_operations_musd": 282.529,
        "guidance_metal_price_assumptions": {
            "gold": 4000.0,
            "zinc": 1.40,
            "lead": 0.85,
            "copper": 4.00,
        },
        "mine_nav_run_rate_inputs": {
            "Greens Creek": {
                "production_low_moz": 8.0,
                "production_high_moz": 8.3,
                "aisc_before_byproduct_musd": 293.8,
                "sustaining_capex_musd": 63.0,
                "byproduct_credits_musd": {
                    "zinc": 102.3,
                    "gold": 201.3,
                    "lead": 25.4,
                    "copper": 1.6,
                },
            },
            "Lucky Friday": {
                "production_low_moz": 4.9,
                "production_high_moz": 5.2,
                "aisc_before_byproduct_musd": 218.2,
                "sustaining_capex_musd": 80.0,
                "byproduct_credits_musd": {
                    "zinc": 38.9,
                    "gold": 0.0,
                    "lead": 51.1,
                    "copper": 0.0,
                },
            },
            "Keno Hill": {
                "production_low_moz": 2.2,
                "production_high_moz": 2.6,
                "precommercial": True,
                "growth_capex_musd": 63.0,
                "aisc_before_byproduct_musd": None,
                "byproduct_credits_musd": {},
            },
        },
        "guidance_comment": (
            "Gesamt-Silberproduktion: obere Bandbreite leicht gesenkt. "
            "Greens Creek angehoben, Lucky Friday gestrafft/verbessert, "
            "Keno Hill reduziert. Kosten-Guidance deutlich verbessert."
        ),
    }


def _snapshot_first(snapshot, *keys):
    for key in keys:
        if key in (snapshot or {}):
            value = (snapshot or {}).get(key)
            if value is not None:
                return value
    return None


def _mining_production_guidance_status(snapshot):
    current_low = safe_float(_snapshot_first(
        snapshot, "production_guidance_current_low", "production_guidance_current_low_moz"
    ))
    current_high = safe_float(_snapshot_first(
        snapshot, "production_guidance_current_high", "production_guidance_current_high_moz"
    ))
    previous_low = safe_float(_snapshot_first(
        snapshot, "production_guidance_previous_low", "production_guidance_previous_low_moz"
    ))
    previous_high = safe_float(_snapshot_first(
        snapshot, "production_guidance_previous_high", "production_guidance_previous_high_moz"
    ))

    if None in [current_low, current_high, previous_low, previous_high]:
        return "Daten unzureichend", None

    previous_mid = (previous_low + previous_high) / 2.0
    current_mid = (current_low + current_high) / 2.0
    if previous_mid <= 0:
        return "Daten unzureichend", None

    change_pct = (current_mid / previous_mid - 1.0) * 100.0

    if change_pct >= 2.0:
        status = "Stark"
    elif change_pct >= 0.5:
        status = "Positiv"
    elif change_pct >= -5.0:
        status = "Stabil"
    else:
        status = "Schwach"

    return status, change_pct


def _mining_aisc_guidance_status(snapshot):
    current_low = safe_float(_snapshot_first(
        snapshot, "commodity_aisc_guidance_current_low", "silver_aisc_guidance_current_low"
    ))
    current_high = safe_float(_snapshot_first(
        snapshot, "commodity_aisc_guidance_current_high", "silver_aisc_guidance_current_high"
    ))
    previous_low = safe_float(_snapshot_first(
        snapshot, "commodity_aisc_guidance_previous_low", "silver_aisc_guidance_previous_low"
    ))
    previous_high = safe_float(_snapshot_first(
        snapshot, "commodity_aisc_guidance_previous_high", "silver_aisc_guidance_previous_high"
    ))

    if None in [current_low, current_high, previous_low, previous_high]:
        return "Daten unzureichend", None

    previous_mid = (previous_low + previous_high) / 2.0
    current_mid = (current_low + current_high) / 2.0
    if previous_mid <= 0:
        return "Daten unzureichend", None

    # Lower AISC is better; positive improvement_pct therefore means improvement.
    improvement_pct = (previous_mid - current_mid) / previous_mid * 100.0

    if improvement_pct >= 10.0:
        status = "Stark verbessert"
    elif improvement_pct >= 2.0:
        status = "Verbessert"
    elif improvement_pct >= -5.0:
        status = "Stabil"
    else:
        status = "Schwach"

    return status, improvement_pct


def _mining_actual_aisc_status(snapshot):
    actual = safe_float(_snapshot_first(
        snapshot, "q2_commodity_aisc", "q2_silver_aisc"
    ))
    guidance_high = safe_float(_snapshot_first(
        snapshot, "commodity_aisc_guidance_current_high", "silver_aisc_guidance_current_high"
    ))

    if actual is None or guidance_high is None or guidance_high <= 0:
        return "Daten unzureichend"
    if actual <= guidance_high:
        return "Stark"
    if actual <= guidance_high * 1.10:
        return "Ausreichend"
    return "Schwach"



def get_verified_mining_commodity_route(symbol, industry=None):
    """
    Conservative primary-commodity router for miners.

    Routing order:
      1) explicitly verified company mapping for ambiguous/mixed miners;
      2) exact, unambiguous Yahoo industry mapping for simple commodity groups.

    Generic labels such as ``Other Precious Metals & Mining`` are deliberately
    *not* inferred, because they can contain materially mixed metal exposure.
    """
    symbol_text = str(symbol or "").upper().strip()
    industry_text = str(industry or "").strip()
    industry_key = industry_text.casefold()

    explicit_routes = {
        "HL": {
            "commodity_name": "Silber",
            "commodity_symbol": "SI=F",
            "unit": "USD/oz",
            "normalization_years": 5,
            "current_window_days": 60,
            "route_source": "Unternehmensspezifisch verifiziert",
            "routing_basis": "HL / Hecla Mining",
            "mapping_note": (
                "Hecla wird wegen der gemischten Yahoo-Branche ausdrücklich primär "
                "dem Silberpreis zugeordnet. Gold, Blei und Zink bleiben zusätzliche "
                "Exposures und werden nicht als separate Primärrohstoffe in diese "
                "V2.16-Kontrolle hineingeschätzt."
            ),
        },
    }
    if symbol_text in explicit_routes:
        return explicit_routes[symbol_text]

    # Only exact and sufficiently specific Yahoo industry labels are allowed to
    # auto-route. Ambiguous mining/precious-metals labels remain blocked.
    industry_routes = {
        "gold": {
            "commodity_name": "Gold",
            "commodity_symbol": "GC=F",
            "unit": "USD/oz",
        },
        "silver": {
            "commodity_name": "Silber",
            "commodity_symbol": "SI=F",
            "unit": "USD/oz",
        },
        "copper": {
            "commodity_name": "Kupfer",
            "commodity_symbol": "HG=F",
            "unit": "USD/lb",
        },
    }

    base = industry_routes.get(industry_key)
    if base is None:
        return None

    return {
        **base,
        "normalization_years": 5,
        "current_window_days": 60,
        "route_source": "Allgemeiner Branchen-Router",
        "routing_basis": f"Yahoo-Branche: {industry_text}",
        "mapping_note": (
            f"Die eindeutige Yahoo-Branche „{industry_text}“ wird in V2.17.1 "
            f"automatisch dem Primärrohstoff {base['commodity_name']} zugeordnet. "
            "Unspezifische oder gemischte Bergbau-Branchen werden weiterhin nicht "
            "automatisch geroutet."
        ),
    }


def _evaluate_mining_commodity_history(
    history,
    normalization_years=5,
    current_window_days=60,
):
    """Pure price-cycle evaluation so the calculation can be unit-tested."""
    result = {
        "available": False,
        "annual_averages": [],
        "years_used": [],
        "normalized_price": None,
        "current_reference_price": None,
        "latest_price": None,
        "ytd_average_price": None,
        "premium_to_normalized_pct": None,
        "price_cycle_status": "Daten unzureichend",
        "method": (
            "Median der Jahresdurchschnittspreise der letzten vollständigen "
            f"{normalization_years} Kalenderjahre"
        ),
        "current_reference_method": (
            f"Median der letzten {current_window_days} Handelstage"
        ),
        "reason": None,
    }

    if history is None or getattr(history, "empty", True) or "Close" not in history:
        result["reason"] = "Keine belastbare Rohstoffpreis-Historie verfügbar."
        return result

    try:
        close = pd.to_numeric(history["Close"], errors="coerce").dropna()
        close = close[close > 0]
    except Exception:
        close = pd.Series(dtype=float)

    if close.empty:
        result["reason"] = "Keine positiven Schlusskurse verfügbar."
        return result

    try:
        years = pd.to_datetime(close.index).year
    except Exception:
        result["reason"] = "Rohstoffpreis-Zeitachse nicht auswertbar."
        return result

    price_frame = pd.DataFrame({"close": close.values, "year": years})
    current_year = datetime.now().year

    complete = price_frame[price_frame["year"] < current_year]
    available_years = sorted(int(y) for y in complete["year"].unique())
    selected_years = available_years[-int(normalization_years):]

    # Require at least four complete calendar years. With five years we use the
    # full intended method; four years are tolerated as a degraded fallback.
    if len(selected_years) < 4:
        result["reason"] = (
            "Weniger als vier vollständige Kalenderjahre Rohstoffpreisdaten vorhanden."
        )
        return result

    annual_averages = []
    for year in selected_years:
        year_values = complete.loc[complete["year"] == year, "close"]
        if year_values.empty:
            continue
        annual_averages.append({
            "year": int(year),
            "average": float(year_values.mean()),
        })

    if len(annual_averages) < 4:
        result["reason"] = "Jahresdurchschnittspreise nicht ausreichend berechenbar."
        return result

    normalized_price = float(pd.Series(
        [item["average"] for item in annual_averages]
    ).median())

    window = close.tail(max(20, int(current_window_days)))
    current_reference = float(window.median()) if not window.empty else None
    latest_price = float(close.iloc[-1])

    current_year_mask = price_frame["year"] == current_year
    ytd_values = price_frame.loc[current_year_mask, "close"]
    ytd_average = float(ytd_values.mean()) if not ytd_values.empty else None

    premium_pct = None
    if normalized_price > 0 and current_reference is not None:
        premium_pct = (current_reference / normalized_price - 1.0) * 100.0

    if premium_pct is None:
        price_status = "Daten unzureichend"
    elif premium_pct >= 75.0:
        price_status = "Extremes Peak-Niveau"
    elif premium_pct >= 40.0:
        price_status = "Peak-Niveau"
    elif premium_pct >= 20.0:
        price_status = "Erhöht"
    elif premium_pct > -20.0:
        price_status = "Nahe Zyklusnormal"
    else:
        price_status = "Unter Zyklusnormal"

    result.update({
        "available": True,
        "annual_averages": annual_averages,
        "years_used": [item["year"] for item in annual_averages],
        "normalized_price": normalized_price,
        "current_reference_price": current_reference,
        "latest_price": latest_price,
        "ytd_average_price": ytd_average,
        "premium_to_normalized_pct": premium_pct,
        "price_cycle_status": price_status,
        "reason": None,
    })
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def load_mining_commodity_price_cycle(
    commodity_symbol,
    cache_version,
    normalization_years=5,
    current_window_days=60,
):
    """Load commodity history from Yahoo and evaluate the cycle conservatively."""
    _ = cache_version
    try:
        commodity_ticker = yf.Ticker(str(commodity_symbol))
        history = commodity_ticker.history(
            period="10y",
            interval="1d",
            auto_adjust=False,
        )
    except Exception:
        history = pd.DataFrame()

    return _evaluate_mining_commodity_history(
        history,
        normalization_years=normalization_years,
        current_window_days=current_window_days,
    )


def build_mining_commodity_cycle(symbol, snapshot, cache_version, industry=None):
    """
    Combine dynamic commodity-price normalization with verified mine cost data.

    The normalized commodity margin is an input into the V2.4 earnings-power
    bridge. It is never used as a direct one-for-one price-to-EPS factor. The
    bridge requires convergence with the already-normalized EPS and an FCF
    plausibility check.
    """
    route = get_verified_mining_commodity_route(symbol, industry)
    if route is None:
        industry_text = str(industry or "").strip()
        if industry_text:
            route_reason = (
                f"Die Yahoo-Branche „{industry_text}“ ist nicht als eindeutige "
                "Primärrohstoff-Branche freigegeben. Bei gemischten oder unspezifischen "
                "Bergbau-Branchen wird kein Rohstoff geraten."
            )
        else:
            route_reason = (
                "Für diese Bergbau-Aktie ist noch kein verifizierter Primärrohstoff "
                "für die Preiszyklus-Normalisierung hinterlegt."
            )
        return {
            "available": False,
            "price_cycle_available": False,
            "margin_cycle_available": False,
            "status": "Keine verifizierte Primärrohstoff-Zuordnung",
            "required": True,
            "reason": route_reason,
        }

    price_cycle = load_mining_commodity_price_cycle(
        route["commodity_symbol"],
        cache_version,
        normalization_years=route.get("normalization_years", 5),
        current_window_days=route.get("current_window_days", 60),
    )

    result = {
        **price_cycle,
        # ``available`` continues to mean: complete commodity *margin* cycle is
        # usable for the earnings bridge. ``price_cycle_available`` is separate
        # so a company such as Newmont can already show a normalized gold cycle
        # even while company-specific AISC data is still missing.
        "available": False,
        "price_cycle_available": bool(price_cycle.get("available", False)),
        "margin_cycle_available": False,
        "commodity_name": route["commodity_name"],
        "commodity_symbol": route["commodity_symbol"],
        "unit": route["unit"],
        "mapping_note": route.get("mapping_note"),
        "route_source": route.get("route_source"),
        "routing_basis": route.get("routing_basis"),
        "cost_basis_price_assumption": safe_float((snapshot or {}).get("commodity_cost_basis_price_assumption")),
        "cost_basis_note": (snapshot or {}).get("commodity_cost_basis_note"),
        "required": True,
        "aisc_midpoint": None,
        "normalized_margin_per_oz": None,
        "current_margin_per_oz": None,
        "normalized_margin_pct": None,
        "margin_resilience_status": "Daten unzureichend",
    }

    if not price_cycle.get("available", False):
        result["status"] = "Preiszyklus-Daten unzureichend"
        return result

    # Generic cost keys are preferred for future miners. The existing Hecla
    # silver snapshot remains backward compatible through the fallback keys.
    current_low = safe_float((snapshot or {}).get("commodity_aisc_guidance_current_low"))
    current_high = safe_float((snapshot or {}).get("commodity_aisc_guidance_current_high"))
    if current_low is None:
        current_low = safe_float((snapshot or {}).get("silver_aisc_guidance_current_low"))
    if current_high is None:
        current_high = safe_float((snapshot or {}).get("silver_aisc_guidance_current_high"))

    if current_low is None or current_high is None or current_low <= 0 or current_high <= 0:
        result["available"] = False
        result["margin_cycle_available"] = False
        result["status"] = (
            f"{route['commodity_name']}-Preiszyklus normalisiert – "
            "AISC-/Kostenbasis fehlt"
        )
        result["reason"] = (
            f"Der {route['commodity_name']}-Preiszyklus ist belastbar normalisiert, "
            "aber die verifizierte aktuelle AISC-/Stückkostenbasis des Unternehmens "
            "fehlt. Der Preiszyklus wird angezeigt; die Margen- und Ertragskraft-"
            "Überleitung bleibt gesperrt."
        )
        return result

    aisc_midpoint = (current_low + current_high) / 2.0
    normalized_price = safe_float(price_cycle.get("normalized_price"))
    current_reference = safe_float(price_cycle.get("current_reference_price"))

    normalized_margin = (
        normalized_price - aisc_midpoint
        if normalized_price is not None
        else None
    )
    current_margin = (
        current_reference - aisc_midpoint
        if current_reference is not None
        else None
    )

    normalized_margin_pct = None
    if normalized_price is not None and normalized_price > 0 and normalized_margin is not None:
        normalized_margin_pct = normalized_margin / normalized_price * 100.0

    if normalized_margin is None or normalized_margin_pct is None:
        margin_status = "Daten unzureichend"
    elif normalized_margin <= 0:
        margin_status = "Nicht tragfähig"
    elif normalized_margin_pct >= 40.0:
        margin_status = "Sehr stark"
    elif normalized_margin_pct >= 25.0:
        margin_status = "Stark"
    elif normalized_margin_pct >= 10.0:
        margin_status = "Ausreichend"
    else:
        margin_status = "Dünn"

    price_status = price_cycle.get("price_cycle_status") or "Daten unzureichend"
    if margin_status == "Nicht tragfähig":
        overall = "Normalisierte Marge nicht tragfähig"
    elif price_status in ["Extremes Peak-Niveau", "Peak-Niveau"]:
        overall = f"Normalisiert – aktueller Preis auf {price_status}"
    else:
        overall = f"Normalisiert – {price_status}"

    result.update({
        "available": True,
        "price_cycle_available": True,
        "margin_cycle_available": True,
        "status": overall,
        "aisc_midpoint": aisc_midpoint,
        "normalized_margin_per_oz": normalized_margin,
        "current_margin_per_oz": current_margin,
        "normalized_margin_pct": normalized_margin_pct,
        "margin_resilience_status": margin_status,
        "reason": None,
    })
    return result



def build_mining_structural_break_fallback(
    commodity_cycle,
    eps_normalization,
    trailing_eps,
    free_cashflow,
    net_income,
    shares_outstanding,
    operating_snapshot,
    operating_status,
    production_status,
    aisc_status,
    actual_aisc_status,
    fcf_status,
    balance_status,
    fcf_history_supports_fallback=None,
    fcf_post_break_years_count=None,
    fcf_post_break_positive_years=None,
    fcf_post_break_negative_years=None,
):
    """Conservative earnings fallback for post-M&A cyclic miners.

    V2.13.1 never relaxes the minimum post-break history rule. This alternative
    route exists only when the normal cyclical EPS history is blocked by an
    explicitly verified structural break. It down-normalizes current TTM EPS
    with the verified commodity-margin factor. Current FCF/share is an
    accounting cash-conversion cross-check; a scaled FCF/share may be displayed
    on the same normalized basis, but because it uses the *same* margin factor
    it is explicitly not treated as an independent normalization path.

    Production guidance is a mandatory run-rate anchor. It is used to show the
    normalized primary-commodity margin pool, not to manufacture revenue, EPS
    or a mine NAV. The fallback remains only a low-confidence plausibility
    bridge; the separate LOM/NAV hard gate remains fully binding.
    """
    result = {
        "applicable": False,
        "available": False,
        "status": "Nicht erforderlich",
        "confidence": "Niedrig",
        "reason": None,
        "event_name": None,
        "event_date": None,
        "comparable_full_years_count": 0,
        "minimum_full_post_break_years": None,
        "production_midpoint_moz": None,
        "normalized_margin_pool_musd": None,
        "current_margin_pool_musd": None,
        "raw_margin_factor": None,
        "used_margin_factor": None,
        "margin_adjusted_ttm_eps": None,
        "current_fcf_per_share": None,
        "normalized_fcf_per_share": None,
        "eps_fcf_convergence_pct": None,  # legacy alias; see cash_conversion_gap_pct
        "eps_fcf_convergence_status": "Daten unzureichend",  # legacy alias
        "fcf_to_eps_ratio": None,  # legacy alias; same as current_fcf_to_ttm_eps_ratio
        "cash_conversion_gap_pct": None,
        "cash_conversion_status": "Daten unzureichend",
        "current_fcf_to_ttm_eps_ratio": None,
        "fcf_scaled_with_same_margin_factor": True,
        "fcf_scaling_is_independent": False,
        "fcf_post_break_years_count": fcf_post_break_years_count,
        "fcf_post_break_positive_years": fcf_post_break_positive_years,
        "fcf_post_break_negative_years": fcf_post_break_negative_years,
        "fcf_history_supports_fallback": fcf_history_supports_fallback,
        "valuation_earnings_per_share": None,
        "valuation_basis_label": None,
        "shares_basis": None,
        "shares_outstanding_used": None,
        "production_guard_status": production_status,
        "cost_guard_status": aisc_status,
        "actual_cost_guard_status": actual_aisc_status,
        "fcf_history_status": fcf_status,
        "balance_status": balance_status,
    }

    eps_data = eps_normalization if isinstance(eps_normalization, dict) else {}
    if not eps_data.get("normalization_blocked_by_structural_break"):
        return result

    break_info = eps_data.get("structural_break") or {}
    result.update({
        "applicable": True,
        "status": "Structural-Break-Fallback wird geprüft",
        "event_name": break_info.get("event_name"),
        "event_date": break_info.get("event_date"),
        "comparable_full_years_count": int(eps_data.get("comparable_full_years_count") or 0),
        "minimum_full_post_break_years": int(eps_data.get("minimum_full_post_break_years") or 3),
    })

    if not isinstance(commodity_cycle, dict) or not commodity_cycle.get("available", False):
        result["status"] = "Fallback gesperrt – Rohstoff-/Margenzyklus fehlt"
        result["reason"] = (
            "Der Structural-Break-Fallback benötigt einen belastbar normalisierten "
            "Primärrohstoffpreis und eine verifizierte aktuelle AISC-/Kostenbasis."
        )
        return result

    snapshot = operating_snapshot if isinstance(operating_snapshot, dict) else {}
    prod_low = safe_float(_snapshot_first(
        snapshot, "production_guidance_current_low", "production_guidance_current_low_moz"
    ))
    prod_high = safe_float(_snapshot_first(
        snapshot, "production_guidance_current_high", "production_guidance_current_high_moz"
    ))
    production_mid = None
    if prod_low is not None and prod_high is not None and prod_low > 0 and prod_high > 0:
        production_mid = (prod_low + prod_high) / 2.0
    result["production_midpoint_moz"] = production_mid

    if operating_status not in ["Ausreichend", "Stark"] or production_mid is None:
        result["status"] = "Fallback gesperrt – Produktionsbasis nicht belastbar"
        result["reason"] = (
            "Der Structural-Break-Fallback benötigt einen aktuellen verifizierten "
            "Produktions- und Kosten-Snapshot mit positiver Jahres-Run-rate."
        )
        return result

    if production_status not in ["Stabil", "Positiv", "Stark"]:
        result["status"] = "Fallback gesperrt – Produktionswarnung"
        result["reason"] = f"Produktions-Guidance-Status ist {production_status}."
        return result

    if aisc_status not in ["Stabil", "Verbessert", "Stark verbessert"]:
        result["status"] = "Fallback gesperrt – Kostenwarnung"
        result["reason"] = f"AISC-/Kosten-Guidance-Status ist {aisc_status}."
        return result

    if actual_aisc_status == "Schwach":
        result["status"] = "Fallback gesperrt – aktuelle Kosten schwach"
        result["reason"] = "Die aktuell gemeldeten Stückkosten stützen die Guidance nicht ausreichend."
        return result

    if fcf_history_supports_fallback is False:
        result["status"] = "Fallback gesperrt – Post-Break-FCF stützt nicht"
        result["reason"] = (
            f"FCF-Kontrolle nach Strukturbruch ist {fcf_status}. Für den Fallback "
            "werden mindestens zwei vollständig vergleichbare Post-Break-Jahre mit "
            "positivem FCF und ohne negatives Vergleichsjahr verlangt."
        )
        return result
    if fcf_history_supports_fallback is None and fcf_status not in ["Stark", "Ausreichend"]:
        result["status"] = "Fallback gesperrt – FCF-Historie nicht belastbar"
        result["reason"] = f"FCF-Stabilität ist {fcf_status}."
        return result

    if balance_status == "Schwach":
        result["status"] = "Fallback gesperrt – Bilanzwarnung"
        result["reason"] = "Ein schwacher Bilanzpuffer erlaubt keinen Structural-Break-Fallback."
        return result

    normalized_margin = safe_float(commodity_cycle.get("normalized_margin_per_oz"))
    current_margin = safe_float(commodity_cycle.get("current_margin_per_oz"))
    margin_resilience = commodity_cycle.get("margin_resilience_status")
    ttm_eps = safe_float(trailing_eps)
    fcf = safe_float(free_cashflow)

    if (
        normalized_margin is None or current_margin is None
        or normalized_margin <= 0 or current_margin <= 0
        or margin_resilience not in ["Ausreichend", "Stark", "Sehr stark"]
        or ttm_eps is None or ttm_eps <= 0
        or fcf is None or fcf <= 0
    ):
        result["status"] = "Fallback gesperrt – normalisierte Ertragsbasis nicht positiv"
        result["reason"] = (
            "Positive normalisierte Primärrohstoffmarge, positive TTM-Erträge und "
            "positiver Free Cashflow sind Pflicht."
        )
        return result

    raw_factor = normalized_margin / current_margin
    result["raw_margin_factor"] = raw_factor
    # V2.13.1 is deliberately a down-normalization fallback. It never boosts a
    # post-break miner above current earnings when the normalized commodity
    # margin is higher than the current margin.
    if raw_factor <= 0 or raw_factor > 1.0:
        result["status"] = "Fallback gesperrt – keine konservative Down-Normalisierung"
        result["reason"] = (
            "Der Structural-Break-Fallback darf nur aktuelle Peak-/Hochzyklus-Erträge "
            "nach unten normalisieren; eine Aufwärts-Extrapolation wird nicht freigegeben."
        )
        return result

    used_factor = raw_factor
    margin_adjusted_eps = ttm_eps * used_factor
    result["used_margin_factor"] = used_factor
    result["margin_adjusted_ttm_eps"] = margin_adjusted_eps
    result["normalized_margin_pool_musd"] = production_mid * normalized_margin
    result["current_margin_pool_musd"] = production_mid * current_margin

    shares = safe_float(shares_outstanding)
    shares_basis = None
    if shares is not None and shares > 0:
        shares_basis = "Yahoo sharesOutstanding"
    else:
        ni = safe_float(net_income)
        if ni is not None and ni > 0 and ttm_eps > 0:
            shares = ni / ttm_eps
            shares_basis = "Net Income / TTM-EPS (Fallback)"

    if shares is None or shares <= 0:
        result["status"] = "Fallback gesperrt – Aktienzahl fehlt"
        result["reason"] = (
            "Für die FCF-je-Aktie-Cash-Conversion-Kontrolle ist keine belastbare Aktienzahl verfügbar."
        )
        return result

    current_fcf_ps = fcf / shares
    normalized_fcf_ps = current_fcf_ps * used_factor
    result.update({
        "shares_basis": shares_basis,
        "shares_outstanding_used": shares,
        "current_fcf_per_share": current_fcf_ps,
        "normalized_fcf_per_share": normalized_fcf_ps,
    })

    if margin_adjusted_eps <= 0 or normalized_fcf_ps <= 0:
        result["status"] = "Fallback gesperrt – Ertrags-/Cash-Conversion-Basis nicht positiv"
        result["reason"] = "Margenadjustiertes TTM-EPS und aktueller FCF je Aktie müssen positiv sein."
        return result

    # Both normalized views use the same commodity-margin factor. Their gap is
    # therefore mathematically the same as the current FCF/share vs. TTM-EPS
    # cash-conversion gap. V2.13.1 labels it accordingly and never calls it an
    # independent convergence path.
    denominator = max((abs(ttm_eps) + abs(current_fcf_ps)) / 2.0, 0.10)
    cash_conversion_gap = abs(ttm_eps - current_fcf_ps) / denominator * 100.0
    current_fcf_to_eps = current_fcf_ps / ttm_eps

    if cash_conversion_gap <= 15.0:
        cash_conversion_status = "Stark stützend"
    elif cash_conversion_gap <= 25.0:
        cash_conversion_status = "Stützend"
    else:
        cash_conversion_status = "Nicht stützend"

    result.update({
        "cash_conversion_gap_pct": cash_conversion_gap,
        "cash_conversion_status": cash_conversion_status,
        "current_fcf_to_ttm_eps_ratio": current_fcf_to_eps,
        # Backward-compatible aliases for any downstream code. UI no longer
        # presents these as independent EPS/FCF convergence.
        "eps_fcf_convergence_pct": cash_conversion_gap,
        "eps_fcf_convergence_status": cash_conversion_status,
        "fcf_to_eps_ratio": current_fcf_to_eps,
    })

    if cash_conversion_gap > 25.0:
        result["status"] = "Fallback gesperrt – Cash-Conversion stützt nicht"
        result["reason"] = (
            f"Aktueller FCF je Aktie ({current_fcf_ps:.2f}) und TTM-EPS ({ttm_eps:.2f}) "
            f"weichen in der Cash-Conversion-Kontrolle um {cash_conversion_gap:.1f} % voneinander ab; "
            "Plausibilitätsgrenze ≤ 25 %. Der skalierte FCF nutzt denselben Margenfaktor "
            "und ist kein unabhängiger Normalisierungsweg."
        )
        return result

    if not (0.50 <= current_fcf_to_eps <= 1.50):
        result["status"] = "Fallback gesperrt – Cash-Conversion außerhalb Band"
        result["reason"] = (
            f"Aktueller FCF je Aktie / TTM-EPS = {current_fcf_to_eps:.2f}× liegt außerhalb des "
            "konservativen Plausibilitätsbands von 0,50× bis 1,50×."
        )
        return result

    # The valuation earnings basis remains the earnings-derived view. FCF is a
    # hard corroboration, not blended into EPS. This avoids manufacturing an
    # accounting EPS from cash flow.
    result.update({
        "available": True,
        "status": "Fallback-Plausibilitätsanker freigegeben – Cash-Conversion stützt",
        "confidence": "Niedrig",
        "valuation_earnings_per_share": margin_adjusted_eps,
        "valuation_basis_label": "Margenadjustiertes TTM-EPS (diagnostischer Structural-Break-Fallback)",
        "reason": (
            "Die reguläre Zyklus-EPS-Historie bleibt gesperrt. Der Fallback gibt nur einen "
            "niedrig-konfidenten Plausibilitätsanker frei: normalisierte Rohstoffmarge und "
            "aktuelle Produktion/Kosten erlauben eine konservative Down-Normalisierung des TTM-EPS. "
            "Der aktuelle FCF stützt die Cash-Conversion und die vollständig vergleichbaren Post-Break-"
            "FCF-Jahre sind positiv. Der auf dieselbe Basis skalierte FCF je Aktie verwendet jedoch "
            "denselben Margenfaktor und ist ausdrücklich kein unabhängiger Normalisierungsweg. "
            "Der Anker erzeugt weder KGV-Multiple noch Fair Value; das separate Life-of-Mine-/NAV-Gate "
            "bleibt unverändert bindend."
        ),
    })
    return result


def build_mining_earnings_translation(
    commodity_cycle,
    eps_normalization,
    trailing_eps,
    free_cashflow,
    net_income,
    shares_outstanding,
):
    """
    Conservative bridge from normalized commodity economics to sustainable
    company earnings power.

    This is deliberately a *plausibility bridge*, not a direct commodity-price
    model. Two independent earnings views must converge:
      1) the existing multi-year cycle-normalized EPS, and
      2) TTM EPS scaled only by the change in AISC-covered commodity margin.

    FCF/share is scaled by the same margin factor only as a cash-conversion
    cross-check. Mixed-metal exposure, by-product credits and corporate items
    prevent this bridge from being a standalone NAV model.
    """
    result = {
        "available": False,
        "status": "Daten unzureichend",
        "raw_margin_factor": None,
        "used_margin_factor": None,
        "margin_adjusted_ttm_eps": None,
        "cycle_normalized_eps": safe_float((eps_normalization or {}).get("normalized_eps")),
        "eps_convergence_pct": None,
        "eps_convergence_status": "Daten unzureichend",
        "sustainable_eps": None,
        "shares_basis": None,
        "shares_outstanding_used": None,
        "current_fcf_per_share": None,
        "normalized_fcf_per_share": None,
        "fcf_support_ratio": None,
        "fcf_support_status": "Daten unzureichend",
        "translation_confidence": "Niedrig",
        "mixed_metal_guard": True,
        "reason": None,
    }

    if not isinstance(commodity_cycle, dict) or not commodity_cycle.get("available", False):
        if isinstance(commodity_cycle, dict) and commodity_cycle.get("price_cycle_available", False):
            result["reason"] = (
                "Rohstoffpreiszyklus belastbar verfügbar; Margenzyklus mangels "
                "verifizierter AISC-/Kostenbasis noch nicht belastbar."
            )
        else:
            result["reason"] = "Rohstoffpreis-/Margenzyklus ist nicht belastbar verfügbar."
        return result

    normalized_margin = safe_float(commodity_cycle.get("normalized_margin_per_oz"))
    current_margin = safe_float(commodity_cycle.get("current_margin_per_oz"))
    ttm_eps = safe_float(trailing_eps)
    cycle_eps = safe_float((eps_normalization or {}).get("normalized_eps"))

    if (eps_normalization or {}).get("normalization_blocked_by_structural_break"):
        break_info = (eps_normalization or {}).get("structural_break") or {}
        comparable_count = int((eps_normalization or {}).get("comparable_full_years_count") or 0)
        minimum_count = int((eps_normalization or {}).get("minimum_full_post_break_years") or 3)
        result["status"] = "Ertragskraft nicht freigegeben – Structural-Break-Historie zu kurz"
        result["reason"] = (
            f"{break_info.get('event_name', 'Wesentlicher Strukturbruch')} am "
            f"{break_info.get('event_date', '–')}: nur {comparable_count} vollständig "
            f"vergleichbare Geschäftsjahre danach; benötigt werden mindestens {minimum_count}. "
            "Die frühere Konzernhistorie wird nicht als gleichartige Zyklus-EPS-Basis weiterverwendet."
        )
        return result

    if (
        normalized_margin is None or current_margin is None
        or normalized_margin <= 0 or current_margin <= 0
        or ttm_eps is None or ttm_eps <= 0
        or cycle_eps is None or cycle_eps <= 0
    ):
        result["reason"] = (
            "Positive normalisierte/aktuelle Rohstoffmarge sowie positive TTM- "
            "und Zyklus-EPS sind für die Ertragskraft-Überleitung erforderlich."
        )
        return result

    raw_factor = normalized_margin / current_margin
    # Guard against aggressive extrapolation when the current commodity price
    # is below the normal price. Down-normalization is kept intact; upward
    # normalization is capped at +50 %.
    used_factor = max(0.0, min(raw_factor, 1.50))
    margin_adjusted_eps = ttm_eps * used_factor

    denominator = max((abs(margin_adjusted_eps) + abs(cycle_eps)) / 2.0, 0.10)
    convergence_pct = abs(margin_adjusted_eps - cycle_eps) / denominator * 100.0

    if convergence_pct <= 25.0:
        convergence_status = "Stark konvergent"
    elif convergence_pct <= 50.0:
        convergence_status = "Ausreichend konvergent"
    else:
        convergence_status = "Nicht konvergent"

    # Conservative blend: 60 % weight on the lower of both independent views.
    low_eps = min(margin_adjusted_eps, cycle_eps)
    high_eps = max(margin_adjusted_eps, cycle_eps)
    sustainable_eps = 0.60 * low_eps + 0.40 * high_eps

    shares = safe_float(shares_outstanding)
    shares_basis = None
    if shares is not None and shares > 0:
        shares_basis = "Yahoo sharesOutstanding"
    else:
        ni = safe_float(net_income)
        if ni is not None and ni > 0 and ttm_eps > 0:
            shares = ni / ttm_eps
            shares_basis = "Net Income / TTM-EPS (Fallback)"

    current_fcf_ps = None
    normalized_fcf_ps = None
    fcf_support_ratio = None
    fcf_support_status = "Daten unzureichend"

    fcf = safe_float(free_cashflow)
    if shares is not None and shares > 0 and fcf is not None:
        current_fcf_ps = fcf / shares
        normalized_fcf_ps = current_fcf_ps * used_factor
        if sustainable_eps > 0:
            fcf_support_ratio = normalized_fcf_ps / sustainable_eps

        if normalized_fcf_ps <= 0:
            fcf_support_status = "Nicht stützend"
        elif fcf_support_ratio is None:
            fcf_support_status = "Daten unzureichend"
        elif 0.50 <= fcf_support_ratio <= 1.50:
            fcf_support_status = "Stützend"
        elif 0.25 <= fcf_support_ratio < 0.50:
            fcf_support_status = "Teilweise stützend"
        elif fcf_support_ratio > 1.50:
            fcf_support_status = "Stark – Plausibilität prüfen"
        else:
            fcf_support_status = "Schwach"

    convergence_ok = convergence_status in ["Stark konvergent", "Ausreichend konvergent"]
    fcf_ok = fcf_support_status in [
        "Stützend",
        "Teilweise stützend",
        "Stark – Plausibilität prüfen",
    ]

    available = convergence_ok and fcf_ok and sustainable_eps > 0
    release_reason = None
    if available and convergence_status == "Stark konvergent" and fcf_support_status == "Stützend":
        status = "Ertragskraft plausibilisiert – starke Konvergenz"
        translation_confidence = "Mittel"
    elif available:
        status = "Ertragskraft plausibilisiert – mit Vorsicht"
        translation_confidence = "Niedrig"
    elif not convergence_ok:
        status = "Ertragskraft nicht freigegeben – EPS-Wege divergieren"
        translation_confidence = "Niedrig"
        release_reason = (
            f"EPS-Wege nicht ausreichend konvergent: {convergence_pct:.1f} % Abweichung "
            f"zwischen margenadjustiertem TTM-EPS ({margin_adjusted_eps:.2f}) und "
            f"Mehrjahres-/Zyklus-EPS ({cycle_eps:.2f}); Freigabegrenze ≤ 50 %."
        )
    else:
        status = "Ertragskraft nicht freigegeben – FCF stützt nicht ausreichend"
        translation_confidence = "Niedrig"
        if fcf_support_ratio is not None:
            release_reason = (
                f"EPS-Wege sind ausreichend konvergent, aber die FCF-Unterstützung ist "
                f"nicht ausreichend ({fcf_support_status}; FCF/EPS {fcf_support_ratio:.2f}×)."
            )
        else:
            release_reason = (
                f"EPS-Wege sind ausreichend konvergent, aber die FCF-Unterstützung ist "
                f"nicht ausreichend ({fcf_support_status})."
            )

    result.update({
        "available": available,
        "status": status,
        "raw_margin_factor": raw_factor,
        "used_margin_factor": used_factor,
        "margin_adjusted_ttm_eps": margin_adjusted_eps,
        "eps_convergence_pct": convergence_pct,
        "eps_convergence_status": convergence_status,
        "sustainable_eps": sustainable_eps if available else None,
        "shares_basis": shares_basis,
        "shares_outstanding_used": shares,
        "current_fcf_per_share": current_fcf_ps,
        "normalized_fcf_per_share": normalized_fcf_ps,
        "fcf_support_ratio": fcf_support_ratio,
        "fcf_support_status": fcf_support_status,
        "translation_confidence": translation_confidence,
        "reason": release_reason,
    })
    return result




def get_verified_mining_asset_snapshot(symbol):
    """
    Curated reserve / mine-life / technical-NAV reference data for Mining V2.11.

    Company reserve snapshots are kept separate from technical NAV anchors. A
    current reserve statement can therefore be displayed without promoting an
    old or incomplete mine plan to a current company NAV.
    """
    symbol_text = str(symbol or "").upper()

    if symbol_text == "NEM":
        return {
            "company": "Newmont Corporation",
            "primary_commodity": "gold",
            "primary_commodity_label": "Gold",
            "reserve_as_of_date": "31.12.2025",
            "reserve_published_date": "19.02.2026",
            "reserve_valid_until": "31.03.2027",
            "reserve_source_name": "Newmont 2025 Mineral Reserves & Resources",
            "reserve_source_note": (
                "Verifizierte Newmont-Jahresenddaten 2025. Newmont meldet 118,2 Mio. "
                "zurechenbare Unzen Goldreserven. Die 2025er Goldreserven der von "
                "Newmont betriebenen Standorte wurden grundsätzlich mit 2.000 USD/oz "
                "Gold bestimmt; einzelne Joint Ventures/Projekte verwenden abweichende "
                "Preisannahmen. Mineral Resources werden nicht zu Reserven addiert und "
                "nicht in einen Basis-NAV hochgerechnet."
            ),
            # Official attributable proven + probable gold reserves. Asset values
            # below are rounded published site totals and may sum to 118.1 because
            # the company total is reported as 118.2 after table rounding.
            "primary_reserves_moz": {
                "NGM": 17.4,
                "Lihir": 16.0,
                "Cadia": 13.5,
                "Norte Abierto": 10.8,
                "Boddington": 10.2,
                "Ahafo Complex": 8.8,
                "Pueblo Viejo": 8.2,
                "Tanami": 5.3,
                "Wafi-Golpu": 5.1,
                "NuevaUnión": 5.1,
                "Merian": 4.5,
                "Red Chris": 3.6,
                "Peñasquito": 3.2,
                "Cerro Negro": 3.0,
                "Brucejack": 2.9,
                "Yanacocha": 0.5,
            },
            "total_core_primary_reserves_moz": 118.2,
            "reserve_price_basis_primary": 2000.0,
            "reserve_price_basis_gold": 2000.0,
            "reserve_price_basis_copper": 3.75,
            "reserve_price_basis_silver": 25.0,
            "reserve_price_basis_lead": 0.90,
            "reserve_price_basis_zinc": 1.20,
            "reserve_mine_life_years": {},
            "company_average_reserve_mine_life_years": None,
            "mine_life_source_date": "19.02.2026",
            "mine_life_note": (
                "Newmont nennt eine Gold-Reservelebensdauer von mindestens zehn Jahren "
                "für Lihir, Cadia, Tanami, Boddington, Ahafo North, Merian, Cerro Negro, "
                "Brucejack, Nevada Gold Mines und Pueblo Viejo. Die einfache Division "
                "Gesamtreserven / Jahresguidance bleibt nur eine Portfolio-"
                "Kontrollrechnung und ist kein mine-spezifisches Life-of-Mine-Profil."
            ),
            "core_asset_lom_structure": get_verified_newmont_core_asset_lom_structure(),
            "technical_nav_references": [],
            "technical_nav_note": (
                "V2.17.1 behält für Lihir, Cadia, Boddington und den Ahafo Complex die in Phase 1 verifizierten aktuellen "
                "S-K-1300-Technical-Report-Summaries mit LOM-Cashflows. "
                "Phase 1 prüft die TRS-Eignung; Phase 2 normalisiert die vier Assets einzeln. V2.16 trennt weiterhin native Asset-NAVs, eine "
                "Portfolio-Aggregationsschicht mit den offiziellen asset-spezifischen TRS-Raten und die separate 8-%-Vergleichsschicht. "
                "Ein Teil-SOTP darf diagnostisch ausgewiesen werden, wird aber weiterhin nicht zu einem Newmont-Gesamt-NAV hochgestuft. Für die übrigen "
                "weiteren gemanagten operativen Reserve-Assetgruppen fehlt im verifizierten 2025-Form-10-K-Exhibit-Set "
                "weiterhin ein entsprechendes aktuelles TRS."
            ),
        }

    if symbol_text != "HL":
        return None

    return {
        "company": "Hecla Mining Company",
        "primary_commodity": "silver",
        "primary_commodity_label": "Silber",
        "reserve_as_of_date": "31.12.2025",
        "reserve_published_date": "13.02.2026",
        "reserve_valid_until": "31.03.2027",
        "reserve_source_name": "Hecla Year-End 2025 Mineral Reserves & Resources",
        "reserve_source_note": (
            "Verifizierte Hecla-Jahresenddaten 2025. Die Silberreserven der drei "
            "Kern-Silberminen Greens Creek, Lucky Friday und Keno Hill summieren "
            "sich auf rund 231,1 Mio. oz. Mineral Resources sind nicht als "
            "Reserven behandelt und werden im Basis-NAV nicht hochgerechnet."
        ),
        "primary_reserves_moz": {
            "Greens Creek": 106.097,
            "Lucky Friday": 71.589,
            "Keno Hill": 53.407,
        },
        "total_core_primary_reserves_moz": 231.093,
        "reserve_price_basis_primary": 25.00,
        # Legacy aliases kept for the Hecla run-rate DCF.
        "silver_reserves_moz": {
            "Greens Creek": 106.097,
            "Lucky Friday": 71.589,
            "Keno Hill": 53.407,
        },
        "total_core_silver_reserves_moz": 231.093,
        "reserve_price_basis_silver": 25.00,
        "reserve_price_basis_gold": 2100.0,
        "reserve_price_basis_lead": 0.90,
        "reserve_price_basis_zinc": 1.15,
        # No copper reserve-price basis is published for the core silver reserve
        # set used here. V2.11 therefore gives copper by-product credits no value
        # in the normalized run-rate NAV instead of inventing a price.
        "reserve_price_basis_copper": None,
        "reserve_mine_life_years": {
            "Greens Creek": 12.0,
            "Lucky Friday": 15.0,
            "Keno Hill": 13.0,
        },
        "company_average_reserve_mine_life_years": 13.3,
        "mine_life_source_date": "Mai 2026",
        "mine_life_note": (
            "Hecla weist für das Portfolio eine durchschnittliche Reserve-"
            "Minenlebensdauer von 13,3 Jahren aus. Die Unternehmensdarstellung "
            "berechnet Reserve Mine Life aus Reservetonnen / Nameplate-Durchsatz."
        ),
        "technical_nav_references": [
            {
                "asset": "Greens Creek",
                "effective_date": "31.12.2021",
                "discount_rate_pct": 5.0,
                "base_after_tax_npv_musd": 747.0,
                "base_silver_reference": 21.00,
                "sensitivity_points": [
                    (23.10, 1029.0),
                    (25.20, 1313.0),
                ],
                "note": (
                    "S-K 1300 TRS 2021; technische NPV-Sensitivität. Der Report "
                    "ist kein aktueller 2026-NAV."
                ),
            },
            {
                "asset": "Lucky Friday",
                "effective_date": "31.12.2021",
                "discount_rate_pct": 5.0,
                "base_after_tax_npv_musd": 554.0,
                "base_silver_reference": 21.00,
                "sensitivity_points": [
                    (23.10, 721.0),
                    (25.20, 893.0),
                ],
                "note": (
                    "S-K 1300 TRS 2021; technische NPV-Sensitivität. Der Report "
                    "ist kein aktueller 2026-NAV."
                ),
            },
            {
                "asset": "Keno Hill",
                "effective_date": "31.12.2023",
                "discount_rate_pct": 5.0,
                "base_after_tax_npv_musd": 304.5,
                "base_silver_reference": 22.00,
                "sensitivity_points": [
                    (24.20, 369.08),
                    (26.40, 433.68),
                ],
                "note": (
                    "S-K 1300 TRS 2023; technische NPV-Sensitivität. Der Report "
                    "ist jünger als die beiden US-Minen-TRS, bleibt aber ein "
                    "historischer Minenplan."
                ),
            },
        ],
    }

def _linear_interpolate_no_extrapolation(x, points):
    """Linear interpolation only inside verified sensitivity points."""
    x = safe_float(x)
    cleaned = []
    for point in points or []:
        try:
            px, py = point
        except Exception:
            continue
        px = safe_float(px)
        py = safe_float(py)
        if px is not None and py is not None:
            cleaned.append((px, py))

    cleaned = sorted(cleaned, key=lambda item: item[0])
    if x is None or len(cleaned) < 2:
        return None
    if x < cleaned[0][0] or x > cleaned[-1][0]:
        return None

    for (x0, y0), (x1, y1) in zip(cleaned[:-1], cleaned[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            weight = (x - x0) / (x1 - x0)
            return y0 + weight * (y1 - y0)
    return None



def _mining_annuity_factor(years, discount_rate):
    years = safe_float(years)
    discount_rate = safe_float(discount_rate)
    if years is None or years <= 0 or discount_rate is None or discount_rate < 0:
        return None
    if discount_rate == 0:
        return years
    return (1.0 - (1.0 + discount_rate) ** (-years)) / discount_rate


def build_mining_normalized_mine_nav_v26(
    symbol,
    commodity_cycle,
    operating_snapshot,
    asset_snapshot,
    technical_nav_details=None,
):
    """
    Mining V2.7 normalized run-rate mine-NAV control.

    This is deliberately a run-rate reserve DCF, not a substitute for a current
    Life-of-Mine technical model. It uses current verified production guidance,
    the company's AISC-before-by-product reconciliation, current reserve mine
    lives and reserve metal-price assumptions. By-product credits are scaled to
    the reserve-price basis. Missing price bases receive zero credit.

    Final NAV release requires full core-mine coverage and a long-term cost
    profile. Keno Hill remains pre-commercial in the Q2-2026 guidance and has no
    comparable AISC reconciliation, so V2.7 keeps this as a diagnostic/control value until the LOM gate passes.
    """
    result = {
        "available": False,
        "partial_available": False,
        "status": "Daten unzureichend",
        "reason": None,
        "discount_rate_pct": None,
        "effective_tax_rate_pct": None,
        "normalized_silver_price": None,
        "normalized_byproduct_prices": {},
        "mine_details": [],
        "commercial_nav_sum_musd": None,
        "commercial_reserve_coverage_pct": None,
        "all_core_mines_covered": False,
        "long_term_cost_profile_available": False,
        "method_note": (
            "Run-rate DCF auf verifizierter 2026 Guidance. Kein Terminalwert, "
            "keine Resources, keine Explorationsoptionen und keine erfundene "
            "Keno-AISC. Ein Guidance-Jahr ist kein Life-of-Mine-Kostenprofil."
        ),
    }

    symbol_text = str(symbol or "").upper()
    if symbol_text != "HL" or not operating_snapshot or not asset_snapshot:
        if symbol_text == "NEM" and asset_snapshot:
            result["status"] = "Phase-1-TRS-Kandidaten verfügbar – Portfolio-NAV noch gesperrt"
            result["reason"] = (
                "V2.16 trennt Phase-1-TRS-Eignung, native Asset-NAV-Freigabe, Portfolio-Aggregationsfähigkeit und die separate 8-%-Vergleichsschicht. "
                "Die Phase-2-NAV-Freigabe wird assetweise durch das Cashflow-Horizon-&-Closure-Tail-Gate bestimmt. "
                "Die qualitätsbereinigte Abdeckung liegt weiter unter dem 90-%-Gate der gesamten gemanagten operativen Reservebasis; deshalb wird noch kein "
                "Newmont-Portfolio-NAV gerechnet und kein synthetischer Ersatz für fehlende Assets geschätzt."
            )
            result["method_note"] = (
                "Phase 1 ist nur eine Eignungsprüfung. Native TRS-NPVs mit unterschiedlichen asset-spezifischen "
                "Diskontsätzen werden nicht ungeprüft addiert. Ein Portfolio-Guidance-Jahr ersetzt ebenfalls keine "
                "mine-spezifischen LOM-Cashflows."
            )
        else:
            result["reason"] = "Kein verifizierter V2.11-Mine-NAV-Datensatz verfügbar."
        return result

    silver_price = safe_float((commodity_cycle or {}).get("normalized_price"))
    if silver_price is None or silver_price <= 0:
        result["reason"] = "Normalisierter Silberpreis fehlt."
        return result
    result["normalized_silver_price"] = silver_price

    discount_pct = safe_float(operating_snapshot.get("nav_model_discount_rate_pct"))
    if discount_pct is None or discount_pct < 0:
        result["reason"] = "Verifizierter NAV-Diskontsatz fehlt."
        return result
    discount_rate = discount_pct / 100.0
    result["discount_rate_pct"] = discount_pct

    tax_provision = safe_float(operating_snapshot.get("ytd_income_tax_provision_musd"))
    income_after_tax = safe_float(
        operating_snapshot.get("ytd_income_from_continuing_operations_musd")
    )
    effective_tax_rate = None
    if (
        tax_provision is not None
        and tax_provision >= 0
        and income_after_tax is not None
        and income_after_tax > 0
    ):
        pretax = tax_provision + income_after_tax
        if pretax > 0:
            effective_tax_rate = min(max(tax_provision / pretax, 0.0), 0.50)
    result["effective_tax_rate_pct"] = (
        effective_tax_rate * 100.0 if effective_tax_rate is not None else None
    )

    normalized_prices = {
        "gold": safe_float(asset_snapshot.get("reserve_price_basis_gold")),
        "lead": safe_float(asset_snapshot.get("reserve_price_basis_lead")),
        "zinc": safe_float(asset_snapshot.get("reserve_price_basis_zinc")),
        "copper": safe_float(asset_snapshot.get("reserve_price_basis_copper")),
    }
    result["normalized_byproduct_prices"] = normalized_prices
    guidance_prices = operating_snapshot.get("guidance_metal_price_assumptions") or {}
    inputs = operating_snapshot.get("mine_nav_run_rate_inputs") or {}
    mine_lives = asset_snapshot.get("reserve_mine_life_years") or {}
    reserves = asset_snapshot.get("silver_reserves_moz") or {}

    technical_by_asset = {
        str(item.get("asset")): item
        for item in (technical_nav_details or [])
        if isinstance(item, dict) and item.get("asset")
    }

    details = []
    nav_sum = 0.0
    commercial_reserves = 0.0
    calculated_mines = 0

    for asset in ["Greens Creek", "Lucky Friday", "Keno Hill"]:
        mine_input = inputs.get(asset) or {}
        reserve_moz = safe_float(reserves.get(asset))
        life_years = safe_float(mine_lives.get(asset))
        prod_low = safe_float(mine_input.get("production_low_moz"))
        prod_high = safe_float(mine_input.get("production_high_moz"))
        prod_mid = (
            (prod_low + prod_high) / 2.0
            if prod_low is not None and prod_high is not None and prod_low > 0 and prod_high > 0
            else None
        )
        detail = {
            "asset": asset,
            "reserve_moz": reserve_moz,
            "mine_life_years": life_years,
            "production_mid_moz": prod_mid,
            "precommercial": bool(mine_input.get("precommercial")),
            "aisc_before_byproduct_musd": safe_float(
                mine_input.get("aisc_before_byproduct_musd")
            ),
            "normalized_byproduct_credit_musd": None,
            "excluded_byproduct_credit_musd": 0.0,
            "normalized_aisc_after_byproduct_per_oz": None,
            "normalized_margin_per_oz": None,
            "annual_pretax_reserve_cash_musd": None,
            "annual_after_tax_reserve_cash_musd": None,
            "run_rate_nav_musd": None,
            "technical_reference_musd": None,
            "run_rate_vs_technical_gap_pct": None,
            "status": "Nicht berechenbar",
            "note": None,
        }

        if detail["precommercial"]:
            detail["status"] = "Pre-commercial – kein vergleichbares AISC-Profil"
            detail["note"] = (
                "Keno Hill ist in der Q2-2026-Guidance weiterhin vor kommerzieller "
                "Produktion und wird aus der AISC-Reconciliation ausgeschlossen. "
                "V2.7 erfindet deshalb keine Life-of-Mine-Kosten."
            )
            tech = technical_by_asset.get(asset) or {}
            detail["technical_reference_musd"] = safe_float(
                tech.get("normalized_sensitivity_npv_musd")
            )
            details.append(detail)
            continue

        aisc_before = detail["aisc_before_byproduct_musd"]
        if (
            prod_mid is None or prod_mid <= 0 or life_years is None or life_years <= 0
            or aisc_before is None or aisc_before <= 0
        ):
            detail["note"] = "Produktions-, Kosten- oder Minenlebensdaten fehlen."
            details.append(detail)
            continue

        normalized_credit = 0.0
        excluded_credit = 0.0
        for metal, credit in (mine_input.get("byproduct_credits_musd") or {}).items():
            credit = safe_float(credit)
            if credit is None or credit <= 0:
                continue
            guidance_price = safe_float(guidance_prices.get(metal))
            normalized_price = safe_float(normalized_prices.get(metal))
            if guidance_price is None or guidance_price <= 0 or normalized_price is None or normalized_price <= 0:
                excluded_credit += credit
                continue
            normalized_credit += credit * (normalized_price / guidance_price)

        detail["normalized_byproduct_credit_musd"] = normalized_credit
        detail["excluded_byproduct_credit_musd"] = excluded_credit
        normalized_aisc_musd = aisc_before - normalized_credit
        normalized_aisc_per_oz = normalized_aisc_musd / prod_mid
        normalized_margin_per_oz = silver_price - normalized_aisc_per_oz
        annual_pretax = normalized_margin_per_oz * prod_mid

        # No tax benefit is assumed for a negative mine run-rate.
        if annual_pretax > 0 and effective_tax_rate is not None:
            annual_after_tax = annual_pretax * (1.0 - effective_tax_rate)
        else:
            annual_after_tax = annual_pretax

        annuity_factor = _mining_annuity_factor(life_years, discount_rate)
        run_rate_nav = annual_after_tax * annuity_factor if annuity_factor is not None else None

        detail.update({
            "normalized_aisc_after_byproduct_per_oz": normalized_aisc_per_oz,
            "normalized_margin_per_oz": normalized_margin_per_oz,
            "annual_pretax_reserve_cash_musd": annual_pretax,
            "annual_after_tax_reserve_cash_musd": annual_after_tax,
            "run_rate_nav_musd": run_rate_nav,
        })

        tech = technical_by_asset.get(asset) or {}
        tech_value = safe_float(tech.get("normalized_sensitivity_npv_musd"))
        detail["technical_reference_musd"] = tech_value
        if run_rate_nav is not None and run_rate_nav > 0 and tech_value is not None and tech_value > 0:
            midpoint = (run_rate_nav + tech_value) / 2.0
            detail["run_rate_vs_technical_gap_pct"] = (
                abs(run_rate_nav - tech_value) / midpoint * 100.0 if midpoint > 0 else None
            )

        if run_rate_nav is None:
            detail["status"] = "Nicht berechenbar"
        elif normalized_margin_per_oz <= 0:
            detail["status"] = "2026 Run-rate unter Zykluspreis nicht tragfähig"
            detail["note"] = (
                "Die aktuelle Jahres-Guidance ergibt am normalisierten Metallpreis "
                "keine positive Reserve-Cash-Marge. Das ist ein Warnsignal gegen "
                "die Verwendung eines einzelnen Guidance-Jahres als LOM-Profil."
            )
        else:
            gap = detail.get("run_rate_vs_technical_gap_pct")
            if gap is not None and gap <= 35.0:
                detail["status"] = "Run-rate plausibel"
            elif gap is not None:
                detail["status"] = "Run-rate / technischer NAV divergieren"
            else:
                detail["status"] = "Run-rate berechnet – Referenzvergleich begrenzt"

        if run_rate_nav is not None:
            nav_sum += run_rate_nav
            calculated_mines += 1
            if reserve_moz is not None and reserve_moz > 0:
                commercial_reserves += reserve_moz
        details.append(detail)

    total_reserves = safe_float(asset_snapshot.get("total_core_silver_reserves_moz"))
    coverage_pct = None
    if total_reserves is not None and total_reserves > 0:
        coverage_pct = commercial_reserves / total_reserves * 100.0

    result.update({
        "mine_details": details,
        "partial_available": calculated_mines >= 2,
        "commercial_nav_sum_musd": nav_sum if calculated_mines else None,
        "commercial_reserve_coverage_pct": coverage_pct,
        "all_core_mines_covered": calculated_mines >= 3,
    })

    # V2.7 deliberately does not claim a full current NAV. A current annual AISC
    # reconciliation cannot replace mine-by-mine Life-of-Mine costs, and Keno
    # Hill still lacks a comparable commercial AISC profile.
    if calculated_mines < 2:
        result["status"] = "Normalisierter Mine-NAV nicht ausreichend berechenbar"
        result["reason"] = "Zu wenige Kernminen besitzen vergleichbare verifizierte Run-rate-Daten."
    elif not result["all_core_mines_covered"]:
        result["status"] = "Teil-NAV verfügbar – Keno/LOM-Kostenprofil noch offen"
        result["reason"] = (
            "Für Greens Creek und Lucky Friday ist ein normalisierter Run-rate-DCF "
            "berechenbar. Keno Hill besitzt noch kein vergleichbares kommerzielles "
            "AISC-Profil; außerdem ist 2026-Guidance kein Life-of-Mine-Kostenplan. "
            "Der Wert bleibt deshalb Kontrollgröße und darf keinen finalen Fair "
            "Value freigeben."
        )
    else:
        result["status"] = "Run-rate NAV berechnet – LOM-Kostenprofil noch zu bestätigen"
        result["reason"] = (
            "Alle Kernminen sind rechnerisch abgedeckt, aber ein einzelnes "
            "Guidance-Jahr ersetzt noch kein belastbares Life-of-Mine-Kostenprofil."
        )

    return result


def build_mining_lom_release_gate_v27(
    asset_snapshot,
    normalized_mine_nav,
    technical_nav_details,
):
    """
    Mining V2.7 formal Life-of-Mine release gate.

    The gate does not create missing mine economics. It only decides whether the
    already available reserve, run-rate and technical-plan evidence is complete
    enough for a final mining NAV. Current annual guidance is never promoted to
    a Life-of-Mine cost curve.
    """
    result = {
        "available": False,
        "released": False,
        "status": "LOM-Gate nicht prüfbar",
        "reason": None,
        "minimum_release_reserve_coverage_pct": 90.0,
        "maximum_unmodeled_material_reserve_pct": 10.0,
        "maximum_technical_plan_age_years": 3.0,
        "annual_run_rate_reserve_coverage_pct": None,
        "current_technical_plan_reserve_coverage_pct": None,
        "release_ready_lom_reserve_coverage_pct": None,
        "unmodeled_or_precommercial_reserve_pct": None,
        "material_mine_threshold_pct": 10.0,
        "material_mines_total": 0,
        "material_mines_release_ready": 0,
        "mine_specific_lom_tax_capex_available": False,
        "single_year_guidance_guard_active": True,
        "mine_details": [],
        "gate_checks": {},
        "blocking_reasons": [],
        "method_note": (
            "V2.7 ist ein Freigabe-Gate, kein zusätzlicher Schätzer. Mindestens "
            "90 % der Kernreserven müssen durch aktuelle technische Minenpläne "
            "und belastbare mine-spezifische Life-of-Mine-Kosten-/CapEx-Profile "
            "abgedeckt sein. Ein einzelnes Guidance-Jahr zählt ausdrücklich nicht "
            "als LOM-Profil."
        ),
    }

    if not isinstance(asset_snapshot, dict) or not isinstance(normalized_mine_nav, dict):
        result["reason"] = "Reserve- oder Run-rate-NAV-Daten fehlen."
        return result

    reserves = asset_snapshot.get("silver_reserves_moz") or {}
    total_reserves = safe_float(asset_snapshot.get("total_core_silver_reserves_moz"))
    if total_reserves is None or total_reserves <= 0:
        result["reason"] = "Kernreservebasis fehlt."
        return result

    run_rate_by_asset = {
        str(item.get("asset")): item
        for item in (normalized_mine_nav.get("mine_details") or [])
        if isinstance(item, dict) and item.get("asset")
    }
    technical_by_asset = {
        str(item.get("asset")): item
        for item in (technical_nav_details or [])
        if isinstance(item, dict) and item.get("asset")
    }

    annual_coverage_reserves = 0.0
    current_technical_reserves = 0.0
    release_ready_reserves = 0.0
    unmodeled_reserves = 0.0
    material_total = 0
    material_ready = 0
    mine_rows = []

    for asset in ["Greens Creek", "Lucky Friday", "Keno Hill"]:
        reserve_moz = safe_float(reserves.get(asset)) or 0.0
        reserve_share_pct = reserve_moz / total_reserves * 100.0 if total_reserves > 0 else 0.0
        material = reserve_share_pct >= result["material_mine_threshold_pct"]
        if material:
            material_total += 1

        run_rate = run_rate_by_asset.get(asset) or {}
        technical = technical_by_asset.get(asset) or {}

        annual_profile_available = (
            safe_float(run_rate.get("run_rate_nav_musd")) is not None
            and not bool(run_rate.get("precommercial"))
        )
        technical_plan_current = bool(technical.get("reference_fresh"))
        technical_age_years = safe_float(technical.get("age_years"))

        # V2.7 currently has no verified current mine-by-mine LOM cost/CapEx
        # schedule. Annual 2026 guidance and an old technical NPV are not merged
        # into a synthetic LOM curve.
        lom_cost_profile_current = False
        mine_specific_tax_capex_current = False
        release_ready = (
            annual_profile_available
            and technical_plan_current
            and lom_cost_profile_current
            and mine_specific_tax_capex_current
        )

        if annual_profile_available:
            annual_coverage_reserves += reserve_moz
        else:
            unmodeled_reserves += reserve_moz
        if technical_plan_current:
            current_technical_reserves += reserve_moz
        if release_ready:
            release_ready_reserves += reserve_moz
            if material:
                material_ready += 1

        if release_ready:
            status = "LOM-freigabefähig"
        elif not annual_profile_available:
            status = "Kein aktuelles kommerzielles Kostenprofil"
        elif not technical_plan_current:
            status = "Technischer Minenplan zu alt"
        elif not lom_cost_profile_current:
            status = "Aktuelles LOM-Kosten-/CapEx-Profil fehlt"
        else:
            status = "Mine-spezifische LOM-Steuer/CapEx-Basis fehlt"

        mine_rows.append({
            "asset": asset,
            "reserve_moz": reserve_moz,
            "reserve_share_pct": reserve_share_pct,
            "material": material,
            "annual_run_rate_profile_available": annual_profile_available,
            "technical_plan_current": technical_plan_current,
            "technical_plan_age_years": technical_age_years,
            "lom_cost_profile_current": lom_cost_profile_current,
            "mine_specific_tax_capex_current": mine_specific_tax_capex_current,
            "release_ready": release_ready,
            "status": status,
        })

    annual_pct = annual_coverage_reserves / total_reserves * 100.0
    technical_pct = current_technical_reserves / total_reserves * 100.0
    release_pct = release_ready_reserves / total_reserves * 100.0
    unmodeled_pct = unmodeled_reserves / total_reserves * 100.0

    min_coverage = result["minimum_release_reserve_coverage_pct"]
    max_unmodeled = result["maximum_unmodeled_material_reserve_pct"]
    checks = {
        "annual_run_rate_coverage_ok": annual_pct >= min_coverage,
        "current_technical_plan_coverage_ok": technical_pct >= min_coverage,
        "release_ready_lom_coverage_ok": release_pct >= min_coverage,
        "unmodeled_reserve_ok": unmodeled_pct <= max_unmodeled,
        "all_material_mines_ready": material_total > 0 and material_ready == material_total,
        "mine_specific_lom_tax_capex_ok": False,
        "single_year_guidance_guard_ok": True,
    }

    blocking = []
    if not checks["annual_run_rate_coverage_ok"]:
        blocking.append(
            f"Run-rate-Kostenprofil deckt nur {annual_pct:.1f} % der Kernreserven ab; erforderlich sind ≥ {min_coverage:.0f} %."
        )
    if not checks["current_technical_plan_coverage_ok"]:
        blocking.append(
            f"Aktuelle technische Minenpläne (≤ {result['maximum_technical_plan_age_years']:.0f} Jahre) decken nur {technical_pct:.1f} % der Kernreserven ab."
        )
    if not checks["release_ready_lom_coverage_ok"]:
        blocking.append(
            f"Belastbare aktuelle LOM-Kosten-/CapEx-Profile decken {release_pct:.1f} % der Kernreserven ab; erforderlich sind ≥ {min_coverage:.0f} %."
        )
    if not checks["unmodeled_reserve_ok"]:
        blocking.append(
            f"Nicht kommerziell modellierte Kernreserven liegen bei {unmodeled_pct:.1f} % und damit über der {max_unmodeled:.0f}-%-Grenze."
        )
    if not checks["all_material_mines_ready"]:
        blocking.append(
            f"Nur {material_ready} von {material_total} wesentlichen Kernminen sind LOM-freigabefähig."
        )
    if not checks["mine_specific_lom_tax_capex_ok"]:
        blocking.append(
            "Mine-spezifische langfristige Steuer-, Sustaining-CapEx- und Kostenverläufe sind noch nicht vollständig verifiziert."
        )

    released = all(checks.values())
    status = (
        "LOM-Gate freigegeben"
        if released
        else "LOM-Gate gesperrt – aktuelle Life-of-Mine-Profile unvollständig"
    )
    reason = None if released else " ".join(blocking)

    result.update({
        "available": True,
        "released": released,
        "status": status,
        "reason": reason,
        "annual_run_rate_reserve_coverage_pct": annual_pct,
        "current_technical_plan_reserve_coverage_pct": technical_pct,
        "release_ready_lom_reserve_coverage_pct": release_pct,
        "unmodeled_or_precommercial_reserve_pct": unmodeled_pct,
        "material_mines_total": material_total,
        "material_mines_release_ready": material_ready,
        "mine_details": mine_rows,
        "gate_checks": checks,
        "blocking_reasons": blocking,
    })
    return result




def get_verified_newmont_managed_source_coverage_map():
    """
    V2.17.1 source-coverage audit for the seven Newmont managed operating reserve
    groups that are still outside the current 2025 S-K 1300 Phase-1 set.

    This module classifies source quality only. It does not create, roll forward,
    interpolate or estimate a NAV. Reserve figures are the attributable 2025
    reserve figures already used by the portfolio layer; ownership percentages
    are shown for auditability and must not be applied a second time to those
    reserve figures.
    """
    rows = [
        {
            "asset": "Tanami",
            "reserve_moz": 5.3,
            "ownership_pct": 100.0,
            "current_corporate_data": True,
            "current_full_trs": False,
            "historical_technical_anchor": True,
            "latest_technical_source": "NI 43-101 Technical Report – Tanami Operations",
            "technical_effective_date": "31.12.2018",
            "source_class": "B – historischer technischer Bericht",
            "complexity": "Gold-Untertagebau + Tanami Expansion 2",
            "phase2_ready": False,
            "next_requirement": "Aktueller LOM-/Cashflow-/Closure-Roll-forward auf 2025/2026 erforderlich",
            "note": (
                "Der 2025 Form 10-K liefert aktuelle Reserven und die 2026-Unternehmensplanung; "
                "der verifizierte technische Vollbericht stammt jedoch aus 2018. Expansion 2 und "
                "heutige Kosten-/CapEx-/Closure-Pfade dürfen nicht aus dem alten Bericht fortgeschrieben werden."
            ),
        },
        {
            "asset": "Merian",
            "reserve_moz": 4.5,
            "ownership_pct": 75.0,
            "current_corporate_data": True,
            "current_full_trs": False,
            "historical_technical_anchor": False,
            "latest_technical_source": "Kein verifizierter vollständiger aktueller/historischer LOM-TRS in der V2.17.1-Quellenprüfung",
            "technical_effective_date": None,
            "source_class": "C – aktuelle Unternehmensdaten, kein Voll-LOM-Bericht",
            "complexity": "Gold-Tagebau; Newmont 75 %, Reserven bereits zurechenbar",
            "phase2_ready": False,
            "next_requirement": "Belastbaren LOM-Minenplan mit Kosten, CapEx, Steuer/Royalty und Closure beschaffen",
            "note": (
                "2025 Form 10-K und 2026 Guidance sind aktuell, ersetzen aber keinen vollständigen "
                "Minen-Cashflow. Die 4,5 Mio. oz sind bereits zurechenbare Reserven; 75 % Eigentum "
                "darf bei der Reserveabdeckung nicht nochmals angewendet werden."
            ),
        },
        {
            "asset": "Cerro Negro",
            "reserve_moz": 3.0,
            "ownership_pct": 100.0,
            "current_corporate_data": True,
            "current_full_trs": False,
            "historical_technical_anchor": True,
            "latest_technical_source": "NI 43-101 Technical Report – Cerro Negro Operations",
            "technical_effective_date": "31.12.2015",
            "source_class": "B – historischer technischer Bericht",
            "complexity": "Gold/Silber-Untertagebau + aktuelle Minenlebensverlängerung",
            "phase2_ready": False,
            "next_requirement": "Neuer LOM-/Kosten-/CapEx-/Closure-Datensatz; 2015-Bericht nur Referenzanker",
            "note": (
                "Der historische Goldcorp-Bericht ist zu alt für eine heutige NAV-Freigabe. "
                "Aktuelle Reserven, 2026 Guidance und Mine-Life-Extension-Aktivitäten werden nur als "
                "Betriebs-/Quellenkontrolle verwendet."
            ),
        },
        {
            "asset": "Yanacocha",
            "reserve_moz": 0.5,
            "ownership_pct": 100.0,
            "current_corporate_data": True,
            "current_full_trs": False,
            "historical_technical_anchor": False,
            "latest_technical_source": "Kein verifizierter vollständiger aktueller LOM-TRS für die heutige Betriebsstruktur",
            "technical_effective_date": None,
            "source_class": "C – aktuelle Unternehmensdaten + Übergangs-/Projektstruktur",
            "complexity": "Leach-Betrieb 2026/27 + separater Sulfides-Projektpfad",
            "phase2_ready": False,
            "next_requirement": "Operativen Leach-NAV strikt vom Sulfides-Projektwert trennen",
            "note": (
                "Die aktuelle Operation wird als Leach-Betrieb verlängert, während Yanacocha Sulfides "
                "ein separater Projektpfad ist. Reserve-/Projektwerte dürfen nicht in einem synthetischen "
                "LOM-Modell vermischt werden."
            ),
        },
        {
            "asset": "Peñasquito",
            "reserve_moz": 3.2,
            "ownership_pct": 100.0,
            "current_corporate_data": True,
            "current_full_trs": False,
            "historical_technical_anchor": True,
            "latest_technical_source": "S-K 1300 TRS – Peñasquito Operations (Exhibit 96.1 im 2023 Form 10-K)",
            "technical_effective_date": "31.12.2023",
            "source_class": "B+ – jüngerer TRS, aber nicht 2025-current",
            "complexity": "Polymetallisch: Gold, Silber, Blei, Zink",
            "phase2_ready": False,
            "next_requirement": "TRS auf 2025 roll-forwarden + echte Multi-Metal-Preisnormalisierung",
            "note": (
                "Peñasquito besitzt den jüngsten belastbaren technischen Anker der sieben offenen Assets, "
                "ist aber kein Gold-only-Asset. Das negative Gold-AISC durch By-Product-Credits bestätigt, "
                "dass ein eigenständiger Gold-NAV methodisch ungeeignet wäre."
            ),
        },
        {
            "asset": "Red Chris",
            "reserve_moz": 3.6,
            "ownership_pct": 70.0,
            "current_corporate_data": True,
            "current_full_trs": False,
            "historical_technical_anchor": True,
            "latest_technical_source": "NI 43-101 Technical Report / Block Cave PFS – Red Chris",
            "technical_effective_date": "30.06.2021",
            "source_class": "B – historischer technischer Bericht + laufender Projekt-Overlay",
            "complexity": "Gold/Kupfer; 70-%-JV; Open Pit + Block-Cave-Projekt",
            "phase2_ready": False,
            "next_requirement": "Aktuelle Feasibility-/LOM-Basis und klare Trennung Betrieb vs. Block Cave",
            "note": (
                "Der 2021-Bericht/PFS ist ein historischer Referenzanker. Die 3,6 Mio. oz in der Newmont-Reservebasis "
                "sind bereits zurechenbare Reserven; der 70-%-Eigentumsanteil darf bei der Reserveabdeckung nicht "
                "nochmals angewendet werden. Für eine spätere Bewertung von 100-%-Projekt-Cashflows bleibt der "
                "Eigentumsanteil dagegen separat relevant. Laufende Open-Pit-/Stockpile-Produktion und das "
                "Block-Cave-Projekt benötigen außerdem einen aktuellen gemeinsamen Bewertungsstichtag und Multi-Metal-Ansatz."
            ),
        },
        {
            "asset": "Brucejack",
            "reserve_moz": 2.9,
            "ownership_pct": 100.0,
            "current_corporate_data": True,
            "current_full_trs": False,
            "historical_technical_anchor": True,
            "latest_technical_source": "NI 43-101 Technical Report – Brucejack Gold Mine",
            "technical_effective_date": "09.03.2020 (Reserven 01.01.2020)",
            "source_class": "B – historischer technischer Bericht",
            "complexity": "Hochgradiger Gold/Silber-Untertagebau",
            "phase2_ready": False,
            "next_requirement": "Aktueller LOM-/Reserve-/Kosten-/Closure-Roll-forward erforderlich",
            "note": (
                "Der 2020-Bericht enthält einen vollständigen historischen LOM- und Economic-Analysis-Anker, "
                "ist nach mehreren Jahren Produktion und Reserveänderungen aber nicht current genug für Phase 2."
            ),
        },
    ]

    open_reserves = sum(float(r.get("reserve_moz") or 0.0) for r in rows)
    historical_rows = [r for r in rows if r.get("historical_technical_anchor")]
    historical_reserves = sum(float(r.get("reserve_moz") or 0.0) for r in historical_rows)
    current_full_rows = [r for r in rows if r.get("current_full_trs")]
    current_full_reserves = sum(float(r.get("reserve_moz") or 0.0) for r in current_full_rows)
    phase2_rows = [r for r in rows if r.get("phase2_ready")]
    phase2_reserves = sum(float(r.get("reserve_moz") or 0.0) for r in phase2_rows)

    special_assets = {"Peñasquito", "Red Chris", "Yanacocha"}
    special_reserves = sum(float(r.get("reserve_moz") or 0.0) for r in rows if r.get("asset") in special_assets)

    return {
        "available": True,
        "version": "V2.17.1",
        "status": "7 offene Managed-Assetgruppen klassifiziert – noch kein zusätzliches Phase-2-Asset freigegeben",
        "as_of_date": "07.09.2026",
        "current_source_basis": "Newmont 2025 Form 10-K + 2025 Reserves + 2026 Guidance + verifizierte historische technische Berichte",
        "open_asset_count": len(rows),
        "open_reserves_moz": open_reserves,
        "current_full_trs_asset_count": len(current_full_rows),
        "current_full_trs_reserves_moz": current_full_reserves,
        "historical_anchor_asset_count": len(historical_rows),
        "historical_anchor_reserves_moz": historical_reserves,
        "historical_anchor_open_coverage_pct": (historical_reserves / open_reserves * 100.0 if open_reserves else 0.0),
        "phase2_ready_asset_count": len(phase2_rows),
        "phase2_ready_reserves_moz": phase2_reserves,
        "special_model_reserves_moz": special_reserves,
        "assets": rows,
        "reason": (
            "V2.17.1 erweitert nur die Quellenlandkarte. Keines der sieben offenen Assets wird allein wegen eines "
            "historischen Technical Reports oder aktueller Guidance in die Phase-2-/SOTP-Abdeckung aufgenommen. "
            "Historische Berichte sind Referenzanker; aktuelle LOM-/Kosten-/CapEx-/Closure-Daten bleiben Pflicht."
        ),
    }

def get_verified_newmont_technical_lom_phase1():
    """
    Newmont V2.14.1 technical LOM/NAV Phase 1 + portfolio coverage denominator control.

    This is an eligibility audit, not a portfolio NAV. Newmont's 2025 Form 10-K
    includes current S-K 1300 Technical Report Summaries for Boddington, Cadia,
    Lihir and the Ahafo Complex (Exhibits 96.1-96.4; effective 31.12.2025).

    V2.14.1 no longer uses a hand-picked "managed core" subset as the binding
    denominator. The release gate is measured against all attributable gold
    reserves of Newmont's managed operating portfolio. Ahafo North and Ahafo
    South are one reserve/TRS asset group (Ahafo Complex), so the 12 managed
    operating sites correspond to 11 reserve asset groups for this coverage
    calculation.
    """
    total_portfolio_reserves_moz = 118.2
    managed_operating_reserves_moz = 71.5
    verified_trs_reserves_moz = 48.5
    required_managed_operating_coverage_pct = 90.0

    # Retained only as a diagnostic of the old V2.14 denominator; it is no
    # longer used by any release gate in V2.14.1.
    legacy_managed_core_reserves_moz = 64.2

    eligible_assets = [
        {
            "asset": "Lihir", "reserve_moz": 16.0,
            "trs_exhibit": "96.3", "effective_date": "31.12.2025", "report_date": "Februar 2026",
            "current_trs": True, "production_schedule": True, "operating_costs": True,
            "capital_costs": True, "taxes_royalties": True, "annual_cashflows": True,
            "gold_price_usd_oz": 2000.0, "discount_rate_pct": 10.0,
            "native_after_tax_npv_musd": 2000.0, "native_fcf_musd": 3100.0,
            "lom_capital_musd": 2200.0, "lom_operating_cost_musd": 16100.0,
            "active_mining_end_year": 2040, "processing_end_year": 2043,
            "nav_candidate_phase1": True,
            "note": "Aktuelles TRS; LOM-Cashflow vollständig genug für eine spätere Asset-NAV-Normalisierung. Native NPV10 nur Referenz."
        },
        {
            "asset": "Cadia", "reserve_moz": 13.5,
            "trs_exhibit": "96.2", "effective_date": "31.12.2025", "report_date": "Februar 2026",
            "current_trs": True, "production_schedule": True, "operating_costs": True,
            "capital_costs": True, "taxes_royalties": True, "annual_cashflows": True,
            "gold_price_usd_oz": 2000.0, "discount_rate_pct": 5.0,
            "native_after_tax_npv_musd": 2600.0, "native_fcf_musd": 5300.0,
            "lom_capital_musd": 9700.0, "lom_operating_cost_musd": 22000.0,
            "active_mining_end_year": 2056, "processing_end_year": 2056,
            "nav_candidate_phase1": True,
            "note": "Aktuelles TRS mit jährlichen LOM-Cashflows; native NPV5 nur Asset-Referenz. Genehmigungs-/TSF-Risiken bleiben separat zu beachten."
        },
        {
            "asset": "Boddington", "reserve_moz": 10.2,
            "trs_exhibit": "96.1", "effective_date": "31.12.2025", "report_date": "Februar 2026",
            "current_trs": True, "production_schedule": True, "operating_costs": True,
            "capital_costs": True, "taxes_royalties": True, "annual_cashflows": True,
            "gold_price_usd_oz": 2000.0, "discount_rate_pct": 5.0,
            "native_after_tax_npv_musd": 1500.0, "native_fcf_musd": 2200.0,
            "lom_capital_musd": 3300.0, "lom_operating_cost_musd": 12300.0,
            "active_mining_end_year": 2040, "processing_end_year": 2040,
            "nav_candidate_phase1": True,
            "note": "Aktuelles TRS mit annualisiertem Cashflow bis 2040; native NPV5 nur Asset-Referenz."
        },
        {
            "asset": "Ahafo Complex", "reserve_moz": 8.8,
            "trs_exhibit": "96.4", "effective_date": "31.12.2025", "report_date": "Februar 2026",
            "current_trs": True, "production_schedule": True, "operating_costs": True,
            "capital_costs": True, "taxes_royalties": True, "annual_cashflows": True,
            "gold_price_usd_oz": 2000.0, "discount_rate_pct": 8.0,
            "native_after_tax_npv_musd": 1700.0, "native_fcf_musd": 2700.0,
            "lom_capital_musd": 1600.0, "lom_operating_cost_musd": 7300.0,
            "active_mining_end_year": 2044, "processing_end_year": 2044,
            "nav_candidate_phase1": True,
            "note": "TRS berichtet Ahafo North und Ahafo South gemeinsam als Ahafo Complex; Phase 1 rechnet den nativen NPV noch nicht in einen Portfolio-NAV um."
        },
    ]

    managed_operating_reserve_groups = [
        {"asset": "Lihir", "reserve_moz": 16.0},
        {"asset": "Cadia", "reserve_moz": 13.5},
        {"asset": "Tanami", "reserve_moz": 5.3},
        {"asset": "Boddington", "reserve_moz": 10.2},
        {"asset": "Ahafo Complex", "reserve_moz": 8.8},
        {"asset": "Merian", "reserve_moz": 4.5},
        {"asset": "Cerro Negro", "reserve_moz": 3.0},
        {"asset": "Yanacocha", "reserve_moz": 0.5},
        {"asset": "Peñasquito", "reserve_moz": 3.2},
        {"asset": "Red Chris", "reserve_moz": 3.6},
        {"asset": "Brucejack", "reserve_moz": 2.9},
    ]

    missing_current_trs_assets = [
        {"asset": "Tanami", "reserve_moz": 5.3, "reason": "Kein separates aktuelles Exhibit-96-TRS im verifizierten Newmont-2025-Form-10-K-Set."},
        {"asset": "Merian", "reserve_moz": 4.5, "reason": "Kein separates aktuelles Exhibit-96-TRS im verifizierten Newmont-2025-Form-10-K-Set."},
        {"asset": "Cerro Negro", "reserve_moz": 3.0, "reason": "Kein separates aktuelles Exhibit-96-TRS im verifizierten Newmont-2025-Form-10-K-Set."},
        {"asset": "Yanacocha", "reserve_moz": 0.5, "reason": "Gemanagte operative Reservebasis mit 2026-Guidance, aber kein gleichwertiges aktuelles Exhibit-96-TRS im verifizierten Set."},
        {"asset": "Peñasquito", "reserve_moz": 3.2, "reason": "Gemanagte operative Reservebasis mit 2026-Guidance, aber kein gleichwertiges aktuelles Exhibit-96-TRS im verifizierten Set."},
        {"asset": "Red Chris", "reserve_moz": 3.6, "reason": "Gemanagte operative Reservebasis; laufender Betrieb/Projektentwicklung ersetzt kein aktuelles vollständiges LOM-TRS."},
        {"asset": "Brucejack", "reserve_moz": 2.9, "reason": "Kein separates aktuelles Exhibit-96-TRS im verifizierten Newmont-2025-Form-10-K-Set."},
    ]

    nav_eligible_managed_operating_coverage_pct = (
        verified_trs_reserves_moz / managed_operating_reserves_moz * 100.0
    )
    total_portfolio_coverage_pct = verified_trs_reserves_moz / total_portfolio_reserves_moz * 100.0
    legacy_managed_core_coverage_pct = verified_trs_reserves_moz / legacy_managed_core_reserves_moz * 100.0
    unmodeled_managed_operating_reserves_moz = managed_operating_reserves_moz - verified_trs_reserves_moz
    coverage_ok = nav_eligible_managed_operating_coverage_pct >= required_managed_operating_coverage_pct

    missing_names = ", ".join(x["asset"] for x in missing_current_trs_assets)
    return {
        "available": True,
        "status": (
            "Phase 1 vollständig – ausreichende Abdeckung der gemanagten operativen Reserven"
            if coverage_ok else
            "Phase 1 teilweise bestanden – TRS-Abdeckung der gemanagten operativen Reserven unter 90 %"
        ),
        "as_of_date": "31.12.2025",
        "published_date": "19.02.2026",
        "source_name": "Newmont 2025 Form 10-K – S-K 1300 TRS Exhibits 96.1–96.4 + 2026 Managed Portfolio Guidance",
        "source_note": (
            "V2.14.2 verwendet weiterhin als bindenden Managed-Operations-Nenner alle zurechenbaren Goldreserven des gemanagten operativen "
            "Portfolios: 71,5 Mio. oz. Newmont führt 2026 zwölf gemanagte Operations; Ahafo North und Ahafo South "
            "werden in der Reserve-/TRS-Abdeckung als Ahafo Complex zusammengefasst, sodass elf Reserve-Assetgruppen "
            "entstehen. Die vier aktuellen TRS für Boddington, Cadia, Lihir und Ahafo decken 48,5 Mio. oz ab. "
            "Nicht gemanagte JVs und Entwicklungsprojekte bleiben separate Portfolio-Schichten. Rundungsdifferenzen "
            "zur gemeldeten Gesamtreserve von 118,2 Mio. oz sind möglich."
        ),
        "total_portfolio_reserves_moz": total_portfolio_reserves_moz,
        "managed_operating_reserves_moz": managed_operating_reserves_moz,
        "nav_eligible_reserves_moz": verified_trs_reserves_moz,
        "verified_trs_reserves_moz": verified_trs_reserves_moz,
        "nav_eligible_managed_operating_coverage_pct": nav_eligible_managed_operating_coverage_pct,
        "managed_operating_coverage_pct": nav_eligible_managed_operating_coverage_pct,
        "total_portfolio_coverage_pct": total_portfolio_coverage_pct,
        "required_managed_operating_coverage_pct": required_managed_operating_coverage_pct,
        "gate_denominator": "managed_operating_reserves",
        "gate_denominator_label": "Gemanagte operative Goldreserven",
        "unmodeled_managed_operating_reserves_moz": unmodeled_managed_operating_reserves_moz,
        "eligible_asset_count": len(eligible_assets),
        "managed_operating_asset_group_count": len(managed_operating_reserve_groups),
        "managed_operating_site_count": 12,
        "managed_operating_reserve_groups": managed_operating_reserve_groups,
        "managed_source_coverage_map": get_verified_newmont_managed_source_coverage_map(),
        "eligible_assets": eligible_assets,
        "missing_current_trs_assets": missing_current_trs_assets,
        "coverage_ok": coverage_ok,
        "phase1_nav_candidates_verified": True,
        "phase1_portfolio_nav_release_ready": False,
        # Legacy aliases retained only so older diagnostics/tests do not crash.
        # They are NOT used by the V2.14.1 release gate.
        "managed_core_reserves_moz": legacy_managed_core_reserves_moz,
        "managed_core_coverage_pct": legacy_managed_core_coverage_pct,
        "required_managed_core_coverage_pct": 90.0,
        "managed_core_asset_count": 8,
        "reason": (
            f"Aktuelle vollständige TRS decken {verified_trs_reserves_moz:.1f} Mio. oz bzw. "
            f"{nav_eligible_managed_operating_coverage_pct:.1f} % der {managed_operating_reserves_moz:.1f} Mio. oz "
            f"gemanagten operativen Goldreserven ab; für das Portfolio-NAV-Gate sind mindestens "
            f"{required_managed_operating_coverage_pct:.0f} % erforderlich. Bezogen auf das Gesamtportfolio von "
            f"{total_portfolio_reserves_moz:.1f} Mio. oz sind {total_portfolio_coverage_pct:.1f} % durch aktuelle Phase-1-TRS abgedeckt. "
            f"Noch ohne gleichwertig aktuellen LOM-Datensatz: {missing_names}."
        ),
    }


def build_newmont_portfolio_completeness_gate(
    total_reserves_moz,
    managed_operating_reserves_moz,
    nonmanaged_jv_reserves_moz,
    development_project_reserves_moz,
    technical_lom_phase1,
    quality_aware_coverage=None,
):
    """
    V2.14.2 enterprise-level portfolio completeness gate for Newmont.

    This gate is deliberately separate from the managed-operations 90 % LOM
    coverage gate. A company Fair Value may only be released when every
    material portfolio block is either supported by an explicit valuation path
    or has been explicitly assigned a conservative zero value. No block is
    automatically set to zero.
    """
    total = float(total_reserves_moz or 0.0)
    managed = float(managed_operating_reserves_moz or 0.0)
    jv = float(nonmanaged_jv_reserves_moz or 0.0)
    development = float(development_project_reserves_moz or 0.0)
    phase1 = technical_lom_phase1 if isinstance(technical_lom_phase1, dict) else {}
    quality = quality_aware_coverage if isinstance(quality_aware_coverage, dict) else {}

    if quality.get("available"):
        managed_coverage_pct = float(quality.get("portfolio_aggregation_managed_coverage_pct") or quality.get("nav_quality_released_managed_coverage_pct") or 0.0)
        managed_required_pct = float(quality.get("required_managed_operating_coverage_pct") or 90.0)
        managed_lom_coverage_ok = bool(quality.get("coverage_ok", False))
        managed_coverage_label = "Portfolio-Aggregations-NAV-Abdeckung (asset-spezifische TRS-Raten)"
    else:
        managed_coverage_pct = float(phase1.get("nav_eligible_managed_operating_coverage_pct") or 0.0)
        managed_required_pct = float(phase1.get("required_managed_operating_coverage_pct") or 90.0)
        managed_lom_coverage_ok = bool(phase1.get("coverage_ok", False))
        managed_coverage_label = "NAV-fähige LOM-Abdeckung"

    def share(value):
        return value / total * 100.0 if total > 0 else 0.0

    # V2.14.2 has not yet built normalized block values. These flags are
    # intentionally False. Future NAV/project modules must switch them only
    # after their own hard gates pass.
    managed_value_available = False
    jv_value_available = False
    development_value_available = False

    # Zero values must be an explicit conservative policy choice. V2.14.2 does
    # not silently discard any material block.
    managed_zero_explicit = False
    jv_zero_explicit = False
    development_zero_explicit = False

    blocks = [
        {
            "key": "managed_operations",
            "label": "Managed Operations",
            "reserves_moz": managed,
            "reserve_share_pct": share(managed),
            "material": True,
            "valuation_available": managed_value_available,
            "conservative_zero_explicit": managed_zero_explicit,
            "lom_coverage_ok": managed_lom_coverage_ok,
            "completion_status": (
                "Bewertungsblock noch offen – LOM-Abdeckung unter 90 %"
                if not managed_lom_coverage_ok
                else "LOM-Abdeckung ausreichend – normalisierter Managed-Operations-NAV noch nicht freigegeben"
            ),
            "detail": (
                f"{managed_coverage_label} {managed_coverage_pct:.1f} %; "
                f"erforderlich mindestens {managed_required_pct:.0f} %."
            ),
        },
        {
            "key": "nonmanaged_jvs",
            "label": "Nicht gemanagte JVs",
            "reserves_moz": jv,
            "reserve_share_pct": share(jv),
            "material": True,
            "valuation_available": jv_value_available,
            "conservative_zero_explicit": jv_zero_explicit,
            "lom_coverage_ok": False,
            "completion_status": "Separater JV-NAV/LOM-Bewertungsblock fehlt",
            "detail": "Nevada Gold Mines und Pueblo Viejo dürfen nicht automatisch im Unternehmenswert verschwinden.",
        },
        {
            "key": "development_projects",
            "label": "Entwicklungsprojekte",
            "reserves_moz": development,
            "reserve_share_pct": share(development),
            "material": True,
            "valuation_available": development_value_available,
            "conservative_zero_explicit": development_zero_explicit,
            "lom_coverage_ok": False,
            "completion_status": "Separater Projektwert-/Entwicklungsstatus-Block fehlt",
            "detail": "Norte Abierto, Wafi-Golpu und NuevaUnión benötigen einen eigenen Projektwert- oder expliziten Nullansatz.",
        },
    ]

    for block in blocks:
        block["complete"] = bool(
            block.get("valuation_available") or block.get("conservative_zero_explicit")
        )

    material_blocks = [b for b in blocks if b.get("material")]
    completed_material_blocks = [b for b in material_blocks if b.get("complete")]
    released = len(material_blocks) > 0 and len(completed_material_blocks) == len(material_blocks)
    open_blocks = [b["label"] for b in material_blocks if not b.get("complete")]

    reason = None
    if not released:
        reason = (
            "Portfolio-Completeness-Gate nicht freigegeben: Materielle Unternehmensblöcke sind noch nicht "
            "vollständig bewertet oder ausdrücklich konservativ mit 0 angesetzt. Offen: "
            + ", ".join(open_blocks)
            + ". Ein bestandener 90-%-LOM-Gate der Managed Operations allein darf keinen Newmont-Gesamt-Fair-Value freigeben."
        )

    return {
        "available": True,
        "released": released,
        "status": "Portfolio vollständig behandelt" if released else "Portfolio unvollständig – Gesamt-Fair-Value gesperrt",
        "total_reserves_moz": total,
        "blocks": blocks,
        "material_block_count": len(material_blocks),
        "completed_material_block_count": len(completed_material_blocks),
        "open_material_blocks": open_blocks,
        "automatic_zeroing_allowed": False,
        "explicit_zero_required": True,
        "managed_operations_lom_coverage_pct": managed_coverage_pct,
        "managed_operations_lom_required_pct": managed_required_pct,
        "managed_operations_lom_coverage_ok": managed_lom_coverage_ok,
        "reason": reason,
        "note": (
            "V2.14.2 trennt die Freigabe des Gesamtunternehmens von der LOM-Abdeckung der Managed Operations. "
            "Nicht gemanagte JVs und Entwicklungsprojekte sind eigene materielle Bewertungsblöcke. "
            "Kein Block wird automatisch mit 0 bewertet; ein Nullansatz muss ausdrücklich konservativ gesetzt werden."
        ),
    }



def _discount_cashflow_series_musd(cashflows_musd, discount_rate_pct):
    """Discount end-of-year cash flows; used only for TRS NAV diagnostics."""
    rate = safe_float(discount_rate_pct)
    if rate is None or rate < 0:
        return None
    r = rate / 100.0
    try:
        values = [float(v) for v in cashflows_musd]
    except Exception:
        return None
    return sum(v / ((1.0 + r) ** (idx + 1)) for idx, v in enumerate(values))


def _newmont_phase2_trs_asset_inputs():
    """
    Verified rounded annual TRS tables for Newmont's four 2025 S-K 1300 exhibits.

    Values are intentionally kept in the units used in the reports. Annual FCF
    figures and the published native NPV are shown to one decimal US$bn. V2.16
    carries source-precision metadata for reconstruction diagnostics and explicit
    cash-flow-horizon / closure-tail metadata. Rounded table cells are never
    treated as exact full-horizon cash flows when the source itself ends before
    the reported closure horizon.
    """
    return {
        "Lihir": {
            "reserve_moz": 16.0,
            "effective_date": "31.12.2025",
            "ownership_pct": 100.0,
            "native_discount_rate_pct": 10.0,
            "native_npv_musd": 2000.0,
            "native_fcf_musd": 3100.0,
            "source_annual_fcf_rounding_step_busd": 0.1,
            "source_native_npv_rounding_step_busd": 0.1,
            "operating_end_year": 2043,
            "closure_end_year": 2066,
            "annual_cashflow_end_year": 2043,
            "closure_tail_annualized": False,
            "closure_in_native_economic_model": True,
            "closure_cost_musd": 700.0,
            "closure_tail_note": "Annualisierte FCF-Tabelle endet 2043; Closure-Kosten laufen laut TRS bis 2066. 2025 undiscounted life-of-asset closure cost ca. 0,7 Mrd. USD.",
            "trs_prices": {"gold": 2000.0},
            "tax_rate_pct": 30.0,
            "revenue_levy_pct": {"gold": 2.5},  # 2% royalty + 0.5% production levy
            "years": list(range(2026, 2044)),
            "fcf_busd": [0.1,-0.1,0.1,0.4,0.5,0.6,0.6,0.5,0.4,0.3,0.1,0.0,0.1,0.2,0.0,0.1,0.0,-0.1],
            "recovered": {
                "gold_moz": [0.6,0.7,0.7,0.9,1.0,1.0,1.0,0.9,0.8,0.7,0.6,0.6,0.6,0.6,0.4,0.4,0.4,0.2],
            },
            "source_exhibit": "96.3",
            "source_note": (
                "Lihir TRS: Gold 2.000 USD/oz, NPV10 2,0 Mrd. USD, 100%-Projektbasis; "
                "30% Körperschaftsteuer sowie 2% Mineralroyalty + 0,5% Produktionsabgabe."
            ),
        },
        "Cadia": {
            "reserve_moz": 13.5,
            "effective_date": "31.12.2025",
            "ownership_pct": 100.0,
            "native_discount_rate_pct": 5.0,
            "native_npv_musd": 2600.0,
            "native_fcf_musd": 5300.0,
            "source_annual_fcf_rounding_step_busd": 0.1,
            "source_native_npv_rounding_step_busd": 0.1,
            "operating_end_year": 2056,
            "closure_end_year": 2058,
            "annual_cashflow_end_year": 2058,
            "closure_tail_annualized": True,
            "closure_in_native_economic_model": True,
            "closure_cost_musd": 500.0,
            "closure_tail_note": "Annualisierte FCF-Tabellen reichen bis 2058 und enthalten nach Betriebsende 2056 die Closure-Jahre 2057/2058.",
            "trs_prices": {"gold": 2000.0, "copper": 3.75, "silver": 25.0, "molybdenum": 13.0},
            "tax_rate_pct": 30.0,
            "revenue_levy_pct": {"gold": 4.0, "copper": 4.0, "silver": 4.0, "molybdenum": 4.0},
            "years": list(range(2026, 2059)),
            "fcf_busd": (
                [-0.1,-0.4,-0.3,0.1,0.3,0.4,0.5,0.5]
                + [0.3,0.3,0.3,0.2,0.3,0.4,0.3,0.3,0.3,0.1]
                + [0.1,0.2,0.3,0.3,0.2,0.2,0.2,0.2,0.3,0.2]
                + [0.2,-0.1,-0.2,-0.2,-0.2]
            ),
            "recovered": {
                "gold_moz": (
                    [0.3,0.3,0.3,0.4,0.4,0.4,0.4,0.4]
                    + [0.4,0.4,0.4,0.5,0.5,0.5,0.4,0.4,0.4,0.4]
                    + [0.4,0.4,0.4,0.3,0.3,0.3,0.3,0.3,0.3,0.3]
                    + [0.2,0.1,0.1,0.0,0.0]
                ),
                "copper_kt": (
                    [84,81,84,94,96,99,100,89]
                    + [81,76,67,63,67,81,90,91,83,79]
                    + [84,86,91,86,79,77,73,73,77,74]
                    + [72,47,21,0,0]
                ),
                "silver_moz": (
                    [0.4,0.4,0.4,0.4,0.4,0.4,0.5,0.5]
                    + [0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5]
                    + [0.5,0.5,0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4]
                    + [0.3,0.2,0.1,0.0,0.0]
                ),
                "molybdenum_kt": (
                    [2,2,2,2,2,2,2,2]
                    + [1,1,1,2,2,2,2,2,2,2]
                    + [2,2,2,2,2,2,2,2,1,2]
                    + [2,1,1,0,0]
                ),
            },
            "source_exhibit": "96.2",
            "source_note": (
                "Cadia TRS: Gold 2.000 USD/oz, Kupfer 3,75 USD/lb, Silber 25 USD/oz, "
                "Molybdän 13 USD/lb; NPV5 2,6 Mrd. USD; 30% Bundessteuer und 4% NSW-Royalty."
            ),
        },
        "Boddington": {
            "reserve_moz": 10.2,
            "effective_date": "31.12.2025",
            "ownership_pct": 100.0,
            "native_discount_rate_pct": 5.0,
            "native_npv_musd": 1500.0,
            "native_fcf_musd": 2200.0,
            "source_annual_fcf_rounding_step_busd": 0.1,
            "source_native_npv_rounding_step_busd": 0.1,
            "operating_end_year": 2040,
            "closure_end_year": 2059,
            "annual_cashflow_end_year": 2040,
            "closure_tail_annualized": False,
            "closure_in_native_economic_model": True,
            "closure_cost_musd": 500.0,
            "closure_tail_note": "Annualisierte FCF-Tabelle endet 2040; Closure-Kosten laufen laut TRS bis 2059 und werden mit ca. 0,5 Mrd. USD veranschlagt.",
            "trs_prices": {"gold": 2000.0, "copper": 3.75},
            "tax_rate_pct": 30.0,
            "revenue_levy_pct": {"gold": 2.5, "copper": 5.0},
            "years": list(range(2026, 2041)),
            "fcf_busd": [0.0,0.1,0.1,0.1,0.0,0.1,0.3,0.3,0.0,0.1,0.1,0.1,0.3,0.3,0.2],
            "recovered": {
                "gold_moz": [0.6,0.7,0.7,0.7,0.7,0.7,0.7,0.6,0.5,0.5,0.5,0.5,0.4,0.4,0.3],
                "copper_kt": [20,25,27,27,27,31,33,27,20,25,26,29,29,26,21],
            },
            "source_exhibit": "96.1",
            "source_note": (
                "Boddington TRS: Gold 2.000 USD/oz, Kupfer 3,75 USD/lb, NPV5 1,5 Mrd. USD; "
                "30% Bundessteuer, 2,5% Gold- und 5% Kupferroyalty. Newmont besitzt 100%."
            ),
        },
        "Ahafo Complex": {
            "reserve_moz": 8.8,
            "effective_date": "31.12.2025",
            "ownership_pct": 90.0,
            "native_discount_rate_pct": 8.0,
            "native_npv_musd": 1700.0,
            "native_fcf_musd": 2700.0,
            "source_annual_fcf_rounding_step_busd": 0.1,
            "source_native_npv_rounding_step_busd": 0.1,
            "operating_end_year": 2044,
            "closure_end_year": 2078,
            "annual_cashflow_end_year": 2044,
            "closure_tail_annualized": False,
            "closure_in_native_economic_model": True,
            "closure_cost_musd": None,
            "closure_tail_note": "Annualisierte Betriebs-FCFs enden 2044. Ahafo South weist Reclamation 2035–2061 und Ahafo North 2045–2078 aus; diese Tail-Cashflows sind in den LOM-Totals enthalten, aber nicht jahresweise bis 2078 offengelegt.",
            "trs_prices": {"gold": 2000.0},
            "tax_rate_pct": 35.0,
            # Post-stability-period fiscal burden: 5% royalty + 3% GSL + 0.6% advance dividend.
            # The separate 2% Rank NSR applies only to specific ounces and is not extrapolated to all production.
            "revenue_levy_pct": {"gold": 8.6},
            "years": list(range(2026, 2045)),
            "fcf_busd": [-0.1,0.2,0.2,0.2,0.4,0.5,0.2,0.2,0.0,0.2,0.0,0.1,0.1,0.1,0.1,0.2,0.1,0.2,0.0],
            "recovered": {
                "gold_moz": [0.7,0.8,0.7,0.7,0.8,0.8,0.6,0.5,0.3,0.2,0.2,0.2,0.2,0.2,0.2,0.3,0.2,0.3,0.1],
            },
            "source_exhibit": "96.4",
            "source_note": (
                "Ahafo Complex TRS: Gold 2.000 USD/oz, NPV8 1,7 Mrd. USD auf 100%-Projektbasis; "
                "Newmont wirtschaftlich 90%. Seit 2026: 35% Steuer, 5% Royalty, 3% GSL; "
                "0,6% Advance-Dividend wird konservativ in der Preisbrücke berücksichtigt."
            ),
        },
    }


def _newmont_phase2_price_map(cache_version):
    """Load model-normal commodity prices for the Phase-2 asset bridge."""
    specs = {
        "gold": ("Gold", "GC=F", "USD/oz"),
        "copper": ("Kupfer", "HG=F", "USD/lb"),
        "silver": ("Silber", "SI=F", "USD/oz"),
    }
    out = {}
    for key, (label, symbol, unit) in specs.items():
        cycle = load_mining_commodity_price_cycle(
            symbol, cache_version, normalization_years=5, current_window_days=60
        )
        out[key] = {
            "commodity": label,
            "symbol": symbol,
            "unit": unit,
            "available": bool(cycle.get("available", False)),
            "normalized_price": safe_float(cycle.get("normalized_price")),
            "years_used": cycle.get("years_used") or [],
            "annual_averages": cycle.get("annual_averages") or [],
            "reason": cycle.get("reason"),
        }
    # No reliable Yahoo futures series is used for molybdenum in V2.16.
    out["molybdenum"] = {
        "commodity": "Molybdän",
        "symbol": None,
        "unit": "USD/lb",
        "available": False,
        "normalized_price": None,
        "reason": "Keine verifizierte dynamische Yahoo-Rohstoffserie im Modell; TRS-Basis bleibt unverändert.",
    }
    return out


def _metal_gross_revenue_musd(metal, quantity, price):
    q = safe_float(quantity)
    p = safe_float(price)
    if q is None or p is None:
        return None
    if metal in ("gold", "silver"):
        return q * 1_000_000.0 * p / 1_000_000.0  # Moz * USD/oz -> MUSD
    if metal in ("copper", "molybdenum"):
        return q * 1_000.0 * 2204.62262185 * p / 1_000_000.0  # kt -> lb -> MUSD
    return None


def build_newmont_asset_nav_phase2(cache_version):
    """
    V2.16 asset-level commodity-price normalization + cashflow-horizon / closure-tail + portfolio-aggregation policy.

    The native-rate NAV is anchored to the published official TRS NPV and receives
    only discounted commodity-price deltas from years with verified recovered-metal
    quantities. A common-rate (8%) comparison NAV is released only when the full
    economic cash-flow horizon through closure is annualized, or when the native TRS
    discount rate already equals 8% so no re-discounting of the hidden closure tail is
    required. Reconstruction robustness remains a diagnostic and is a hard gate only
    where the annualized source horizon is complete enough to reproduce the economic
    model. Missing closure-tail cash flows are never estimated.
    """
    trs_assets = _newmont_phase2_trs_asset_inputs()
    prices = _newmont_phase2_price_map(cache_version)
    common_discount_rate_pct = 8.0
    material_unmodeled_revenue_share_limit_pct = 5.0
    max_material_price_gap_pct = 25.0
    calibration_good_limit_pct = 5.0
    sensitivity_nav_move_warning_pct = 20.0
    sensitivity_material_price_gap_ceiling_pct = 15.0
    results = []

    for asset_name, data in trs_assets.items():
        years = list(data.get("years") or [])
        raw_fcf_musd = [float(x) * 1000.0 for x in (data.get("fcf_busd") or [])]
        native_rate = safe_float(data.get("native_discount_rate_pct"))
        native_npv = safe_float(data.get("native_npv_musd"))
        ownership_pct = safe_float(data.get("ownership_pct")) or 100.0
        operating_end_year = int(data.get("operating_end_year")) if data.get("operating_end_year") is not None else None
        closure_end_year = int(data.get("closure_end_year")) if data.get("closure_end_year") is not None else None
        annual_cashflow_end_year = int(data.get("annual_cashflow_end_year")) if data.get("annual_cashflow_end_year") is not None else (max(years) if years else None)
        closure_tail_annualized = bool(data.get("closure_tail_annualized", False))
        closure_in_native_economic_model = bool(data.get("closure_in_native_economic_model", False))
        closure_cost_musd = safe_float(data.get("closure_cost_musd"))
        horizon_complete_through_closure = bool(
            closure_tail_annualized
            and annual_cashflow_end_year is not None
            and closure_end_year is not None
            and annual_cashflow_end_year >= closure_end_year
        )
        common_rate_same_as_native = bool(
            native_rate is not None and abs(native_rate - common_discount_rate_pct) <= 1e-9
        )
        common_rate_horizon_released = bool(horizon_complete_through_closure or common_rate_same_as_native)
        if horizon_complete_through_closure:
            common_rate_horizon_status = "Vollständiger Cashflow-Horizont bis Closure annualisiert"
        elif common_rate_same_as_native:
            common_rate_horizon_status = "Keine Re-Diskontierung nötig – TRS-Rate entspricht 8 %"
        else:
            common_rate_horizon_status = "Closure-Tail nicht annualisiert – 8%-Re-Diskontierung gesperrt"

        raw_base_npv = _discount_cashflow_series_musd(raw_fcf_musd, native_rate)
        calibration_factor = None
        calibrated_fcf_musd = list(raw_fcf_musd)
        if raw_base_npv not in (None, 0) and native_npv is not None:
            calibration_factor = native_npv / raw_base_npv
            calibrated_fcf_musd = [x * calibration_factor for x in raw_fcf_musd]

        calibration_adjustment_pct = None
        raw_vs_official_npv_pct = None
        raw_npv_gap_musd = None
        source_annual_fcf_rounding_step_busd = safe_float(data.get("source_annual_fcf_rounding_step_busd"))
        source_native_npv_rounding_step_busd = safe_float(data.get("source_native_npv_rounding_step_busd"))
        annual_fcf_rounding_half_step_musd = (
            source_annual_fcf_rounding_step_busd * 1000.0 / 2.0
            if source_annual_fcf_rounding_step_busd is not None else None
        )
        native_npv_rounding_half_step_musd = (
            source_native_npv_rounding_step_busd * 1000.0 / 2.0
            if source_native_npv_rounding_step_busd is not None else 0.0
        )
        discounted_annual_rounding_band_musd = None
        source_precision_band_musd = None  # absolute deterministic worst-case band
        source_precision_usage_pct = None
        within_source_precision_band = False
        robustness_band_musd = None
        robustness_usage_pct = None
        within_robustness_band = False
        robustness_confidence_approx_pct = 95.0
        if annual_fcf_rounding_half_step_musd is not None and native_rate is not None:
            # Worst case: every annual table cell is rounded by the full half-step in the same direction.
            discounted_half_steps = [
                annual_fcf_rounding_half_step_musd / ((1.0 + native_rate / 100.0) ** (idx + 1))
                for idx in range(len(raw_fcf_musd))
            ]
            discounted_annual_rounding_band_musd = sum(discounted_half_steps)
            source_precision_band_musd = discounted_annual_rounding_band_musd + (native_npv_rounding_half_step_musd or 0.0)

            # Robustness screen: independent, unbiased rounding errors uniformly distributed within each half-step.
            # This is a model diagnostic, not a source-provided confidence interval. 95% normal approximation.
            uniform_variance_terms = [(x * x) / 3.0 for x in discounted_half_steps]
            if native_npv_rounding_half_step_musd:
                uniform_variance_terms.append((native_npv_rounding_half_step_musd ** 2) / 3.0)
            robustness_sigma_musd = math.sqrt(sum(uniform_variance_terms)) if uniform_variance_terms else None
            if robustness_sigma_musd is not None:
                robustness_band_musd = 1.96 * robustness_sigma_musd

        calibration_quality = "Nicht prüfbar"
        calibration_nav_released = False
        calibration_gate_applicable = horizon_complete_through_closure
        calibration_quality_note = "Kalibrierungsqualität nicht belastbar prüfbar."
        if calibration_factor is not None:
            calibration_adjustment_pct = abs(calibration_factor - 1.0) * 100.0
            if native_npv not in (None, 0) and raw_base_npv is not None:
                raw_vs_official_npv_pct = (raw_base_npv / native_npv - 1.0) * 100.0
                raw_npv_gap_musd = abs(raw_base_npv - native_npv)
            if raw_npv_gap_musd is not None and source_precision_band_musd not in (None, 0):
                source_precision_usage_pct = raw_npv_gap_musd / source_precision_band_musd * 100.0
                within_source_precision_band = raw_npv_gap_musd <= source_precision_band_musd + 1e-9
            if raw_npv_gap_musd is not None and robustness_band_musd not in (None, 0):
                robustness_usage_pct = raw_npv_gap_musd / robustness_band_musd * 100.0
                within_robustness_band = raw_npv_gap_musd <= robustness_band_musd + 1e-9

            if not calibration_gate_applicable:
                calibration_quality = "Diagnose · Closure-Tail nicht annualisiert"
                calibration_nav_released = True
                calibration_quality_note = (
                    "Die annualisierte FCF-Tabelle endet vor dem ausgewiesenen Closure-Horizont. Der NPV-Rekonstruktionsabstand "
                    "wird deshalb nicht als Qualitätsgate verwendet: Der offizielle native TRS-NPV verankert die Basisbewertung, "
                    "während fehlende Closure-Tail-Cashflows nicht in Betriebsjahre hineingeschätzt werden."
                )
            elif calibration_adjustment_pct <= calibration_good_limit_pct:
                calibration_quality = "Gut"
                calibration_nav_released = True
                calibration_quality_note = (
                    f"Kalibrierungsabweichung {calibration_adjustment_pct:.1f}% ≤ {calibration_good_limit_pct:.0f}%: "
                    "annualisiertes TRS-Cashflow-Profil bereits ausreichend nah am offiziellen NPV."
                )
            elif within_robustness_band:
                calibration_quality = "Plausibel · Robustheitsband"
                calibration_nav_released = True
                calibration_quality_note = (
                    f"Kalibrierungsabweichung {calibration_adjustment_pct:.1f}% liegt über {calibration_good_limit_pct:.0f}%, "
                    f"der absolute NPV-Abstand von {raw_npv_gap_musd:.0f} Mio. USD liegt aber innerhalb des engeren "
                    f"Robustheitsbands von ±{robustness_band_musd:.0f} Mio. USD. NAV mit Robustheitswarnung freigegeben."
                )
            elif within_source_precision_band:
                calibration_quality = "Eingeschränkt · nur Worst-Case-Band"
                calibration_nav_released = False
                calibration_quality_note = (
                    f"Kalibrierungsabweichung {calibration_adjustment_pct:.1f}%: Der absolute NPV-Abstand von {raw_npv_gap_musd:.0f} Mio. USD "
                    f"liegt außerhalb des Robustheitsbands von ±{robustness_band_musd:.0f} Mio. USD, aber noch innerhalb des absoluten "
                    f"Worst-Case-Rundungsbands von ±{source_precision_band_musd:.0f} Mio. USD. Die vollständige Cashflow-Historie ist vorhanden, "
                    "aber die Rekonstruktion ist nicht robust genug für die NAV-Freigabe."
                )
            else:
                calibration_quality = "Gesperrt · außerhalb Worst-Case-Band"
                calibration_nav_released = False
                band_text = f"±{source_precision_band_musd:.0f} Mio. USD" if source_precision_band_musd is not None else "nicht belastbar bestimmbar"
                gap_text = f"{raw_npv_gap_musd:.0f} Mio. USD" if raw_npv_gap_musd is not None else "–"
                calibration_quality_note = (
                    f"Kalibrierungsabweichung {calibration_adjustment_pct:.1f}% und absoluter NPV-Abstand {gap_text}; "
                    f"absolutes Worst-Case-Rundungsband {band_text}. Die Rekonstruktion liegt selbst außerhalb der aus der "
                    "Quellenpräzision erklärbaren Spanne; NAV-Freigabe bleibt gesperrt."
                )

        trs_prices = data.get("trs_prices") or {}
        recovered = data.get("recovered") or {}

        # Base gross-metal revenue shares are diagnostics only; net revenue in
        # the TRS also contains realization effects and therefore will not match exactly.
        base_revenue_by_metal = {}
        for metal, base_price in trs_prices.items():
            q_key = {
                "gold": "gold_moz", "silver": "silver_moz",
                "copper": "copper_kt", "molybdenum": "molybdenum_kt",
            }.get(metal)
            if not q_key:
                continue
            q_total = sum(float(x) for x in (recovered.get(q_key) or []))
            rev = _metal_gross_revenue_musd(metal, q_total, base_price)
            if rev is not None:
                base_revenue_by_metal[metal] = rev
        total_base_metal_revenue = sum(base_revenue_by_metal.values())
        revenue_share_pct = {
            metal: (value / total_base_metal_revenue * 100.0 if total_base_metal_revenue > 0 else None)
            for metal, value in base_revenue_by_metal.items()
        }

        commodity_details = []
        commodity_blockers = []
        reconstruction_blockers = []
        if calibration_gate_applicable and not calibration_nav_released:
            reconstruction_blockers.append(calibration_quality_note)
        annual_adjustments_musd = [0.0 for _ in years]
        unmodeled_share_pct = 0.0

        for metal, base_price in trs_prices.items():
            price_info = prices.get(metal) or {}
            share_pct = safe_float(revenue_share_pct.get(metal)) or 0.0
            normalized_price = safe_float(price_info.get("normalized_price"))
            material = share_pct >= material_unmodeled_revenue_share_limit_pct
            normalized = bool(price_info.get("available", False)) and normalized_price is not None
            if not normalized:
                unmodeled_share_pct += share_pct
                if material:
                    commodity_blockers.append(
                        f"{price_info.get('commodity', metal)} ({share_pct:.1f}% Brutto-Metallumsatz) nicht dynamisch normalisiert"
                    )
                commodity_details.append({
                    "metal": metal,
                    "label": price_info.get("commodity", metal),
                    "symbol": price_info.get("symbol"),
                    "unit": price_info.get("unit"),
                    "trs_price": base_price,
                    "normalized_price": None,
                    "price_gap_pct": None,
                    "gross_revenue_share_pct": share_pct,
                    "material": material,
                    "normalized": False,
                    "note": price_info.get("reason") or "Keine dynamische Normalisierung verfügbar.",
                })
                continue

            price_gap_pct = (normalized_price / base_price - 1.0) * 100.0 if base_price else None
            if material and price_gap_pct is not None and abs(price_gap_pct) > max_material_price_gap_pct:
                commodity_blockers.append(
                    f"{price_info.get('commodity', metal)}-Normalpreis weicht {price_gap_pct:+.1f}% von der TRS-Basis ab (>25%); Mine-Plan müsste neu optimiert werden"
                )

            q_key = {
                "gold": "gold_moz", "silver": "silver_moz",
                "copper": "copper_kt", "molybdenum": "molybdenum_kt",
            }.get(metal)
            quantities = list(recovered.get(q_key) or [])
            levy_pct = safe_float((data.get("revenue_levy_pct") or {}).get(metal)) or 0.0
            tax_pct = safe_float(data.get("tax_rate_pct")) or 0.0
            marginal_after_tax_factor = (1.0 - levy_pct / 100.0) * (1.0 - tax_pct / 100.0)

            for idx in range(min(len(years), len(quantities))):
                base_rev = _metal_gross_revenue_musd(metal, quantities[idx], base_price)
                norm_rev = _metal_gross_revenue_musd(metal, quantities[idx], normalized_price)
                if base_rev is None or norm_rev is None:
                    continue
                annual_adjustments_musd[idx] += (norm_rev - base_rev) * marginal_after_tax_factor

            commodity_details.append({
                "metal": metal,
                "label": price_info.get("commodity", metal),
                "symbol": price_info.get("symbol"),
                "unit": price_info.get("unit"),
                "trs_price": base_price,
                "normalized_price": normalized_price,
                "price_gap_pct": price_gap_pct,
                "gross_revenue_share_pct": share_pct,
                "material": material,
                "normalized": True,
                "marginal_after_tax_factor": marginal_after_tax_factor,
                "years_used": price_info.get("years_used") or [],
            })

        # Cadia's un-normalized molybdenum is tolerated only while its base gross
        # metal-revenue share remains below the explicit 5% de-minimis threshold.
        if unmodeled_share_pct > material_unmodeled_revenue_share_limit_pct:
            commodity_blockers.append(
                f"Nicht dynamisch normalisierte Nebenprodukt-Exposures summieren sich auf {unmodeled_share_pct:.1f}% (>5%)."
            )

        # Native-rate bridge: official TRS NPV is the baseline anchor. Only verified commodity-price
        # deltas from operating/recovery years are added at the native TRS discount rate. This avoids
        # forcing hidden closure-tail cash flows into visible operating years.
        commodity_delta_npv_native_100 = _discount_cashflow_series_musd(annual_adjustments_musd, native_rate)
        normalized_npv_native_100 = (
            native_npv + commodity_delta_npv_native_100
            if native_npv is not None and commodity_delta_npv_native_100 is not None else None
        )

        # Common-rate comparison requires correct cash-flow timing through closure. When the source
        # horizon is complete, the calibrated full series can be re-discounted. If the native rate
        # already equals 8%, no re-discounting is needed and the native-rate result is itself the
        # comparable 8% NAV. Otherwise the comparison value is withheld rather than estimated.
        normalized_fcf_musd = [
            calibrated_fcf_musd[i] + annual_adjustments_musd[i]
            for i in range(min(len(calibrated_fcf_musd), len(annual_adjustments_musd)))
        ]
        diagnostic_common_rate_npv_100 = _discount_cashflow_series_musd(normalized_fcf_musd, common_discount_rate_pct)
        if common_rate_same_as_native:
            normalized_npv_common_100 = normalized_npv_native_100
        elif horizon_complete_through_closure and calibration_nav_released:
            normalized_npv_common_100 = diagnostic_common_rate_npv_100
        else:
            normalized_npv_common_100 = None
        ownership_factor = ownership_pct / 100.0
        normalized_npv_native_owned = (
            normalized_npv_native_100 * ownership_factor if normalized_npv_native_100 is not None else None
        )
        normalized_npv_common_owned = (
            normalized_npv_common_100 * ownership_factor if normalized_npv_common_100 is not None else None
        )
        native_owned_npv = native_npv * ownership_factor if native_npv is not None else None
        raw_base_npv_owned = raw_base_npv * ownership_factor if raw_base_npv is not None else None
        raw_npv_gap_musd_owned = raw_npv_gap_musd * ownership_factor if raw_npv_gap_musd is not None else None
        source_precision_band_musd_owned = source_precision_band_musd * ownership_factor if source_precision_band_musd is not None else None
        robustness_band_musd_owned = robustness_band_musd * ownership_factor if robustness_band_musd is not None else None
        delta_vs_native_owned_pct = None
        if native_owned_npv not in (None, 0) and normalized_npv_native_owned is not None:
            delta_vs_native_owned_pct = (normalized_npv_native_owned / native_owned_npv - 1.0) * 100.0

        material_price_gaps = [
            abs(safe_float(x.get("price_gap_pct")) or 0.0)
            for x in commodity_details
            if x.get("material") and x.get("normalized") and safe_float(x.get("price_gap_pct")) is not None
        ]
        max_material_price_gap_observed_pct = max(material_price_gaps) if material_price_gaps else None
        sensitivity_warning = False
        sensitivity_note = None
        if (
            delta_vs_native_owned_pct is not None
            and abs(delta_vs_native_owned_pct) >= sensitivity_nav_move_warning_pct
            and max_material_price_gap_observed_pct is not None
            and max_material_price_gap_observed_pct <= sensitivity_material_price_gap_ceiling_pct
        ):
            sensitivity_warning = True
            sensitivity_note = (
                f"Hohe NAV-Preissensitivität: Asset-NAV reagiert mit {delta_vs_native_owned_pct:+.1f}% auf materielle "
                f"Rohstoffpreisabweichungen von maximal {max_material_price_gap_observed_pct:.1f}%. Das ist eine Sensitivitätswarnung, "
                "kein automatischer Fehler oder Sperrgrund."
            )

        calculated = normalized_npv_native_owned is not None
        native_nav_released = bool(calculated and len(commodity_blockers) == 0 and (calibration_nav_released or not calibration_gate_applicable))
        # V2.16: A heterogeneous-rate SOTP may retain the official asset-specific TRS after-tax rate.
        # The common 8% rate is comparison-only. Portfolio aggregation eligibility therefore follows
        # the native-rate normalized NAV, subject to aligned valuation date/currency checks at portfolio level.
        portfolio_aggregation_nav_released = bool(
            native_nav_released
            and normalized_npv_native_owned is not None
            and native_rate is not None
            and native_rate > 0
        )
        common_nav_released = bool(native_nav_released and common_rate_horizon_released and normalized_npv_common_owned is not None)
        blockers = list(commodity_blockers) + list(reconstruction_blockers)
        if native_nav_released and not common_nav_released:
            blockers.append(
                "8%-Vergleichs-NAV gesperrt: Closure-Tail ist nicht vollständig annualisiert und der native TRS-Diskontsatz weicht von 8% ab. "
                "Fehlende Closure-Cashflows werden nicht zeitlich geschätzt."
            )
        if native_nav_released and common_nav_released and not horizon_complete_through_closure and common_rate_same_as_native:
            common_rate_release_note = "Freigegeben ohne Re-Diskontierung: native TRS-Rate entspricht 8%; Closure-Tail-Timing wird nicht verändert."
        elif common_nav_released:
            common_rate_release_note = "Freigegeben: annualisierte Cashflows decken den wirtschaftlichen Horizont bis Closure ab."
        else:
            common_rate_release_note = "Gesperrt: vollständiger Closure-Tail für eine Re-Diskontierung auf 8% fehlt."

        if native_nav_released and calibration_quality == "Plausibel · Robustheitsband":
            confidence = "Niedrig bis Mittel"
        elif native_nav_released and not horizon_complete_through_closure:
            confidence = "Mittel (native Rate) · Vergleichsrate horizonabhängig"
        elif native_nav_released and unmodeled_share_pct <= 0.5:
            confidence = "Mittel"
        elif native_nav_released:
            confidence = "Niedrig bis Mittel"
        else:
            confidence = "Niedrig"
        results.append({
            "asset": asset_name,
            "reserve_moz": safe_float(data.get("reserve_moz")),
            "calculated": calculated,
            "available": native_nav_released,
            "native_nav_released": native_nav_released,
            "portfolio_aggregation_nav_released": portfolio_aggregation_nav_released,
            "nav_released": portfolio_aggregation_nav_released,
            "common_nav_released": common_nav_released,
            "effective_date": data.get("effective_date") or "31.12.2025",
            "portfolio_aggregation_discount_policy": "Offizieller asset-spezifischer TRS-After-Tax-Diskontsatz",
            "status": (
                "Native-TRS-NAV und 8%-Vergleichs-NAV freigegeben" if common_nav_released
                else "Native-TRS-NAV freigegeben · 8%-Vergleichs-NAV gesperrt" if native_nav_released
                else "Phase-2-Asset-NAV gesperrt"
            ),
            "operating_end_year": operating_end_year,
            "closure_end_year": closure_end_year,
            "annual_cashflow_end_year": annual_cashflow_end_year,
            "closure_tail_annualized": closure_tail_annualized,
            "closure_in_native_economic_model": closure_in_native_economic_model,
            "closure_cost_musd": closure_cost_musd,
            "closure_tail_note": data.get("closure_tail_note"),
            "horizon_complete_through_closure": horizon_complete_through_closure,
            "common_rate_same_as_native": common_rate_same_as_native,
            "common_rate_horizon_released": common_rate_horizon_released,
            "common_rate_horizon_status": common_rate_horizon_status,
            "common_rate_release_note": common_rate_release_note,
            "calibration_gate_applicable": calibration_gate_applicable,
            "ownership_pct": ownership_pct,
            "native_discount_rate_pct": native_rate,
            "common_discount_rate_pct": common_discount_rate_pct,
            "native_trs_npv_musd_100pct": native_npv,
            "native_trs_npv_musd_owned": native_owned_npv,
            "raw_rounded_series_npv_musd": raw_base_npv,
            "raw_rounded_series_npv_musd_100pct": raw_base_npv,
            "raw_rounded_series_npv_musd_owned": raw_base_npv_owned,
            "raw_vs_official_npv_pct": raw_vs_official_npv_pct,
            "reconstruction_basis": "100%-Projektbasis",
            "annual_cashflow_calibration_factor": calibration_factor,
            "calibration_adjustment_pct": calibration_adjustment_pct,
            "calibration_quality": calibration_quality,
            "calibration_quality_note": calibration_quality_note,
            "calibration_nav_released": calibration_nav_released,
            "raw_npv_gap_musd": raw_npv_gap_musd,
            "source_annual_fcf_rounding_step_busd": source_annual_fcf_rounding_step_busd,
            "source_native_npv_rounding_step_busd": source_native_npv_rounding_step_busd,
            "discounted_annual_rounding_band_musd": discounted_annual_rounding_band_musd,
            "native_npv_rounding_half_step_musd": native_npv_rounding_half_step_musd,
            "source_precision_band_musd": source_precision_band_musd,
            "source_precision_band_musd_owned": source_precision_band_musd_owned,
            "source_precision_usage_pct": source_precision_usage_pct,
            "within_source_precision_band": within_source_precision_band,
            "robustness_band_musd": robustness_band_musd,
            "robustness_band_musd_owned": robustness_band_musd_owned,
            "robustness_usage_pct": robustness_usage_pct,
            "within_robustness_band": within_robustness_band,
            "robustness_confidence_approx_pct": robustness_confidence_approx_pct,
            "raw_npv_gap_musd_owned": raw_npv_gap_musd_owned,
            "normalized_nav_native_rate_musd_100pct": normalized_npv_native_100,
            "normalized_nav_native_rate_musd_owned": normalized_npv_native_owned,
            "normalized_nav_common_rate_musd_100pct": normalized_npv_common_100,
            "normalized_nav_common_rate_musd_owned": normalized_npv_common_owned,
            "diagnostic_common_rate_npv_musd_100pct": diagnostic_common_rate_npv_100,
            "diagnostic_common_rate_npv_musd_owned": (diagnostic_common_rate_npv_100 * ownership_factor if diagnostic_common_rate_npv_100 is not None else None),
            "delta_vs_native_owned_pct": delta_vs_native_owned_pct,
            "max_material_price_gap_observed_pct": max_material_price_gap_observed_pct,
            "sensitivity_warning": sensitivity_warning,
            "sensitivity_note": sensitivity_note,
            "unmodeled_gross_revenue_share_pct": unmodeled_share_pct,
            "commodity_details": commodity_details,
            "blockers": blockers,
            "confidence": confidence,
            "source_exhibit": data.get("source_exhibit"),
            "source_note": data.get("source_note"),
            "method_note": (
                "V2.16 behält für die Portfolio-Aggregationsschicht den offiziellen asset-spezifischen TRS-After-Tax-Diskontsatz bei. "
                "Der native-rate Preisbridge-NAV wird direkt auf den offiziellen TRS-NPV verankert und nur um diskontierte Rohstoffpreis-Deltas "
                "der verifizierten Produktionsjahre ergänzt. Die 8-%-Re-Diskontierung bleibt eine separate Vergleichsschicht und wird nur "
                "freigegeben, wenn der annualisierte Cashflow-Horizont bis zum Closure-Ende reicht; Ausnahme: native TRS-Rate = 8 %. "
                "Fehlende Closure-Jahre werden weder geschätzt noch aus Closure-Gesamtkosten synthetisch verteilt."
            ),
        })

    phase2_calculated_assets = [x for x in results if x.get("calculated")]
    native_ready_assets = [x for x in results if x.get("native_nav_released")]
    aggregation_candidates = [x for x in results if x.get("portfolio_aggregation_nav_released")]
    common_ready_assets = [x for x in results if x.get("common_nav_released")]
    effective_dates = sorted({str(x.get("effective_date")) for x in aggregation_candidates if x.get("effective_date")})
    valuation_date_aligned = len(effective_dates) == 1 and len(aggregation_candidates) > 0
    aggregation_ready_assets = aggregation_candidates if valuation_date_aligned else []
    native_released_reserves_moz = sum(safe_float(x.get("reserve_moz")) or 0.0 for x in native_ready_assets)
    portfolio_aggregation_reserves_moz = sum(safe_float(x.get("reserve_moz")) or 0.0 for x in aggregation_ready_assets)
    portfolio_comparable_reserves_moz = sum(safe_float(x.get("reserve_moz")) or 0.0 for x in common_ready_assets)
    partial_portfolio_sotp_nav_musd = sum(safe_float(x.get("normalized_nav_native_rate_musd_owned")) or 0.0 for x in aggregation_ready_assets)
    aggregation_blocked_assets = [
        {
            "asset": x.get("asset"),
            "reserve_moz": safe_float(x.get("reserve_moz")),
            "reason": "Native-rate Asset-NAV oder konsistenter Bewertungsstichtag für die Portfolio-Aggregation nicht freigegeben.",
        }
        for x in results if x.get("calculated") and x not in aggregation_ready_assets
    ]
    comparison_blocked_assets = [
        {
            "asset": x.get("asset"),
            "reserve_moz": safe_float(x.get("reserve_moz")),
            "calibration_quality": x.get("calibration_quality"),
            "reason": (x.get("common_rate_release_note") or " · ".join(str(v) for v in x.get("blockers", []))),
        }
        for x in results if x.get("calculated") and not x.get("common_nav_released")
    ]
    return {
        "available": True,
        "status": (
            f"Phase 2: {len(phase2_calculated_assets)}/{len(results)} berechnet · "
            f"{len(native_ready_assets)}/{len(results)} Native-TRS-NAV · "
            f"{len(aggregation_ready_assets)}/{len(results)} Portfolio-Aggregations-NAV · "
            f"{len(common_ready_assets)}/{len(results)} 8%-Vergleichs-NAV"
        ),
        "common_discount_rate_pct": common_discount_rate_pct,
        "asset_count": len(results),
        "calculated_asset_count": len(phase2_calculated_assets),
        "normalized_asset_count": len(phase2_calculated_assets),
        "native_nav_released_asset_count": len(native_ready_assets),
        "nav_released_asset_count": len(aggregation_ready_assets),
        "common_nav_released_asset_count": len(common_ready_assets),
        "native_nav_released_reserves_moz": native_released_reserves_moz,
        "portfolio_aggregation_asset_count": len(aggregation_ready_assets),
        "portfolio_aggregation_reserves_moz": portfolio_aggregation_reserves_moz,
        "partial_portfolio_sotp_nav_musd": partial_portfolio_sotp_nav_musd,
        "portfolio_aggregation_policy_released": valuation_date_aligned,
        "portfolio_aggregation_policy_status": (
            "Asset-spezifische TRS-After-Tax-Diskontsätze für SOTP zugelassen – 8 % bleibt Vergleichsschicht"
            if valuation_date_aligned else
            "Portfolio-Aggregation gesperrt – Bewertungsstichtage nicht konsistent"
        ),
        "portfolio_aggregation_effective_date": (effective_dates[0] if valuation_date_aligned else None),
        "portfolio_aggregation_blocked_assets": aggregation_blocked_assets,
        "portfolio_comparable_reserves_moz": portfolio_comparable_reserves_moz,
        "comparison_blocked_assets": comparison_blocked_assets,
        # Backward compatibility: quality-released now follows the binding V2.16 aggregation policy, not the 8% comparison layer.
        "quality_released_reserves_moz": portfolio_aggregation_reserves_moz,
        "quality_blocked_assets": aggregation_blocked_assets,
        "calibration_good_limit_pct": calibration_good_limit_pct,
        "assets": results,
        "price_map": prices,
        "aggregation_released": False,
        "reason": (
            "V2.16 trennt drei Ebenen: native Asset-NAVs, eine heterogene Portfolio-Aggregationsschicht mit den offiziellen asset-spezifischen "
            "TRS-After-Tax-Diskontsätzen und eine separate 8-%-Vergleichsschicht. Die 8-%-Vergleichsfähigkeit ist kein bindendes 90-%-Gate mehr. "
            "Für die Portfolio-Aggregationsschicht zählen nur native-rate normalisierte Asset-NAVs mit konsistentem Bewertungsstichtag, Währung, "
            "Eigentumsanteil und Rohstoffpreis-Basis. Das Managed-Operations-90-%-Gate sowie JV- und Entwicklungsprojekt-Blöcke bleiben bindend."
        ),
        "note": (
            "Der native-rate NAV wird auf den offiziellen TRS-NPV verankert. V2.16 erlaubt einen heterogenen SOTP mit den offiziellen asset-spezifischen "
            "TRS-After-Tax-Diskontsätzen; unterschiedliche Diskontsätze werden nicht künstlich auf 8 % gezwungen. Der 8-%-Vergleichs-NAV bleibt eine "
            "separate Vergleichsschicht und benötigt für echte Re-Diskontierungen den vollständigen annualisierten Cashflow-Horizont bis Closure. "
            "Closure-Tail-Cashflows werden niemals aus Gesamtkosten geschätzt. Ein Teil-SOTP der Phase-2-Assets ist nur Diagnose und kein Newmont-Gesamt-NAV."
        ),
    }

def get_verified_newmont_core_asset_lom_structure():
    """Verified Newmont V2.14.2 portfolio LOM evidence map with completeness gate; not a synthetic NAV."""
    total_reserves = 118.2
    long_life_reserves = 85.7
    managed_operating_reserves = 71.5
    nonmanaged_jv_reserves = 25.6
    development_project_reserves = 21.0
    phase1 = get_verified_newmont_technical_lom_phase1()
    try:
        phase2 = build_newmont_asset_nav_phase2(CACHE_VERSION)
    except Exception as exc:
        phase2 = {
            "available": False,
            "status": "Phase 2 – Daten/Preisnormalisierung nicht verfügbar",
            "assets": [],
            "aggregation_released": False,
            "reason": f"Phase-2-Normalisierung konnte nicht belastbar berechnet werden: {exc}",
        }
    phase1_trs_eligible_reserves = safe_float(phase1.get("verified_trs_reserves_moz")) or 0.0
    native_nav_released_reserves = safe_float(phase2.get("native_nav_released_reserves_moz")) or 0.0
    portfolio_aggregation_reserves = safe_float(phase2.get("portfolio_aggregation_reserves_moz")) or 0.0
    phase2_comparison_reserves = safe_float(phase2.get("portfolio_comparable_reserves_moz")) or 0.0
    native_nav_released_managed_coverage_pct = (native_nav_released_reserves / managed_operating_reserves * 100.0 if managed_operating_reserves > 0 else 0.0)
    native_nav_released_total_coverage_pct = (native_nav_released_reserves / total_reserves * 100.0 if total_reserves > 0 else 0.0)
    portfolio_aggregation_managed_coverage_pct = (
        portfolio_aggregation_reserves / managed_operating_reserves * 100.0
        if managed_operating_reserves > 0 else 0.0
    )
    portfolio_aggregation_total_coverage_pct = (
        portfolio_aggregation_reserves / total_reserves * 100.0
        if total_reserves > 0 else 0.0
    )
    portfolio_comparable_managed_coverage_pct = (
        phase2_comparison_reserves / managed_operating_reserves * 100.0
        if managed_operating_reserves > 0 else 0.0
    )
    portfolio_comparable_total_coverage_pct = (
        phase2_comparison_reserves / total_reserves * 100.0
        if total_reserves > 0 else 0.0
    )
    required_managed_operating_coverage_pct = safe_float(phase1.get("required_managed_operating_coverage_pct")) or 90.0
    quality_aware_coverage = {
        "available": bool(phase2.get("available")),
        "phase1_trs_eligible_reserves_moz": phase1_trs_eligible_reserves,
        "phase1_trs_managed_coverage_pct": (phase1_trs_eligible_reserves / managed_operating_reserves * 100.0 if managed_operating_reserves > 0 else 0.0),
        "phase1_trs_total_coverage_pct": (phase1_trs_eligible_reserves / total_reserves * 100.0 if total_reserves > 0 else 0.0),
        "native_nav_released_reserves_moz": native_nav_released_reserves,
        "native_nav_released_managed_coverage_pct": native_nav_released_managed_coverage_pct,
        "native_nav_released_total_coverage_pct": native_nav_released_total_coverage_pct,
        "portfolio_aggregation_reserves_moz": portfolio_aggregation_reserves,
        "portfolio_aggregation_managed_coverage_pct": portfolio_aggregation_managed_coverage_pct,
        "portfolio_aggregation_total_coverage_pct": portfolio_aggregation_total_coverage_pct,
        "partial_portfolio_sotp_nav_musd": safe_float(phase2.get("partial_portfolio_sotp_nav_musd")),
        "portfolio_comparable_reserves_moz": phase2_comparison_reserves,
        "portfolio_comparable_managed_coverage_pct": portfolio_comparable_managed_coverage_pct,
        "portfolio_comparable_total_coverage_pct": portfolio_comparable_total_coverage_pct,
        # Backward-compatible binding names now follow the V2.16 portfolio-aggregation policy.
        "nav_quality_released_reserves_moz": portfolio_aggregation_reserves,
        "nav_quality_released_managed_coverage_pct": portfolio_aggregation_managed_coverage_pct,
        "nav_quality_released_total_coverage_pct": portfolio_aggregation_total_coverage_pct,
        "required_managed_operating_coverage_pct": required_managed_operating_coverage_pct,
        "coverage_ok": portfolio_aggregation_managed_coverage_pct >= required_managed_operating_coverage_pct,
        "released_asset_count": int(phase2.get("portfolio_aggregation_asset_count") or 0),
        "comparison_released_asset_count": int(phase2.get("common_nav_released_asset_count") or 0),
        "calculated_asset_count": int(phase2.get("calculated_asset_count") or 0),
        "quality_blocked_assets": phase2.get("portfolio_aggregation_blocked_assets") or [],
        "comparison_blocked_assets": phase2.get("comparison_blocked_assets") or [],
    }
    portfolio_completeness_gate = build_newmont_portfolio_completeness_gate(
        total_reserves,
        managed_operating_reserves,
        nonmanaged_jv_reserves,
        development_project_reserves,
        phase1,
        quality_aware_coverage,
    )

    managed_operating_assets = [
        {"asset":"Lihir","reserve_moz":16.0,"production_2026_koz":560,"aisc_2026_usd_oz":1765,
         "reserve_life_evidence":"≥10 Jahre; Nearshore Barrier verlängert Minenleben über 2040",
         "lom_profile_status":"Aktuelles S-K 1300 TRS – Phase-1-TRS-Kandidat; noch kein aggregierter NAV"},
        {"asset":"Cadia","reserve_moz":13.5,"production_2026_koz":270,"aisc_2026_usd_oz":1575,
         "reserve_life_evidence":"≥10 Jahre; aktuelles TRS modelliert Betrieb bis 2056",
         "lom_profile_status":"Aktuelles S-K 1300 TRS – Phase-1-TRS-Kandidat; noch kein aggregierter NAV"},
        {"asset":"Tanami","reserve_moz":5.3,"production_2026_koz":365,"aisc_2026_usd_oz":2145,
         "reserve_life_evidence":"≥10 Jahre; Expansion 2 verlängert Minenleben über 2040",
         "lom_profile_status":"Kein gleichwertig verifiziertes aktuelles TRS im 2025-Exhibit-Set – nicht NAV-fähig"},
        {"asset":"Boddington","reserve_moz":10.2,"production_2026_koz":580,"aisc_2026_usd_oz":1630,
         "reserve_life_evidence":"≥10 Jahre; aktuelles TRS modelliert Betrieb bis 2040",
         "lom_profile_status":"Aktuelles S-K 1300 TRS – Phase-1-TRS-Kandidat; noch kein aggregierter NAV"},
        {"asset":"Ahafo Complex","reserve_moz":8.8,"production_2026_koz":755,"aisc_2026_usd_oz":None,
         "reserve_life_evidence":"Ahafo North ≥10 Jahre; aktuelles Complex-TRS modelliert Betrieb bis 2044",
         "lom_profile_status":"Aktuelles S-K 1300 TRS – Phase-1-TRS-Kandidat; North/South im Report getrennt",
         "note":"2026 Guidance: Ahafo South 440 koz / 2.160 USD AISC; Ahafo North 315 koz / 1.285 USD AISC."},
        {"asset":"Merian","reserve_moz":4.5,"production_2026_koz":225,"aisc_2026_usd_oz":1800,
         "reserve_life_evidence":"≥10 Jahre Reserveleben",
         "lom_profile_status":"Kein gleichwertig verifiziertes aktuelles TRS im 2025-Exhibit-Set – nicht NAV-fähig"},
        {"asset":"Cerro Negro","reserve_moz":3.0,"production_2026_koz":220,"aisc_2026_usd_oz":1960,
         "reserve_life_evidence":"≥10 Jahre; 2026 Investitionen für Minenlebensverlängerung",
         "lom_profile_status":"Kein gleichwertig verifiziertes aktuelles TRS im 2025-Exhibit-Set – nicht NAV-fähig"},
        {"asset":"Yanacocha","reserve_moz":0.5,"production_2026_koz":460,"aisc_2026_usd_oz":1170,
         "reserve_life_evidence":"Gemanagte Leach-Operation; 2026/2027-Verlängerungsplan, aber keine 10+-Jahre-Reserve-Langlebigkeit im aktuellen Highlight",
         "lom_profile_status":"2026 Site-Guidance vorhanden; kein gleichwertig aktuelles vollständiges LOM-TRS – nicht NAV-fähig"},
        {"asset":"Peñasquito","reserve_moz":3.2,"production_2026_koz":185,"aisc_2026_usd_oz":-2395,
         "reserve_life_evidence":"Gemanagte polymetallische Operation; nicht Teil der offiziellen 10+-Jahre-Goldreserve-Langlebigkeitsliste",
         "lom_profile_status":"2026 Site-Guidance vorhanden; kein gleichwertig aktuelles vollständiges LOM-TRS – nicht NAV-fähig",
         "note":"Gold-AISC ist wegen Silber-/Blei-/Zink-By-Product-Credits negativ; kein eigenständiger Gold-LOM-NAV wird daraus abgeleitet."},
        {"asset":"Red Chris","reserve_moz":3.6,"production_2026_koz":35,"aisc_2026_usd_oz":3625,
         "reserve_life_evidence":"Gemanagte Operation; Block-Cave-Projekt separat in Entwicklung/Prüfung",
         "lom_profile_status":"2026 Run-rate vorhanden; Projektentwicklung ersetzt kein aktuelles vollständiges LOM-TRS – nicht NAV-fähig"},
        {"asset":"Brucejack","reserve_moz":2.9,"production_2026_koz":260,"aisc_2026_usd_oz":2085,
         "reserve_life_evidence":"≥10 Jahre Reserveleben",
         "lom_profile_status":"Kein gleichwertig verifiziertes aktuelles TRS im 2025-Exhibit-Set – nicht NAV-fähig"},
    ]

    return {
        "available": True,
        "as_of_date": "23.07.2026",
        "reserve_as_of_date": "31.12.2025",
        "source_name": "Newmont 2025 Reserves + 2026 Managed Portfolio Guidance + 2025 S-K 1300 TRS",
        "source_note": (
            "V2.14.2 trennt die NAV-Abdeckung nach festen Portfolio-Schichten und ergänzt ein separates Gesamtunternehmens-Completeness-Gate. Die gemanagte operative Reservebasis "
            "umfasst alle 2026 als Managed Portfolio geführten Gold-Operations mit zurechenbaren Reserven, nicht nur "
            "eine ausgewählte Kernasset-Liste. Das 90-%-Gate wird ausschließlich gegen diese 71,5 Mio. oz gemessen. "
            "Nicht gemanagte JVs und Entwicklungsprojekte bleiben separate Bewertungsblöcke."
        ),
        "total_reserves_moz": total_reserves,
        "long_life_reserves_moz": long_life_reserves,
        "long_life_reserve_coverage_pct": long_life_reserves / total_reserves * 100.0,
        "managed_operating_reserves_moz": managed_operating_reserves,
        "managed_operating_portfolio_coverage_pct": managed_operating_reserves / total_reserves * 100.0,
        # Backward-compatible aliases for previous display code.
        "managed_run_rate_reserves_moz": managed_operating_reserves,
        "managed_run_rate_coverage_pct": managed_operating_reserves / total_reserves * 100.0,
        "phase1_trs_eligible_reserves_moz": phase1_trs_eligible_reserves,
        "phase1_trs_managed_operating_coverage_pct": phase1_trs_eligible_reserves / managed_operating_reserves * 100.0,
        "phase1_trs_total_portfolio_coverage_pct": phase1_trs_eligible_reserves / total_reserves * 100.0,
        "native_nav_released_reserves_moz": native_nav_released_reserves,
        "native_nav_released_managed_operating_coverage_pct": native_nav_released_managed_coverage_pct,
        "native_nav_released_total_portfolio_coverage_pct": native_nav_released_total_coverage_pct,
        "portfolio_aggregation_reserves_moz": portfolio_aggregation_reserves,
        "portfolio_aggregation_managed_operating_coverage_pct": portfolio_aggregation_managed_coverage_pct,
        "portfolio_aggregation_total_portfolio_coverage_pct": portfolio_aggregation_total_coverage_pct,
        "partial_portfolio_sotp_nav_musd": safe_float(phase2.get("partial_portfolio_sotp_nav_musd")),
        "portfolio_comparable_reserves_moz": phase2_comparison_reserves,
        "portfolio_comparable_managed_operating_coverage_pct": portfolio_comparable_managed_coverage_pct,
        "portfolio_comparable_total_portfolio_coverage_pct": portfolio_comparable_total_coverage_pct,
        # Legacy NAV-eligible aliases now mean binding V2.16 portfolio-aggregation eligibility.
        "nav_eligible_reserves_moz": portfolio_aggregation_reserves,
        "nav_eligible_managed_operating_coverage_pct": portfolio_aggregation_managed_coverage_pct,
        "nav_eligible_total_portfolio_coverage_pct": portfolio_aggregation_total_coverage_pct,
        "full_lom_profile_coverage_pct": portfolio_aggregation_total_coverage_pct,
        "quality_aware_coverage": quality_aware_coverage,
        "technical_lom_phase1": phase1,
        "asset_nav_phase2": phase2,
        "nonmanaged_jv_reserves_moz": nonmanaged_jv_reserves,
        "nonmanaged_jv_coverage_pct": nonmanaged_jv_reserves / total_reserves * 100.0,
        "development_project_reserves_moz": development_project_reserves,
        "development_project_coverage_pct": development_project_reserves / total_reserves * 100.0,
        "portfolio_completeness_gate": portfolio_completeness_gate,
        "managed_operating_assets": managed_operating_assets,
        # Legacy key now points to the full managed operating reserve universe so
        # no downstream display can silently omit Peñasquito, Red Chris or Yanacocha.
        "managed_core_assets": managed_operating_assets,
        "nonmanaged_long_life_assets": [
            {"asset":"Nevada Gold Mines (38,5 %)","reserve_moz":17.4,"reserve_life_evidence":"≥10 Jahre"},
            {"asset":"Pueblo Viejo (40 %)","reserve_moz":8.2,"reserve_life_evidence":"≥10 Jahre"},
        ],
        "development_projects": [
            {"asset":"Norte Abierto","reserve_moz":10.8},
            {"asset":"Wafi-Golpu","reserve_moz":5.1},
            {"asset":"NuevaUnión","reserve_moz":5.1},
        ],
        "full_lom_release_ready": bool(
            quality_aware_coverage.get("coverage_ok", False) and portfolio_completeness_gate.get("released", False)
        ),
        "reason": portfolio_completeness_gate.get("reason") or phase1.get("reason"),
    }

def build_mining_asset_nav_control(
    symbol,
    commodity_cycle,
    earnings_translation,
    balance_score,
    fundamental_multiple,
    operating_snapshot,
):
    """
    Mining V2.7 reserve / mine-life / technical-NAV + LOM release control.

    Important: technical-report NPVs are not presented as current company NAV.
    They are independent asset anchors only. V2.7 also builds an independent
    normalized run-rate mine NAV and blocks final Fair Value when
    the technical mine plans are too old or when earnings value and the asset
    anchor diverge materially.
    """
    result = {
        "available": False,
        "status": "Daten unzureichend",
        "required": True,
        "reference_only": True,
        "reserve_snapshot_fresh": False,
        "reserve_price_alignment_pct": None,
        "reserve_price_alignment_status": "Daten unzureichend",
        "total_core_primary_reserves_moz": None,
        "total_core_silver_reserves_moz": None,
        "production_guidance_mid_moz": None,
        "reserve_coverage_years": None,
        "portfolio_reserve_coverage_status": "Daten unzureichend",
        "company_average_reserve_mine_life_years": None,
        "mine_life_status": "Daten unzureichend",
        "core_asset_lom_structure": {},
        "technical_lom_phase1": {},
        "asset_nav_phase2": {},
        "portfolio_completeness_gate": {},
        "technical_nav_available": False,
        "technical_nav_reference_fresh": False,
        "technical_nav_sum_musd": None,
        "equity_nav_anchor_musd": None,
        "nav_anchor_per_share": None,
        "earnings_value_per_share": None,
        "earnings_nav_gap_pct": None,
        "earnings_nav_convergence_status": "Daten unzureichend",
        "nav_details": [],
        "normalized_mine_nav": {},
        "lom_release_gate": {},
        "snapshot": None,
        "reason": None,
    }

    snapshot = get_verified_mining_asset_snapshot(symbol)
    if snapshot is None:
        result["reason"] = (
            "Für diese Bergbau-Aktie ist noch kein verifizierter Reserve-/NAV-"
            "Snapshot hinterlegt."
        )
        return result
    result["snapshot"] = snapshot

    try:
        reserve_valid_until = datetime.strptime(
            snapshot["reserve_valid_until"], "%d.%m.%Y"
        ).date()
        reserve_fresh = datetime.now().date() <= reserve_valid_until
    except Exception:
        reserve_fresh = False
    result["reserve_snapshot_fresh"] = reserve_fresh

    normalized_price = safe_float((commodity_cycle or {}).get("normalized_price"))
    reserve_price = safe_float(
        snapshot.get("reserve_price_basis_primary")
        if snapshot.get("reserve_price_basis_primary") is not None
        else snapshot.get("reserve_price_basis_silver")
    )
    if normalized_price is not None and reserve_price is not None and reserve_price > 0:
        price_gap_pct = abs(normalized_price / reserve_price - 1.0) * 100.0
        result["reserve_price_alignment_pct"] = price_gap_pct
        if price_gap_pct <= 5.0:
            price_alignment_status = "Sehr stark"
        elif price_gap_pct <= 10.0:
            price_alignment_status = "Stark"
        elif price_gap_pct <= 20.0:
            price_alignment_status = "Ausreichend"
        else:
            price_alignment_status = "Schwach"
    else:
        price_alignment_status = "Daten unzureichend"
    result["reserve_price_alignment_status"] = price_alignment_status

    reserves_moz = safe_float(
        snapshot.get("total_core_primary_reserves_moz")
        if snapshot.get("total_core_primary_reserves_moz") is not None
        else snapshot.get("total_core_silver_reserves_moz")
    )
    result["total_core_primary_reserves_moz"] = reserves_moz
    # Legacy output alias retained for older Hecla display/tests.
    result["total_core_silver_reserves_moz"] = (
        reserves_moz if str(snapshot.get("primary_commodity") or "").lower() == "silver" else None
    )

    current_low = safe_float(
        (operating_snapshot or {}).get("production_guidance_current_low_moz")
        if (operating_snapshot or {}).get("production_guidance_current_low_moz") is not None
        else (operating_snapshot or {}).get("production_guidance_current_low")
    )
    current_high = safe_float(
        (operating_snapshot or {}).get("production_guidance_current_high_moz")
        if (operating_snapshot or {}).get("production_guidance_current_high_moz") is not None
        else (operating_snapshot or {}).get("production_guidance_current_high")
    )
    production_mid = None
    reserve_coverage = None
    if current_low is not None and current_high is not None and current_low > 0 and current_high > 0:
        production_mid = (current_low + current_high) / 2.0
        if reserves_moz is not None and reserves_moz > 0:
            reserve_coverage = reserves_moz / production_mid
    result["production_guidance_mid_moz"] = production_mid
    result["reserve_coverage_years"] = reserve_coverage
    if reserve_coverage is None:
        portfolio_reserve_coverage_status = "Daten unzureichend"
    elif reserve_coverage >= 15.0:
        portfolio_reserve_coverage_status = "Sehr stark"
    elif reserve_coverage >= 10.0:
        portfolio_reserve_coverage_status = "Stark"
    elif reserve_coverage >= 7.0:
        portfolio_reserve_coverage_status = "Ausreichend"
    else:
        portfolio_reserve_coverage_status = "Kurz"
    result["portfolio_reserve_coverage_status"] = portfolio_reserve_coverage_status

    core_asset_lom_structure = snapshot.get("core_asset_lom_structure") or {}
    result["core_asset_lom_structure"] = core_asset_lom_structure
    technical_lom_phase1 = core_asset_lom_structure.get("technical_lom_phase1") or {}
    result["technical_lom_phase1"] = technical_lom_phase1
    asset_nav_phase2 = core_asset_lom_structure.get("asset_nav_phase2") or {}
    result["asset_nav_phase2"] = asset_nav_phase2
    portfolio_completeness_gate = core_asset_lom_structure.get("portfolio_completeness_gate") or {}
    result["portfolio_completeness_gate"] = portfolio_completeness_gate
    quality_aware_coverage = core_asset_lom_structure.get("quality_aware_coverage") or {}
    result["quality_aware_coverage"] = quality_aware_coverage

    company_mine_life = safe_float(snapshot.get("company_average_reserve_mine_life_years"))
    result["company_average_reserve_mine_life_years"] = company_mine_life

    symbol_text = str(symbol or "").upper()
    if symbol_text == "NEM" and core_asset_lom_structure:
        quality_managed_pct = safe_float(quality_aware_coverage.get("portfolio_aggregation_managed_coverage_pct"))
        long_life_pct = safe_float(core_asset_lom_structure.get("long_life_reserve_coverage_pct"))
        if quality_managed_pct is not None and quality_managed_pct >= 90.0:
            mine_life_status = "Portfolio-Aggregations-NAV-Profile decken ≥90 % der gemanagten operativen Reserven ab"
        elif quality_managed_pct is not None:
            mine_life_status = f"Portfolio-Aggregations-NAV-Profile decken {quality_managed_pct:.1f} % der gemanagten operativen Reserven ab – unter 90 %"
        elif long_life_pct is not None and long_life_pct >= 70.0:
            mine_life_status = "Reserve-Langlebigkeit stark – technische LOM-Abdeckung noch unvollständig"
        else:
            mine_life_status = "Mine-spezifische LOM-Abdeckung noch nicht ausreichend verifiziert"
    else:
        life_values = [value for value in [reserve_coverage, company_mine_life] if value is not None]
        if not life_values:
            mine_life_status = "Daten unzureichend"
        elif min(life_values) >= 10.0:
            mine_life_status = "Sehr stark"
        elif min(life_values) >= 7.0:
            mine_life_status = "Stark"
        elif min(life_values) >= 5.0:
            mine_life_status = "Ausreichend"
        else:
            mine_life_status = "Kurz"
    result["mine_life_status"] = mine_life_status

    nav_details = []
    technical_nav_sum = 0.0
    technical_nav_ok = True
    nav_reference_fresh = True
    today = datetime.now().date()

    for ref in snapshot.get("technical_nav_references", []):
        interpolated = _linear_interpolate_no_extrapolation(
            normalized_price,
            ref.get("sensitivity_points"),
        )
        try:
            effective_date = datetime.strptime(ref["effective_date"], "%d.%m.%Y").date()
            age_years = (today - effective_date).days / 365.25
        except Exception:
            age_years = None

        # A current independent NAV anchor should generally use a technical mine
        # plan no older than three years. Older reports stay visible as references
        # but cannot release Fair Value.
        reference_fresh = age_years is not None and age_years <= 3.0
        if not reference_fresh:
            nav_reference_fresh = False
        if interpolated is None:
            technical_nav_ok = False
        else:
            technical_nav_sum += interpolated

        nav_details.append({
            "asset": ref.get("asset"),
            "effective_date": ref.get("effective_date"),
            "age_years": age_years,
            "discount_rate_pct": ref.get("discount_rate_pct"),
            "base_after_tax_npv_musd": ref.get("base_after_tax_npv_musd"),
            "normalized_sensitivity_npv_musd": interpolated,
            "reference_fresh": reference_fresh,
            "note": ref.get("note"),
        })

    result["nav_details"] = nav_details
    result["technical_nav_available"] = technical_nav_ok and len(nav_details) >= 3
    result["technical_nav_reference_fresh"] = nav_reference_fresh
    if result["technical_nav_available"]:
        result["technical_nav_sum_musd"] = technical_nav_sum

    normalized_mine_nav = build_mining_normalized_mine_nav_v26(
        symbol,
        commodity_cycle,
        operating_snapshot,
        snapshot,
        nav_details,
    )
    result["normalized_mine_nav"] = normalized_mine_nav

    # Only run the formal LOM gate once a mine-level run-rate NAV dataset exists.
    # A current portfolio reserve statement by itself must not be converted into
    # synthetic mine schedules.
    if (normalized_mine_nav or {}).get("partial_available", False):
        lom_release_gate = build_mining_lom_release_gate_v27(
            snapshot,
            normalized_mine_nav,
            nav_details,
        )
    else:
        lom_release_gate = {}
    result["lom_release_gate"] = lom_release_gate

    net_debt = safe_float((balance_score or {}).get("net_debt"))
    equity_nav_anchor_musd = None
    if result["technical_nav_available"] and net_debt is not None:
        # net_debt < 0 means net cash and therefore increases equity NAV.
        equity_nav_anchor_musd = technical_nav_sum - (net_debt / 1_000_000.0)
        result["equity_nav_anchor_musd"] = equity_nav_anchor_musd

    shares = safe_float((earnings_translation or {}).get("shares_outstanding_used"))
    if equity_nav_anchor_musd is not None and shares is not None and shares > 0:
        result["nav_anchor_per_share"] = equity_nav_anchor_musd * 1_000_000.0 / shares

    sustainable_eps = safe_float((earnings_translation or {}).get("sustainable_eps"))
    used_multiple = safe_float((fundamental_multiple or {}).get("multiple"))
    if sustainable_eps is not None and sustainable_eps > 0 and used_multiple is not None and used_multiple > 0:
        result["earnings_value_per_share"] = sustainable_eps * used_multiple

    nav_ps = safe_float(result.get("nav_anchor_per_share"))
    earnings_ps = safe_float(result.get("earnings_value_per_share"))
    if nav_ps is not None and nav_ps > 0 and earnings_ps is not None and earnings_ps > 0:
        midpoint = (nav_ps + earnings_ps) / 2.0
        gap_pct = abs(nav_ps - earnings_ps) / midpoint * 100.0 if midpoint > 0 else None
        result["earnings_nav_gap_pct"] = gap_pct
        if gap_pct is None:
            convergence = "Daten unzureichend"
        elif gap_pct <= 25.0:
            convergence = "Stark konvergent"
        elif gap_pct <= 50.0:
            convergence = "Ausreichend konvergent"
        else:
            convergence = "Nicht konvergent"
    else:
        convergence = "Daten unzureichend"
    result["earnings_nav_convergence_status"] = convergence

    reserve_ok = reserve_fresh and price_alignment_status in ["Sehr stark", "Stark", "Ausreichend"]
    if str(symbol or "").upper() == "NEM" and core_asset_lom_structure:
        quality_managed_pct = safe_float((quality_aware_coverage or {}).get("portfolio_aggregation_managed_coverage_pct"))
        quality_threshold = safe_float((quality_aware_coverage or {}).get("required_managed_operating_coverage_pct")) or 90.0
        life_ok = quality_managed_pct is not None and quality_managed_pct >= quality_threshold
    else:
        life_ok = mine_life_status in ["Sehr stark", "Stark", "Ausreichend"]
    nav_current_ok = result["technical_nav_available"] and nav_reference_fresh
    convergence_ok = convergence in ["Stark konvergent", "Ausreichend konvergent"]
    portfolio_completeness_ok = (
        portfolio_completeness_gate.get("released", False)
        if str(symbol or "").upper() == "NEM"
        else True
    )

    normalized_nav_partial_ok = (result.get("normalized_mine_nav") or {}).get(
        "partial_available", False
    )
    lom_gate_ok = (result.get("lom_release_gate") or {}).get("released", False)

    if not reserve_ok:
        status = "Reservebasis nicht belastbar freigegeben"
        reason = (
            "Reserve-Daten sind veraltet oder die verwendete Reserve-Preisannahme "
            "liegt zu weit vom normalisierten Rohstoffpreis entfernt."
        )
    elif not life_ok:
        if str(symbol or "").upper() == "NEM" and core_asset_lom_structure:
            quality_pct = safe_float((quality_aware_coverage or {}).get("portfolio_aggregation_managed_coverage_pct"))
            threshold = safe_float((quality_aware_coverage or {}).get("required_managed_operating_coverage_pct")) or 90.0
            managed_reserves = safe_float((technical_lom_phase1 or {}).get("managed_operating_reserves_moz"))
            phase1_trs_reserves = safe_float((quality_aware_coverage or {}).get("phase1_trs_eligible_reserves_moz"))
            nav_released_reserves = safe_float((quality_aware_coverage or {}).get("portfolio_aggregation_reserves_moz"))
            total_pct = safe_float((quality_aware_coverage or {}).get("portfolio_aggregation_total_coverage_pct"))
            phase2_ready = int((asset_nav_phase2 or {}).get("portfolio_aggregation_asset_count") or 0)
            phase2_native_ready = int((asset_nav_phase2 or {}).get("native_nav_released_asset_count") or 0)
            phase2_calculated = int((asset_nav_phase2 or {}).get("calculated_asset_count") or 0)
            phase2_total = int((asset_nav_phase2 or {}).get("asset_count") or 0)
            status = (
                f"LOM/NAV Phase 2 – {phase2_calculated}/{phase2_total} berechnet · {phase2_native_ready}/{phase2_total} Native-TRS-NAV · {phase2_ready}/{phase2_total} Portfolio-Aggregations-NAV; Managed-Abdeckung unter Freigabegrenze"
                if phase2_total > 0 else
                "LOM/NAV Phase 1 – Portfolio-Aggregations-NAV-Abdeckung gemanagter operativer Reserven unter Freigabegrenze"
            )
            if quality_pct is not None:
                missing_names = [
                    str(x.get("asset")) for x in (technical_lom_phase1 or {}).get("missing_current_trs_assets", []) if x.get("asset")
                ]
                quality_blocked = [
                    str(x.get("asset")) for x in (quality_aware_coverage or {}).get("quality_blocked_assets", []) if x.get("asset")
                ]
                all_open = missing_names + [x for x in quality_blocked if x not in missing_names]
                reason = (
                    f"Phase 1 besitzt aktuelle TRS für {(phase1_trs_reserves or 0.0):.1f} Mio. oz. Nach der V2.16 Discount-Rate-&-Portfolio-Aggregation-Policy sind "
                    f"{nav_released_reserves:.1f} Mio. oz bzw. {quality_pct:.1f} % der {managed_reserves:.1f} Mio. oz "
                    f"gemanagten operativen Goldreserven auf einer asset-spezifischen TRS-SOTP-Basis aggregationsfähig. Das Gate verlangt mindestens {threshold:.0f} %. "
                    + (f"Bezogen auf das Gesamtportfolio sind {total_pct:.1f} % aggregationsfähig. " if total_pct is not None else "")
                    + (f"Noch nicht aggregationsfähig: {', '.join(all_open)}." if all_open else "")
                )
            else:
                reason = (technical_lom_phase1 or {}).get("reason") or (
                    "Aktuelle qualitätsbereinigte LOM/NAV-Abdeckung der gemanagten operativen Reservebasis ist noch nicht ausreichend verifiziert."
                )
        else:
            status = "Minenlebensdauer zu kurz oder unklar"
            reason = "Die Reserve-Lebensdauer reicht nicht für eine robuste Asset-Bewertung."
    elif not portfolio_completeness_ok:
        status = "Portfolio-Completeness-Gate nicht freigegeben"
        reason = portfolio_completeness_gate.get("reason") or (
            "Mindestens ein materieller Newmont-Portfolio-Block ist noch weder belastbar bewertet noch ausdrücklich konservativ mit 0 angesetzt."
        )
    elif not normalized_nav_partial_ok:
        if str(symbol or "").upper() == "NEM":
            status = "Reservebasis stark – aktueller Mine-NAV/LOM noch offen"
            reason = (
                "Die 2025er Goldreservebasis und ihre Preisannahmen sind verifiziert, "
                "aber es fehlt noch ein aktueller mine-spezifischer Newmont-NAV mit "
                "Life-of-Mine-Produktion, Kosten, Sustaining CapEx und Steuern. Die "
                "Portfolioreserven werden deshalb nicht aus einem einzelnen Guidance-"
                "Jahr in einen synthetischen NAV umgerechnet."
            )
        else:
            status = (result.get("normalized_mine_nav") or {}).get(
                "status", "Normalisierter Mine-NAV nicht ausreichend berechenbar"
            )
            reason = (result.get("normalized_mine_nav") or {}).get("reason") or (
                "Zu wenige Kernminen besitzen eine belastbare Run-rate-NAV-Kontrolle."
            )
    elif not lom_gate_ok:
        status = (result.get("lom_release_gate") or {}).get(
            "status", "LOM-Gate nicht freigegeben"
        )
        reason = (result.get("lom_release_gate") or {}).get("reason") or (
            "Die Life-of-Mine-Abdeckung reicht noch nicht für eine Fair-Value-Freigabe."
        )
    elif not result["technical_nav_available"]:
        status = "Technischer NAV-Anker nicht vollständig verfügbar"
        reason = (
            "Es fehlen mindestens drei belastbare technische Mine-NPV-Referenzen "
            "innerhalb ihrer veröffentlichten Sensitivitätsbereiche."
        )
    elif not nav_reference_fresh:
        status = "Reserven/Lebensdauer stark – technischer NAV-Anker veraltet"
        reason = (
            "Die Reservebasis und Minenlebensdauer sind belastbar, aber die "
            "eingebundenen technischen Mine-NPVs beruhen teilweise auf 2021er "
            "Minenplänen. Sie bleiben ein unabhängiger Referenzanker und dürfen "
            "keinen finalen 2026-Fair-Value freigeben."
        )
    elif not convergence_ok:
        status = "NAV und Ertragswert nicht ausreichend konvergent"
        reason = (
            "Der unabhängige Asset-NAV-Anker und der nachhaltige Ertragswert "
            "liegen zu weit auseinander. Der Fair Value bleibt gesperrt."
        )
    else:
        status = "Reserve/NAV-Kontrolle freigegeben"
        reason = None

    available = (
        reserve_ok
        and life_ok
        and portfolio_completeness_ok
        and normalized_nav_partial_ok
        and lom_gate_ok
        and nav_current_ok
        and convergence_ok
    )
    result.update({
        "available": available,
        "reference_only": not available,
        "status": status,
        "reason": reason,
    })
    return result


def build_mining_special_control(
    base_control,
    company_type,
    symbol,
    eps_normalization,
    trailing_eps,
    forward_eps,
    historical,
    fcf_score,
    balance_score,
    profit_margin,
    roe,
    free_cashflow=None,
    net_income=None,
    shares_outstanding=None,
    fundamental_multiple=None,
    industry=None,
):
    """
    Conservative Mining V2.11.

    Financial-cycle checks are calculated from already-loaded company data.
    Production guidance and AISC/unit-cost data are used only when a dated,
    verified operating snapshot exists. Peak-cycle risk does not change the
    100-point Multiple Score; it caps valuation confidence instead.
    """

    control = dict(base_control or {})
    control.setdefault("router_status", control.get("status"))
    control.setdefault("router_note", control.get("note"))

    if control.get("control_key") != "mining_cycle_quality":
        return control

    eps_history = _extract_numeric_history((historical or {}).get("eps", []))
    fcf_history = _extract_numeric_history((historical or {}).get("fcf", []))

    cycle_basis = safe_float((eps_normalization or {}).get("cycle_basis"))
    normalized_eps = safe_float((eps_normalization or {}).get("normalized_eps"))
    structural_break_info = (eps_normalization or {}).get("structural_break") or {}
    structural_break_blocked = bool(
        (eps_normalization or {}).get("normalization_blocked_by_structural_break")
    )
    ttm_eps = safe_float(trailing_eps)
    fwd_eps = safe_float(forward_eps)

    ttm_to_cycle = None
    if cycle_basis is not None and cycle_basis > 0 and ttm_eps is not None:
        ttm_to_cycle = ttm_eps / cycle_basis

    if structural_break_blocked:
        eps_status = "Structural-Break – Zyklus-EPS gesperrt"
    elif len(eps_history) < 3 or cycle_basis is None or cycle_basis <= 0:
        eps_status = "Daten unzureichend"
    elif ttm_to_cycle is None:
        eps_status = "Zyklus-Basis vorhanden"
    elif ttm_to_cycle <= 1.5:
        eps_status = "Unauffällig"
    elif ttm_to_cycle <= 3.0:
        eps_status = "Erhöht"
    else:
        eps_status = "Peak-Risiko"

    # V2.13.1: FCF history follows the same comparability boundary as EPS.
    # Pre-break / transition-year cash flows remain visible as history, but do
    # not support a "strong" stability label for the post-M&A company.
    fcf_history_rows = _extract_dated_numeric_history((historical or {}).get("fcf", []))
    positive_fcf_years_all = sum(1 for value in fcf_history if value > 0)
    negative_fcf_years_all = sum(1 for value in fcf_history if value < 0)

    post_break_fcf_rows = list(fcf_history_rows)
    excluded_fcf_rows = []
    fcf_structural_break_active = bool(structural_break_info.get("active", False))
    if fcf_structural_break_active:
        first_full_year = int(structural_break_info.get("first_full_comparable_year") or 0)
        post_break_fcf_rows = [row for row in fcf_history_rows if row["year"] >= first_full_year]
        excluded_fcf_rows = [row for row in fcf_history_rows if row["year"] < first_full_year]

    post_break_fcf_values = [row["value"] for row in post_break_fcf_rows]
    positive_fcf_years = sum(1 for value in post_break_fcf_values if value > 0)
    negative_fcf_years = sum(1 for value in post_break_fcf_values if value < 0)
    post_break_fcf_years = sorted({row["year"] for row in post_break_fcf_rows}, reverse=True)
    excluded_fcf_years = sorted({row["year"] for row in excluded_fcf_rows}, reverse=True)
    minimum_post_break_years = int(
        structural_break_info.get("minimum_full_post_break_years") or 3
    ) if fcf_structural_break_active else 3

    if fcf_structural_break_active and len(post_break_fcf_values) < minimum_post_break_years:
        if (
            len(post_break_fcf_values) >= 2
            and positive_fcf_years == len(post_break_fcf_values)
            and negative_fcf_years == 0
        ):
            fcf_status = "Post-Break positiv – Historie zu kurz"
        elif positive_fcf_years >= 1 and negative_fcf_years >= 1:
            fcf_status = "Post-Break gemischt – Historie zu kurz"
        elif negative_fcf_years > 0:
            fcf_status = "Post-Break schwach – Historie zu kurz"
        else:
            fcf_status = "Post-Break-Daten unzureichend"
    elif len(post_break_fcf_values) < 3:
        fcf_status = "Daten unzureichend"
    elif negative_fcf_years == 0 and positive_fcf_years >= 3:
        fcf_status = "Stark"
    elif positive_fcf_years >= 2 and negative_fcf_years <= 1:
        fcf_status = "Ausreichend"
    elif positive_fcf_years >= 1 and negative_fcf_years >= 1:
        fcf_status = "Zyklisch"
    else:
        fcf_status = "Schwach"

    if fcf_structural_break_active:
        fcf_history_supports_fallback = (
            len(post_break_fcf_values) >= 2
            and positive_fcf_years == len(post_break_fcf_values)
            and negative_fcf_years == 0
        )
    else:
        fcf_history_supports_fallback = fcf_status in ["Stark", "Ausreichend"]

    balance_status_raw = (balance_score or {}).get("status")
    net_debt_to_fcf = safe_float((balance_score or {}).get("net_debt_to_fcf"))
    net_debt = safe_float((balance_score or {}).get("net_debt"))

    if balance_status_raw == "net_cash" or (net_debt is not None and net_debt <= 0):
        balance_status = "Sehr stark"
    elif net_debt_to_fcf is None:
        balance_status = "Daten unzureichend"
    elif net_debt_to_fcf < 1.5:
        balance_status = "Stark"
    elif net_debt_to_fcf < 3.0:
        balance_status = "Ausreichend"
    else:
        balance_status = "Schwach"

    margin = safe_float(profit_margin)
    roe_value = safe_float(roe)
    if margin is None or roe_value is None:
        profitability_status = "Daten unzureichend"
    elif margin < 0 or roe_value < 0:
        profitability_status = "Schwach"
    elif margin >= 0.15 and roe_value >= 0.15:
        profitability_status = "Stark"
    else:
        profitability_status = "Ausreichend"

    snapshot = get_verified_mining_snapshot(symbol)
    snapshot_fresh = False
    production_status = "Daten fehlen"
    production_change_pct = None
    aisc_status = "Daten fehlen"
    aisc_improvement_pct = None
    actual_aisc_status = "Daten fehlen"
    operating_status = "Daten fehlen"

    if snapshot is not None:
        try:
            valid_until = datetime.strptime(
                snapshot["valid_until"], "%d.%m.%Y"
            ).date()
            snapshot_fresh = datetime.now().date() <= valid_until
        except Exception:
            snapshot_fresh = False

        production_status, production_change_pct = _mining_production_guidance_status(snapshot)
        aisc_status, aisc_improvement_pct = _mining_aisc_guidance_status(snapshot)
        actual_aisc_status = _mining_actual_aisc_status(snapshot)

        if not snapshot_fresh:
            operating_status = "Daten veraltet"
        elif "Daten unzureichend" in [production_status, aisc_status, actual_aisc_status]:
            operating_status = "Daten unzureichend"
        elif "Schwach" in [production_status, aisc_status, actual_aisc_status]:
            operating_status = "Schwach"
        elif aisc_status == "Stark verbessert" and production_status in ["Stark", "Positiv", "Stabil"]:
            operating_status = "Stark"
        else:
            operating_status = "Ausreichend"

    financial_checks_usable = (
        not structural_break_blocked
        and eps_status != "Daten unzureichend"
        and fcf_status != "Daten unzureichend"
        and balance_status != "Daten unzureichend"
    )

    peak_risk = eps_status == "Peak-Risiko"
    weak_financial_check = (
        fcf_status == "Schwach"
        or balance_status == "Schwach"
        or profitability_status == "Schwach"
    )

    operating_data_available = (
        snapshot is not None
        and snapshot_fresh
        and operating_status not in ["Daten fehlen", "Daten unzureichend", "Daten veraltet"]
    )

    # Mining V2.11 price-cycle normalization. Price history is loaded dynamically
    # from either an explicitly verified company route or an exact, unambiguous
    # industry route. The normalized commodity margin is a control input, not a
    # direct one-for-one price-to-EPS conversion factor.
    commodity_price_cycle = build_mining_commodity_cycle(
        symbol,
        snapshot,
        CACHE_VERSION,
        industry=industry,
    )
    commodity_price_cycle_available = commodity_price_cycle.get("available", False)
    commodity_price_cycle_status = commodity_price_cycle.get(
        "status", "Daten unzureichend"
    )

    # Mining V2.7: independent earnings-power bridge. The bridge can become
    # available only when cycle-normalized EPS and commodity-margin-adjusted TTM
    # EPS converge and normalized FCF/share provides a positive cash cross-check.
    earnings_translation = build_mining_earnings_translation(
        commodity_price_cycle,
        eps_normalization,
        trailing_eps,
        free_cashflow,
        net_income,
        shares_outstanding,
    )
    earnings_translation_available = earnings_translation.get("available", False)
    earnings_translation_status = earnings_translation.get("status", "Daten unzureichend")

    # Mining V2.13.1: when a verified structural break blocks the regular cycle-EPS
    # history, a separate low-confidence fallback may down-normalize current EPS
    # using the verified commodity margin while FCF remains a cash-conversion control. It never relaxes the 3-year rule.
    structural_break_fallback = build_mining_structural_break_fallback(
        commodity_price_cycle,
        eps_normalization,
        trailing_eps,
        free_cashflow,
        net_income,
        shares_outstanding,
        snapshot,
        operating_status,
        production_status,
        aisc_status,
        actual_aisc_status,
        fcf_status,
        balance_status,
        fcf_history_supports_fallback=fcf_history_supports_fallback,
        fcf_post_break_years_count=len(post_break_fcf_values),
        fcf_post_break_positive_years=positive_fcf_years,
        fcf_post_break_negative_years=negative_fcf_years,
    )
    structural_break_fallback_available = structural_break_fallback.get("available", False)

    # V2.13.1 deliberately does not convert the fallback into a KGV valuation basis.
    # It is an earnings plausibility bridge only. A later mine-NAV/LOM valuation
    # must remain independent and may use the fallback only as a cross-check.

    # Mining V2.7: reserve / mine-life / normalized run-rate NAV / technical anchor.
    # Current reserve data may be fresh while the incorporated S-K 1300 mine
    # plans are older. In that case V2.7 shows the technical NAV as a reference
    # but deliberately does not release a final Fair Value.
    asset_nav_control = build_mining_asset_nav_control(
        symbol,
        commodity_price_cycle,
        earnings_translation,
        balance_score,
        fundamental_multiple,
        snapshot,
    )
    asset_nav_available = asset_nav_control.get("available", False)

    if structural_break_blocked and not structural_break_fallback_available:
        released = False
        overall_status = "Structural-Break-Kontrolle – Fallback-Ertragsbasis nicht freigegeben"
        confidence_cap = "Niedrig"
    elif structural_break_blocked and structural_break_fallback_available:
        # The normal cycle-EPS path remains blocked. V2.13.1 may plausibilize a
        # separate low-confidence earnings fallback, but it does not turn that
        # bridge into a KGV/Fair-Value release. LOM/NAV remains a separate path.
        released = False
        if weak_financial_check:
            overall_status = "Structural-Break-Fallback plausibilisiert – finanzielle Warnung"
        elif not asset_nav_available:
            overall_status = asset_nav_control.get(
                "status", "Structural-Break-Fallback plausibilisiert – LOM/NAV noch offen"
            )
        else:
            overall_status = "Structural-Break-Fallback plausibilisiert – Bewertungsweg noch nicht freigegeben"
        confidence_cap = "Niedrig"
    elif not financial_checks_usable:
        released = False
        overall_status = "Finanzzyklus-Daten unzureichend"
        confidence_cap = "Niedrig"
    elif weak_financial_check:
        released = False
        overall_status = "Finanzielle Warnung"
        confidence_cap = "Niedrig"
    elif not operating_data_available:
        released = False
        overall_status = "Operative Minendaten fehlen oder sind veraltet"
        confidence_cap = "Niedrig"
    elif operating_status == "Schwach":
        released = False
        overall_status = "Operative Warnung"
        confidence_cap = "Niedrig"
    elif not commodity_price_cycle_available:
        released = False
        overall_status = "Rohstoffpreis-Zyklus nicht belastbar verfügbar"
        confidence_cap = "Niedrig"
    elif not earnings_translation_available:
        released = False
        overall_status = "Ertragskraft-Überleitung nicht belastbar freigegeben"
        confidence_cap = "Niedrig"
    elif not asset_nav_available:
        released = False
        overall_status = asset_nav_control.get(
            "status", "Reserve-/NAV-Kontrolle nicht freigegeben"
        )
        confidence_cap = "Niedrig"
    elif peak_risk:
        released = True
        overall_status = "Freigegeben mit Peak-Cycle-Warnung"
        confidence_cap = "Niedrig"
    else:
        released = True
        overall_status = "Ausreichend"
        confidence_cap = "Mittel"

    control.update({
        "implemented": True,
        "released": released,
        "confidence_cap": confidence_cap,
        "step3b_status": (
            "Schritt 3B vollständig – Fair Value mit Zykluswarnung freigegeben"
            if released and peak_risk
            else "Schritt 3B vollständig – Fair Value freigegeben"
            if released
            else "Schritt 3B nicht freigegeben"
        ),
        "overall_status": overall_status,
        "snapshot_fresh": snapshot_fresh,
        "snapshot": snapshot,
        "checks": {
            "cycle_eps": {
                "history_count": len(eps_history),
                "cycle_basis": cycle_basis,
                "normalized_eps": normalized_eps,
                "ttm_eps": ttm_eps,
                "forward_eps": fwd_eps,
                "ttm_to_cycle_ratio": ttm_to_cycle,
                "status": eps_status,
                "structural_break": structural_break_info,
                "structural_break_blocked": structural_break_blocked,
                "comparable_full_years": (eps_normalization or {}).get("comparable_full_years", []),
                "excluded_history_years": (eps_normalization or {}).get("excluded_history_years", []),
                "comparable_full_years_count": (eps_normalization or {}).get("comparable_full_years_count", 0),
                "minimum_full_post_break_years": (eps_normalization or {}).get("minimum_full_post_break_years"),
                "diagnostic_post_break_cycle_basis": (eps_normalization or {}).get("diagnostic_post_break_cycle_basis"),
            },
            "fcf_stability": {
                "history_count": len(fcf_history),
                "all_history_positive_years": positive_fcf_years_all,
                "all_history_negative_years": negative_fcf_years_all,
                "positive_years": positive_fcf_years,
                "negative_years": negative_fcf_years,
                "structural_break_active": fcf_structural_break_active,
                "comparable_post_break_years": post_break_fcf_years,
                "excluded_history_years": excluded_fcf_years,
                "post_break_history_count": len(post_break_fcf_values),
                "minimum_post_break_years": minimum_post_break_years,
                "supports_structural_break_fallback": fcf_history_supports_fallback,
                "score_status": (fcf_score or {}).get("status"),
                "status": fcf_status,
            },
            "balance_buffer": {
                "net_debt": net_debt,
                "net_debt_to_fcf": net_debt_to_fcf,
                "status": balance_status,
            },
            "profitability": {
                "margin": margin,
                "roe": roe_value,
                "status": profitability_status,
            },
            "operating_mine_data": {
                "available": operating_data_available,
                "status": operating_status,
                "production_status": production_status,
                "production_change_pct": production_change_pct,
                "aisc_status": aisc_status,
                "aisc_improvement_pct": aisc_improvement_pct,
                "actual_aisc_status": actual_aisc_status,
            },
            "commodity_price_cycle": commodity_price_cycle,
            "commodity_earnings_translation": earnings_translation,
            "structural_break_fallback": structural_break_fallback,
            "mining_asset_nav_control": asset_nav_control,
        },
        "note": (
            "Die Bergbau-Spezialkontrolle V2.17.1 ergänzt die Managed-Operations Source Coverage Map und trennt weiterhin Discount-Rate-&-Portfolio-Aggregation-Policy, Quality-aware Coverage Propagation, Asset-NAV-Normalisierung Phase 2 inklusive Cashflow-Horizon-&-Closure-Tail-Gate, Portfolio-Completeness-Gate, Portfolio-Abdeckungslogik, technische LOM/NAV-Phase 1, Structural-Break-Kontrolle, Structural-Break-Fallback, Reserve-/NAV-Snapshot, Primärrohstoff-Routing, Finanzzyklus, operative "
            "Minenvisibilität, Rohstoffpreis-Normalisierung, nachhaltige "
            "Ertragskraft, Reserve-/Asset-Kontrolle, Run-rate-Mine-NAV und das "
            "formale Life-of-Mine-Freigabe-Gate. Ein Guidance-Jahr ersetzt kein "
            "LOM-Kostenprofil; unvollständige oder veraltete Minenpläne sperren "
            "den Fair Value. Der 100-Punkte-Multiple-Score bleibt unverändert."
        ),
    })

    return control


# =========================================================
# Modul 6 – Bewertungssicherheit & Bewertungszonen
# =========================================================

def _confidence_rank_value(level):
    mapping = {
        "Niedrig": 1,
        "Niedrig bis Mittel": 2,
        "Mittel": 2,
        "Mittel bis Hoch": 3,
        "Hoch": 3,
    }
    return mapping.get(str(level or "").strip())


def calculate_valuation_confidence(
    company_type,
    eps_normalization,
    peer_check,
    special_control,
    fair_value,
):
    result = {
        "available": False,
        "level": None,
        "components": {},
        "limiting_factor": None,
        "note": None,
    }

    if not isinstance(fair_value, dict) or not fair_value.get("available"):
        result["note"] = "Ohne berechenbaren Fair Value keine Bewertungssicherheit."
        return result

    components = {}

    company_cap_raw = (company_type or {}).get("confidence_cap")
    company_rank = _confidence_rank_value(company_cap_raw)
    if company_rank is not None:
        components["Unternehmenstyp / Methode"] = (company_rank, company_cap_raw)

    eps_level = (eps_normalization or {}).get("confidence")
    eps_rank = _confidence_rank_value(eps_level)
    if eps_rank is not None:
        components["EPS-Normalisierung"] = (eps_rank, eps_level)

    if isinstance(peer_check, dict) and peer_check.get("method_supported"):
        usable_peers = int(peer_check.get("usable_count") or 0)
        peer_level = "Hoch" if peer_check.get("applied") and usable_peers >= 3 else "Mittel"
        components["Peer-Check"] = (_confidence_rank_value(peer_level), peer_level)

    if isinstance(special_control, dict) and special_control.get("required"):
        special_level = special_control.get("confidence_cap") or "Niedrig"
        special_rank = _confidence_rank_value(special_level)
        if special_rank is not None:
            components["Spezialkontrolle"] = (special_rank, special_level)

    if not components:
        result["note"] = "Keine belastbaren Sicherheitskomponenten verfügbar."
        return result

    min_rank = min(value[0] for value in components.values())
    final_level = {1: "Niedrig", 2: "Mittel", 3: "Hoch"}[min_rank]
    limiting = [
        name for name, value in components.items()
        if value[0] == min_rank
    ]

    result.update({
        "available": True,
        "level": final_level,
        "components": {
            name: display for name, (_, display) in components.items()
        },
        "limiting_factor": ", ".join(limiting),
        "note": (
            "Die endgültige Bewertungssicherheit entspricht der schwächsten "
            "relevanten Sicherheitsstufe. Eine spätere Kontrolle kann eine "
            "frühere Unsicherheit nicht hochstufen."
        ),
    })
    return result


def get_zone_thresholds(confidence):
    if confidence == "Hoch":
        return {"fair_band": 0.075, "strong_threshold": 0.15}
    if confidence == "Mittel":
        return {"fair_band": 0.10, "strong_threshold": 0.20}
    if confidence == "Niedrig":
        return {"fair_band": 0.15, "strong_threshold": 0.25}
    return None


def calculate_valuation_zone(current_price, fair_value, valuation_confidence):
    result = {
        "available": False,
        "zone": None,
        "price_vs_fair_value_pct": None,
        "fair_lower": None,
        "fair_upper": None,
        "strong_undervaluation_limit": None,
        "strong_overvaluation_limit": None,
        "note": None,
    }

    price = safe_float(current_price)
    fair = safe_float((fair_value or {}).get("fair_value_quote"))
    confidence = (valuation_confidence or {}).get("level")
    thresholds = get_zone_thresholds(confidence)

    if price is None or fair is None or price <= 0 or fair <= 0 or thresholds is None:
        result["note"] = "Bewertungszone derzeit nicht belastbar berechenbar."
        return result

    fair_band = thresholds["fair_band"]
    strong = thresholds["strong_threshold"]
    distance_pct = (price / fair - 1.0) * 100.0

    strong_low = fair * (1.0 - strong)
    fair_low = fair * (1.0 - fair_band)
    fair_high = fair * (1.0 + fair_band)
    strong_high = fair * (1.0 + strong)

    if price <= strong_low:
        zone = "Stark unterbewertet"
    elif price < fair_low:
        zone = "Unterbewertet"
    elif price <= fair_high:
        zone = "Fair bewertet"
    elif price < strong_high:
        zone = "Überbewertet"
    else:
        zone = "Stark überbewertet"

    result.update({
        "available": True,
        "zone": zone,
        "price_vs_fair_value_pct": distance_pct,
        "fair_lower": fair_low,
        "fair_upper": fair_high,
        "strong_undervaluation_limit": strong_low,
        "strong_overvaluation_limit": strong_high,
        "note": (
            "Die Zonenbreite hängt von der Bewertungssicherheit ab. "
            "Die Bewertungszone ist noch kein Handlungssignal."
        ),
    })
    return result


# =========================================================
# Modul 7 – Signal-Engine V1
# =========================================================

def get_fundamental_strength(multiple_score):
    score = safe_float(multiple_score)
    if score is None:
        return "Nicht bestimmbar"
    if score >= 70.0:
        return "Stark"
    if score >= 50.0:
        return "Ausreichend"
    return "Schwach"


def generate_new_buy_signal(valuation_zone, valuation_confidence, multiple_score):
    zone = (valuation_zone or {}).get("zone")
    confidence = (valuation_confidence or {}).get("level")
    fundamental = get_fundamental_strength(multiple_score)

    result = {
        "available": False,
        "signal": None,
        "fundamental_strength": fundamental,
        "reason": None,
    }

    if not zone or not confidence:
        result["reason"] = "Ohne belastbare Bewertungszone kein Neukauf-Signal."
        return result

    result["available"] = True

    if confidence == "Niedrig":
        if zone in ["Stark unterbewertet", "Unterbewertet"]:
            result.update({
                "signal": "Beobachten",
                "reason": "Bewertung günstig, Bewertungssicherheit aber niedrig.",
            })
        else:
            result.update({
                "signal": "Kein Kauf",
                "reason": "Bewertungssicherheit für einen Neukauf zu niedrig.",
            })
        return result

    if zone == "Stark unterbewertet":
        if fundamental == "Stark":
            result.update({"signal": "Starker Kauf", "reason": "Deutliche Unterbewertung bei starker fundamentaler Basis."})
        elif fundamental == "Ausreichend":
            result.update({"signal": "Kauf", "reason": "Deutliche Unterbewertung bei ausreichender fundamentaler Basis."})
        else:
            result.update({"signal": "Beobachten", "reason": "Bewertung attraktiv, fundamentale Basis jedoch schwach."})
    elif zone == "Unterbewertet":
        if fundamental in ["Stark", "Ausreichend"]:
            result.update({"signal": "Kauf", "reason": "Ausreichender Abschlag zum Fair Value."})
        else:
            result.update({"signal": "Beobachten", "reason": "Unterbewertung vorhanden, fundamentale Basis jedoch schwach."})
    elif zone == "Fair bewertet":
        result.update({"signal": "Abwarten", "reason": "Kein ausreichender Bewertungsabschlag für einen Neukauf."})
    else:
        result.update({"signal": "Kein Kauf", "reason": "Kurs liegt oberhalb des angemessenen Bewertungsbereichs."})

    return result


def generate_holding_signal(valuation_zone, valuation_confidence, multiple_score):
    zone = (valuation_zone or {}).get("zone")
    confidence = (valuation_confidence or {}).get("level")
    fundamental = get_fundamental_strength(multiple_score)

    result = {
        "available": False,
        "signal": None,
        "fundamental_strength": fundamental,
        "reason": None,
    }

    if not zone or not confidence:
        result["reason"] = "Ohne belastbare Bewertungszone kein Bestands-Signal."
        return result

    result["available"] = True

    # Niedrige Bewertungssicherheit darf keine harte Bestandsaktion
    # wie Reduzieren oder Verkaufen auslösen. In diesem Fall bleibt
    # die Bewertung ein Prüfhinweis, bis die Gewinnbasis belastbarer ist.
    if confidence == "Niedrig":
        if fundamental == "Schwach":
            result.update({
                "signal": "Überprüfen",
                "reason": (
                    "Bewertungssicherheit niedrig und fundamentale Basis "
                    "schwach. Keine harte Verkaufsentscheidung allein aus "
                    "dem unsicheren Fair Value ableiten."
                ),
            })
        else:
            result.update({
                "signal": "Halten / nicht nachkaufen",
                "reason": (
                    "Bewertungssicherheit niedrig. Der Fair Value reicht "
                    "nicht für ein belastbares Reduzieren-/Verkaufen-Signal."
                ),
            })
        return result

    if zone in ["Stark unterbewertet", "Unterbewertet"]:
        if fundamental in ["Stark", "Ausreichend"] and confidence in ["Hoch", "Mittel"]:
            result.update({"signal": "Nachkaufen", "reason": "Unterbewertung bei ausreichender fundamentaler Basis und Bewertungssicherheit."})
        else:
            result.update({"signal": "Halten", "reason": "Bewertung attraktiv, aber Qualität oder Sicherheit begrenzen einen Nachkauf."})
    elif zone == "Fair bewertet":
        if fundamental == "Schwach":
            result.update({"signal": "Überprüfen", "reason": "Bewertung fair, fundamentale Basis jedoch schwach."})
        else:
            result.update({"signal": "Halten", "reason": "Aktie liegt innerhalb des angemessenen Bewertungsbereichs."})
    elif zone == "Überbewertet":
        if fundamental == "Schwach":
            result.update({"signal": "Reduzieren", "reason": "Überbewertung trifft auf schwache fundamentale Basis."})
        else:
            result.update({"signal": "Halten / nicht nachkaufen", "reason": "Moderate Überbewertung, aber noch kein zwingender Verkaufsfall."})
    elif zone == "Stark überbewertet":
        if fundamental == "Schwach":
            result.update({"signal": "Verkaufen", "reason": "Deutliche Überbewertung bei schwacher fundamentaler Basis."})
        else:
            result.update({"signal": "Reduzieren", "reason": "Aktie liegt deutlich über dem errechneten Fair Value."})

    return result


# =========================================================
# Modul 6 – Fair Value V1
# =========================================================

def calculate_fair_value_v1(
    eps_normalization,
    fundamental_multiple,
    peer_check,
    special_control,
    current_price,
    currency_context
):
    """
    Conservative Fair Value V1 for already-supported normal company types.

    Rules:
    - Requires a positive normalized EPS and a valid fundamental multiple.
    - Uses the peer-controlled multiple only when the peer check actually
      applied a valid adjustment; otherwise the fundamental multiple remains
      the valuation basis.
    - A required special control blocks the valuation until it is explicitly
      implemented and released. A released control never changes the score;
      it only permits the already-defined valuation chain to continue.
    - GBp/GBP is aligned explicitly with 1 GBP = 100 GBp. Other unexpected
      currency mismatches are blocked instead of silently converted.
    - No confidence rating and no action signal are produced here.
    """

    result = {
        "available": False,
        "normalized_eps": None,
        "used_multiple": None,
        "multiple_source": None,
        "fair_value_financial": None,
        "fair_value_quote": None,
        "financial_currency": None,
        "quote_currency": None,
        "current_price": safe_float(current_price),
        "potential_pct": None,
        "unit_conversion_applied": False,
        "unit_note": None,
        "note": None
    }

    context = (
        currency_context
        if isinstance(currency_context, dict)
        else {}
    )

    result["financial_currency"] = context.get(
        "financial_currency"
    )
    result["quote_currency"] = context.get(
        "quote_currency"
    )

    # Mining V2.11 hard safety gate. This is intentionally independent of the
    # special-control release flag so that stale cache/state can never release
    # a mining Fair Value before commodity-price / margin-cycle normalization.
    if (
        isinstance(special_control, dict)
        and special_control.get("control_key") == "mining_cycle_quality"
    ):
        checks = special_control.get("checks") or {}
        cycle_check = checks.get("cycle_eps", {})
        structural_fallback = checks.get("structural_break_fallback", {})
        if cycle_check.get("structural_break_blocked") and not structural_fallback.get("available", False):
            break_info = cycle_check.get("structural_break") or {}
            comparable_count = int(cycle_check.get("comparable_full_years_count") or 0)
            minimum_count = int(cycle_check.get("minimum_full_post_break_years") or 3)
            fallback_reason = structural_fallback.get("reason")
            result["note"] = (
                "Fair Value V1 gesperrt: Structural-Break-Kontrolle nicht bestanden und "
                "der alternative Bergbau-Fallback ist nicht freigegeben. "
                f"{break_info.get('event_name', 'Wesentlicher Strukturbruch')} am "
                f"{break_info.get('event_date', '–')}; danach liegen erst {comparable_count} "
                f"vollständig vergleichbare Geschäftsjahre vor, benötigt werden mindestens "
                f"{minimum_count}. Vor-Strukturbruch-Jahre werden nicht als gleichartige "
                "Zyklus-EPS-Basis verwendet."
                + ((" Fallback-Sperrgrund: " + str(fallback_reason)) if fallback_reason else "")
            )
            return result

        commodity_cycle = checks.get(
            "commodity_price_cycle", {}
        )
        earnings_translation = checks.get(
            "commodity_earnings_translation", {}
        )
        structural_fallback = checks.get("structural_break_fallback", {})
        if not commodity_cycle.get("available", False):
            if commodity_cycle.get("price_cycle_available", False):
                result["note"] = (
                    "Fair Value V1 gesperrt: Der Primärrohstoff-Preiszyklus ist zwar "
                    "normalisiert, aber die verifizierte unternehmensspezifische "
                    "AISC-/Kostenbasis für die Margen-Normalisierung fehlt. Die "
                    "Bergbau-Hard-Gate-Sperre ist aktiv."
                )
            else:
                result["note"] = (
                    "Fair Value V1 gesperrt: Bei Bergbauunternehmen ist die belastbare "
                    "Rohstoffpreis-/Margenzyklus-Normalisierung nicht vollständig "
                    "verfügbar. Die Bergbau-Hard-Gate-Sperre ist aktiv."
                )
            return result
        if not earnings_translation.get("available", False) and not structural_fallback.get("available", False):
            translation_reason = earnings_translation.get("reason")
            if translation_reason:
                result["note"] = (
                    "Fair Value V1 gesperrt: Der Rohstoffpreis-/Margenzyklus ist "
                    "normalisiert, aber weder die reguläre nachhaltige Ertragskraft noch "
                    "ein Structural-Break-Fallback wurden freigegeben. " + str(translation_reason)
                )
            else:
                result["note"] = (
                    "Fair Value V1 gesperrt: Der Rohstoffpreis-/Margenzyklus ist "
                    "normalisiert, aber die Ertragsbasis ist noch nicht belastbar freigegeben."
                )
            return result
        asset_nav_control = (special_control.get("checks") or {}).get(
            "mining_asset_nav_control", {}
        )
        lom_release_gate = asset_nav_control.get("lom_release_gate") or {}
        if lom_release_gate.get("available", False) and not lom_release_gate.get("released", False):
            result["note"] = (
                "Fair Value V1 gesperrt: Life-of-Mine-Freigabe-Gate V2.7 nicht "
                "bestanden. " + str(lom_release_gate.get("reason") or "Die aktuelle "
                "LOM-Abdeckung reicht nicht für einen finalen Bergbau-NAV.")
            )
            return result
        if not asset_nav_control.get("available", False):
            nav_reason = asset_nav_control.get("reason")
            if nav_reason:
                result["note"] = (
                    "Fair Value V1 gesperrt: Reserve-/Minenlebensdauer- & NAV-"
                    "Kontrolle nicht freigegeben. " + str(nav_reason)
                )
            else:
                result["note"] = (
                    "Fair Value V1 gesperrt: Reserve-/Minenlebensdauer und "
                    "Asset-NAV sind noch nicht belastbar freigegeben."
                )
            return result

    if (
        isinstance(special_control, dict)
        and special_control.get("required")
        and not special_control.get("released", False)
    ):
        control_name = special_control.get(
            "control_name"
        ) or "Spezialkontrolle"

        result["note"] = (
            "Fair Value V1 gesperrt: Für diesen Unternehmenstyp ist die "
            f"Spezialkontrolle „{control_name}“ erforderlich. Solange diese "
            "Kontrolle nicht fachlich vollständig implementiert und "
            "freigegeben ist, wird kein Fair Value erzeugt."
        )
        return result

    if not isinstance(fundamental_multiple, dict):
        result["note"] = (
            "Fair Value V1 nicht berechenbar: Kein belastbares "
            "Fundamental-Multiple verfügbar."
        )
        return result

    if not fundamental_multiple.get("available"):
        result["note"] = (
            "Fair Value V1 nicht berechenbar: Das Fundamental-Multiple "
            "ist noch nicht belastbar verfügbar. Fehlende Komponenten "
            "werden nicht ergänzt oder hochgerechnet."
        )
        return result

    normalized_eps = safe_float(
        (eps_normalization or {}).get(
            "normalized_eps"
        )
    )

    if normalized_eps is None or normalized_eps <= 0:
        result["note"] = (
            "Fair Value V1 gesperrt: Es liegt keine positive und "
            "verwertbare normalisierte Gewinnbasis vor."
        )
        return result

    base_multiple = safe_float(
        fundamental_multiple.get("multiple")
    )

    if base_multiple is None or base_multiple <= 0:
        result["note"] = (
            "Fair Value V1 nicht berechenbar: Das Fundamental-Multiple "
            "ist nicht positiv bzw. nicht plausibel verfügbar."
        )
        return result

    used_multiple = base_multiple
    multiple_source = "Fundamental-Multiple"

    if isinstance(peer_check, dict):
        peer_multiple = safe_float(
            peer_check.get("adjusted_multiple")
        )

        if (
            peer_check.get("method_supported")
            and peer_check.get("applied")
            and peer_multiple is not None
            and peer_multiple > 0
        ):
            used_multiple = peer_multiple
            multiple_source = "Peer-kontrolliertes Multiple"

    fair_value_financial = (
        normalized_eps * used_multiple
    )

    if fair_value_financial <= 0:
        result["note"] = (
            "Fair Value V1 nicht berechenbar: Die resultierende "
            "Bewertung ist nicht positiv."
        )
        return result

    quote_currency = str(
        context.get("quote_currency") or ""
    ).strip()
    financial_currency = str(
        context.get("financial_currency") or ""
    ).strip()

    if not quote_currency or not financial_currency:
        result["note"] = (
            "Fair Value V1 gesperrt: Die Währungseinheiten sind nicht "
            "ausreichend eindeutig verfügbar. Es wird keine Einheit geraten."
        )
        return result

    if context.get("mixed_units"):
        factor = safe_float(
            context.get("financial_to_quote_factor")
        )

        if (
            not context.get("conversion_available")
            or factor is None
            or factor <= 0
        ):
            result["note"] = (
                "Fair Value V1 gesperrt: Kurs- und Finanzwährung weichen "
                "voneinander ab, aber es ist keine belastbare ausdrückliche "
                "Umrechnung verfügbar."
            )
            return result

        fair_value_quote = fair_value_financial * factor
        result["unit_conversion_applied"] = True

        if context.get("conversion_kind") == "gbp_pence":
            result["unit_note"] = (
                "Einheitenangleichung ausdrücklich angewendet: Der Fair Value "
                "wird zunächst aus EPS in GBP berechnet und anschließend mit "
                "1 GBP = 100 GBp in die Kurs-Einheit GBp umgerechnet."
            )
        else:
            fx_symbol = context.get("fx_symbol")
            result["unit_note"] = (
                f"Währungsumrechnung ausdrücklich angewendet: 1 "
                f"{financial_currency} = {factor:.6f} {quote_currency}"
                + (f" über {fx_symbol}." if fx_symbol else ".")
            )

    else:
        if quote_currency != financial_currency:
            result["note"] = (
                "Fair Value V1 gesperrt: Kurs- und Finanzwährung weichen "
                "voneinander ab und es ist keine ausdrücklich hinterlegte "
                "Umrechnung verfügbar."
            )
            return result

        fair_value_quote = fair_value_financial

    current_price_value = safe_float(
        current_price
    )

    potential_pct = None
    if (
        current_price_value is not None
        and current_price_value > 0
    ):
        potential_pct = (
            fair_value_quote / current_price_value
            - 1.0
        ) * 100.0

    result.update({
        "available": True,
        "normalized_eps": normalized_eps,
        "used_multiple": used_multiple,
        "multiple_source": multiple_source,
        "fair_value_financial": fair_value_financial,
        "fair_value_quote": fair_value_quote,
        "potential_pct": potential_pct,
        "note": (
            "Fair Value V1 = normalisiertes EPS × verwendetes Multiple. "
            "Der Wert ist eine reine Bewertungsrechnung. Bewertungssicherheit, "
            "Bewertungszone und Signal werden in separaten nachfolgenden "
            "Schritten abgeleitet."
        )
    })

    return result


# =========================================================
# Handelsnotierung vs. Fundamentaldatenquelle
# =========================================================

def resolve_fundamental_symbol(selected_symbol, company_name=None):
    """
    Return a verified primary symbol for fundamentals when we have explicitly
    established one. Unknown secondary listings are NOT guessed.

    The selected symbol always remains the trading/price source.
    """
    symbol = str(selected_symbol or "").strip().upper()
    name = str(company_name or "").strip().upper()

    exact_routes = {
        # Cisco: German secondary listings -> Nasdaq primary fundamentals.
        "CIS.DE": "CSCO",
        "CIS.F": "CSCO",
        "CIS.BE": "CSCO",
        "CIS.MU": "CSCO",
        "CIS.DU": "CSCO",
        "CIS.HM": "CSCO",
        "CIS.HA": "CSCO",
        "CIS.SG": "CSCO",

        # Rheinmetall Frankfurt -> XETRA primary fundamentals.
        "RHM.F": "RHM.DE",
    }

    if symbol in exact_routes:
        return {
            "symbol": exact_routes[symbol],
            "separate_source": exact_routes[symbol] != symbol,
            "reason": "Verifizierte Hauptnotierung"
        }

    # Conservative name safeguard for Cisco German listings.
    if (
        "CISCO SYSTEMS" in name
        and symbol.startswith("CIS.")
    ):
        return {
            "symbol": "CSCO",
            "separate_source": True,
            "reason": "Verifizierte Hauptnotierung"
        }

    return {
        "symbol": symbol,
        "separate_source": False,
        "reason": "Ausgewählte Notierung"
    }


@st.cache_data(
    ttl=3600,
    show_spinner=False
)
def load_fx_conversion(
    from_currency,
    to_currency,
    cache_version
):
    """Load an explicit current FX factor: 1 from_currency -> to_currency."""
    _ = cache_version

    source = str(from_currency or "").strip()
    target = str(to_currency or "").strip()

    if source.upper() == "GBX":
        source = "GBp"
    if target.upper() == "GBX":
        target = "GBp"

    if not source or not target:
        return {"available": False, "factor": None, "symbol": None}

    if source == target:
        return {"available": True, "factor": 1.0, "symbol": None}

    if source == "GBP" and target == "GBp":
        return {"available": True, "factor": 100.0, "symbol": None}

    if source == "GBp" and target == "GBP":
        return {"available": True, "factor": 0.01, "symbol": None}

    # GBp is not a standalone FX currency. Other combinations involving GBp
    # require a two-step conversion and are intentionally not guessed here.
    if source == "GBp" or target == "GBp":
        return {"available": False, "factor": None, "symbol": None}

    direct_symbol = f"{source}{target}=X"
    inverse_symbol = f"{target}{source}=X"

    def last_rate(symbol):
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="5d")
            if history is not None and not history.empty and "Close" in history:
                close = history["Close"].dropna()
                if not close.empty:
                    value = safe_float(close.iloc[-1])
                    if value is not None and value > 0:
                        return value
        except Exception:
            pass

        try:
            info = yf.Ticker(symbol).info or {}
            value = safe_float(
                info.get("regularMarketPrice")
                or info.get("currentPrice")
                or info.get("previousClose")
            )
            if value is not None and value > 0:
                return value
        except Exception:
            pass

        return None

    direct = last_rate(direct_symbol)
    if direct is not None:
        return {
            "available": True,
            "factor": direct,
            "symbol": direct_symbol
        }

    inverse = last_rate(inverse_symbol)
    if inverse is not None and inverse > 0:
        return {
            "available": True,
            "factor": 1.0 / inverse,
            "symbol": inverse_symbol + " (invertiert)"
        }

    return {"available": False, "factor": None, "symbol": None}


# =========================================================
# Hauptdaten laden
# =========================================================

CACHE_VERSION = "m6_mining_managed_source_coverage_v2171_20260907"

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

    # -----------------------------------------------------
    # 1. Trading/quote source: exactly the selected listing.
    # -----------------------------------------------------
    quote_ticker = yf.Ticker(symbol)
    quote_info = quote_ticker.info or {}

    name = (
        quote_info.get("longName")
        or quote_info.get("shortName")
        or result.get("longname")
        or result.get("shortname")
        or symbol
    )

    price = (
        quote_info.get("currentPrice")
        or quote_info.get("regularMarketPrice")
        or quote_info.get("previousClose")
    )

    quote_currency = quote_info.get("currency")

    # -----------------------------------------------------
    # 2. Fundamental source: verified primary route only.
    #    Unknown secondary listings are not guessed.
    # -----------------------------------------------------
    fundamental_route = resolve_fundamental_symbol(
        symbol,
        name
    )
    fundamental_symbol = fundamental_route.get("symbol") or symbol

    if fundamental_symbol == symbol:
        fundamental_ticker = quote_ticker
        fundamental_info = quote_info
    else:
        fundamental_ticker = yf.Ticker(fundamental_symbol)
        fundamental_info = fundamental_ticker.info or {}

        # Hard safety fallback: if the routed source does not return usable
        # company data, keep the selected listing instead of mixing blanks.
        if not fundamental_info:
            fundamental_symbol = symbol
            fundamental_ticker = quote_ticker
            fundamental_info = quote_info
            fundamental_route = {
                "symbol": symbol,
                "separate_source": False,
                "reason": "Hauptnotierung nicht verfügbar – ausgewählte Notierung verwendet"
            }

    financial_currency = (
        fundamental_info.get("financialCurrency")
        or fundamental_info.get("currency")
        or quote_info.get("financialCurrency")
        or quote_currency
    )

    fx_conversion = load_fx_conversion(
        financial_currency,
        quote_currency,
        cache_version
    )

    currency_context = build_currency_context(
        quote_currency,
        financial_currency,
        fx_conversion
    )

    earnings_timestamp = (
        fundamental_info.get("earningsTimestamp")
        or fundamental_info.get("earningsTimestampStart")
        or quote_info.get("earningsTimestamp")
        or quote_info.get("earningsTimestampStart")
    )

    company_type = classify_company(
        name,
        fundamental_symbol,
        fundamental_info.get("sector") or quote_info.get("sector"),
        fundamental_info.get("industry") or quote_info.get("industry")
    )

    historical = build_historical_data(
        fundamental_ticker
    )

    trailing_eps = safe_float(
        fundamental_info.get("trailingEps")
    )
    forward_eps = safe_float(
        fundamental_info.get("forwardEps")
    )
    revenue = safe_float(
        fundamental_info.get("totalRevenue")
    )
    net_income = safe_float(
        fundamental_info.get("netIncomeToCommon")
    )
    free_cashflow = safe_float(
        fundamental_info.get("freeCashflow")
    )
    shares_outstanding = safe_float(
        fundamental_info.get("sharesOutstanding")
    )
    cash = safe_float(
        fundamental_info.get("totalCash")
    )
    debt = safe_float(
        fundamental_info.get("totalDebt")
    )
    revenue_growth = safe_float(
        fundamental_info.get("revenueGrowth")
    )
    earnings_growth = safe_float(
        fundamental_info.get("earningsGrowth")
    )
    roe = safe_float(
        fundamental_info.get("returnOnEquity")
    )

    profit_margin, profit_margin_note = (
        sanitize_profit_margin(
            fundamental_info.get("profitMargins"),
            net_income,
            revenue
        )
    )

    structural_break = resolve_structural_break(
        fundamental_symbol,
        company_type
    )

    eps_normalization = normalize_eps(
        company_type,
        trailing_eps,
        forward_eps,
        historical["eps"],
        revenue_growth,
        earnings_growth,
        structural_break=structural_break
    )

    growth_score = calculate_growth_score(
        revenue_growth,
        earnings_growth
    )

    profitability_score = calculate_profitability_score(
        company_type,
        profit_margin,
        roe,
        earnings_growth
    )

    fcf_score = calculate_fcf_score(
        company_type,
        revenue,
        free_cashflow,
        historical.get("fcf", [])
    )

    balance_score = calculate_balance_score(
        company_type,
        cash,
        debt,
        free_cashflow,
        historical.get("fcf", [])
    )

    # Special models receive the fundamental data package, while price is
    # still the selected market quote. Currency context converts explicitly
    # when a model needs price in the financial currency.
    insurance_special_model = build_insurance_special_model(
        company_type,
        fundamental_info,
        price,
        currency_context
    )

    bank_special_model = build_bank_special_model(
        company_type,
        fundamental_info,
        price,
        currency_context
    )

    midstream_special_model = build_midstream_special_model(
        company_type,
        fundamental_info,
        price,
        currency_context
    )

    auto_special_model = build_auto_special_model(
        company_type,
        fundamental_info,
        eps_normalization,
        currency_context
    )

    reit_special_model = build_reit_special_model(
        company_type,
        fundamental_info,
        price,
        currency_context
    )

    fundamental_multiple = calculate_fundamental_multiple(
        company_type,
        growth_score,
        profitability_score,
        fcf_score,
        balance_score,
        eps_normalization
    )

    peer_group = get_peer_group(
        company_type,
        fundamental_symbol
    )

    peer_check = calculate_peer_check(
        company_type,
        peer_group,
        fundamental_multiple.get("multiple"),
        cache_version,
        fundamental_multiple.get(
            "earnings_basis_usable",
            False
        )
    )

    special_control = get_special_control(
        company_type,
        symbol
    )

    special_control = build_defense_special_control(
        special_control,
        company_type,
        symbol
    )

    special_control = build_mining_special_control(
        special_control,
        company_type,
        symbol,
        eps_normalization,
        trailing_eps,
        forward_eps,
        historical,
        fcf_score,
        balance_score,
        profit_margin,
        roe,
        free_cashflow,
        net_income,
        shares_outstanding,
        fundamental_multiple,
        industry=fundamental_info.get("industry"),
    )

    fair_value = calculate_fair_value_v1(
        eps_normalization,
        fundamental_multiple,
        peer_check,
        special_control,
        price,
        currency_context
    )

    valuation_confidence = calculate_valuation_confidence(
        company_type,
        eps_normalization,
        peer_check,
        special_control,
        fair_value
    )

    valuation_zone = calculate_valuation_zone(
        price,
        fair_value,
        valuation_confidence
    )

    new_buy_signal = generate_new_buy_signal(
        valuation_zone,
        valuation_confidence,
        fundamental_multiple.get("score")
    )

    holding_signal = generate_holding_signal(
        valuation_zone,
        valuation_confidence,
        fundamental_multiple.get("score")
    )

    return {
        "name": name,
        "symbol": symbol,

        "quote_type": (
            quote_info.get("quoteType")
            or result.get("quoteType")
        ),

        "exchange": (
            quote_info.get("exchange")
            or result.get("exchange")
        ),

        "exchange_name": (
            quote_info.get("fullExchangeName")
            or result.get("exchDisp")
            or result.get("exchange")
        ),

        "fundamental_symbol": fundamental_symbol,
        "fundamental_source_separate": fundamental_symbol != symbol,
        "fundamental_source_reason": fundamental_route.get("reason"),
        "fundamental_exchange": fundamental_info.get("exchange"),
        "fundamental_exchange_name": (
            fundamental_info.get("fullExchangeName")
            or fundamental_info.get("exchange")
        ),

        "price": price,
        "currency": currency_context["quote_currency"],
        "financial_currency": currency_context["financial_currency"],
        "currency_context": currency_context,

        "sector": (
            fundamental_info.get("sector")
            or quote_info.get("sector")
        ),
        "industry": (
            fundamental_info.get("industry")
            or quote_info.get("industry")
        ),

        "market_cap": fundamental_info.get("marketCap"),
        "trailing_eps": trailing_eps,
        "forward_eps": forward_eps,

        "revenue": revenue,
        "net_income": net_income,
        "free_cashflow": free_cashflow,

        "cash": cash,
        "debt": debt,

        "revenue_growth": revenue_growth,
        "earnings_growth": earnings_growth,

        "profit_margin": profit_margin,
        "profit_margin_note": profit_margin_note,
        "roe": roe,

        "earnings_timestamp": earnings_timestamp,

        "company_type": company_type,
        "historical": historical,
        "structural_break": structural_break,
        "eps_normalization": eps_normalization,
        "growth_score": growth_score,
        "profitability_score": profitability_score,
        "fcf_score": fcf_score,
        "balance_score": balance_score,
        "insurance_special_model": insurance_special_model,
        "bank_special_model": bank_special_model,
        "midstream_special_model": midstream_special_model,
        "auto_special_model": auto_special_model,
        "reit_special_model": reit_special_model,
        "fundamental_multiple": fundamental_multiple,
        "peer_group": peer_group,
        "peer_check": peer_check,
        "special_control": special_control,
        "fair_value": fair_value,
        "valuation_confidence": valuation_confidence,
        "valuation_zone": valuation_zone,
        "new_buy_signal": new_buy_signal,
        "holding_signal": holding_signal
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
        "Ab 2 Zeichen suchen, z. B. Mi, AX, Rh, TSMC oder MSFT"
    )
).strip()

selected_symbol = None

if search_text:
    if len(search_text) < 2:
        st.caption(
            "Bitte mindestens 2 Zeichen eingeben. "
            "Danach öffnet sich automatisch die Aktienauswahl."
        )
    else:
        with st.spinner("Passende Aktien werden gesucht..."):
            suggestions = search_stock_suggestions(
                search_text
            )

        if suggestions:
            suggestion_map = {
                item["symbol"]: item
                for item in suggestions
            }

            def suggestion_label(symbol):
                item = suggestion_map[symbol]
                parts = [
                    str(item["name"]),
                    str(item["symbol"]),
                    str(item["exchange"]),
                ]

                if item.get("currency"):
                    parts.append(str(item["currency"]))

                return " · ".join(parts)

            selected_symbol = st.selectbox(
                "Treffer auswählen",
                options=list(suggestion_map.keys()),
                index=None,
                placeholder="Aktie auswählen …",
                format_func=suggestion_label
            )

            st.caption(
                "Die vollständigen Finanzdaten werden erst nach deiner "
                "Auswahl geladen. So wird kein erster Suchtreffer "
                "automatisch als richtige Aktie angenommen."
            )
        else:
            st.warning(
                "Keine passende Aktie in der automatischen Suche gefunden."
            )


if selected_symbol:

    with st.spinner(
        "Finanzdaten werden geladen und Analyse wird berechnet..."
    ):

        try:

            data = load_stock(
                selected_symbol,
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

                financial_currency = text_or_dash(
                    data.get(
                        "financial_currency",
                        data["currency"]
                    )
                )

                currency_context = data.get(
                    "currency_context",
                    {}
                )

                st.success("Aktie gefunden")

                st.header(data["name"])

                if search_text.upper() != str(
                    data["symbol"]
                ).upper():

                    st.info(
                        f"„{search_text}“ → "
                        f"{data['symbol']} "
                        f"aus Auswahl übernommen"
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

                if data.get("fundamental_source_separate"):
                    st.info(
                        "Handelsnotierung und Fundamentaldaten werden getrennt "
                        "geführt: "
                        f"Kurs von {data['symbol']} "
                        f"({text_or_dash(data['exchange_name'])}), "
                        f"Fundamentaldaten von {data['fundamental_symbol']} "
                        f"({text_or_dash(data.get('fundamental_exchange_name'))})."
                    )

                if currency_context.get("mixed_units"):
                    if currency_context.get("conversion_available"):
                        st.info(
                            currency_context.get("note")
                        )
                    else:
                        st.warning(
                            currency_context.get("note")
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
                            financial_currency
                        )
                    )

                    st.metric(
                        "EPS aktuell (TTM)",
                        format_eps(
                            data["trailing_eps"],
                            financial_currency
                        )
                    )

                    st.metric(
                        "EPS erwartet (Forward)",
                        format_eps(
                            data["forward_eps"],
                            financial_currency
                        )
                    )

                    st.metric(
                        "Umsatz",
                        format_money(
                            data["revenue"],
                            financial_currency
                        )
                    )

                with col2:

                    st.metric(
                        "Nettogewinn",
                        format_money(
                            data["net_income"],
                            financial_currency
                        )
                    )

                    st.metric(
                        "Free Cashflow",
                        format_money(
                            data["free_cashflow"],
                            financial_currency
                        )
                    )

                    st.metric(
                        "Liquide Mittel",
                        format_money(
                            data["cash"],
                            financial_currency
                        )
                    )

                    st.metric(
                        "Gesamtschulden",
                        format_money(
                            data["debt"],
                            financial_currency
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

                if data.get("profit_margin_note"):
                    st.warning(
                        data["profit_margin_note"]
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
                    financial_currency
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
                            financial_currency
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

                if eps_result.get("confidence_note"):
                    st.warning(
                        eps_result["confidence_note"]
                    )

                if eps_result.get("structural_break_active"):
                    break_info = eps_result.get("structural_break") or {}
                    st.warning(
                        "**Structural-Break-Kontrolle aktiv:** "
                        f"{break_info.get('event_name', 'wesentlicher Strukturbruch')} "
                        f"am {break_info.get('event_date', '–')}."
                    )
                    st.write(
                        "**Vollständig vergleichbare Jahre nach Strukturbruch:** "
                        + (
                            ", ".join(str(y) for y in eps_result.get("comparable_full_years", []))
                            or "keine"
                        )
                    )
                    st.write(
                        "**Aus der Zyklus-Normalisierung ausgeschlossene Jahre:** "
                        + (
                            ", ".join(str(y) for y in eps_result.get("excluded_history_years", []))
                            or "keine"
                        )
                    )
                    if eps_result.get("diagnostic_post_break_cycle_basis") is not None:
                        st.write(
                            "**Post-Break-EPS-Diagnose (nicht freigegebene Bewertungsbasis):** "
                            f"{format_eps(eps_result.get('diagnostic_post_break_cycle_basis'), financial_currency)}"
                        )
                    if eps_result.get("normalization_blocked_by_structural_break"):
                        st.error(
                            "Zyklus-EPS nicht freigegeben: "
                            f"{eps_result.get('comparable_full_years_count', 0)} vollständige "
                            "Vergleichsjahre nach dem Strukturbruch; benötigt werden mindestens "
                            f"{eps_result.get('minimum_full_post_break_years') or 3}."
                        )
                    if break_info.get("source_note"):
                        st.caption(break_info.get("source_note"))

                if (
                    eps_result["cycle_basis"]
                    is not None
                ):

                    st.write(
                        "**Zyklus-Basis vor "
                        "Forward-Anpassung:** "
                        f"{format_eps(
                            eps_result['cycle_basis'],
                            financial_currency
                        )}"
                    )

                if company_type.get("type") == "REIT / Immobilien":
                    st.caption(
                        "Das normalisierte EPS wird bei REITs nur "
                        "als Kontext angezeigt. Für die spätere "
                        "Bewertung sind FFO/AFFO maßgeblich."
                    )
                elif eps_result.get("normalization_blocked_by_structural_break"):
                    st.caption(
                        "Die reguläre Zyklus-EPS-Bewertungsbasis ist wegen des Structural Breaks "
                        "nicht freigegeben. Ein möglicher Bergbau-Fallback wird erst in Modul 6 "
                        "Schritt 3B separat geprüft."
                    )
                else:
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
                        f"{fcf_result['fcf_margin'] * 100:.2f} %"
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

                    elif fcf_result[
                        "status"
                    ] == "negative":

                        st.warning(
                            "⚠️ Negativer Free Cashflow erkannt"
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
                            financial_currency
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
                    "Banken, Versicherungen, REIT/Immobilien, "
                    "Autohersteller und Midstream-Unternehmen benötigen "
                    "Sondermodelle."
                )

                insurance_model = data.get(
                    "insurance_special_model",
                    {"applicable": False}
                )

                if insurance_model.get("applicable"):

                    st.divider()

                    st.subheader(
                        "🛡️ Versicherungs-Sondermodell V1 – Datenbasis"
                    )

                    st.info(
                        "Versicherungsmodell erkannt. In V1 werden nur "
                        "versicherungstypische Basiskennzahlen und "
                        "Einheiten plausibilisiert; es wird noch keine "
                        "Versicherungsbewertung erzeugt."
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        if insurance_model["roe"] is not None:
                            st.metric(
                                "ROE",
                                f"{insurance_model['roe'] * 100:.1f} %"
                            )
                        else:
                            st.metric(
                                "ROE",
                                "–"
                            )

                        if insurance_model[
                            "book_value_per_share"
                        ] is not None:
                            st.metric(
                                "Buchwert je Aktie",
                                format_eps(
                                    insurance_model[
                                        "book_value_per_share"
                                    ],
                                    financial_currency
                                )
                            )
                        else:
                            st.metric(
                                "Buchwert je Aktie",
                                "–"
                            )

                        if insurance_model[
                            "display_price_to_book"
                        ] is not None:
                            st.metric(
                                "KBV aus Kurs / Buchwert",
                                f"{insurance_model['display_price_to_book']:.2f}×"
                            )
                        else:
                            st.metric(
                                "KBV aus Kurs / Buchwert",
                                "–"
                            )

                    with col2:

                        if insurance_model[
                            "calculated_forward_pe"
                        ] is not None:
                            st.metric(
                                "Forward-KGV (nur Referenz)",
                                f"{insurance_model['calculated_forward_pe']:.2f}×"
                            )
                        else:
                            st.metric(
                                "Forward-KGV (nur Referenz)",
                                "–"
                            )

                        if insurance_model[
                            "dividend_yield"
                        ] is not None:
                            st.metric(
                                "Dividendenrendite",
                                f"{insurance_model['dividend_yield'] * 100:.2f} %"
                            )
                        else:
                            st.metric(
                                "Dividendenrendite",
                                "–"
                            )

                        if insurance_model.get(
                            "dividend_yield_source"
                        ):
                            st.caption(
                                "Quelle/Plausibilisierung: "
                                f"{insurance_model['dividend_yield_source']}"
                            )

                        if insurance_model[
                            "payout_ratio"
                        ] is not None:
                            st.metric(
                                "Ausschüttungsquote",
                                f"{insurance_model['payout_ratio'] * 100:.1f} %"
                            )
                        else:
                            st.metric(
                                "Ausschüttungsquote",
                                "–"
                            )

                    if data[
                        "currency_context"
                    ].get("mixed_units"):
                        price_financial = insurance_model.get(
                            "price_financial"
                        )
                        if price_financial is not None:
                            st.write(
                                "**Kurs für fundamentale Verhältniskennzahlen:** "
                                f"{price_financial:,.4f} {financial_currency} "
                                "(explizit aus der Pence-Notierung umgerechnet)"
                            )

                    if insurance_model.get(
                        "dividend_yield_note"
                    ):
                        dividend_note = insurance_model[
                            "dividend_yield_note"
                        ]
                        if dividend_note.startswith("⚠️"):
                            st.warning(dividend_note)
                        else:
                            st.caption(dividend_note)

                    if insurance_model.get(
                        "payout_ratio_note"
                    ):
                        st.warning(
                            insurance_model[
                                "payout_ratio_note"
                            ]
                        )

                    st.write(
                        "**Core Earnings:** – "
                        "(nicht separat verfügbar; wird nicht durch "
                        "Nettogewinn oder Standard-EPS ersetzt)"
                    )

                    st.write(
                        "**Solvency- / Kapitalquote:** – "
                        "(in der aktuellen Datenquelle nicht separat "
                        "verfügbar; wird nicht geschätzt)"
                    )

                    st.write(
                        "**Datenreife Sondermodell:** "
                        f"{insurance_model['readiness']}"
                    )

                    if insurance_model.get(
                        "pb_consistency_note"
                    ):
                        st.warning(
                            insurance_model[
                                "pb_consistency_note"
                            ]
                        )

                    st.caption(
                        insurance_model["note"]
                    )

                bank_model = data.get(
                    "bank_special_model",
                    {"applicable": False}
                )

                if bank_model.get("applicable"):

                    st.divider()

                    st.subheader(
                        "🏦 Banken-Sondermodell V1 – Datenbasis"
                    )

                    st.info(
                        "Bankmodell erkannt. In V1 werden nur "
                        "bankspezifische Basiskennzahlen und ihre "
                        "Einheiten/Plausibilität geprüft; es wird noch "
                        "keine Bankbewertung erzeugt."
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        if bank_model["roe"] is not None:
                            st.metric(
                                "ROE",
                                f"{bank_model['roe'] * 100:.1f} %"
                            )
                        else:
                            st.metric(
                                "ROE",
                                "–"
                            )

                        if bank_model[
                            "book_value_per_share"
                        ] is not None:
                            st.metric(
                                "Buchwert je Aktie",
                                format_eps(
                                    bank_model[
                                        "book_value_per_share"
                                    ],
                                    financial_currency
                                )
                            )
                        else:
                            st.metric(
                                "Buchwert je Aktie",
                                "–"
                            )

                        if bank_model[
                            "display_price_to_book"
                        ] is not None:
                            st.metric(
                                "KBV aus Kurs / Buchwert",
                                f"{bank_model['display_price_to_book']:.2f}×"
                            )
                        else:
                            st.metric(
                                "KBV aus Kurs / Buchwert",
                                "–"
                            )

                    with col2:

                        if bank_model[
                            "display_forward_pe"
                        ] is not None:
                            st.metric(
                                "Forward-KGV (nur Referenz)",
                                f"{bank_model['display_forward_pe']:.2f}×"
                            )
                        else:
                            st.metric(
                                "Forward-KGV (nur Referenz)",
                                "–"
                            )

                        st.metric(
                            "RoTE",
                            "–"
                        )

                        st.metric(
                            "CET1-Kapitalquote",
                            "–"
                        )

                    if data[
                        "currency_context"
                    ].get("mixed_units"):
                        price_financial = bank_model.get(
                            "price_financial"
                        )
                        if price_financial is not None:
                            st.write(
                                "**Kurs für fundamentale Verhältniskennzahlen:** "
                                f"{price_financial:,.4f} {financial_currency} "
                                "(explizit aus der Pence-Notierung umgerechnet)"
                            )

                    st.write(
                        "**Tangible Book Value / TBV:** – "
                        "(nicht separat belastbar verfügbar; normaler "
                        "Buchwert wird nicht als Ersatz verwendet)"
                    )

                    st.write(
                        "**RoTE:** – "
                        "(nicht separat verfügbar; ROE wird nicht als "
                        "identischer Ersatzwert behandelt)"
                    )

                    st.write(
                        "**CET1-Kapitalquote:** – "
                        "(in der aktuellen Datenquelle nicht separat "
                        "verfügbar; wird nicht geschätzt)"
                    )

                    st.write(
                        "**Datenreife Sondermodell:** "
                        f"{bank_model['readiness']}"
                    )

                    if bank_model.get(
                        "pb_consistency_note"
                    ):
                        pb_note = bank_model[
                            "pb_consistency_note"
                        ]
                        if pb_note.startswith("⚠️"):
                            st.warning(pb_note)
                        else:
                            st.caption(pb_note)

                    if bank_model.get(
                        "forward_pe_note"
                    ):
                        pe_note = bank_model[
                            "forward_pe_note"
                        ]
                        if pe_note.startswith("⚠️"):
                            st.warning(pe_note)
                        else:
                            st.caption(pe_note)

                    st.caption(
                        bank_model["note"]
                    )

                midstream_model = data.get(
                    "midstream_special_model",
                    {"applicable": False}
                )

                if midstream_model.get("applicable"):

                    st.divider()

                    st.subheader(
                        "🛢️ Midstream-Sondermodell V1 – Datenbasis"
                    )

                    st.info(
                        "Midstream-Modell erkannt. In V1 werden nur "
                        "EV/EBITDA-, Cashflow- und Verschuldungsdaten "
                        "plausibilisiert; es wird noch keine "
                        "Midstream-Bewertung erzeugt."
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        st.metric(
                            "EBITDA",
                            format_money(
                                midstream_model["ebitda"],
                                financial_currency
                            )
                        )

                        st.metric(
                            "Enterprise Value",
                            format_money(
                                midstream_model["enterprise_value"],
                                financial_currency
                            )
                        )

                        if midstream_model[
                            "display_ev_to_ebitda"
                        ] is not None:
                            st.metric(
                                "EV / EBITDA (nur Referenz)",
                                f"{midstream_model['display_ev_to_ebitda']:.2f}×"
                            )
                        else:
                            st.metric(
                                "EV / EBITDA (nur Referenz)",
                                "–"
                            )

                    with col2:

                        st.metric(
                            "Nettoschulden",
                            format_money(
                                midstream_model["net_debt"],
                                financial_currency
                            )
                        )

                        if midstream_model[
                            "net_debt_to_ebitda"
                        ] is not None:
                            st.metric(
                                "Netto-Schulden / EBITDA",
                                f"{midstream_model['net_debt_to_ebitda']:.2f}×"
                            )
                        else:
                            st.metric(
                                "Netto-Schulden / EBITDA",
                                "–"
                            )

                        st.metric(
                            "Operating Cashflow (nur Kontext)",
                            format_money(
                                midstream_model["operating_cashflow"],
                                financial_currency
                            )
                        )

                    st.write(
                        "**Distributable Cash Flow:** – "
                        "(nicht separat belastbar verfügbar; Yahoo-Free-"
                        "Cashflow und Operating Cashflow werden nicht als "
                        "Ersatz verwendet)"
                    )

                    if midstream_model.get(
                        "free_cashflow_reference"
                    ) is not None:
                        st.write(
                            "**Yahoo-Free-Cashflow nur als Rohdaten-Referenz:** "
                            f"{format_money(
                                midstream_model['free_cashflow_reference'],
                                financial_currency
                            )}"
                        )

                    st.write(
                        "**Datenreife Sondermodell:** "
                        f"{midstream_model['readiness']}"
                    )

                    if midstream_model.get(
                        "ev_to_ebitda_note"
                    ):
                        ev_note = midstream_model[
                            "ev_to_ebitda_note"
                        ]
                        if ev_note.startswith("⚠️"):
                            st.warning(ev_note)
                        else:
                            st.caption(ev_note)

                    st.caption(
                        midstream_model["note"]
                    )

                auto_model = data.get(
                    "auto_special_model",
                    {"applicable": False}
                )

                if auto_model.get("applicable"):

                    st.divider()

                    st.subheader(
                        "🚗 Autohersteller-Sondermodell V1 – Datenbasis"
                    )

                    st.info(
                        "Autohersteller-Modell erkannt. In V1 werden nur "
                        "Zyklus-EPS, EV/EBITDA und Konzern-Cashflow-Daten "
                        "plausibilisiert. Konsolidierte Schulden und Cashflows "
                        "werden nicht als reines Automotive-Industriegeschäft "
                        "interpretiert."
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        st.metric(
                            "Zyklus-/normalisiertes EPS",
                            format_eps(
                                auto_model["normalized_eps"],
                                financial_currency
                            )
                        )

                        st.write(
                            "**EPS-Methode:** "
                            f"{text_or_dash(auto_model['eps_method'])}"
                        )

                        st.write(
                            "**EPS-Sicherheit:** "
                            f"{text_or_dash(auto_model['eps_confidence'])}"
                        )

                        st.metric(
                            "EBITDA",
                            format_money(
                                auto_model["ebitda"],
                                financial_currency
                            )
                        )

                        st.metric(
                            "Enterprise Value",
                            format_money(
                                auto_model["enterprise_value"],
                                financial_currency
                            )
                        )

                        if auto_model[
                            "display_ev_to_ebitda"
                        ] is not None:
                            st.metric(
                                "EV / EBITDA (Konzern-Kontext)",
                                f"{auto_model['display_ev_to_ebitda']:.2f}×"
                            )
                        else:
                            st.metric(
                                "EV / EBITDA (Konzern-Kontext)",
                                "–"
                            )

                    with col2:

                        st.metric(
                            "Operating Cashflow (Konzern, nur Kontext)",
                            format_money(
                                auto_model["operating_cashflow"],
                                financial_currency
                            )
                        )

                        st.metric(
                            "Yahoo-Free-Cashflow (Konzern, nur Referenz)",
                            format_money(
                                auto_model["free_cashflow_reference"],
                                financial_currency
                            )
                        )

                        st.metric(
                            "Cash (Konzern, nur Referenz)",
                            format_money(
                                auto_model["total_cash_reference"],
                                financial_currency
                            )
                        )

                        st.metric(
                            "Schulden (Konzern, nur Referenz)",
                            format_money(
                                auto_model["total_debt_reference"],
                                financial_currency
                            )
                        )

                    st.write(
                        "**Automotive Free Cash Flow:** – "
                        "(nicht separat belastbar verfügbar; Konzern-FCF wird "
                        "nicht als Ersatz verwendet)"
                    )

                    st.write(
                        "**Industrie-Netto-Cash / -Schulden:** – "
                        "(nicht separat belastbar verfügbar; Konzern-Cash und "
                        "-Schulden werden nicht als Ersatz verwendet)"
                    )

                    st.write(
                        "**Finanzdienstleistungs-Anteil:** – "
                        "(in der aktuellen Datenquelle nicht separat belastbar "
                        "verfügbar; wird nicht geschätzt)"
                    )

                    st.write(
                        "**Datenreife Sondermodell:** "
                        f"{auto_model['readiness']}"
                    )

                    if auto_model.get(
                        "ev_to_ebitda_note"
                    ):
                        ev_note = auto_model[
                            "ev_to_ebitda_note"
                        ]
                        if ev_note.startswith("⚠️"):
                            st.warning(ev_note)
                        else:
                            st.caption(ev_note)

                    st.warning(
                        "Bei Autoherstellern können konsolidierte Yahoo-"
                        "Schulden und Cashflows das Finanzdienstleistungsgeschäft "
                        "enthalten. Deshalb werden diese Werte in V1 nicht für "
                        "eine normale Netto-Schulden/FCF-Bewertung verwendet."
                    )

                    st.caption(
                        auto_model["note"]
                    )

                reit_model = data.get(
                    "reit_special_model",
                    {"applicable": False}
                )

                if reit_model.get("applicable"):

                    st.divider()

                    st.subheader(
                        "🏢 REIT-/Immobilien-Sondermodell V1 – Datenbasis"
                    )

                    st.info(
                        "REIT-/Immobilien-Modell erkannt. In V1 werden nur "
                        "direkt verfügbare FFO/AFFO-Daten sowie EV/EBITDA- "
                        "und Verschuldungskennzahlen plausibilisiert. FFO "
                        "und AFFO werden nicht aus Standard-FCF oder "
                        "Nettogewinn rekonstruiert."
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        st.metric(
                            "FFO (direkt gemeldet)",
                            format_money(
                                reit_model["ffo_total"],
                                financial_currency
                            )
                        )

                        st.metric(
                            "FFO je Aktie (direkt gemeldet)",
                            format_eps(
                                reit_model["ffo_per_share"],
                                financial_currency
                            )
                        )

                        if reit_model["price_to_ffo"] is not None:
                            st.metric(
                                "P / FFO (nur Datenreferenz)",
                                f"{reit_model['price_to_ffo']:.2f}×"
                            )
                        else:
                            st.metric(
                                "P / FFO (nur Datenreferenz)",
                                "–"
                            )

                        st.metric(
                            "AFFO je Aktie (direkt gemeldet)",
                            format_eps(
                                reit_model["affo_per_share"],
                                financial_currency
                            )
                        )

                        if reit_model["price_to_affo"] is not None:
                            st.metric(
                                "P / AFFO (nur Datenreferenz)",
                                f"{reit_model['price_to_affo']:.2f}×"
                            )
                        else:
                            st.metric(
                                "P / AFFO (nur Datenreferenz)",
                                "–"
                            )

                    with col2:

                        st.metric(
                            "EBITDA",
                            format_money(
                                reit_model["ebitda"],
                                financial_currency
                            )
                        )

                        st.metric(
                            "Enterprise Value",
                            format_money(
                                reit_model["enterprise_value"],
                                financial_currency
                            )
                        )

                        if reit_model[
                            "display_ev_to_ebitda"
                        ] is not None:
                            st.metric(
                                "EV / EBITDA (nur Kontext)",
                                f"{reit_model['display_ev_to_ebitda']:.2f}×"
                            )
                        else:
                            st.metric(
                                "EV / EBITDA (nur Kontext)",
                                "–"
                            )

                        st.metric(
                            "Nettoschulden",
                            format_money(
                                reit_model["net_debt"],
                                financial_currency
                            )
                        )

                        if reit_model[
                            "net_debt_to_ebitda"
                        ] is not None:
                            st.metric(
                                "Netto-Schulden / EBITDA",
                                f"{reit_model['net_debt_to_ebitda']:.2f}×"
                            )
                        else:
                            st.metric(
                                "Netto-Schulden / EBITDA",
                                "–"
                            )

                    if data[
                        "currency_context"
                    ].get("mixed_units"):
                        price_financial = reit_model.get(
                            "price_financial"
                        )
                        if price_financial is not None:
                            st.write(
                                "**Kurs für fundamentale Verhältniskennzahlen:** "
                                f"{price_financial:,.4f} {financial_currency} "
                                "(explizit aus der Pence-Notierung umgerechnet)"
                            )

                    st.write(
                        "**NAV / EPRA NTA / Immobilienwert:** – "
                        "(in der aktuellen Datenquelle nicht separat belastbar "
                        "verfügbar; wird nicht aus Buchwert oder Enterprise "
                        "Value geschätzt)"
                    )

                    st.write(
                        "**Datenreife Sondermodell:** "
                        f"{reit_model['readiness']}"
                    )

                    st.caption(
                        reit_model["ffo_note"]
                    )

                    st.caption(
                        reit_model["affo_note"]
                    )

                    if reit_model.get(
                        "ev_to_ebitda_note"
                    ):
                        ev_note = reit_model[
                            "ev_to_ebitda_note"
                        ]
                        if ev_note.startswith("⚠️"):
                            st.warning(ev_note)
                        else:
                            st.caption(ev_note)

                    st.warning(
                        "Bei REITs werden normales EPS, Yahoo-Free-Cashflow "
                        "und die allgemeine Netto-Schulden/FCF-Logik nicht "
                        "als Ersatz für FFO/AFFO verwendet."
                    )

                    st.caption(
                        reit_model["note"]
                    )

                st.divider()

                st.subheader(
                    "🧭 Modul 6 – Bewertungs-Korridor & Fundamental-Multiple"
                )

                multiple_result = data[
                    "fundamental_multiple"
                ]

                corridor = multiple_result[
                    "corridor"
                ]

                if corridor["available"]:

                    st.write(
                        "**Bewertungs-Korridor:** "
                        f"{corridor['lower']:.1f}× bis "
                        f"{corridor['upper']:.1f}×"
                    )

                    st.write(
                        "**Multiple-Methode:** "
                        f"{corridor['method']}"
                    )

                else:

                    st.warning(
                        "Noch kein belastbarer "
                        "Bewertungs-Korridor verfügbar."
                    )

                if multiple_result["score"] is not None:

                    st.write(
                        "**Verwendeter Multiple Score:** "
                        f"{multiple_result['score']}/100"
                    )

                if multiple_result["available"]:

                    st.metric(
                        "Fundamental-Multiple",
                        f"{multiple_result['multiple']:.2f}×"
                    )

                    st.success(
                        "Fundamental-Multiple erfolgreich "
                        "aus Score und Korridor berechnet."
                    )

                else:

                    st.info(
                        "Noch kein Fundamental-Multiple berechenbar."
                    )

                st.caption(
                    multiple_result["note"]
                )

                st.caption(
                    "Schritt 1 berechnet ausschließlich das "
                    "Fundamental-Multiple. Peer-Check und Fair Value "
                    "werden in getrennten nachfolgenden Schritten geprüft."
                )

                st.divider()

                st.subheader(
                    "👥 Modul 6 – Schritt 2A: Peer-Gruppe"
                )

                peer_group = data[
                    "peer_group"
                ]

                if peer_group["available"]:

                    st.write(
                        "**Automatisch ausgewählte Peers:**"
                    )

                    for peer in peer_group["peers"]:
                        st.write(
                            f"• {peer['name']} "
                            f"({peer['symbol']})"
                        )

                    st.write(
                        "**Anzahl vorgesehener Peers:** "
                        f"{peer_group['count']}"
                    )

                    if peer_group["count"] >= 3:
                        st.success(
                            "Mindestens 3 vorgesehene Peers "
                            "vorhanden. Ob mindestens 3 davon "
                            "brauchbare Bewertungsdaten liefern, "
                            "wird erst in Schritt 2B geprüft."
                        )
                    else:
                        st.warning(
                            "Weniger als 3 vorgesehene Peers. "
                            "Damit wäre später keine automatische "
                            "Peer-Anpassung zulässig."
                        )

                else:

                    st.info(
                        "Noch keine automatische Peer-Gruppe "
                        "für diesen Unternehmenstyp hinterlegt."
                    )

                st.caption(
                    peer_group["note"]
                )

                st.caption(
                    "Schritt 2A verändert weder Multiple Score "
                    "noch Fundamental-Multiple. Peer-Median und "
                    "maximale ±5-%-Anpassung folgen erst nach "
                    "Prüfung der tatsächlichen Peer-Daten."
                )

                st.divider()

                st.subheader(
                    "📐 Modul 6 – Schritt 2B: Peer-Check"
                )

                peer_check = data[
                    "peer_check"
                ]

                if not peer_check[
                    "method_supported"
                ]:

                    st.info(
                        peer_check["note"]
                    )

                else:

                    st.write(
                        "**Geladene Peer-KGVs:**"
                    )

                    for row in peer_check[
                        "peer_rows"
                    ]:

                        if row["usable"]:

                            st.write(
                                f"• {row['name']} "
                                f"({row['symbol']}): "
                                f"{row['forward_pe']:.2f}×"
                            )

                        else:

                            st.write(
                                f"• {row['name']} "
                                f"({row['symbol']}): –"
                            )

                    st.write(
                        "**Brauchbare Peer-Daten:** "
                        f"{peer_check['usable_count']}"
                    )

                    if peer_check[
                        "peer_median"
                    ] is not None:

                        st.metric(
                            "Peer-Median Forward-KGV",
                            (
                                f"{peer_check['peer_median']:.2f}×"
                            )
                        )

                    if peer_check["applied"]:

                        adjustment_percent = (
                            peer_check[
                                "adjustment_pct"
                            ]
                            * 100.0
                        )

                        st.write(
                            "**Peer-Anpassung:** "
                            f"{adjustment_percent:+.2f} %"
                        )

                        st.metric(
                            "Peer-kontrolliertes Multiple",
                            (
                                f"{peer_check['adjusted_multiple']:.2f}×"
                            )
                        )

                        st.success(
                            "Peer-Kontrolle angewendet. "
                            "Die Anpassung ist auf maximal "
                            "±5 % begrenzt."
                        )

                    else:

                        if (
                            data[
                                "fundamental_multiple"
                            ]["available"]
                            and peer_check[
                                "adjusted_multiple"
                            ] is not None
                        ):

                            st.metric(
                                "Multiple nach Peer-Prüfung",
                                (
                                    f"{peer_check['adjusted_multiple']:.2f}×"
                                )
                            )

                        st.warning(
                            "Keine automatische Peer-Anpassung."
                        )

                    st.caption(
                        peer_check["note"]
                    )

                st.caption(
                    "Der Peer-Check ist nur ein externer "
                    "Realitätscheck. Er verändert den "
                    "100-Punkte-Multiple-Score nicht. "
                    "Mindestens 3 brauchbare Peers sind "
                    "Pflicht; der Median wird statt des "
                    "Durchschnitts verwendet."
                )

                st.caption(
                    "Der Peer-Check erzeugt selbst noch keinen Fair Value. "
                    "Die eigentliche Fair-Value-Rechnung folgt separat."
                )

                st.divider()

                st.subheader(
                    "🧩 Modul 6 – Schritt 3A: "
                    "Spezialkontroll-Router"
                )

                special_control = data[
                    "special_control"
                ]

                if special_control[
                    "required"
                ]:

                    st.success(
                        "Erkannte Spezialkontrolle: "
                        f"**{special_control['control_name']}**"
                    )

                    st.write(
                        "**Status:** "
                        f"{special_control.get('router_status', special_control.get('status'))}"
                    )

                    planned_checks = special_control[
                        "planned_checks"
                    ]

                    if planned_checks:

                        st.write(
                            "**Bereits festgelegte spätere "
                            "Prüfpunkte:**"
                        )

                        for check in planned_checks:
                            st.write(
                                f"• {check}"
                            )

                    st.info(
                        special_control.get(
                            "router_note",
                            special_control.get("note")
                        )
                    )

                else:

                    st.info(
                        "Für diesen Unternehmenstyp ist "
                        "in Schritt 3A keine separate "
                        "Spezialkontrolle hinterlegt."
                    )

                    st.caption(
                        special_control[
                            "note"
                        ]
                    )

                st.caption(
                    "Schritt 3A ist ausschließlich der Router. "
                    "Die eigentliche Spezialprüfung erfolgt – sofern bereits "
                    "implementiert – getrennt in Schritt 3B und verändert weder "
                    "Multiple Score noch Fundamental-/Peer-Multiple."
                )

                st.caption(
                    "Erforderliche Spezialkontrollen sperren den "
                    "nachfolgenden Fair-Value-Schritt, solange sie noch "
                    "nicht vollständig implementiert und freigegeben sind."
                )

                if special_control.get(
                    "control_key"
                ) == "defense_order_visibility":

                    st.divider()

                    st.subheader(
                        "🛡️ Modul 6 – Schritt 3B: "
                        "Defense-Auftrags- & Visibilitätskontrolle"
                    )

                    if special_control.get("implemented"):
                        snapshot = special_control.get("snapshot", {})
                        checks = special_control.get("checks", {})

                        st.write(
                            "**Datenstand:** "
                            f"{text_or_dash(snapshot.get('as_of_date'))} "
                            f"(veröffentlicht {text_or_dash(snapshot.get('published_date'))})"
                        )

                        backlog = checks.get("backlog", {})
                        coverage = checks.get("revenue_coverage", {})
                        fixed_orders = checks.get("fixed_orders", {})
                        book_to_bill = checks.get("book_to_bill", {})
                        near_term = checks.get("near_term_fixed_coverage", {})
                        margin_trend = checks.get("margin_trend", {})

                        col1, col2 = st.columns(2)

                        with col1:
                            st.metric(
                                "Backlog",
                                format_money(
                                    backlog.get("value"),
                                    financial_currency
                                )
                            )

                            if backlog.get("growth_pct") is not None:
                                st.metric(
                                    "Backlog-Wachstum",
                                    f"{backlog['growth_pct']:+.1f} %"
                                )

                            st.write(
                                "**Backlog-Status:** "
                                f"{backlog.get('status', '–')}"
                            )

                            if coverage.get("value") is not None:
                                st.metric(
                                    "Revenue Coverage",
                                    f"{coverage['value']:.2f}×"
                                )

                            st.write(
                                "**Coverage-Status:** "
                                f"{coverage.get('status', '–')}"
                            )

                            fixed_orders_value = format_money(
                                fixed_orders.get("value"),
                                financial_currency
                            )
                            if fixed_orders_value != "–":
                                fixed_orders_value = f"≈ {fixed_orders_value}"

                            st.metric(
                                "Fester Auftragsbestand",
                                fixed_orders_value
                            )

                            if fixed_orders.get("share_pct") is not None:
                                st.write(
                                    "**Anteil feste Aufträge am Backlog:** "
                                    f"{fixed_orders['share_pct']:.1f} %"
                                )

                            if fixed_orders.get("share_change_pp") is not None:
                                st.write(
                                    "**Veränderung ggü. Vorjahr:** "
                                    f"{fixed_orders['share_change_pp']:+.1f} Prozentpunkte"
                                )

                            st.write(
                                "**Fixed-Orders-Status:** "
                                f"{fixed_orders.get('status', '–')}"
                            )

                        with col2:
                            btb_value = book_to_bill.get("value")
                            if btb_value is not None:
                                btb_prefix = ">" if book_to_bill.get("is_lower_bound") else ""
                                st.metric(
                                    "Book-to-Bill",
                                    f"{btb_prefix}{btb_value:.1f}×"
                                )

                            st.write(
                                "**Book-to-Bill-Status:** "
                                f"{book_to_bill.get('status', '–')}"
                            )

                            if near_term.get("value_pct") is not None:
                                st.metric(
                                    "Kurzfristig feste Abdeckung",
                                    f"{near_term['value_pct']:.0f} %"
                                )

                            st.write(
                                "**Horizont:** "
                                f"{text_or_dash(near_term.get('horizon'))}"
                            )

                            if margin_trend.get("current_margin") is not None:
                                st.metric(
                                    "Operative Marge H1",
                                    f"{margin_trend['current_margin']:.1f} %"
                                )

                            if margin_trend.get("margin_change_pp") is not None:
                                st.write(
                                    "**Margenveränderung ggü. H1 Vorjahr:** "
                                    f"{margin_trend['margin_change_pp']:+.1f} Prozentpunkte"
                                )

                            if margin_trend.get("latest_quarter_margin") is not None:
                                st.write(
                                    "**Q2-Marge:** "
                                    f"{margin_trend['latest_quarter_margin']:.1f} %"
                                )

                            if margin_trend.get("guidance_margin") is not None:
                                st.write(
                                    "**Guidance Jahresmarge:** "
                                    f"ca. {margin_trend['guidance_margin']:.1f} %"
                                )

                            st.write(
                                "**Margentrend:** "
                                f"{margin_trend.get('overall_status', '–')}"
                            )

                        st.info(
                            snapshot.get("source_note")
                        )

                        if special_control.get("released"):
                            st.success(
                                "Defense-Visibilität: "
                                f"**{special_control.get('overall_status', 'Freigegeben')}** – "
                                "Spezialkontrolle bestanden. Fair Value freigegeben."
                            )
                        else:
                            st.warning(
                                "Defense-Spezialkontrolle nicht freigegeben. "
                                "Der Fair Value bleibt gesperrt."
                            )

                    else:
                        st.info(
                            special_control.get("note")
                        )

                    st.caption(
                        "Backlog und feste Aufträge werden bewusst getrennt. "
                        "Book-to-Bill verändert den 100-Punkte-Multiple-Score nicht. "
                        "Verifizierte Spezialdaten werden nach ihrem Gültigkeitsdatum "
                        "nicht stillschweigend weiterverwendet."
                    )

                if special_control.get(
                    "control_key"
                ) == "mining_cycle_quality":

                    st.divider()

                    st.subheader(
                        "⛏️ Modul 6 – Schritt 3B: "
                        "Bergbau-/Rohstoff-Zykluskontrolle"
                    )
                    st.caption("Bergbau-Schutzmodell V2.17.1 – Managed-Operations Source Coverage Map + V2.16 Portfolio-Aggregation")

                    if special_control.get("implemented"):
                        checks = special_control.get("checks", {})
                        cycle_eps = checks.get("cycle_eps", {})
                        fcf_stability = checks.get("fcf_stability", {})
                        balance_buffer = checks.get("balance_buffer", {})
                        profitability = checks.get("profitability", {})
                        operating = checks.get("operating_mine_data", {})
                        mining_snapshot = special_control.get("snapshot") or {}

                        col1, col2 = st.columns(2)

                        with col1:
                            st.metric(
                                "Zyklus-Basis EPS",
                                format_eps(
                                    cycle_eps.get("cycle_basis"),
                                    financial_currency
                                )
                            )
                            st.write(
                                "**Verfügbare EPS-Historie gesamt:** "
                                f"{cycle_eps.get('history_count', 0)} Jahre"
                            )
                            if cycle_eps.get("structural_break_blocked"):
                                break_info = cycle_eps.get("structural_break") or {}
                                st.warning(
                                    "Structural-Break aktiv: "
                                    f"{break_info.get('event_name', 'wesentlicher Strukturbruch')} "
                                    f"({break_info.get('event_date', '–')})."
                                )
                                st.write(
                                    "**Vergleichbare vollständige Post-Break-Jahre:** "
                                    + (
                                        ", ".join(str(y) for y in cycle_eps.get("comparable_full_years", []))
                                        or "keine"
                                    )
                                )
                                st.write(
                                    "**Ausgeschlossen:** "
                                    + (
                                        ", ".join(str(y) for y in cycle_eps.get("excluded_history_years", []))
                                        or "keine"
                                    )
                                )
                                if cycle_eps.get("diagnostic_post_break_cycle_basis") is not None:
                                    st.write(
                                        "**Post-Break-Diagnose-EPS:** "
                                        f"{format_eps(cycle_eps.get('diagnostic_post_break_cycle_basis'), financial_currency)} "
                                        "(nur Diagnose, keine Bewertungsbasis)"
                                    )
                            if cycle_eps.get("ttm_to_cycle_ratio") is not None:
                                st.metric(
                                    "TTM-EPS / Zyklus-Basis",
                                    f"{cycle_eps['ttm_to_cycle_ratio']:.2f}×"
                                )
                            st.write(
                                "**Peak-Cycle-Status:** "
                                f"{cycle_eps.get('status', '–')}"
                            )

                            st.write(
                                "**FCF-Stabilität:** "
                                f"{fcf_stability.get('status', '–')}"
                            )
                            if fcf_stability.get("structural_break_active", False):
                                st.write(
                                    "**Vergleichbare Post-Break-FCF-Jahre:** "
                                    + (
                                        ", ".join(
                                            str(y) for y in fcf_stability.get("comparable_post_break_years", [])
                                        )
                                        or "keine"
                                    )
                                )
                                st.write(
                                    "Post-Break positive / negative FCF-Jahre: "
                                    f"{fcf_stability.get('positive_years', 0)} / "
                                    f"{fcf_stability.get('negative_years', 0)}"
                                )
                                st.write(
                                    "**Ältere/Übergangs-FCF-Jahre:** "
                                    + (
                                        ", ".join(
                                            str(y) for y in fcf_stability.get("excluded_history_years", [])
                                        )
                                        or "keine"
                                    )
                                    + " (nur historische Information)"
                                )
                                st.caption(
                                    "Vor-Strukturbruch-FCFs werden nicht für die Stabilitätsfreigabe des heutigen "
                                    "Konzerns gleichgewichtet. Zwei positive Post-Break-Jahre können den Fallback "
                                    "stützen, reichen aber noch nicht für das Prädikat ‚Stark‘."
                                )
                            else:
                                st.write(
                                    "Positive / negative FCF-Jahre: "
                                    f"{fcf_stability.get('positive_years', 0)} / "
                                    f"{fcf_stability.get('negative_years', 0)}"
                                )

                        with col2:
                            st.write(
                                "**Bilanzpuffer:** "
                                f"{balance_buffer.get('status', '–')}"
                            )
                            net_debt_value = balance_buffer.get("net_debt")
                            if net_debt_value is not None:
                                st.metric(
                                    "Nettoschulden",
                                    format_money(
                                        net_debt_value,
                                        financial_currency
                                    )
                                )

                            st.write(
                                "**Aktuelle Profitabilität:** "
                                f"{profitability.get('status', '–')}"
                            )
                            if profitability.get("margin") is not None:
                                st.write(
                                    "Nettomarge: "
                                    f"{profitability['margin'] * 100:.1f} %"
                                )
                            if profitability.get("roe") is not None:
                                st.write(
                                    "ROE: "
                                    f"{profitability['roe'] * 100:.1f} %"
                                )

                            st.write(
                                "**Produktions-/Kostenvisibilität:** "
                                f"{operating.get('status', '–')}"
                            )

                        if mining_snapshot:
                            st.write(
                                "**Datenstand operative Minenkennzahlen:** "
                                f"{mining_snapshot.get('as_of_date', '–')} "
                                f"(veröffentlicht {mining_snapshot.get('published_date', '–')})"
                            )

                            op1, op2 = st.columns(2)

                            with op1:
                                current_low = _snapshot_first(
                                    mining_snapshot,
                                    "production_guidance_current_low",
                                    "production_guidance_current_low_moz",
                                )
                                current_high = _snapshot_first(
                                    mining_snapshot,
                                    "production_guidance_current_high",
                                    "production_guidance_current_high_moz",
                                )
                                previous_low = _snapshot_first(
                                    mining_snapshot,
                                    "production_guidance_previous_low",
                                    "production_guidance_previous_low_moz",
                                )
                                previous_high = _snapshot_first(
                                    mining_snapshot,
                                    "production_guidance_previous_high",
                                    "production_guidance_previous_high_moz",
                                )
                                prod_label = mining_snapshot.get(
                                    "production_guidance_label",
                                    "2026 Silber-Produktions-Guidance",
                                )
                                prod_unit = mining_snapshot.get(
                                    "production_guidance_unit", "Mio. oz"
                                )
                                prod_display = mining_snapshot.get("production_guidance_display")
                                prev_prod_display = mining_snapshot.get(
                                    "previous_production_guidance_display"
                                )

                                if prod_display:
                                    st.metric(prod_label, prod_display)
                                elif current_low is not None and current_high is not None:
                                    st.metric(
                                        prod_label,
                                        f"{current_low:.1f} – {current_high:.1f} {prod_unit}"
                                    )
                                if prev_prod_display:
                                    st.write(f"**Vorherige Guidance:** {prev_prod_display}")
                                elif previous_low is not None and previous_high is not None:
                                    st.write(
                                        "**Vorherige Guidance:** "
                                        f"{previous_low:.1f} – {previous_high:.1f} {prod_unit}"
                                    )
                                if operating.get("production_change_pct") is not None:
                                    st.write(
                                        "**Guidance-Mittelpunkt Veränderung:** "
                                        f"{operating['production_change_pct']:+.1f} %"
                                    )
                                st.write(
                                    "**Produktionsstatus:** "
                                    f"{operating.get('production_status', '–')}"
                                )

                            with op2:
                                aisc_low = _snapshot_first(
                                    mining_snapshot,
                                    "commodity_aisc_guidance_current_low",
                                    "silver_aisc_guidance_current_low",
                                )
                                aisc_high = _snapshot_first(
                                    mining_snapshot,
                                    "commodity_aisc_guidance_current_high",
                                    "silver_aisc_guidance_current_high",
                                )
                                aisc_prev_low = _snapshot_first(
                                    mining_snapshot,
                                    "commodity_aisc_guidance_previous_low",
                                    "silver_aisc_guidance_previous_low",
                                )
                                aisc_prev_high = _snapshot_first(
                                    mining_snapshot,
                                    "commodity_aisc_guidance_previous_high",
                                    "silver_aisc_guidance_previous_high",
                                )
                                q2_aisc = _snapshot_first(
                                    mining_snapshot, "q2_commodity_aisc", "q2_silver_aisc"
                                )
                                aisc_label = mining_snapshot.get(
                                    "aisc_guidance_label", "2026 Silver-AISC-Guidance"
                                )
                                aisc_unit = mining_snapshot.get("aisc_unit", "USD/oz")
                                aisc_display = mining_snapshot.get("aisc_guidance_display")
                                prev_aisc_display = mining_snapshot.get(
                                    "previous_aisc_guidance_display"
                                )
                                actual_label = mining_snapshot.get(
                                    "actual_aisc_label", "Q2 Silver AISC"
                                )
                                actual_display = mining_snapshot.get("actual_aisc_display")

                                if aisc_display:
                                    st.metric(aisc_label, aisc_display)
                                elif aisc_low is not None and aisc_high is not None:
                                    st.metric(
                                        aisc_label,
                                        f"{aisc_low:.2f} – {aisc_high:.2f} {aisc_unit}"
                                    )
                                if prev_aisc_display:
                                    st.write(f"**Vorherige AISC-Guidance:** {prev_aisc_display}")
                                elif aisc_prev_low is not None and aisc_prev_high is not None:
                                    st.write(
                                        "**Vorherige AISC-Guidance:** "
                                        f"{aisc_prev_low:.2f} – {aisc_prev_high:.2f} {aisc_unit}"
                                    )
                                if actual_display:
                                    st.write(f"**{actual_label}:** {actual_display}")
                                elif q2_aisc is not None:
                                    st.write(f"**{actual_label}:** {q2_aisc:.2f} {aisc_unit}")
                                if operating.get("aisc_improvement_pct") is not None:
                                    st.write(
                                        "**AISC-Guidance Veränderung ggü. vorher:** "
                                        f"{operating['aisc_improvement_pct']:+.1f} %"
                                    )
                                st.write(
                                    "**Kostenstatus:** "
                                    f"{operating.get('aisc_status', '–')}"
                                )

                            st.info(mining_snapshot.get("source_note"))
                            if mining_snapshot.get("guidance_comment"):
                                st.caption(mining_snapshot.get("guidance_comment"))
                        else:
                            st.caption(
                                "Für diese Bergbau-Aktie liegt noch kein verifizierter "
                                "operativer Snapshot mit Produktions-Guidance und AISC/"
                                "Stückkosten vor. Es wird nichts aus Yahoo geschätzt."
                            )

                        commodity_cycle = checks.get("commodity_price_cycle", {})
                        st.write(
                            "**Rohstoffpreis-/Preiszyklus-Normalisierung:** "
                            f"{commodity_cycle.get('status', 'Daten fehlen')}"
                        )

                        price_cycle_visible = commodity_cycle.get(
                            "price_cycle_available",
                            commodity_cycle.get("available", False),
                        )
                        if price_cycle_visible:
                            commodity_name = commodity_cycle.get("commodity_name", "Rohstoff")
                            commodity_symbol = commodity_cycle.get("commodity_symbol", "–")
                            unit = commodity_cycle.get("unit", "")
                            st.write(
                                f"**Primärrohstoff:** {commodity_name} ({commodity_symbol})"
                            )
                            route_source = commodity_cycle.get("route_source")
                            routing_basis = commodity_cycle.get("routing_basis")
                            if route_source or routing_basis:
                                route_text = " · ".join(
                                    str(x) for x in [route_source, routing_basis] if x
                                )
                                st.write(f"**Rohstoff-Routing:** {route_text}")
                            if commodity_cycle.get("mapping_note"):
                                st.caption(commodity_cycle.get("mapping_note"))

                            pc1, pc2 = st.columns(2)
                            with pc1:
                                normalized_price = commodity_cycle.get("normalized_price")
                                current_reference = commodity_cycle.get("current_reference_price")
                                if normalized_price is not None:
                                    st.metric(
                                        "Normalisierter Rohstoffpreis",
                                        f"{normalized_price:.2f} {unit}"
                                    )
                                if current_reference is not None:
                                    st.metric(
                                        "Aktuelle Preisreferenz",
                                        f"{current_reference:.2f} {unit}"
                                    )
                                premium = commodity_cycle.get("premium_to_normalized_pct")
                                if premium is not None:
                                    st.write(
                                        "**Abstand zum Zyklusnormal:** "
                                        f"{premium:+.1f} %"
                                    )
                                st.write(
                                    "**Preiszyklus-Status:** "
                                    f"{commodity_cycle.get('price_cycle_status', '–')}"
                                )

                            with pc2:
                                if commodity_cycle.get("margin_cycle_available", False):
                                    aisc_mid = commodity_cycle.get("aisc_midpoint")
                                    norm_margin = commodity_cycle.get("normalized_margin_per_oz")
                                    current_margin = commodity_cycle.get("current_margin_per_oz")
                                    if aisc_mid is not None:
                                        st.metric(
                                            "AISC-/Kosten-Mittelpunkt",
                                            f"{aisc_mid:.2f} {unit}"
                                        )
                                    if norm_margin is not None:
                                        st.metric(
                                            "Normalisierte Margin-Reserve",
                                            f"{norm_margin:.2f} {unit}"
                                        )
                                    if current_margin is not None:
                                        st.write(
                                            "**Aktuelle Margin-Reserve:** "
                                            f"{current_margin:.2f} {unit}"
                                        )
                                    st.write(
                                        "**Normalisierte Margentragfähigkeit:** "
                                        f"{commodity_cycle.get('margin_resilience_status', '–')}"
                                    )
                                    if commodity_cycle.get("cost_basis_note"):
                                        st.caption(commodity_cycle.get("cost_basis_note"))
                                else:
                                    st.warning(
                                        "Preiszyklus verfügbar, aber die verifizierte "
                                        "unternehmensspezifische AISC-/Kostenbasis fehlt. "
                                        "Die Margen- und Ertragskraft-Überleitung bleibt gesperrt."
                                    )

                            annual = commodity_cycle.get("annual_averages") or []
                            if annual:
                                annual_text = " · ".join(
                                    f"{item['year']}: {item['average']:.2f}"
                                    for item in annual
                                )
                                st.caption(
                                    f"Jahresdurchschnittspreise ({unit}): {annual_text}. "
                                    f"Methode: {commodity_cycle.get('method', '–')}."
                                )
                            if commodity_cycle.get("reason"):
                                st.caption(commodity_cycle.get("reason"))
                        else:
                            st.warning(
                                "Die Rohstoffpreis-Normalisierung konnte nicht belastbar "
                                "berechnet werden. Ohne diese Ebene bleibt der Fair Value "
                                "gesperrt."
                            )
                            if commodity_cycle.get("reason"):
                                st.caption(commodity_cycle.get("reason"))

                        earnings_translation = checks.get(
                            "commodity_earnings_translation", {}
                        )
                        st.write(
                            "**Überleitung Preiszyklus → normalisierte Ertragskraft:** "
                            f"{earnings_translation.get('status', 'Noch offen')}"
                        )
                        if earnings_translation.get("available", False):
                            et1, et2 = st.columns(2)
                            with et1:
                                if earnings_translation.get("used_margin_factor") is not None:
                                    st.metric(
                                        "Verwendeter Margen-Normalisierungsfaktor",
                                        f"{earnings_translation['used_margin_factor']:.3f}×"
                                    )
                                if earnings_translation.get("margin_adjusted_ttm_eps") is not None:
                                    st.metric(
                                        "Margenadjustiertes TTM-EPS",
                                        f"{earnings_translation['margin_adjusted_ttm_eps']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                                if earnings_translation.get("cycle_normalized_eps") is not None:
                                    st.write(
                                        "**Mehrjahres-/Zyklus-EPS:** "
                                        f"{earnings_translation['cycle_normalized_eps']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                                if earnings_translation.get("eps_convergence_pct") is not None:
                                    st.write(
                                        "**Abweichung der EPS-Wege:** "
                                        f"{earnings_translation['eps_convergence_pct']:.1f} % "
                                        f"({earnings_translation.get('eps_convergence_status', '–')})"
                                    )
                            with et2:
                                if earnings_translation.get("sustainable_eps") is not None:
                                    st.metric(
                                        "Plausibilisierte nachhaltige EPS-Basis",
                                        f"{earnings_translation['sustainable_eps']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                                if earnings_translation.get("normalized_fcf_per_share") is not None:
                                    st.metric(
                                        "Normalisierter FCF je Aktie (Kontrolle)",
                                        f"{earnings_translation['normalized_fcf_per_share']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                                st.write(
                                    "**FCF-Unterstützung:** "
                                    f"{earnings_translation.get('fcf_support_status', '–')}"
                                )
                                if earnings_translation.get("fcf_support_ratio") is not None:
                                    st.write(
                                        "**FCF / nachhaltiges EPS:** "
                                        f"{earnings_translation['fcf_support_ratio']:.2f}×"
                                    )
                            st.info(
                                "Die nachhaltige EPS-Basis wird nicht aus dem Primärrohstoffpreis "
                                "allein abgeleitet. Sie wird nur akzeptiert, wenn die "
                                "margenadjustierte TTM-Ertragskraft mit der unabhängigen "
                                "Mehrjahres-EPS-Normalisierung konvergiert und der "
                                "normalisierte FCF je Aktie die Richtung stützt."
                            )
                        else:
                            # V2.11: Auch bei gesperrter Ertragskraft die Diagnosewerte
                            # transparent zeigen. Die Freigabelogik selbst bleibt unverändert.
                            diag1, diag2 = st.columns(2)
                            with diag1:
                                if earnings_translation.get("used_margin_factor") is not None:
                                    st.metric(
                                        "Verwendeter Margen-Normalisierungsfaktor",
                                        f"{earnings_translation['used_margin_factor']:.3f}×"
                                    )
                                if earnings_translation.get("margin_adjusted_ttm_eps") is not None:
                                    st.metric(
                                        "Margenadjustiertes TTM-EPS",
                                        f"{earnings_translation['margin_adjusted_ttm_eps']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                                if earnings_translation.get("cycle_normalized_eps") is not None:
                                    st.write(
                                        "**Mehrjahres-/Zyklus-EPS:** "
                                        f"{earnings_translation['cycle_normalized_eps']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                                if earnings_translation.get("eps_convergence_pct") is not None:
                                    st.write(
                                        "**Abweichung der EPS-Wege:** "
                                        f"{earnings_translation['eps_convergence_pct']:.1f} % "
                                        f"({earnings_translation.get('eps_convergence_status', '–')})"
                                    )
                            with diag2:
                                if earnings_translation.get("normalized_fcf_per_share") is not None:
                                    st.metric(
                                        "Normalisierter FCF je Aktie (Kontrolle)",
                                        f"{earnings_translation['normalized_fcf_per_share']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                                regular_cycle_blocked = bool((checks.get("cycle_eps") or {}).get("structural_break_blocked"))
                                fcf_support_display = (
                                    "Für reguläre Zyklus-EPS-Überleitung nicht anwendbar"
                                    if regular_cycle_blocked
                                    else earnings_translation.get("fcf_support_status", "–")
                                )
                                st.write(
                                    "**FCF-Unterstützung:** "
                                    f"{fcf_support_display}"
                                )
                                if earnings_translation.get("fcf_support_ratio") is not None:
                                    st.write(
                                        "**FCF / diagnostische EPS-Basis:** "
                                        f"{earnings_translation['fcf_support_ratio']:.2f}×"
                                    )

                            st.warning(
                                "Die Ertragskraft-Überleitung ist nicht freigegeben. "
                                "Die Diagnosewerte werden nur zur Nachvollziehbarkeit angezeigt "
                                "und erzeugen kein nachhaltiges EPS für die Bewertung."
                            )
                            if earnings_translation.get("reason"):
                                st.caption("Sperrgrund: " + earnings_translation.get("reason"))

                        structural_fallback = checks.get("structural_break_fallback", {})
                        if structural_fallback.get("applicable", False):
                            st.write(
                                "**Structural-Break-Fallback V2.13.1 (unverändert innerhalb V2.17.1):** "
                                f"{structural_fallback.get('status', 'Noch offen')}"
                            )
                            fb1, fb2 = st.columns(2)
                            with fb1:
                                if structural_fallback.get("production_midpoint_moz") is not None:
                                    st.metric(
                                        "Verifizierte Produktions-Run-rate",
                                        f"{structural_fallback['production_midpoint_moz']:.2f} Mio. oz"
                                    )
                                if structural_fallback.get("normalized_margin_pool_musd") is not None:
                                    st.metric(
                                        "Normalisierter Primärrohstoff-Margenpool",
                                        f"{structural_fallback['normalized_margin_pool_musd'] / 1000.0:.2f} Mrd. USD"
                                    )
                                if structural_fallback.get("used_margin_factor") is not None:
                                    st.write(
                                        "**Down-Normalisierungsfaktor:** "
                                        f"{structural_fallback['used_margin_factor']:.3f}×"
                                    )
                                if structural_fallback.get("margin_adjusted_ttm_eps") is not None:
                                    st.metric(
                                        "Margenadjustiertes TTM-EPS (Fallback)",
                                        f"{structural_fallback['margin_adjusted_ttm_eps']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                            with fb2:
                                if structural_fallback.get("current_fcf_per_share") is not None:
                                    st.metric(
                                        "Aktueller FCF je Aktie (Cash-Conversion)",
                                        f"{structural_fallback['current_fcf_per_share']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                                if structural_fallback.get("normalized_fcf_per_share") is not None:
                                    st.metric(
                                        "Mit gleichem Faktor skalierter FCF je Aktie",
                                        f"{structural_fallback['normalized_fcf_per_share']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                                if structural_fallback.get("cash_conversion_gap_pct") is not None:
                                    st.write(
                                        "**Cash-Conversion-Abweichung (TTM-EPS vs. aktueller FCF/Aktie):** "
                                        f"{structural_fallback['cash_conversion_gap_pct']:.1f} % "
                                        f"({structural_fallback.get('cash_conversion_status', '–')})"
                                    )
                                if structural_fallback.get("current_fcf_to_ttm_eps_ratio") is not None:
                                    st.write(
                                        "**Aktueller FCF/Aktie / TTM-EPS:** "
                                        f"{structural_fallback['current_fcf_to_ttm_eps_ratio']:.2f}×"
                                    )
                                st.caption(
                                    "Der skalierte FCF je Aktie verwendet denselben Rohstoffmargenfaktor wie das "
                                    "Fallback-EPS. Er ist deshalb keine unabhängige zweite Normalisierung, sondern "
                                    "nur die normalisierte Darstellung der aktuellen Cash-Conversion."
                                )
                                if structural_fallback.get("valuation_earnings_per_share") is not None:
                                    st.metric(
                                        "Alternative Ertragsbasis je Aktie",
                                        f"{structural_fallback['valuation_earnings_per_share']:.2f} {data.get('financial_currency') or data.get('currency') or ''}"
                                    )
                            if structural_fallback.get("available", False):
                                st.success(
                                    "Fallback-Plausibilitätsgate bestanden: Die reguläre 3-Jahres-Zyklus-EPS-Regel "
                                    "bleibt gesperrt. Der Anker wird durch normalisierte Rohstoffmarge, Produktion/Kosten, "
                                    "positive Post-Break-FCF-Jahre und aktuelle Cash-Conversion gestützt. Der FCF ist "
                                    "kein unabhängiger Normalisierungsweg; es entstehen weder KGV-Multiple noch Fair Value."
                                )
                            else:
                                st.warning(
                                    "Structural-Break-Fallback nicht freigegeben. Die normale 3-Jahres-Regel "
                                    "wird nicht umgangen."
                                )
                            if structural_fallback.get("reason"):
                                st.caption(structural_fallback.get("reason"))

                        asset_nav_control = checks.get("mining_asset_nav_control", {})
                        st.write(
                            "**Reserve-/Minenlebensdauer- & NAV-Kontrolle:** "
                            f"{asset_nav_control.get('status', 'Noch offen')}"
                        )

                        asset_snapshot = asset_nav_control.get("snapshot") or {}
                        if asset_snapshot:
                            st.write(
                                "**Datenstand Reserven:** "
                                f"{asset_snapshot.get('reserve_as_of_date', '–')} "
                                f"(veröffentlicht {asset_snapshot.get('reserve_published_date', '–')})"
                            )

                            commodity_label = asset_snapshot.get("primary_commodity_label") or "Primärrohstoff"
                            total_primary_reserves = safe_float(
                                asset_nav_control.get("total_core_primary_reserves_moz")
                            )
                            if total_primary_reserves is None:
                                total_primary_reserves = safe_float(
                                    asset_nav_control.get("total_core_silver_reserves_moz")
                                )

                            navc1, navc2 = st.columns(2)
                            with navc1:
                                if total_primary_reserves is not None:
                                    reserve_metric_label = (
                                        "Kern-Silberreserven"
                                        if str(commodity_label).lower() == "silber"
                                        else f"{commodity_label}reserven (zurechenbar)"
                                    )
                                    st.metric(
                                        reserve_metric_label,
                                        f"{total_primary_reserves:.1f} Mio. oz"
                                    )
                                if asset_nav_control.get("company_average_reserve_mine_life_years") is not None:
                                    company_name = asset_snapshot.get("company") or "Unternehmen"
                                    st.metric(
                                        f"{company_name} Ø Reserve-Minenleben",
                                        f"{asset_nav_control['company_average_reserve_mine_life_years']:.1f} Jahre"
                                    )
                                if asset_nav_control.get("reserve_coverage_years") is not None:
                                    st.write(
                                        "**Reserve/Guidance-Abdeckung:** "
                                        f"{asset_nav_control['reserve_coverage_years']:.1f} Jahre "
                                        "(Portfolio-Kontrollrechnung, kein mine-spezifisches LOM-Profil)"
                                    )
                                    st.write(
                                        "**Portfolio-Reserveabdeckung:** "
                                        f"{asset_nav_control.get('portfolio_reserve_coverage_status', '–')}"
                                    )
                                st.write(
                                    "**Mine-spezifische LOM-Abdeckung:** "
                                    f"{asset_nav_control.get('mine_life_status', '–')}"
                                )
                                if asset_snapshot.get("mine_life_note"):
                                    st.caption(asset_snapshot.get("mine_life_note"))

                            with navc2:
                                reserve_price_basis = safe_float(
                                    asset_snapshot.get("reserve_price_basis_primary")
                                    if asset_snapshot.get("reserve_price_basis_primary") is not None
                                    else asset_snapshot.get("reserve_price_basis_silver")
                                )
                                if reserve_price_basis is not None:
                                    st.metric(
                                        f"{commodity_label}preis-Basis der Reserven",
                                        f"{reserve_price_basis:.2f} USD/oz"
                                    )
                                if asset_nav_control.get("reserve_price_alignment_pct") is not None:
                                    st.write(
                                        f"**Abstand zum normalisierten {commodity_label}preis:** "
                                        f"{asset_nav_control['reserve_price_alignment_pct']:.1f} % "
                                        f"({asset_nav_control.get('reserve_price_alignment_status', '–')})"
                                    )
                                st.write(
                                    "**Reserve-Snapshot:** "
                                    + (
                                        "Aktuell"
                                        if asset_nav_control.get("reserve_snapshot_fresh", False)
                                        else "Veraltet / nicht freigegeben"
                                    )
                                )

                            reserve_map = (
                                asset_snapshot.get("primary_reserves_moz")
                                or asset_snapshot.get("silver_reserves_moz")
                                or {}
                            )
                            if reserve_map:
                                reserve_text = " · ".join(
                                    f"{name}: {value:.1f} Mio. oz"
                                    for name, value in reserve_map.items()
                                )
                                st.caption(f"{commodity_label}reserven nach Asset: " + reserve_text)
                            if asset_snapshot.get("reserve_source_note"):
                                st.info(asset_snapshot.get("reserve_source_note"))

                            core_lom = asset_nav_control.get("core_asset_lom_structure") or {}
                            if core_lom.get("available"):
                                st.markdown("**Portfolio-LOM-Abdeckungsstruktur (V2.17.1):**")
                                cov1, cov2, cov3 = st.columns(3)
                                with cov1:
                                    st.metric("Gesamtportfolio-Reserven", f"{safe_float(core_lom.get('total_reserves_moz')) or 0.0:.1f} Mio. oz")
                                with cov2:
                                    st.metric("Gemanagte operative Reserven", f"{safe_float(core_lom.get('managed_operating_reserves_moz')) or 0.0:.1f} Mio. oz")
                                with cov3:
                                    st.metric("Phase-1-TRS-Reserven", f"{safe_float(core_lom.get('phase1_trs_eligible_reserves_moz')) or 0.0:.1f} Mio. oz")

                                cov4, cov5, cov6, cov7 = st.columns(4)
                                with cov4:
                                    st.metric("Native-rate NAV freigegeben", f"{safe_float(core_lom.get('native_nav_released_reserves_moz')) or 0.0:.1f} Mio. oz")
                                with cov5:
                                    st.metric("Portfolio-Aggregations-NAV", f"{safe_float(core_lom.get('portfolio_aggregation_reserves_moz')) or 0.0:.1f} Mio. oz")
                                with cov6:
                                    st.metric("Aggregation / gemanagt", f"{core_lom.get('portfolio_aggregation_managed_operating_coverage_pct', 0.0):.1f} %")
                                with cov7:
                                    st.metric("8%-Vergleich / gemanagt", f"{core_lom.get('portfolio_comparable_managed_operating_coverage_pct', 0.0):.1f} %")
                                st.caption(
                                    f"8-%-Vergleichsschicht: {safe_float(core_lom.get('portfolio_comparable_reserves_moz')) or 0.0:.1f} Mio. oz "
                                    f"({core_lom.get('portfolio_comparable_total_portfolio_coverage_pct', 0.0):.1f} % des Gesamtportfolios). "
                                    "Diese Schicht ist Vergleich, nicht das bindende 90-%-Aggregationsgate."
                                )

                                st.write(
                                    f"**Gemanagte operative Reservebasis / Gesamt:** {core_lom.get('managed_operating_portfolio_coverage_pct', 0.0):.1f} % · "
                                    f"**Nicht gemanagte JV-Reserven:** {core_lom.get('nonmanaged_jv_coverage_pct', 0.0):.1f} % · "
                                    f"**Entwicklungs-/Projektreserven:** {core_lom.get('development_project_coverage_pct', 0.0):.1f} %"
                                )
                                st.caption(core_lom.get("source_note") or "")

                                completeness_gate = core_lom.get("portfolio_completeness_gate") or {}
                                if completeness_gate.get("available"):
                                    st.markdown("**Portfolio-Completeness-Gate (V2.14.2 innerhalb V2.17.1):**")
                                    block_map = {b.get("key"): b for b in completeness_gate.get("blocks", [])}
                                    pc1, pc2, pc3 = st.columns(3)
                                    for col, key in [
                                        (pc1, "managed_operations"),
                                        (pc2, "nonmanaged_jvs"),
                                        (pc3, "development_projects"),
                                    ]:
                                        block = block_map.get(key, {})
                                        with col:
                                            st.metric(
                                                block.get("label", key),
                                                f"{safe_float(block.get('reserve_share_pct')) or 0.0:.1f} % der Reserven",
                                            )
                                            st.caption(block.get("completion_status", "Noch offen"))
                                            if block.get("detail"):
                                                st.caption(block.get("detail"))
                                            st.caption(
                                                "Konservativer Nullansatz: "
                                                + ("Ja – ausdrücklich gesetzt" if block.get("conservative_zero_explicit") else "Nein")
                                            )
                                    st.write(
                                        "**Materielle Portfolio-Blöcke vollständig behandelt:** "
                                        f"{int(completeness_gate.get('completed_material_block_count') or 0)}/"
                                        f"{int(completeness_gate.get('material_block_count') or 0)}"
                                    )
                                    st.caption(
                                        "Ein bestandener Managed-Operations-LOM-Gate reicht allein nicht für den Newmont-Gesamt-Fair-Value. "
                                        "JVs und Entwicklungsprojekte müssen separat bewertet oder ausdrücklich konservativ mit 0 angesetzt werden. "
                                        "Automatische Nullansätze sind nicht zulässig."
                                    )
                                    if not completeness_gate.get("released", False):
                                        st.warning(completeness_gate.get("reason") or "Portfolio-Completeness-Gate nicht freigegeben.")

                                phase1 = core_lom.get("technical_lom_phase1") or {}
                                if phase1.get("available"):
                                    st.markdown("**Technische LOM/NAV-Prüfung Phase 1 – Teilmodul V2.14.1 innerhalb V2.17.1:**")
                                    st.write(f"**Status:** {phase1.get('status', '–')}")
                                    p1c1, p1c2, p1c3, p1c4 = st.columns(4)
                                    with p1c1:
                                        st.metric(
                                            "NAV-Kandidaten / Reserve-Assetgruppen",
                                            f"{phase1.get('eligible_asset_count', 0)}/{phase1.get('managed_operating_asset_group_count', 0)}"
                                        )
                                    with p1c2:
                                        st.metric(
                                            "Phase-1-TRS-Reserven",
                                            f"{safe_float(phase1.get('verified_trs_reserves_moz')) or 0.0:.1f} Mio. oz"
                                        )
                                    with p1c3:
                                        st.metric(
                                            "TRS-Abdeckung gemanagt operativ",
                                            f"{safe_float(phase1.get('nav_eligible_managed_operating_coverage_pct')) or 0.0:.1f} %"
                                        )
                                    with p1c4:
                                        st.metric(
                                            "TRS-Abdeckung Gesamtportfolio",
                                            f"{safe_float(phase1.get('total_portfolio_coverage_pct')) or 0.0:.1f} %"
                                        )
                                    st.caption(
                                        f"Bindender Gate-Nenner: {safe_float(phase1.get('managed_operating_reserves_moz')) or 0.0:.1f} Mio. oz "
                                        "gemanagte operative Goldreserven. Ahafo North/South werden als eine Reserve-/TRS-Assetgruppe zusammengefasst."
                                    )

                                    st.caption(phase1.get("source_note") or "")
                                    st.write("**Aktuelle Phase-1-TRS-Kandidaten:**")
                                    for trs in phase1.get("eligible_assets", []):
                                        st.write(
                                            f"• **{trs.get('asset')}** – Exhibit {trs.get('trs_exhibit')} · "
                                            f"TRS effektiv {trs.get('effective_date')} · Reserve {safe_float(trs.get('reserve_moz')) or 0.0:.1f} Mio. oz"
                                        )
                                        t1, t2, t3 = st.columns(3)
                                        with t1:
                                            st.write(f"Diskontsatz: {safe_float(trs.get('discount_rate_pct')) or 0.0:.1f} %")
                                            if trs.get("active_mining_end_year"):
                                                st.write(f"Aktiver Minenplan bis: {trs.get('active_mining_end_year')}")
                                        with t2:
                                            npv = safe_float(trs.get("native_after_tax_npv_musd"))
                                            fcf = safe_float(trs.get("native_fcf_musd"))
                                            if npv is not None:
                                                st.write(f"Native TRS-NPV-Referenz: {npv/1000.0:.2f} Mrd. USD")
                                            if fcf is not None:
                                                st.write(f"Native TRS-FCF: {fcf/1000.0:.2f} Mrd. USD")
                                        with t3:
                                            capex = safe_float(trs.get("lom_capital_musd"))
                                            opex = safe_float(trs.get("lom_operating_cost_musd"))
                                            if capex is not None:
                                                st.write(f"LOM-Kapital: {capex/1000.0:.2f} Mrd. USD")
                                            if opex is not None:
                                                st.write(f"LOM-Betriebskosten: {opex/1000.0:.2f} Mrd. USD")
                                        st.caption(
                                            "Produktionspfad: ja · Betriebskosten: ja · CapEx: ja · Steuern/Royalties: ja · "
                                            "jährliche Cashflows: ja. " + str(trs.get("note") or "")
                                        )

                                    missing = phase1.get("missing_current_trs_assets", [])
                                    if missing:
                                        missing_text = " · ".join(
                                            f"{x.get('asset')} ({safe_float(x.get('reserve_moz')) or 0.0:.1f} Mio. oz)"
                                            for x in missing
                                        )
                                        st.write(f"**Noch ohne gleichwertig aktuelles Phase-1-TRS:** {missing_text}")
                                        st.caption(
                                            "Für diese gemanagten operativen Reserve-Assetgruppen ist im verifizierten Newmont-2025-Form-10-K-Exhibit-Set "
                                            "kein gleichwertiges aktuelles S-K-1300-TRS hinterlegt. Fehlende Daten werden nicht aus Run-rate-"
                                            "Guidance oder Reserveleben hochgerechnet."
                                        )

                                    source_map = phase1.get("managed_source_coverage_map") or {}
                                    if source_map.get("available"):
                                        st.markdown("**V2.17.1 – Managed-Operations Source Coverage Map:**")
                                        st.write(f"**Status:** {source_map.get('status', '–')}")
                                        sm1, sm2, sm3, sm4 = st.columns(4)
                                        with sm1:
                                            st.metric(
                                                "Offene Managed-Assets",
                                                f"{int(source_map.get('open_asset_count') or 0)} · {safe_float(source_map.get('open_reserves_moz')) or 0.0:.1f} Mio. oz",
                                            )
                                        with sm2:
                                            st.metric(
                                                "Aktueller Voll-TRS",
                                                f"{int(source_map.get('current_full_trs_asset_count') or 0)}/{int(source_map.get('open_asset_count') or 0)}",
                                            )
                                        with sm3:
                                            st.metric(
                                                "Historischer Tech-Anker",
                                                f"{int(source_map.get('historical_anchor_asset_count') or 0)}/{int(source_map.get('open_asset_count') or 0)}",
                                            )
                                        with sm4:
                                            st.metric(
                                                "Direkt Phase-2-bereit",
                                                f"{int(source_map.get('phase2_ready_asset_count') or 0)}/{int(source_map.get('open_asset_count') or 0)}",
                                            )
                                        st.caption(
                                            f"Historische technische Anker decken {safe_float(source_map.get('historical_anchor_reserves_moz')) or 0.0:.1f} Mio. oz "
                                            f"bzw. {safe_float(source_map.get('historical_anchor_open_coverage_pct')) or 0.0:.1f} % der noch offenen Managed-Reserven ab. "
                                            "Sie erhöhen die bindende NAV-Abdeckung ausdrücklich nicht."
                                        )
                                        st.caption(source_map.get("current_source_basis") or "")

                                        for src in source_map.get("assets", []):
                                            tech_date = src.get("technical_effective_date") or "–"
                                            ownership = safe_float(src.get("ownership_pct"))
                                            ownership_text = f"{ownership:.0f} %" if ownership is not None else "–"
                                            st.write(
                                                f"• **{src.get('asset')}** – {safe_float(src.get('reserve_moz')) or 0.0:.1f} Mio. oz · "
                                                f"Newmont-Anteil {ownership_text} · **{src.get('source_class', '–')}**"
                                            )
                                            st.caption(
                                                f"Technischer Anker: {src.get('latest_technical_source', '–')} · effektiv: {tech_date} · "
                                                f"Komplexität: {src.get('complexity', '–')}"
                                            )
                                            st.caption(f"Nächste Voraussetzung: {src.get('next_requirement', '–')}")
                                            if src.get("note"):
                                                st.caption(src.get("note"))

                                        st.info(source_map.get("reason") or "V2.17.1 ist ausschließlich eine Quellenklassifizierung.")

                                    if not phase1.get("coverage_ok", False):
                                        st.warning(phase1.get("reason") or "Phase-1-Abdeckung unter Freigabegrenze.")

                                phase2 = core_lom.get("asset_nav_phase2") or {}
                                if phase2.get("available"):
                                    st.markdown("**Asset-NAV-Normalisierung Phase 2 – V2.16 Policy innerhalb V2.17.1:**")
                                    st.write(f"**Status:** {phase2.get('status', '–')}")
                                    p2a, p2b, p2c, p2d = st.columns(4)
                                    with p2a:
                                        st.metric("TRS-Assets berechnet", f"{int(phase2.get('calculated_asset_count') or 0)}/{int(phase2.get('asset_count') or 0)}")
                                    with p2b:
                                        st.metric("Native-TRS-NAV", f"{int(phase2.get('native_nav_released_asset_count') or 0)}/{int(phase2.get('asset_count') or 0)}")
                                    with p2c:
                                        st.metric("Portfolio-Aggregations-NAV", f"{int(phase2.get('portfolio_aggregation_asset_count') or 0)}/{int(phase2.get('asset_count') or 0)}")
                                    with p2d:
                                        st.metric("8%-Vergleich", f"{int(phase2.get('common_nav_released_asset_count') or 0)}/{int(phase2.get('asset_count') or 0)}")
                                    partial_sotp = safe_float(phase2.get("partial_portfolio_sotp_nav_musd"))
                                    if partial_sotp is not None:
                                        st.metric("Teil-SOTP der aktuell aggregationsfähigen Phase-2-Assets", f"{partial_sotp/1000.0:.2f} Mrd. USD")
                                        st.caption("Nur diagnostischer Teil-SOTP; kein Managed-Operations-Gesamt-NAV und kein Newmont-Fair-Value.")
                                    st.caption(phase2.get("portfolio_aggregation_policy_status") or "")
                                    st.caption(phase2.get("note") or "")

                                    quality_cov = core_lom.get("quality_aware_coverage") or {}
                                    if quality_cov.get("available"):
                                        qa1, qa2, qa3, qa4 = st.columns(4)
                                        with qa1:
                                            st.metric(
                                                "Phase-1-TRS-Abdeckung",
                                                f"{safe_float(quality_cov.get('phase1_trs_managed_coverage_pct')) or 0.0:.1f} %"
                                            )
                                        with qa2:
                                            st.metric(
                                                "Portfolio-Aggregation / Managed",
                                                f"{safe_float(quality_cov.get('portfolio_aggregation_managed_coverage_pct')) or 0.0:.1f} %"
                                            )
                                        with qa3:
                                            st.metric(
                                                "8%-Vergleich / Managed",
                                                f"{safe_float(quality_cov.get('portfolio_comparable_managed_coverage_pct')) or 0.0:.1f} %"
                                            )
                                        with qa4:
                                            st.metric(
                                                "Aggregationsfähige Reserven",
                                                f"{safe_float(quality_cov.get('portfolio_aggregation_reserves_moz')) or 0.0:.1f} Mio. oz"
                                            )
                                        blocked_quality = quality_cov.get("quality_blocked_assets") or []
                                        if blocked_quality:
                                            blocked_text = " · ".join(
                                                f"{x.get('asset')} ({safe_float(x.get('reserve_moz')) or 0.0:.1f} Mio. oz; {x.get('reason', 'Portfolio-Aggregation gesperrt')})"
                                                for x in blocked_quality
                                            )
                                            st.warning("Nicht in der V2.16-Portfolio-Aggregationsbasis enthalten: " + blocked_text)
                                        comparison_blocked = quality_cov.get("comparison_blocked_assets") or []
                                        if comparison_blocked:
                                            comparison_text = " · ".join(
                                                f"{x.get('asset')} ({safe_float(x.get('reserve_moz')) or 0.0:.1f} Mio. oz)"
                                                for x in comparison_blocked
                                            )
                                            st.info(
                                                "Nur in der separaten 8-%-Vergleichsschicht nicht verfügbar: " + comparison_text
                                                + ". Das sperrt den asset-spezifischen SOTP nicht automatisch."
                                            )

                                    for nav_asset in phase2.get("assets", []):
                                        st.write(
                                            f"• **{nav_asset.get('asset')}** – Exhibit {nav_asset.get('source_exhibit')} · "
                                            f"Newmont-Anteil {safe_float(nav_asset.get('ownership_pct')) or 0.0:.0f} % · "
                                            f"TRS-Diskont {safe_float(nav_asset.get('native_discount_rate_pct')) or 0.0:.1f} %"
                                        )
                                        n1, n2, n3, n4 = st.columns(4)
                                        with n1:
                                            val = safe_float(nav_asset.get("native_trs_npv_musd_100pct"))
                                            st.metric("Native TRS-NPV · 100% Projekt", f"{(val or 0.0)/1000.0:.2f} Mrd. USD" if val is not None else "–")
                                        with n2:
                                            val = safe_float(nav_asset.get("native_trs_npv_musd_owned"))
                                            st.metric("Native TRS-NPV · Newmont-Anteil", f"{(val or 0.0)/1000.0:.2f} Mrd. USD" if val is not None else "–")
                                        with n3:
                                            val = safe_float(nav_asset.get("normalized_nav_native_rate_musd_owned"))
                                            st.metric("Normalisiert · Anteil · TRS-Rate", f"{(val or 0.0)/1000.0:.2f} Mrd. USD" if val is not None else "–")
                                        with n4:
                                            val = safe_float(nav_asset.get("normalized_nav_common_rate_musd_owned"))
                                            st.metric("Vergleichs-NAV · Anteil · 8 %", f"{(val or 0.0)/1000.0:.2f} Mrd. USD" if nav_asset.get("common_nav_released") and val is not None else "–")
                                        delta = safe_float(nav_asset.get("delta_vs_native_owned_pct"))
                                        st.caption("Preisnormalisierung vs. nativem Newmont-Anteil: " + (f"{delta:+.1f} %" if delta is not None else "–"))

                                        q1, q2, q3 = st.columns(3)
                                        with q1:
                                            raw_npv = safe_float(nav_asset.get("raw_rounded_series_npv_musd_100pct"))
                                            st.metric("Rekonstruierter NPV · 100% Projekt", f"{(raw_npv or 0.0)/1000.0:.2f} Mrd. USD" if raw_npv is not None else "–")
                                        with q2:
                                            raw_diff = safe_float(nav_asset.get("raw_vs_official_npv_pct"))
                                            st.metric("Rekonstruiert vs. offiziell · 100%", f"{raw_diff:+.1f} %" if raw_diff is not None else "–")
                                        with q3:
                                            cal_gap = safe_float(nav_asset.get("calibration_adjustment_pct"))
                                            st.metric("Kalibrierungsabweichung · 100%", f"{cal_gap:.1f} % · {nav_asset.get('calibration_quality', '–')}" if cal_gap is not None else "–")
                                        if (safe_float(nav_asset.get("ownership_pct")) or 100.0) < 99.999:
                                            raw_owned = safe_float(nav_asset.get("raw_rounded_series_npv_musd_owned"))
                                            st.caption(
                                                "Rekonstruktionsprüfung auf 100%-Projektbasis; erst danach Newmont-Anteil. "
                                                + (f"Rekonstruierter NPV nach Anteil: {raw_owned/1000.0:.2f} Mrd. USD." if raw_owned is not None else "")
                                            )

                                        sp1, sp2, sp3, sp4 = st.columns(4)
                                        with sp1:
                                            npv_gap = safe_float(nav_asset.get("raw_npv_gap_musd"))
                                            st.metric("NPV-Abstand · 100%", f"{npv_gap:.0f} Mio. USD" if npv_gap is not None else "–")
                                        with sp2:
                                            robust_band = safe_float(nav_asset.get("robustness_band_musd"))
                                            st.metric("Robustheitsband", f"±{robust_band:.0f} Mio. USD" if robust_band is not None else "–")
                                        with sp3:
                                            robust_usage = safe_float(nav_asset.get("robustness_usage_pct"))
                                            st.metric("Robustheits-Auslastung", f"{robust_usage:.1f} %" if robust_usage is not None else "–")
                                        with sp4:
                                            precision_band = safe_float(nav_asset.get("source_precision_band_musd"))
                                            st.metric("Worst-Case-Rundungsband", f"±{precision_band:.0f} Mio. USD" if precision_band is not None else "–")
                                        st.write(
                                            f"**Native-TRS-NAV:** {'Freigegeben' if nav_asset.get('native_nav_released') else 'Gesperrt'} · "
                                            f"**Portfolio-Aggregations-NAV:** {'Freigegeben' if nav_asset.get('portfolio_aggregation_nav_released') else 'Gesperrt'} · "
                                            f"**8%-Vergleichs-NAV:** {'Freigegeben' if nav_asset.get('common_nav_released') else 'Gesperrt'}"
                                        )
                                        h1, h2, h3, h4 = st.columns(4)
                                        with h1:
                                            st.metric("Annualisierte FCF bis", str(nav_asset.get("annual_cashflow_end_year") or "–"))
                                        with h2:
                                            st.metric("Betrieb bis", str(nav_asset.get("operating_end_year") or "–"))
                                        with h3:
                                            st.metric("Closure bis", str(nav_asset.get("closure_end_year") or "–"))
                                        with h4:
                                            st.metric("Closure-Tail annualisiert", "Ja" if nav_asset.get("horizon_complete_through_closure") else "Nein")
                                        st.caption(nav_asset.get("common_rate_horizon_status") or "")
                                        st.caption(nav_asset.get("common_rate_release_note") or "")
                                        if nav_asset.get("closure_tail_note"):
                                            st.caption(nav_asset.get("closure_tail_note"))
                                        st.caption(nav_asset.get("calibration_quality_note") or "")
                                        annual_step = safe_float(nav_asset.get("source_annual_fcf_rounding_step_busd"))
                                        npv_step = safe_float(nav_asset.get("source_native_npv_rounding_step_busd"))
                                        if annual_step is not None or npv_step is not None:
                                            st.caption(
                                                "Quellenpräzision: jährliche FCF-Tabelle "
                                                + (f"{annual_step:.1f} Mrd. USD Schritte" if annual_step is not None else "–")
                                                + " · native NPV-Angabe "
                                                + (f"{npv_step:.1f} Mrd. USD Schritte" if npv_step is not None else "–")
                                                + ". Robustheits- und Worst-Case-Band werden auf 100%-Projektbasis über den jeweiligen TRS-Diskontsatz berechnet."
                                            )

                                        metal_parts = []
                                        for metal in nav_asset.get("commodity_details", []):
                                            base = safe_float(metal.get("trs_price"))
                                            norm = safe_float(metal.get("normalized_price"))
                                            share = safe_float(metal.get("gross_revenue_share_pct"))
                                            unit = metal.get("unit") or ""
                                            if metal.get("normalized") and base is not None and norm is not None:
                                                metal_parts.append(
                                                    f"{metal.get('label')}: TRS {base:.2f} → Modell {norm:.2f} {unit} "
                                                    f"({safe_float(metal.get('price_gap_pct')) or 0.0:+.1f} %; Brutto-Metallumsatz ~{share or 0.0:.1f} %)"
                                                )
                                            else:
                                                metal_parts.append(
                                                    f"{metal.get('label')}: TRS {base:.2f} {unit}; nicht dynamisch normalisiert "
                                                    f"(Brutto-Metallumsatz ~{share or 0.0:.1f} %)"
                                                )
                                        if metal_parts:
                                            st.caption(" · ".join(metal_parts))
                                        cal = safe_float(nav_asset.get("annual_cashflow_calibration_factor"))
                                        st.caption(
                                            "Rekonstruktionsdiagnostik: annualisierte TRS-FCFs werden gegen den veröffentlichten nativen NPV geprüft. "
                                            "Das Cashflow-Horizon-&-Closure-Tail-Gate entscheidet separat, ob zusätzlich eine Re-Diskontierung auf 8% für die Vergleichsschicht zulässig ist"
                                            + (f" (Faktor {cal:.3f}). " if cal is not None else ". ")
                                            + f"Phase-2-Konfidenz: {nav_asset.get('confidence', '–')}."
                                        )
                                        if nav_asset.get("sensitivity_warning"):
                                            st.warning(nav_asset.get("sensitivity_note") or "Hohe NAV-Preissensitivität erkannt.")
                                        st.caption(nav_asset.get("source_note") or "")
                                        st.caption(nav_asset.get("method_note") or "")
                                        if nav_asset.get("blockers"):
                                            st.warning("Phase-2-Sperren: " + " · ".join(str(x) for x in nav_asset.get("blockers", [])))

                                    st.warning(phase2.get("reason") or "Phase 2 erzeugt noch keinen Newmont-Portfolio-NAV.")
                                elif phase2:
                                    st.warning(phase2.get("reason") or "Asset-NAV-Normalisierung Phase 2 nicht verfügbar.")

                                for asset in core_lom.get("managed_operating_assets", core_lom.get("managed_core_assets", [])):
                                    reserve_moz = safe_float(asset.get("reserve_moz")) or 0.0
                                    reserve_share = reserve_moz / max(safe_float(core_lom.get("total_reserves_moz")) or 1.0, 1e-9) * 100.0
                                    line = (
                                        f"• **{asset.get('asset')}** – Reserve {reserve_moz:.1f} Mio. oz ({reserve_share:.1f} %) · "
                                        f"2026 Produktion {safe_float(asset.get('production_2026_koz')) or 0:,.0f} koz"
                                    )
                                    aisc = safe_float(asset.get("aisc_2026_usd_oz"))
                                    if aisc is not None:
                                        line += f" · AISC {aisc:,.0f} USD/oz"
                                    st.write(line)
                                    st.caption(
                                        f"Reserve-/Langlebigkeitsnachweis: {asset.get('reserve_life_evidence', '–')} · "
                                        f"LOM-Status: {asset.get('lom_profile_status', '–')}"
                                    )
                                    if asset.get("note"):
                                        st.caption(asset.get("note"))

                                jv_names = ", ".join(
                                    f"{x.get('asset')} ({safe_float(x.get('reserve_moz')) or 0.0:.1f} Mio. oz)"
                                    for x in core_lom.get("nonmanaged_long_life_assets", [])
                                )
                                if jv_names:
                                    st.write(f"**Nicht gemanagte Long-Life-JVs:** {jv_names}")
                                    st.caption("Diese Reserven zählen zur Reservebasis, benötigen für einen NAV aber separate JV-LOM-Daten.")

                                project_names = ", ".join(
                                    f"{x.get('asset')} ({safe_float(x.get('reserve_moz')) or 0.0:.1f} Mio. oz)"
                                    for x in core_lom.get("development_projects", [])
                                )
                                if project_names:
                                    st.write(f"**Entwicklungs-/Projektreserven:** {project_names}")
                                    st.caption("Projektreserven werden nicht mit einem laufenden Produktions-AISC-Profil bewertet.")

                                phase1 = core_lom.get("technical_lom_phase1") or {}
                                quality_cov = core_lom.get("quality_aware_coverage") or {}
                                quality_pct = safe_float(quality_cov.get("portfolio_aggregation_managed_coverage_pct"))
                                phase1_pct = safe_float(quality_cov.get("phase1_trs_managed_coverage_pct"))
                                quality_threshold = safe_float(quality_cov.get("required_managed_operating_coverage_pct")) or 90.0
                                managed_moz = safe_float(phase1.get("managed_operating_reserves_moz"))
                                quality_total_pct = safe_float(quality_cov.get("portfolio_aggregation_total_coverage_pct"))
                                comparison_pct = safe_float(quality_cov.get("portfolio_comparable_managed_coverage_pct"))
                                st.warning(
                                    "LOM-/NAV-Freigabe weiterhin gesperrt: Phase 1 deckt "
                                    + (f"{phase1_pct:.1f} % der gemanagten operativen Reserven mit aktuellen TRS ab. " if phase1_pct is not None else "einen Teil der gemanagten operativen Reserven mit aktuellen TRS ab. ")
                                    + "Nach der V2.16-Portfolio-Aggregationspolicy sind "
                                    + (f"{quality_pct:.1f} % der {managed_moz:.1f} Mio. oz gemanagten operativen Reserven aggregationsfähig; " if quality_pct is not None and managed_moz is not None else "noch nicht ausreichend viele Reserven aggregationsfähig; ")
                                    + f"erforderlich sind mindestens {quality_threshold:.0f} %. "
                                    + (f"Aggregationsfähige Abdeckung des Gesamtportfolios: {quality_total_pct:.1f} %. " if quality_total_pct is not None else "")
                                    + (f"Separate 8-%-Vergleichsabdeckung / Managed: {comparison_pct:.1f} %." if comparison_pct is not None else "")
                                )

                            if asset_snapshot.get("technical_nav_note"):
                                st.warning(asset_snapshot.get("technical_nav_note"))

                        if asset_nav_control.get("technical_nav_available", False):
                            st.write("**Technischer NAV-Referenzanker (S-K 1300):**")
                            for detail in asset_nav_control.get("nav_details", []):
                                npv_value = detail.get("normalized_sensitivity_npv_musd")
                                npv_text = (
                                    f"{npv_value:,.0f} Mio. USD"
                                    if npv_value is not None
                                    else "–"
                                )
                                age_value = detail.get("age_years")
                                age_text = f"{age_value:.1f} J." if age_value is not None else "–"
                                st.write(
                                    f"• {detail.get('asset', '–')}: {npv_text} "
                                    f"(TRS effektiv {detail.get('effective_date', '–')}, Alter {age_text})"
                                )

                            navsum1, navsum2 = st.columns(2)
                            with navsum1:
                                if asset_nav_control.get("technical_nav_sum_musd") is not None:
                                    st.metric(
                                        "Summe technischer Mine-NPV-Anker",
                                        f"{asset_nav_control['technical_nav_sum_musd'] / 1000.0:.2f} Mrd. USD"
                                    )
                                if asset_nav_control.get("equity_nav_anchor_musd") is not None:
                                    st.metric(
                                        "Equity-NAV-Referenz inkl. Netto-Cash/-Schulden",
                                        f"{asset_nav_control['equity_nav_anchor_musd'] / 1000.0:.2f} Mrd. USD"
                                    )
                            with navsum2:
                                if asset_nav_control.get("nav_anchor_per_share") is not None:
                                    st.metric(
                                        "NAV-Referenz je Aktie",
                                        f"{asset_nav_control['nav_anchor_per_share']:.2f} USD"
                                    )
                                if asset_nav_control.get("earnings_value_per_share") is not None:
                                    st.metric(
                                        "Ertragswert-Referenz je Aktie",
                                        f"{asset_nav_control['earnings_value_per_share']:.2f} USD"
                                    )
                                if asset_nav_control.get("earnings_nav_gap_pct") is not None:
                                    st.write(
                                        "**NAV-/Ertragswert-Abweichung:** "
                                        f"{asset_nav_control['earnings_nav_gap_pct']:.1f} % "
                                        f"({asset_nav_control.get('earnings_nav_convergence_status', '–')})"
                                    )

                            st.caption(
                                "Der technische NAV-Anker interpoliert nur innerhalb der "
                                "veröffentlichten S-K-1300-Metallpreis-Sensitivitäten. "
                                "Es wird nicht außerhalb der offiziellen Sensitivitätsbereiche extrapoliert."
                            )

                        normalized_mine_nav = asset_nav_control.get("normalized_mine_nav") or {}
                        if normalized_mine_nav:
                            st.write(
                                "**Normalisierter Mine-NAV (nach Phase-1-Prüfung; noch keine Portfolio-Aggregation):** "
                                f"{normalized_mine_nav.get('status', '–')}"
                            )
                            nav_method1, nav_method2 = st.columns(2)
                            with nav_method1:
                                if normalized_mine_nav.get("discount_rate_pct") is not None:
                                    st.metric(
                                        "DCF-Diskontsatz",
                                        f"{normalized_mine_nav['discount_rate_pct']:.1f} %"
                                    )
                                if normalized_mine_nav.get("effective_tax_rate_pct") is not None:
                                    st.metric(
                                        "YTD-Steuerquote als Kontroll-Haircut",
                                        f"{normalized_mine_nav['effective_tax_rate_pct']:.1f} %"
                                    )
                            with nav_method2:
                                if normalized_mine_nav.get("commercial_nav_sum_musd") is not None:
                                    st.metric(
                                        "Run-rate Mine-NAV – berechenbare Kernminen",
                                        f"{normalized_mine_nav['commercial_nav_sum_musd'] / 1000.0:.2f} Mrd. USD"
                                    )
                                if normalized_mine_nav.get("commercial_reserve_coverage_pct") is not None:
                                    st.metric(
                                        "Reserveabdeckung des Run-rate NAV",
                                        f"{normalized_mine_nav['commercial_reserve_coverage_pct']:.1f} %"
                                    )

                            bp = normalized_mine_nav.get("normalized_byproduct_prices") or {}
                            bp_text = []
                            for metal, label, unit in [
                                ("gold", "Gold", "USD/oz"),
                                ("lead", "Blei", "USD/lb"),
                                ("zinc", "Zink", "USD/lb"),
                            ]:
                                value = safe_float(bp.get(metal))
                                if value is not None:
                                    bp_text.append(f"{label}: {value:.2f} {unit}")
                            if bp_text:
                                st.caption(
                                    "Normalisierte Nebenmetallpreise aus der aktuellen Reservebasis: "
                                    + " · ".join(bp_text)
                                )

                            for mine in normalized_mine_nav.get("mine_details", []):
                                st.write(f"**{mine.get('asset', 'Mine')}** – {mine.get('status', '–')}")
                                mc1, mc2, mc3 = st.columns(3)
                                with mc1:
                                    if mine.get("production_mid_moz") is not None:
                                        st.metric(
                                            "Produktion (Guidance-Mitte)",
                                            f"{mine['production_mid_moz']:.2f} Mio. oz"
                                        )
                                    if mine.get("mine_life_years") is not None:
                                        st.write(f"Minenleben: {mine['mine_life_years']:.1f} Jahre")
                                with mc2:
                                    if mine.get("normalized_aisc_after_byproduct_per_oz") is not None:
                                        st.metric(
                                            "Normalisiertes AISC-Äquivalent",
                                            f"{mine['normalized_aisc_after_byproduct_per_oz']:.2f} USD/oz"
                                        )
                                    if mine.get("normalized_margin_per_oz") is not None:
                                        st.write(
                                            f"Normalisierte Margin: {mine['normalized_margin_per_oz']:.2f} USD/oz"
                                        )
                                with mc3:
                                    if mine.get("run_rate_nav_musd") is not None:
                                        st.metric(
                                            "Run-rate DCF",
                                            f"{mine['run_rate_nav_musd']:,.0f} Mio. USD"
                                        )
                                    if mine.get("technical_reference_musd") is not None:
                                        st.write(
                                            f"Technischer Referenz-NPV: {mine['technical_reference_musd']:,.0f} Mio. USD"
                                        )
                                if mine.get("excluded_byproduct_credit_musd"):
                                    st.caption(
                                        "Nicht normalisierbare Nebenproduktgutschriften wurden konservativ "
                                        f"mit 0 angesetzt: {mine['excluded_byproduct_credit_musd']:.1f} Mio. USD."
                                    )
                                if mine.get("run_rate_vs_technical_gap_pct") is not None:
                                    st.caption(
                                        "Abweichung Run-rate DCF / technischer Referenz-NPV: "
                                        f"{mine['run_rate_vs_technical_gap_pct']:.1f} %"
                                    )
                                if mine.get("note"):
                                    st.caption(mine.get("note"))

                            st.info(normalized_mine_nav.get("method_note"))
                            normalized_reason = normalized_mine_nav.get("reason")
                            asset_reason = asset_nav_control.get("reason")
                            if normalized_reason and normalized_reason != asset_reason:
                                st.warning(normalized_reason)

                        lom_gate = asset_nav_control.get("lom_release_gate") or {}
                        if lom_gate:
                            st.write(
                                "**Life-of-Mine-Freigabe-Gate V2.7:** "
                                f"{lom_gate.get('status', '–')}"
                            )
                            lg1, lg2 = st.columns(2)
                            with lg1:
                                if lom_gate.get("annual_run_rate_reserve_coverage_pct") is not None:
                                    st.metric(
                                        "Run-rate-Kostenprofil – Reserveabdeckung",
                                        f"{lom_gate['annual_run_rate_reserve_coverage_pct']:.1f} %"
                                    )
                                if lom_gate.get("current_technical_plan_reserve_coverage_pct") is not None:
                                    st.metric(
                                        "Aktuelle technische Pläne – Reserveabdeckung",
                                        f"{lom_gate['current_technical_plan_reserve_coverage_pct']:.1f} %"
                                    )
                            with lg2:
                                if lom_gate.get("release_ready_lom_reserve_coverage_pct") is not None:
                                    st.metric(
                                        "LOM-freigabefähige Reserveabdeckung",
                                        f"{lom_gate['release_ready_lom_reserve_coverage_pct']:.1f} %"
                                    )
                                if lom_gate.get("unmodeled_or_precommercial_reserve_pct") is not None:
                                    st.metric(
                                        "Nicht kommerziell modellierte Reserven",
                                        f"{lom_gate['unmodeled_or_precommercial_reserve_pct']:.1f} %"
                                    )

                            st.caption(
                                "Freigabegrenzen V2.7: mindestens "
                                f"{lom_gate.get('minimum_release_reserve_coverage_pct', 90):.0f} % "
                                "LOM-Abdeckung; höchstens "
                                f"{lom_gate.get('maximum_unmodeled_material_reserve_pct', 10):.0f} % "
                                "nicht modellierte wesentliche Reserven; technische Minenpläne "
                                f"höchstens {lom_gate.get('maximum_technical_plan_age_years', 3):.0f} Jahre alt."
                            )

                            for mine in lom_gate.get("mine_details", []):
                                tech_age = mine.get("technical_plan_age_years")
                                tech_age_text = f"{tech_age:.1f} J." if tech_age is not None else "–"
                                annual_text = "ja" if mine.get("annual_run_rate_profile_available") else "nein"
                                tech_text = "ja" if mine.get("technical_plan_current") else "nein"
                                lom_text = "ja" if mine.get("lom_cost_profile_current") else "nein"
                                st.write(
                                    f"• **{mine.get('asset', 'Mine')}** – Reserveanteil "
                                    f"{mine.get('reserve_share_pct', 0):.1f} % · "
                                    f"aktuelles Run-rate-Profil: {annual_text} · "
                                    f"technischer Plan aktuell: {tech_text} ({tech_age_text}) · "
                                    f"aktuelles LOM-Kosten-/CapEx-Profil: {lom_text} · "
                                    f"Status: {mine.get('status', '–')}"
                                )

                            blocking_reasons = lom_gate.get("blocking_reasons") or []
                            if blocking_reasons:
                                st.warning(
                                    "LOM-Gate blockiert: " + " ".join(blocking_reasons)
                                )
                            st.info(lom_gate.get("method_note"))

                        if not asset_nav_control.get("available", False):
                            asset_reason = asset_nav_control.get("reason")
                            lom_reason = (asset_nav_control.get("lom_release_gate") or {}).get("reason")
                            if asset_reason and asset_reason != lom_reason:
                                st.warning(asset_reason)
                            elif not asset_reason:
                                st.warning(
                                    "Reserve-/Minenlebensdauer- und NAV-Kontrolle ist "
                                    "noch nicht belastbar freigegeben."
                                )

                        if special_control.get("released"):
                            if cycle_eps.get("status") == "Peak-Risiko":
                                st.warning(
                                    "Bergbau-Spezialkontrolle: "
                                    f"**{special_control.get('overall_status', 'Freigegeben')}**. "
                                    "Der Fair Value darf berechnet werden, die "
                                    "Bewertungssicherheit wird wegen des Peak-Cycle-"
                                    "Risikos jedoch auf Niedrig begrenzt."
                                )
                            else:
                                st.success(
                                    "Bergbau-Spezialkontrolle: "
                                    f"**{special_control.get('overall_status', 'Freigegeben')}** – "
                                    "Fair Value freigegeben."
                                )
                        else:
                            st.warning(
                                "Bergbau-Spezialkontrolle: "
                                f"**{special_control.get('overall_status', 'Nicht freigegeben')}**. "
                                "Der Fair Value bleibt gesperrt."
                            )

                        st.caption(special_control.get("note"))
                    else:
                        st.info(special_control.get("note"))

                st.divider()

                st.subheader(
                    "💰 Modul 6 – Fair Value V1"
                )

                fair_value = data[
                    "fair_value"
                ]

                if fair_value["available"]:

                    st.write(
                        "**Bewertungsformel:** "
                        "Normalisiertes EPS × verwendetes Multiple"
                    )

                    st.write(
                        "**Normalisiertes EPS:** "
                        f"{format_eps(
                            fair_value['normalized_eps'],
                            fair_value['financial_currency']
                        )}"
                    )

                    st.write(
                        "**Verwendetes Multiple:** "
                        f"{fair_value['used_multiple']:.2f}×"
                    )

                    st.write(
                        "**Multiple-Quelle:** "
                        f"{fair_value['multiple_source']}"
                    )

                    if fair_value.get(
                        "unit_conversion_applied"
                    ):
                        st.write(
                            "**Fair Value vor Einheitenangleichung:** "
                            f"{fair_value['fair_value_financial']:.2f} "
                            f"{fair_value['financial_currency']}"
                        )

                        st.info(
                            fair_value["unit_note"]
                        )

                    st.metric(
                        "Fair Value V1",
                        (
                            f"{fair_value['fair_value_quote']:.2f} "
                            f"{fair_value['quote_currency']}"
                        )
                    )

                    if fair_value[
                        "current_price"
                    ] is not None:
                        st.write(
                            "**Aktueller Kurs:** "
                            f"{fair_value['current_price']:.2f} "
                            f"{fair_value['quote_currency']}"
                        )

                    if fair_value[
                        "potential_pct"
                    ] is not None:
                        potential = fair_value["potential_pct"]
                        potential_label = (
                            "Upside bis Fair Value"
                            if potential >= 0
                            else "Downside bis Fair Value"
                        )
                        st.metric(
                            potential_label,
                            f"{potential:+.1f} %"
                        )

                    st.success(
                        "Fair Value V1 wurde aus der bereits geprüften "
                        "Gewinnbasis und dem verwendeten Multiple berechnet."
                    )

                else:
                    st.info(
                        "Fair Value V1 noch nicht berechenbar."
                    )

                st.caption(
                    fair_value["note"]
                )

                valuation_confidence = data.get(
                    "valuation_confidence",
                    {}
                )

                if valuation_confidence.get("available"):
                    st.write(
                        "**Bewertungssicherheit:** "
                        f"{valuation_confidence.get('level')}"
                    )

                    if valuation_confidence.get("limiting_factor"):
                        st.write(
                            "**Begrenzender Faktor:** "
                            f"{valuation_confidence['limiting_factor']}"
                        )

                    eps_confidence_note = data.get(
                        "eps_normalization", {}
                    ).get("confidence_note")

                    if eps_confidence_note:
                        st.warning(eps_confidence_note)

                    st.caption(
                        valuation_confidence.get("note")
                    )

                valuation_zone = data.get(
                    "valuation_zone",
                    {}
                )

                st.divider()

                st.subheader(
                    "🎯 Modul 6 – Bewertungszonen V1"
                )

                if valuation_zone.get("available"):
                    st.metric(
                        "Aktuelle Bewertungszone",
                        valuation_zone.get("zone")
                    )

                    if valuation_zone.get("price_vs_fair_value_pct") is not None:
                        price_distance = valuation_zone[
                            "price_vs_fair_value_pct"
                        ]
                        if price_distance < 0:
                            distance_label = (
                                "Aktueller Kursabschlag zum Fair Value"
                            )
                            distance_text = f"{abs(price_distance):.1f} %"
                        elif price_distance > 0:
                            distance_label = (
                                "Aktueller Kursaufschlag zum Fair Value"
                            )
                            distance_text = f"{price_distance:.1f} %"
                        else:
                            distance_label = "Abstand zum Fair Value"
                            distance_text = "0.0 %"

                        st.write(
                            f"**{distance_label}:** {distance_text}"
                        )

                    st.write(
                        "**Stark unterbewertet:** ≤ "
                        f"{valuation_zone['strong_undervaluation_limit']:.2f} "
                        f"{fair_value.get('quote_currency', currency)}"
                    )

                    st.write(
                        "**Unterbewertet:** "
                        f"{valuation_zone['strong_undervaluation_limit']:.2f} – "
                        f"{valuation_zone['fair_lower']:.2f} "
                        f"{fair_value.get('quote_currency', currency)}"
                    )

                    st.write(
                        "**Fair bewertet:** "
                        f"{valuation_zone['fair_lower']:.2f} – "
                        f"{valuation_zone['fair_upper']:.2f} "
                        f"{fair_value.get('quote_currency', currency)}"
                    )

                    st.write(
                        "**Überbewertet:** "
                        f"{valuation_zone['fair_upper']:.2f} – "
                        f"{valuation_zone['strong_overvaluation_limit']:.2f} "
                        f"{fair_value.get('quote_currency', currency)}"
                    )

                    st.write(
                        "**Stark überbewertet:** ≥ "
                        f"{valuation_zone['strong_overvaluation_limit']:.2f} "
                        f"{fair_value.get('quote_currency', currency)}"
                    )

                    st.caption(
                        valuation_zone.get("note")
                    )

                else:
                    st.info(
                        valuation_zone.get(
                            "note",
                            "Bewertungszonen noch nicht verfügbar."
                        )
                    )

                st.divider()

                st.subheader(
                    "🚦 Modul 7 – Signal-Engine V1"
                )

                new_buy_signal = data.get(
                    "new_buy_signal",
                    {}
                )
                holding_signal = data.get(
                    "holding_signal",
                    {}
                )

                if new_buy_signal.get("available"):
                    st.write(
                        "**Fundamentale Basis:** "
                        f"{text_or_dash(new_buy_signal.get('fundamental_strength'))} "
                        f"({text_or_dash(data.get('fundamental_multiple', {}).get('score'))}/100)"
                    )

                    st.metric(
                        "🛒 Neukauf-Signal",
                        new_buy_signal.get("signal")
                    )
                    st.caption(
                        new_buy_signal.get("reason")
                    )

                    st.metric(
                        "📦 Falls bereits im Depot",
                        holding_signal.get("signal")
                    )
                    st.caption(
                        holding_signal.get("reason")
                    )

                    st.info(
                        "Das Bestands-Signal gilt nur, wenn die Aktie tatsächlich "
                        "im Depot vorhanden ist. Depotgewicht, Einstandskurs, "
                        "Klumpenrisiko und persönliches Risikobudget werden hier "
                        "noch nicht berücksichtigt."
                    )

                else:
                    st.info(
                        new_buy_signal.get(
                            "reason",
                            "Noch kein belastbares Handlungssignal."
                        )
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
