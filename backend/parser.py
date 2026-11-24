"""
RDL XML Parser
Extracts datasets, SQL queries, parameters, fields, expressions, subreports, and visual structures
from Power BI / SSRS Paginated Report XML definitions across all schema versions.
"""

from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any


@dataclass
class ReportParameter:
    name: str
    data_type: str = "String"
    prompt: Optional[str] = None
    default_values: List[str] = field(default_factory=list)
    multi_value: bool = False
    hidden: bool = False
    valid_values_dataset: Optional[str] = None
    valid_values_value_field: Optional[str] = None
    valid_values_label_field: Optional[str] = None
    default_values_dataset: Optional[str] = None
    default_values_value_field: Optional[str] = None


@dataclass
class DatasetField:
    name: str
    data_field: str
    type_name: Optional[str] = None
    is_calculated: bool = False
    calculation_expression: Optional[str] = None


@dataclass
class QueryParameter:
    name: str
    value: str


@dataclass
class DatasetFilter:
    expression: str
    operator: str
    values: List[str] = field(default_factory=list)


@dataclass
class DatasetInfo:
    name: str
    query_text: str = ""
    command_type: str = "Text"
    data_source_name: Optional[str] = None
    data_provider: Optional[str] = None
    query_type: str = "SQL"
    query_parameters: List[QueryParameter] = field(default_factory=list)
    fields: List[DatasetField] = field(default_factory=list)
    filters: List[DatasetFilter] = field(default_factory=list)
    referenced_in_visuals: int = 0
    referenced_in_parameters: int = 0
    referenced_in_expressions: int = 0
    is_parameter_dataset: bool = False
    is_embedded_xml: bool = False
    is_orphan: bool = False
    dependency_type: str = "Visual Bound"  # "Visual Bound", "Parameter Lookup", "Expression Dependency", "Orphan Candidate"
    used_field_names: Set[str] = field(default_factory=set)
    unused_field_names: Set[str] = field(default_factory=set)


@dataclass
class SubreportInfo:
    name: str
    report_name: str
    parent_container: Optional[str] = None
    in_row_group: bool = False
    parameters: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class VisualItem:
    item_type: str  # Tablix, Chart, Gauge, Textbox, Subreport, etc.
    name: str
    dataset_name: Optional[str] = None
    container: Optional[str] = None
    has_groups: bool = False
    group_expressions: List[str] = field(default_factory=list)
    filters: List[DatasetFilter] = field(default_factory=list)


@dataclass
class ExpressionInfo:
    text: str
    location: str
    dataset_name: Optional[str] = None
    expression_type: str = "Value"  # Value, Filter, Group, Visibility, etc.


@dataclass
class ParsedRDL:
    report_name: str
    schema_version: str = "2016"
    parameters: Dict[str, ReportParameter] = field(default_factory=dict)
    datasets: Dict[str, DatasetInfo] = field(default_factory=dict)
    subreports: List[SubreportInfo] = field(default_factory=list)
    visuals: List[VisualItem] = field(default_factory=list)
    expressions: List[ExpressionInfo] = field(default_factory=list)
    custom_code: Optional[str] = None
    raw_xml_length: int = 0


class RDLParser:
    """Parses RDL XML files into clean structured Python objects."""

    # Regex to capture field references: Fields!FieldName.Value or Fields("FieldName").Value
    FIELD_REF_REGEX = re.compile(
        r"Fields!([a-zA-Z0-9_#]+)(?:\.Value)?|Fields\((\"|')([a-zA-Z0-9_#]+)\2\)(?:\.Value)?",
        re.IGNORECASE,
    )

    # Regex to capture parameter references: Parameters!ParamName.Value
    PARAM_REF_REGEX = re.compile(
        r"Parameters!([a-zA-Z0-9_#]+)(?:\.Value)?|Parameters\((\"|')([a-zA-Z0-9_#]+)\2\)(?:\.Value)?",
        re.IGNORECASE,
    )

    def parse_string(self, xml_content: str, report_name: str = "Report") -> ParsedRDL:
        """Parses an RDL XML string."""
        # Strip XML namespaces for uniform tag processing regardless of RDL version
        cleaned_xml = self._strip_namespaces(xml_content)
        root = ET.fromstring(cleaned_xml)
        return self._extract_rdl_components(root, report_name, len(xml_content))

    def parse_file(self, file_path: str) -> ParsedRDL:
        """Parses an RDL file from disk."""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        import os
        report_name = os.path.splitext(os.path.basename(file_path))[0]
        return self.parse_string(content, report_name)

    def _strip_namespaces(self, xml_str: str) -> str:
        """Removes XML namespaces to simplify XPath and element searches."""
        # Remove xmlns attributes
        clean = re.sub(r'\sxmlns(?::\w+)?="[^"]*"', "", xml_str)
        # Remove namespace prefixes from tags like <df:Report> -> <Report>
        clean = re.sub(r"<(/)?([a-zA-Z0-9_]+):", r"<\1", clean)
        return clean

    def _extract_rdl_components(
        self, root: ET.Element, report_name: str, raw_length: int
    ) -> ParsedRDL:
        schema_version = root.attrib.get("xmlns", "Standard RDL")

        parsed = ParsedRDL(
            report_name=report_name,
            schema_version=schema_version,
            raw_xml_length=raw_length,
        )

        # 1. Extract DataSources map (name -> data_provider)
        data_sources = self._extract_data_sources(root)

        # 2. Extract Report Parameters
        parsed.parameters = self._extract_parameters(root)

        # 3. Extract DataSets
        parsed.datasets = self._extract_datasets(root, data_sources)

        # 4. Extract Custom Code (<Code>)
        code_elem = root.find("Code")
        if code_elem is not None and code_elem.text:
            parsed.custom_code = code_elem.text.strip()

        # 5. Extract Visuals, Subreports, and Expressions
        self._extract_body_items(root, parsed)

        # 6. Compute Field Usage Mapping across all datasets
        self._compute_field_usage(parsed, root)

        return parsed

    def _extract_data_sources(self, root: ET.Element) -> Dict[str, str]:
        sources = {}
        for ds_elem in root.findall(".//DataSource"):
            name = ds_elem.attrib.get("Name")
            if not name:
                continue
            dp_elem = ds_elem.find(".//DataProvider")
            dp = dp_elem.text.strip() if dp_elem is not None and dp_elem.text else ""
            sources[name] = dp
        return sources

    def _extract_parameters(self, root: ET.Element) -> Dict[str, ReportParameter]:
        params = {}
        for param_elem in root.findall(".//ReportParameter"):
            name = param_elem.attrib.get("Name")
            if not name:
                continue

            dt_elem = param_elem.find("DataType")
            data_type = dt_elem.text.strip() if dt_elem is not None and dt_elem.text else "String"

            prompt_elem = param_elem.find("Prompt")
            prompt = prompt_elem.text.strip() if prompt_elem is not None and prompt_elem.text else None

            mv_elem = param_elem.find("MultiValue")
            multi_value = mv_elem is not None and mv_elem.text and mv_elem.text.lower() == "true"

            hidden_elem = param_elem.find("Hidden")
            hidden = hidden_elem is not None and hidden_elem.text and hidden_elem.text.lower() == "true"

            default_values = []
            for val_elem in param_elem.findall(".//DefaultValue/Values/Value"):
                if val_elem.text:
                    default_values.append(val_elem.text.strip())

            # ValidValues / DataSetReference
            valid_ds = None
            valid_vf = None
            valid_lf = None
            vv_ref = param_elem.find(".//ValidValues/DataSetReference")
            if vv_ref is not None:
                ds_name_e = vv_ref.find("DataSetName")
                if ds_name_e is not None and ds_name_e.text:
                    valid_ds = ds_name_e.text.strip()
                vf_e = vv_ref.find("ValueField")
                if vf_e is not None and vf_e.text:
                    valid_vf = vf_e.text.strip()
                lf_e = vv_ref.find("LabelField")
                if lf_e is not None and lf_e.text:
                    valid_lf = lf_e.text.strip()

            # DefaultValue / DataSetReference
            default_ds = None
            default_vf = None
            dv_ref = param_elem.find(".//DefaultValue/DataSetReference")
            if dv_ref is not None:
                ds_name_e = dv_ref.find("DataSetName")
                if ds_name_e is not None and ds_name_e.text:
                    default_ds = ds_name_e.text.strip()
                vf_e = dv_ref.find("ValueField")
                if vf_e is not None and vf_e.text:
                    default_vf = vf_e.text.strip()

            params[name] = ReportParameter(
                name=name,
                data_type=data_type,
                prompt=prompt,
                default_values=default_values,
                multi_value=multi_value,
                hidden=hidden,
                valid_values_dataset=valid_ds,
                valid_values_value_field=valid_vf,
                valid_values_label_field=valid_lf,
                default_values_dataset=default_ds,
                default_values_value_field=default_vf,
            )
        return params

    def _extract_datasets(
        self, root: ET.Element, data_sources: Optional[Dict[str, str]] = None
    ) -> Dict[str, DatasetInfo]:
        datasets = {}
        for ds_elem in root.findall(".//DataSet"):
            name = ds_elem.attrib.get("Name")
            if not name:
                continue

            query_elem = ds_elem.find("Query")
            query_text = ""
            command_type = "Text"
            data_source_name = None
            query_params = []

            if query_elem is not None:
                cmd_elem = query_elem.find("CommandText")
                if cmd_elem is not None and cmd_elem.text:
                    query_text = cmd_elem.text.strip()

                cmd_type_elem = query_elem.find("CommandType")
                if cmd_type_elem is not None and cmd_type_elem.text:
                    command_type = cmd_type_elem.text.strip()

                ds_name_elem = query_elem.find("DataSourceName")
                if ds_name_elem is not None and ds_name_elem.text:
                    data_source_name = ds_name_elem.text.strip()

                for qp_elem in query_elem.findall(".//QueryParameter"):
                    qp_name = qp_elem.attrib.get("Name", "")
                    qp_val_elem = qp_elem.find("Value")
                    qp_val = qp_val_elem.text.strip() if qp_val_elem is not None and qp_val_elem.text else ""
                    query_params.append(QueryParameter(name=qp_name, value=qp_val))

            # Fields
            fields = []
            for f_elem in ds_elem.findall(".//Field"):
                f_name = f_elem.attrib.get("Name", "")
                df_elem = f_elem.find("DataField")
                data_field = df_elem.text.strip() if df_elem is not None and df_elem.text else f_name

                val_elem = f_elem.find("Value")
                is_calc = val_elem is not None and val_elem.text is not None
                calc_expr = val_elem.text.strip() if is_calc else None

                type_elem = f_elem.find("TypeName")
                type_name = type_elem.text.strip() if type_elem is not None and type_elem.text else None

                fields.append(
                    DatasetField(
                        name=f_name,
                        data_field=data_field,
                        type_name=type_name,
                        is_calculated=is_calc,
                        calculation_expression=calc_expr,
                    )
                )

            # In-memory Dataset Filters
            filters = []
            for flt_elem in ds_elem.findall(".//Filter"):
                fe_elem = flt_elem.find("FilterExpression")
                expr = fe_elem.text.strip() if fe_elem is not None and fe_elem.text else ""
                op_elem = flt_elem.find("Operator")
                op = op_elem.text.strip() if op_elem is not None and op_elem.text else "Equal"
                vals = [
                    v.text.strip()
                    for v in flt_elem.findall(".//FilterValues/FilterValue")
                    if v.text
                ]
                filters.append(DatasetFilter(expression=expr, operator=op, values=vals))

            data_provider = None
            if data_source_name and data_sources and data_source_name in data_sources:
                data_provider = data_sources[data_source_name]

            # Source awareness: Check for embedded XML or ENTERDATA
            is_embedded_xml = False
            has_datagrid = query_elem is not None and query_elem.find(".//DataGrid") is not None
            if (data_provider and data_provider.upper() in ["ENTERDATA", "XML", "XMLDATA"]) or has_datagrid:
                is_embedded_xml = True

            # Determine dataset query type
            q_type = "SQL"
            if data_provider and data_provider.upper() == "ENTERDATA":
                q_type = "XML/EnterData"
            elif is_embedded_xml:
                q_type = "XML/EnterData"
            elif data_provider and data_provider.upper() in ["XML", "XMLDATA", "SHAREPOINT", "SHAREPOINTLIST"]:
                q_type = "XML"
            elif data_provider and data_provider.upper() in ["MSDAX", "POWERBI", "ASAZURE", "SSAS"]:
                q_type = "DAX"
            elif command_type.lower() == "storedprocedure":
                q_type = "StoredProcedure"

            datasets[name] = DatasetInfo(
                name=name,
                query_text=query_text,
                command_type=command_type,
                data_source_name=data_source_name,
                data_provider=data_provider,
                query_type=q_type,
                query_parameters=query_params,
                fields=fields,
                filters=filters,
                is_embedded_xml=is_embedded_xml,
            )

        return datasets

    def _extract_body_items(self, root: ET.Element, parsed: ParsedRDL) -> None:
        """Walks report body to extract visual items, expressions, and subreports."""
        # Search for Tablix components
        for tablix in root.findall(".//Tablix"):
            t_name = tablix.attrib.get("Name", "UnnamedTablix")
            ds_elem = tablix.find("DataSetName")
            ds_name = ds_elem.text.strip() if ds_elem is not None and ds_elem.text else None

            # Check for group expressions
            group_exprs = []
            for ge in tablix.findall(".//GroupExpression"):
                if ge.text:
                    group_exprs.append(ge.text.strip())
                    parsed.expressions.append(
                        ExpressionInfo(
                            text=ge.text.strip(),
                            location=f"Tablix '{t_name}' Group",
                            dataset_name=ds_name,
                            expression_type="Group",
                        )
                    )

            # Tablix Filters
            t_filters = []
            for flt_elem in tablix.findall(".//Filter"):
                fe_elem = flt_elem.find("FilterExpression")
                expr = fe_elem.text.strip() if fe_elem is not None and fe_elem.text else ""
                op_elem = flt_elem.find("Operator")
                op = op_elem.text.strip() if op_elem is not None and op_elem.text else "Equal"
                vals = [
                    v.text.strip()
                    for v in flt_elem.findall(".//FilterValues/FilterValue")
                    if v.text
                ]
                t_filters.append(DatasetFilter(expression=expr, operator=op, values=vals))
                parsed.expressions.append(
                    ExpressionInfo(
                        text=expr,
                        location=f"Tablix '{t_name}' Filter",
                        dataset_name=ds_name,
                        expression_type="Filter",
                    )
                )

            parsed.visuals.append(
                VisualItem(
                    item_type="Tablix",
                    name=t_name,
                    dataset_name=ds_name,
                    has_groups=len(group_exprs) > 0,
                    group_expressions=group_exprs,
                    filters=t_filters,
                )
            )

            # Check if any Subreport is inside this Tablix row hierarchy (repeating $N+1$ hazard)
            for sub_elem in tablix.findall(".//Subreport"):
                sub_name = sub_elem.attrib.get("Name", "UnnamedSubreport")
                rep_elem = sub_elem.find("ReportName")
                rep_name = rep_elem.text.strip() if rep_elem is not None and rep_elem.text else "Unknown"

                # Check if it's inside TablixBody / TablixRowHierarchy
                in_rows = tablix.find(".//TablixRowHierarchy//Subreport") is not None or \
                          tablix.find(".//TablixBody//Subreport") is not None

                sub_params = []
                for p in sub_elem.findall(".//Parameter"):
                    p_name = p.attrib.get("Name", "")
                    pv_elem = p.find("Value")
                    p_val = pv_elem.text.strip() if pv_elem is not None and pv_elem.text else ""
                    sub_params.append({"name": p_name, "value": p_val})

                parsed.subreports.append(
                    SubreportInfo(
                        name=sub_name,
                        report_name=rep_name,
                        parent_container=f"Tablix '{t_name}'",
                        in_row_group=in_rows,
                        parameters=sub_params,
                    )
                )

        # Standalone Subreports (outside Tablix)
        for sub_elem in root.findall(".//ReportItems/Subreport"):
            sub_name = sub_elem.attrib.get("Name", "UnnamedSubreport")
            # If not already recorded from Tablix
            if not any(s.name == sub_name for s in parsed.subreports):
                rep_elem = sub_elem.find("ReportName")
                rep_name = rep_elem.text.strip() if rep_elem is not None and rep_elem.text else "Unknown"
                sub_params = []
                for p in sub_elem.findall(".//Parameter"):
                    p_name = p.attrib.get("Name", "")
                    pv_elem = p.find("Value")
                    p_val = pv_elem.text.strip() if pv_elem is not None and pv_elem.text else ""
                    sub_params.append({"name": p_name, "value": p_val})

                parsed.subreports.append(
                    SubreportInfo(
                        name=sub_name,
                        report_name=rep_name,
                        parent_container="Body",
                        in_row_group=False,
                        parameters=sub_params,
                    )
                )

        # Visuals: Charts, Gauges
        for chart in root.findall(".//Chart"):
            c_name = chart.attrib.get("Name", "UnnamedChart")
            ds_elem = chart.find("DataSetName")
            ds_name = ds_elem.text.strip() if ds_elem is not None and ds_elem.text else None
            parsed.visuals.append(VisualItem(item_type="Chart", name=c_name, dataset_name=ds_name))

        for gauge in root.findall(".//GaugePanel"):
            g_name = gauge.attrib.get("Name", "UnnamedGauge")
            ds_elem = gauge.find("DataSetName")
            ds_name = ds_elem.text.strip() if ds_elem is not None and ds_elem.text else None
            parsed.visuals.append(VisualItem(item_type="Gauge", name=g_name, dataset_name=ds_name))

        # Extract all Value expressions (Textboxes, calculations, etc.)
        for val_elem in root.findall(".//Value"):
            if val_elem.text and val_elem.text.strip().startswith("="):
                parent_tag = "Unknown"
                ds_context = None

                # Find ancestor dataset if possible
                # Simple check: does the expression explicitly state dataset scope? e.g. Sum(..., "SalesDataset")
                expr_text = val_elem.text.strip()
                scope_match = re.search(r'["\']([a-zA-Z0-9_]+)["\']', expr_text)
                if scope_match and scope_match.group(1) in parsed.datasets:
                    ds_context = scope_match.group(1)

                parsed.expressions.append(
                    ExpressionInfo(
                        text=expr_text,
                        location="ReportItem Value",
                        dataset_name=ds_context,
                        expression_type="Value",
                    )
                )

        # Extract Hidden expressions (Conditional Visibility)
        for hid_elem in root.findall(".//Hidden"):
            if hid_elem.text and hid_elem.text.strip().startswith("="):
                parsed.expressions.append(
                    ExpressionInfo(
                        text=hid_elem.text.strip(),
                        location="Visibility Hidden",
                        expression_type="Visibility",
                    )
                )

    def _compute_field_usage(self, parsed: ParsedRDL, root: Optional[ET.Element] = None) -> None:
        """Cross-references dataset fields with their actual scoped visuals, parameters, and expressions to determine genuine usage."""
        scoped_fields: Dict[str, Set[str]] = {name: set() for name in parsed.datasets}

        # Reset counts
        for ds in parsed.datasets.values():
            ds.referenced_in_visuals = 0
            ds.referenced_in_parameters = 0
            ds.referenced_in_expressions = 0

        # 1. Scoped visual extraction from XML tree
        if root is not None:
            # Tablix elements
            for tablix in root.findall(".//Tablix"):
                ds_elem = tablix.find("DataSetName")
                ds_name = ds_elem.text.strip() if ds_elem is not None and ds_elem.text else None
                if ds_name and ds_name in parsed.datasets:
                    parsed.datasets[ds_name].referenced_in_visuals += 1
                    for elem in tablix.iter():
                        if elem.text:
                            for m in self.FIELD_REF_REGEX.findall(elem.text):
                                fn = m[0] or m[2]
                                if fn:
                                    scoped_fields[ds_name].add(fn.lower())

            # Chart elements
            for chart in root.findall(".//Chart"):
                ds_elem = chart.find("DataSetName")
                ds_name = ds_elem.text.strip() if ds_elem is not None and ds_elem.text else None
                if ds_name and ds_name in parsed.datasets:
                    parsed.datasets[ds_name].referenced_in_visuals += 1
                    for elem in chart.iter():
                        if elem.text:
                            for m in self.FIELD_REF_REGEX.findall(elem.text):
                                fn = m[0] or m[2]
                                if fn:
                                    scoped_fields[ds_name].add(fn.lower())

            # GaugePanel elements
            for gauge in root.findall(".//GaugePanel"):
                ds_elem = gauge.find("DataSetName")
                ds_name = ds_elem.text.strip() if ds_elem is not None and ds_elem.text else None
                if ds_name and ds_name in parsed.datasets:
                    parsed.datasets[ds_name].referenced_in_visuals += 1
                    for elem in gauge.iter():
                        if elem.text:
                            for m in self.FIELD_REF_REGEX.findall(elem.text):
                                fn = m[0] or m[2]
                                if fn:
                                    scoped_fields[ds_name].add(fn.lower())

        # 2. Track parameter dataset references and parameter lookup fields
        for param in parsed.parameters.values():
            if param.valid_values_dataset and param.valid_values_dataset in parsed.datasets:
                ds = parsed.datasets[param.valid_values_dataset]
                ds.referenced_in_parameters += 1
                ds.is_parameter_dataset = True
                if param.valid_values_value_field:
                    scoped_fields[param.valid_values_dataset].add(param.valid_values_value_field.lower())
                if param.valid_values_label_field:
                    scoped_fields[param.valid_values_dataset].add(param.valid_values_label_field.lower())

            if param.default_values_dataset and param.default_values_dataset in parsed.datasets:
                ds = parsed.datasets[param.default_values_dataset]
                ds.referenced_in_parameters += 1
                ds.is_parameter_dataset = True
                if param.default_values_value_field:
                    scoped_fields[param.default_values_dataset].add(param.default_values_value_field.lower())

        # 3. Track explicit scoped expressions (Lookup, Sum with scope)
        for expr in parsed.expressions:
            # Check Lookup functions: Lookup(..., ..., ReturnField, "DatasetName")
            m_lookup = re.search(r'Lookup(?:Set)?\s*\([^,]+,[^,]+,\s*([^,]+),\s*["\']([^"\']+)["\']\s*\)', expr.text, re.IGNORECASE)
            if m_lookup:
                res_expr = m_lookup.group(1)
                target_ds = m_lookup.group(2)
                if target_ds in parsed.datasets:
                    parsed.datasets[target_ds].referenced_in_expressions += 1
                    for m in self.FIELD_REF_REGEX.findall(res_expr):
                        fn = m[0] or m[2]
                        if fn:
                            scoped_fields[target_ds].add(fn.lower())

            # Check Aggregates with scope: Sum(Fields!X.Value, "DatasetName")
            m_agg = re.search(r'(?:Sum|Avg|Count|First|Last|Min|Max)\s*\(\s*Fields!([a-zA-Z0-9_]+)\.Value\s*,\s*["\']([^"\']+)["\']\s*\)', expr.text, re.IGNORECASE)
            if m_agg:
                fn = m_agg.group(1)
                target_ds = m_agg.group(2)
                if target_ds in parsed.datasets:
                    parsed.datasets[target_ds].referenced_in_expressions += 1
                    scoped_fields[target_ds].add(fn.lower())

        # 4. If report has ONLY 1 dataset, all unbound expressions belong to it
        if len(parsed.datasets) == 1 and root is not None:
            single_ds_name = list(parsed.datasets.keys())[0]
            for elem in root.iter():
                if elem.text:
                    for m in self.FIELD_REF_REGEX.findall(elem.text):
                        fn = m[0] or m[2]
                        if fn:
                            scoped_fields[single_ds_name].add(fn.lower())

        # 5. Check dataset filters and assign used/unused fields + dependency_type
        for ds_name, ds in parsed.datasets.items():
            # Include fields used in dataset filters
            for flt in ds.filters:
                for m in self.FIELD_REF_REGEX.findall(flt.expression):
                    fn = m[0] or m[2]
                    if fn:
                        scoped_fields[ds_name].add(fn.lower())

            has_deps = (
                ds.referenced_in_visuals > 0
                or ds.referenced_in_parameters > 0
                or ds.referenced_in_expressions > 0
                or ds.is_parameter_dataset
            )
            # If no direct visual or parameter ref, check if explicitly named in any expression text
            if not has_deps and any(f'"{ds_name.lower()}"' in expr.text.lower() or f"'{ds_name.lower()}'" in expr.text.lower() for expr in parsed.expressions):
                has_deps = True
                ds.referenced_in_expressions += 1

            if not has_deps:
                ds.is_orphan = True
                ds.dependency_type = "Orphan Candidate"
                ds.used_field_names = set()
                ds.unused_field_names = {f.name for f in ds.fields}
            else:
                ds.is_orphan = False
                if ds.referenced_in_visuals > 0:
                    ds.dependency_type = "Visual Bound"
                elif ds.referenced_in_parameters > 0 or ds.is_parameter_dataset:
                    ds.dependency_type = "Parameter Lookup"
                else:
                    ds.dependency_type = "Expression Dependency"

                fset = scoped_fields.get(ds_name, set())
                used = set()
                unused = set()
                for f in ds.fields:
                    f_norm = f.name.lower()
                    df_norm = f.data_field.lower()
                    if f_norm in fset or df_norm in fset:
                        used.add(f.name)
                    else:
                        unused.add(f.name)
                ds.used_field_names = used
                ds.unused_field_names = unused
