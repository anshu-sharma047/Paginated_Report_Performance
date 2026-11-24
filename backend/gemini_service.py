"""
Gemini AI Service
Provides AI-assisted query optimization, performance bottleneck explanations,
and client-ready executive diagnostic summaries using Google Gemini.
Falls back seamlessly to rule-based engine when API key is unavailable.
"""

from __future__ import annotations
import os
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

load_dotenv()


class GeminiService:
    """Interfaces with Google Gemini for intelligent performance optimization."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = None
        self._init_client()

    def _init_client(self) -> None:
        if not self.api_key:
            return
        try:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
        except Exception as e:
            print(f"[GeminiService] Warning: Failed to initialize Gemini client: {e}")
            self.client = None

    def is_available(self) -> bool:
        return self.client is not None

    def explain_issue(self, issue_title: str, target: str, description: str, impact: str) -> str:
        """Generates deep technical insight explaining why an issue affects Paginated Report rendering."""
        if not self.is_available():
            return (
                f"**Rule-based Analysis**: {description}\n\n"
                f"**Engine Impact**: {impact}\n\n"
                f"_Tip: Configure `GEMINI_API_KEY` in `.env` to enable dynamic AI query optimization and index guidance._"
            )

        prompt = f"""
You are a Principal Power BI & SSRS Performance Architect.
Explain this paginated report bottleneck to a client engineering team:

Issue: {issue_title}
Target Object: {target}
Description: {description}
Engine Impact: {impact}

Provide:
1. Deep Technical Cause (Why this degrades Power BI Paginated Report Service memory or query processing).
2. T-SQL / RDL Best Practice Solution.
3. Database Indexing or Schema Suggestion if applicable.

Keep your response concise, bulleted, and actionable.
"""
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            return response.text or description
        except Exception as e:
            return f"{description}\n\n*(AI service error: {e}. Falling back to rule-based diagnosis)*"

    def optimize_sql_ai(
        self, original_sql: str, used_fields: List[str], report_parameters: List[str]
    ) -> Dict[str, Any]:
        """Uses Gemini to rewrite a complex SQL query, pruning unused columns and adding sargable predicates."""
        if not self.is_available():
            return {
                "source": "rule_engine",
                "explanation": "AI optimization unavailable (GEMINI_API_KEY not configured). Used deterministic rule engine.",
                "optimized_query": original_sql,
            }

        prompt = f"""
You are a Database Performance Expert optimizing a SQL query for a Power BI Paginated Report.

Original SQL Query:
```sql
{original_sql}
```

Columns actually used by the report visuals/expressions:
{', '.join(used_fields) if used_fields else 'Not explicitly mapped - preserve required columns'}

Available Report Parameters:
{', '.join(report_parameters) if report_parameters else 'None'}

Tasks:
1. Replace SELECT * with explicit projection of only the used columns.
2. Ensure WHERE clauses are sargable (e.g. convert YEAR(Date)=2026 into Date >= '2026-01-01' AND Date < '2027-01-01').
3. Push available report parameters into WHERE predicates.
4. Output ONLY valid SQL in a fenced ```sql block, followed by 2-3 bullet points of explanation.
"""
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = response.text or ""
            # Extract SQL block
            import re
            sql_match = re.search(r"```sql\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            sql_text = sql_match.group(1).strip() if sql_match else original_sql

            return {
                "source": "gemini-ai",
                "explanation": text,
                "optimized_query": sql_text,
            }
        except Exception as e:
            return {
                "source": "fallback",
                "explanation": f"AI rewrite failed: {e}",
                "optimized_query": original_sql,
            }

    def generate_executive_brief(
        self, report_name: str, health_score: int, metrics: Dict[str, Any], top_issues: List[str]
    ) -> str:
        """Generates a high-level executive summary for client presentation."""
        if not self.is_available():
            issues_text = "\n".join([f"- {iss}" for iss in top_issues])
            return (
                f"### Executive Performance Assessment: {report_name}\n\n"
                f"- **Overall Health Score**: {health_score}/100\n"
                f"- **Total Datasets**: {metrics.get('total_datasets', 0)} ({metrics.get('total_queries', 0)} queries)\n"
                f"- **Critical Issues**: {metrics.get('high_severity_count', 0)} High, {metrics.get('medium_severity_count', 0)} Medium\n\n"
                f"#### Priority Findings:\n{issues_text}\n"
            )

        prompt = f"""
Write an executive performance briefing for a Power BI Paginated Report audit:
Report Name: {report_name}
Performance Health Score: {health_score}/100
Metrics: {metrics}
Top Issues Identified:
{chr(10).join(top_issues)}

Format as a professional 3-paragraph executive summary:
Paragraph 1: Overall health assessment and readiness for production.
Paragraph 2: Primary root causes of latency (data retrieval vs memory vs rendering).
Paragraph 3: Recommended high-ROI fixes with expected user experience improvement.
"""
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            return response.text or "Executive assessment generated."
        except Exception as e:
            return f"Executive summary could not be retrieved from AI: {e}"
