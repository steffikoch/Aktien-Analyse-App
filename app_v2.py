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
    forward_eps
):
    adjusted_confidence, confidence_note, deviation = (
        apply_eps_confidence_brake(
            confidence,
            trailing_eps,
            forward_eps
        )
    )

    return {
        "normalized_eps": normalized_eps,
        "method": method,
        "confidence": adjusted_confidence,
        "cycle_basis": cycle_basis,
        "confidence_note": confidence_note,
        "ttm_forward_deviation": deviation
    }


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

            return build_eps_result(
                normalized,
                method,
                "Mittel",
                cycle_basis,
                trailing,
                forward
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
                forward
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
            forward
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
                "Peak-Cycle-Abstand",
                "FCF-Stabilität",
                "Bilanzpuffer",
                "Produktions-/Kostenvisibilität",
                "Rohstoffpreis-/Preiszyklus-Normalisierung",
                "Überleitung Preiszyklus → normalisierte Ertragskraft",
                "Reserve-/Minenlebensdauer- & NAV-Kontrolle",
                "Normalisierter Mine-NAV (Run-rate DCF / LOM-Kontrolle)"
            ],
            "status": "Router aktiv – V2.6.1 normalisierter Mine-NAV",
            "note": (
                "V2.6.1 ergänzt Reserve- und NAV-Kontrolle um einen unabhängig "
                "berechneten normalisierten Mine-NAV-Kontrollwert. Verwendet "
                "werden verifizierte 2026 Produktions-/AISC-Reconciliation, "
                "2025 Reservepreise und Reserve-Minenleben. Ein einzelnes "
                "Guidance-Jahr wird jedoch nicht als Life-of-Mine-Kostenprofil "
                "ausgegeben; bei unvollständiger LOM-Abdeckung bleibt der Fair "
                "Value gesperrt."
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


def get_verified_mining_snapshot(symbol):
    """
    Curated, explicitly dated official-data snapshots for Mining V2.

    Operating mine KPIs are never inferred from Yahoo summary data. A snapshot
    is added only after production/cost guidance was verified from an official
    company publication or filing. The refresh deadline is an internal safety
    deadline so stale operating guidance cannot silently release a Fair Value.
    """

    symbol_text = str(symbol or "").upper()

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
        # Q2-2026 guidance reconciliation used by Mining V2.6.1. Values are
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


def _mining_production_guidance_status(snapshot):
    current_low = safe_float(snapshot.get("production_guidance_current_low_moz"))
    current_high = safe_float(snapshot.get("production_guidance_current_high_moz"))
    previous_low = safe_float(snapshot.get("production_guidance_previous_low_moz"))
    previous_high = safe_float(snapshot.get("production_guidance_previous_high_moz"))

    if None in [current_low, current_high, previous_low, previous_high]:
        return "Daten unzureichend", None

    previous_mid = (previous_low + previous_high) / 2.0
    current_mid = (current_low + current_high) / 2.0
    if previous_mid <= 0:
        return "Daten unzureichend", None

    change_pct = (current_mid / previous_mid - 1.0) * 100.0

    if change_pct >= 2.0:
        status = "Stark"
    elif change_pct >= 0.0:
        status = "Positiv"
    elif change_pct >= -5.0:
        status = "Stabil"
    else:
        status = "Schwach"

    return status, change_pct


def _mining_aisc_guidance_status(snapshot):
    current_low = safe_float(snapshot.get("silver_aisc_guidance_current_low"))
    current_high = safe_float(snapshot.get("silver_aisc_guidance_current_high"))
    previous_low = safe_float(snapshot.get("silver_aisc_guidance_previous_low"))
    previous_high = safe_float(snapshot.get("silver_aisc_guidance_previous_high"))

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
    elif improvement_pct >= 0.0:
        status = "Verbessert"
    elif improvement_pct >= -10.0:
        status = "Stabil"
    else:
        status = "Schwach"

    return status, improvement_pct


def _mining_actual_aisc_status(snapshot):
    actual = safe_float(snapshot.get("q2_silver_aisc"))
    guidance_high = safe_float(snapshot.get("silver_aisc_guidance_current_high"))

    if actual is None or guidance_high is None or guidance_high <= 0:
        return "Daten unzureichend"
    if actual <= guidance_high:
        return "Stark"
    if actual <= guidance_high * 1.10:
        return "Ausreichend"
    return "Schwach"



def get_verified_mining_commodity_route(symbol):
    """
    Explicit primary-commodity mapping for miners.

    A commodity is never inferred from a generic industry label because many
    miners have mixed metal exposure. A route is added only after the primary
    commodity has been verified for the company.
    """
    symbol_text = str(symbol or "").upper()

    routes = {
        "HL": {
            "commodity_name": "Silber",
            "commodity_symbol": "SI=F",
            "unit": "USD/oz",
            "normalization_years": 5,
            "current_window_days": 60,
            "mapping_note": (
                "Hecla wird für die Preiszyklus-Kontrolle primär dem Silberpreis "
                "zugeordnet. Gold, Blei und Zink bleiben zusätzliche Exposures und "
                "werden nicht als separate Primärrohstoffe in diese V2.6.1-Kontrolle "
                "hineingeschätzt."
            ),
        },
    }
    return routes.get(symbol_text)


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


def build_mining_commodity_cycle(symbol, snapshot, cache_version):
    """
    Combine dynamic commodity-price normalization with verified mine cost data.

    The normalized commodity margin is an input into the V2.4 earnings-power
    bridge. It is never used as a direct one-for-one price-to-EPS factor. The
    bridge requires convergence with the already-normalized EPS and an FCF
    plausibility check.
    """
    route = get_verified_mining_commodity_route(symbol)
    if route is None:
        return {
            "available": False,
            "status": "Keine verifizierte Primärrohstoff-Zuordnung",
            "required": True,
            "reason": (
                "Für diese Bergbau-Aktie ist noch kein verifizierter Primärrohstoff "
                "für die Preiszyklus-Normalisierung hinterlegt."
            ),
        }

    price_cycle = load_mining_commodity_price_cycle(
        route["commodity_symbol"],
        cache_version,
        normalization_years=route.get("normalization_years", 5),
        current_window_days=route.get("current_window_days", 60),
    )

    result = {
        **price_cycle,
        "commodity_name": route["commodity_name"],
        "commodity_symbol": route["commodity_symbol"],
        "unit": route["unit"],
        "mapping_note": route.get("mapping_note"),
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

    current_low = safe_float((snapshot or {}).get("silver_aisc_guidance_current_low"))
    current_high = safe_float((snapshot or {}).get("silver_aisc_guidance_current_high"))
    if current_low is None or current_high is None or current_low <= 0 or current_high <= 0:
        result["available"] = False
        result["status"] = "Preiszyklus vorhanden, AISC-Basis fehlt"
        result["reason"] = (
            "Der Rohstoffpreis ist normalisierbar, aber die verifizierte aktuelle "
            "AISC-/Stückkostenbasis fehlt."
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
        "status": overall,
        "aisc_midpoint": aisc_midpoint,
        "normalized_margin_per_oz": normalized_margin,
        "current_margin_per_oz": current_margin,
        "normalized_margin_pct": normalized_margin_pct,
        "margin_resilience_status": margin_status,
        "reason": None,
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
        result["reason"] = "Rohstoffpreis-/Margenzyklus ist nicht belastbar verfügbar."
        return result

    normalized_margin = safe_float(commodity_cycle.get("normalized_margin_per_oz"))
    current_margin = safe_float(commodity_cycle.get("current_margin_per_oz"))
    ttm_eps = safe_float(trailing_eps)
    cycle_eps = safe_float((eps_normalization or {}).get("normalized_eps"))

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
    if available and convergence_status == "Stark konvergent" and fcf_support_status == "Stützend":
        status = "Ertragskraft plausibilisiert – starke Konvergenz"
        translation_confidence = "Mittel"
    elif available:
        status = "Ertragskraft plausibilisiert – mit Vorsicht"
        translation_confidence = "Niedrig"
    elif not convergence_ok:
        status = "Ertragskraft nicht freigegeben – EPS-Wege divergieren"
        translation_confidence = "Niedrig"
    else:
        status = "Ertragskraft nicht freigegeben – FCF stützt nicht ausreichend"
        translation_confidence = "Niedrig"

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
        "reason": None if available else status,
    })
    return result




def get_verified_mining_asset_snapshot(symbol):
    """
    Curated reserve / mine-life / technical-NAV reference data for Mining V2.5.

    The reserve snapshot is current year-end company data. Technical NPV values
    are deliberately kept separate because the currently incorporated S-K 1300
    mine plans for Greens Creek and Lucky Friday have 2021 effective dates and
    Keno Hill has a 2023 effective date. They are useful as independent asset
    anchors, but are not silently treated as current NAV.
    """
    symbol_text = str(symbol or "").upper()
    if symbol_text != "HL":
        return None

    return {
        "company": "Hecla Mining Company",
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
        # set used here. V2.6.1 therefore gives copper by-product credits no value
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
    Mining V2.6.1 independent normalized mine-NAV control.

    This is deliberately a run-rate reserve DCF, not a substitute for a current
    Life-of-Mine technical model. It uses current verified production guidance,
    the company's AISC-before-by-product reconciliation, current reserve mine
    lives and reserve metal-price assumptions. By-product credits are scaled to
    the reserve-price basis. Missing price bases receive zero credit.

    Final NAV release requires full core-mine coverage and a long-term cost
    profile. Keno Hill remains pre-commercial in the Q2-2026 guidance and has no
    comparable AISC reconciliation, so V2.6.1 is a diagnostic/control value only.
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

    if str(symbol or "").upper() != "HL" or not operating_snapshot or not asset_snapshot:
        result["reason"] = "Kein verifizierter V2.6.1-Mine-NAV-Datensatz verfügbar."
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
                "V2.6.1 erfindet deshalb keine Life-of-Mine-Kosten."
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

    # V2.6.1 deliberately does not claim a full current NAV. A current annual AISC
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


def build_mining_asset_nav_control(
    symbol,
    commodity_cycle,
    earnings_translation,
    balance_score,
    fundamental_multiple,
    operating_snapshot,
):
    """
    Mining V2.6.1 reserve / mine-life / technical-NAV + run-rate NAV control.

    Important: technical-report NPVs are not presented as current company NAV.
    They are independent asset anchors only. V2.6.1 also builds an independent
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
        "total_core_silver_reserves_moz": None,
        "production_guidance_mid_moz": None,
        "reserve_coverage_years": None,
        "company_average_reserve_mine_life_years": None,
        "mine_life_status": "Daten unzureichend",
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
    reserve_price = safe_float(snapshot.get("reserve_price_basis_silver"))
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

    reserves_moz = safe_float(snapshot.get("total_core_silver_reserves_moz"))
    result["total_core_silver_reserves_moz"] = reserves_moz

    current_low = safe_float((operating_snapshot or {}).get("production_guidance_current_low_moz"))
    current_high = safe_float((operating_snapshot or {}).get("production_guidance_current_high_moz"))
    production_mid = None
    reserve_coverage = None
    if current_low is not None and current_high is not None and current_low > 0 and current_high > 0:
        production_mid = (current_low + current_high) / 2.0
        if reserves_moz is not None and reserves_moz > 0:
            reserve_coverage = reserves_moz / production_mid
    result["production_guidance_mid_moz"] = production_mid
    result["reserve_coverage_years"] = reserve_coverage

    company_mine_life = safe_float(snapshot.get("company_average_reserve_mine_life_years"))
    result["company_average_reserve_mine_life_years"] = company_mine_life

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
    life_ok = mine_life_status in ["Sehr stark", "Stark", "Ausreichend"]
    nav_current_ok = result["technical_nav_available"] and nav_reference_fresh
    convergence_ok = convergence in ["Stark konvergent", "Ausreichend konvergent"]

    if not reserve_ok:
        status = "Reservebasis nicht belastbar freigegeben"
        reason = (
            "Reserve-Daten sind veraltet oder die verwendete Reserve-Preisannahme "
            "liegt zu weit vom normalisierten Rohstoffpreis entfernt."
        )
    elif not life_ok:
        status = "Minenlebensdauer zu kurz oder unklar"
        reason = "Die Reserve-Lebensdauer reicht nicht für eine robuste Asset-Bewertung."
    elif not (result.get("normalized_mine_nav") or {}).get("available", False):
        status = (result.get("normalized_mine_nav") or {}).get(
            "status", "Normalisierter Mine-NAV nicht freigegeben"
        )
        reason = (result.get("normalized_mine_nav") or {}).get("reason") or (
            "Der selbst berechnete normalisierte Mine-NAV ist noch nicht als "
            "vollständiges Life-of-Mine-Modell freigegeben."
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

    normalized_nav_ok = (result.get("normalized_mine_nav") or {}).get("available", False)
    available = (
        reserve_ok and life_ok and normalized_nav_ok and nav_current_ok and convergence_ok
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
):
    """
    Conservative Mining V2.6.1.

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
    ttm_eps = safe_float(trailing_eps)
    fwd_eps = safe_float(forward_eps)

    ttm_to_cycle = None
    if cycle_basis is not None and cycle_basis > 0 and ttm_eps is not None:
        ttm_to_cycle = ttm_eps / cycle_basis

    if len(eps_history) < 3 or cycle_basis is None or cycle_basis <= 0:
        eps_status = "Daten unzureichend"
    elif ttm_to_cycle is None:
        eps_status = "Zyklus-Basis vorhanden"
    elif ttm_to_cycle <= 1.5:
        eps_status = "Unauffällig"
    elif ttm_to_cycle <= 3.0:
        eps_status = "Erhöht"
    else:
        eps_status = "Peak-Risiko"

    positive_fcf_years = sum(1 for value in fcf_history if value > 0)
    negative_fcf_years = sum(1 for value in fcf_history if value < 0)

    if len(fcf_history) < 3:
        fcf_status = "Daten unzureichend"
    elif negative_fcf_years == 0 and positive_fcf_years >= 3:
        fcf_status = "Stark"
    elif positive_fcf_years >= 2 and negative_fcf_years <= 1:
        fcf_status = "Ausreichend"
    elif positive_fcf_years >= 1 and negative_fcf_years >= 1:
        fcf_status = "Zyklisch"
    else:
        fcf_status = "Schwach"

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
        eps_status != "Daten unzureichend"
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

    # Mining V2.3 price-cycle normalization. Price history is loaded dynamically
    # only for an explicitly verified primary commodity mapping. The resulting
    # normalized commodity margin is a control input, not yet a direct EPS/FCF
    # conversion factor.
    commodity_price_cycle = build_mining_commodity_cycle(
        symbol,
        snapshot,
        CACHE_VERSION,
    )
    commodity_price_cycle_available = commodity_price_cycle.get("available", False)
    commodity_price_cycle_status = commodity_price_cycle.get(
        "status", "Daten unzureichend"
    )

    # Mining V2.6.1: independent earnings-power bridge. The bridge can become
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

    # Mining V2.6.1: reserve / mine-life / normalized run-rate NAV / technical anchor.
    # Current reserve data may be fresh while the incorporated S-K 1300 mine
    # plans are older. In that case V2.6.1 shows the technical NAV as a reference
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

    if not financial_checks_usable:
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
            },
            "fcf_stability": {
                "history_count": len(fcf_history),
                "positive_years": positive_fcf_years,
                "negative_years": negative_fcf_years,
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
            "mining_asset_nav_control": asset_nav_control,
        },
        "note": (
            "Die Bergbau-Spezialkontrolle V2.6.1 trennt Finanzzyklus, operative "
            "Minenvisibilität, Rohstoffpreis-Normalisierung, nachhaltige "
            "Ertragskraft, Reserve-/Asset-Kontrolle und einen unabhängig "
            "berechneten Run-rate-Mine-NAV. Ein Guidance-Jahr ersetzt kein "
            "Life-of-Mine-Kostenprofil; Keno Hill wird ohne kommerzielles AISC "
            "nicht geschätzt. Veraltete technische Mine-Pläne bleiben nur "
            "Referenz. Der 100-Punkte-Multiple-Score bleibt unverändert."
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

    # Mining V2.3 hard safety gate. This is intentionally independent of the
    # special-control release flag so that stale cache/state can never release
    # a mining Fair Value before commodity-price / margin-cycle normalization.
    if (
        isinstance(special_control, dict)
        and special_control.get("control_key") == "mining_cycle_quality"
    ):
        commodity_cycle = (special_control.get("checks") or {}).get(
            "commodity_price_cycle", {}
        )
        earnings_translation = (special_control.get("checks") or {}).get(
            "commodity_earnings_translation", {}
        )
        if not commodity_cycle.get("available", False):
            result["note"] = (
                "Fair Value V1 gesperrt: Bei Bergbauunternehmen ist die belastbare "
                "Rohstoffpreis-/Margenzyklus-Normalisierung nicht vollständig "
                "verfügbar. Die Bergbau-Hard-Gate-Sperre ist aktiv."
            )
            return result
        if not earnings_translation.get("available", False):
            result["note"] = (
                "Fair Value V1 gesperrt: Der Rohstoffpreis-/Margenzyklus ist "
                "normalisiert, aber die Überleitung in nachhaltige Ertragskraft "
                "ist noch nicht ausreichend konvergent bzw. durch FCF gestützt."
            )
            return result
        asset_nav_control = (special_control.get("checks") or {}).get(
            "mining_asset_nav_control", {}
        )
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

CACHE_VERSION = "m6_mining_mine_nav_v261_20260906"

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

    eps_normalization = normalize_eps(
        company_type,
        trailing_eps,
        forward_eps,
        historical["eps"],
        revenue_growth,
        earnings_growth
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
                    st.caption("Bergbau-Schutzmodell V2.6.1 – normalisierter Mine-NAV + Reserve/NAV-Kontrolle")

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
                                "**Verfügbare EPS-Historie:** "
                                f"{cycle_eps.get('history_count', 0)} Jahre"
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
                                current_low = mining_snapshot.get(
                                    "production_guidance_current_low_moz"
                                )
                                current_high = mining_snapshot.get(
                                    "production_guidance_current_high_moz"
                                )
                                previous_low = mining_snapshot.get(
                                    "production_guidance_previous_low_moz"
                                )
                                previous_high = mining_snapshot.get(
                                    "production_guidance_previous_high_moz"
                                )

                                if current_low is not None and current_high is not None:
                                    st.metric(
                                        "2026 Silber-Produktions-Guidance",
                                        f"{current_low:.1f} – {current_high:.1f} Mio. oz"
                                    )
                                if previous_low is not None and previous_high is not None:
                                    st.write(
                                        "**Vorherige Guidance:** "
                                        f"{previous_low:.1f} – {previous_high:.1f} Mio. oz"
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
                                aisc_low = mining_snapshot.get(
                                    "silver_aisc_guidance_current_low"
                                )
                                aisc_high = mining_snapshot.get(
                                    "silver_aisc_guidance_current_high"
                                )
                                aisc_prev_low = mining_snapshot.get(
                                    "silver_aisc_guidance_previous_low"
                                )
                                aisc_prev_high = mining_snapshot.get(
                                    "silver_aisc_guidance_previous_high"
                                )
                                q2_aisc = mining_snapshot.get("q2_silver_aisc")

                                if aisc_low is not None and aisc_high is not None:
                                    st.metric(
                                        "2026 Silver-AISC-Guidance",
                                        f"{aisc_low:.2f} – {aisc_high:.2f} USD/oz"
                                    )
                                if aisc_prev_low is not None and aisc_prev_high is not None:
                                    st.write(
                                        "**Vorherige AISC-Guidance:** "
                                        f"{aisc_prev_low:.2f} – {aisc_prev_high:.2f} USD/oz"
                                    )
                                if q2_aisc is not None:
                                    st.write(
                                        "**Q2 Silver AISC:** "
                                        f"{q2_aisc:.2f} USD/oz"
                                    )
                                if operating.get("aisc_improvement_pct") is not None:
                                    st.write(
                                        "**AISC-Guidance Verbesserung:** "
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

                        if commodity_cycle.get("available", False):
                            commodity_name = commodity_cycle.get("commodity_name", "Rohstoff")
                            commodity_symbol = commodity_cycle.get("commodity_symbol", "–")
                            unit = commodity_cycle.get("unit", "")
                            st.write(
                                f"**Primärrohstoff:** {commodity_name} ({commodity_symbol})"
                            )
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
                                aisc_mid = commodity_cycle.get("aisc_midpoint")
                                norm_margin = commodity_cycle.get("normalized_margin_per_oz")
                                current_margin = commodity_cycle.get("current_margin_per_oz")
                                if aisc_mid is not None:
                                    st.metric(
                                        "AISC-Mittelpunkt",
                                        f"{aisc_mid:.2f} USD/oz"
                                    )
                                if norm_margin is not None:
                                    st.metric(
                                        "Normalisierte Margin-Reserve",
                                        f"{norm_margin:.2f} USD/oz"
                                    )
                                if current_margin is not None:
                                    st.write(
                                        "**Aktuelle Margin-Reserve:** "
                                        f"{current_margin:.2f} USD/oz"
                                    )
                                st.write(
                                    "**Normalisierte Margentragfähigkeit:** "
                                    f"{commodity_cycle.get('margin_resilience_status', '–')}"
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
                                "Die nachhaltige EPS-Basis wird nicht aus dem Silberpreis "
                                "allein abgeleitet. Sie wird nur akzeptiert, wenn die "
                                "margenadjustierte TTM-Ertragskraft mit der unabhängigen "
                                "Mehrjahres-EPS-Normalisierung konvergiert und der "
                                "normalisierte FCF je Aktie die Richtung stützt."
                            )
                        else:
                            st.warning(
                                "Die Ertragskraft-Überleitung ist noch nicht ausreichend "
                                "plausibilisiert. Es wird kein nachhaltiges EPS für eine "
                                "Bergbau-Bewertung freigegeben."
                            )
                            if earnings_translation.get("reason"):
                                st.caption(earnings_translation.get("reason"))

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

                            navc1, navc2 = st.columns(2)
                            with navc1:
                                if asset_nav_control.get("total_core_silver_reserves_moz") is not None:
                                    st.metric(
                                        "Kern-Silberreserven",
                                        f"{asset_nav_control['total_core_silver_reserves_moz']:.1f} Mio. oz"
                                    )
                                if asset_nav_control.get("company_average_reserve_mine_life_years") is not None:
                                    st.metric(
                                        "Hecla Ø Reserve-Minenleben",
                                        f"{asset_nav_control['company_average_reserve_mine_life_years']:.1f} Jahre"
                                    )
                                if asset_nav_control.get("reserve_coverage_years") is not None:
                                    st.write(
                                        "**Reserve/Guidance-Abdeckung:** "
                                        f"{asset_nav_control['reserve_coverage_years']:.1f} Jahre "
                                        "(Kontrollrechnung, nicht identisch mit Nameplate-Minenleben)"
                                    )
                                st.write(
                                    "**Minenlebensdauer-Status:** "
                                    f"{asset_nav_control.get('mine_life_status', '–')}"
                                )

                            with navc2:
                                reserve_price_basis = safe_float(
                                    asset_snapshot.get("reserve_price_basis_silver")
                                )
                                if reserve_price_basis is not None:
                                    st.metric(
                                        "Silberpreis-Basis der Reserven",
                                        f"{reserve_price_basis:.2f} USD/oz"
                                    )
                                if asset_nav_control.get("reserve_price_alignment_pct") is not None:
                                    st.write(
                                        "**Abstand zum normalisierten Silberpreis:** "
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

                            reserve_map = asset_snapshot.get("silver_reserves_moz") or {}
                            if reserve_map:
                                reserve_text = " · ".join(
                                    f"{name}: {value:.1f} Mio. oz"
                                    for name, value in reserve_map.items()
                                )
                                st.caption("Silberreserven: " + reserve_text)
                            if asset_snapshot.get("reserve_source_note"):
                                st.info(asset_snapshot.get("reserve_source_note"))

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
                                "**Normalisierter Mine-NAV V2.6.1 (Run-rate DCF):** "
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
                            if normalized_mine_nav.get("reason"):
                                st.warning(normalized_mine_nav.get("reason"))

                        if not asset_nav_control.get("available", False):
                            st.warning(
                                asset_nav_control.get("reason")
                                or (
                                    "Reserve-/Minenlebensdauer- und NAV-Kontrolle ist "
                                    "noch nicht belastbar freigegeben."
                                )
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
