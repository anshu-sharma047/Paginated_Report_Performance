# ⚡ Power BI Paginated Report Performance Analyzer Accelerator

An automated, client-facing diagnostic accelerator that identifies why Power BI Paginated Reports (`.rdl` files) run slowly and recommends exact, actionable performance fixes.

Instead of manually inspecting every dataset, SQL query, report parameter, visual binding, and expression across complex paginated reports, developers and QA teams upload an `.rdl` file to this accelerator to instantly generate a comprehensive performance diagnostic report with optimized queries and downloadable Excel workbooks.

---

## 🚀 Key Capabilities: The 5 Analysis Components

| Component | Focus Area | Checks Performed |
|---|---|---|
| **1. SQL Query Analyzer** | Data Retrieval Layer | Detects `SELECT *`, non-sargable functions (`YEAR(Date)=2026`), missing `WHERE` clauses, old-style cartesian comma joins, and unreferenced fetched columns. |
| **2. Parameter & Filtering Analyzer** | Filter Pushdown | Identifies report parameters not pushed to SQL, inefficient post-retrieval in-memory Tablix filters, and missing query parameter mappings. |
| **3. Dataset & Report Structure Analyzer** | Report Architecture | Flags orphan/unused datasets, dataset proliferation, and critical $N+1$ query hazards where subreports are nested in repeating Tablix row groups. |
| **4. Expression Performance Analyzer** | Rendering & CPU Engine | Inspects expressions for deeply nested `IIF`s (depth $\ge 3$), redundant calculations across cells, repeated type conversions (`CDate`, `CDbl`), and custom VB.NET `<Code>` blocks. |
| **5. Performance Recommendation Engine** | Synthesis & Optimization | Computes an overall Health Score (0–100), classifies findings by severity (`High`, `Medium`, `Low`), auto-generates optimized SQL with column pruning, and exports formatted Excel workbooks. |

---

## 📁 Project Architecture & File Structure

```
Paginated Report Performance Analyzer/
├── backend/
│   ├── __init__.py
│   ├── parser.py              # RDL XML parser (extracts queries, parameters, fields, visuals, expressions)
│   ├── analyzer.py            # Core engine containing the 5 analysis components
│   ├── gemini_service.py      # Google Gemini AI service for intelligent query advice and explanations
│   └── main.py                # FastAPI backend REST API (/analyze, /optimize-sql, /ai-explain, /export)
├── frontend/
│   ├── __init__.py
│   └── app.py                 # Streamlit interactive dashboard (4 screens)
├── sample_reports/            # Ready-to-use sample RDL test fixtures with intentionally crafted bottlenecks
│   ├── sample1_sql_bottlenecks.rdl
│   ├── sample2_structure_subreports.rdl
│   └── sample3_expressions_parameters.rdl
├── tests/
│   ├── __init__.py
│   ├── test_parser.py         # Unit tests for RDL parsing
│   ├── test_analyzer.py       # Unit tests for the 5 diagnostic components
│   └── test_api.py            # Integration tests for FastAPI endpoints
├── .env.example               # Example environment variables
├── .gitignore                 # Standard Python, virtual environment, and cache exclusions
├── README.md                  # Complete technical documentation & guide
└── requirements.txt           # Project dependencies
```

---

## 🖥️ The 4 Main Application Screens

1. **Upload & Preset Selector**: Upload an `.rdl` file or select one of the 3 built-in demo presets with 1 click.
2. **Analysis Summary**: Executive overview with overall Performance Health Score (0–100), metric cards, component category breakdown, and priority action items.
3. **Issue Explorer**: Deep-dive interactive finding cards with severity badges, classification (`[Detected Issue]`, `[Potential Optimization]`, `[Runtime-Verified Target]`), engine impact, remediation steps, code snippets, and optional AI explanations.
4. **Optimization Studio & Export**: Side-by-side SQL diff (original vs. suggested query with column pruning and sargability rewrites), field utilization matrix, and 1-click downloadable **Excel Diagnostic Workbook (`.xlsx`)** and **JSON Report**.

---

## ⚙️ Installation & Quickstart

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.14)
- Pip

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. (Optional) Configure Gemini AI
Copy `.env.example` to `.env` and set your Google Gemini API key to enable AI-powered query optimization and natural language explanations:
```bash
cp .env.example .env
```
*(If no API key is provided, the tool runs in 100% deterministic rule-based mode with zero external dependencies.)*

### 4. Run the Application

#### Option A: Modern Enterprise HTML5/CSS3 Frontend (Recommended)
Launch the unified FastAPI server which directly delivers the modern, responsive HTML/CSS/JS frontend:
```bash
uvicorn backend.main:app --reload --port 8000
```
Open your browser to:
👉 **`http://localhost:8000`**

*(Interactive Swagger API docs are also available at `http://localhost:8000/docs`)*

#### Option B: Streamlit Dashboard (Alternative)
You can also launch the Streamlit dashboard:
```bash
streamlit run frontend/app.py
```
Open your browser to `http://localhost:8501`.

---

## 🧪 Testing & Verification

Run the automated test suite with pytest:
```bash
pytest -v
```

All 16 unit and integration tests validate:
- RDL XML schema-agnostic extraction (`test_parser.py`)
- Detection of `SELECT *`, non-sargable functions, missing `WHERE`, orphan datasets, $N+1$ subreports, and nested `IIF`s (`test_analyzer.py`)
- Static frontend delivery, sample report execution, and REST endpoints (`test_api.py`)
- Self-contained HTML diagnostic report generation and Azure OpenAI fallback (`test_html_report.py`)
- FastAPI endpoints, SQL rewriting, and multi-tab Excel export generation (`test_api.py`)

---

## 📋 Sample Test Reports

The `sample_reports/` folder contains three realistic Paginated Reports designed for immediate demonstration:

1. **`sample1_sql_bottlenecks.rdl`**:
   - `SELECT * FROM Sales WHERE YEAR(SaleDate) = 2026;`
   - Missing `WHERE` on `TransactionsDataset`
   - 11 unused fields fetched over the network
   - *Expected*: High SQL warnings, sargable range rewrite suggestion, column pruning.

2. **`sample2_structure_subreports.rdl`**:
   - 8 Datasets total (including 2 completely unreferenced orphan datasets)
   - Subreport `SubreportOrderItems` placed inside a Tablix repeating detail row
   - *Expected*: High warning for $N+1$ subreport execution multiplier, orphan dataset warnings.

3. **`sample3_expressions_parameters.rdl`**:
   - Report parameters `@FiscalYear` and `@RegionName` omitted from SQL query
   - In-memory client-side Tablix filter
   - 5-level nested `IIF` expression
   - Embedded VB.NET custom `<Code>` block
   - *Expected*: High warning for unpushed parameter, Tablix filter warning, nested IIF alert.
