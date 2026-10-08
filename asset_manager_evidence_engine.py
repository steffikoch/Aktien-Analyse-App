from __future__ import annotations

import io
import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


ENGINE_VERSION = "AM-EVIDENCE-ENGINE-1.2.0"
CONTROL_VERSION = ENGINE_VERSION
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DOC_CLASS_PRIORITY = {
    "press_release": 0,
    "financial_data_supplement": 1,
    "annual_report": 2,
    "presentation": 3,
    "half_year_report": 4,
    "other": 9,
}


@dataclass
class Check:
    stage: str
    status: str  # PASS / WARN / FAIL / INFO
    message: str
    details: dict[str, Any] | None = None


@dataclass
class FetchResult:
    url: str
    final_url: str
    ok: bool
    status_code: int | None
    content_type: str
    size_bytes: int
    elapsed_s: float
    kind: str
    text: str
    error: str | None = None
    raw: bytes | None = None

    def public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        d["text_length"] = len(self.text or "")
        d.pop("text", None)
        return d




def html_source_from_fetch(fetch: FetchResult) -> str:
    """Return raw HTML markup for structural archive parsing.

    FetchResult.text intentionally contains cleaned visible text for KPI/EPS parsing.
    Structural discovery (tables, anchors, row/column coordinates) must use the
    original HTML bytes, otherwise BeautifulSoup sees no tags at all.
    """
    if fetch is None:
        return ""
    raw = getattr(fetch, "raw", None)
    if raw:
        # UTF-8 covers the issuer pages we target; replacement keeps malformed
        # bytes from breaking structural parsing while preserving tags/links.
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")
    return getattr(fetch, "text", "") or ""

def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def company_host(url_or_host: str) -> str:
    raw = (url_or_host or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def host_belongs(url: str, company_domain: str) -> bool:
    h = company_host(url)
    d = company_host(company_domain)
    if not h or not d:
        return False
    return h == d or h.endswith("." + d) or d.endswith("." + h)


def classify_document(label: str) -> str:
    s = normalize_ws(label).lower()
    if any(x in s for x in ["press release", "financial release", "results release", "communiqu"]):
        return "press_release"
    if "financial supplement" in s or "financial data" in s or "supplement" in s:
        return "financial_data_supplement"
    if any(x in s for x in ["universal registration", "annual report", "registration document"]):
        return "annual_report"
    if "presentation" in s or "slides" in s:
        return "presentation"
    if "half year" in s or "half-year" in s or "interim report" in s:
        return "half_year_report"
    return "other"


def infer_period(label: str, href: str = "") -> str | None:
    s = normalize_ws(f"{label} {href}").upper()
    for p in ("Q4", "Q3", "Q2", "Q1", "H2", "H1", "FY"):
        if re.search(rf"(?<![A-Z0-9]){p}(?![A-Z0-9])", s):
            return p
    if "FULL YEAR" in s or "FULL-YEAR" in s or "ANNUAL RESULTS" in s:
        return "FY"
    return None


def _safe_year(value: str) -> int | None:
    m = re.search(r"\b(20\d{2})\b", value or "")
    if not m:
        return None
    y = int(m.group(1))
    return y if 2000 <= y <= 2100 else None


def expand_html_table(table) -> list[list[Any]]:
    """Expand row/colspans into a rectangular grid of BeautifulSoup cells."""
    rows = table.find_all("tr")
    grid: list[list[Any]] = []
    pending: dict[tuple[int, int], Any] = {}

    for r_idx, tr in enumerate(rows):
        row: list[Any] = []
        c_idx = 0
        cells = tr.find_all(["th", "td"], recursive=False)
        ci = 0
        while ci < len(cells) or any(rr == r_idx for rr, _ in pending):
            while (r_idx, c_idx) in pending:
                row.append(pending[(r_idx, c_idx)])
                c_idx += 1
            if ci >= len(cells):
                break
            cell = cells[ci]
            ci += 1
            rowspan = int(cell.get("rowspan") or 1)
            colspan = int(cell.get("colspan") or 1)
            for dx in range(colspan):
                if dx == 0:
                    row.append(cell)
                else:
                    row.append(cell)
                for dy in range(1, rowspan):
                    pending[(r_idx + dy, c_idx + dx)] = cell
            c_idx += colspan
        grid.append(row)
    return grid


def parse_archive_grid(
    html: str,
    base_url: str,
    company_domain: str,
    target_years: Iterable[int],
    accepted_periods: Iterable[str] = ("Q4", "FY"),
) -> list[dict[str, Any]]:
    """Parse issuer result archives by physical table coordinates.

    Generic rule: a header row provides explicit fiscal-year columns; the first
    cell of each data row defines the document class; anchors inside the year
    cell define periods (Q1-Q4/FY). This avoids nearest-anchor/year heuristics.
    """
    targets = {int(y) for y in target_years}
    accepted = {str(p).upper() for p in accepted_periods}
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str, str]] = set()

    for table_index, table in enumerate(soup.find_all("table")):
        grid = expand_html_table(table)
        if not grid:
            continue

        header_idx = None
        year_columns: dict[int, int] = {}
        for ri, row in enumerate(grid[:8]):
            mapping: dict[int, int] = {}
            for ci, cell in enumerate(row):
                y = _safe_year(normalize_ws(cell.get_text(" ", strip=True)) if cell else "")
                if y is not None:
                    mapping[ci] = y
            if len(set(mapping.values())) >= 2:
                header_idx = ri
                year_columns = mapping
                break
        if header_idx is None:
            continue

        for ri in range(header_idx + 1, len(grid)):
            row = grid[ri]
            if not row:
                continue
            # document-class label: first meaningful cell before/at first year column
            first_year_col = min(year_columns) if year_columns else 1
            labels = []
            for ci in range(min(first_year_col + 1, len(row))):
                cell = row[ci]
                if cell:
                    txt = normalize_ws(cell.get_text(" ", strip=True))
                    if txt:
                        labels.append(txt)
            row_label = labels[0] if labels else ""
            doc_class = classify_document(row_label)
            if doc_class == "other" and not row_label:
                continue

            for ci, year in year_columns.items():
                if year not in targets or ci >= len(row):
                    continue
                cell = row[ci]
                if cell is None:
                    continue
                anchors = cell.find_all("a", href=True)
                for anchor_index, a in enumerate(anchors):
                    href = urljoin(base_url, a.get("href"))
                    if not host_belongs(href, company_domain):
                        continue
                    label = normalize_ws(a.get_text(" ", strip=True))
                    period = infer_period(label, href)
                    # In archive rows with 4 unlabeled links, position is Q1-Q4.
                    if period is None and len(anchors) == 4:
                        period = ("Q1", "Q2", "Q3", "Q4")[anchor_index]
                    if period not in accepted:
                        continue
                    key = (year, doc_class, period, href)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "year": year,
                        "period": period,
                        "document_class": doc_class,
                        "row_label": row_label,
                        "label": label,
                        "url": href,
                        "table_index": table_index,
                        "row_index": ri,
                        "column_index": ci,
                        "anchor_index": anchor_index,
                        "source": "html_table_grid",
                    })
    out.sort(key=lambda x: (-x["year"], DOC_CLASS_PRIORITY.get(x["document_class"], 9), x["url"]))
    return out


def fallback_link_candidates(
    html: str,
    base_url: str,
    company_domain: str,
    target_years: Iterable[int],
    accepted_periods: Iterable[str] = ("Q4", "FY"),
) -> list[dict[str, Any]]:
    targets = {int(y) for y in target_years}
    accepted = {str(p).upper() for p in accepted_periods}
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict[str, Any]] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href"))
        if not host_belongs(href, company_domain):
            continue
        label = normalize_ws(a.get_text(" ", strip=True))
        context = normalize_ws((a.parent.get_text(" ", strip=True) if a.parent else "") + " " + label)
        year = _safe_year(context + " " + href)
        period = infer_period(label + " " + context, href)
        if year in targets and period in accepted:
            out.append({
                "year": year,
                "period": period,
                "document_class": classify_document(context),
                "row_label": context[:160],
                "label": label,
                "url": href,
                "source": "fallback_anchor_context",
            })
    out.sort(key=lambda x: (-x["year"], DOC_CLASS_PRIORITY.get(x["document_class"], 9), x["url"]))
    return out


def period_candidates(
    html: str,
    base_url: str,
    company_domain: str,
    target_year: int,
    periods: Iterable[str],
) -> list[dict[str, Any]]:
    rows = parse_archive_grid(html, base_url, company_domain, [target_year], periods)
    if not rows:
        rows = fallback_link_candidates(html, base_url, company_domain, [target_year], periods)
    return rows


def best_candidate_per_year(candidates: list[dict[str, Any]], target_years: Iterable[int]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for y in sorted({int(x) for x in target_years}, reverse=True):
        rows = [c for c in candidates if c.get("year") == y]
        if not rows:
            continue
        rows.sort(key=lambda x: (DOC_CLASS_PRIORITY.get(x.get("document_class", "other"), 9), 0 if x.get("period") == "Q4" else 1))
        result[y] = rows[0]
    return result


def extract_pdf_text(raw: bytes) -> tuple[str, str | None]:
    errors = []
    if fitz is not None:
        try:
            doc = fitz.open(stream=raw, filetype="pdf")
            pages = [page.get_text("text") for page in doc]
            text = "\n".join(pages)
            if text.strip():
                return text, None
        except Exception as e:  # pragma: no cover
            errors.append(f"PyMuPDF: {e}")
    if PdfReader is not None:
        try:
            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
            if text.strip():
                return text, None
        except Exception as e:  # pragma: no cover
            errors.append(f"pypdf: {e}")
    return "", "; ".join(errors) or "No PDF extractor available"


def extract_html_text(raw: bytes, encoding: str | None = None) -> str:
    text = raw.decode(encoding or "utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return "\n".join(s.strip() for s in soup.stripped_strings if s.strip())


def fetch_primary(url: str, timeout: float = 18.0, session: requests.Session | None = None) -> FetchResult:
    sess = session or requests.Session()
    start = time.monotonic()
    try:
        r = sess.get(url, timeout=timeout, allow_redirects=True, headers={"User-Agent": DEFAULT_UA, "Accept": "*/*"})
        elapsed = time.monotonic() - start
        raw = r.content or b""
        ctype = (r.headers.get("content-type") or "").lower()
        is_pdf = raw[:5] == b"%PDF-" or "application/pdf" in ctype
        if is_pdf:
            text, err = extract_pdf_text(raw)
            kind = "pdf"
        else:
            enc = r.encoding or "utf-8"
            text = extract_html_text(raw, enc)
            err = None
            kind = "html" if "html" in ctype or b"<html" in raw[:1000].lower() else "text"
        return FetchResult(
            url=url,
            final_url=r.url,
            ok=bool(r.ok and text.strip()),
            status_code=r.status_code,
            content_type=ctype,
            size_bytes=len(raw),
            elapsed_s=elapsed,
            kind=kind,
            text=text,
            error=err if not text.strip() else None,
            raw=raw,
        )
    except Exception as e:
        return FetchResult(url, url, False, None, "", 0, time.monotonic() - start, "error", "", str(e), None)


def _num(raw: str) -> float | None:
    s = (raw or "").strip().replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    s = s.replace("€", "").replace("EUR", "").replace("$", "")
    # decimal comma vs thousands separators
    if "," in s and "." not in s:
        parts = s.split(",")
        if len(parts[-1]) <= 2:
            s = ".".join(parts)
        else:
            s = "".join(parts)
    elif "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(re.sub(r"[^0-9+\-.]", "", s))
    except Exception:
        return None


def parse_annual_eps(text: str, target_year: int, basis: str = "adjusted") -> dict[str, Any]:
    """High-confidence FY EPS parser.

    For adjusted EPS, the word ``adjusted`` must be semantically bound to the
    EPS label itself. A nearby adjusted profit line is not sufficient. This
    prevents table flattening from binding unrelated values (for example a
    reported EPS, dividend, percentage or another euro amount) to adjusted EPS.
    """
    raw = text or ""
    compact = normalize_ws(raw)

    if basis == "adjusted":
        label_patterns = [
            r"(?:adjusted|underlying)\s+(?:net\s+)?(?:earnings|net\s+earnings)\s+per\s+share(?:\s*\(?EPS\)?)?",
            r"(?:earnings|net\s+earnings)\s+per\s+share(?:\s*\(?EPS\)?)?\s*(?:[-–—:,]\s*)?(?:adjusted|underlying)",
            r"adjusted\s+EPS\b",
            r"EPS\s*(?:[-–—:,]\s*)?adjusted\b",
        ]
    else:
        label_patterns = [
            r"(?:reported|accounting)\s+(?:net\s+)?(?:earnings|net\s+earnings)\s+per\s+share(?:\s*\(?EPS\)?)?",
            r"(?:earnings|net\s+earnings)\s+per\s+share(?:\s*\(?EPS\)?)?",
        ]

    label_re = re.compile("(?:" + "|".join(label_patterns) + ")", re.I)

    def number_candidates(fragment: str) -> list[float]:
        vals: list[float] = []
        # EPS values normally contain a decimal separator; integers are accepted
        # only when explicitly currency-bound. 4-digit years are excluded.
        token_re = re.compile(r"(?<!\d)([+\-]?[0-9]{1,2}(?:[.,][0-9]{1,3})?)(?!\d)")
        for m in token_re.finditer(fragment or ""):
            tail = (fragment or "")[m.end():m.end()+3]
            head = (fragment or "")[max(0, m.start()-6):m.start()]
            if "%" in tail or re.match(r"\s*pp", tail, re.I):
                continue
            val = _num(m.group(1))
            if val is None or not (0.05 <= abs(val) <= 100):
                continue
            # Ignore footnote/list numbers unless decimal or currency adjacent.
            raw_token = m.group(1)
            if "." not in raw_token and "," not in raw_token and not re.search(r"(?:€|EUR)\s*$", head, re.I):
                continue
            vals.append(val)
        return vals

    # 1) Row/line binding first. This is safest for flattened issuer tables.
    lines = [normalize_ws(x) for x in raw.splitlines() if normalize_ws(x)]
    for i, line in enumerate(lines):
        lm = label_re.search(line)
        if not lm:
            continue
        # Start after the exact adjusted-EPS label so preceding reported EPS
        # values cannot leak into the adjusted row.
        tail = line[lm.end():]
        block_lines = [tail]
        # If PDF extraction placed values on following lines, accept at most the
        # next two lines and stop before a new semantic row label.
        for j in range(i + 1, min(len(lines), i + 3)):
            nxt = lines[j]
            if re.search(r"(?:net\s+income|operating\s+income|dividend|assets\s+under\s+management|cost\s*/?\s*income|earnings\s+per\s+share)", nxt, re.I):
                break
            block_lines.append(nxt)
        block = " ".join(block_lines)
        if re.search(r"\b(?:Q[1-4]|H[12]|quarter|half[- ]year|nine months)\b", block, re.I) and not re.search(r"full[- ]year|annual|for the year|\bFY\b", block, re.I):
            continue
        vals = number_candidates(block)
        if vals:
            return {
                "ok": True,
                "year": target_year,
                "value": vals[0],
                "basis": basis,
                "method": "explicit_adjusted_eps_row" if basis == "adjusted" else "explicit_eps_row",
                "evidence": normalize_ws(" ".join(lines[max(0, i-1):min(len(lines), i+3)]))[:500],
            }

    # 2) Compact sentence binding for prose releases such as
    # "Adjusted earnings per share reached EUR 6.58 in 2025".
    for lm in label_re.finditer(compact):
        lo = max(0, lm.start() - 80)
        hi = min(len(compact), lm.end() + 180)
        window = compact[lo:hi]
        if str(target_year) not in window and not re.search(r"full[- ]year|annual|for the year|\bFY\b", window, re.I):
            continue
        if re.search(r"\b(?:Q[1-4]|H[12]|quarter|half[- ]year|nine months)\b", window, re.I) and not re.search(r"full[- ]year|annual|for the year|\bFY\b", window, re.I):
            continue
        after = compact[lm.end():hi]
        vals = number_candidates(after)
        if vals:
            return {
                "ok": True,
                "year": target_year,
                "value": vals[0],
                "basis": basis,
                "method": "explicit_adjusted_eps_clause" if basis == "adjusted" else "explicit_eps_clause",
                "evidence": normalize_ws(window)[:500],
            }

    return {"ok": False, "year": target_year, "value": None, "basis": basis, "method": "not_found", "evidence": ""}


def validate_annual_eps_history(eps_map: dict[int, float], target_years: Iterable[int]) -> dict[str, Any]:
    """Fail closed on an implausible same-basis EPS history.

    The guard does not replace semantic parsing. It catches residual extraction
    mistakes that survive row binding. A very large isolated jump requires
    manual review because stock splits, accounting rebases or corporate actions
    can also create genuine discontinuities.
    """
    years = [int(y) for y in target_years]
    available = {int(y): float(eps_map[y]) for y in years if y in eps_map}
    issues: list[dict[str, Any]] = []
    if len(available) < len(years):
        return {"ok": False, "issues": [{"type": "missing_years", "years": [y for y in years if y not in available]}]}

    abs_values = sorted(abs(v) for v in available.values() if v is not None)
    if not abs_values:
        return {"ok": False, "issues": [{"type": "empty_history"}]}
    median = abs_values[len(abs_values)//2]
    if median <= 0:
        return {"ok": False, "issues": [{"type": "nonpositive_median", "median": median}]}

    for year, value in sorted(available.items(), reverse=True):
        ratio = abs(value) / median if median else float("inf")
        # A >4x isolated deviation is not silently accepted. This is deliberately
        # conservative: such a discontinuity needs explicit corporate-action or
        # rebasing evidence before the valuation pipeline may continue.
        if ratio > 4.0 or ratio < 0.25:
            issues.append({
                "type": "multi_year_outlier",
                "year": year,
                "value": value,
                "median_abs_eps": median,
                "ratio_to_median": round(ratio, 3),
            })

    ordered = sorted(available)
    for y0, y1 in zip(ordered, ordered[1:]):
        a, b = abs(available[y0]), abs(available[y1])
        if min(a, b) > 0:
            ratio = max(a, b) / min(a, b)
            if ratio > 4.0:
                issues.append({
                    "type": "year_to_year_discontinuity",
                    "from_year": y0,
                    "to_year": y1,
                    "from_value": available[y0],
                    "to_value": available[y1],
                    "ratio": round(ratio, 3),
                })

    return {"ok": not issues, "issues": issues, "median_abs_eps": median}

def _text_lines(text: str) -> list[str]:
    return [normalize_ws(x) for x in (text or "").splitlines() if normalize_ws(x)]


def _first_number_after_label(line: str, label_re: str) -> tuple[str | None, float | None]:
    m = re.search(label_re, line or "", re.I)
    if not m:
        return None, None
    tail = (line or "")[m.end():]
    n = re.search(r"([+\-]?\(?[0-9][0-9.,]*\)?)", tail)
    if not n:
        return None, None
    raw = n.group(1)
    val = _num(raw.replace("(", "-").replace(")", "")) if raw.startswith("(") else _num(raw)
    return raw, val


def _first_percentage(line: str) -> tuple[str | None, float | None]:
    m = re.search(r"([+\-]?[0-9]{1,3}(?:[.,][0-9]+)?)\s*%", line or "")
    if not m:
        return None, None
    return m.group(1), _num(m.group(1))



def _structured_compact_kpi_bindings(text: str) -> dict[str, dict[str, Any]]:
    """High-confidence KPI bindings that survive flattened PDF text.

    Targets issuer table-row grammar rather than nearby prose. Values are not
    issuer-specific: the labels/unit wrappers define the semantic row.
    """
    compact = normalize_ws(text or "")
    out: dict[str, dict[str, Any]] = {}

    def ctx(m, radius=110):
        if not m:
            return ""
        return compact[max(0, m.start()-radius): min(len(compact), m.end()+radius)]

    # AuM (€bn) 2,581 ...  / Assets under management (EUR bn) 2,581 ...
    m = re.search(
        r"\b(?:AuM|Assets\s+under\s+management)\s*[\(\{]\s*(?:€|EUR)?\s*(bn|billion|tn|trillion)\s*[\)\}]\s*([+\-]?[0-9][0-9.,]*)",
        compact, re.I,
    )
    if m:
        raw = m.group(2); val = _num(raw)
        out['aum'] = {
            'status': 'PASS' if val is not None else 'FAIL', 'raw_line': ctx(m),
            'raw_value': raw, 'parsed_value': val, 'unit': m.group(1),
            'method': 'compact_structured_aum_row', 'candidate_count': 1,
        }

    # Total net inflows {€bn) +56.4 ... (tolerate mismatched brace/paren from PDF extraction)
    m = re.search(
        r"\btotal\s+net\s+(?:inflows|flows)\s*[\(\{]\s*(?:€|EUR)?\s*(bn|billion|m|million)\s*[\)\}]\s*([+\-]?[0-9][0-9.,]*)",
        compact, re.I,
    )
    if m:
        raw = m.group(2); val = _num(raw)
        out['net_flows'] = {
            'status': 'PASS' if val is not None else 'FAIL', 'raw_line': ctx(m),
            'raw_value': raw, 'parsed_value': val, 'unit': m.group(1),
            'method': 'compact_structured_total_flow_row', 'candidate_count': 1,
        }

    # Prefer adjusted/ajusted CIR over the unadjusted line when both exist.
    m = re.search(
        r"cost\s*[/\- ]\s*income\s+ratio\s*,?\s*(?:adjusted|ajusted)(?:\s*,?\s*normalised)?\s*\(%\)\s*[^0-9]{0,50}([0-9]{1,2}(?:[.,][0-9]+)?)\s*%",
        compact, re.I,
    )
    if m:
        raw = m.group(1); val = _num(raw)
        out['cost_income_ratio'] = {
            'status': 'PASS' if val is not None else 'FAIL', 'raw_line': ctx(m),
            'raw_value': raw, 'parsed_value': val, 'unit': '%',
            'method': 'compact_structured_adjusted_cir_row', 'candidate_count': 1,
        }

    # Net management fees 1,619 1,454 +11.3% ... -> bind first percent after the row label.
    m = re.search(r"(?:net\s+)?management\s+fees\b.{0,140}?([+\-]?[0-9]{1,3}(?:[.,][0-9]+)?)\s*%", compact, re.I)
    if m:
        raw = m.group(1); val = _num(raw)
        out['fee_growth'] = {
            'status': 'PASS' if val is not None else 'FAIL', 'raw_line': ctx(m),
            'raw_value': raw, 'parsed_value': val, 'unit': '%',
            'method': 'compact_structured_fee_growth_row', 'candidate_count': 1,
        }
    return out

def diagnose_kpi_bindings(text: str) -> dict[str, dict[str, Any]]:
    """Return transparent row-level binding diagnostics for current-period KPIs."""
    lines = _text_lines(text)
    result: dict[str, dict[str, Any]] = _structured_compact_kpi_bindings(text)

    # Total AUM: prefer explicit AuM row and avoid average/subcomponent rows.
    aum_rows = [l for l in lines if re.search(r"(?:^|\s)(?:AuM|Assets\s+under\s+management)(?:\s|\()", l, re.I)]
    aum_rows = [l for l in aum_rows if not re.search(r"average|excluding|o/w|of which", l, re.I)] or aum_rows
    chosen = next((l for l in aum_rows if re.search(r"AuM\s*\([^)]*(?:€|EUR)?\s*(?:bn|billion|tn|trillion)", l, re.I)), aum_rows[0] if aum_rows else "")
    raw, val = _first_number_after_label(chosen, r"(?:AuM|Assets\s+under\s+management)(?:\s*\([^)]*\))?") if chosen else (None, None)
    unit_m = re.search(r"\((?:[^)]*?)(bn|billion|tn|trillion)(?:[^)]*?)\)", chosen, re.I) if chosen else None
    unit = unit_m.group(1) if unit_m else ("bn" if re.search(r"€\s*bn|EUR\s*bn", chosen, re.I) else None)
    if "aum" not in result:
        result["aum"] = {"status": "PASS" if val is not None else "FAIL", "raw_line": chosen, "raw_value": raw, "parsed_value": val, "unit": unit, "method": "line_table_first_value" if chosen else "not_found", "candidate_count": len(aum_rows)}

    # Net flows: prefer explicit total row; first number is the current H1/YTD value.
    flow_rows = [l for l in lines if re.search(r"(?:total\s+)?net\s+(?:inflows|flows)", l, re.I)]
    chosen = next((l for l in flow_rows if re.search(r"total\s+net\s+(?:inflows|flows)", l, re.I)), flow_rows[0] if flow_rows else "")
    raw, val = _first_number_after_label(chosen, r"(?:total\s+)?net\s+(?:inflows|flows)(?:\s*[({][^)}]*[)}])?") if chosen else (None, None)
    unit = "bn" if chosen and re.search(r"(?:€|EUR)?\s*bn", chosen, re.I) else ("m" if chosen and re.search(r"(?:€|EUR)?\s*(?:m|million)", chosen, re.I) else None)
    if "net_flows" not in result:
        result["net_flows"] = {"status": "PASS" if val is not None else "FAIL", "raw_line": chosen, "raw_value": raw, "parsed_value": val, "unit": unit, "method": "line_total_flow_first_value" if chosen else "not_found", "candidate_count": len(flow_rows)}

    # CIR: adjusted/ajusted row has priority over unadjusted row.
    cir_rows = [l for l in lines if re.search(r"cost\s*[/\- ]\s*income\s+ratio", l, re.I)]
    adjusted_rows = [l for l in cir_rows if re.search(r"adjusted|ajusted", l, re.I) and not re.search(r"normalis", l, re.I)]
    chosen = adjusted_rows[0] if adjusted_rows else (cir_rows[0] if cir_rows else "")
    raw, val = _first_percentage(chosen) if chosen else (None, None)
    if "cost_income_ratio" not in result:
        result["cost_income_ratio"] = {"status": "PASS" if val is not None else "FAIL", "raw_line": chosen, "raw_value": raw, "parsed_value": val, "unit": "%", "method": "line_adjusted_first_percent" if adjusted_rows else ("line_first_percent" if chosen else "not_found"), "candidate_count": len(cir_rows)}

    # Fee growth: use first percentage on management-fee row, not the last digit before '%'.
    fee_rows = [l for l in lines if re.search(r"(?:net\s+)?management\s+fees", l, re.I)]
    chosen = fee_rows[0] if fee_rows else ""
    raw, val = _first_percentage(chosen) if chosen else (None, None)
    if "fee_growth" not in result:
        result["fee_growth"] = {"status": "PASS" if val is not None else "FAIL", "raw_line": chosen, "raw_value": raw, "parsed_value": val, "unit": "%", "method": "line_first_percent" if chosen else "not_found", "candidate_count": len(fee_rows)}

    for key, unit in (("aum", None), ("net_flows", None), ("cost_income_ratio", "%"), ("fee_growth", "%")):
        result.setdefault(key, {"status": "FAIL", "raw_line": "", "raw_value": None, "parsed_value": None, "unit": unit, "method": "not_found", "candidate_count": 0})
    return result


def parse_kpis(text: str) -> dict[str, Any]:
    compact = normalize_ws(text)
    out: dict[str, Any] = {}

    date_patterns = [
        r"data\s+as\s+of\s*[:]?\s*(\d{1,2}[/-]\d{1,2}[/-]20\d{2})",
        r"as\s+at\s+(\d{1,2}\s+[A-Za-z]+\s+20\d{2})",
        r"as\s+of\s+(\d{1,2}\s+[A-Za-z]+\s+20\d{2})",
    ]
    for p in date_patterns:
        m = re.search(p, compact, re.I)
        if m:
            out["as_of"] = m.group(1)
            break

    diag = diagnose_kpi_bindings(text)
    if diag["aum"]["parsed_value"] is not None:
        out["aum"] = diag["aum"]["parsed_value"]
        out["aum_unit"] = diag["aum"]["unit"] or "bn"
        out["aum_evidence"] = diag["aum"]["raw_line"][:300]
    if diag["net_flows"]["parsed_value"] is not None:
        out["net_flows"] = diag["net_flows"]["parsed_value"]
        out["net_flows_unit"] = diag["net_flows"]["unit"] or "bn"
        out["net_flows_evidence"] = diag["net_flows"]["raw_line"][:300]
    if diag["cost_income_ratio"]["parsed_value"] is not None:
        out["cost_income_ratio"] = diag["cost_income_ratio"]["parsed_value"]
        out["cir_evidence"] = diag["cost_income_ratio"]["raw_line"][:250]
    if diag["fee_growth"]["parsed_value"] is not None:
        out["fee_growth"] = diag["fee_growth"]["parsed_value"]
        out["fee_growth_evidence"] = diag["fee_growth"]["raw_line"][:250]

    # Compact-text fallbacks for issuer formats that do not preserve table rows.
    if "aum" not in out:
        aum_patterns = [
            r"assets\s+under\s+management[^€]{0,120}€\s*([0-9][0-9.,\s]*)\s*(bn|billion|tn|trillion)",
            r"€\s*([0-9][0-9.,\s]*)\s*(bn|billion|tn|trillion)[^.;]{0,80}assets\s+under\s+management",
        ]
        for p in aum_patterns:
            m = re.search(p, compact, re.I)
            if m:
                out["aum"] = _num(m.group(1)); out["aum_unit"] = m.group(2); out["aum_evidence"] = normalize_ws(m.group(0))[:300]; break

    if "net_flows" not in out:
        flow_patterns = [
            r"(?:net\s+inflows|net\s+flows)[^€]{0,100}([+\-]?)\s*€\s*([0-9][0-9.,\s]*)\s*(bn|billion|m|million)",
            r"([+\-]?)\s*€\s*([0-9][0-9.,\s]*)\s*(bn|billion|m|million)[^.;]{0,80}(?:net\s+inflows|net\s+flows)",
        ]
        for p in flow_patterns:
            m = re.search(p, compact, re.I)
            if m:
                sign = -1 if m.group(1) == "-" else 1
                out["net_flows"] = sign * (_num(m.group(2)) or 0); out["net_flows_unit"] = m.group(3); out["net_flows_evidence"] = normalize_ws(m.group(0))[:300]; break

    if "cost_income_ratio" not in out:
        cir = re.search(r"cost\s*[/\- ]\s*income\s+ratio\s*,?\s*(?:adjusted|ajusted)(?:\s*,?\s*normalised)?\s*\(%\)[^0-9]{0,50}([0-9]{1,2}(?:[.,][0-9]+)?)\s*%", compact, re.I)
        if not cir:
            cir = re.search(r"cost\s*[/\- ]\s*income\s+ratio[^0-9]{0,50}([0-9]{1,2}(?:[.,][0-9]+)?)\s*%", compact, re.I)
        if cir:
            out["cost_income_ratio"] = _num(cir.group(1)); out["cir_evidence"] = normalize_ws(cir.group(0))[:250]

    if "fee_growth" not in out:
        fee = re.search(r"(?:management\s+fees|fee\s+revenues?|net\s+revenues?)[^%]{0,120}?([+\-]?[0-9]{1,2}(?:[.,][0-9])?)\s*%", compact, re.I)
        if fee:
            out["fee_growth"] = _num(fee.group(1)); out["fee_growth_evidence"] = normalize_ws(fee.group(0))[:250]
    return out


def keyword_probe(text: str) -> dict[str, Any]:
    probes = {
        "assets_under_management": r"assets\s+under\s+management",
        "net_flows": r"net\s+(?:inflows|flows)",
        "earnings_per_share": r"earnings\s+per\s+share",
        "cost_income_ratio": r"cost[- ]?(?:to[- ]?)?income\s+ratio",
        "adjusted": r"adjusted",
    }
    return {k: bool(re.search(v, text or "", re.I)) for k, v in probes.items()}


def snippet_around(text: str, pattern: str, radius: int = 260) -> str:
    m = re.search(pattern, text or "", re.I)
    if not m:
        return ""
    lo = max(0, m.start() - radius)
    hi = min(len(text), m.end() + radius)
    return normalize_ws(text[lo:hi])


def save_fixture(root: Path, name: str, fetch: FetchResult) -> Path | None:
    if fetch.raw is None:
        return None
    root.mkdir(parents=True, exist_ok=True)
    ext = ".pdf" if fetch.kind == "pdf" else ".html" if fetch.kind == "html" else ".bin"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")[:100]
    path = root / f"{safe}{ext}"
    path.write_bytes(fetch.raw)
    (root / f"{safe}.meta.json").write_text(json.dumps(fetch.public_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def diagnose_archive_html(html: str, base_url: str, company_domain: str, target_years: Iterable[int]) -> dict[str, Any]:
    checks: list[Check] = []
    if not html.strip():
        checks.append(Check("archive_html", "FAIL", "IR-Archiv ist leer."))
        return {"checks": checks, "candidates": [], "picks": {}, "first_failure": "archive_html"}
    checks.append(Check("archive_html", "PASS", f"IR-Archiv geladen ({len(html):,} Zeichen)."))

    candidates = parse_archive_grid(html, base_url, company_domain, target_years)
    source = "html_table_grid"
    if not candidates:
        candidates = fallback_link_candidates(html, base_url, company_domain, target_years)
        source = "fallback_anchor_context"
    if candidates:
        checks.append(Check("archive_mapping", "PASS", f"{len(candidates)} Q4/FY-Kandidaten gefunden ({source})."))
    else:
        checks.append(Check("archive_mapping", "FAIL", "Keine Q4/FY-Kandidaten an Zieljahre gebunden."))

    picks = best_candidate_per_year(candidates, target_years)
    missing = [y for y in target_years if int(y) not in picks]
    if missing:
        checks.append(Check("year_coverage", "FAIL", "Jahresabdeckung unvollständig.", {"missing_years": missing}))
    else:
        checks.append(Check("year_coverage", "PASS", "Alle Zieljahre haben mindestens einen Q4/FY-Kandidaten."))

    first = next((c.stage for c in checks if c.status == "FAIL"), None)
    return {"checks": checks, "candidates": candidates, "picks": picks, "first_failure": first}


def load_fixture_directory(root: Path) -> dict[str, FetchResult]:
    """Load saved fixture files keyed by original and final URL."""
    root = Path(root)
    out: dict[str, FetchResult] = {}
    if not root.exists():
        return out
    for meta_path in root.glob("*.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            stem = meta_path.name[:-10]  # strip .meta.json
            raw_path = None
            for ext in (".pdf", ".html", ".bin"):
                p = root / f"{stem}{ext}"
                if p.exists():
                    raw_path = p
                    break
            if raw_path is None:
                continue
            raw = raw_path.read_bytes()
            kind = meta.get("kind") or ("pdf" if raw_path.suffix == ".pdf" else "html")
            if kind == "pdf":
                text, err = extract_pdf_text(raw)
            else:
                text = extract_html_text(raw)
                err = None
            fr = FetchResult(
                url=meta.get("url") or "",
                final_url=meta.get("final_url") or meta.get("url") or "",
                ok=bool(text.strip()),
                status_code=meta.get("status_code"),
                content_type=meta.get("content_type") or "",
                size_bytes=len(raw),
                elapsed_s=0.0,
                kind=kind,
                text=text,
                error=err if not text.strip() else None,
                raw=raw,
            )
            if fr.url:
                out[fr.url] = fr
            if fr.final_url:
                out[fr.final_url] = fr
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Shared production/control pipeline
# ---------------------------------------------------------------------------
def engine_sha256() -> str:
    """SHA-256 of this exact engine source file.

    The control app displays this value. The main Aktien-Analyse app must display
    the same value before an Asset-Manager result is considered a 1:1 run.
    """
    import hashlib
    try:
        data = Path(__file__).read_bytes()
    except Exception:
        return "unavailable"
    return hashlib.sha256(data).hexdigest()


def _check_dict(c: Check) -> dict[str, Any]:
    return {"stage": c.stage, "status": c.status, "message": c.message, "details": c.details}


def _default_candidate_rank(item: dict[str, Any], current_priority: dict[str, int]) -> tuple:
    k = item.get("kpis") or {}
    row = item.get("row") or {}
    core_count = int(row.get("core_kpis") or 0)
    total_count = int(row.get("total_kpis") or 0)
    dated = 1 if k.get("as_of") else 0
    probe_count = sum(1 for v in (item.get("probes") or {}).values() if v)
    class_score = -current_priority.get((item.get("candidate") or {}).get("document_class"), 9)
    return (core_count, total_count, dated, probe_count, min(int(row.get("text_chars") or 0), 200000), class_score)


def run_asset_manager_evidence_pipeline(
    *,
    company: str,
    symbol: str,
    company_domain: str,
    archive_url: str,
    target_years: Iterable[int] = (2025, 2024, 2023),
    current_year: int = 2026,
    current_periods: Iterable[str] = ("Q2", "H1"),
    timeout: float = 20.0,
    fetcher=None,
    fixture_root: Path | None = None,
    save_fixtures: bool = False,
) -> dict[str, Any]:
    """Authoritative Asset-Manager evidence path used by control and production.

    This function intentionally stops at evidence readiness. It does not calculate
    a fair value, score or signal. The main app must consume its returned evidence
    instead of re-running a separate Asset-Manager parser path.
    """
    target_years = [int(y) for y in target_years]
    current_periods = [str(x).upper().strip() for x in current_periods if str(x).strip()]
    session = requests.Session()
    checks: list[Check] = []
    diagnostic_events: list[dict[str, Any]] = []

    def emit(c: Check):
        checks.append(c)
        diagnostic_events.append(_check_dict(c))
        return c

    if fetcher is None:
        def get_fetch(url: str):
            return fetch_primary(url, timeout=float(timeout), session=session)
    else:
        get_fetch = fetcher

    # 1) Archive fetch + structural discovery.
    archive_fetch = get_fetch(archive_url)
    if archive_fetch is None:
        emit(Check("archive_fetch", "FAIL", "Archivquelle nicht verfügbar."))
        return _pipeline_finalize(company, symbol, company_domain, archive_url, target_years, current_year, current_periods, checks, diagnostic_events, None, {}, [], {})
    if save_fixtures and fixture_root is not None and archive_fetch.raw:
        save_fixture(Path(fixture_root), "financial_results_archive", archive_fetch)
    if not archive_fetch.ok:
        emit(Check("archive_fetch", "FAIL", f"Archiv konnte nicht geladen werden: {archive_fetch.error or archive_fetch.status_code}", archive_fetch.public_dict()))
        return _pipeline_finalize(company, symbol, company_domain, archive_url, target_years, current_year, current_periods, checks, diagnostic_events, None, {}, [], {})
    emit(Check("archive_fetch", "PASS", f"Archiv geladen: HTTP {archive_fetch.status_code}, {archive_fetch.size_bytes:,} Bytes."))
    archive_markup = html_source_from_fetch(archive_fetch)
    emit(Check("archive_markup", "PASS" if "<" in archive_markup and ">" in archive_markup else "FAIL", f"Strukturelles Roh-HTML bereit ({len(archive_markup):,} Zeichen)." if archive_markup else "Kein strukturelles Roh-HTML verfügbar."))
    archive_diag = diagnose_archive_html(archive_markup, archive_fetch.final_url, company_domain, target_years)
    for c in archive_diag["checks"]:
        emit(c)
    candidates = archive_diag["candidates"]

    # 2) Current-period evidence.
    current_candidates = period_candidates(archive_markup, archive_fetch.final_url, company_domain, int(current_year), current_periods)
    current_priority = {"financial_data_supplement": 0, "press_release": 1, "presentation": 2, "half_year_report": 3, "annual_report": 4, "other": 9}
    current_candidates = sorted(
        current_candidates,
        key=lambda c: (
            current_periods.index(c.get("period")) if c.get("period") in current_periods else 99,
            current_priority.get(c.get("document_class"), 9),
        ),
    )
    evaluated = []
    for idx, cand in enumerate(current_candidates):
        fr = get_fetch(cand["url"])
        row = {
            "attempt": idx + 1,
            "period": cand.get("period"),
            "document_class": cand.get("document_class"),
            "url": cand.get("url"),
            "fetch_ok": False,
            "kind": None,
            "text_chars": 0,
            "core_kpis": 0,
            "total_kpis": 0,
            "aum": None,
            "net_flows": None,
            "cir": None,
            "fee_growth": None,
        }
        if fr is None:
            row["fetch_note"] = "fixture_missing"
            evaluated.append({"candidate": cand, "fetch": None, "row": row, "kpis": {}, "binding": {}, "probes": {}})
            continue
        if save_fixtures and fixture_root is not None and fr.raw:
            save_fixture(Path(fixture_root), f"current_{current_year}_{idx+1}_{cand['document_class']}_{cand['period']}", fr)
        row.update({"fetch_ok": bool(fr.ok), "kind": fr.kind, "text_chars": len(fr.text or ""), "size_bytes": fr.size_bytes})
        if not fr.ok:
            row["fetch_note"] = fr.error or fr.status_code
            evaluated.append({"candidate": cand, "fetch": fr, "row": row, "kpis": {}, "binding": {}, "probes": {}})
            continue
        probes = keyword_probe(fr.text)
        binding = diagnose_kpi_bindings(fr.text)
        kpis = parse_kpis(fr.text)
        core_count = sum(1 for k in ("aum", "net_flows", "cost_income_ratio") if k in kpis)
        total_count = core_count + (1 if "fee_growth" in kpis else 0)
        row.update({
            "core_kpis": core_count,
            "total_kpis": total_count,
            "aum": kpis.get("aum"),
            "net_flows": kpis.get("net_flows"),
            "cir": kpis.get("cost_income_ratio"),
            "fee_growth": kpis.get("fee_growth"),
            "as_of": kpis.get("as_of"),
        })
        evaluated.append({"candidate": cand, "fetch": fr, "row": row, "kpis": kpis, "binding": binding, "probes": probes})

    current_snapshot = None
    usable = [x for x in evaluated if x.get("fetch") is not None and x["fetch"].ok]
    if usable:
        emit(Check("current_document_fetch", "PASS", f"{len(usable)}/{len(current_candidates)} aktuelle Dokumentkandidaten nutzbar geladen/extrahiert."))
        best = max(usable, key=lambda x: _default_candidate_rank(x, current_priority))
        kpis = best["kpis"]
        complete = all(k in kpis for k in ("aum", "net_flows", "cost_income_ratio"))
        if complete:
            current_snapshot = {
                "candidate": best["candidate"],
                "fetch": best["fetch"].public_dict(),
                "kpis": kpis,
                "bindings": best["binding"],
                "probes": best["probes"],
            }
            emit(Check("current_snapshot_mapping", "PASS", "Aktueller Snapshot vollständig: AUM + Net Flows + CIR.", kpis))
        else:
            missing = [k for k in ("aum", "net_flows", "cost_income_ratio") if k not in kpis]
            emit(Check("current_snapshot_mapping", "FAIL", "Bester geladener aktueller Kandidat ist in der KPI-Bindung unvollständig.", {
                "selected_document_class": best["candidate"].get("document_class"),
                "selected_period": best["candidate"].get("period"),
                "selected_url": best["candidate"].get("url"),
                "missing": missing,
                "kpis": kpis,
            }))
    else:
        if current_candidates:
            attempt_details = []
            for x in evaluated:
                fr = x.get("fetch")
                row = x.get("row") or {}
                attempt_details.append({
                    "period": row.get("period"),
                    "document_class": row.get("document_class"),
                    "url": row.get("url"),
                    "status_code": getattr(fr, "status_code", None) if fr is not None else None,
                    "kind": getattr(fr, "kind", None) if fr is not None else None,
                    "content_type": getattr(fr, "content_type", None) if fr is not None else None,
                    "size_bytes": getattr(fr, "size_bytes", 0) if fr is not None else 0,
                    "text_chars": len(getattr(fr, "text", "") or "") if fr is not None else 0,
                    "error": (getattr(fr, "error", None) if fr is not None else "fixture_missing"),
                })
            emit(Check("current_document_fetch", "FAIL", "Aktuelle H1/Q2-Kandidaten wurden gefunden, aber kein Dokument konnte nutzbar geladen/extrahiert werden.", {
                "candidate_count": len(current_candidates),
                "attempts": attempt_details,
            }))
        else:
            emit(Check("current_period_discovery", "FAIL", f"Keine {current_periods} Kandidaten für {int(current_year)} im Archiv gefunden."))

    # 3) Annual same-basis evidence, one explicit target year at a time.
    year_results: dict[int, Any] = {}
    for year in sorted(target_years, reverse=True):
        year_candidates = [c for c in candidates if c.get("year") == year]
        parsed = None
        attempts = []
        fetched_ok = 0
        if not year_candidates:
            emit(Check(f"document_{year}", "FAIL", "Kein Dokumentkandidat vorhanden."))
            year_results[year] = {"parsed": None, "attempts": attempts}
            continue
        for idx, cand in enumerate(year_candidates):
            fr = get_fetch(cand["url"])
            if fr is None:
                attempts.append({**cand, "fetch_note": "fixture_missing"})
                continue
            attempts.append({**cand, **fr.public_dict()})
            if save_fixtures and fixture_root is not None and fr.raw:
                save_fixture(Path(fixture_root), f"{year}_{idx+1}_{cand['document_class']}_{cand['period']}", fr)
            if not fr.ok:
                continue
            fetched_ok += 1
            eps = parse_annual_eps(fr.text, year, basis="adjusted")
            kpis = parse_kpis(fr.text)
            if eps["ok"]:
                parsed = {"candidate": cand, "fetch": fr.public_dict(), "eps": eps, "kpis": kpis}
                emit(Check(f"annual_eps_{year}", "PASS", f"Adjusted FY EPS {year}: {eps['value']:.2f}.", {"evidence": eps["evidence"], "url": cand.get("url"), "method": eps.get("method")}))
                break
        year_results[year] = {"parsed": parsed, "attempts": attempts}
        if parsed is None:
            brief_attempts = [{
                "document_class": a.get("document_class"),
                "period": a.get("period"),
                "url": a.get("url"),
                "status_code": a.get("status_code"),
                "kind": a.get("kind"),
                "content_type": a.get("content_type"),
                "size_bytes": a.get("size_bytes"),
                "text_length": a.get("text_length"),
                "error": a.get("error") or a.get("fetch_note"),
            } for a in attempts]
            if fetched_ok == 0:
                emit(Check(f"annual_document_fetch_{year}", "FAIL", f"Dokumentkandidaten für {year} gefunden, aber keiner konnte nutzbar geladen/extrahiert werden.", {"attempts": brief_attempts}))
            else:
                emit(Check(f"annual_eps_parse_{year}", "FAIL", f"{fetched_ok} Dokument(e) für {year} wurden geladen, aber kein eindeutig gebundener Adjusted-FY-EPS wurde erkannt.", {"attempts": brief_attempts}))

    eps_map = {y: r["parsed"]["eps"]["value"] for y, r in year_results.items() if r.get("parsed")}
    if len(eps_map) == len(target_years):
        emit(Check("annual_eps_history", "PASS", "Alle Zieljahre auf derselben Adjusted-EPS-Basis vorhanden.", {str(y): eps_map[y] for y in sorted(eps_map)}))
        quality = validate_annual_eps_history(eps_map, target_years)
        if quality.get("ok"):
            emit(Check("annual_eps_history_quality", "PASS", "Mehrjahres-EPS semantisch gebunden und ohne unbestätigte Ausreißer.", quality))
        else:
            emit(Check("annual_eps_history_quality", "FAIL", "Mehrjahres-EPS enthält einen unbestätigten Ausreißer / Basisbruch. Evidence-Freigabe gesperrt.", quality))
    else:
        missing = [y for y in target_years if y not in eps_map]
        emit(Check("annual_eps_history", "FAIL", "3Y-Historie unvollständig.", {"missing_years": missing, "available": eps_map}))

    return _pipeline_finalize(company, symbol, company_domain, archive_url, target_years, current_year, current_periods, checks, diagnostic_events, current_snapshot, eps_map, evaluated, year_results)


def _pipeline_finalize(company, symbol, company_domain, archive_url, target_years, current_year, current_periods, checks, diagnostic_events, current_snapshot, eps_map, current_candidates, year_results):
    # Deduplicate exact repeated diagnostics while retaining order.
    deduped = []
    seen = set()
    for c in checks:
        key = (c.stage, c.status, c.message, json.dumps(c.details or {}, sort_keys=True, ensure_ascii=False, default=str))
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    fails = [c for c in deduped if c.status == "FAIL"]
    warns = [c for c in deduped if c.status == "WARN"]
    passes = [c for c in deduped if c.status == "PASS"]
    first_failure = fails[0] if fails else None
    annual_complete = len(eps_map) == len(target_years)
    annual_quality_complete = any(c.stage == "annual_eps_history_quality" and c.status == "PASS" for c in deduped)
    current_complete = bool(current_snapshot and all(k in (current_snapshot.get("kpis") or {}) for k in ("aum", "net_flows", "cost_income_ratio")))
    evidence_ready = bool(current_complete and annual_complete and annual_quality_complete and not fails)
    return {
        "engine_version": ENGINE_VERSION,
        "engine_sha256": engine_sha256(),
        "company": company,
        "symbol": symbol,
        "company_domain": company_domain,
        "archive_url": archive_url,
        "target_years": list(target_years),
        "current_year": int(current_year),
        "current_periods": list(current_periods),
        "current_snapshot": current_snapshot,
        "current_candidate_evaluations": [x.get("row", {}) for x in current_candidates],
        "annual_eps": eps_map,
        "annual_results": year_results,
        "checks": [_check_dict(c) for c in deduped],
        "counts": {"pass": len(passes), "warn": len(warns), "fail": len(fails)},
        "first_failure": _check_dict(first_failure) if first_failure else None,
        "current_complete": current_complete,
        "annual_history_complete": annual_complete,
        "annual_history_quality_complete": annual_quality_complete,
        "evidence_ready": evidence_ready,
        "production_contract": {
            "required_engine_sha256": engine_sha256(),
            "rule": "Control Center and Aktien-Analyse must import this exact module and call run_asset_manager_evidence_pipeline().",
        },
    }
