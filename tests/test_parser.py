import os
import pytest
from backend.parser import RDLParser

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_reports")


def test_parse_sample1_sql_bottlenecks():
    parser = RDLParser()
    file_path = os.path.join(SAMPLES_DIR, "sample1_sql_bottlenecks.rdl")
    rdl = parser.parse_file(file_path)

    assert rdl.report_name == "sample1_sql_bottlenecks"
    assert "Year" in rdl.parameters
    assert "SalesDataset" in rdl.datasets
    assert "TransactionsDataset" in rdl.datasets

    sales_ds = rdl.datasets["SalesDataset"]
    assert "SELECT *" in sales_ds.query_text
    assert len(sales_ds.fields) == 15
    # Used fields should be SaleID, CustomerID, SaleDate, Amount
    assert "SaleID" in sales_ds.used_field_names
    assert "Amount" in sales_ds.used_field_names
    # Unused fields should include Notes, Filler1, etc.
    assert "Notes" in sales_ds.unused_field_names
    assert "Filler1" in sales_ds.unused_field_names
    assert len(sales_ds.unused_field_names) == 11


def test_parse_sample2_structure_subreports():
    parser = RDLParser()
    file_path = os.path.join(SAMPLES_DIR, "sample2_structure_subreports.rdl")
    rdl = parser.parse_file(file_path)

    assert len(rdl.datasets) == 8
    assert "ActiveOrders" in rdl.datasets
    assert "OrphanCustomerHistory" in rdl.datasets
    assert "OrphanSuppliers" in rdl.datasets

    # Subreport should be detected inside Tablix row group
    assert len(rdl.subreports) == 1
    sub = rdl.subreports[0]
    assert sub.name == "SubreportOrderItems"
    assert sub.in_row_group is True


def test_parse_sample3_expressions_parameters():
    parser = RDLParser()
    file_path = os.path.join(SAMPLES_DIR, "sample3_expressions_parameters.rdl")
    rdl = parser.parse_file(file_path)

    assert "FiscalYear" in rdl.parameters
    assert "RegionName" in rdl.parameters
    assert rdl.custom_code is not None
    assert "CalculateCommission" in rdl.custom_code

    # Check that in-memory filter was extracted
    sales_visual = next(v for v in rdl.visuals if v.name == "SalesTablix")
    assert len(sales_visual.filters) == 1
    assert "Fields!Region.Value" in sales_visual.filters[0].expression
