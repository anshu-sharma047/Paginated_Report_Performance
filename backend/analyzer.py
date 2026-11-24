"""
Paginated Report Performance Analyzer Engine
Contains the 5 core diagnostic components:
1. SQL Query Analyzer (sqlglot AST + heuristics)
2. Parameter & Filtering Analyzer (pushdown verification)
3. Dataset & Report Structure Analyzer (orphans, N+1 subreports, field waste)
4. Expression Performance Analyzer (nested IIF, repeated logic, custom code)
5. Performance Recommendation Engine (scoring, classification, SQL rewriting)
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Any

import sqlglot
from sqlglot import exp

from backend.parser import ParsedRDL, DatasetInfo, ExpressionInfo, SubreportInfo


class Severity(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Info"


class IssueClassification(str, Enum):
    DETECTED_ISSUE = "Detected Issue"
    POTENTIAL_OPTIMIZATION = "Potential Optimization"
    FUNCTIONAL_DEFECT = "Functional Defect"
    RUNTIME_VERIFIED_TARGET = "Runtime-Verified Target"
    BEST_PRACTICE = "Best Practice"


class ComponentCategory(str, Enum):
    SQL_QUERY = "SQL Query"
    PARAMETER_FILTER = "Parameter & Filter"
    REPORT_STRUCTURE = "Report Structure"
    EXPRESSIONS = "Expressions"


class ValidationStatus(str, Enum):
    VALIDATED_RDL = "Validated against RDL metadata"
    PARTIALLY_VALIDATED = "Partially validated"
    REQUIRES_MANUAL_VALIDATION = "Requires manual validation"
    INVALID_RECOMMENDATION = "Invalid recommendation"


@dataclass
class PerformanceIssue:
    id: str
    category: ComponentCategory
    severity: Severity
    classification: IssueClassification
    title: str
    target_object: str  # e.g., Dataset: SalesDataset, Tablix: Tablix1
    description: str
    impact: str
    remediation: str
    code_snippet: Optional[str] = None
    suggested_fix: Optional[str] = None
    validation_status: str = "Validated against RDL metadata"


@dataclass
class DatasetOptimization:
    dataset_name: str
    original_query: str
    suggested_query: str
    query_type: str = "SQL"
    optimization_reasons: List[str] = field(default_factory=list)
    fields_used: List[str] = field(default_factory=list)
    fields_pruned: List[str] = field(default_factory=list)
    detected_issues: List[str] = field(default_factory=list)
    suggested_improvements: List[str] = field(default_factory=list)
    validation_status: str = "Validated against RDL metadata"


def detect_query_type_from_text(
    query_text: str, command_type: str = "Text", data_provider: Optional[str] = None
) -> str:
    """
    Classifies a paginated report dataset query into its definitive type:
    'SQL', 'XML/EnterData', 'XML', 'DAX', 'MDX', 'JSON', 'API', 'StoredProcedure', 'TableDirect', or 'Non-SQL'.
    Guarantees XML, EnterData, DAX, MDX, and JSON queries are never misidentified as SQL.
    """
    cmd_type_clean = (command_type or "").strip().lower()
    if cmd_type_clean == "storedprocedure":
        return "StoredProcedure"
    if cmd_type_clean == "tabledirect":
        return "TableDirect"

    # 1. Check DataProvider if available from DataSource definition
    if data_provider:
        dp = data_provider.strip().upper()
        if dp in ["ENTERDATA"]:
            return "XML/EnterData"
        if dp in ["XML", "SHAREPOINTLIST", "SHAREPOINT", "XMLDATA"]:
            return "XML"
        if dp in ["MSDAX", "POWERBI", "ASAZURE", "SSAS"]:
            return "DAX"
        if dp in ["REST", "WEBAPI", "JSON"]:
            return "API"

    q = (query_text or "").strip()
    if not q:
        if data_provider and data_provider.strip().upper() == "ENTERDATA":
            return "XML/EnterData"
        return "Empty"

    # 2. XML / EnterData detection
    # Checks for XML header, root/query tags, ElementPath, SOAP, or web method XML
    if q.startswith("<") or re.search(
        r"<\s*(?:[a-zA-Z0-9_\-]+:)?(?:Query|ElementPath|XmlData|Data|DataGrid|Method|Envelope|Root|Schema|SoapRequest)\b",
        q,
        re.IGNORECASE,
    ):
        return "XML/EnterData" if (data_provider and data_provider.strip().upper() == "ENTERDATA") else "XML"

    if q.startswith("<") and ">" in q and ("</" in q or "/>" in q):
        return "XML"

    # 3. JSON detection
    if (q.startswith("{") and q.endswith("}")) or (q.startswith("[") and q.endswith("]")):
        try:
            json.loads(q)
            return "JSON"
        except Exception:
            pass

    # 4. DAX detection
    if re.search(
        r"^\s*(?:EVALUATE|DEFINE\s+(?:MEASURE|VAR))\b|SUMMARIZECOLUMNS\s*\(|CALCULATETABLE\s*\(",
        q,
        re.IGNORECASE,
    ):
        return "DAX"

    # 5. MDX detection
    if re.search(
        r"\bON\s+(?:COLUMNS|ROWS|[0-9])\b|^\s*WITH\s+(?:MEMBER|SET)\b|\bFROM\s+\[[^\]]+\]\s+WHERE\b",
        q,
        re.IGNORECASE,
    ):
        return "MDX"

    # 6. Stored procedure call inside CommandText (e.g. EXEC or EXECUTE without SELECT)
    if re.match(r"^\s*(?:EXEC|EXECUTE)\s+[\w\.\@]+", q, re.IGNORECASE) and not re.search(r"\bSELECT\b", q, re.IGNORECASE):
        return "StoredProcedure"

    # 7. SQL statement detection
    # Check standard SQL keywords at statement start
    if re.search(
        r"^\s*(?:SELECT|WITH\s+[\w#\[\]]+\s+AS\s*\(|INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM|MERGE\s+INTO)\b",
        q,
        re.IGNORECASE,
    ):
        return "SQL"

    # sqlglot parser confirmation
    try:
        parsed = sqlglot.parse_one(q, read="tsql")
        if parsed and isinstance(parsed, (exp.Select, exp.Union, exp.Insert, exp.Update, exp.Delete)):
            return "SQL"
    except Exception:
        pass

    # If it contains SELECT ... FROM pattern
    if re.search(r"\bSELECT\b.+\bFROM\b", q, re.IGNORECASE | re.DOTALL):
        return "SQL"

    return "Non-SQL"


def detect_query_type(dataset: DatasetInfo) -> str:
    """Convenience wrapper to detect query type from a DatasetInfo object."""
    if getattr(dataset, "is_embedded_xml", False) or getattr(dataset, "data_provider", "") == "ENTERDATA":
        return "XML/EnterData"
    if getattr(dataset, "query_type", None) in ["XML/EnterData", "EnterData"]:
        return "XML/EnterData"
    return detect_query_type_from_text(
        query_text=dataset.query_text,
        command_type=dataset.command_type,
        data_provider=getattr(dataset, "data_provider", None),
    )


@dataclass
class AnalysisResult:
    report_name: str
    health_score: int
    health_status: str  # Excellent, Good, Fair, Critical
    summary_metrics: Dict[str, Any]
    issues: List[PerformanceIssue]
    dataset_optimizations: Dict[str, DatasetOptimization]
    field_usage_matrix: Dict[str, Dict[str, Any]]
    recommendations_summary: List[str]


class SQLQueryAnalyzer:
    """Component 1: Ingests SQL statements from RDL datasets and analyzes for performance bottlenecks."""

    def analyze(self, dataset: DatasetInfo, all_datasets: Dict[str, DatasetInfo]) -> Tuple[List[PerformanceIssue], Optional[DatasetOptimization]]:
        # Requirement 2 & 10: If a dataset has no report item, expression, parameter, or indirect dependency,
        # prioritize recommending removal. Suppress redundant SQL findings and SQL comparison diffs.
        if getattr(dataset, "is_orphan", False):
            return [], None

        issues: List[PerformanceIssue] = []
        query = (dataset.query_text or "").strip()
        q_type = detect_query_type(dataset)
        dataset.query_type = q_type

        # Requirement 5: Never generate SQL optimization suggestions for XML, DAX, MDX, JSON, or other non-SQL query types
        if q_type != "SQL":
            if q_type == "StoredProcedure":
                issues.append(
                    PerformanceIssue(
                        id=f"SQL-SP-{dataset.name}",
                        category=ComponentCategory.SQL_QUERY,
                        severity=Severity.INFO,
                        classification=IssueClassification.RUNTIME_VERIFIED_TARGET,
                        title="Stored Procedure Used",
                        target_object=f"Dataset: {dataset.name}",
                        description=f"Dataset executes Stored Procedure '{query}'. Static SQL analysis inside SP requires database access.",
                        impact="Report relies on database engine execution plan. Inefficient parameters or internal temporary tables may slow execution.",
                        remediation="Inspect stored procedure execution plan, ensure parameterized indexes exist, and avoid OPTION(RECOMPILE) unless necessary.",
                        code_snippet=query,
                        validation_status=ValidationStatus.VALIDATED_RDL.value,
                    )
                )
            elif q_type == "XML":
                # Keep XML data analysis separate from SQL query optimization
                if dataset.unused_field_names and len(dataset.fields) > 0:
                    unused_count = len(dataset.unused_field_names)
                    total_count = len(dataset.fields)
                    if unused_count > 0:
                        issues.append(
                            PerformanceIssue(
                                id=f"XML-UNUSED-FIELDS-{dataset.name}",
                                category=ComponentCategory.REPORT_STRUCTURE,
                                severity=Severity.LOW if unused_count < 3 else Severity.MEDIUM,
                                classification=IssueClassification.DETECTED_ISSUE,
                                title=f"Unused XML Fields Defined ({unused_count} of {total_count})",
                                target_object=f"Dataset (XML): {dataset.name}",
                                description=f"XML dataset '{dataset.name}' defines {total_count} fields, but {unused_count} are never referenced in any visual, group, expression, or subreport.",
                                impact="Inflates in-memory XML DOM parsing and serialization payload across the Power BI On-Premises Data Gateway.",
                                remediation=f"Prune unreferenced XML nodes from the dataset field collection: {', '.join(sorted(list(dataset.unused_field_names))[:8])}{'...' if unused_count > 8 else ''}.",
                                code_snippet=f"Unused: {list(dataset.unused_field_names)[:5]}",
                                validation_status=ValidationStatus.VALIDATED_RDL.value,
                            )
                        )
            return issues, None

        if not query:
            return issues, None

        # 1. Check for SELECT *
        has_select_star = False
        parsed_ast = None
        ast_parse_success = False

        try:
            parsed_ast = sqlglot.parse_one(query, read="tsql")
            ast_parse_success = True
        except Exception:
            try:
                parsed_ast = sqlglot.parse_one(query)
                ast_parse_success = True
            except Exception:
                ast_parse_success = False

        if ast_parse_success and parsed_ast:
            selects = parsed_ast.find_all(exp.Star)
            has_select_star = any(True for _ in selects)
        else:
            has_select_star = bool(re.search(r"SELECT\s+(?:DISTINCT\s+)?\*", query, re.IGNORECASE))

        if has_select_star:
            issues.append(
                PerformanceIssue(
                    id=f"SQL-STAR-{dataset.name}",
                    category=ComponentCategory.SQL_QUERY,
                    severity=Severity.HIGH,
                    classification=IssueClassification.DETECTED_ISSUE,
                    title="Wildcard Projection (SELECT *)",
                    target_object=f"Dataset: {dataset.name}",
                    description=f"Query in dataset '{dataset.name}' retrieves all columns with SELECT * instead of specifying needed columns.",
                    impact="Static analysis risk: Transfers unneeded columns across the gateway, prevents index-covering query plans, and increases memory buffer usage in the report server.",
                    remediation="Explicitly project only the columns required by the report visuals and expressions.",
                    code_snippet="SELECT * ...",
                    validation_status=ValidationStatus.VALIDATED_RDL.value,
                )
            )

        # 2. Check for Missing WHERE clause in SQL queries
        has_where = False
        if ast_parse_success and parsed_ast:
            where_node = parsed_ast.find(exp.Where)
            has_where = where_node is not None
        else:
            has_where = bool(re.search(r"\bWHERE\b", query, re.IGNORECASE))

        if not has_where:
            issues.append(
                PerformanceIssue(
                    id=f"SQL-NOWHERE-{dataset.name}",
                    category=ComponentCategory.SQL_QUERY,
                    severity=Severity.HIGH,
                    classification=IssueClassification.POTENTIAL_OPTIMIZATION,
                    title="Missing SQL WHERE Predicate",
                    target_object=f"Dataset: {dataset.name}",
                    description=f"Query in dataset '{dataset.name}' has no WHERE clause, potentially scanning the entire table or view.",
                    impact="Static analysis risk: Fetches unconstrained data across all dates and dimensions, drastically inflating execution time and report render delay.",
                    remediation="Push report parameters directly into the SQL query WHERE clause.",
                    code_snippet=query[:150] + ("..." if len(query) > 150 else ""),
                    validation_status=ValidationStatus.VALIDATED_RDL.value,
                )
            )

        # 3. Check for Non-Sargable Functions in WHERE clause (e.g. YEAR(TransactionDate) = @Year)
        sargable_matches: List[Tuple[str, str, str, str]] = []  # (full_match, col, suggested, explanation)

        # 3a. YEAR() pattern: YEAR(col) = @param or YEAR(col) = 2025 (and reverse)
        m_year_1 = list(re.finditer(r"\bYEAR\s*\(\s*([a-zA-Z0-9_\.\[\]]+)\s*\)\s*=\s*(@?[a-zA-Z0-9_]+|\d{4})\b", query, re.IGNORECASE))
        m_year_2 = list(re.finditer(r"\b(@?[a-zA-Z0-9_]+|\d{4})\s*=\s*YEAR\s*\(\s*([a-zA-Z0-9_\.\[\]]+)\s*\)\b", query, re.IGNORECASE))

        for m in m_year_1:
            col, val = m.group(1), m.group(2)
            if val.isdigit() and len(val) == 4:
                val_next = str(int(val) + 1)
                suggested = f"{col} >= '{val}-01-01' AND {col} < '{val_next}-01-01'"
            elif val.startswith("@"):
                suggested = f"{col} >= DATEFROMPARTS({val}, 1, 1) AND {col} < DATEFROMPARTS({val} + 1, 1, 1)"
            else:
                suggested = f"{col} >= DATEFROMPARTS(@{val}, 1, 1) AND {col} < DATEFROMPARTS(@{val} + 1, 1, 1)"
            sargable_matches.append((
                m.group(0), col, suggested,
                f"Wrapping '{col}' inside YEAR() renders the predicate non-SARGable. Potential index benefit: allows the database optimizer to seek on an index on '{col}'."
            ))

        for m in m_year_2:
            val, col = m.group(1), m.group(2)
            if val.isdigit() and len(val) == 4:
                val_next = str(int(val) + 1)
                suggested = f"{col} >= '{val}-01-01' AND {col} < '{val_next}-01-01'"
            elif val.startswith("@"):
                suggested = f"{col} >= DATEFROMPARTS({val}, 1, 1) AND {col} < DATEFROMPARTS({val} + 1, 1, 1)"
            else:
                suggested = f"{col} >= DATEFROMPARTS(@{val}, 1, 1) AND {col} < DATEFROMPARTS(@{val} + 1, 1, 1)"
            sargable_matches.append((
                m.group(0), col, suggested,
                f"Wrapping '{col}' inside YEAR() renders the predicate non-SARGable. Potential index benefit: allows the database optimizer to seek on an index on '{col}'."
            ))

        # 3b. LEFT() pattern
        for m in re.finditer(r"\bLEFT\s*\(\s*([a-zA-Z0-9_\.\[\]]+)\s*,\s*(\d+)\s*\)\s*=\s*'([^']+)'", query, re.IGNORECASE):
            col, length, val = m.group(1), m.group(2), m.group(3)
            suggested = f"{col} LIKE '{val}%'"
            sargable_matches.append((
                m.group(0), col, suggested,
                f"LEFT() function on '{col}' disables index seek. Replace with LIKE prefix matching."
            ))

        # 3c. CONVERT() pattern
        for m in re.finditer(r"\bCONVERT\s*\(\s*varchar(?:\(\d+\))?\s*,\s*([a-zA-Z0-9_\.\[\]]+)(?:\s*,\s*\d+)?\s*\)\s*=\s*'([^']+)'", query, re.IGNORECASE):
            col, val = m.group(1), m.group(2)
            suggested = f"{col} = '{val}'"
            sargable_matches.append((
                m.group(0), col, suggested,
                f"Type conversion on '{col}' prevents index utilization. Compare directly with typed literal."
            ))

        for full_match, col, suggested, expl in sargable_matches:
            col_clean = re.sub(r"[\[\]\.]", "_", col)
            issues.append(
                PerformanceIssue(
                    id=f"SQL-SARGABLE-{dataset.name}-{col_clean}",
                    category=ComponentCategory.SQL_QUERY,
                    severity=Severity.HIGH,
                    classification=IssueClassification.POTENTIAL_OPTIMIZATION,
                    title=f"Non-Sargable Predicate on '{col}'",
                    target_object=f"Dataset: {dataset.name}",
                    description=f"The predicate `{full_match}` applies a function over column `{col}`, preventing index seek operations.",
                    impact="Static analysis risk: Forces the database engine to perform a full clustered index scan or table scan evaluating the function row-by-row.",
                    remediation=f"Rewrite condition using half-open date/value intervals: `{suggested}`. {expl} Requires manual validation to confirm index presence and execution plan.",
                    code_snippet=full_match,
                    suggested_fix=suggested,
                    validation_status=ValidationStatus.REQUIRES_MANUAL_VALIDATION.value,
                )
            )

        # 4. Check for Unused Fetched Columns in SQL queries
        if dataset.unused_field_names and len(dataset.fields) > 0:
            unused_count = len(dataset.unused_field_names)
            total_count = len(dataset.fields)
            if unused_count > 0:
                issues.append(
                    PerformanceIssue(
                        id=f"SQL-UNUSED-COLS-{dataset.name}",
                        category=ComponentCategory.SQL_QUERY,
                        severity=Severity.MEDIUM if unused_count >= 3 else Severity.LOW,
                        classification=IssueClassification.DETECTED_ISSUE,
                        title=f"Unused Columns Fetched ({unused_count} of {total_count})",
                        target_object=f"Dataset: {dataset.name}",
                        description=f"Dataset defines {total_count} fields, but {unused_count} are never referenced in any visual, group, expression, or subreport.",
                        impact="Static analysis risk: Wastes database I/O, network bandwidth, and memory inside the Power BI tabular processing engine.",
                        remediation=f"Remove the unused columns: {', '.join(sorted(list(dataset.unused_field_names))[:8])}{'...' if unused_count > 8 else ''}.",
                        code_snippet=f"Unused: {list(dataset.unused_field_names)[:5]}",
                        validation_status=ValidationStatus.VALIDATED_RDL.value,
                    )
                )

        # 5. Check for Cartesian Joins (Comma joins without ON condition)
        if re.search(r"\bFROM\s+[\w\.]+,\s*[\w\.]+", query, re.IGNORECASE):
            issues.append(
                PerformanceIssue(
                    id=f"SQL-CARTESIAN-{dataset.name}",
                    category=ComponentCategory.SQL_QUERY,
                    severity=Severity.HIGH,
                    classification=IssueClassification.POTENTIAL_OPTIMIZATION,
                    title="Potential Cartesian Join (Old Comma Join Syntax)",
                    target_object=f"Dataset: {dataset.name}",
                    description=f"Query in dataset '{dataset.name}' uses comma-separated table joins without explicit ANSI JOIN ON syntax.",
                    impact="Static analysis risk: High risk of accidental Cartesian product resulting in exponential row multiplication and database lockup.",
                    remediation="Refactor to explicit ANSI `INNER JOIN ... ON ...` or `LEFT JOIN ... ON ...` syntax.",
                    code_snippet=query[:150],
                    validation_status=ValidationStatus.REQUIRES_MANUAL_VALIDATION.value,
                )
            )

        # Collect detected SQL issue titles specifically for this dataset
        detected_issues = [
            i.title for i in issues if dataset.name in i.target_object or f"-{dataset.name}" in i.id
        ]

        # Generate Suggested Optimized SQL
        optimization = self._generate_sql_optimization(dataset, query, parsed_ast, detected_issues, sargable_matches)

        return issues, optimization

    def _generate_sql_optimization(
        self,
        dataset: DatasetInfo,
        original_query: str,
        parsed_ast: Optional[exp.Expression],
        detected_issues: Optional[List[str]] = None,
        sargable_matches: Optional[List[Tuple[str, str, str, str]]] = None,
    ) -> Optional[DatasetOptimization]:
        if not original_query or dataset.command_type.lower() == "storedprocedure":
            return None

        # Requirement 5: Never generate SQL optimization suggestions for non-SQL query types
        if detect_query_type(dataset) != "SQL":
            return None

        # Requirement 2: Do not generate optimized SQL for an orphan dataset
        if getattr(dataset, "is_orphan", False):
            return None

        reasons = []
        suggested_improvements = []
        optimized_query = original_query
        requires_manual_validation = False

        # Determine used columns to project
        used_cols = sorted(list(dataset.used_field_names))
        if not used_cols and dataset.fields:
            used_cols = [f.data_field or f.name for f in dataset.fields]

        pruned_cols = sorted(list(dataset.unused_field_names))
        if pruned_cols:
            suggested_improvements.append(
                f"Prune {len(pruned_cols)} unreferenced column(s) ({', '.join(pruned_cols[:4])}{'...' if len(pruned_cols) > 4 else ''}) to reduce gateway transmission payload."
            )

        # 1. Replace SELECT * with specific columns
        if re.search(r"SELECT\s+(?:DISTINCT\s+)?\*", optimized_query, re.IGNORECASE):
            reasons.append("Replaced wildcard SELECT * with only the fields actually consumed in the report.")
            suggested_improvements.append("Use explicit column projection to enable index-covering query plans.")
            if used_cols:
                col_projection = ", ".join(used_cols)
                optimized_query = re.sub(
                    r"SELECT\s+(DISTINCT\s+)?\*",
                    r"SELECT \1" + col_projection,
                    optimized_query,
                    count=1,
                    flags=re.IGNORECASE,
                )

        # 2. Rewrite non-sargable functions (grounded in query)
        if sargable_matches:
            for full_match, col, suggested, expl in sargable_matches:
                if full_match in optimized_query:
                    optimized_query = optimized_query.replace(full_match, suggested)
                    reasons.append(f"Converted non-sargable predicate `{full_match}` to sargable interval `{suggested}`.")
                    suggested_improvements.append(f"Candidate SARGable rewrite for `{col}`: verify in database that an index exists to allow an Index Seek.")
                    requires_manual_validation = True

        # 3. Handle queries missing a WHERE clause
        # REQUIREMENT 1: NEVER invent SQL columns, parameters, date filters, or business logic.
        # DO NOT inject fake WHERE clauses like "WHERE [DateColumn] >= @StartDate...".
        if not re.search(r"\bWHERE\b", optimized_query, re.IGNORECASE) and re.search(r"\bSELECT\b.+\bFROM\b", optimized_query, re.IGNORECASE | re.DOTALL):
            suggested_improvements.append("Query lacks a WHERE clause. Parameter pushdown is recommended if report parameters apply to this dataset.")

        if not reasons:
            reasons.append("Query follows standard projection and filter best practices.")

        if not suggested_improvements:
            suggested_improvements.append("Monitor query execution times under peak concurrent users.")

        validation_status = (
            ValidationStatus.REQUIRES_MANUAL_VALIDATION.value
            if requires_manual_validation
            else ValidationStatus.VALIDATED_RDL.value
        )

        return DatasetOptimization(
            dataset_name=dataset.name,
            original_query=original_query,
            suggested_query=optimized_query.strip(),
            query_type="SQL",
            optimization_reasons=reasons,
            fields_used=used_cols,
            fields_pruned=pruned_cols,
            detected_issues=detected_issues or [],
            suggested_improvements=suggested_improvements,
            validation_status=validation_status,
        )


class ParameterFilteringAnalyzer:
    """Component 2: Validates report parameters vs SQL query parameters and flags in-memory filtering."""

    def analyze(self, rdl: ParsedRDL) -> List[PerformanceIssue]:
        issues: List[PerformanceIssue] = []

        # Find report-level parameters
        report_param_names = set(rdl.parameters.keys())

        # 1. Detect inert / unreferenced report parameters across the entire report
        inert_parameters: Set[str] = set()
        for rp_name, rp in rdl.parameters.items():
            rp_clean = rp_name.lstrip("@").lower()

            used_in_query = any(
                re.search(rf"@{re.escape(rp_clean)}\b", ds.query_text, re.IGNORECASE)
                for ds in rdl.datasets.values() if ds.query_text
            )
            used_in_qp = any(
                rp_clean == qp.name.lstrip("@").lower() or rp_clean in qp.value.lower()
                for ds in rdl.datasets.values()
                for qp in ds.query_parameters
            )
            used_in_ds_filter = any(
                rp_clean in flt.expression.lower() or any(rp_clean in str(v).lower() for v in flt.values)
                for ds in rdl.datasets.values()
                for flt in ds.filters
            )
            used_in_vis_filter = any(
                rp_clean in flt.expression.lower() or any(rp_clean in str(v).lower() for v in flt.values)
                for vis in rdl.visuals
                for flt in vis.filters
            )
            used_in_expr = any(
                f"parameters!{rp_clean}" in expr.text.lower()
                or f'parameters("{rp_clean}")' in expr.text.lower()
                or f"parameters('{rp_clean}')" in expr.text.lower()
                for expr in rdl.expressions
            )
            used_as_param_ds = any(
                rp_name.lower() in (other_p.valid_values_dataset or "").lower()
                or rp_name.lower() in (other_p.default_values_dataset or "").lower()
                for other_p in rdl.parameters.values()
            )

            if not (used_in_query or used_in_qp or used_in_ds_filter or used_in_vis_filter or used_in_expr or used_as_param_ds):
                inert_parameters.add(rp_name)
                default_str = ", ".join(rp.default_values) if rp.default_values else "None"
                has_all = any(v.lower() == "all" for v in rp.default_values)
                target_col = rp_name
                issues.append(
                    PerformanceIssue(
                        id=f"PARAM-INERT-REPORT-{rp_name}",
                        category=ComponentCategory.PARAMETER_FILTER,
                        severity=Severity.MEDIUM,
                        classification=IssueClassification.FUNCTIONAL_DEFECT,
                        title=f"Inactive Parameter '@{rp_name}' (Never Applied to Any Dataset or Visual)",
                        target_object=f"Parameter: @{rp_name}",
                        description=(
                            f"Parameter '@{rp_name}' (Default: '{default_str}') is defined in the report definition, "
                            f"but is never referenced in any SQL query, dataset filter, tablix filter, or visual expression."
                        ),
                        impact=(
                            f"User selections for '@{rp_name}' have no filtering effect on any report visual. "
                            f"Furthermore, because its default value is '{default_str}', naively pushing an equality filter "
                            f"(`{target_col} = @{rp_name}`) into SQL would incorrectly filter out all rows when '{default_str}' is selected."
                        ),
                        remediation=(
                            f"Review business intent: if '@{rp_name}' should filter data, apply conditional filtering "
                            f"(`(@{rp_name} = '{rp.default_values[0] if rp.default_values else 'All'}' OR {target_col} = @{rp_name})`) "
                            f"in the dataset query or Tablix filter. If obsolete, remove the parameter from the report definition."
                        ),
                        code_snippet=f"<ReportParameter Name=\"{rp_name}\"><DataType>{rp.data_type}</DataType><DefaultValue><Values><Value>{default_str}</Value></Values></DefaultValue></ReportParameter>",
                        suggested_fix=f"(@{rp_name} = '{rp.default_values[0] if rp.default_values else 'All'}' OR {target_col} = @{rp_name})" if has_all else f"{target_col} = @{rp_name}",
                        validation_status=ValidationStatus.VALIDATED_RDL.value,
                    )
                )

        # 2. Check parameter pushdown for active datasets
        for ds_name, ds in rdl.datasets.items():
            if getattr(ds, "is_orphan", False):
                continue

            ds_qtype = detect_query_type(ds)
            query_text = ds.query_text or ""
            mapped_qp_names = {qp.name.lstrip("@").lower() for qp in ds.query_parameters}

            # Check which report parameters are completely absent from this dataset (SQL datasets only)
            if ds_qtype == "SQL":
                for rp_name, rp in rdl.parameters.items():
                    # Skip parameters already identified as report-wide inert parameters to avoid duplicate findings
                    if rp_name in inert_parameters:
                        continue

                    rp_lower = rp_name.lower()
                    is_in_query = f"@{rp_lower}" in query_text.lower() or rp_lower in mapped_qp_names

                    if not is_in_query and ds.referenced_in_visuals > 0 and len(report_param_names) > 0:
                        common_filter_words = {"date", "year", "quarter", "month", "region", "customer", "dept", "status", "org"}
                        if any(w in rp_lower for w in common_filter_words):
                            has_all = any(v.lower() == "all" for v in rp.default_values)
                            default_val = rp.default_values[0] if rp.default_values else "All"
                            if has_all:
                                fix_str = f"AND (@{rp_name} = '{default_val}' OR {rp_name} = @{rp_name})"
                                rem_str = f"Map parameter `@{rp_name}` into the SQL query WHERE clause using conditional logic to support '{default_val}': `(@{rp_name} = '{default_val}' OR {rp_name} = @{rp_name})`."
                            else:
                                fix_str = f"AND {rp_name} = @{rp_name}"
                                rem_str = f"Map parameter `@{rp_name}` into the SQL query WHERE clause: `WHERE {rp_name} = @{rp_name}`."

                            issues.append(
                                PerformanceIssue(
                                    id=f"PARAM-UNPUSHED-{ds_name}-{rp_name}",
                                    category=ComponentCategory.PARAMETER_FILTER,
                                    severity=Severity.HIGH,
                                    classification=IssueClassification.POTENTIAL_OPTIMIZATION,
                                    title=f"Report Parameter '@{rp_name}' Not Pushed to SQL",
                                    target_object=f"Dataset (SQL): {ds_name}",
                                    description=f"Report defines parameter '@{rp_name}', but it is not utilized in dataset '{ds_name}' SQL query or query parameters.",
                                    impact="The query retrieves unconstrained historical or organizational data; filtering happens in-memory after network transmission.",
                                    remediation=rem_str,
                                    code_snippet=f"Parameter: @{rp_name} ({rp.data_type})",
                                    suggested_fix=fix_str,
                                    validation_status=ValidationStatus.PARTIALLY_VALIDATED.value,
                                )
                            )
            elif ds_qtype in ("XML/EnterData", "EnterData") or getattr(ds, "is_embedded_xml", False):
                # Embedded XML / EnterData does NOT evaluate <QueryParameters> at the engine level!
                for qp in ds.query_parameters:
                    qp_clean = qp.name.lstrip("@")
                    qp_lower = qp_clean.lower()
                    used_in_ds_filter = any(
                        qp_lower in flt.expression.lower()
                        or any(qp_lower in str(v).lower() for v in flt.values)
                        for flt in ds.filters
                    )
                    used_in_vis_filter = any(
                        v.dataset_name == ds_name and any(
                            qp_lower in flt.expression.lower()
                            or any(qp_lower in str(v).lower() for v in flt.values)
                            for flt in v.filters
                        )
                        for v in rdl.visuals
                    )
                    if not used_in_ds_filter and not used_in_vis_filter:
                        issues.append(
                            PerformanceIssue(
                                id=f"PARAM-INERT-FILTER-{ds_name}-{qp_clean}",
                                category=ComponentCategory.PARAMETER_FILTER,
                                severity=Severity.MEDIUM,
                                classification=IssueClassification.FUNCTIONAL_DEFECT,
                                title=f"Inert Query Parameter '@{qp_clean}' on Static Embedded Dataset '{ds_name}'",
                                target_object=f"Dataset ({ds_qtype}): {ds_name}",
                                description=(
                                    f"Dataset '{ds_name}' defines query parameter '@{qp_clean}', but embedded {ds_qtype} "
                                    f"data is static and does not support native query parameter binding. No RDL dataset filter or "
                                    f"visual filter is defined to apply '@{qp_clean}'."
                                ),
                                impact=(
                                    f"User selections for parameter '@{qp_clean}' in the report viewer will not filter data from dataset '{ds_name}', "
                                    f"leaving report visuals completely unfiltered by this parameter (functional defect)."
                                ),
                                remediation=(
                                    f"Add an explicit Tablix filter or Dataset filter on '{ds_name}': "
                                    f"`[TargetField] = Parameters!{qp_clean}.Value`, or migrate the dataset to a parameterized relational/API data source."
                                ),
                                code_snippet=f"<QueryParameter Name=\"{qp.name}\"><Value>{qp.value}</Value></QueryParameter>",
                                suggested_fix=f"Add Dataset Filter: [Field] = Parameters!{qp_clean}.Value",
                                validation_status=ValidationStatus.VALIDATED_RDL.value,
                            )
                        )

            # Check In-Memory Dataset Filters
            if ds.filters:
                for idx, flt in enumerate(ds.filters):
                    if ds_qtype == "SQL":
                        issues.append(
                            PerformanceIssue(
                                id=f"PARAM-DS-FILTER-{ds_name}-{idx}",
                                category=ComponentCategory.PARAMETER_FILTER,
                                severity=Severity.MEDIUM,
                                classification=IssueClassification.DETECTED_ISSUE,
                                title=f"In-Memory Dataset Filter in '{ds_name}'",
                                target_object=f"Dataset (SQL): {ds_name}",
                                description=f"Dataset '{ds_name}' has an in-memory RDL filter on `{flt.expression}` {flt.operator} {flt.values}.",
                                impact="Data is retrieved across the network from the SQL source first, then discarded inside SSRS processing memory.",
                                remediation="Move this filter directly into the SQL query WHERE clause to reduce query runtime and network transfer.",
                                code_snippet=f"<FilterExpression>{flt.expression}</FilterExpression>",
                                suggested_fix=f"Add to SQL: WHERE {flt.expression.replace('Fields!', '').replace('.Value', '')} = ...",
                                validation_status=ValidationStatus.VALIDATED_RDL.value,
                            )
                        )
                    elif ds_qtype in ("XML/EnterData", "EnterData") or getattr(ds, "is_embedded_xml", False):
                        issues.append(
                            PerformanceIssue(
                                id=f"PARAM-DS-FILTER-{ds_name}-{idx}",
                                category=ComponentCategory.PARAMETER_FILTER,
                                severity=Severity.INFO,
                                classification=IssueClassification.BEST_PRACTICE,
                                title=f"In-Memory Dataset Filter in Embedded '{ds_name}'",
                                target_object=f"Dataset ({ds_qtype}): {ds_name}",
                                description=f"Dataset '{ds_name}' ({ds_qtype}) has an in-memory RDL filter on `{flt.expression}` {flt.operator} {flt.values}.",
                                impact="Filtering embedded static data at the dataset level is standard practice in RDL since EnterData does not use a remote database engine.",
                                remediation="Keep the embedded XML/EnterData payload compact so in-memory filtering does not impact report render performance.",
                                code_snippet=f"<FilterExpression>{flt.expression}</FilterExpression>",
                                validation_status=ValidationStatus.VALIDATED_RDL.value,
                            )
                        )
                    else:
                        issues.append(
                            PerformanceIssue(
                                id=f"PARAM-DS-FILTER-{ds_name}-{idx}",
                                category=ComponentCategory.PARAMETER_FILTER,
                                severity=Severity.LOW,
                                classification=IssueClassification.POTENTIAL_OPTIMIZATION,
                                title=f"In-Memory Dataset Filter in '{ds_name}'",
                                target_object=f"Dataset ({ds_qtype}): {ds_name}",
                                description=f"Dataset '{ds_name}' ({ds_qtype}) has an in-memory RDL filter on `{flt.expression}` {flt.operator} {flt.values}.",
                                impact=f"Entire {ds_qtype} data payload is parsed in memory before SSRS filters rows.",
                                remediation=f"For {ds_qtype} datasets, constrain data at the source or element path where feasible to eliminate in-memory filter evaluation.",
                                code_snippet=f"<FilterExpression>{flt.expression}</FilterExpression>",
                                validation_status=ValidationStatus.VALIDATED_RDL.value,
                            )
                        )

        # Check In-Memory Tablix Filters
        for visual in rdl.visuals:
            if visual.filters:
                vis_ds = rdl.datasets.get(visual.dataset_name) if visual.dataset_name else None
                vis_qtype = detect_query_type(vis_ds) if vis_ds else "Unknown"
                for idx, flt in enumerate(visual.filters):
                    if vis_qtype == "SQL":
                        issues.append(
                            PerformanceIssue(
                                id=f"PARAM-TABLIX-FILTER-{visual.name}-{idx}",
                                category=ComponentCategory.PARAMETER_FILTER,
                                severity=Severity.MEDIUM,
                                classification=IssueClassification.DETECTED_ISSUE,
                                title=f"In-Memory Filter on Visual '{visual.name}'",
                                target_object=f"Visual: {visual.name}",
                                description=f"Visual '{visual.name}' applies an in-memory Tablix filter: `{flt.expression}` {flt.operator}.",
                                impact="The entire dataset is loaded into the report session before rows are filtered out visually.",
                                remediation="Where feasible, push this filter into the underlying SQL query or create a filtered dataset.",
                                code_snippet=f"Filter: {flt.expression}",
                                validation_status=ValidationStatus.VALIDATED_RDL.value,
                            )
                        )
                    else:
                        issues.append(
                            PerformanceIssue(
                                id=f"PARAM-TABLIX-FILTER-{visual.name}-{idx}",
                                category=ComponentCategory.PARAMETER_FILTER,
                                severity=Severity.LOW if vis_qtype in ("XML/EnterData", "EnterData") else Severity.MEDIUM,
                                classification=IssueClassification.BEST_PRACTICE if vis_qtype in ("XML/EnterData", "EnterData") else IssueClassification.POTENTIAL_OPTIMIZATION,
                                title=f"In-Memory Filter on Visual '{visual.name}'",
                                target_object=f"Visual: {visual.name}",
                                description=f"Visual '{visual.name}' applies an in-memory Tablix filter: `{flt.expression}` {flt.operator}.",
                                impact="Visual filters execute in-memory after dataset binding.",
                                remediation="For non-SQL sources, consider pushing the filter to the dataset level if multiple visuals share the same filtered scope.",
                                code_snippet=f"Filter: {flt.expression}",
                                validation_status=ValidationStatus.VALIDATED_RDL.value,
                            )
                        )

        return issues


class DatasetStructureAnalyzer:
    """Component 3: Analyzes dataset relationships, orphan datasets, subreport N+1 hazards, and visual density."""

    def analyze(self, rdl: ParsedRDL) -> List[PerformanceIssue]:
        issues: List[PerformanceIssue] = []

        # 1. Detect Orphan / Unused Datasets
        for ds_name, ds in rdl.datasets.items():
            if getattr(ds, "is_orphan", False):
                issues.append(
                    PerformanceIssue(
                        id=f"STRUCT-ORPHAN-DS-{ds_name}",
                        category=ComponentCategory.REPORT_STRUCTURE,
                        severity=Severity.HIGH,
                        classification=IssueClassification.DETECTED_ISSUE,
                        title=f"Unused / Orphan Dataset '{ds_name}'",
                        target_object=f"Dataset: {ds_name}",
                        description=f"Dataset '{ds_name}' is declared in the report definition but is never referenced by any Tablix, Chart, Gauge, Parameter, or Expression. Scoped dependency analysis confirms 0 references.",
                        impact="Static analysis risk: The report engine executes this query during report initialization, consuming database connections and delaying initial render without displaying results.",
                        remediation=f"Validate dependencies and remove unused dataset '{ds_name}' from the report definition to eliminate unnecessary query execution and connection overhead.",
                        validation_status=ValidationStatus.VALIDATED_RDL.value,
                    )
                )
            elif ds.referenced_in_visuals == 0:
                # Check if dataset is used by report parameters (available values / default values)
                if getattr(ds, "is_parameter_dataset", False) or getattr(ds, "referenced_in_parameters", 0) > 0:
                    continue
                used_in_params = any(
                    ds_name.lower() == (rp.valid_values_dataset or "").lower()
                    or ds_name.lower() == (rp.default_values_dataset or "").lower()
                    or ds_name.lower() in (rp.prompt or "").lower()
                    for rp in rdl.parameters.values()
                )
                if used_in_params:
                    continue
                # Also check if referenced in any expression (e.g. Lookup, LookupSet, Sum in textbox)
                used_in_expr = any(
                    ds_name == expr.dataset_name
                    or f'"{ds_name.lower()}"' in expr.text.lower()
                    or f"'{ds_name.lower()}'" in expr.text.lower()
                    for expr in rdl.expressions
                )
                if used_in_expr:
                    continue

                issues.append(
                    PerformanceIssue(
                        id=f"STRUCT-ORPHAN-DS-{ds_name}",
                        category=ComponentCategory.REPORT_STRUCTURE,
                        severity=Severity.HIGH,
                        classification=IssueClassification.DETECTED_ISSUE,
                        title=f"Unused / Orphan Dataset '{ds_name}'",
                        target_object=f"Dataset: {ds_name}",
                        description=f"Dataset '{ds_name}' is declared in the report but is never referenced by any Tablix, Chart, Gauge, Parameter, or Expression.",
                        impact="Static analysis risk: Executes an unnecessary database query on report open, consuming database connections and delaying initial render.",
                        remediation=f"Validate dependencies and remove dataset '{ds_name}' from the report definition if its results are not displayed.",
                        validation_status=ValidationStatus.VALIDATED_RDL.value,
                    )
                )

        # 2. Check for Subreports inside Repeating Row Groups (The classic N+1 bottleneck)
        for sub in rdl.subreports:
            if sub.in_row_group:
                issues.append(
                    PerformanceIssue(
                        id=f"STRUCT-SUBREPORT-ROW-{sub.name}",
                        category=ComponentCategory.REPORT_STRUCTURE,
                        severity=Severity.HIGH,
                        classification=IssueClassification.DETECTED_ISSUE,
                        title=f"Subreport '{sub.name}' Embedded in Repeating Row Group",
                        target_object=f"Subreport: {sub.name}",
                        description=f"Subreport '{sub.report_name}' is located inside a Tablix row hierarchy ({sub.parent_container}).",
                        impact="Executes a separate subreport roundtrip for EVERY row rendered in the parent table (e.g., 500 rows = 500 subreport executions), multiplying render time exponentially.",
                        remediation="Refactor by flattening data into a single master SQL query with JOINs, or replace subreport with a native Tablix grouping or drillthrough action.",
                        code_snippet=f"<Subreport Name=\"{sub.name}\"><ReportName>{sub.report_name}</ReportName>",
                    )
                )
            else:
                issues.append(
                    PerformanceIssue(
                        id=f"STRUCT-SUBREPORT-STANDALONE-{sub.name}",
                        category=ComponentCategory.REPORT_STRUCTURE,
                        severity=Severity.LOW,
                        classification=IssueClassification.RUNTIME_VERIFIED_TARGET,
                        title=f"Standalone Subreport '{sub.name}'",
                        target_object=f"Subreport: {sub.name}",
                        description=f"Report includes subreport '{sub.report_name}'. Standalone subreports trigger extra HTTP/database requests.",
                        impact="Adds independent latency to overall report rendering.",
                        remediation="Review if the subreport content can be merged directly into the main report layout.",
                    )
                )

        # 3. High Dataset Count
        total_ds = len(rdl.datasets)
        if total_ds > 8:
            issues.append(
                PerformanceIssue(
                    id="STRUCT-HIGH-DATASET-COUNT",
                    category=ComponentCategory.REPORT_STRUCTURE,
                    severity=Severity.MEDIUM,
                    classification=IssueClassification.POTENTIAL_OPTIMIZATION,
                    title=f"High Dataset Count ({total_ds} Datasets)",
                    target_object="Report Root",
                    description=f"Report defines {total_ds} separate datasets. Paginated Report service must execute each query sequentially or concurrently.",
                    impact="Can exhaust database connection pools, introduce lock contention, and extend total data retrieval phase.",
                    remediation="Consolidate related datasets where possible using SQL JOINs or UNIONs.",
                )
            )

        return issues


class ExpressionPerformanceAnalyzer:
    """Component 4: Identifies complex nested IIF expressions, repeated calculations, and custom code overhead."""

    def analyze(self, rdl: ParsedRDL) -> List[PerformanceIssue]:
        issues: List[PerformanceIssue] = []
        has_sql = any(detect_query_type(ds) == "SQL" for ds in rdl.datasets.values())

        seen_expressions: Dict[str, int] = {}

        for expr in rdl.expressions:
            text = expr.text.strip()
            seen_expressions[text] = seen_expressions.get(text, 0) + 1

            # 1. Nested IIF Depth Check
            iif_count = len(re.findall(r"\bIIF\s*\(", text, re.IGNORECASE))
            if iif_count >= 3:
                iif_remediation = (
                    "Move conditional logic to SQL using `CASE WHEN ... THEN ... END`, or refactor to `Switch()` in SSRS expressions."
                    if has_sql
                    else "Refactor nested IIF statements to `Switch()` or pre-calculate categories at the data source to avoid evaluating both branches."
                )
                issues.append(
                    PerformanceIssue(
                        id=f"EXPR-NESTED-IIF-{abs(hash(text)) % 10000}",
                        category=ComponentCategory.EXPRESSIONS,
                        severity=Severity.MEDIUM if iif_count == 3 else Severity.HIGH,
                        classification=IssueClassification.DETECTED_ISSUE,
                        title=f"Deeply Nested IIF Expression (Depth: {iif_count})",
                        target_object=expr.location,
                        description=f"Expression contains {iif_count} levels of nested IIF statements.",
                        impact="Evaluates both true and false branches in VB.NET engine for every row, multiplying CPU time during pagination.",
                        remediation=iif_remediation,
                        code_snippet=text[:120] + ("..." if len(text) > 120 else ""),
                    )
                )

            # 2. Heavy Type Conversions inside expressions
            conversion_matches = re.findall(r"\b(CDate|CDbl|CStr|CInt|Val)\s*\(", text, re.IGNORECASE)
            if len(conversion_matches) >= 2:
                conv_remediation = (
                    "Cast data types in the SQL query directly (e.g., `CAST(x AS decimal)` or `CONVERT(...)`) so the database engine formats the data before retrieval."
                    if has_sql
                    else "Pre-format data types at the data source or configure explicit field datatypes in the dataset definition to avoid runtime VB.NET conversions."
                )
                issues.append(
                    PerformanceIssue(
                        id=f"EXPR-CONVERSION-{abs(hash(text)) % 10000}",
                        category=ComponentCategory.EXPRESSIONS,
                        severity=Severity.LOW,
                        classification=IssueClassification.POTENTIAL_OPTIMIZATION,
                        title="Repeated In-Memory Type Conversions",
                        target_object=expr.location,
                        description=f"Expression applies multiple type conversion functions: {', '.join(set(conversion_matches))}.",
                        impact="Re-evaluated for each cell in every row, causing avoidable CPU overhead during page rendering.",
                        remediation=conv_remediation,
                        code_snippet=text[:120],
                    )
                )

        # 3. Repeated Calculations
        for text, count in seen_expressions.items():
            if count >= 4 and len(text) > 40 and not text.startswith("=Fields!"):
                rep_remediation = (
                    "Define a single Calculated Field in the Dataset, or calculate the column inside the SQL query."
                    if has_sql
                    else "Define a single Calculated Field in the Dataset, or calculate the value once at the data source."
                )
                issues.append(
                    PerformanceIssue(
                        id=f"EXPR-REPEATED-{abs(hash(text)) % 10000}",
                        category=ComponentCategory.EXPRESSIONS,
                        severity=Severity.LOW,
                        classification=IssueClassification.POTENTIAL_OPTIMIZATION,
                        title=f"Repeated Expression Calculated {count} Times",
                        target_object="Multiple Report Locations",
                        description=f"The exact expression is calculated independently in {count} separate textboxes or cells.",
                        impact="Redundant CPU calculation cycles during report layout generation.",
                        remediation=rep_remediation,
                        code_snippet=text[:120] + ("..." if len(text) > 120 else ""),
                    )
                )

        # 4. Custom Code (<Code>) Inspection
        if rdl.custom_code:
            code = rdl.custom_code
            has_loops = bool(re.search(r"\b(For\s+|While\s+|Do\s+While)\b", code, re.IGNORECASE))
            code_remediation = (
                "Where possible, migrate business logic calculations into SQL views or stored procedures."
                if has_sql
                else "Where possible, pre-compute complex procedural logic at the data source before ingestion into report rendering."
            )
            issues.append(
                PerformanceIssue(
                    id="EXPR-CUSTOM-CODE",
                    category=ComponentCategory.EXPRESSIONS,
                    severity=Severity.MEDIUM if has_loops else Severity.LOW,
                    classification=IssueClassification.RUNTIME_VERIFIED_TARGET,
                    title="Embedded VB.NET Custom Code Detected",
                    target_object="Report Code Block",
                    description=f"Report contains embedded VB.NET code ({len(code.splitlines())} lines).{' Contains iterative loops.' if has_loops else ''}",
                    impact="VB.NET code blocks run in a restricted AppDomain sandbox in Power BI Paginated Report Service, incurring inter-process serialization overhead.",
                    remediation=code_remediation,
                    code_snippet=code[:200] + ("..." if len(code) > 200 else ""),
                )
            )

        return issues


class RecommendationEngine:
    """Component 5: Combines all diagnostic findings, calculates health score, and prepares actionable reports."""

    def compile_report(self, rdl: ParsedRDL) -> AnalysisResult:
        sql_analyzer = SQLQueryAnalyzer()
        param_analyzer = ParameterFilteringAnalyzer()
        struct_analyzer = DatasetStructureAnalyzer()
        expr_analyzer = ExpressionPerformanceAnalyzer()

        all_issues: List[PerformanceIssue] = []
        dataset_optimizations: Dict[str, DatasetOptimization] = {}

        # 1. SQL Analyzer
        for ds_name, ds in rdl.datasets.items():
            ds_issues, ds_opt = sql_analyzer.analyze(ds, rdl.datasets)
            all_issues.extend(ds_issues)
            if ds_opt and getattr(ds_opt, "query_type", "SQL") == "SQL":
                dataset_optimizations[ds_name] = ds_opt

        # 2. Parameter Analyzer
        all_issues.extend(param_analyzer.analyze(rdl))

        # 3. Structure Analyzer
        all_issues.extend(struct_analyzer.analyze(rdl))

        # 4. Expression Analyzer
        all_issues.extend(expr_analyzer.analyze(rdl))

        # Count issues by severity (exclude Info, Best Practice, and Runtime-Verified Target from score deductions)
        penalizing_issues = [
            i for i in all_issues
            if i.severity != Severity.INFO
            and i.classification not in (IssueClassification.BEST_PRACTICE, IssueClassification.RUNTIME_VERIFIED_TARGET)
        ]
        high_count = sum(1 for i in penalizing_issues if i.severity == Severity.HIGH)
        med_count = sum(1 for i in penalizing_issues if i.severity == Severity.MEDIUM)
        low_count = sum(1 for i in penalizing_issues if i.severity == Severity.LOW)

        # Progressive penalty function to avoid premature floor-collapse
        def _calc_high_penalty(cnt: int) -> int:
            if cnt <= 0:
                return 0
            if cnt == 1:
                return 14
            if cnt == 2:
                return 26
            if cnt == 3:
                return 36
            if cnt == 4:
                return 45
            return 45 + (cnt - 4) * 7

        def _calc_med_penalty(cnt: int) -> int:
            if cnt <= 0:
                return 0
            if cnt == 1:
                return 6
            if cnt == 2:
                return 11
            if cnt == 3:
                return 15
            if cnt == 4:
                return 19
            return 19 + (cnt - 4) * 3

        def _calc_low_penalty(cnt: int) -> int:
            return min(10, cnt * 1)

        p_high = _calc_high_penalty(high_count)
        p_med = _calc_med_penalty(med_count)
        p_low = _calc_low_penalty(low_count)
        total_penalty = p_high + p_med + p_low

        score = max(10, min(100, 100 - total_penalty))

        if score >= 85:
            status = "Excellent"
        elif score >= 70:
            status = "Good"
        elif score >= 50:
            status = "Fair"
        elif score >= 30:
            status = "Needs Optimization"
        else:
            status = "Critical Bottlenecks Detected"

        # Summary Metrics
        total_sql_queries = sum(1 for ds in rdl.datasets.values() if detect_query_type(ds) == "SQL" and ds.query_text)
        total_non_sql = len(rdl.datasets) - total_sql_queries
        total_queries = sum(1 for ds in rdl.datasets.values() if ds.query_text)
        total_subreports = len(rdl.subreports)
        total_fields_defined = sum(len(ds.fields) for ds in rdl.datasets.values())
        total_fields_used = sum(len(ds.used_field_names) for ds in rdl.datasets.values())

        metrics = {
            "total_datasets": len(rdl.datasets),
            "total_queries": total_queries,
            "total_sql_queries": total_sql_queries,
            "total_non_sql_datasets": total_non_sql,
            "total_parameters": len(rdl.parameters),
            "total_subreports": total_subreports,
            "total_fields_defined": total_fields_defined,
            "total_fields_used": total_fields_used,
            "unused_fields_count": total_fields_defined - total_fields_used,
            "total_issues": len(all_issues),
            "high_severity_count": high_count,
            "medium_severity_count": med_count,
            "low_severity_count": low_count,
            "score_breakdown": {
                "score_name": "Static Architecture Health Score",
                "base_score": 100,
                "high_deduction": p_high,
                "medium_deduction": p_med,
                "low_deduction": p_low,
                "final_score": score,
                "formula": f"Base 100 - {p_high} ({high_count} High) - {p_med} ({med_count} Med) - {p_low} ({low_count} Low) = {score}/100",
                "methodology": "Static rule-based deduction from base score 100 based on AST analysis and Power BI RDL architecture best practices. Does not measure runtime execution time or database latency.",
            },
        }

        # Build Field Usage Matrix
        field_usage_matrix = {}
        for ds_name, ds in rdl.datasets.items():
            field_usage_matrix[ds_name] = {
                "total_fields": len(ds.fields),
                "used_count": len(ds.used_field_names),
                "unused_count": len(ds.unused_field_names),
                "used_fields": sorted(list(ds.used_field_names)),
                "unused_fields": sorted(list(ds.unused_field_names)),
            }

        # High-level recommendation bullet points
        recs = []
        if high_count > 0:
            recs.append(f"Address {high_count} High-severity bottlenecks immediately (e.g. SELECT *, unpushed filters, N+1 subreport calls).")
        if any(i.id.startswith("SQL-STAR") for i in all_issues):
            recs.append("Replace wildcard SELECT * with explicit column projections to save database I/O and network payload.")
        if any(i.id.startswith("STRUCT-SUBREPORT-ROW") for i in all_issues):
            recs.append("Refactor subreports nested in repeating row groups into native Tablix groups to eliminate N+1 roundtrips.")
        if any(i.id.startswith("PARAM-UNPUSHED") for i in all_issues):
            recs.append("Push report parameters into SQL query WHERE clauses to avoid fetching unconstrained data.")
        if any(i.id.startswith("STRUCT-ORPHAN") for i in all_issues):
            recs.append("Remove orphan/unused datasets to reduce database connection overhead.")
        if not recs:
            recs.append("Report demonstrates sound architecture and parameter pushdown practices.")

        return AnalysisResult(
            report_name=rdl.report_name,
            health_score=score,
            health_status=status,
            summary_metrics=metrics,
            issues=all_issues,
            dataset_optimizations=dataset_optimizations,
            field_usage_matrix=field_usage_matrix,
            recommendations_summary=recs,
        )
