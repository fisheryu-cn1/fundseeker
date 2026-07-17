"""Index constituent weight fetching and storage.

Data source: 中证指数有限公司 official XLS files, e.g.
https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/closeweight/000300closeweight.xls

Weights are published after market close and represent the latest official
constituent weights.  We store them in ``index_constituent_weight`` so the
attribution layer can use them as a benchmark.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import pandas as pd
import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fundseeker.models.database import get_session_maker
from fundseeker.models.tables import IndexConstituentWeight


_CSINDEX_WEIGHT_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/"
    "public/uploads/file/autofile/closeweight/{index_code}closeweight.xls"
)

# Map exchange names in the XLS to internal market codes.
_EXCHANGE_MAP = {
    "上海证券交易所": "SH",
    "深圳证券交易所": "SZ",
    "北京证券交易所": "BJ",
}


_SUPPORTED_INDEX_CODES = {
    "000300": "沪深300",
    "000906": "中证800",
}


def fetch_index_weights(index_code: str) -> pd.DataFrame:
    """Fetch the latest constituent weights for a CSI index.

    Args:
        index_code: Index code such as ``000300`` or ``000906``.

    Returns:
        DataFrame with columns:
        index_code, index_name, constituent_code, constituent_name, market,
        weight, effective_date.
    """
    url = _CSINDEX_WEIGHT_URL.format(index_code=index_code)
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    df = pd.read_excel(BytesIO(response.content))
    # The XLS header is bilingual; select columns by position to stay robust.
    columns = df.columns.tolist()
    if len(columns) < 10:
        raise ValueError(f"Unexpected CSI weight file format for {index_code}")

    df = df.iloc[:, [0, 1, 2, 4, 5, 7, 9]].copy()
    df.columns = [
        "effective_date",
        "index_code",
        "index_name",
        "constituent_code",
        "constituent_name",
        "exchange",
        "weight_pct",
    ]

    df["effective_date"] = pd.to_datetime(
        df["effective_date"], format="%Y%m%d", errors="coerce"
    ).dt.date
    df["index_code"] = df["index_code"].astype(str).str.strip().str.zfill(6)
    df["constituent_code"] = df["constituent_code"].astype(str).str.strip().str.zfill(6)
    df["weight"] = pd.to_numeric(df["weight_pct"], errors="coerce") / 100.0
    df["market"] = df["exchange"].map(_EXCHANGE_MAP).fillna(
        df["exchange"].apply(lambda x: _guess_market(str(x)))
    )

    index_name = _SUPPORTED_INDEX_CODES.get(index_code) or str(
        df["index_name"].dropna().iloc[0]
    )
    df["index_name"] = index_name

    return df[
        [
            "index_code",
            "index_name",
            "constituent_code",
            "constituent_name",
            "market",
            "weight",
            "effective_date",
        ]
    ]


def _guess_market(exchange: str) -> str:
    if "上海" in exchange:
        return "SH"
    if "深圳" in exchange:
        return "SZ"
    if "北京" in exchange:
        return "BJ"
    return "UNKNOWN"


def refresh_index_weights(
    index_codes: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch and persist index constituent weights.

    Args:
        index_codes: List of CSI index codes. Defaults to CSI 300 and CSI 800.
        dry_run: If True, only count without writing.

    Returns:
        Dict with counts per index_code.
    """
    if index_codes is None:
        index_codes = ["000300", "000906"]

    stats: dict[str, Any] = {"indices": {}}
    Session = get_session_maker()

    with Session() as session:
        for code in index_codes:
            df = fetch_index_weights(code)
            if df.empty:
                stats["indices"][code] = {"rows": 0}
                continue

            records = df.to_dict("records")
            if not dry_run:
                for record in records:
                    stmt = pg_insert(IndexConstituentWeight).values(**record)
                    update_dict = {
                        c.name: stmt.excluded[c.name]
                        for c in IndexConstituentWeight.__table__.columns
                        if c.name
                        not in ("id", "index_code", "constituent_code", "effective_date", "created_at")
                    }
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[
                            "index_code",
                            "constituent_code",
                            "effective_date",
                        ],
                        set_=update_dict,
                    )
                    session.execute(stmt)
                session.commit()

            stats["indices"][code] = {
                "rows": len(records),
                "effective_date": str(df["effective_date"].iloc[0]),
            }

    return stats


def load_index_weights(index_code: str, effective_date: date | None = None) -> pd.DataFrame:
    """Load stored index weights from the database.

    Args:
        index_code: Index code.
        effective_date: Specific effective date. If None, the latest available
            date is used.

    Returns:
        DataFrame with the same columns as ``fetch_index_weights``.
    """
    Session = get_session_maker()
    with Session() as session:
        query = select(IndexConstituentWeight).where(
            IndexConstituentWeight.index_code == index_code
        )
        if effective_date is not None:
            query = query.where(
                IndexConstituentWeight.effective_date == effective_date
            )
        else:
            query = query.order_by(IndexConstituentWeight.effective_date.desc())

        rows = session.scalars(query).all()
        if not rows:
            raise ValueError(f"No weights found for index {index_code}")

        if effective_date is None:
            latest_date = rows[0].effective_date
            rows = [r for r in rows if r.effective_date == latest_date]

        return pd.DataFrame(
            [
                {
                    "index_code": r.index_code,
                    "index_name": r.index_name,
                    "constituent_code": r.constituent_code,
                    "constituent_name": r.constituent_name,
                    "market": r.market,
                    "weight": r.weight,
                    "effective_date": r.effective_date,
                }
                for r in rows
            ]
        )
