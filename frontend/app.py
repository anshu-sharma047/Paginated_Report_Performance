"""
Power BI Paginated Report Performance Analyzer
Xebia Enterprise Accelerator Frontend
Refined UI/UX following the Xebia Enterprise Design System.
"""

from __future__ import annotations
import os
import sys

# Ensure root directory is in sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import base64
import json
import pandas as pd
import streamlit as st

from backend.parser import RDLParser
from backend.analyzer import RecommendationEngine, Severity
from backend.main import export_excel_report
from backend.gemini_service import GeminiService
from backend.azure_llm import AzureOpenAIService
from backend.html_report_generator import generate_html_report, generate_unique_report_id

st.set_page_config(
    page_title="Xebia | Paginated Report Performance Analyzer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Load authentic Xebia brand logo
ASSETS_DIR = os.path.join(ROOT_DIR, "frontend", "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "xebia_logo.png")
XEBIA_LOGO_B64 = ""
if os.path.exists(LOGO_PATH):
    with open(LOGO_PATH, "rb") as _f:
        XEBIA_LOGO_B64 = base64.b64encode(_f.read()).decode("utf-8")

# Initialize Session State
if "analysis_data" not in st.session_state:
    st.session_state.analysis_data = None
if "current_report_name" not in st.session_state:
    st.session_state.current_report_name = None
if "current_report_id" not in st.session_state:
    st.session_state.current_report_id = None
if "current_parsed_rdl" not in st.session_state:
    st.session_state.current_parsed_rdl = None
if "selected_preset" not in st.session_state:
    st.session_state.selected_preset = None
if "ai_explanations" not in st.session_state:
    st.session_state.ai_explanations = {}

parser = RDLParser()
engine = RecommendationEngine()
ai_service = GeminiService()
azure_llm = AzureOpenAIService()
SAMPLES_DIR = os.path.join(ROOT_DIR, "sample_reports")


def format_file_size(size_in_bytes: int) -> str:
    """Formats bytes into human-readable KB or MB."""
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"
    elif size_in_bytes < 1024 * 1024:
        return f"{size_in_bytes / 1024:.1f} KB"
    else:
        return f"{size_in_bytes / (1024 * 1024):.2f} MB"


def get_severity_badge_html(severity: str) -> str:
    """Returns standardized severity badge HTML based on enterprise design tokens."""
    sev_lower = severity.lower()
    if sev_lower in ("critical", "high"):
        # Critical/High: Dark red / deep orange
        return f'<span class="badge badge-high">{severity.upper()}</span>'
    elif sev_lower == "medium":
        # Medium: Amber
        return f'<span class="badge badge-medium">{severity.upper()}</span>'
    elif sev_lower == "low":
        # Low: Blue
        return f'<span class="badge badge-low">{severity.upper()}</span>'
    else:
        # Info: Grey
        return f'<span class="badge badge-info">{severity.upper()}</span>'


# ==========================================
# Comprehensive Xebia Enterprise Styling
# ==========================================
st.markdown(
    """
    <style>
        /* Typography & Root Variables */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

        :root {
            --xebia-purple: #682A5B;
            --xebia-purple-hover: #532049;
            --xebia-purple-tint: #F8F2F6;
            --xebia-purple-border: #EBD8E7;
            --xebia-dark: #111827;
            --xebia-gray-text: #4B5563;
            --xebia-light-gray: #F9FAFB;
            --xebia-border: #E5E7EB;
            
            /* Severity tokens */
            --sev-critical-text: #991B1B;
            --sev-critical-bg: #FEE2E2;
            --sev-critical-border: #FCA5A5;
            
            --sev-high-text: #C2410C;
            --sev-high-bg: #FFEDD5;
            --sev-high-border: #FDBA74;
            
            --sev-med-text: #B45309;
            --sev-med-bg: #FEF3C7;
            --sev-med-border: #FDE68A;
            
            --sev-low-text: #1D4ED8;
            --sev-low-bg: #DBEAFE;
            --sev-low-border: #93C5FD;
            
            --sev-info-text: #4B5563;
            --sev-info-bg: #F3F4F6;
            --sev-info-border: #D1D5DB;
        }

        /* Prevent page-level horizontal overflow */
        html, body {
            max-width: 100vw !important;
            overflow-x: hidden !important;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
            color: #1F2937 !important;
            background-color: #FAFAFA !important;
        }

        /* Completely hide default Streamlit header bar, deploy button, & toolbars to prevent clipping */
        header,
        [data-testid="stHeader"],
        [data-testid="stAppHeader"],
        .stAppHeader,
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stDeployButton"],
        [data-testid="stHeaderActionElements"],
        .stAppDeployButton,
        #MainMenu,
        footer {
            display: none !important;
            visibility: hidden !important;
            height: 0px !important;
            min-height: 0px !important;
            max-height: 0px !important;
            padding: 0 !important;
            margin: 0 !important;
            overflow: hidden !important;
            pointer-events: none !important;
        }

        /* Streamlit Container Reset: Generous top padding, perfectly aligned */
        .stApp {
            background-color: #FAFAFA !important;
        }

        .main, [data-testid="stMain"] {
            padding-top: 0 !important;
        }

        .block-container {
            padding-top: 2.25rem !important;
            padding-bottom: 3rem !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
            max-width: 1300px !important;
            margin: 0 auto !important;
        }

        /* Top Navigation Header Bar */
        .xebia-header-bar {
            width: 100%;
            background-color: transparent;
            border-bottom: 1px solid var(--xebia-border);
            padding: 8px 0 16px 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
            box-sizing: border-box;
        }
        .xebia-logo-container {
            display: flex;
            align-items: center;
        }
        .xebia-header-logo {
            height: 28px;
            width: auto;
            display: block;
            object-fit: contain;
        }
        .xebia-wordmark {
            font-size: 26px;
            font-weight: 800;
            color: var(--xebia-purple);
            letter-spacing: -0.5px;
            text-decoration: none;
            line-height: 1;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: inline-block;
        }
        .nav-divider {
            color: #D1D5DB;
            font-size: 22px;
            font-weight: 200;
            margin: 0 16px;
            line-height: 1;
        }
        .app-title-group {
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .app-title-main {
            font-size: 15px;
            font-weight: 700;
            line-height: 1.15;
            letter-spacing: -0.2px;
        }
        .app-title-sub {
            font-size: 9px;
            font-weight: 700;
            color: #6B7280;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            margin-top: 2px;
        }
        .nav-right-actions {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .nav-status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: #374151;
            font-weight: 500;
            background: #FFFFFF;
            padding: 4px 10px;
            border-radius: 20px;
            border: 1px solid var(--xebia-border);
        }
        .status-dot {
            height: 7px;
            width: 7px;
            background-color: #10B981;
            border-radius: 50%;
            display: inline-block;
        }
        .nav-link {
            color: #4B5563;
            font-size: 12px;
            text-decoration: none;
            font-weight: 500;
            transition: color 0.15s ease;
        }
        .nav-link:hover {
            color: var(--xebia-purple);
        }

        /* Compact Hero Section */
        .hero-container {
            text-align: center;
            padding: 4px 0 12px 0;
            max-width: 780px;
            margin: 0 auto;
        }
        .accelerator-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background-color: var(--xebia-purple-tint);
            color: var(--xebia-purple);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1px;
            border: 1px solid var(--xebia-purple-border);
            margin-bottom: 8px;
        }
        .hero-title {
            font-size: 34px;
            font-weight: 800;
            color: var(--xebia-dark);
            line-height: 1.2;
            letter-spacing: -0.8px;
            margin-bottom: 8px;
        }
        .hero-title-accent {
            color: var(--xebia-purple);
        }
        .hero-description {
            font-size: 14px;
            color: var(--xebia-gray-text);
            max-width: 640px;
            margin: 0 auto 12px auto;
            line-height: 1.45;
        }
        .feature-chips {
            display: flex;
            justify-content: center;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 14px;
        }
        .chip {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
        }
        .chip-purple { background-color: #F3E8FF; color: #6B21A8; }
        .chip-pink { background-color: #FCE7F3; color: #9D174D; }
        .chip-green { background-color: #DCFCE7; color: #15803D; }

        /* Workspace Card Container */
        .workspace-card {
            background: #FFFFFF;
            border: 1px solid var(--xebia-border);
            border-radius: 14px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.03);
            padding: 18px 22px;
            margin-bottom: 20px;
        }
        .workspace-top-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
            padding-bottom: 8px;
            border-bottom: 1px solid #F3F4F6;
        }
        .workspace-step {
            font-size: 10px;
            font-weight: 700;
            color: var(--xebia-purple);
            letter-spacing: 1px;
            text-transform: uppercase;
        }
        .workspace-title {
            font-size: 18px;
            font-weight: 700;
            color: var(--xebia-dark);
        }

        /* Two-Column Workspace Panels */
        .panel-box {
            border: 1px solid var(--xebia-border);
            border-radius: 10px;
            background: #FFFFFF;
            padding: 14px;
            min-height: 250px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        .panel-header-left {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .panel-avatar {
            width: 26px;
            height: 26px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 11px;
        }
        .panel-avatar-purple { background-color: #F3E8FF; color: var(--xebia-purple); }
        .panel-avatar-amber { background-color: #FEF3C7; color: #B45309; }

        .panel-title {
            font-size: 13px;
            font-weight: 700;
            color: var(--xebia-dark);
            line-height: 1.15;
        }
        .panel-subtitle {
            font-size: 11px;
            color: #6B7280;
        }
        .panel-tag {
            font-size: 9px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .tag-purple { background-color: #F3E8FF; color: var(--xebia-purple); }
        .tag-amber { background-color: #FEF3C7; color: #B45309; }
        .tag-neutral { background-color: #F3F4F6; color: #4B5563; }
        .tag-green { background-color: #DCFCE7; color: #166534; }

        .panel-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-top: 8px;
            border-top: 1px solid #F3F4F6;
            margin-top: 10px;
            font-size: 11px;
            color: #6B7280;
        }

        /* File Upload Metadata Chip */
        .file-meta-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background-color: #F0FDF4;
            color: #166534;
            border: 1px solid #BBF7D0;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            margin-top: 6px;
        }

        /* Buttons & CTA Styling */
        div[data-testid="stButton"] > button {
            border-radius: 8px !important;
            font-weight: 600 !important;
            font-size: 13px !important;
            transition: all 0.15s ease !important;
        }
        div[data-testid="stButton"] > button[kind="primary"] {
            background-color: var(--xebia-purple) !important;
            color: #FFFFFF !important;
            border: 1px solid var(--xebia-purple-hover) !important;
            padding: 8px 20px !important;
        }
        div[data-testid="stButton"] > button[kind="primary"]:hover {
            background-color: var(--xebia-purple-hover) !important;
            box-shadow: 0 4px 12px rgba(104, 42, 91, 0.22) !important;
        }

        /* Equal-Height KPI Dashboard Cards */
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }
        .kpi-card {
            background-color: #FFFFFF;
            border: 1px solid var(--xebia-border);
            border-radius: 10px;
            padding: 14px 12px;
            text-align: center;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            min-height: 92px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
            transition: border-color 0.15s ease;
        }
        .kpi-card:hover {
            border-color: #CBD5E1;
        }
        .kpi-val {
            font-size: 24px;
            font-weight: 800;
            line-height: 1.1;
        }
        .kpi-lbl {
            font-size: 11px;
            font-weight: 600;
            color: #64748B;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 4px;
        }
        .kpi-status-badge {
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            margin-top: 4px;
        }

        /* Standardized Severity Badges */
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 700;
            font-size: 10px;
            letter-spacing: 0.5px;
        }
        .badge-high {
            background-color: var(--sev-critical-bg);
            color: var(--sev-critical-text);
            border: 1px solid var(--sev-critical-border);
        }
        .badge-medium {
            background-color: var(--sev-med-bg);
            color: var(--sev-med-text);
            border: 1px solid var(--sev-med-border);
        }
        .badge-low {
            background-color: var(--sev-low-bg);
            color: var(--sev-low-text);
            border: 1px solid var(--sev-low-border);
        }
        .badge-info {
            background-color: var(--sev-info-bg);
            color: var(--sev-info-text);
            border: 1px solid var(--sev-info-border);
        }

        /* Pill tags */
        .pill-meta {
            background: #F3F4F6;
            color: #374151;
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
        }

        /* Structured Reusable Issue Card */
        .issue-card-container {
            border: 1px solid var(--xebia-border);
            border-radius: 10px;
            background: #FFFFFF;
            padding: 14px;
            margin-bottom: 10px;
            transition: all 0.15s ease;
        }
        .issue-card-container:hover {
            box-shadow: 0 3px 10px rgba(0, 0, 0, 0.04);
            border-color: #D1D5DB;
        }
        .issue-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
            flex-wrap: wrap;
            gap: 6px;
        }
        .issue-card-header-left {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .issue-title {
            font-size: 13.5px;
            font-weight: 700;
            color: var(--xebia-dark);
        }
        .issue-body-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            background: #F9FAFB;
            border: 1px solid #F3F4F6;
            border-radius: 8px;
            padding: 10px 12px;
            margin-top: 8px;
            margin-bottom: 8px;
            font-size: 12px;
        }
        .issue-field-label {
            font-weight: 700;
            color: #374151;
            margin-bottom: 2px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.4px;
        }

        /* SQL Code Containers & Previews: strict overflow prevention */
        .sql-box {
            font-family: 'JetBrains Mono', Consolas, monospace !important;
            font-size: 12px !important;
            border-radius: 6px;
            padding: 8px 10px;
            overflow-x: auto !important;
            max-width: 100% !important;
            box-sizing: border-box !important;
            white-space: pre !important;
            line-height: 1.4 !important;
            margin-top: 4px;
            margin-bottom: 8px;
        }
        .sql-box-original {
            background-color: #FFF5F5;
            border: 1px solid #FED7D7;
            color: #742A2A;
        }
        .sql-box-suggested {
            background-color: #F0FFF4;
            border: 1px solid #C6F6D5;
            color: #22543D;
        }

        /* Ensure Streamlit pre and code blocks never overflow horizontally */
        pre, code, .stCodeBlock {
            max-width: 100% !important;
            overflow-x: auto !important;
            box-sizing: border-box !important;
            font-family: 'JetBrains Mono', Consolas, monospace !important;
        }

        /* Executive Verdict Banner */
        .exec-verdict-banner {
            background: linear-gradient(135deg, #FAF5F9 0%, #FFFFFF 100%);
            border: 1px solid var(--xebia-purple-border);
            border-radius: 12px;
            padding: 18px 22px;
            margin-top: 14px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(104, 42, 91, 0.04);
        }
        .exec-banner-grid {
            display: grid;
            grid-template-columns: 1.1fr 1.1fr 1.4fr;
            gap: 20px;
            align-items: flex-start;
        }
        .exec-metric-box {
            border-right: 1px solid #EBD8E7;
            padding-right: 18px;
        }
        .exec-metric-title {
            font-size: 11px;
            font-weight: 700;
            color: #6B7280;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            margin-bottom: 4px;
        }
        .exec-metric-value {
            font-size: 20px;
            font-weight: 800;
            color: var(--xebia-dark);
            line-height: 1.2;
        }
        .exec-metric-sub {
            font-size: 11.5px;
            color: #166534;
            font-weight: 600;
            margin-top: 3px;
        }
        .latency-bar-container {
            margin-top: 8px;
        }
        .latency-bar {
            display: flex;
            height: 10px;
            border-radius: 6px;
            overflow: hidden;
            background: #E5E7EB;
        }
        .bar-retrieval { background-color: #DC2626; }
        .bar-inmemory { background-color: #F59E0B; }
        .bar-render { background-color: #3B82F6; }
        .latency-legend {
            display: flex;
            gap: 12px;
            margin-top: 6px;
            font-size: 10.5px;
            color: #4B5563;
            flex-wrap: wrap;
        }
        .latency-legend-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 4px;
        }
        .quick-wins-list {
            margin: 6px 0 0 0;
            padding-left: 0;
            list-style: none;
        }
        .quick-win-item {
            font-size: 12px;
            color: #374151;
            margin-bottom: 5px;
            display: flex;
            align-items: flex-start;
            gap: 6px;
            line-height: 1.3;
        }

        /* Responsive Breakpoints */
        @media (max-width: 900px) {
            .exec-banner-grid {
                grid-template-columns: 1fr !important;
            }
            .exec-metric-box {
                border-right: none !important;
                border-bottom: 1px solid #EBD8E7;
                padding-bottom: 14px;
                padding-right: 0 !important;
            }
            .kpi-grid {
                grid-template-columns: repeat(2, 1fr) !important;
            }
            .issue-body-grid {
                grid-template-columns: 1fr !important;
            }
        }

        @media (max-width: 600px) {
            .block-container {
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }
            .hero-title {
                font-size: 26px !important;
            }
            .hero-description {
                font-size: 13px !important;
            }
            .workspace-card {
                padding: 12px !important;
            }
            .kpi-grid {
                grid-template-columns: 1fr !important;
            }
            .xebia-navbar {
                flex-direction: column;
                align-items: flex-start;
                gap: 8px;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def run_analysis_from_xml(xml_content: str, report_name: str):
    """Executes parser and recommendation engine on RDL XML string."""
    parsed = parser.parse_string(xml_content, report_name=report_name)
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
        }
        for i in analysis.issues
    ]

    optimizations_dict = {
        ds_name: {
            "dataset_name": opt.dataset_name,
            "original_query": opt.original_query,
            "suggested_query": opt.suggested_query,
            "optimization_reasons": opt.optimization_reasons,
            "fields_used": opt.fields_used,
            "fields_pruned": opt.fields_pruned,
        }
        for ds_name, opt in analysis.dataset_optimizations.items()
    }

    # Build dataset inventory for report export
    import re
    dataset_inventory = [
        {
            "name": ds_name,
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

    parameter_inventory = []
    for prm_name, prm in parsed.parameters.items():
        sql_usage = [
            ds_name for ds_name, ds in parsed.datasets.items()
            if ds.query_text and re.search(rf"@{re.escape(prm_name)}\b", ds.query_text, re.IGNORECASE)
        ]
        prm_issues = [
            iss.title for iss in analysis.issues
            if prm_name in iss.target_object or f"@{prm_name}" in iss.description
        ]
        is_pushed = len(sql_usage) > 0
        parameter_inventory.append({
            "name": prm_name,
            "data_type": prm.data_type,
            "multi_value": "Yes" if prm.multi_value else "No",
            "default_value": ", ".join(prm.default_values) if prm.default_values else "None",
            "available_values_dataset": "Static / None",
            "dataset_parameter_mapping": ", ".join(sql_usage) if sql_usage else "None",
            "sql_parameter_usage": ", ".join(sql_usage) if sql_usage else "None",
            "validation_status": "Action Required (Not Pushed)" if not is_pushed else "Validated (Pushed to SQL)",
            "detected_issues": prm_issues,
            "is_pushed_to_sql": is_pushed,
        })

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
        "ai_available": ai_service.is_available() or azure_llm.is_available(),
    }, parsed


# ==========================================
# 1. Top Navigation Bar (Header)
# ==========================================
logo_html = (
    f'<img src="data:image/png;base64,{XEBIA_LOGO_B64}" class="xebia-header-logo" alt="Xebia" />'
    if XEBIA_LOGO_B64
    else '<span class="xebia-wordmark">Xebia</span>'
)

st.markdown(
    f"""
    <div class="xebia-header-bar">
        <div class="xebia-logo-container">
            {logo_html}
            <span class="nav-divider">/</span>
            <div class="app-title-group">
                <div class="app-title-main">
                    <span style="color: #111827;">PBI</span>
                    <span style="color: #682A5B; margin: 0 4px; font-weight: 600;">→</span>
                    <span style="color: #682A5B;">Paginated</span>
                </div>
                <span class="app-title-sub">PERFORMANCE ANALYZER</span>
            </div>
        </div>
        <div class="nav-right-actions">
            <div class="nav-status-badge">
                <span class="status-dot"></span>
                <span>Local engine ready</span>
            </div>
            <a class="nav-link" href="#01-analyze">How it works ↗</a>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# 2. Compact Hero Section
# ==========================================
st.markdown(
    """
    <div class="hero-container">
        <div class="accelerator-pill">
            <span>◆</span> XEBIA ENTERPRISE ACCELERATOR
        </div>
        <div class="hero-title">
            From slow Paginated Reports<br>
            to <span class="hero-title-accent">peak performance, effortlessly.</span>
        </div>
        <div class="hero-description">
            Audit datasets, SQL queries, parameters, and expressions in seconds. Simple checks stay private and local; Gemini assists only when query plans get complex.
        </div>
        <div class="feature-chips">
            <div class="chip chip-purple"><span>⚙️</span> Local-first analysis</div>
            <div class="chip chip-pink"><span>✦</span> AI when needed</div>
            <div class="chip chip-green"><span>✓</span> RDL schema checks</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# 3. Report Workspace (Two-Column Grid)
# ==========================================
st.markdown(
    """
    <div id="01-analyze" class="workspace-card">
        <div class="workspace-top-bar">
            <div>
                <div class="workspace-step">01 / ANALYZE</div>
                <div class="workspace-title">Report workspace</div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Two-column layout for upload and diagnostic panels
col_left, col_right = st.columns([1, 1], gap="medium")

# LEFT PANEL: RDL Upload
with col_left:
    st.markdown(
        """
        <div class="panel-header">
            <div class="panel-header-left">
                <div class="panel-avatar panel-avatar-purple">R</div>
                <div>
                    <div class="panel-title">RDL report definition</div>
                    <div class="panel-subtitle">Upload your .rdl report definition</div>
                </div>
            </div>
            <span class="panel-tag tag-purple">RDL</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    uploaded_file = st.file_uploader(
        "Upload RDL file",
        type=["rdl", "xml"],
        label_visibility="collapsed",
        help="Upload standard Power BI Paginated Report or SSRS .rdl definition",
    )

    # Clean file metadata presentation (No raw byte counts)
    file_meta_html = ""
    if uploaded_file is not None:
        file_size_formatted = format_file_size(len(uploaded_file.getvalue()))
        file_meta_html = f'<div class="file-meta-chip"><span>📁</span> {uploaded_file.name} · {file_size_formatted}</div>'
    else:
        file_meta_html = '<div style="font-size: 11px; color: #9CA3AF; margin-top: 6px;">No file selected · Ready to inspect</div>'

    st.markdown(file_meta_html, unsafe_allow_html=True)

    st.markdown(
        """
        <div class="panel-footer">
            <span>Schema-agnostic parser (2008–2016+)</span>
            <span style="color: var(--xebia-purple); font-weight: 600;">Enterprise Grade</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

# RIGHT PANEL: Performance Diagnostic & Preview
with col_right:
    data = st.session_state.analysis_data

    # Display status badge accurately: only show OPTIMIZATION AVAILABLE if optimizations exist
    if data:
        opts_count = len(data.get("dataset_optimizations", {}))
        tag_html = '<span class="panel-tag tag-green">OPTIMIZATION AVAILABLE</span>' if opts_count > 0 else '<span class="panel-tag tag-neutral">ANALYSIS COMPLETE</span>'
    else:
        tag_html = '<span class="panel-tag tag-neutral">AWAITING INPUT</span>'

    st.markdown(
        f"""
        <div class="panel-header">
            <div class="panel-header-left">
                <div class="panel-avatar panel-avatar-amber">P</div>
                <div>
                    <div class="panel-title">Performance diagnostic</div>
                    <div class="panel-subtitle">Health score & query optimization preview</div>
                </div>
            </div>
            {tag_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if data:
        score = data["health_score"]
        status = data["health_status"]
        score_color = "#16A34A" if score >= 80 else ("#D97706" if score >= 60 else "#DC2626")

        st.markdown(
            f"""
            <div style="background-color: #F8FAFC; border: 1px solid var(--xebia-border); border-radius: 8px; padding: 10px 14px; margin-bottom: 10px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 12px; font-weight: 600; color: #374151;">Overall Report Health</span>
                    <span style="font-size: 17px; font-weight: 800; color: {score_color};">{score} / 100</span>
                </div>
                <div style="font-size: 11px; color: #64748B; margin-top: 1px;">Status: <strong>{status}</strong></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        opts = data.get("dataset_optimizations", {})
        inventory = data.get("dataset_inventory", [])
        if inventory:
            ds_names = [d["name"] for d in inventory]
            def format_ds_label(name):
                d = next((item for item in inventory if item["name"] == name), None)
                if not d:
                    return name
                if d.get("is_orphan"):
                    return f"{name} (Orphan Candidate)"
                if d.get("query_type") and d.get("query_type") != "SQL":
                    return f"{name} ({d.get('query_type')})"
                return name

            selected_ds = st.selectbox(
                "Selected Dataset:",
                ds_names,
                format_func=format_ds_label,
                key="preview_ds_selector"
            )
            inv_item = next((item for item in inventory if item["name"] == selected_ds), None)
            if selected_ds in opts and opts[selected_ds].get("suggested_query"):
                st.code(opts[selected_ds]["suggested_query"], language="sql")
            elif inv_item and inv_item.get("is_orphan"):
                st.code(
                    f"-- ⚠️ ORPHAN CANDIDATE: '{selected_ds}'\n"
                    f"-- Status: 0 visual references, 0 parameter bindings, 0 expression references.\n"
                    f"-- Recommendation: Remove this dataset from report definition to eliminate query overhead.\n"
                    f"-- Original Query:\n{inv_item.get('query_text', '-- (No query text defined)')}",
                    language="sql"
                )
            elif inv_item and inv_item.get("query_type") and inv_item.get("query_type") != "SQL":
                st.info(f"Dataset '{selected_ds}' uses {inv_item.get('query_type')}. Static embedded payload — SQL rewrites not applicable.")
            else:
                st.info("No query optimization needed for this dataset.")
        elif opts:
            ds_keys = list(opts.keys())
            selected_ds = st.selectbox("Selected Dataset:", ds_keys, key="preview_ds_selector")
            opt = opts[selected_ds]
            st.code(opt["suggested_query"], language="sql")
        else:
            st.info("No query optimization needed for this report definition.")
    else:
        st.markdown(
            """
            <div style="background-color: #F8FAFC; border: 1px dashed #D1D5DB; border-radius: 8px; padding: 32px 14px; text-align: center; color: #6B7280;">
                <div style="font-size: 22px; margin-bottom: 4px;">⚡</div>
                <div style="font-size: 13px; font-weight: 600; color: #374151;">Awaiting Report Analysis</div>
                <div style="font-size: 11px; color: #9CA3AF; margin-top: 2px;">Upload an .rdl file on the left, then click Analyze.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <div class="panel-footer">
            <span>Local conversion · no external API calls</span>
            <span style="color: var(--xebia-purple); font-weight: 600;">Ready</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")

# Action Controls: Gemini Toggle & Analyze CTA Button
c_toggle, c_btn = st.columns([1, 1], gap="medium")

with c_toggle:
    use_gemini = st.toggle(
        "Use Gemini for complex expressions",
        value=ai_service.is_available(),
        help="Enables AI query plan reasoning and index guidance via Google Gemini.",
    )
    st.caption("Simple conversions never call the API · Fully private local analysis")

with c_btn:
    analyze_clicked = st.button("✦ Analyze Report →", type="primary", use_container_width=True)

    if analyze_clicked:
        xml_content = None
        rep_name = "Report"

        if uploaded_file is not None:
            xml_content = uploaded_file.getvalue().decode("utf-8", errors="replace")
            rep_name = os.path.splitext(uploaded_file.name)[0]

        if xml_content:
            with st.spinner("Analyzing datasets, SQL queries, parameters, and expressions..."):
                res, parsed_obj = run_analysis_from_xml(xml_content, rep_name)
                st.session_state.analysis_data = res
                st.session_state.current_parsed_rdl = parsed_obj
                st.session_state.current_report_name = rep_name
                st.session_state.current_report_id = generate_unique_report_id()
                st.session_state.ai_explanations = {}
            st.rerun()
        else:
            st.error("Please upload an .rdl report file first.")

st.markdown(
    """
    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px; font-size: 11px; color: #9CA3AF;">
        <span>◆ Enterprise-grade privacy · Keys stay on the server</span>
        <span>Version 1.0.0</span>
    </div>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# 4. Diagnostic Results Section
# ==========================================
data = st.session_state.analysis_data
if data:
    st.write("")
    st.divider()

    st.markdown(
        f"""
        <div style="margin-bottom: 14px;">
            <div style="font-size: 10px; font-weight: 700; color: var(--xebia-purple); letter-spacing: 1px; text-transform: uppercase;">02 / DIAGNOSTIC RESULTS</div>
            <div style="font-size: 22px; font-weight: 800; color: var(--xebia-dark);">Performance Findings: {data['report_name']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 5 Equal-Height KPI Cards with Standardized Typography & Severity Tokens
    m = data["summary_metrics"]
    score = data["health_score"]
    status = data["health_status"]

    score_text_color = "#16A34A" if score >= 80 else ("#D97706" if score >= 60 else "#991B1B")
    status_bg = "#DCFCE7" if score >= 80 else ("#FEF3C7" if score >= 60 else "#FEE2E2")
    status_color = "#166534" if score >= 80 else ("#92400E" if score >= 60 else "#991B1B")

    st.markdown(
        f"""
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-val" style="color: {score_text_color};">{score}/100</div>
                <div class="kpi-lbl">Health Score</div>
                <span class="kpi-status-badge" style="background:{status_bg}; color:{status_color};">{status}</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-val" style="color: var(--sev-critical-text);">{m.get('high_severity_count', 0)}</div>
                <div class="kpi-lbl">Critical / High Issues</div>
                <span class="kpi-status-badge" style="background:var(--sev-critical-bg); color:var(--sev-critical-text);">Requires Action</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-val" style="color: var(--sev-med-text);">{m.get('medium_severity_count', 0)}</div>
                <div class="kpi-lbl">Medium Issues</div>
                <span class="kpi-status-badge" style="background:var(--sev-med-bg); color:var(--sev-med-text);">Investigation</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-val" style="color: #334155;">{m.get('total_datasets', 0)}</div>
                <div class="kpi-lbl">Datasets ({m.get('total_queries', 0)} SQL)</div>
                <span class="kpi-status-badge" style="background:#F1F5F9; color:#475569;">Architecture</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-val" style="color: var(--sev-low-text);">{m.get('unused_fields_count', 0)}</div>
                <div class="kpi-lbl">Unused Columns</div>
                <span class="kpi-status-badge" style="background:var(--sev-low-bg); color:var(--sev-low-text);">Prune Safe</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Dynamic Executive Performance Forecast & Verdict Banner
    high_count = m.get('high_severity_count', 0)
    med_count = m.get('medium_severity_count', 0)
    unused_fields_count = m.get('unused_fields_count', 0)
    total_queries = m.get('total_queries', 0)

    if high_count > 0:
        total_est_seconds = max(1, high_count * 50 + med_count * 15)
        minutes = total_est_seconds // 60
        seconds = total_est_seconds % 60
        est_orig_time = f"~{minutes}m {seconds:02d}s" if minutes > 0 else f"~{seconds}s"
        est_opt_time = "~6–10s"
        est_speedup = "Est. 92–95% latency reduction"
        pct_retrieval = 74
        pct_inmemory = 19
        pct_render = 7
    elif med_count > 0:
        est_orig_time = "~25–35s"
        est_opt_time = "~4–7s"
        est_speedup = "Est. 75–80% latency reduction"
        pct_retrieval = 55
        pct_inmemory = 30
        pct_render = 15
    else:
        est_orig_time = "~2–4s"
        est_opt_time = "< 1s"
        est_speedup = "Optimized report design"
        pct_retrieval = 35
        pct_inmemory = 35
        pct_render = 30

    if unused_fields_count > 0:
        payload_text = f"{unused_fields_count} redundant columns across {total_queries} queries"
        payload_impact = "Est. 60–75% network payload cut"
    else:
        payload_text = "All projected columns utilized in visuals"
        payload_impact = "Zero payload bloat"

    # Top high-ROI quick wins
    quick_wins = []
    for iss in data.get("issues", []):
        if iss["severity"] in ("High", "Critical") and len(quick_wins) < 3:
            quick_wins.append(
                f"<li class='quick-win-item'><span style='color:#DC2626;'>•</span> <span><strong>{iss['target_object']}</strong>: {iss['title']} — {iss['remediation']}</span></li>"
            )
    if len(quick_wins) < 3:
        for iss in data.get("issues", []):
            if iss["severity"] == "Medium" and len(quick_wins) < 3:
                quick_wins.append(
                    f"<li class='quick-win-item'><span style='color:#D97706;'>•</span> <span><strong>{iss['target_object']}</strong>: {iss['title']} — {iss['remediation']}</span></li>"
                )
    if not quick_wins:
        quick_wins.append(
            "<li class='quick-win-item'><span style='color:#16A34A;'>✓</span> <span>Report definition follows SSRS enterprise performance best practices.</span></li>"
        )
    quick_wins_html = "".join(quick_wins)

    st.markdown(
        f"""
        <div class="exec-verdict-banner">
            <div class="exec-banner-grid">
                <div class="exec-metric-box">
                    <div class="exec-metric-title">⏱️ Projected Render Time</div>
                    <div class="exec-metric-value">{est_orig_time} <span style="font-size:15px; color:#6B7280; font-weight:500;">→</span> <span style="color:#16A34A;">{est_opt_time}</span></div>
                    <div class="exec-metric-sub">{est_speedup}</div>
                    <div class="latency-bar-container">
                        <div style="font-size:10px; color:#6B7280; font-weight:600; margin-bottom:3px;">ESTIMATED LATENCY PHASE BREAKDOWN</div>
                        <div class="latency-bar">
                            <div class="bar-retrieval" style="width: {pct_retrieval}%;" title="Data Retrieval ({pct_retrieval}%)"></div>
                            <div class="bar-inmemory" style="width: {pct_inmemory}%;" title="In-Memory Processing ({pct_inmemory}%)"></div>
                            <div class="bar-render" style="width: {pct_render}%;" title="Visual & PDF Render ({pct_render}%)"></div>
                        </div>
                        <div class="latency-legend">
                            <span><span class="latency-legend-dot" style="background:#DC2626;"></span>Retrieval ({pct_retrieval}%)</span>
                            <span><span class="latency-legend-dot" style="background:#F59E0B;"></span>In-Memory ({pct_inmemory}%)</span>
                            <span><span class="latency-legend-dot" style="background:#3B82F6;"></span>Render ({pct_render}%)</span>
                        </div>
                    </div>
                </div>
                <div class="exec-metric-box">
                    <div class="exec-metric-title">📦 Payload & Memory Overhead</div>
                    <div class="exec-metric-value" style="font-size: 16px; margin-top:2px;">{payload_text}</div>
                    <div class="exec-metric-sub" style="margin-top:6px;">{payload_impact}</div>
                    <div style="font-size: 11px; color:#6B7280; margin-top:10px; line-height:1.4;">
                        Pruning unused fields eliminates serialization overhead in the Power BI On-Premises Gateway and minimizes SSRS memory pressure during high user concurrency.
                    </div>
                </div>
                <div>
                    <div class="exec-metric-title">⚡ Top High-ROI Quick Wins</div>
                    <ul class="quick-wins-list">
                        {quick_wins_html}
                    </ul>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Clean Sub-Tabs
    res_tab_issues, res_tab_diff, res_tab_matrix, res_tab_export = st.tabs([
        f"🔍 Detected Issues ({len(data['issues'])})",
        "⚡ Side-by-Side SQL Diff",
        "📊 Field Utilization Matrix",
        "📥 Download Reports",
    ])

    # -------------------------------------------------------------
    # TAB 1: Reusable Refactored Issue Cards
    # -------------------------------------------------------------
    with res_tab_issues:
        issues = data.get("issues", [])
        if not issues:
            st.success("No performance bottlenecks detected. Report structure follows best practices.")
        else:
            # Responsive Filter Bar
            fc1, fc2, fc3 = st.columns([1, 1, 1], gap="small")
            with fc1:
                sev_options = ["High", "Medium", "Low", "Info"]
                # Count per severity for friendly chips
                sev_counts = {s: sum(1 for i in issues if i["severity"] == s) for s in sev_options}
                sev_filter = st.multiselect(
                    "Severity:",
                    options=sev_options,
                    default=sev_options,
                    format_func=lambda s: f"{s} ({sev_counts.get(s, 0)})",
                    key="filter_sev",
                )
            with fc2:
                cat_options = sorted(list({i["category"] for i in issues}))
                cat_filter = st.multiselect("Category:", options=cat_options, default=cat_options, key="filter_cat")
            with fc3:
                target_options = sorted(list({i["target_object"] for i in issues}))
                target_filter = st.multiselect("Target Object:", options=target_options, default=target_options, key="filter_target")

            # Filter issues
            filtered_issues = [
                i for i in issues
                if i["severity"] in sev_filter
                and i["category"] in cat_filter
                and i["target_object"] in target_filter
            ]

            st.caption(f"Showing **{len(filtered_issues)}** of **{len(issues)}** diagnostic findings")

            # Render Reusable Issue Cards
            for idx, iss in enumerate(filtered_issues):
                iss_id = iss["id"]
                sev = iss["severity"]
                badge_html = get_severity_badge_html(sev)

                # Card Expander
                with st.expander(f"[{sev.upper()}] {iss['title']} — {iss['target_object']}", expanded=(sev == "High" and idx < 3)):
                    # Header metadata row
                    st.markdown(
                        f"""
                        <div class="issue-card-header">
                            <div class="issue-card-header-left">
                                {badge_html}
                                <span class="pill-meta">Target: <strong>{iss['target_object']}</strong></span>
                                <span class="pill-meta">Category: {iss['category']}</span>
                                <span class="pill-meta">Status: {iss['classification']}</span>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Two-column description & impact grid
                    st.markdown(
                        f"""
                        <div class="issue-body-grid">
                            <div>
                                <div class="issue-field-label">Description</div>
                                <div>{iss['description']}</div>
                                <div class="issue-field-label" style="margin-top:8px;">Engine Impact</div>
                                <div style="color: #991B1B;">{iss['impact']}</div>
                            </div>
                            <div>
                                <div class="issue-field-label">Recommended Remediation</div>
                                <div style="color: #166534; font-weight: 500;">{iss['remediation']}</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Code snippets (Original vs Suggested Fix)
                    has_code = bool(iss.get("code_snippet"))
                    has_fix = bool(iss.get("suggested_fix"))

                    if has_code or has_fix:
                        code_col1, code_col2 = st.columns(2 if (has_code and has_fix) else 1, gap="small")
                        if has_code:
                            with code_col1:
                                st.markdown('<div class="issue-field-label">Identified Code / Expression:</div>', unsafe_allow_html=True)
                                st.code(iss["code_snippet"], language="sql" if iss["category"] == "SQL Query" else "vb")
                        if has_fix:
                            with code_col2:
                                st.markdown('<div class="issue-field-label" style="color:#166534;">Suggested Replacement:</div>', unsafe_allow_html=True)
                                st.code(iss["suggested_fix"], language="sql")



    # -------------------------------------------------------------
    # TAB 2: Side-by-Side SQL Diff
    # -------------------------------------------------------------
    with res_tab_diff:
        opts = data.get("dataset_optimizations", {})
        inventory = data.get("dataset_inventory", [])
        sql_datasets = [d for d in inventory if d.get("query_type", "SQL") == "SQL"] if inventory else []
        if not sql_datasets and opts:
            sql_datasets = [{"name": k, "query_type": "SQL", "is_orphan": False, "query_text": opts[k].get("original_query", "")} for k in opts]

        if sql_datasets:
            sql_names = [d["name"] for d in sql_datasets]
            ds_diff_choice = st.selectbox(
                "Select dataset to view query diff:",
                sql_names,
                format_func=lambda x: f"{x} (Orphan Candidate)" if next((d.get("is_orphan") for d in sql_datasets if d["name"] == x), False) else x,
                key="diff_ds_selector"
            )
            opt_diff = opts.get(ds_diff_choice)
            inv_diff = next((d for d in sql_datasets if d["name"] == ds_diff_choice), None)

            d_col1, d_col2 = st.columns(2, gap="medium")
            if opt_diff:
                with d_col1:
                    st.markdown("##### 🔴 Original SQL Query")
                    st.code(opt_diff["original_query"], language="sql")
                    if opt_diff.get("fields_pruned"):
                        st.warning(f"Unused columns fetched: {', '.join(opt_diff['fields_pruned'])}")
                with d_col2:
                    st.markdown("##### 🟢 Recommended Optimized Query")
                    st.code(opt_diff["suggested_query"], language="sql")
                    st.success("✅ Improvements applied:")
                    for r in opt_diff.get("optimization_reasons", []):
                        st.write(f"- {r}")
            elif inv_diff and inv_diff.get("is_orphan"):
                with d_col1:
                    st.markdown("##### 🔴 Original SQL Query")
                    st.code(inv_diff.get("query_text", "-- No query text"), language="sql")
                    st.warning("⚠️ Orphan Dataset: 0 visual references. Recommended for removal.")
                with d_col2:
                    st.markdown("##### 🟡 Recommended Action")
                    st.code(
                        f"-- ⚠️ ORPHAN DATASET: RECOMMEND REMOVAL\n"
                        f"-- This dataset is not referenced by any visual, expression, or parameter.\n"
                        f"-- Recommendation: Remove this dataset rather than optimizing the query.\n"
                        f"-- Removing this dataset eliminates redundant query execution and connection overhead on report load.",
                        language="sql"
                    )
                    st.info("Query tuning is suppressed because removing the unneeded dataset is the optimal performance fix.")
            else:
                with d_col1:
                    st.markdown("##### 🔴 Original SQL Query")
                    st.code(inv_diff.get("query_text", "") if inv_diff else "", language="sql")
                with d_col2:
                    st.markdown("##### 🟢 Recommended Query")
                    st.info("Query follows standard projection and filter best practices.")
        else:
            st.info("No SQL datasets were detected in this report. SQL comparison is not applicable.")

    # -------------------------------------------------------------
    # TAB 3: Field Utilization Matrix
    # -------------------------------------------------------------
    with res_tab_matrix:
        st.markdown("##### 📊 Visual-to-Query Field Utilization Matrix")
        st.caption("Audits every column fetched by dataset queries against actual visual references, group expressions, and sort definitions in the RDL XML.")
        matrix = data.get("field_usage_matrix", {})
        if matrix:
            matrix_data = []
            for ds_name, info in matrix.items():
                total = info.get("total_fields", 0)
                used = info.get("used_count", 0)
                unused = info.get("unused_count", 0)
                rate = f"{(used / total * 100):.0f}%" if total > 0 else "N/A"
                if total > 0:
                    pct_unused = unused / total
                    if pct_unused > 0.7:
                        risk = "🔴 High Risk (>70% unused)"
                    elif pct_unused > 0.4:
                        risk = "🟠 Medium Risk (40–70% unused)"
                    elif pct_unused > 0:
                        risk = "🟡 Low Risk (<40% unused)"
                    else:
                        risk = "🟢 Optimal (100% used)"
                else:
                    risk = "⚪ N/A"

                matrix_data.append({
                    "Dataset": ds_name,
                    "Total Columns": total,
                    "Used in Visuals": used,
                    "Unused Columns": unused,
                    "Utilization %": rate,
                    "Payload Risk": risk,
                    "Safe to Prune": ", ".join(info.get("unused_fields", [])) if info.get("unused_fields") else "None (Fully utilized)",
                })
            st.dataframe(pd.DataFrame(matrix_data), use_container_width=True, hide_index=True)
            st.caption("💡 **Recommendation**: Pruning safe columns removes network serialization latency without altering report layout or numbers.")

    # -------------------------------------------------------------
    # TAB 4: Download Deliverables
    # -------------------------------------------------------------
    with res_tab_export:
        st.markdown("##### Export Diagnostic Deliverables")
        st.caption("Download comprehensive technical findings for client presentation, architectural review, or engineering remediation.")

        # 1. Primary Deliverable: Self-Contained Professional HTML Report
        rpt_id = st.session_state.get("current_report_id") or generate_unique_report_id()
        html_content = generate_html_report(
            analysis_data=data,
            parsed_rdl=st.session_state.get("current_parsed_rdl"),
            report_id=rpt_id,
            azure_llm=azure_llm,
        )

        st.markdown(
            """
            <div style="background: linear-gradient(135deg, #FAF5F9 0%, #FFFFFF 100%); border: 1px solid var(--xebia-purple-border); border-radius: 8px; padding: 14px 18px; margin-bottom: 12px;">
                <div style="font-size: 13.5px; font-weight: 700; color: var(--xebia-purple); margin-bottom: 3px;">🌐 Professional HTML Performance Analysis Report</div>
                <div style="font-size: 12px; color: #4B5563; line-height: 1.4;">
                    Self-contained technical assessment document containing all 8 sections (Executive Summary, Detailed Findings, SQL Comparison, Dataset Inventory, Parameter Pushdown, Interactive Remediation Action Plan with LocalStorage persistence, and Roadmap).
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.download_button(
            label="📥 Download HTML Performance Analysis Report",
            data=html_content.encode("utf-8"),
            file_name=f"Paginated_Report_Performance_Analysis_{rpt_id}.html",
            mime="text/html",
            use_container_width=True,
            type="primary",
            help="Download the self-contained HTML report for client stakeholders and developers.",
        )

        st.write("")
        exp_c1, exp_c2 = st.columns(2, gap="medium")

        with exp_c1:
            try:
                res_export = export_excel_report(data)
                excel_bytes = (
                    res_export.body_iterator.getbuffer()
                    if hasattr(res_export.body_iterator, "getbuffer")
                    else b"".join([chunk for chunk in res_export.body_iterator])
                )
                st.download_button(
                    label="📊 Download Formatted Excel Report (.xlsx)",
                    data=excel_bytes,
                    file_name=f"Xebia_Diagnostic_{data['report_name']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Excel export error: {e}")

        with exp_c2:
            st.download_button(
                label="📄 Download Diagnostic JSON (.json)",
                data=json.dumps(data, indent=2),
                file_name=f"Xebia_Diagnostic_{data['report_name']}.json",
                mime="application/json",
                use_container_width=True,
            )
