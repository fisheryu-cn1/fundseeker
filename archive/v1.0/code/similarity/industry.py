"""Industry mapping utilities for holdings.

Fetches stock-to-industry mappings from Eastmoney public APIs and updates the
holding_security_info reference table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from fundseeker.models.database import get_session_maker
from fundseeker.models.tables import HoldingSecurityInfo
from fundseeker.utils.http import PoliteHttpClient


DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[3] / ".cache" / "industry_mapping.json"


@dataclass
class IndustryMapping:
    """Mapping from (asset_code, market) to industry name."""

    mapping: dict[tuple[str, str], str]

    def get(self, asset_code: str, market: str | None = None) -> str | None:
        market = market or "UNKNOWN"
        return self.mapping.get((asset_code, market))

    def to_serializable(self) -> dict[str, str]:
        """Return a JSON-serializable dict keyed by 'code|market'."""
        return {
            f"{code}|{market}": industry
            for (code, market), industry in self.mapping.items()
        }

    @classmethod
    def from_serializable(cls, data: dict[str, str]) -> "IndustryMapping":
        mapping: dict[tuple[str, str], str] = {}
        for key, industry in data.items():
            if "|" in key:
                code, market = key.split("|", 1)
            else:
                code, market = key, "UNKNOWN"
            mapping[(code, market)] = industry
        return cls(mapping)


def load_industry_mapping_from_cache(path: Path | str | None = None) -> IndustryMapping | None:
    """Load industry mapping from local JSON cache if it exists."""
    path = Path(path or DEFAULT_CACHE_PATH)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return IndustryMapping.from_serializable(data)


def save_industry_mapping_to_cache(
    mapping: IndustryMapping, path: Path | str | None = None
) -> None:
    """Save industry mapping to local JSON cache."""
    path = Path(path or DEFAULT_CACHE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(mapping.to_serializable(), f, ensure_ascii=False, indent=2)


def load_industry_mapping_from_db() -> IndustryMapping:
    """Build industry mapping from holding_security_info table.

    Falls back to market inference when market is missing/UNKNOWN.
    """
    Session = get_session_maker()
    mapping: dict[tuple[str, str], str] = {}

    with Session() as session:
        records = session.scalars(
            select(HoldingSecurityInfo).where(
                HoldingSecurityInfo.industry_name.isnot(None)
            )
        ).all()

        for record in records:
            code = record.asset_code
            market = record.market or _infer_market(code)
            industry = record.industry_name
            mapping[(code, market)] = industry
            # Also store under inferred market for robust lookup.
            inferred = _infer_market(code)
            if inferred != market:
                mapping[(code, inferred)] = industry

    return IndustryMapping(mapping)


def _infer_market(code: str) -> str:
    """Infer A-share market from stock code (same rules as holding collector)."""
    code = str(code).strip()
    if code.startswith(("60", "68", "51", "52", "53")):
        return "SH"
    if code.startswith(("00", "30", "39", "12", "08")):
        return "SZ"
    if code.startswith(("8", "4", "43")):
        return "BJ"
    if len(code) == 5:
        return "HK"
    return "UNKNOWN"


def _fetch_eastmoney_list(fs: str, page_size: int = 100) -> pd.DataFrame:
    """Fetch all pages of stock list data from Eastmoney clist API."""
    client = PoliteHttpClient(min_delay=0.3, max_delay=0.8, respect_robots_txt=False)
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    rows: list[dict[str, Any]] = []
    page = 1

    while True:
        params = {
            "pn": page,
            "pz": page_size,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f12",
            "fs": fs,
            "fields": "f12,f13,f14,f100",
        }

        response = client.get(url, params=params)
        data = response.json()
        diff = data.get("data", {}).get("diff", [])
        total = data.get("data", {}).get("total", 0)

        if not diff:
            break

        for item in diff:
            code = str(item.get("f12", "")).strip()
            name = str(item.get("f14", "")).strip()
            raw_market = item.get("f13")
            industry = str(item.get("f100", "")).strip()

            # Map Eastmoney market codes to our internal market codes.
            if raw_market == 0 or raw_market == "0":
                market = "SZ"
            elif raw_market == 1 or raw_market == "1":
                market = "SH"
            elif raw_market == 128 or raw_market == "128":
                market = "HK"
            else:
                market = _infer_market(code)

            if code and industry and industry != "-":
                rows.append(
                    {
                        "asset_code": code,
                        "asset_name": name,
                        "market": market,
                        "industry_name": industry,
                    }
                )

        if page * page_size >= total:
            break
        page += 1

    return pd.DataFrame(rows)


def fetch_industry_mapping(
    use_cache: bool = True,
    save_cache: bool = True,
    include_hk: bool = True,
) -> IndustryMapping:
    """Fetch A-share and HK stock industry mappings from Eastmoney.

    Args:
        use_cache: Load from local cache if available.
        save_cache: Save fetched mapping to local cache.
        include_hk: Whether to fetch HK stock mappings.

    Returns:
        IndustryMapping object keyed by (asset_code, market).
    """
    if use_cache:
        cached = load_industry_mapping_from_cache()
        if cached is not None:
            return cached

    # A-shares: 沪市主板/科创板 + 深市主板/创业板/北交所
    a_share_fs = "m:0+t:6,m:0+t:80,m:0+t:81,m:1+t:2,m:1+t:23"
    df_a = _fetch_eastmoney_list(a_share_fs)

    if include_hk:
        try:
            hk_fs = "m:128+t:3,m:128+t:4,m:128+t:5,m:128+t:6,m:128+t:7"
            df_hk = _fetch_eastmoney_list(hk_fs)
            df = pd.concat([df_a, df_hk], ignore_index=True)
        except Exception:
            df = df_a
    else:
        df = df_a

    mapping: dict[tuple[str, str], str] = {}
    for _, row in df.iterrows():
        mapping[(row["asset_code"], row["market"])] = row["industry_name"]
        # Also index by inferred market for robust lookup.
        inferred = _infer_market(row["asset_code"])
        if inferred != row["market"]:
            mapping[(row["asset_code"], inferred)] = row["industry_name"]

    result = IndustryMapping(mapping)
    if save_cache:
        try:
            save_industry_mapping_to_cache(result)
        except Exception:
            pass
    return result


def update_security_industries(
    mapping: IndustryMapping | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Update holding_security_info.industry_name for all records.

    Args:
        mapping: Optional pre-built mapping. If None, fetch from Eastmoney.
        dry_run: If True, only count updates without writing.

    Returns:
        Dict with counts: total, updated, unchanged, missing.
    """
    if mapping is None:
        mapping = fetch_industry_mapping()

    Session = get_session_maker()
    stats = {"total": 0, "updated": 0, "unchanged": 0, "missing": 0}

    with Session() as session:
        stmt = select(HoldingSecurityInfo)
        records = session.scalars(stmt).all()

        for record in records:
            stats["total"] += 1
            code = record.asset_code
            market = record.market or _infer_market(code)

            # Try exact (code, market) match first, then fallback to code only.
            industry = mapping.get(code, market)
            if industry is None:
                industry = mapping.get(code, _infer_market(code))
            if industry is None:
                # Some HK stocks may use 5-digit code without leading zero.
                if market == "HK" and len(code) == 4:
                    industry = mapping.get("0" + code, "HK")
                if industry is None:
                    stats["missing"] += 1
                    continue

            if record.industry_name != industry:
                if not dry_run:
                    record.industry_name = industry
                    record.updated_at = datetime.utcnow()
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1

        if not dry_run:
            session.commit()

    return stats


def build_industry_weights(
    holdings_df: pd.DataFrame,
    mapping: IndustryMapping | None = None,
) -> pd.DataFrame:
    """Aggregate stock weights into industry weights.

    Args:
        holdings_df: DataFrame with columns product_id, asset_code, market, weight.
        mapping: Industry mapping. If None, fetch from Eastmoney.

    Returns:
        DataFrame with columns product_id, industry_name, weight (sum of stock
        weights belonging to the industry).
    """
    if mapping is None:
        mapping = fetch_industry_mapping()

    df = holdings_df.copy()
    df["market"] = df["market"].fillna(
        df["asset_code"].apply(_infer_market)
    )
    df["industry_name"] = df.apply(
        lambda r: mapping.get(r["asset_code"], r["market"]) or "未知行业",
        axis=1,
    )

    return (
        df.groupby(["product_id", "industry_name"], as_index=False)["weight"]
        .sum()
        .sort_values(["product_id", "weight"], ascending=[True, False])
    )
