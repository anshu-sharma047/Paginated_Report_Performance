import os
import io
import pytest
from starlette.datastructures import UploadFile
from backend.main import (
    health_check,
    optimize_sql,
    ai_explain,
    analyze_rdl,
    export_excel_report,
    serve_index,
    serve_css,
    serve_js,
    get_sample_reports,
    analyze_sample_report,
    QueryOptimizeRequest,
    AIExplainRequest,
)

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_reports")


def test_api_health():
    data = health_check()
    assert data["status"] == "healthy"
    assert "ai_service_available" in data
    assert "azure_llm_available" in data


def test_static_frontend_delivery():
    # Test index.html delivery
    res_index = serve_index()
    assert os.path.exists(res_index.path)
    assert res_index.path.endswith("index.html")

    # Test style.css delivery
    res_css = serve_css()
    assert os.path.exists(res_css.path)
    assert res_css.media_type == "text/css"

    # Test app.js delivery
    res_js = serve_js()
    assert os.path.exists(res_js.path)
    assert res_js.media_type == "application/javascript"


def test_api_sample_endpoints():
    # Test sample listing
    samples = get_sample_reports()
    assert len(samples) >= 3
    sample_ids = [s["id"] for s in samples]
    assert "sample1" in sample_ids
    assert "sample2" in sample_ids
    assert "sample3" in sample_ids

    # Test sample direct analysis
    res = analyze_sample_report("sample1")
    assert "health_score" in res
    assert len(res["issues"]) > 0
    assert "SalesDataset" in res["dataset_optimizations"]


def test_api_optimize_sql():
    req = QueryOptimizeRequest(
        dataset_name="TestDS",
        original_query="SELECT * FROM Sales WHERE YEAR(SaleDate) = 2026",
        used_fields=["SaleID", "Amount"],
        parameters=["Year"],
        use_ai=False,
    )
    data = optimize_sql(req)
    assert data["query_type"] == "SQL"
    assert "SELECT *" not in data["optimized_query"]
    assert "SaleID" in data["optimized_query"]
    assert "SaleDate >=" in data["optimized_query"]
    assert "detected_issues" in data
    assert "suggested_improvements" in data


def test_api_optimize_sql_non_sql_guard():
    # Pass an XML query to the optimize-sql endpoint
    req = QueryOptimizeRequest(
        dataset_name="XmlDS",
        original_query="<Query><ElementPath>Orders/Order{ID, Date}</ElementPath></Query>",
        used_fields=["ID"],
        use_ai=False,
    )
    data = optimize_sql(req)
    assert data["source"] == "non_sql_guard"
    assert data["query_type"] == "XML"
    # Never modify or append WHERE to XML payload
    assert data["optimized_query"] == req.original_query
    assert "SQL comparison is unavailable for XML datasets" in data["explanation"]



def test_api_ai_explain():
    req = AIExplainRequest(
        title="Wildcard Projection (SELECT *)",
        target_object="SalesDataset",
        description="Selects all columns",
        impact="High network traffic",
    )
    data = ai_explain(req)
    assert "explanation" in data
    assert len(data["explanation"]) > 20


def test_api_analyze_sample1():
    file_path = os.path.join(SAMPLES_DIR, "sample1_sql_bottlenecks.rdl")
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    upload_file = UploadFile(filename="sample1.rdl", file=io.BytesIO(file_bytes))
    data = analyze_rdl(file=upload_file)

    assert data["report_name"] == "sample1"
    assert "health_score" in data
    assert len(data["issues"]) > 0
    assert "SalesDataset" in data["dataset_optimizations"]

    # Test Excel export with this analysis payload
    export_res = export_excel_report(data)
    assert export_res.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _get_stream_bytes(response):
    import anyio

    async def _consume():
        chunks = []
        async for c in response.body_iterator:
            chunks.append(c)
        return b"".join(chunks)

    return anyio.run(_consume)


def test_api_export_5_sheets_exact_format():
    import openpyxl

    file_path = os.path.join(SAMPLES_DIR, "sample1_sql_bottlenecks.rdl")
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    upload_file = UploadFile(filename="sample1.rdl", file=io.BytesIO(file_bytes))
    data = analyze_rdl(file=upload_file)

    export_res = export_excel_report(data)
    content = _get_stream_bytes(export_res)
    wb = openpyxl.load_workbook(io.BytesIO(content))

    expected_sheets = [
        "1 Detailed Findings (Short)",
        "2 SQL Comparison",
        "3 Dataset Analysis",
        "4 Parameter Analysis",
        "5 Optimization Tracker",
    ]
    assert wb.sheetnames == expected_sheets

    # Tab 1: Detailed Findings (Short)
    ws1 = wb["1 Detailed Findings (Short)"]
    assert ws1.cell(row=1, column=1).value == "Issue ID"
    assert ws1.max_row >= 2

    # Tab 2: SQL Comparison
    ws2 = wb["2 SQL Comparison"]
    assert ws2.cell(row=1, column=1).value == "Dataset Name"
    assert ws2.max_row >= 2
    assert ws2.cell(row=2, column=1).value == "SalesDataset"

    # Tab 3: Dataset Analysis
    ws3 = wb["3 Dataset Analysis"]
    assert ws3.cell(row=1, column=1).value == "Dataset Name"
    assert ws3.cell(row=1, column=2).value == "Query Type"
    assert ws3.max_row >= 2

    # Tab 4: Parameter Analysis
    ws4 = wb["4 Parameter Analysis"]
    assert ws4.cell(row=1, column=1).value == "Parameter Name"
    assert ws4.max_row >= 2

    # Tab 5: Optimization Tracker
    ws5 = wb["5 Optimization Tracker"]
    assert ws5.cell(row=1, column=1).value == "Priority"
    assert ws5.cell(row=1, column=2).value == "Finding ID"
    assert ws5.max_row >= 2


def test_api_export_non_sql_report():
    import openpyxl

    # Test an analysis payload with 0 SQL datasets
    mock_data = {
        "report_name": "InvoiceReport",
        "health_score": 50,
        "health_status": "Fair",
        "summary_metrics": {"total_datasets": 2, "total_sql_queries": 0, "unused_fields_count": 4},
        "issues": [
            {
                "id": "XML-UNUSED-1",
                "category": "Report Structure & Architecture",
                "severity": "Medium",
                "classification": "Optimization Opportunity",
                "title": "Unused fields in XML dataset",
                "target_object": "Dataset (XML): Company",
                "description": "4 unreferenced fields",
                "impact": "In-memory parsing overhead",
                "remediation": "Prune unused fields",
            }
        ],
        "dataset_optimizations": {},  # No SQL queries
        "dataset_inventory": [
            {
                "name": "Company",
                "query_type": "XML",
                "data_source_name": "Embedded",
                "command_type": "Text",
                "fields_retrieved_count": 8,
                "fields_referenced_count": 4,
                "unused_fields_count": 4,
                "visual_references_count": 1,
                "detected_issues_count": 1,
                "used_fields": ["ID", "Name", "Addr", "City"],
                "unused_fields": ["ColA", "ColB", "ColC", "ColD"],
            }
        ],
        "parameter_inventory": [
            {
                "name": "CompanyID",
                "data_type": "String",
                "multi_value": "No",
                "default_value": "100",
                "available_values_dataset": "Static / None",
                "sql_parameter_usage": "None",
                "validation_status": "N/A (No SQL Datasets)",
                "detected_issues": [],
            }
        ],
    }

    export_res = export_excel_report(mock_data)
    content = _get_stream_bytes(export_res)
    wb = openpyxl.load_workbook(io.BytesIO(content))

    assert wb.sheetnames == [
        "1 Detailed Findings (Short)",
        "2 SQL Comparison",
        "3 Dataset Analysis",
        "4 Parameter Analysis",
        "5 Optimization Tracker",
    ]

    # In Tab 2, verify no SQL notice
    ws2 = wb["2 SQL Comparison"]
    assert "No SQL datasets were detected" in str(ws2.cell(row=2, column=1).value)

