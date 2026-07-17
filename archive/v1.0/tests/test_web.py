"""Smoke tests for the Flask read-only Web UI."""

from __future__ import annotations

import pytest

from fundseeker.web.app import create_app
from fundseeker.web import queries


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_search_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "产品检索" in resp.text


def test_dashboard_page(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "数据概览" in resp.text


def test_market_page(client):
    resp = client.get("/market")
    assert resp.status_code == 200
    assert "市场行情" in resp.text


def test_similarity_index_page(client):
    resp = client.get("/similarity")
    assert resp.status_code == 200
    assert "相似度分析" in resp.text


def test_product_detail_not_found(client):
    resp = client.get("/product/999999999")
    assert resp.status_code == 404
    assert "未找到" in resp.text


def test_similarity_run_not_found(client):
    resp = client.get("/similarity/999999999")
    assert resp.status_code == 404


def test_api_dashboard_summary(client):
    resp = client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "product_total" in data
    assert "holding_total" in data


def test_api_products(client):
    resp = client.get("/api/products?page=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "total" in data
    assert "pages" in data


def test_api_market_quotes(client):
    resp = client.get("/api/market/quotes")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "count" in data


def test_api_similarity_runs(client):
    resp = client.get("/api/similarity/runs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "total" in data


def test_nav_aggregated_by_product_code():
    """NAV records for a logical product should be aggregated across snapshots."""
    # Find a product with multiple snapshots.
    items, _ = queries.list_products(page=1, page_size=1)
    assert items
    product = items[0]
    per_id = queries.list_nav(product.id, limit=50)
    per_code = queries.list_nav_by_product_code(
        product.institution_code, product.product_code, limit=50
    )
    # The aggregated view should have at least as many records as any single snapshot.
    assert len(per_code) >= len(per_id)


def test_holding_reports_deduplicated_by_product_code():
    """Holding reports should be deduplicated by report_date across snapshots."""
    items, _ = queries.list_products(page=1, page_size=1)
    assert items
    product = items[0]
    reports = queries.list_holding_reports_by_product_code(
        product.institution_code, product.product_code
    )
    dates = [r.report_date for r in reports]
    assert len(dates) == len(set(dates)), "report_date should be unique"


def test_similarity_run_detail_page(client):
    """The run detail page should render the cluster overview table."""
    runs = queries.list_similarity_runs(limit=1)
    if not runs:
        pytest.skip("no similarity runs available")
    run_id = runs[0].cluster_run_id
    resp = client.get(f"/similarity/{run_id}")
    assert resp.status_code == 200
    assert "簇概览" in resp.text


def test_cluster_run_period_changes():
    """Batch cluster period-change helper should return a value per cluster."""
    runs = queries.list_similarity_runs(limit=1)
    if not runs:
        pytest.skip("no similarity runs available")
    run_id = runs[0].cluster_run_id
    detail = queries.get_similarity_run_by_id(run_id)
    changes = queries.cluster_run_period_changes(run_id, days=60)
    assert isinstance(changes, dict)
    for cluster in detail.clusters:
        assert cluster.cluster_id in changes
