"""Core database table definitions."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BIGINT,
    Boolean,
    Date,
    DateTime,
    DECIMAL,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""


class ProductInfo(Base):
    """Product basic information (daily snapshot)."""

    __tablename__ = "product_info"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    institution_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="机构类型: fund_company / bank_wm"
    )
    institution_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="机构名称"
    )
    institution_code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="机构代码, 如 YFD/HTF/ZY/JX"
    )
    product_code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="产品唯一代码"
    )
    product_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="产品全称"
    )
    product_short_name: Mapped[str | None] = mapped_column(
        String(100), comment="产品简称"
    )
    product_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="统一类型: equity/mixed/fixed_income/..."
    )
    product_sub_type: Mapped[str | None] = mapped_column(
        String(50), comment="产品子类型"
    )
    registration_code: Mapped[str | None] = mapped_column(
        String(50), comment="银行理财登记编码"
    )
    sales_code: Mapped[str | None] = mapped_column(
        String(50), comment="银行理财销售代码"
    )
    establish_date: Mapped[datetime | None] = mapped_column(Date, comment="成立日期")
    maturity_date: Mapped[datetime | None] = mapped_column(Date, comment="到期日期")
    risk_level: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="原始风险等级"
    )
    risk_level_standard: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="统一风险等级 L1-L5"
    )
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, default="CNY", comment="币种"
    )
    manager: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="管理人"
    )
    custodian: Mapped[str | None] = mapped_column(String(100), comment="托管人")
    fund_manager: Mapped[str | None] = mapped_column(
        String(100), comment="基金经理/投资经理"
    )
    investment_target: Mapped[str | None] = mapped_column(Text, comment="投资目标")
    investment_scope: Mapped[str | None] = mapped_column(Text, comment="投资范围")
    investment_strategy: Mapped[str | None] = mapped_column(Text, comment="投资策略")
    performance_benchmark: Mapped[str | None] = mapped_column(
        String(500), comment="业绩比较基准"
    )
    benchmark_type: Mapped[str | None] = mapped_column(
        String(20), comment="基准类型: index_composite/yield_range/..."
    )
    min_purchase_amount: Mapped[float | None] = mapped_column(
        DECIMAL(18, 4), comment="最低购买金额"
    )
    min_additional_amount: Mapped[float | None] = mapped_column(
        DECIMAL(18, 4), comment="最低追加金额"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", comment="产品状态"
    )
    data_source: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="数据来源URL"
    )
    collect_date: Mapped[datetime] = mapped_column(
        Date, nullable=False, comment="数据采集日期"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, comment="记录创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="记录更新时间",
    )

    nav_records: Mapped[list["ProductNav"]] = relationship(
        "ProductNav", back_populates="product", cascade="all, delete-orphan"
    )
    return_records: Mapped[list["ProductReturn"]] = relationship(
        "ProductReturn", back_populates="product", cascade="all, delete-orphan"
    )
    fee_records: Mapped[list["ProductFee"]] = relationship(
        "ProductFee", back_populates="product", cascade="all, delete-orphan"
    )
    holding_reports: Mapped[list["HoldingReport"]] = relationship(
        "HoldingReport", back_populates="product", cascade="all, delete-orphan"
    )
    asset_allocations: Mapped[list["ProductAssetAllocation"]] = relationship(
        "ProductAssetAllocation", back_populates="product", cascade="all, delete-orphan"
    )
    holding_summaries: Mapped[list["ProductHoldingSummary"]] = relationship(
        "ProductHoldingSummary", back_populates="product", cascade="all, delete-orphan"
    )
    style_tags: Mapped[list["ProductManagerStyle"]] = relationship(
        "ProductManagerStyle", back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_code",
            "product_code",
            "collect_date",
            name="uix_product_snapshot",
        ),
        Index("ix_product_info_institution", "institution_code"),
        Index("ix_product_info_type", "product_type"),
        Index("ix_product_info_risk", "risk_level_standard"),
        Index("ix_product_info_collect_date", "collect_date"),
    )


class ProductNav(Base):
    """Product net asset value (time-series)."""

    __tablename__ = "product_nav"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    nav_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment="净值日期")
    unit_nav: Mapped[float] = mapped_column(
        DECIMAL(18, 6), nullable=False, comment="单位净值"
    )
    cumulative_nav: Mapped[float | None] = mapped_column(
        DECIMAL(18, 6), comment="累计净值"
    )
    daily_return: Mapped[float | None] = mapped_column(
        DECIMAL(10, 6), comment="日收益率"
    )
    nav_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal", comment="净值类型"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    product: Mapped["ProductInfo"] = relationship("ProductInfo", back_populates="nav_records")

    __table_args__ = (
        UniqueConstraint("product_id", "nav_date", name="uix_product_nav"),
        Index("ix_product_nav_date", "nav_date"),
    )


class ProductReturn(Base):
    """Product return rates for various periods."""

    __tablename__ = "product_return"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    return_period: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="收益周期: 1m/3m/6m/1y/ytd/since_inception"
    )
    return_value: Mapped[float] = mapped_column(
        DECIMAL(10, 6), nullable=False, comment="收益率值"
    )
    return_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="cumulative", comment="收益类型"
    )
    calc_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment="计算日期")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    product: Mapped["ProductInfo"] = relationship(
        "ProductInfo", back_populates="return_records"
    )

    __table_args__ = (
        UniqueConstraint(
            "product_id", "return_period", "calc_date", name="uix_product_return"
        ),
        Index("ix_product_return_period", "return_period"),
        Index("ix_product_return_calc_date", "calc_date"),
    )


class ProductFee(Base):
    """Product fee structure (versioned)."""

    __tablename__ = "product_fee"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    fee_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="费用类型: management_fee/custody_fee/..."
    )
    fee_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="费用名称")
    fee_rate: Mapped[float | None] = mapped_column(
        DECIMAL(10, 6), comment="费率(年化或单次)"
    )
    fee_calc_method: Mapped[str | None] = mapped_column(
        String(50), comment="计费方式: annual/one_time/tiered"
    )
    fee_details: Mapped[str | None] = mapped_column(Text, comment="费率详情(JSON)")
    effective_date: Mapped[datetime | None] = mapped_column(Date, comment="费率生效日期")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    product: Mapped["ProductInfo"] = relationship("ProductInfo", back_populates="fee_records")

    __table_args__ = (
        Index("ix_product_fee_type", "fee_type"),
        Index("ix_product_fee_effective_date", "effective_date"),
    )


class CollectionLog(Base):
    """Collection job execution log."""

    __tablename__ = "collection_log"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="任务名称")
    institution_code: Mapped[str | None] = mapped_column(
        String(20), comment="机构代码"
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime, comment="开始时间")
    end_time: Mapped[datetime | None] = mapped_column(DateTime, comment="结束时间")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", comment="状态"
    )
    records_count: Mapped[int | None] = mapped_column(Integer, comment="采集记录数")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误信息")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_collection_log_job", "job_name"),
        Index("ix_collection_log_status", "status"),
        Index("ix_collection_log_created_at", "created_at"),
    )


class MarketQuote(Base):
    """Daily market quote for major global indices and commodities."""

    __tablename__ = "market_quote"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    quote_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="行情日期"
    )
    symbol_code: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="内部统一代码, 如 SH000001 / DJIA / GOLD"
    )
    symbol_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="指数/品种名称"
    )
    market_region: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="市场区域: domestic/us/hk/commodity"
    )
    asset_class: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="资产类别: index/commodity"
    )
    open_price: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="开盘价"
    )
    high_price: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="最高价"
    )
    low_price: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="最低价"
    )
    close_price: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="收盘价/最新价"
    )
    prev_close: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="昨收/昨结算价"
    )
    change_amount: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="涨跌额"
    )
    change_pct: Mapped[float | None] = mapped_column(
        Numeric(10, 4), comment="涨跌幅(%)"
    )
    volume: Mapped[int | None] = mapped_column(BIGINT, comment="成交量")
    volume_unit: Mapped[str | None] = mapped_column(
        String(10), default="lot", comment="成交量单位: lot/share/contract"
    )
    amount: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="成交额"
    )
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, default="CNY", comment="币种"
    )
    data_source: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="数据来源URL"
    )
    source_code: Mapped[str | None] = mapped_column(
        String(50), comment="数据源原始代码"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("quote_date", "symbol_code", name="uix_market_quote"),
        Index("ix_market_quote_date", "quote_date"),
        Index("ix_market_quote_region", "market_region"),
        Index("ix_market_quote_asset_class", "asset_class"),
        # Composite index for the /market dashboard batch query, which filters
        # by asset_class + symbol_code IN (...) + quote_date <= end_date and
        # orders by quote_date DESC. Created alongside the model so fresh
        # databases pick it up automatically; existing databases apply it
        # via scripts/migrate_market_quote_index.py.
        Index(
            "ix_market_quote_asset_class_date_symbol",
            "asset_class",
            "quote_date",
            "symbol_code",
        ),
    )


class HoldingReport(Base):
    """A holding report period for a product (quarterly/annual)."""

    __tablename__ = "holding_report"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    report_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="quarterly", comment="报告类型: quarterly/annual/interim"
    )
    report_period: Mapped[str | None] = mapped_column(
        String(20), comment="报告期描述, 如 2024年4季度"
    )
    data_source: Mapped[str] = mapped_column(String(500), nullable=False, comment="数据来源URL")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    product: Mapped["ProductInfo"] = relationship("ProductInfo", back_populates="holding_reports")
    holdings: Mapped[list["ProductHolding"]] = relationship(
        "ProductHolding", back_populates="report", cascade="all, delete-orphan"
    )
    asset_allocations: Mapped[list["ProductAssetAllocation"]] = relationship(
        "ProductAssetAllocation", back_populates="report", cascade="all, delete-orphan"
    )
    summary: Mapped["ProductHoldingSummary"] = relationship(
        "ProductHoldingSummary", back_populates="report", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("product_id", "report_date", "report_type", name="uix_holding_report"),
        Index("ix_holding_report_date", "report_date"),
        Index("ix_holding_report_type", "report_type"),
    )


class ProductHolding(Base):
    """Individual holding position within a product report."""

    __tablename__ = "product_holding"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("holding_report.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    asset_code: Mapped[str | None] = mapped_column(
        String(50), comment="资产代码, 如股票代码/债券代码"
    )
    asset_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="资产名称")
    asset_type: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="资产类型: stock/bond/fund/cash/deposit/derivative/other"
    )
    sub_type: Mapped[str | None] = mapped_column(
        String(50), comment="子类型, 如 A股/港股/国债/企业债/ETF"
    )
    market: Mapped[str | None] = mapped_column(
        String(20), comment="市场: SH/SZ/HK/US/CN_INTERBANK/OTC/UNKNOWN"
    )
    issuer_name: Mapped[str | None] = mapped_column(String(200), comment="发行人/上市公司名称")
    industry_code: Mapped[str | None] = mapped_column(String(20), comment="行业代码")
    industry_name: Mapped[str | None] = mapped_column(String(100), comment="行业名称")
    weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="占净值比例(小数, 如 0.085 表示 8.5%)"
    )
    market_value: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="持仓市值(万元或元, 与数据源保持一致)"
    )
    share_quantity: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="持仓数量(万股/万份/张)"
    )
    cost_basis: Mapped[float | None] = mapped_column(
        Numeric(18, 6), comment="成本价/成本(可选)"
    )
    valuation_method: Mapped[str | None] = mapped_column(
        String(50), comment="估值方法: market_value/amortized_cost/other"
    )
    is_top10: Mapped[bool | None] = mapped_column(
        Boolean, default=False, comment="是否前十大持仓"
    )
    sort_order: Mapped[int | None] = mapped_column(
        Integer, comment="持仓排名"
    )
    raw_data: Mapped[str | None] = mapped_column(
        Text, comment="原始数据(JSON)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    report: Mapped["HoldingReport"] = relationship("HoldingReport", back_populates="holdings")
    product: Mapped["ProductInfo"] = relationship("ProductInfo")

    __table_args__ = (
        UniqueConstraint(
            "report_id", "asset_code", "asset_name", name="uix_product_holding"
        ),
        Index("ix_product_holding_asset_type", "asset_type"),
        Index("ix_product_holding_industry", "industry_name"),
        Index("ix_product_holding_issuer", "issuer_name"),
        Index("ix_product_holding_top10", "is_top10"),
    )


class ProductAssetAllocation(Base):
    """High-level asset allocation snapshot from a product report."""

    __tablename__ = "product_asset_allocation"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("holding_report.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    asset_class: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="资产类别: stock/bond/cash/fund/derivative/non_standard/other"
    )
    weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="占比(小数)"
    )
    market_value: Mapped[float | None] = mapped_column(
        Numeric(18, 4), comment="市值"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    report: Mapped["HoldingReport"] = relationship(
        "HoldingReport", back_populates="asset_allocations"
    )
    product: Mapped["ProductInfo"] = relationship("ProductInfo", back_populates="asset_allocations")

    __table_args__ = (
        UniqueConstraint(
            "report_id", "asset_class", name="uix_product_asset_allocation"
        ),
        Index("ix_asset_allocation_class", "asset_class"),
    )


class HoldingSecurityInfo(Base):
    """Reference table for securities encountered in holdings."""

    __tablename__ = "holding_security_info"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    asset_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="资产代码")
    market: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNKNOWN", comment="市场"
    )
    asset_name: Mapped[str | None] = mapped_column(String(200), comment="资产名称")
    asset_type: Mapped[str | None] = mapped_column(String(30), comment="资产类型")
    exchange: Mapped[str | None] = mapped_column(String(20), comment="交易所")
    industry_code: Mapped[str | None] = mapped_column(String(20), comment="行业代码")
    industry_name: Mapped[str | None] = mapped_column(String(100), comment="行业名称")
    issuer_name: Mapped[str | None] = mapped_column(String(200), comment="发行人")
    listing_date: Mapped[date | None] = mapped_column(Date, comment="上市日期")
    status: Mapped[str | None] = mapped_column(
        String(20), default="active", comment="状态: active/inactive/delisted"
    )
    extra: Mapped[str | None] = mapped_column(Text, comment="扩展信息(JSON)")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("asset_code", "market", name="uix_holding_security"),
        Index("ix_holding_security_industry", "industry_name"),
        Index("ix_holding_security_issuer", "issuer_name"),
    )


class ProductHoldingSummary(Base):
    """Derived summary metrics for a product holding report."""

    __tablename__ = "product_holding_summary"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("holding_report.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    top10_weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="前十大持仓占净值比"
    )
    stock_weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="股票占比"
    )
    bond_weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="债券占比"
    )
    cash_weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="现金及存款占比"
    )
    fund_weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="基金占比"
    )
    derivative_weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="衍生品占比"
    )
    non_standard_weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="非标债权占比"
    )
    other_weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="其他资产占比"
    )
    concentration_score: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="集中度得分(如 HHI)"
    )
    holding_count: Mapped[int | None] = mapped_column(
        Integer, comment="披露持仓总数"
    )
    turnover_indicator: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="换手率估算(可选)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    report: Mapped["HoldingReport"] = relationship(
        "HoldingReport", back_populates="summary"
    )
    product: Mapped["ProductInfo"] = relationship("ProductInfo", back_populates="holding_summaries")

    __table_args__ = (
        UniqueConstraint("product_id", "report_date", name="uix_product_holding_summary"),
    )


class ProductManagerStyle(Base):
    """Style tags for a product/manager derived from holdings."""

    __tablename__ = "product_manager_style"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    dimension: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="维度: sector/value_growth/cap/esg/concentration/turnover"
    )
    tag: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="标签值, 如 科技/价值/大盘/高ESG/高集中度"
    )
    score: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="评分或占比"
    )
    source: Mapped[str | None] = mapped_column(
        String(100), comment="计算来源/算法版本"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    product: Mapped["ProductInfo"] = relationship("ProductInfo", back_populates="style_tags")

    __table_args__ = (
        UniqueConstraint(
            "product_id", "report_date", "dimension", "tag", name="uix_product_manager_style"
        ),
        Index("ix_product_style_dimension", "dimension"),
        Index("ix_product_style_tag", "tag"),
    )


class SimilarityClusterRun(Base):
    """A single clustering run (batch) for a holding report cross-section."""

    __tablename__ = "similarity_cluster_run"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    product_type_filter: Mapped[str | None] = mapped_column(
        String(100), comment="参与聚类的产品类型过滤, 如 equity,mixed"
    )
    algorithm: Mapped[str] = mapped_column(
        String(30), nullable=False, default="kmeans", comment="聚类算法"
    )
    k: Mapped[int] = mapped_column(Integer, nullable=False, comment="聚类数")
    params_json: Mapped[Any | None] = mapped_column(
        JSONB, comment="运行参数(JSON), 用于结果复现"
    )
    silhouette: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="轮廓系数"
    )
    inertia: Mapped[float | None] = mapped_column(
        Numeric(20, 6), comment="SSE"
    )
    n_products: Mapped[int | None] = mapped_column(
        Integer, comment="参与产品数"
    )
    n_features: Mapped[int | None] = mapped_column(
        Integer, comment="特征维度数"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="full",
        comment="运行模式: full(全量) / incremental(增量)",
    )
    baseline_run_id: Mapped[int | None] = mapped_column(
        BIGINT,
        ForeignKey("similarity_cluster_run.id"),
        nullable=True,
        comment="增量运行时依赖的基线运行 ID",
    )

    __table_args__ = (
        UniqueConstraint(
            "report_date", "algorithm", "k", "product_type_filter", "created_at",
            name="uix_similarity_cluster_run"
        ),
        Index("ix_similarity_cluster_run_date", "report_date"),
        Index("ix_similarity_cluster_run_algo", "algorithm"),
        Index("ix_similarity_cluster_run_baseline", "baseline_run_id"),
    )


class SimilarityClusterBaseline(Base):
    """Baseline centroid / K information for incremental clustering."""

    __tablename__ = "similarity_cluster_baseline"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    cluster_run_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("similarity_cluster_run.id", ondelete="CASCADE"),
        nullable=False,
        comment="基线运行 ID",
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    product_type_filter: Mapped[str | None] = mapped_column(
        String(100), comment="参与聚类的产品类型过滤, 如 equity,mixed"
    )
    algorithm: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="聚类算法标识"
    )
    k: Mapped[int] = mapped_column(Integer, nullable=False, comment="基线 K 值")
    feature_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="特征类型: asset / industry"
    )
    feature_names: Mapped[Any] = mapped_column(
        JSONB, nullable=False, comment="基线特征维度列表"
    )
    centroids: Mapped[Any] = mapped_column(
        JSONB, nullable=False, comment="基线质心矩阵 (k × n_features)"
    )
    silhouette: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="基线 silhouette"
    )
    inertia: Mapped[float | None] = mapped_column(
        Numeric(20, 6), comment="基线 inertia"
    )
    n_products: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="基线参与产品数"
    )
    k_search_results: Mapped[Any | None] = mapped_column(
        JSONB, comment="K 搜索过程 [{k, silhouette, inertia}, ...]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "report_date", "product_type_filter", "algorithm",
            name="uix_similarity_cluster_baseline"
        ),
        Index("ix_similarity_cluster_baseline_run", "cluster_run_id"),
        Index("ix_similarity_cluster_baseline_lookup", "report_date", "product_type_filter", "algorithm"),
    )


class SimilarityCluster(Base):
    """Clustering result for a holding report cross-section."""

    __tablename__ = "similarity_clusters"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    cluster_run_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("similarity_cluster_run.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属聚类运行批次"
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    product_type_filter: Mapped[str | None] = mapped_column(
        String(100), comment="参与聚类的产品类型过滤, 如 equity,mixed"
    )
    algorithm: Mapped[str] = mapped_column(
        String(30), nullable=False, default="kmeans", comment="聚类算法"
    )
    k: Mapped[int] = mapped_column(Integer, nullable=False, comment="聚类数")
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="簇编号")
    cluster_label: Mapped[str | None] = mapped_column(
        String(100), comment="簇标签, 如 光通信主题"
    )
    size: Mapped[int] = mapped_column(Integer, nullable=False, comment="簇内产品数")
    top_industries: Mapped[Any | None] = mapped_column(
        JSONB, comment="Top 行业及权重(JSON)"
    )
    top_holdings: Mapped[Any | None] = mapped_column(
        JSONB, comment="Top 重仓股及权重(JSON)"
    )
    avg_hhi: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="簇内平均 HHI 集中度"
    )
    avg_overlap: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="簇内平均 pairwise overlap (基于 L2 归一化向量)"
    )
    avg_overlap_raw: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="簇内平均 pairwise overlap (基于原始权重)"
    )
    ac_share_dominance_ratio: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="簇内 AC 份额合并占比"
    )
    institution_distribution: Mapped[Any | None] = mapped_column(
        JSONB, comment="机构分布(JSON)"
    )
    representative_products: Mapped[Any | None] = mapped_column(
        JSONB, comment="代表产品 ID 列表(JSON)"
    )
    representative_codes: Mapped[Any | None] = mapped_column(
        JSONB, comment="代表产品代码列表(JSON)"
    )
    representative_names: Mapped[Any | None] = mapped_column(
        JSONB, comment="代表产品名称列表(JSON)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "cluster_run_id", "cluster_id",
            name="uix_similarity_cluster_run_cluster"
        ),
        Index("ix_similarity_clusters_run_id", "cluster_run_id"),
        Index("ix_similarity_clusters_date", "report_date"),
        Index("ix_similarity_clusters_k", "k"),
    )


class SimilarityClusterMember(Base):
    """Membership of a product in a cluster run."""

    __tablename__ = "similarity_cluster_members"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    cluster_run_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("similarity_cluster_run.id", ondelete="CASCADE"),
        nullable=False,
        comment="聚类运行标识(对应 similarity_cluster_run.id)"
    )
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="簇编号")
    distance_to_center: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="到簇中心的距离"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    product: Mapped["ProductInfo"] = relationship("ProductInfo")

    __table_args__ = (
        UniqueConstraint(
            "report_date", "product_id", "cluster_run_id",
            name="uix_similarity_cluster_members"
        ),
        Index("ix_similarity_members_run", "cluster_run_id"),
        Index("ix_similarity_members_product", "product_id"),
        Index("ix_similarity_members_cluster", "cluster_id"),
    )


class IndexConstituentWeight(Base):
    """Index constituent weights from CSI/SSE/SZSE official files."""

    __tablename__ = "index_constituent_weight"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    index_code: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="指数代码, 如 000300 / 000906"
    )
    index_name: Mapped[str | None] = mapped_column(String(100), comment="指数名称")
    constituent_code: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="成分券代码"
    )
    constituent_name: Mapped[str | None] = mapped_column(String(100), comment="成分券名称")
    market: Mapped[str | None] = mapped_column(String(10), comment="市场: SH / SZ")
    weight: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="权重(小数, 如 0.00345)"
    )
    effective_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="权重生效日"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "index_code", "constituent_code", "effective_date",
            name="uix_index_constituent_weight"
        ),
        Index("ix_index_weight_code", "index_code"),
        Index("ix_index_weight_date", "effective_date"),
    )


class SimilarityAttribution(Base):
    """Brinson attribution result for a product within a cluster run."""

    __tablename__ = "similarity_attribution"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("product_info.id", ondelete="CASCADE"), nullable=False
    )
    cluster_run_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("similarity_cluster_run.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属聚类运行批次"
    )
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="簇编号")
    report_date: Mapped[date] = mapped_column(Date, nullable=False, comment="报告期截止日")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="归因起始日")
    end_date: Mapped[date] = mapped_column(Date, nullable=False, comment="归因截止日")
    benchmark_type: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="基准类型: cluster_avg / index"
    )
    benchmark_code: Mapped[str | None] = mapped_column(
        String(30), comment="指数基准代码(如 SH000300)"
    )
    total_return: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="组合区间收益"
    )
    benchmark_return: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="基准区间收益"
    )
    excess_return: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="超额收益"
    )
    allocation_effect: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="配置贡献(行业权重差异)"
    )
    selection_effect: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="选股贡献(行业内个股差异)"
    )
    interaction_effect: Mapped[float | None] = mapped_column(
        Numeric(10, 6), comment="交互贡献"
    )
    rank_in_cluster: Mapped[int | None] = mapped_column(
        Integer, comment="同簇超额收益排名"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    product: Mapped["ProductInfo"] = relationship("ProductInfo")

    __table_args__ = (
        UniqueConstraint(
            "product_id", "cluster_run_id", "start_date", "end_date", "benchmark_type",
            name="uix_similarity_attribution"
        ),
        Index("ix_similarity_attribution_run", "cluster_run_id"),
        Index("ix_similarity_attribution_product", "product_id"),
    )
