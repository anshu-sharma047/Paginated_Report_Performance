"""
Azure OpenAI LLM Client
Provides enterprise-grade AI diagnostic reasoning, executive summaries,
and SQL optimization explanations using Azure OpenAI (e.g. gpt-5-mini, gpt-4o).
Falls back deterministically to rule-based diagnostics if credentials are not configured or offline.
"""

from __future__ import annotations
import os
import json
import re
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

load_dotenv()


class AzureOpenAIService:
    """Interfaces with Azure OpenAI Service for intelligent report analysis."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        deployment: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.endpoint = (
            endpoint if endpoint is not None else os.getenv("AZURE_OPENAI_ENDPOINT", "")
        ).strip().rstrip("/")
        self.api_key = (
            api_key if api_key is not None else os.getenv("AZURE_OPENAI_API_KEY", "")
        ).strip()
        self.deployment = (
            deployment
            if deployment is not None
            else (
                os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
                or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
                or "gpt-5-mini"
            )
        ).strip()
        self.api_version = (
            api_version
            if api_version is not None
            else (os.getenv("AZURE_OPENAI_API_VERSION") or "2024-08-01-preview")
        ).strip()

    def is_available(self) -> bool:
        """Checks if valid Azure OpenAI configuration is set (not dummy placeholders)."""
        if not self.endpoint or not self.api_key:
            return False
        if "your-resource-name" in self.endpoint or "your_azure_openai" in self.api_key:
            return False
        return True

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: int = 1500,
    ) -> Optional[str]:
        """
        Sends a chat completion request to Azure OpenAI.
        Supports both Azure AI Foundry v1 routes and standard Azure OpenAI deployment routes.
        Handles reasoning models (gpt-5-mini, o1/o3) using max_completion_tokens.
        """
        if not self.is_available():
            return None

        # Determine target endpoint URLs to try
        urls_to_try = []
        if self.endpoint.endswith("/openai/v1"):
            urls_to_try.append(f"{self.endpoint}/chat/completions")
            base = self.endpoint.replace("/openai/v1", "")
            urls_to_try.append(f"{base}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}")
        else:
            urls_to_try.append(f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}")
            urls_to_try.append(f"{self.endpoint}/openai/v1/chat/completions")

        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

        # Build payloads (reasoning models require max_completion_tokens; older models use max_tokens)
        payload_modern = {
            "model": self.deployment,
            "messages": messages,
            "max_completion_tokens": max(max_tokens, 1500),
        }
        if temperature is not None:
            payload_modern["temperature"] = temperature

        payload_legacy = {
            "model": self.deployment,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload_legacy["temperature"] = temperature

        import requests
        for url in urls_to_try:
            for payload in [payload_modern, payload_legacy]:
                try:
                    res = requests.post(url, headers=headers, json=payload, timeout=25.0)
                    if res.status_code == 200:
                        data = res.json()
                        choices = data.get("choices", [])
                        if choices and choices[0].get("message"):
                            content = choices[0]["message"].get("content")
                            if content:
                                return content.strip()
                    elif res.status_code == 400 and "max_completion_tokens" in res.text:
                        continue  # Try legacy max_tokens payload
                    elif res.status_code == 400 and "max_tokens" in res.text:
                        continue  # Try modern payload
                except Exception as ex:
                    print(f"[AzureOpenAI] Attempt to {url} failed: {ex}")
                    continue

        return None

    def explain_issue(
        self,
        issue_title: str,
        target: str,
        description: str,
        impact: str,
        remediation: str = "",
    ) -> str:
        """Provides technical deep dive explanation for a specific finding."""
        if not self.is_available():
            return (
                f"**Rule-based Analysis**: {description}\n\n"
                f"**Engine Impact**: {impact}\n\n"
                f"**Remediation**: {remediation or 'Review report design according to SSRS guidelines.'}"
            )

        messages = [
            {
                "role": "user",
                "content": f"""You are a Principal Power BI & SSRS Database Architect at Xebia.
Analyze this paginated report performance bottleneck and provide actionable recommendations:

Issue Title: {issue_title}
Target Object: {target}
Detected Problem: {description}
Engine Impact: {impact}
Initial Recommendation: {remediation}

Provide a concise, professional assessment covering:
1. Root Cause in Power BI / SSRS Engine Architecture
2. Exact Technical Fix (SQL or RDL modification)
3. Database Indexing or Schema Suggestion (if applicable)

Format using clean markdown with bullet points."""
            }
        ]

        res = self.chat_completion(messages, max_tokens=1500)
        if res:
            return res.strip()

        return (
            f"**Technical Diagnosis**: {description}\n\n"
            f"**Engine Impact**: {impact}\n\n"
            f"**Recommended Action**: {remediation or 'Prune unreferenced columns and push filters to SQL.'}"
        )

    def optimize_sql(
        self,
        original_query: str,
        used_fields: List[str],
        parameters: List[str],
    ) -> Dict[str, Any]:
        """Generates an AI-optimized SQL query with explanation and indexing advice."""
        if not self.is_available():
            # Deterministic fallback
            fields_str = ", ".join(f"[{f}]" for f in used_fields) if used_fields else "*"
            return {
                "suggested_query": f"SELECT {fields_str} FROM ... -- Rule-based suggestion",
                "explanation": "Optimized query projects only fields bound to report visual elements.",
                "reasons": ["Pruned unreferenced columns to reduce memory overhead"],
                "indexing_advice": "Ensure an index covers the WHERE predicate columns.",
            }

        fields_list_str = ", ".join(used_fields) if used_fields else "All referenced visual fields"
        params_str = ", ".join(parameters) if parameters else "None"

        messages = [
            {
                "role": "user",
                "content": f"""You are a SQL Performance Architect at Xebia specializing in Power BI Paginated Reports.
Optimize this original SQL query extracted from an RDL report.

Original Query:
```sql
{original_query}
```

Fields Actually Bound to Report Visuals:
{fields_list_str}

Available Report Parameters:
{params_str}

Rules:
1. ONLY project the fields bound to report visuals (never use SELECT *).
2. Make all WHERE predicates sargable (convert YEAR(col)=2026 into col >= '2026-01-01' AND col < '2027-01-01').
3. Do NOT invent non-existent tables or columns.
4. Output your answer in JSON format with keys:
   - "suggested_query": the optimized SQL string
   - "explanation": concise explanation of changes
   - "indexing_advice": recommended database index DDL
"""
            }
        ]

        raw = self.chat_completion(messages, max_tokens=1800)
        if raw:
            try:
                cleaned = raw.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                    cleaned = re.sub(r"\n?```$", "", cleaned)
                parsed = json.loads(cleaned)
                return {
                    "suggested_query": parsed.get("suggested_query", original_query),
                    "explanation": parsed.get("explanation", "Optimized by Azure OpenAI (gpt-5-mini)."),
                    "reasons": ["AI Sargability Refinement", "Projected Visual Fields Only"],
                    "indexing_advice": parsed.get("indexing_advice", ""),
                }
            except Exception:
                return {
                    "suggested_query": raw,
                    "explanation": "Optimized by Azure OpenAI (gpt-5-mini).",
                    "reasons": ["Sargable Predicate Conversion", "Selective Column Projection"],
                    "indexing_advice": "Create supporting index on filtered columns.",
                }

        return {
            "suggested_query": original_query,
            "explanation": "Original query retained (AI optimization unavailable).",
            "reasons": [],
            "indexing_advice": "",
        }

    def generate_executive_assessment(
        self,
        report_name: str,
        health_score: int,
        health_status: str,
        metrics: Dict[str, Any],
        issues: List[Dict[str, Any]],
    ) -> str:
        """Generates a concise, high-impact executive assessment for client stakeholders."""
        critical_high = [i for i in issues if i.get("severity") in ("Critical", "High")]
        top_concerns = [f"{i.get('target_object', 'Unknown')}: {i.get('title', '')}" for i in critical_high[:5]]
        if not top_concerns and issues:
            top_concerns = [f"{i.get('target_object', 'Unknown')}: {i.get('title', '')}" for i in issues[:3]]

        total_datasets = metrics.get("total_datasets", 0)
        total_sql = metrics.get("total_sql_queries", 0)
        total_non_sql = metrics.get("total_non_sql_datasets", max(0, total_datasets - total_sql))
        unused_cols = metrics.get("unused_fields_count", 0)

        user_prompt = f"""You are a Principal Power BI & SSRS Performance Architect at Xebia.
Write an executive technical assessment of a Power BI Paginated Report performance audit.
Address technical leadership and project managers. Keep it concise, authoritative, and structured in 2 paragraphs.

Report Name: {report_name}
Overall Performance Health Score: {health_score}/100 ({health_status})
Total Datasets: {total_datasets} (Relational SQL: {total_sql}, Non-SQL/XML/EnterData/DAX: {total_non_sql})
Critical & High Issues: {len(critical_high)}
Total Detected Issues: {len(issues)}
Unused Columns Fetched: {unused_cols}
Primary Issues Detected:
{chr(10).join(f"- {c}" for c in top_concerns) if top_concerns else "- No critical issues detected"}

Strict Constraints:
- If Relational SQL is 0, do NOT mention SQL WHERE clauses, table indexing, non-sargable SQL functions, or SQL query tuning. Instead, focus on report architecture, unused dataset columns, XML/EnterData payload parsing, expression efficiency, and SSRS rendering memory.
- Base your analysis strictly on the detected issues above. Do not assume issues that are not reported.
- Structure in 2 concise paragraphs:
  1. Executive Assessment: Overview of report health, why bottlenecks exist based on the detected issues, and primary latency driver (query execution, gateway network payload, or SSRS rendering memory).
  2. Recommended Action: Clear, prioritized guidance on the top remediation items tailored to this specific report.
"""
        messages = [{"role": "user", "content": user_prompt}]

        llm_response = self.chat_completion(messages, max_tokens=1500)
        if llm_response:
            return llm_response.strip()

        # Dynamic Rule-Based Fallback (constructed strictly from actual report findings)
        issue_titles = [i.get("title", "") for i in (critical_high if critical_high else issues[:3])]
        primary_issues_str = ", ".join(issue_titles[:3]) if issue_titles else "identified structural items"

        if health_score < 50:
            if total_sql > 0:
                p1 = (
                    f"The performance assessment for <strong>{report_name}</strong> reveals critical bottlenecks "
                    f"(Health Score: {health_score}/100, Status: {health_status}). The primary latency drivers include "
                    f"{primary_issues_str}, combined with {unused_cols} unreferenced columns across database queries, "
                    f"which inflate network transfer and strain SSRS execution memory."
                )
                p2 = (
                    f"Immediate remediation must prioritize optimizing relational SQL queries, pruning {unused_cols} unused columns "
                    f"from dataset projections, and ensuring parameter predicates are pushed down to source queries. Implementing these "
                    f"targeted optimizations will significantly lower retrieval latency and memory pool saturation."
                )
            else:
                p1 = (
                    f"The performance assessment for <strong>{report_name}</strong> reveals critical design and payload bottlenecks "
                    f"(Health Score: {health_score}/100, Status: {health_status}). Across {total_datasets} datasets, the primary latency drivers "
                    f"stem from {primary_issues_str}, accompanied by {unused_cols} unused fields that increase in-memory deserialization overhead."
                )
                p2 = (
                    f"Immediate remediation must focus on pruning unreferenced dataset fields, removing redundant or orphan datasets, "
                    f"and streamlining visual expressions. Reducing memory overhead will enhance client rendering speeds and concurrent capacity."
                )
        elif health_score < 80:
            p1 = (
                f"The technical assessment for <strong>{report_name}</strong> indicates moderate performance degradation "
                f"(Health Score: {health_score}/100, Status: {health_status}). The report functions properly, but performance can be improved "
                f"by addressing {primary_issues_str} and pruning {unused_cols} unused fields."
            )
            p2 = (
                f"We recommend pruning {unused_cols} unreferenced fields from dataset definitions to reduce network and serialization overhead, "
                f"and reviewing Tablix expressions to avoid repetitive in-memory type conversions."
            )
        else:
            p1 = (
                f"The technical audit for <strong>{report_name}</strong> confirms a well-architected report definition "
                f"(Health Score: {health_score}/100, Status: {health_status}). Dataset projections are focused and visual bindings "
                f"follow established SSRS and Power BI enterprise standards."
            )
            p2 = (
                "Continuous monitoring via Power BI Premium Capacity metrics and standard operational logging is recommended to ensure response "
                "times remain within SLA thresholds under peak concurrent report generation."
            )

        return f"<p>{p1}</p><p>{p2}</p>"
