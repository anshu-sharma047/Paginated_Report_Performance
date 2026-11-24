"""
HTML Report Generator
Generates a downloadable, professional, self-contained HTML performance report
for Power BI Paginated Reports (.rdl) using Jinja2 and Azure OpenAI.
Embedded CSS & JavaScript ensure 100% offline viewing and printing.
"""

from __future__ import annotations
import os
import re
import uuid
import base64
from datetime import datetime
from typing import Dict, List, Optional, Any
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.azure_llm import AzureOpenAIService

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
ASSETS_DIR = os.path.join(ROOT_DIR, "frontend", "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "xebia_logo.png")


def get_logo_base64() -> str:
    """Returns base64-encoded Xebia brand logo for offline self-containment."""
    if os.path.exists(LOGO_PATH):
        try:
            with open(LOGO_PATH, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return ""
    return ""


def generate_unique_report_id() -> str:
    """Generates an enterprise-standard unique report identifier."""
    date_str = datetime.now().strftime("%Y%m%d")
    short_uuid = uuid.uuid4().hex[:6].upper()
    return f"RPT-{date_str}-{short_uuid}"


def generate_html_report(
    analysis_data: Dict[str, Any],
    parsed_rdl: Optional[Any] = None,
    report_id: Optional[str] = None,
    azure_llm: Optional[AzureOpenAIService] = None,
) -> str:
    """
    Renders a comprehensive, self-contained HTML diagnostic report.

    Parameters:
        analysis_data: Dictionary containing analysis findings, metrics, and health score.
        parsed_rdl: Optional ParsedRDL object with raw dataset & parameter objects.
        report_id: Optional custom report ID; auto-generated if omitted.
        azure_llm: Optional AzureOpenAIService instance for executive reasoning.
    """
    llm = azure_llm or AzureOpenAIService()
    rpt_id = report_id or generate_unique_report_id()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report_name = analysis_data.get("report_name", "Paginated_Report")
    health_score = int(analysis_data.get("health_score", 50))
    health_status = analysis_data.get("health_status", "Evaluation Complete")
    summary_metrics = analysis_data.get("summary_metrics", {})
    issues = analysis_data.get("issues", [])
    raw_opts = analysis_data.get("dataset_optimizations", {})
    dataset_optimizations = {
        k: v for k, v in raw_opts.items()
        if (v.get("query_type", "SQL") if isinstance(v, dict) else getattr(v, "query_type", "SQL")) == "SQL"
    }

    total_sql_queries = int(summary_metrics.get("total_sql_queries", 0))
    if total_sql_queries == 0 and parsed_rdl and hasattr(parsed_rdl, "datasets"):
        from backend.analyzer import detect_query_type
        total_sql_queries = sum(1 for ds in parsed_rdl.datasets.values() if detect_query_type(ds) == "SQL" and ds.query_text)

    # 1. Build Dataset Inventory
    dataset_inventory: List[Dict[str, Any]] = []
    if parsed_rdl and hasattr(parsed_rdl, "datasets"):
        for ds_name, ds in parsed_rdl.datasets.items():
            visual_refs = [v.name for v in getattr(parsed_rdl, "visuals", []) if getattr(v, "dataset_name", None) == ds_name]
            ds_issues = [
                i for i in issues
                if ds_name in i.get("target_object", "") or ds_name in i.get("description", "")
            ]
            dataset_inventory.append({
                "name": ds_name,
                "query_type": getattr(ds, "query_type", "SQL"),
                "dependency_type": getattr(ds, "dependency_type", "Visual Bound"),
                "is_orphan": getattr(ds, "is_orphan", False),
                "data_source_name": getattr(ds, "data_source_name", "Embedded") or "Embedded",
                "command_type": getattr(ds, "command_type", "Text") or "Text",
                "query_length": len(getattr(ds, "query_text", "") or ""),
                "query_text": getattr(ds, "query_text", "") or "",
                "fields_retrieved_count": len(getattr(ds, "fields", [])),
                "fields_referenced_count": len(getattr(ds, "used_field_names", set())),
                "unused_fields_count": len(getattr(ds, "unused_field_names", set())),
                "used_fields": sorted(list(getattr(ds, "used_field_names", set()))),
                "unused_fields": sorted(list(getattr(ds, "unused_field_names", set()))),
                "visual_references_count": len(visual_refs) or getattr(ds, "referenced_in_visuals", 0),
                "detected_issues_count": len(ds_issues),
            })
    elif "dataset_inventory" in analysis_data:
        dataset_inventory = analysis_data["dataset_inventory"]
    else:
        # Fallback dataset inventory from field_usage_matrix & dataset_optimizations
        matrix = analysis_data.get("field_usage_matrix", {})
        for ds_name, info in matrix.items():
            opt = dataset_optimizations.get(ds_name, {})
            ds_issues = [i for i in issues if ds_name in i.get("target_object", "")]
            dataset_inventory.append({
                "name": ds_name,
                "query_type": "SQL",
                "dependency_type": "Visual Bound",
                "is_orphan": False,
                "data_source_name": "Relational DW",
                "command_type": "Text",
                "query_length": len(opt.get("original_query", "")),
                "query_text": opt.get("original_query", ""),
                "fields_retrieved_count": info.get("total_fields", 0),
                "fields_referenced_count": info.get("used_count", 0),
                "unused_fields_count": info.get("unused_count", 0),
                "used_fields": info.get("used_fields", []),
                "unused_fields": info.get("unused_fields", []),
                "visual_references_count": 1,
                "detected_issues_count": len(ds_issues),
            })

    # 2. Build Parameter Inventory
    parameter_inventory: List[Dict[str, Any]] = []
    if parsed_rdl and hasattr(parsed_rdl, "parameters"):
        for prm_name, prm in parsed_rdl.parameters.items():
            # Check SQL query references
            sql_usage = [
                ds_name
                for ds_name, ds in getattr(parsed_rdl, "datasets", {}).items()
                if getattr(ds, "query_text", None)
                and re.search(rf"@{re.escape(prm_name)}\b", ds.query_text, re.IGNORECASE)
            ]
            valid_ds = getattr(prm, "valid_values_dataset", None)
            default_ds = getattr(prm, "default_values_dataset", None)

            # Check if used in dataset filters or query parameters
            ds_filter_usage = [
                ds_name
                for ds_name, ds in getattr(parsed_rdl, "datasets", {}).items()
                if any(prm_name.lower() in flt.expression.lower() or any(prm_name.lower() in str(v).lower() for v in flt.values) for flt in getattr(ds, "filters", []))
            ]
            qp_usage = [
                ds_name
                for ds_name, ds in getattr(parsed_rdl, "datasets", {}).items()
                if any(prm_name.lower() == qp.name.lstrip("@").lower() or prm_name.lower() in qp.value.lower() for qp in getattr(ds, "query_parameters", []))
            ]

            is_inert = any(i.get("id") == f"PARAM-INERT-REPORT-{prm_name}" for i in issues)

            if is_inert:
                is_pushed = False
                validation_status = "Potential Functional Defect"
                mapping_str = "None (Unreferenced in Report)"
            elif total_sql_queries > 0:
                is_pushed = len(sql_usage) > 0 or len(qp_usage) > 0
                validation_status = "Validated against RDL metadata (Pushed to SQL)" if is_pushed else "Requires Action (Not Pushed)"
                active_mappings = list(dict.fromkeys(sql_usage + qp_usage))
                mapping_str = ", ".join(active_mappings) if active_mappings else "None"
            else:
                # Non-SQL / EnterData / XML report
                if ds_filter_usage:
                    is_pushed = True
                    validation_status = "Applied in Dataset Filter"
                    mapping_str = f"Filter in {', '.join(ds_filter_usage)}"
                elif valid_ds:
                    is_pushed = True
                    validation_status = f"Lookup Dataset ({valid_ds})"
                    mapping_str = f"Available Values: {valid_ds}"
                elif qp_usage:
                    is_pushed = False
                    validation_status = "Inert Query Parameter"
                    mapping_str = f"QueryParam in {', '.join(qp_usage)}"
                else:
                    is_pushed = False
                    validation_status = "Unused Parameter"
                    mapping_str = "None"

            avail_ds_str = valid_ds if valid_ds else ("Default Dataset: " + default_ds if default_ds else "Static / Single-value")

            parameter_inventory.append({
                "name": prm_name,
                "data_type": getattr(prm, "data_type", "String"),
                "multi_value": "Yes" if getattr(prm, "multi_value", False) else "No",
                "default_value": ", ".join(getattr(prm, "default_values", [])) if getattr(prm, "default_values", []) else "None",
                "available_values_dataset": avail_ds_str,
                "dataset_parameter_mapping": mapping_str,
                "sql_parameter_usage": mapping_str,
                "validation_status": validation_status,
                "is_pushed_to_sql": is_pushed,
            })
    elif "parameter_inventory" in analysis_data:
        parameter_inventory = analysis_data["parameter_inventory"]

    # Dedicated Helper for Tailored Tracker Actions and Expected Outcomes
    def get_tracker_action_and_outcome(iss: Dict[str, Any]) -> Tuple[str, str]:
        fid = iss.get("id", "")
        target = iss.get("target_object", "")
        remediation = iss.get("remediation", "")

        if fid.startswith("SQL-STAR"):
            return (
                f"Replace wildcard SELECT * in {target} with explicit projection of fields actually consumed by report visuals.",
                "Eliminates retrieval of unreferenced table columns, enables database index-covering query plans, and lowers memory overhead in Power BI Service."
            )
        elif fid.startswith("SQL-SARGABLE"):
            return (
                f"Rewrite non-SARGable predicate in {target} using a half-open date/value interval. Confirm an index exists on the filtered column.",
                "Enables database engine to perform an efficient Index Seek instead of a full table or clustered index scan."
            )
        elif fid.startswith("SQL-NOWHERE"):
            return (
                f"Add parameterized WHERE clause to {target} to filter data at the database source.",
                "Prevents full table scans and restricts row retrieval across the network."
            )
        elif fid.startswith("SQL-UNUSED-COLS"):
            return (
                f"Prune unreferenced columns from {target} query definition and dataset field list.",
                "Reduces tabular row-buffer width and data serialization size across the gateway."
            )
        elif fid.startswith("SQL-CARTESIAN"):
            return (
                f"Refactor comma-separated joins in {target} to explicit ANSI INNER JOIN ... ON syntax.",
                "Prevents accidental Cartesian product row multiplication and excessive tempdb allocation."
            )
        elif fid.startswith("PARAM-INERT-REPORT"):
            return (
                f"Review business requirements for {target}. If parameter should filter visuals, implement conditional filtering (supporting 'All'); otherwise remove it.",
                "Resolves functional defect where user parameter selections currently have no effect on report output."
            )
        elif fid.startswith("PARAM-UNPUSHED"):
            return (
                f"Map {target} into the SQL query WHERE clause using conditional parameter binding.",
                "Pushes filtering to the database engine, avoiding downloading unconstrained rows into report memory."
            )
        elif fid.startswith("PARAM-INERT-FILTER"):
            return (
                f"Add an explicit Tablix filter or Dataset filter on {target} to apply parameter value.",
                "Ensures parameter selection actively filters embedded static data."
            )
        elif fid.startswith("PARAM-DS-FILTER") or fid.startswith("PARAM-TABLIX-FILTER"):
            return (
                f"Push in-memory filter on {target} into the SQL query WHERE clause where applicable.",
                "Discards unneeded rows at the database engine prior to gateway transmission."
            )
        elif fid.startswith("STRUCT-ORPHAN-DS"):
            ds_clean = target.replace("Dataset: ", "").replace("Dataset (SQL): ", "")
            return (
                f"Validate dependencies and remove unused dataset '{ds_clean}' from the report definition.",
                "Eliminates redundant database query execution and connection overhead during report initialization."
            )
        elif fid.startswith("STRUCT-SUBREPORT-ROW"):
            return (
                f"Flatten repeating subreport in {target} into master query JOIN or native Tablix grouping.",
                "Eliminates N+1 query roundtrips, reducing query executions from O(N) to O(1)."
            )
        elif fid.startswith("EXPR-NESTED-IIF"):
            return (
                f"Refactor nested IIF in {target} to Switch() or SQL CASE expression.",
                "Prevents double-branch evaluation in VB.NET engine for every rendered row."
            )
        elif fid.startswith("EXPR-CONVERSION"):
            return (
                f"Cast data types directly at query source or set explicit dataset field types for {target}.",
                "Eliminates per-cell runtime VB.NET type conversions during pagination."
            )

        return (
            remediation or "Optimize query or parameter mapping.",
            "Reduces query execution latency and eliminates memory serialization overhead."
        )

    # 3. Construct Prioritized Remediation Action Plan
    action_plan: List[Dict[str, Any]] = []
    for idx, iss in enumerate(issues):
        sev = iss.get("severity", "Medium")
        if sev in ("Critical", "High"):
            priority = "P1" if idx == 0 else "P2"
        elif sev == "Medium":
            priority = "P3"
        else:
            priority = "P4"

        action_text, outcome_text = get_tracker_action_and_outcome(iss)
        action_plan.append({
            "priority": priority,
            "finding_id": iss.get("id", f"ISS-{idx+1}"),
            "target": iss.get("target_object", "Report"),
            "action": action_text,
            "expected_outcome": outcome_text,
            "validation_status": iss.get("validation_status", "Validated against RDL metadata"),
            "owner": "",
            "status": "Not Started",
            "validation_notes": "",
        })

    # Sort action plan by priority (P1 -> P2 -> P3 -> P4)
    p_rank = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
    action_plan.sort(key=lambda x: p_rank.get(x["priority"], 99))

    # 4. Generate Executive Assessment via Azure OpenAI (or Rule-Based Fallback)
    executive_assessment = llm.generate_executive_assessment(
        report_name=report_name,
        health_score=health_score,
        health_status=health_status,
        metrics=summary_metrics,
        issues=issues,
    )

    # 5. Load Jinja2 Template and Render
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("report_template.html")

    html_content = template.render(
        report_id=rpt_id,
        report_name=report_name,
        generation_time=now_str,
        analyzer_version="v1.0.0 (Xebia Enterprise Accelerator)",
        analysis_type="Static RDL Analysis (AST & Rules + AI Advisory)",
        health_score=health_score,
        health_status=health_status,
        total_sql_queries=total_sql_queries,
        metrics=summary_metrics,
        issues=issues,
        dataset_optimizations=dataset_optimizations,
        dataset_inventory=dataset_inventory,
        parameter_inventory=parameter_inventory,
        action_plan=action_plan,
        executive_assessment_html=executive_assessment,
        logo_b64=get_logo_base64(),
    )

    return html_content
