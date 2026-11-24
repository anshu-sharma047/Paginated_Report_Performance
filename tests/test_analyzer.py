import os
import pytest
from backend.parser import RDLParser
from backend.analyzer import RecommendationEngine, Severity

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_reports")


def test_analyzer_sample1_sql():
    parser = RDLParser()
    engine = RecommendationEngine()

    rdl = parser.parse_file(os.path.join(SAMPLES_DIR, "sample1_sql_bottlenecks.rdl"))
    result = engine.compile_report(rdl)

    # Health score should drop due to High-severity SQL issues
    assert result.health_score < 70

    issue_ids = [i.id for i in result.issues]
    # Check SELECT * detected
    assert any("SQL-STAR-SalesDataset" in id for id in issue_ids)
    # Check Non-sargable YEAR(SaleDate) detected
    assert any("SQL-SARGABLE-SalesDataset" in id for id in issue_ids)
    # Check Missing WHERE detected on TransactionsDataset
    assert any("SQL-NOWHERE-TransactionsDataset" in id for id in issue_ids)
    # Check Unused columns detected
    assert any("SQL-UNUSED-COLS-SalesDataset" in id for id in issue_ids)

    # Check optimization suggestion was generated
    opt = result.dataset_optimizations["SalesDataset"]
    assert "SELECT *" not in opt.suggested_query
    assert "SaleID" in opt.suggested_query
    assert "2026-01-01" in opt.suggested_query


def test_analyzer_sample2_structure():
    parser = RDLParser()
    engine = RecommendationEngine()

    rdl = parser.parse_file(os.path.join(SAMPLES_DIR, "sample2_structure_subreports.rdl"))
    result = engine.compile_report(rdl)

    issue_ids = [i.id for i in result.issues]
    # Check subreport in row group detected (N+1 hazard)
    assert any("STRUCT-SUBREPORT-ROW-SubreportOrderItems" in id for id in issue_ids)
    # Check orphan datasets detected
    assert any("STRUCT-ORPHAN-DS-OrphanCustomerHistory" in id for id in issue_ids)
    assert any("STRUCT-ORPHAN-DS-OrphanSuppliers" in id for id in issue_ids)


def test_analyzer_sample3_expressions():
    parser = RDLParser()
    engine = RecommendationEngine()

    rdl = parser.parse_file(os.path.join(SAMPLES_DIR, "sample3_expressions_parameters.rdl"))
    result = engine.compile_report(rdl)

    issue_ids = [i.id for i in result.issues]
    # Check unpushed parameters
    assert any("PARAM-UNPUSHED-SalesData-RegionName" in id for id in issue_ids)
    # Check in-memory Tablix filter
    assert any("PARAM-TABLIX-FILTER-SalesTablix" in id for id in issue_ids)
    # Check nested IIF
    assert any("EXPR-NESTED-IIF" in id for id in issue_ids)
    # Check custom code
    assert any("EXPR-CUSTOM-CODE" in id for id in issue_ids)


def test_detect_query_type_variants():
    from backend.analyzer import detect_query_type_from_text, detect_query_type
    from backend.parser import DatasetInfo

    # XML Query Text
    xml_query_1 = "<Query><ElementPath>Root/Item</ElementPath></Query>"
    assert detect_query_type_from_text(xml_query_1) == "XML"

    xml_query_2 = "<?xml version='1.0'?><Data><Row id='1'/></Data>"
    assert detect_query_type_from_text(xml_query_2) == "XML"

    # XML via data_provider
    ds_xml = DatasetInfo(name="XmlDs", query_text="Some text", data_provider="XML")
    assert detect_query_type(ds_xml) == "XML"

    # DAX Query
    dax_query = "EVALUATE SUMMARIZECOLUMNS('Date'[Year], 'Sales'[Amount])"
    assert detect_query_type_from_text(dax_query) == "DAX"

    # MDX Query
    mdx_query = "SELECT {[Measures].[Sales]} ON COLUMNS FROM [Cube]"
    assert detect_query_type_from_text(mdx_query) == "MDX"

    # Stored Procedure
    ds_sp = DatasetInfo(name="SpDs", query_text="usp_GetOrders", command_type="StoredProcedure")
    assert detect_query_type(ds_sp) == "StoredProcedure"

    # Standard SQL
    sql_query = "SELECT SaleID, Amount FROM Sales WHERE Year = 2026"
    assert detect_query_type_from_text(sql_query) == "SQL"


def test_xml_dataset_never_optimized_as_sql():
    from backend.parser import DatasetInfo, ParsedRDL
    from backend.analyzer import SQLQueryAnalyzer, RecommendationEngine

    xml_content = """<Query>
        <ElementPath>Orders/Order{OrderID, CustomerName, Amount}</ElementPath>
    </Query>"""

    xml_ds = DatasetInfo(
        name="OrdersXML",
        query_text=xml_content,
        command_type="Text",
        data_provider="XML",
        fields=["OrderID", "CustomerName", "Amount"],
        used_field_names={"OrderID", "Amount"},
        unused_field_names={"CustomerName"},
    )

    sql_analyzer = SQLQueryAnalyzer()
    issues, opt = sql_analyzer.analyze(xml_ds, {})

    # Requirement 5: Never generate SQL optimization suggestions for XML data
    assert opt is None

    # Requirement 6: Never append SQL WHERE clauses to XML payloads
    for iss in issues:
        assert "WHERE" not in iss.title
        if iss.suggested_fix:
            assert "WHERE" not in iss.suggested_fix

    # Requirement 9: Keep XML analysis separate from SQL query optimization
    # Unused fields for XML dataset should be under REPORT_STRUCTURE, not SQL Query
    xml_issues = [i for i in issues if "XML-UNUSED-FIELDS-OrdersXML" in i.id]
    assert len(xml_issues) == 1
    assert xml_issues[0].category.value == "Report Structure"

    # Full compile_report test:
    # A report with ONLY XML datasets should have empty dataset_optimizations
    rdl = ParsedRDL(
        report_name="XmlOnlyReport",
        datasets={"OrdersXML": xml_ds},
    )
    engine = RecommendationEngine()
    result = engine.compile_report(rdl)

    assert "OrdersXML" not in result.dataset_optimizations
    assert len(result.dataset_optimizations) == 0
    assert result.summary_metrics["total_sql_queries"] == 0
    assert result.summary_metrics["total_non_sql_datasets"] == 1


def test_regional_sales_analysis():
    """Validates the exact logic required for RegionalSales.rdl:
    - ENTERDATA data source is recognized as XML/EnterData
    - 0 SQL datasets, 0 SQL optimizations
    - dsParamYear & dsParamSalesTerritoryGroup are NOT flagged as orphan datasets
    - dsMain CalendarYear query parameter is flagged as inert functional defect
    - No SQL WHERE-clause pushdown recommendation for EnterData
    - Unused fields is 0 for all datasets
    - Health score >= 90
    """
    downloads_rdl = os.path.expanduser("~/Downloads/RegionalSales.rdl")
    if not os.path.exists(downloads_rdl):
        pytest.skip("RegionalSales.rdl not found in Downloads")

    parser = RDLParser()
    engine = RecommendationEngine()
    parsed = parser.parse_file(downloads_rdl)
    result = engine.compile_report(parsed)

    # 1. Zero SQL datasets
    assert result.summary_metrics["total_sql_queries"] == 0
    assert len(result.dataset_optimizations) == 0

    # 2. Query types
    for ds in parsed.datasets.values():
        assert ds.query_type == "XML/EnterData"

    # 3. No orphan dataset issues for parameter datasets
    issue_ids = [i.id for i in result.issues]
    assert "STRUCT-ORPHAN-DS-dsParamYear" not in issue_ids
    assert "STRUCT-ORPHAN-DS-dsParamSalesTerritoryGroup" not in issue_ids
    assert not any("STRUCT-ORPHAN-DS" in id for id in issue_ids)

    # 4. Inert parameter CalendarYear detected on dsMain as Functional Defect
    assert "PARAM-INERT-FILTER-dsMain-CalendarYear" in issue_ids
    inert_issue = next(i for i in result.issues if i.id == "PARAM-INERT-FILTER-dsMain-CalendarYear")
    assert inert_issue.severity.value == "Medium"
    assert inert_issue.classification.value == "Functional Defect"
    assert "CalendarYear" in inert_issue.title

    # 5. In-memory filter on dsMain is marked Best Practice with no SQL pushdown
    ds_filter_issue = next((i for i in result.issues if "PARAM-DS-FILTER-dsMain" in i.id), None)
    if ds_filter_issue:
        assert ds_filter_issue.classification.value == "Best Practice"
        assert ds_filter_issue.severity.value == "Info"
        assert "WHERE" not in ds_filter_issue.remediation

    # 6. Unused fields count is 0
    assert result.summary_metrics["unused_fields_count"] == 0

    # 7. Health score reflects verified findings without false penalties
    assert result.health_score >= 90


def test_slow_performance_test_report_analysis():
    """Validates technical logic on Slow_Performance_Test_Report.rdl:
    1. SalesDataset retains @Year parameter mapping (no unpushed parameter error for Year).
    2. SELECT * and unused columns accurately detected for SalesDataset (4 unused fields).
    3. YEAR(TransactionDate) = @Year detected as non-SARGable and rewritten with DATEFROMPARTS.
    4. Region parameter flagged as inactive / potential functional defect, without unsafe equality filter.
    5. TransactionsDataset & CustomerLookupDataset flagged as orphan datasets without SQL comparison entries or invented columns.
    6. Dataset analysis consistency: 0 visual refs = 0 used fields for orphan datasets.
    7. No invented [DateColumn] or fake WHERE clause in suggested queries.
    8. Recommendations include appropriate validation statuses.
    """
    downloads_rdl = os.path.expanduser("~/Downloads/Slow_Performance_Test_Report.rdl")
    if not os.path.exists(downloads_rdl):
        pytest.skip("Slow_Performance_Test_Report.rdl not found in Downloads")

    parser = RDLParser()
    engine = RecommendationEngine()
    parsed = parser.parse_file(downloads_rdl)
    result = engine.compile_report(parsed)

    # 1. Dataset analysis consistency (0 visual refs = 0 used fields)
    assert parsed.datasets["TransactionsDataset"].referenced_in_visuals == 0
    assert len(parsed.datasets["TransactionsDataset"].used_field_names) == 0
    assert parsed.datasets["TransactionsDataset"].is_orphan is True

    assert parsed.datasets["CustomerLookupDataset"].referenced_in_visuals == 0
    assert len(parsed.datasets["CustomerLookupDataset"].used_field_names) == 0
    assert parsed.datasets["CustomerLookupDataset"].is_orphan is True

    assert parsed.datasets["SalesDataset"].referenced_in_visuals == 1
    assert len(parsed.datasets["SalesDataset"].used_field_names) == 10
    assert len(parsed.datasets["SalesDataset"].unused_field_names) == 4
    assert parsed.datasets["SalesDataset"].unused_field_names == {"CreatedBy", "PaymentMethod", "ShippingAmount", "Status"}

    # 2. Issues detection
    issue_ids = [i.id for i in result.issues]

    # SalesDataset issues
    assert "SQL-STAR-SalesDataset" in issue_ids
    assert "SQL-SARGABLE-SalesDataset-TransactionDate" in issue_ids
    assert "SQL-UNUSED-COLS-SalesDataset" in issue_ids

    # Check SARGable issue details and DATEFROMPARTS rewrite
    sarg_issue = next(i for i in result.issues if i.id == "SQL-SARGABLE-SalesDataset-TransactionDate")
    assert "DATEFROMPARTS(@Year, 1, 1)" in sarg_issue.suggested_fix
    assert sarg_issue.validation_status == "Requires manual validation"

    # Region flagged as inactive functional defect
    assert "PARAM-INERT-REPORT-Region" in issue_ids
    assert not any("PARAM-UNPUSHED-SalesDataset-Region" in id for id in issue_ids)
    region_issue = next(i for i in result.issues if i.id == "PARAM-INERT-REPORT-Region")
    assert region_issue.classification.value == "Functional Defect"
    assert "All" in region_issue.suggested_fix

    # Year parameter should NOT be flagged as unpushed
    assert not any("Year" in id and "PARAM-UNPUSHED" in id for id in issue_ids)

    # Orphan datasets flagged for removal
    assert "STRUCT-ORPHAN-DS-TransactionsDataset" in issue_ids
    assert "STRUCT-ORPHAN-DS-CustomerLookupDataset" in issue_ids

    # Suppress redundant SQL findings on orphan datasets
    assert "SQL-STAR-TransactionsDataset" not in issue_ids
    assert "SQL-NOWHERE-TransactionsDataset" not in issue_ids
    assert "SQL-STAR-CustomerLookupDataset" not in issue_ids
    assert "SQL-NOWHERE-CustomerLookupDataset" not in issue_ids

    # 3. SQL Optimizations: ONLY SalesDataset should have an entry
    assert list(result.dataset_optimizations.keys()) == ["SalesDataset"]
    opt_sales = result.dataset_optimizations["SalesDataset"]
    assert "SELECT *" not in opt_sales.suggested_query
    assert "DATEFROMPARTS(@Year, 1, 1)" in opt_sales.suggested_query
    assert opt_sales.validation_status == "Requires manual validation"

    # 4. Never invent columns or dates
    for opt in result.dataset_optimizations.values():
        assert "[DateColumn]" not in opt.suggested_query
        assert "@StartDate" not in opt.suggested_query
        assert "@EndDate" not in opt.suggested_query


def test_slow_performance_test_report_optimized():
    """Validates that the fixed/optimized report achieves 100/100 score and 0 issues."""
    parser = RDLParser()
    engine = RecommendationEngine()
    opt_path = "Slow_Performance_Test_Report_Optimized.rdl"
    if not os.path.exists(opt_path):
        opt_path = os.path.expanduser("~/Downloads/Slow_Performance_Test_Report_Optimized.rdl")
    if not os.path.exists(opt_path):
        pytest.skip("Slow_Performance_Test_Report_Optimized.rdl not found")

    rdl = parser.parse_file(opt_path)
    result = engine.compile_report(rdl)

    # 1. Clean bill of health
    assert result.health_score == 100
    assert result.health_status == "Excellent"
    assert len(result.issues) == 0

    # 2. Exactly 1 dataset (SalesDataset) with 100% field utilization
    assert list(rdl.datasets.keys()) == ["SalesDataset"]
    sales_ds = rdl.datasets["SalesDataset"]
    assert len(sales_ds.fields) == 10
    assert len(sales_ds.used_field_names) == 10
    assert len(sales_ds.unused_field_names) == 0

    # 3. Both parameters active and pushed
    assert len(rdl.parameters) == 2
    param_issues = [i for i in result.issues if i.category == ComponentCategory.PARAMETER_FILTER]
    assert len(param_issues) == 0




