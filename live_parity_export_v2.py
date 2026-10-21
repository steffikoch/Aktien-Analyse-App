"""V2 read-only reference export for one already-computed Streamlit result.

No provider calls. No model recalculation. Staging is NEVER labeled as a phone live export.
Neither same-data inputs, identity nor strict parity is attested by this module.
"""
from __future__ import annotations
import datetime as dt
import decimal
import hashlib
import json
import math
from pathlib import Path

IDENTITY_FIELDS = ('selected_symbol','selected_exchange','selected_exchange_code',
                   'primary_symbol','primary_exchange','selected_currency',
                   'listing_role','identifier_verified','identity_match_reason')
BASE_FIELDS = ('symbol','exchange','currency','financial_currency',
    'fundamental_symbol','fundamental_exchange','price','market_cap','trailing_eps',
    'forward_eps','valuation_trailing_eps','valuation_forward_eps','revenue',
    'net_income','free_cashflow','cash','debt','revenue_growth','earnings_growth',
    'earnings_growth_for_score','profit_margin','roe')
CURRENCY_FIELDS = ('quote_currency','financial_currency','conversion_kind',
    'conversion_available','financial_to_quote_factor','quote_to_financial_factor',
    'fx_symbol','mixed_units')
DISPLAY_RATE_FIELDS = ('factor','symbol','as_of','retrieved_at','available')
SPECIALIST_FIELDS = ('available','applicable','score','normalized_eps',
    'target_multiple','premium_unlock_count','annualized_flow_rate_pct',
    'flow_rate_verified','flow_direction','flow_cap_applied', 'as_of_date',
    'beginning_aum','aum_growth_pct','effective_fee_rate_bps')


def safe(value, depth=0):
    if depth > 7:
        return None
    if value is None or isinstance(value, (str,bool)):
        return value
    if isinstance(value,(int,float,decimal.Decimal)):
        v=float(value) if isinstance(value,decimal.Decimal) else value
        return v if math.isfinite(v) else None
    if isinstance(value,(dt.date,dt.datetime)):
        return value.isoformat()
    if isinstance(value,dict):
        return {str(k):safe(v,depth+1) for k,v in sorted(value.items(),key=lambda kv:str(kv[0])) if isinstance(k,str)}
    if isinstance(value,(tuple,list)):
        return [safe(v,depth+1) for v in value[:40]]
    return None


def pick(obj, fields):
    if not isinstance(obj,dict):
        return {}
    return {k:safe(obj[k]) for k in fields if k in obj}


def model_values(data):
    fm=data.get('fundamental_multiple') or {}
    fv=data.get('fair_value') or {}
    zn=data.get('valuation_zone') or {}
    fx=data.get('currency_context') or {}
    buy=data.get('new_buy_signal') or {}
    hold=data.get('holding_signal') or {}
    final=data.get('final_signal_overlay') or {}
    final_buy=final.get('new_buy_signal') or {}
    final_hold=final.get('holding_signal') or {}
    available=fv.get('available') is True
    # This is the exact earnings basis used by calculate_fair_value_v1.
    # TROW: Through-Cycle 30/50/20, NOT generic eps_normalization.
    # META: tax-adjusted normalized TTM EPS already used by fair_value.
    actual_eps=fv.get('normalized_eps')
    gates=None
    if available:
        gates=[]
    else:
        for src in (fv,data.get('special_control'),fm):
            if isinstance(src,dict):
                for key in ('gate_codes','blocking_codes'):
                    g=src.get(key)
                    if isinstance(g,list) and all(isinstance(x,str) for x in g):
                        gates=g; break
            if gates is not None: break
    return safe({
        'symbol':data.get('symbol'), 'exchange':data.get('exchange'),
        'listing_currency':data.get('currency'),
        'financial_currency':data.get('financial_currency'),
        'price':data.get('price'), 'score':fm.get('score'),
        # Use multiple actually applied in fair value; peer guard can change it.
        'multiple':fv.get('used_multiple'),
        'normalized_ttm_eps':actual_eps, # legacy control schema; valuation basis is documented below
        'valuation_method':fv.get('valuation_method'),
        'fair_value_quote':fv.get('fair_value_quote'),
        'valuation_zone':zn.get('zone') if zn.get('available') else None,
        'new_buy_signal':buy.get('signal') if buy.get('available') else None,
        'holding_signal':hold.get('signal') if hold.get('available') else None,
        'final_new_buy_signal':final_buy.get('signal') if final_buy.get('available') else None,
        'final_holding_signal':final_hold.get('signal') if final_hold.get('available') else None,
        'fair_value_available':available,
        'gate_codes':gates,
        'fx_financial_to_quote':fx.get('financial_to_quote_factor'),
    })


def diagnostic_subset(data, display_context=None):
    """Finite, allowlisted fields for troubleshooting; NOT full raw upstream inputs."""
    asset=data.get('asset_management_specialist_model') or {}
    sp_earn=(asset.get('earnings_basis') or asset.get('specialist_earnings') or {})
    sp_val=asset.get('specialist_valuation') or {}
    sp_score=asset.get('specialist_score') or {}
    display=display_context if isinstance(display_context,dict) else {}
    display_rates=display.get('rates') or {}
    rates={k:pick(v,DISPLAY_RATE_FIELDS) for k,v in display_rates.items()
           if isinstance(k,str) and len(k)<=5 and isinstance(v,dict)}
    return safe({
        'base':pick(data,BASE_FIELDS),
        'currency_context':pick(data.get('currency_context'),CURRENCY_FIELDS),
        'display_currency':{'target':display.get('target_currency'),
                            'enabled':display.get('enabled'), 'available':display.get('available'),
                            'rates':rates},
        'valuation':pick(data.get('fair_value'),('available','normalized_eps','used_multiple',
            'fair_value_quote','fair_value_financial','valuation_method','multiple_source')),
        'fundamental_multiple':pick(data.get('fundamental_multiple'),('available','score','multiple')),
        'eps_diagnostic':pick(data.get('eps_normalization'),('available','normalized_eps','method')),
        'tax_diagnostic':pick(data.get('discrete_tax_primary_normalization_v266'),
            ('released','normalized_ttm_eps','status')),
        'asset_manager':{'active':bool(asset.get('applicable')),
            'earnings_basis':pick(sp_earn,SPECIALIST_FIELDS),
            'specialist_valuation':pick(sp_val,SPECIALIST_FIELDS),
            'specialist_score':pick(sp_score,SPECIALIST_FIELDS)},
    })


def _event_date_utc(earnings_timestamp):
    """Yahoo earningsTimestamp denotes an EVENT, never an input-data as-of time."""
    try:
        if isinstance(earnings_timestamp, bool) or earnings_timestamp is None:
            return None
        stamp=float(earnings_timestamp)
        if not math.isfinite(stamp) or stamp <= 0:
            return None
        return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def build_live_export(data, ui_identity=None, app_file=None, display_context=None,
                      origin='STAGING_LIVE_EXPORT'):
    """Serialize an existing load_stock result; never rerun calculations or providers."""
    if origin not in ('STAGING_LIVE_EXPORT','MAIN_APP_LIVE_EXPORT'):
        raise ValueError('unsupported origin')
    if not isinstance(data,dict) or not str(data.get('symbol') or '').strip():
        raise ValueError('no existing main app result')
    src=Path(app_file) if app_file else None
    content=src.read_bytes() if src and src.is_file() else None
    source_sha=hashlib.sha256(content).hexdigest() if content else ''
    boundary=b'# =========================================================\n# Benutzeroberfl\xc3\xa4che\n# ========================================================='
    core_sha=hashlib.sha256(content.split(boundary)[0]).hexdigest() if content and boundary in content else ''
    selection=pick(ui_identity,IDENTITY_FIELDS)
    values=model_values(data)
    subset=diagnostic_subset(data,display_context)
    subset_hash=hashlib.sha256(json.dumps(subset,sort_keys=True,ensure_ascii=False,
                     separators=(',',':'),allow_nan=False).encode('utf8')).hexdigest()
    captured=dt.datetime.now(dt.timezone.utc).isoformat()
    event_date=_event_date_utc(data.get('earnings_timestamp'))
    is_am=bool((data.get('asset_management_specialist_model') or {}).get('applicable'))
    model_basis_type='THROUGH_CYCLE_30_50_20' if is_am else 'FAIR_VALUE_ACTUAL_EARNINGS_BASIS'
    return {
      'schema_version':1,
      'references':[{
        'symbol':str(data['symbol']).upper().strip(),
        'main_build':'V2.24.02',
        'main_source_sha256':source_sha,
        'captured_utc':captured,
        'data_asof':'', # input quote/filing as-of UNVERIFIED; earningsTimestamp is a FUTURE EVENT
        'data_fingerprint':'', # no false strict-input attestation
        'identity_verified':False, # UI symbol confirmation != independent identity proof
        'origin':origin,
        'values':values,
      }],
      'diagnostic_only':{
        'status':'SNAPSHOT_SUBSET_RECORDED_STRICT_PARITY_OPEN',
        'source_sha256':source_sha,
        'valuation_core_sha256':core_sha,
        'selected_identity':selection,
        'symbol_selection_matches':selection.get('selected_symbol')==data.get('symbol'),
        'actual_earnings_basis_type':model_basis_type,
        'actual_earnings_basis_quote_schema_key':'normalized_ttm_eps',
        'input_subset_sha256':subset_hash,
        'input_subset_complete':False,
        'timestamp_evidence':{
          'capture_utc':captured,
          'data_asof_status':'UNVERIFIED_NO_COMMON_QUOTE_AND_FILING_SNAPSHOT',
          'earnings_event_utc':event_date,
          'earnings_event_note':'Yahoo earningsTimestamp is next earnings event, NOT quote/fundamental snapshot time.',
          'fx_asof_in_subset':True if (subset.get('display_currency') or {}).get('rates') else False,
        },
        'subset':subset,
        'limit':'Source quotes/provider revisions, full identity attestation and identical control inputs not recorded.',
        'export_origin_scope':'Staging cannot certify the actual phone-app session.' if origin.startswith('STAGING') else 'Exported by main-app deployment; no input identity parity claimed.',
      },
    }


def build_live_export_json(*args,**kwargs):
    return json.dumps(build_live_export(*args,**kwargs),indent=2,ensure_ascii=False,allow_nan=False)
