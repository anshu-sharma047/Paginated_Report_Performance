"""
FastAPI Backend Application
Exposes REST endpoints for Paginated Report Performance Analysis,
SQL Optimization, AI Explanation, and Excel Report Generation.
"""

from __future__ import annotations
import io
import os
import sys

# Ensure root directory is in sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from typing import Dict, List, Optional, Any
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from backend.parser import RDLParser
from backend.analyzer import RecommendationEngine, Severity
from backend.gemini_service import GeminiService
from backend.azure_llm import AzureOpenAIService
from backend.html_report_generator import generate_html_report, generate_unique_report_id

app = FastAPI(
    title="Paginated Report Performance Analyzer API",
    description="High-performance diagnostic API for Power BI / SSRS Paginated Reports",
    version="1.0.0",
)

# Enable CORS for local access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
SAMPLES_DIR = os.path.join(ROOT_DIR, "sample_reports")

# Mount assets directory for logo and static images
if os.path.exists(os.path.join(FRONTEND_DIR, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

parser = RDLParser()
engine = RecommendationEngine()
ai_service = GeminiService()
azure_llm = AzureOpenAIService()

SAMPLE_MAP = {
    "sample1": {
        "filename": "sample1_sql_bottlenecks.rdl",
        "title": "Sample 1: SQL Bottlenecks",
        "description": "Wildcard SELECT *, non-sargable YEAR(SaleDate) predicate, missing WHERE clause.",
    },
    "sample2": {
        "filename": "sample2_structure_subreports.rdl",
        "title": "Sample 2: Architecture & Subreports",
        "description": "N+1 subreport query hazard in Tablix rows, orphan/unused datasets.",
    },
    "sample3": {
        "filename": "sample3_expressions_parameters.rdl",
        "title": "Sample 3: Complex Expressions & Pushdown",
        "description": "Deeply nested IIFs, repeated type casting (CDate, CDbl), unpushed report parameters.",
    },
}


def _run_analysis(content_str: str, report_name: str) -> Dict[str, Any]:
    """Core analysis execution subroutine shared across upload and preset endpoints."""
    import re

    parsed = parser.parse_string(content_str, report_name=report_name)
    analysis = engine.compile_report(parsed)

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
            "validation_status": getattr(i, "validation_status", "Validated against RDL metadata"),
        }
        for i in analysis.issues
    ]

    from backend.analyzer import detect_query_type

    optimizations_dict = {
        ds_name: {
            "dataset_name": opt.dataset_name,
            "query_type": getattr(opt, "query_type", "SQL"),
            "original_query": opt.original_query,
            "suggested_query": opt.suggested_query,
            "optimization_reasons": opt.optimization_reasons,
            "detected_issues": getattr(opt, "detected_issues", []),
            "suggested_improvements": getattr(opt, "suggested_improvements", []),
            "fields_used": opt.fields_used,
            "fields_pruned": opt.fields_pruned,
            "validation_status": getattr(opt, "validation_status", "Validated against RDL metadata"),
        }
        for ds_name, opt in analysis.dataset_optimizations.items()
        if getattr(opt, "query_type", "SQL") == "SQL"
    }

    # Build complete dataset inventory for Section 5
    dataset_inventory = [
        {
            "name": ds_name,
            "query_type": getattr(ds, "query_type", detect_query_type(ds)),
            "dependency_type": getattr(ds, "dependency_type", "Visual Bound"),
            "is_orphan": getattr(ds, "is_orphan", False),
            "data_source_name": ds.data_source_name or "Embedded",
            "command_type": ds.command_type or "Text",
            "query_length": len(ds.query_text) if ds.query_text else 0,
            "query_text": ds.query_text or "",
            "fields_retrieved_count": len(ds.fields),
            "fields_referenced_count": len(ds.used_field_names),
            "unused_fields_count": len(ds.unused_field_names),
            "used_fields": sorted(list(ds.used_field_names)),
            "unused_fields": sorted(list(ds.unused_field_names)),
            "visual_references_count": ds.referenced_in_visuals,
            "detected_issues_count": sum(1 for iss in analysis.issues if ds_name in iss.target_object),
        }
        for ds_name, ds in parsed.datasets.items()
    ]

    # Build complete parameter inventory for Section 6
    parameter_inventory = []
    total_sql_ds = sum(1 for ds in parsed.datasets.values() if getattr(ds, "query_type", "SQL") == "SQL" and ds.query_text)
    for prm_name, prm in parsed.parameters.items():
        sql_usage = [
            ds_name for ds_name, ds in parsed.datasets.items()
            if ds.query_text and getattr(ds, "query_type", "SQL") == "SQL" and re.search(rf"@{re.escape(prm_name)}\b", ds.query_text, re.IGNORECASE)
        ]
        qp_usage = [
            ds_name for ds_name, ds in parsed.datasets.items()
            if any(prm_name.lower() == qp.name.lstrip("@").lower() or prm_name.lower() in qp.value.lower() for qp in getattr(ds, "query_parameters", []))
        ]
        prm_issues = [
            iss.title for iss in analysis.issues
            if prm_name in iss.target_object or f"@{prm_name}" in iss.description
        ]
        is_inert = any(iss.id == f"PARAM-INERT-REPORT-{prm_name}" for iss in analysis.issues)
        valid_ds = getattr(prm, "valid_values_dataset", None)
        default_ds = getattr(prm, "default_values_dataset", None)
        avail_ds_str = valid_ds if valid_ds else ("Default Dataset: " + default_ds if default_ds else "Static / Single-value")

        if is_inert:
            is_pushed = False
            val_status = "Potential Functional Defect"
            mapping_str = "None (Unreferenced in Report)"
        elif total_sql_ds > 0:
            is_pushed = len(sql_usage) > 0 or len(qp_usage) > 0
            val_status = "Validated against RDL metadata (Pushed to SQL)" if is_pushed else "Requires Action (Not Pushed)"
            active_mappings = list(dict.fromkeys(sql_usage + qp_usage))
            mapping_str = ", ".join(active_mappings) if active_mappings else "None"
        else:
            # Non-SQL / EnterData / XML report
            ds_filter_usage = [
                ds_name for ds_name, ds in parsed.datasets.items()
                if any(prm_name.lower() in flt.expression.lower() or any(prm_name.lower() in str(v).lower() for v in flt.values) for flt in getattr(ds, "filters", []))
            ]
            if ds_filter_usage:
                is_pushed = True
                val_status = "Applied in Dataset Filter"
                mapping_str = f"Filter in {', '.join(ds_filter_usage)}"
            elif valid_ds:
                is_pushed = True
                val_status = f"Lookup Dataset ({valid_ds})"
                mapping_str = f"Available Values: {valid_ds}"
            elif qp_usage:
                is_pushed = False
                val_status = "Inert Query Parameter"
                mapping_str = f"QueryParam in {', '.join(qp_usage)}"
            else:
                is_pushed = False
                val_status = "Unused Parameter"
                mapping_str = "None"

        parameter_inventory.append({
            "name": prm_name,
            "data_type": prm.data_type,
            "multi_value": "Yes" if prm.multi_value else "No",
            "default_value": ", ".join(prm.default_values) if prm.default_values else "None",
            "available_values_dataset": avail_ds_str,
            "dataset_parameter_mapping": mapping_str,
            "sql_parameter_usage": mapping_str,
            "validation_status": val_status,
            "detected_issues": prm_issues,
            "is_pushed_to_sql": is_pushed,
        })

    ai_exec_summary = ""
    if azure_llm.is_available():
        try:
            ai_exec_summary = azure_llm.generate_executive_assessment(
                report_name=analysis.report_name,
                health_score=analysis.health_score,
                health_status=analysis.health_status,
                metrics=analysis.summary_metrics,
                issues=issues_dict,
            )
        except Exception as e:
            print(f"[Main] Azure OpenAI executive assessment failed: {e}")

    return {
        "report_name": analysis.report_name,
        "health_score": analysis.health_score,
        "health_status": analysis.health_status,
        "summary_metrics": analysis.summary_metrics,
        "issues": issues_dict,
        "dataset_optimizations": optimizations_dict,
        "field_usage_matrix": analysis.field_usage_matrix,
        "recommendations_summary": analysis.recommendations_summary,
        "dataset_inventory": dataset_inventory,
        "parameter_inventory": parameter_inventory,
        "ai_available": azure_llm.is_available() or ai_service.is_available(),
        "ai_executive_summary": ai_exec_summary,
        "llm_info": {
            "provider": "Azure OpenAI" if azure_llm.is_available() else ("Google Gemini" if ai_service.is_available() else "Rule Engine"),
            "deployment": azure_llm.deployment if azure_llm.is_available() else "None",
            "active": azure_llm.is_available() or ai_service.is_available(),
        },
    }


class QueryOptimizeRequest(BaseModel):
    dataset_name: str
    original_query: str
    used_fields: List[str] = []
    parameters: List[str] = []
    use_ai: bool = False


class AIExplainRequest(BaseModel):
    title: str
    target_object: str
    description: str
    impact: str


# ==============================================================================
# Frontend Static Routing (Direct HTML/CSS/JS Delivery)
# ==============================================================================

@app.get("/", include_in_schema=False)
def serve_index():
    """Serves the pure HTML5/CSS3 frontend application."""
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return RedirectResponse(url="/docs")


@app.get("/style.css", include_in_schema=False)
def serve_css():
    """Serves the enterprise Xebia stylesheet."""
    css_file = os.path.join(FRONTEND_DIR, "style.css")
    if os.path.exists(css_file):
        return FileResponse(css_file, media_type="text/css")
    raise HTTPException(status_code=404, detail="Stylesheet not found")


@app.get("/app.js", include_in_schema=False)
def serve_js():
    """Serves the vanilla JavaScript client logic."""
    js_file = os.path.join(FRONTEND_DIR, "app.js")
    if os.path.exists(js_file):
        return FileResponse(js_file, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="JavaScript bundle not found")


# ==============================================================================
# API Endpoints
# ==============================================================================

@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Paginated Report Performance Analyzer Backend",
        "ai_service_available": ai_service.is_available(),
        "azure_llm_available": azure_llm.is_available(),
    }


@app.get("/api/samples")
def get_sample_reports():
    """Returns available pre-packaged sample RDL reports."""
    results = []
    for sid, info in SAMPLE_MAP.items():
        p = os.path.join(SAMPLES_DIR, info["filename"])
        sz = os.path.getsize(p) if os.path.exists(p) else 0
        results.append({
            "id": sid,
            "title": info["title"],
            "filename": info["filename"],
            "description": info["description"],
            "size_bytes": sz,
        })
    return results


@app.get("/api/samples/{sample_id}")
def get_sample_content(sample_id: str):
    """Returns content and metadata for a specific sample report."""
    if sample_id not in SAMPLE_MAP:
        raise HTTPException(status_code=404, detail="Sample not found")
    info = SAMPLE_MAP[sample_id]
    p = os.path.join(SAMPLES_DIR, info["filename"])
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Sample file missing on disk")
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
    return {
        "id": sample_id,
        "filename": info["filename"],
        "title": info["title"],
        "content": content,
    }


@app.post("/api/samples/{sample_id}/analyze")
def analyze_sample_report(sample_id: str):
    """Directly executes diagnostic analysis on a built-in sample report."""
    if sample_id not in SAMPLE_MAP:
        raise HTTPException(status_code=404, detail="Sample not found")
    info = SAMPLE_MAP[sample_id]
    p = os.path.join(SAMPLES_DIR, info["filename"])
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Sample file missing on disk")
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()

    rep_name = os.path.splitext(info["filename"])[0]
    return _run_analysis(content, rep_name)


@app.post("/api/analyze")
def analyze_rdl(file: UploadFile = File(...)):
    """Ingests an .rdl file and returns a complete performance diagnostic report."""
    if not file.filename.lower().endswith((".rdl", ".xml")):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Please upload a valid .rdl or .xml report definition.",
        )

    try:
        content_bytes = file.file.read()
        content_str = content_bytes.decode("utf-8", errors="replace")
        report_name = os.path.splitext(file.filename)[0]
        return _run_analysis(content_str, report_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse and analyze RDL: {str(e)}")


@app.post("/api/optimize-sql")
def optimize_sql(req: QueryOptimizeRequest):
    """Generates an optimized SQL proposal with column pruning and sargability."""
    from backend.analyzer import detect_query_type_from_text
    q_type = detect_query_type_from_text(req.original_query)
    if q_type != "SQL":
        return {
            "source": "non_sql_guard",
            "query_type": q_type,
            "optimized_query": req.original_query,
            "suggested_query": req.original_query,
            "explanation": f"SQL comparison is unavailable for {q_type} datasets. SQL optimizations apply strictly to relational SQL queries.",
            "reasons": [f"Dataset utilizes {q_type} syntax. SQL transformations are not applicable."],
            "detected_issues": [f"Non-SQL query format ({q_type})"],
            "suggested_improvements": ["Non-SQL datasets are managed outside of the relational SQL optimizer."],
            "indexing_advice": f"N/A for {q_type} datasets.",
        }

    if req.use_ai:
        if azure_llm.is_available():
            ai_res = azure_llm.optimize_sql(req.original_query, req.used_fields, req.parameters)
            ai_res["query_type"] = "SQL"
            ai_res["optimized_query"] = ai_res.get("suggested_query", req.original_query)
            return ai_res
        elif ai_service.is_available():
            ai_res = ai_service.optimize_sql_ai(req.original_query, req.used_fields, req.parameters)
            ai_res["query_type"] = "SQL"
            return ai_res

    # Fallback to deterministic rule engine
    from backend.parser import DatasetInfo
    from backend.analyzer import SQLQueryAnalyzer

    dummy_ds = DatasetInfo(
        name=req.dataset_name,
        query_text=req.original_query,
        used_field_names=set(req.used_fields),
        unused_field_names=set(),
    )
    sql_analyzer = SQLQueryAnalyzer()
    _, opt = sql_analyzer.analyze(dummy_ds, {})
    res_sql = opt.suggested_query if opt else req.original_query
    return {
        "source": "rule_engine",
        "query_type": "SQL",
        "optimized_query": res_sql,
        "suggested_query": res_sql,
        "explanation": "Rule-based optimization applied (projected only bound fields, removed wildcards).",
        "reasons": opt.optimization_reasons if opt else ["No rule optimizations found."],
        "detected_issues": opt.detected_issues if opt else [],
        "suggested_improvements": opt.suggested_improvements if opt else [],
        "indexing_advice": "Verify that columns in WHERE predicates have appropriate nonclustered indexes.",
    }


@app.post("/api/ai-explain")
def ai_explain(req: AIExplainRequest):
    """Provides deep diagnostic explanation for a specific performance finding using Azure OpenAI."""
    if azure_llm.is_available():
        explanation = azure_llm.explain_issue(
            issue_title=req.title,
            target=req.target_object,
            description=req.description,
            impact=req.impact,
        )
    elif ai_service.is_available():
        explanation = ai_service.explain_issue(
            issue_title=req.title,
            target=req.target_object,
            description=req.description,
            impact=req.impact,
        )
    else:
        explanation = (
            f"**Rule-based Analysis**: {req.description}\n\n"
            f"**Engine Impact**: {req.impact}\n\n"
            f"_Tip: Azure OpenAI is not connected. Configure credentials in `.env` for AI-assisted insights._"
        )
    return {"explanation": explanation}


@app.post("/api/export")
def export_excel_report(analysis_data: Dict[str, Any]):
    """Generates a professional 5-tab Excel (.xlsx) diagnostic report matching client standards."""
    try:
        wb = openpyxl.Workbook()
        # Remove default sheet
        wb.remove(wb.active)

        # Style definitions
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        bold_font = Font(name="Calibri", size=11, bold=True)
        regular_font = Font(name="Calibri", size=10)
        italic_font = Font(name="Calibri", size=10, italic=True, color="595959")
        empty_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        border_thin = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )

        sev_colors = {
            "Critical": PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid"),
            "High": PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid"),
            "Medium": PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"),
            "Low": PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid"),
            "Info": PatternFill(start_color="EDF2F8", end_color="EDF2F8", fill_type="solid"),
        }

        # ======================================================================
        # Tab 1: 1 Detailed Findings (Short)
        # ======================================================================
        ws1 = wb.create_sheet(title="1 Detailed Findings (Short)")
        ws1.views.sheetView[0].showGridLines = True

        headers1 = [
            "Issue ID", "Category", "Severity", "Classification",
            "Title", "Target Object", "Description", "Engine Impact", "Remediation"
        ]
        for col_idx, h in enumerate(headers1, 1):
            cell = ws1.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        issues = analysis_data.get("issues", [])
        if issues:
            for r_idx, iss in enumerate(issues, 2):
                ws1.cell(row=r_idx, column=1, value=iss.get("id")).font = regular_font
                ws1.cell(row=r_idx, column=2, value=iss.get("category")).font = regular_font

                sev_cell = ws1.cell(row=r_idx, column=3, value=iss.get("severity"))
                sev_cell.font = bold_font
                sev_cell.alignment = Alignment(horizontal="center")
                if iss.get("severity") in sev_colors:
                    sev_cell.fill = sev_colors[iss.get("severity")]

                ws1.cell(row=r_idx, column=4, value=iss.get("classification")).font = regular_font
                ws1.cell(row=r_idx, column=5, value=iss.get("title")).font = bold_font
                ws1.cell(row=r_idx, column=6, value=iss.get("target_object")).font = regular_font
                ws1.cell(row=r_idx, column=7, value=iss.get("description")).font = regular_font
                ws1.cell(row=r_idx, column=8, value=iss.get("impact")).font = regular_font
                ws1.cell(row=r_idx, column=9, value=iss.get("remediation")).font = regular_font

                for c in range(1, 10):
                    cell = ws1.cell(row=r_idx, column=c)
                    cell.border = border_thin
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
        else:
            ws1.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers1))
            empty_cell = ws1.cell(row=2, column=1, value="No performance issues detected. Report satisfies enterprise standards.")
            empty_cell.font = italic_font
            empty_cell.fill = empty_fill
            empty_cell.alignment = Alignment(horizontal="center", vertical="center")

        # ======================================================================
        # Tab 2: 2 SQL Comparison
        # ======================================================================
        ws2 = wb.create_sheet(title="2 SQL Comparison")
        ws2.views.sheetView[0].showGridLines = True

        headers2 = [
            "Dataset Name", "Original SQL Query", "Suggested Optimized Query",
            "Optimization Reasons", "Pruned Columns", "Detected Issues", "Suggested Improvements"
        ]
        for col_idx, h in enumerate(headers2, 1):
            cell = ws2.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        raw_opts = analysis_data.get("dataset_optimizations", {})
        sql_opts = {
            k: v for k, v in raw_opts.items()
            if (v.get("query_type", "SQL") if isinstance(v, dict) else getattr(v, "query_type", "SQL")) == "SQL"
        }

        if sql_opts:
            for r_idx, (ds_name, opt) in enumerate(sql_opts.items(), 2):
                ws2.cell(row=r_idx, column=1, value=ds_name).font = bold_font
                ws2.cell(row=r_idx, column=2, value=opt.get("original_query", "")).font = regular_font
                ws2.cell(row=r_idx, column=3, value=opt.get("suggested_query", "")).font = regular_font

                reasons = "\n".join([f"• {r}" for r in opt.get("optimization_reasons", [])])
                ws2.cell(row=r_idx, column=4, value=reasons).font = regular_font

                pruned = ", ".join(opt.get("fields_pruned", [])) or "None"
                ws2.cell(row=r_idx, column=5, value=pruned).font = regular_font

                issues_list = "\n".join([f"• {i}" for i in opt.get("detected_issues", [])]) or "None"
                ws2.cell(row=r_idx, column=6, value=issues_list).font = regular_font

                improvements = "\n".join([f"• {s}" for s in opt.get("suggested_improvements", [])]) or "None"
                ws2.cell(row=r_idx, column=7, value=improvements).font = regular_font

                for c in range(1, 8):
                    cell = ws2.cell(row=r_idx, column=c)
                    cell.border = border_thin
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
        else:
            ws2.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers2))
            empty_cell = ws2.cell(row=2, column=1, value="No SQL datasets were detected in this report. SQL comparison is not applicable.")
            empty_cell.font = italic_font
            empty_cell.fill = empty_fill
            empty_cell.alignment = Alignment(horizontal="center", vertical="center")
            for c in range(1, len(headers2) + 1):
                ws2.cell(row=2, column=c).border = border_thin

        # ======================================================================
        # Tab 3: 3 Dataset Analysis
        # ======================================================================
        ws3 = wb.create_sheet(title="3 Dataset Analysis")
        ws3.views.sheetView[0].showGridLines = True

        headers3 = [
            "Dataset Name", "Query Type", "Data Source", "Command Type",
            "Retrieved Fields", "Referenced Fields", "Unused Columns (Prune-Safe)",
            "Visual References", "Detected Issues Count", "Used Field List", "Unused Field List"
        ]
        for col_idx, h in enumerate(headers3, 1):
            cell = ws3.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ds_inv = analysis_data.get("dataset_inventory", [])
        if not ds_inv:
            # Fallback to field_usage_matrix
            matrix = analysis_data.get("field_usage_matrix", {})
            ds_inv = [
                {
                    "name": ds_name,
                    "query_type": "SQL",
                    "data_source_name": "Embedded",
                    "command_type": "Text",
                    "fields_retrieved_count": info.get("total_fields", 0),
                    "fields_referenced_count": info.get("used_count", 0),
                    "unused_fields_count": info.get("unused_count", 0),
                    "visual_references_count": 1,
                    "detected_issues_count": sum(1 for iss in issues if ds_name in iss.get("target_object", "")),
                    "used_fields": info.get("used_fields", []),
                    "unused_fields": info.get("unused_fields", []),
                }
                for ds_name, info in matrix.items()
            ]

        for r_idx, ds in enumerate(ds_inv, 2):
            ws3.cell(row=r_idx, column=1, value=ds.get("name", "")).font = bold_font
            ws3.cell(row=r_idx, column=2, value=ds.get("query_type", "SQL")).font = regular_font
            ws3.cell(row=r_idx, column=3, value=ds.get("data_source_name", "Embedded")).font = regular_font
            ws3.cell(row=r_idx, column=4, value=ds.get("command_type", "Text")).font = regular_font
            ws3.cell(row=r_idx, column=5, value=ds.get("fields_retrieved_count", 0)).font = regular_font
            ws3.cell(row=r_idx, column=6, value=ds.get("fields_referenced_count", 0)).font = regular_font

            unused_c = ws3.cell(row=r_idx, column=7, value=ds.get("unused_fields_count", 0))
            unused_c.font = bold_font
            if ds.get("unused_fields_count", 0) > 0:
                unused_c.fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")

            ws3.cell(row=r_idx, column=8, value=ds.get("visual_references_count", 0)).font = regular_font
            ws3.cell(row=r_idx, column=9, value=ds.get("detected_issues_count", 0)).font = regular_font
            ws3.cell(row=r_idx, column=10, value=", ".join(ds.get("used_fields", []))).font = regular_font
            ws3.cell(row=r_idx, column=11, value=", ".join(ds.get("unused_fields", []))).font = regular_font

            for c in range(1, 12):
                cell = ws3.cell(row=r_idx, column=c)
                cell.border = border_thin
                cell.alignment = Alignment(vertical="top", wrap_text=True)

        # ======================================================================
        # Tab 4: 4 Parameter Analysis
        # ======================================================================
        ws4 = wb.create_sheet(title="4 Parameter Analysis")
        ws4.views.sheetView[0].showGridLines = True

        headers4 = [
            "Parameter Name", "Data Type", "Multi-Value", "Default Value",
            "Available Values Dataset", "SQL Parameter Usage", "Pushdown Status", "Detected Issues"
        ]
        for col_idx, h in enumerate(headers4, 1):
            cell = ws4.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        param_inv = analysis_data.get("parameter_inventory", [])
        if param_inv:
            for r_idx, prm in enumerate(param_inv, 2):
                ws4.cell(row=r_idx, column=1, value=prm.get("name", "")).font = bold_font
                ws4.cell(row=r_idx, column=2, value=prm.get("data_type", "String")).font = regular_font
                ws4.cell(row=r_idx, column=3, value=prm.get("multi_value", "No")).font = regular_font
                ws4.cell(row=r_idx, column=4, value=prm.get("default_value", "None")).font = regular_font
                ws4.cell(row=r_idx, column=5, value=prm.get("available_values_dataset", "Static / None")).font = regular_font
                ws4.cell(row=r_idx, column=6, value=prm.get("sql_parameter_usage", "None")).font = regular_font

                status_cell = ws4.cell(row=r_idx, column=7, value=prm.get("validation_status", "Validated"))
                status_cell.font = bold_font
                if "Action Required" in prm.get("validation_status", ""):
                    status_cell.fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
                elif "Validated" in prm.get("validation_status", ""):
                    status_cell.fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")

                issues_str = ", ".join(prm.get("detected_issues", [])) if prm.get("detected_issues") else "None"
                ws4.cell(row=r_idx, column=8, value=issues_str).font = regular_font

                for c in range(1, 9):
                    cell = ws4.cell(row=r_idx, column=c)
                    cell.border = border_thin
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
        else:
            ws4.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers4))
            empty_cell = ws4.cell(row=2, column=1, value="No report parameters defined.")
            empty_cell.font = italic_font
            empty_cell.fill = empty_fill
            empty_cell.alignment = Alignment(horizontal="center", vertical="center")
            for c in range(1, len(headers4) + 1):
                ws4.cell(row=2, column=c).border = border_thin

        # ======================================================================
        # Tab 5: 5 Optimization Tracker
        # ======================================================================
        ws5 = wb.create_sheet(title="5 Optimization Tracker")
        ws5.views.sheetView[0].showGridLines = True

        headers5 = [
            "Priority", "Finding ID", "Category", "Severity", "Target Object",
            "Action Item / Remediation", "Estimated Latency Impact", "Status",
            "Assigned Owner", "Target Sprint / Date", "Validation Notes"
        ]
        for col_idx, h in enumerate(headers5, 1):
            cell = ws5.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        if issues:
            # Sort findings by severity
            sev_rank = {"Critical": 1, "High": 2, "Medium": 3, "Low": 4, "Info": 5}
            sorted_issues = sorted(issues, key=lambda x: sev_rank.get(x.get("severity", "Low"), 99))

            for r_idx, iss in enumerate(sorted_issues, 2):
                sev = iss.get("severity", "Low")
                if sev in ("Critical", "High"):
                    prio = "P1 - Critical"
                    impact_est = "High (80–95% query speedup or major memory relief)"
                elif sev == "Medium":
                    prio = "P2 - Medium"
                    impact_est = "Moderate (reduces payload & serialization overhead)"
                else:
                    prio = "P3 - Low"
                    impact_est = "Low (architectural hygiene / best practice)"

                prio_cell = ws5.cell(row=r_idx, column=1, value=prio)
                prio_cell.font = bold_font
                prio_cell.alignment = Alignment(horizontal="center")

                ws5.cell(row=r_idx, column=2, value=iss.get("id")).font = regular_font
                ws5.cell(row=r_idx, column=3, value=iss.get("category")).font = regular_font

                sev_cell = ws5.cell(row=r_idx, column=4, value=sev)
                sev_cell.font = bold_font
                sev_cell.alignment = Alignment(horizontal="center")
                if sev in sev_colors:
                    sev_cell.fill = sev_colors[sev]

                ws5.cell(row=r_idx, column=5, value=iss.get("target_object")).font = regular_font
                ws5.cell(row=r_idx, column=6, value=iss.get("remediation")).font = regular_font
                ws5.cell(row=r_idx, column=7, value=impact_est).font = regular_font

                status_cell = ws5.cell(row=r_idx, column=8, value="Not Started")
                status_cell.font = regular_font
                status_cell.alignment = Alignment(horizontal="center")

                ws5.cell(row=r_idx, column=9, value="").font = regular_font  # Assigned Owner
                ws5.cell(row=r_idx, column=10, value="").font = regular_font # Target Sprint
                ws5.cell(row=r_idx, column=11, value="").font = regular_font # Validation Notes

                for c in range(1, 12):
                    cell = ws5.cell(row=r_idx, column=c)
                    cell.border = border_thin
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
        else:
            ws5.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers5))
            empty_cell = ws5.cell(row=2, column=1, value="Report meets all performance benchmarks. No active remediation items tracked.")
            empty_cell.font = italic_font
            empty_cell.fill = empty_fill
            empty_cell.alignment = Alignment(horizontal="center", vertical="center")
            for c in range(1, len(headers5) + 1):
                ws5.cell(row=2, column=c).border = border_thin

        # Auto-adjust column widths across all sheets
        for sheet in wb.worksheets:
            for col in sheet.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = get_column_letter(col[0].column)
                sheet.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 65)

        stream = io.BytesIO()
        wb.save(stream)
        stream.seek(0)

        filename = f"Xebia_Diagnostic_{analysis_data.get('report_name', 'Report')}.xlsx"
        return StreamingResponse(
            stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate Excel export: {str(e)}")


@app.post("/api/export-html")
def export_html_report_endpoint(analysis_data: Dict[str, Any]):
    """Generates a downloadable, self-contained HTML performance report."""
    try:
        rpt_id = generate_unique_report_id()
        html_str = generate_html_report(
            analysis_data=analysis_data,
            report_id=rpt_id,
            azure_llm=azure_llm,
        )
        filename = f"Paginated_Report_Performance_Analysis_{rpt_id}.html"

        return StreamingResponse(
            io.BytesIO(html_str.encode("utf-8")),
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate HTML export: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
