"""
Unit and Integration tests for HTML Report Generator & Azure OpenAI Client.
"""

import os
import pytest
from backend.parser import RDLParser
from backend.analyzer import RecommendationEngine
from backend.html_report_generator import generate_html_report, generate_unique_report_id
from backend.azure_llm import AzureOpenAIService
from backend.main import export_html_report_endpoint

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_reports")


def test_unique_report_id_format():
    rpt_id = generate_unique_report_id()
    assert rpt_id.startswith("RPT-")
    assert len(rpt_id) >= 15


def test_azure_llm_service_fallback():
    # Test service when no credentials provided (fallback mode)
    llm = AzureOpenAIService(endpoint="", api_key="")
    assert not llm.is_available()
    
    summary = llm.generate_executive_assessment(
        report_name="TestReport",
        health_score=40,
        health_status="Critical Bottlenecks Detected",
        metrics={"total_datasets": 2, "total_queries": 2, "unused_fields_count": 8},
        issues=[{"severity": "High", "target_object": "SalesDataset", "title": "SELECT *"}],
    )
    assert "TestReport" in summary
    assert "bottlenecks" in summary.lower()


def test_html_report_generation_sample1():
    parser = RDLParser()
    engine = RecommendationEngine()
    p = os.path.join(SAMPLES_DIR, "sample1_sql_bottlenecks.rdl")
    parsed = parser.parse_file(p)
    res = engine.compile_report(parsed)

    issues_dict = [
        {
            "id": i.id,
            "category": i.category.value,
            "severity": i.severity.value,
            "classification": i.classification.value,
            "title": i.title,
            "target_object": i.target_object,
            "description": i.description,
            "impact": i.impact,
            "remediation": i.remediation,
            "code_snippet": i.code_snippet,
            "suggested_fix": i.suggested_fix,
        }
        for i in res.issues
    ]
    opts_dict = {
        k: {
            "dataset_name": v.dataset_name,
            "original_query": v.original_query,
            "suggested_query": v.suggested_query,
            "optimization_reasons": v.optimization_reasons,
            "fields_used": v.fields_used,
            "fields_pruned": v.fields_pruned,
        }
        for k, v in res.dataset_optimizations.items()
    }

    data = {
        "report_name": res.report_name,
        "health_score": res.health_score,
        "health_status": res.health_status,
        "summary_metrics": res.summary_metrics,
        "issues": issues_dict,
        "dataset_optimizations": opts_dict,
        "field_usage_matrix": res.field_usage_matrix,
    }

    html = generate_html_report(data, parsed_rdl=parsed)

    # 1. Check self-containment (zero external script/style tags)
    assert "<!DOCTYPE html>" in html
    assert "<style>" in html
    assert "<script>" in html
    assert "https://cdn" not in html
    assert "http://cdn" not in html

    # 2. Check streamlined 5 key sections (and verify removed sections are absent)
    assert "Paginated Report Performance Analysis" in html
    assert "Detailed Findings" in html
    assert "SQL Comparison" in html
    assert "Dataset Analysis" in html
    assert "Parameter Analysis" in html
    assert "Optimization Tracker" in html
    # Verify removed sections are absent
    assert "Executive Summary &amp; Health Score" not in html
    assert "Performance Architecture Summary" not in html
    assert "Lead Architect Technical Assessment" not in html

    # 3. Check interactive Action Plan and localStorage script
    assert "xebia_action_plan_" in html
    assert "localStorage" in html
    assert "plan-select-status" in html

    # 4. Check SQL comparison & copy buttons
    assert "Copy SQL" in html
    assert "copyText" in html


def test_html_report_generation_non_sql():
    """Verify that non-SQL reports (like RegionalSales.rdl) omit the SQL Comparison section entirely."""
    import os
    downloads_rdl = os.path.expanduser("~/Downloads/RegionalSales.rdl")
    if not os.path.exists(downloads_rdl):
        pytest.skip("RegionalSales.rdl not found in Downloads")

    parser = RDLParser()
    engine = RecommendationEngine()
    parsed = parser.parse_file(downloads_rdl)
    res = engine.compile_report(parsed)

    issues_dict = [
        {
            "id": i.id,
            "category": i.category.value,
            "severity": i.severity.value,
            "classification": i.classification.value,
            "title": i.title,
            "target_object": i.target_object,
            "description": i.description,
            "impact": i.impact,
            "remediation": i.remediation,
            "code_snippet": i.code_snippet,
            "suggested_fix": i.suggested_fix,
        }
        for i in res.issues
    ]
    data = {
        "report_name": res.report_name,
        "health_score": res.health_score,
        "health_status": res.health_status,
        "summary_metrics": res.summary_metrics,
        "issues": issues_dict,
        "dataset_optimizations": {},
        "field_usage_matrix": res.field_usage_matrix,
    }

    html = generate_html_report(data, parsed_rdl=parsed)

    # 1. Self-contained
    assert "<!DOCTYPE html>" in html
    # 2. 4 active sections present, SQL Comparison omitted
    assert "Detailed Findings" in html
    assert "Dataset Analysis" in html
    assert "Parameter Analysis" in html
    assert "Optimization Tracker" in html
    assert 'id="section-sql"' not in html
    # 3. Parameter defect detected
    assert "PARAM-INERT-FILTER-dsMain-CalendarYear" in html


def test_export_html_api_endpoint():
    data = {
        "report_name": "APITestReport",
        "health_score": 75,
        "health_status": "Good",
        "summary_metrics": {
            "total_datasets": 1,
            "total_queries": 1,
            "total_issues": 1,
            "high_severity_count": 0,
            "medium_severity_count": 1,
            "low_severity_count": 0,
            "unused_fields_count": 2,
        },
        "issues": [
            {
                "id": "SQL-UNUSED-1",
                "category": "SQL Query",
                "severity": "Medium",
                "classification": "Potential Optimization",
                "title": "Unused Columns Fetched",
                "target_object": "OrdersDataset",
                "description": "2 columns fetched are never used in visuals.",
                "impact": "Increases gateway payload.",
                "remediation": "Prune unused columns from SELECT clause.",
            }
        ],
        "dataset_optimizations": {},
        "field_usage_matrix": {
            "OrdersDataset": {
                "total_fields": 5,
                "used_count": 3,
                "unused_count": 2,
                "used_fields": ["OrderID", "Amount", "OrderDate"],
                "unused_fields": ["ColA", "ColB"],
            }
        },
    }

    res = export_html_report_endpoint(data)
    assert res.media_type == "text/html"
    assert "attachment; filename=" in res.headers["Content-Disposition"]
    assert "Paginated_Report_Performance_Analysis_" in res.headers["Content-Disposition"]
    assert res.status_code == 200
