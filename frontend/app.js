/**
 * Xebia Paginated Report Performance Analyzer
 * Frontend Application Logic (Vanilla ES6 JavaScript)
 */

(function () {
    "use strict";

    // Application State
    const state = {
        selectedFile: null,
        selectedSampleId: null,
        analysisData: null,
        reportId: null,
        activeTab: "tabIssues",
        filterSeverity: "ALL",
        filterCategory: "ALL"
    };

    // DOM Elements
    const dropzone = document.getElementById("dropzone");
    const rdlFileInput = document.getElementById("rdlFileInput");
    const fileLoadedBanner = document.getElementById("fileLoadedBanner");
    const loadedFileName = document.getElementById("loadedFileName");
    const loadedFileSize = document.getElementById("loadedFileSize");
    const btnRemoveFile = document.getElementById("btnRemoveFile");

    const btnAnalyze = document.getElementById("btnAnalyze");
    const analyzeSpinner = document.getElementById("analyzeSpinner");
    const analyzeBtnText = document.getElementById("analyzeBtnText");
    const aiToggle = document.getElementById("aiToggle");

    const diagnosticTag = document.getElementById("diagnosticTag");
    const diagPlaceholder = document.getElementById("diagPlaceholder");
    const diagActiveBox = document.getElementById("diagActiveBox");
    const previewScoreText = document.getElementById("previewScoreText");
    const previewStatusText = document.getElementById("previewStatusText");
    const previewDatasetSelect = document.getElementById("previewDatasetSelect");
    const previewSqlCode = document.getElementById("previewSqlCode");

    const resultsSection = document.getElementById("resultsSection");
    const resultsTitle = document.getElementById("resultsTitle");
    const kpiScore = document.getElementById("kpiScore");
    const kpiStatus = document.getElementById("kpiStatus");
    const kpiHighCount = document.getElementById("kpiHighCount");
    const kpiMedCount = document.getElementById("kpiMedCount");
    const kpiDatasetCount = document.getElementById("kpiDatasetCount");
    const kpiDatasetLabel = document.getElementById("kpiDatasetLabel");
    const kpiUnusedCols = document.getElementById("kpiUnusedCols");

    const forecastOrigTime = document.getElementById("forecastOrigTime");
    const forecastOptTime = document.getElementById("forecastOptTime");
    const forecastSpeedup = document.getElementById("forecastSpeedup");
    const barRetrieval = document.getElementById("barRetrieval");
    const barInmemory = document.getElementById("barInmemory");
    const barRender = document.getElementById("barRender");
    const pctRetrievalText = document.getElementById("pctRetrievalText");
    const pctInmemoryText = document.getElementById("pctInmemoryText");
    const pctRenderText = document.getElementById("pctRenderText");
    const forecastPayloadText = document.getElementById("forecastPayloadText");
    const forecastPayloadImpact = document.getElementById("forecastPayloadImpact");
    const quickWinsList = document.getElementById("quickWinsList");

    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabPanels = document.querySelectorAll(".tab-content-panel");
    const tabBtnIssues = document.getElementById("tabBtnIssues");
    const issuesContainer = document.getElementById("issuesContainer");
    const filterSeverity = document.getElementById("filterSeverity");
    const filterCategory = document.getElementById("filterCategory");
    const issuesShowingCount = document.getElementById("issuesShowingCount");

    const diffDatasetSelect = document.getElementById("diffDatasetSelect");
    const diffOriginalSql = document.getElementById("diffOriginalSql");
    const diffSuggestedSql = document.getElementById("diffSuggestedSql");
    const diffPrunedWarning = document.getElementById("diffPrunedWarning");
    const diffReasonsList = document.getElementById("diffReasonsList");

    const matrixTableBody = document.getElementById("matrixTableBody");

    const btnDownloadHtml = document.getElementById("btnDownloadHtml");
    const btnDownloadExcel = document.getElementById("btnDownloadExcel");

    const btnHowItWorks = document.getElementById("btnHowItWorks");
    const modalHowItWorks = document.getElementById("modalHowItWorks");
    const modalCloseBtn = document.getElementById("modalCloseBtn");

    const modalAiAdvisor = document.getElementById("modalAiAdvisor");
    const modalAiCloseBtn = document.getElementById("modalAiCloseBtn");
    const modalAiIssueTitle = document.getElementById("modalAiIssueTitle");
    const modalAiContent = document.getElementById("modalAiContent");

    const toast = document.getElementById("toast");

    // ==========================================
    // Helper Functions
    // ==========================================
    function formatBytes(bytes) {
        if (!bytes || bytes === 0) return "0 B";
        const k = 1024;
        const sizes = ["B", "KB", "MB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
    }

    function generateReportId() {
        const d = new Date();
        const ymd = d.toISOString().slice(0,10).replace(/-/g, '');
        const rnd = Math.random().toString(16).substring(2, 8).toUpperCase();
        return `RPT-${ymd}-${rnd}`;
    }

    function showToast(msg) {
        toast.innerText = msg;
        toast.style.display = "block";
        setTimeout(() => {
            toast.style.display = "none";
        }, 2200);
    }

    window.copyTextFromElement = function (elemId) {
        const el = document.getElementById(elemId);
        if (!el) return;
        const text = el.innerText || el.textContent;
        navigator.clipboard.writeText(text).then(() => {
            showToast("SQL query copied to clipboard!");
        }).catch(err => {
            showToast("Failed to copy: " + err);
        });
    };

    function resetAnalysisState() {
        state.analysisData = null;
        state.reportId = null;
        if (resultsSection) resultsSection.style.display = "none";
        if (diagActiveBox) diagActiveBox.style.display = "none";
        if (diagPlaceholder) diagPlaceholder.style.display = "block";
        if (diagnosticTag) {
            diagnosticTag.className = "panel-tag tag-neutral";
            diagnosticTag.innerText = "READY TO ANALYZE";
        }
    }

    // ==========================================
    // File Upload & Preset Selection
    // ==========================================
    dropzone.addEventListener("click", () => {
        rdlFileInput.value = "";
        rdlFileInput.click();
    });

    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("drag-over");
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.classList.remove("drag-over");
    });

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("drag-over");
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            handleFileSelected(e.dataTransfer.files[0]);
        }
    });

    rdlFileInput.addEventListener("change", (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleFileSelected(e.target.files[0]);
        }
    });

    function handleFileSelected(file) {
        if (!file.name.toLowerCase().endsWith(".rdl") && !file.name.toLowerCase().endsWith(".xml")) {
            alert("Please select a valid Power BI Paginated Report (.rdl or .xml) file.");
            return;
        }
        state.selectedFile = file;
        state.selectedSampleId = null;

        loadedFileName.innerText = file.name;
        loadedFileSize.innerText = `(${formatBytes(file.size)})`;
        fileLoadedBanner.style.display = "flex";

        resetAnalysisState();
    }

    btnRemoveFile.addEventListener("click", () => {
        state.selectedFile = null;
        state.selectedSampleId = null;
        rdlFileInput.value = "";
        fileLoadedBanner.style.display = "none";
        resetAnalysisState();
    });

    // ==========================================
    // Analyze Action Execution
    // ==========================================
    btnAnalyze.addEventListener("click", async () => {
        if (!state.selectedFile) {
            alert("Please upload an .rdl report file first.");
            return;
        }

        // Show loading state
        btnAnalyze.disabled = true;
        analyzeSpinner.style.display = "inline-block";
        analyzeBtnText.innerText = "Analyzing Report...";

        try {
            const formData = new FormData();
            formData.append("file", state.selectedFile);
            const res = await fetch("/api/analyze", {
                method: "POST",
                body: formData
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || `Analysis request failed with HTTP ${res.status}`);
            }

            const data = await res.json();
            state.analysisData = data;
            state.reportId = generateReportId();

            renderDiagnosticResults(data);
        } catch (err) {
            console.error("Analysis error:", err);
            alert("Error analyzing report: " + err.message);
        } finally {
            btnAnalyze.disabled = false;
            analyzeSpinner.style.display = "none";
            analyzeBtnText.innerText = "✦ Analyze Report →";
        }
    });

    // ==========================================
    // Render Results & Diagnostics
    // ==========================================
    function renderDiagnosticResults(data) {
        // 1. Update Workspace Preview Panel
        diagPlaceholder.style.display = "none";
        diagActiveBox.style.display = "block";
        diagnosticTag.className = "panel-tag tag-green";
        diagnosticTag.innerText = "ANALYSIS COMPLETE";

        const score = data.health_score;
        previewScoreText.innerText = `${score} / 100`;
        previewScoreText.style.color = score >= 80 ? "#16A34A" : (score >= 60 ? "#D97706" : "#DC2626");
        previewStatusText.innerText = data.health_status;

        // Populate Preview Dataset Dropdown with all report datasets
        const opts = data.dataset_optimizations || {};
        const inventory = data.dataset_inventory || [];
        previewDatasetSelect.innerHTML = "";

        // Build list of datasets from inventory (or fallback to opts / field_usage_matrix)
        let dsList = [];
        if (inventory.length > 0) {
            dsList = inventory;
        } else if (Object.keys(opts).length > 0) {
            dsList = Object.keys(opts).map(k => ({
                name: k,
                query_type: opts[k].query_type || "SQL",
                is_orphan: false,
                query_text: opts[k].original_query || ""
            }));
        } else if (data.field_usage_matrix) {
            dsList = Object.keys(data.field_usage_matrix).map(k => ({
                name: k,
                query_type: "Unknown",
                is_orphan: false,
                query_text: ""
            }));
        }

        if (dsList.length > 0) {
            dsList.forEach(ds => {
                const opt = document.createElement("option");
                opt.value = ds.name;
                const orphanTag = ds.is_orphan ? " (Orphan Candidate)" : "";
                const typeTag = (ds.query_type && ds.query_type !== "SQL" && !ds.is_orphan) ? ` (${ds.query_type})` : "";
                opt.innerText = `${ds.name}${orphanTag}${typeTag}`;
                previewDatasetSelect.appendChild(opt);
            });

            function updatePreviewCode(dsName) {
                const curOpt = opts[dsName];
                const curInv = dsList.find(d => d.name === dsName);

                if (curOpt && curOpt.suggested_query) {
                    previewSqlCode.innerText = curOpt.suggested_query;
                    previewSqlCode.className = (curOpt.validation_status === "Requires manual validation")
                        ? "code-box suggested candidate"
                        : "code-box suggested";
                } else if (curInv && curInv.is_orphan) {
                    previewSqlCode.className = "code-box";
                    previewSqlCode.innerText =
`-- ⚠️ ORPHAN CANDIDATE: '${dsName}'
-- Status: 0 visual references, 0 parameter bindings, 0 expression references.
-- Recommended Action: Remove this dataset from report definition to eliminate
-- redundant query execution and connection overhead during report load.
-- Original Query:
${curInv.query_text || "-- (No query text defined)"}`;
                } else if (curInv && curInv.query_type && curInv.query_type !== "SQL") {
                    previewSqlCode.className = "code-box";
                    previewSqlCode.innerText =
`-- DATASET: '${dsName}' (${curInv.query_type})
-- Dependency: ${curInv.dependency_type || "Embedded"} · ${curInv.fields_retrieved_count || 0} fields defined.
-- Status: Static embedded data payload. SQL query rewrites are not applicable.`;
                } else {
                    previewSqlCode.className = "code-box";
                    previewSqlCode.innerText = (curInv && curInv.query_text)
                        ? `-- Query in '${dsName}' follows standard projection and filter best practices.\n${curInv.query_text}`
                        : "-- No SQL query rewrites applicable";
                }
            }

            // Prefer selecting the first optimized SQL dataset if available, else first item
            const firstOptimized = dsList.find(d => opts[d.name]);
            const defaultDs = firstOptimized ? firstOptimized.name : dsList[0].name;
            previewDatasetSelect.value = defaultDs;
            updatePreviewCode(defaultDs);

            previewDatasetSelect.onchange = () => {
                updatePreviewCode(previewDatasetSelect.value);
            };
        } else {
            const opt = document.createElement("option");
            opt.disabled = true;
            opt.selected = true;
            opt.innerText = "No datasets detected";
            previewDatasetSelect.appendChild(opt);
            previewSqlCode.innerText = "-- No datasets detected in report definition";
        }

        // 2. Reveal 02 / DIAGNOSTIC RESULTS
        resultsSection.style.display = "block";
        resultsTitle.innerText = `Performance Findings: ${data.report_name}`;

        // 3. KPI Cards
        kpiScore.innerText = `${score}/100`;
        kpiScore.style.color = score >= 80 ? "#16A34A" : (score >= 60 ? "#D97706" : "#DC2626");
        kpiStatus.innerText = data.health_status;
        kpiStatus.className = `kpi-status-badge ${score >= 80 ? 'badge-low' : (score >= 60 ? 'badge-medium' : 'badge-critical')}`;

        const m = data.summary_metrics || {};
        kpiHighCount.innerText = m.high_severity_count || 0;
        kpiMedCount.innerText = m.medium_severity_count || 0;
        kpiDatasetCount.innerText = m.total_datasets || 0;
        const sqlCount = m.total_sql_queries !== undefined ? m.total_sql_queries : (m.total_queries || 0);
        kpiDatasetLabel.innerText = `Datasets (${sqlCount} SQL)`;
        kpiUnusedCols.innerText = m.unused_fields_count || 0;

        const kpiScoreFormula = document.getElementById("kpiScoreFormula");
        if (kpiScoreFormula && m.score_breakdown && m.score_breakdown.formula) {
            kpiScoreFormula.innerText = m.score_breakdown.formula;
        } else if (kpiScoreFormula) {
            kpiScoreFormula.innerText = "Calculated from detected issue severity";
        }

        // 4. Executive Performance Forecast Banner
        renderForecastBanner(data, m);

        // 5. Render Issues (Tab 1)
        renderIssuesTab(data.issues || []);

        // 6. Render SQL Diff (Tab 2)
        renderSqlDiffTab(opts, data.dataset_inventory || []);

        // 7. Render Field Utilization Matrix (Tab 3)
        renderMatrixTab(data.field_usage_matrix || {});

        // Smooth scroll to results
        resultsSection.scrollIntoView({ behavior: "smooth" });
    }

    function renderForecastBanner(data, m) {
        const highCount = m.high_severity_count || 0;
        const medCount = m.medium_severity_count || 0;
        const unusedCols = m.unused_fields_count || 0;
        const totalQueries = m.total_queries || 0;

        let pctRet = 35, pctInm = 35, pctRen = 30;

        if (highCount > 0) {
            const totalSec = Math.max(1, highCount * 50 + medCount * 15);
            const mins = Math.floor(totalSec / 60);
            const secs = totalSec % 60;
            forecastOrigTime.innerText = mins > 0 ? `~${mins}m ${secs}s` : `~${secs}s`;
            forecastOptTime.innerText = "~6–10s";
            forecastSpeedup.innerText = "Est. 92–95% latency reduction";
            pctRet = 74; pctInm = 19; pctRen = 7;
        } else if (medCount > 0) {
            forecastOrigTime.innerText = "~25–35s";
            forecastOptTime.innerText = "~4–7s";
            forecastSpeedup.innerText = "Est. 75–80% latency reduction";
            pctRet = 55; pctInm = 30; pctRen = 15;
        } else {
            forecastOrigTime.innerText = "~2–4s";
            forecastOptTime.innerText = "< 1s";
            forecastSpeedup.innerText = "Optimized report design";
        }

        barRetrieval.style.width = `${pctRet}%`;
        barInmemory.style.width = `${pctInm}%`;
        barRender.style.width = `${pctRen}%`;
        pctRetrievalText.innerText = `${pctRet}%`;
        pctInmemoryText.innerText = `${pctInm}%`;
        pctRenderText.innerText = `${pctRen}%`;

        if (unusedCols > 0) {
            const sqlCount = m.total_sql_queries !== undefined ? m.total_sql_queries : (m.total_queries || 0);
            const totalDs = m.total_datasets || totalQueries;
            const dsLabel = sqlCount > 0 ? (sqlCount === 1 ? "1 SQL query" : `${sqlCount} SQL queries`) : (totalDs === 1 ? "1 dataset" : `${totalDs} datasets`);
            forecastPayloadText.innerText = `${unusedCols} redundant columns across ${dsLabel}`;
            forecastPayloadImpact.innerText = "Est. 60–75% network payload cut";
        } else {
            forecastPayloadText.innerText = "All projected columns utilized in visuals";
            forecastPayloadImpact.innerText = "Zero payload bloat";
        }

        // Quick Wins List
        quickWinsList.innerHTML = "";
        const quickWins = [];
        (data.issues || []).forEach(iss => {
            if (iss.severity === "High" && quickWins.length < 3) {
                quickWins.push(`<strong>${iss.target_object}</strong>: ${iss.title} — ${iss.remediation}`);
            }
        });
        if (quickWins.length < 3) {
            (data.issues || []).forEach(iss => {
                if (iss.severity === "Medium" && quickWins.length < 3) {
                    quickWins.push(`<strong>${iss.target_object}</strong>: ${iss.title} — ${iss.remediation}`);
                }
            });
        }
        if (quickWins.length === 0) {
            quickWins.push("Report definition follows SSRS enterprise performance best practices.");
        }

        quickWins.forEach(qw => {
            const li = document.createElement("li");
            li.className = "quick-win-item";
            li.innerHTML = `<span style="color:#DC2626;">•</span> <span>${qw}</span>`;
            quickWinsList.appendChild(li);
        });
    }

    // ==========================================
    // Tab 1: Issues Rendering & Filtering
    // ==========================================
    function renderIssuesTab(issues) {
        tabBtnIssues.innerText = `🔍 Detected Issues (${issues.length})`;
        populateCategoryFilter(issues);
        filterAndRenderIssues(issues);

        filterSeverity.onchange = () => {
            state.filterSeverity = filterSeverity.value;
            filterAndRenderIssues(issues);
        };

        filterCategory.onchange = () => {
            state.filterCategory = filterCategory.value;
            filterAndRenderIssues(issues);
        };
    }

    function populateCategoryFilter(issues) {
        const cats = new Set(issues.map(i => i.category));
        filterCategory.innerHTML = '<option value="ALL">All Categories</option>';
        cats.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c;
            opt.innerText = c;
            filterCategory.appendChild(opt);
        });
    }

    function filterAndRenderIssues(issues) {
        const filtered = issues.filter(i => {
            const matchSev = state.filterSeverity === "ALL" || i.severity === state.filterSeverity;
            const matchCat = state.filterCategory === "ALL" || i.category === state.filterCategory;
            return matchSev && matchCat;
        });

        issuesShowingCount.innerText = `Showing ${filtered.length} of ${issues.length} diagnostic findings`;
        issuesContainer.innerHTML = "";

        if (filtered.length === 0) {
            issuesContainer.innerHTML = `
                <div style="background:var(--white); border:1px solid var(--gray-200); border-radius:8px; padding:30px; text-align:center; color:var(--gray-500);">
                    No findings match the selected filters.
                </div>
            `;
            return;
        }

        filtered.forEach((iss, idx) => {
            const card = document.createElement("div");
            card.className = `issue-card-container ${iss.severity === "High" && idx < 3 ? "open" : ""}`;

            const sevClass = iss.severity === "Critical" ? "badge-critical" :
                             (iss.severity === "High" ? "badge-high" :
                             (iss.severity === "Medium" ? "badge-medium" : "badge-low"));

            card.innerHTML = `
                <div class="issue-card-header">
                    <div class="issue-card-header-left">
                        <span class="badge ${sevClass}">${iss.severity.toUpperCase()}</span>
                        <span class="issue-title">${iss.title}</span>
                        <span class="pill-meta">${iss.target_object}</span>
                        <span class="pill-meta">${iss.category}</span>
                        <span class="pill-meta" style="background:#FDF2F8; color:#9D174D;">${iss.classification}</span>
                    </div>
                    <button type="button" class="issue-toggle-btn">Toggle Details ▼</button>
                </div>
                <div class="issue-card-body">
                    <div class="issue-body-grid">
                        <div>
                            <div class="issue-field-label">Description</div>
                            <div style="color:var(--dark-800);">${iss.description}</div>
                            <div class="issue-field-label" style="margin-top:8px;">Engine Impact</div>
                            <div style="color:var(--sev-critical-text);">${iss.impact}</div>
                        </div>
                        <div>
                            <div class="issue-field-label">Recommended Remediation</div>
                            <div style="color:#166534; font-weight:500;">${iss.remediation}</div>
                        </div>
                    </div>

                    ${(iss.code_snippet || iss.suggested_fix) ? `
                        <div style="display:grid; grid-template-columns:${iss.code_snippet && iss.suggested_fix ? '1fr 1fr' : '1fr'}; gap:10px; margin-top:8px;">
                            ${iss.code_snippet ? `
                                <div>
                                    <div class="issue-field-label">Identified Code / Expression:</div>
                                    <div class="code-box">${escapeHtml(iss.code_snippet)}</div>
                                </div>
                            ` : ''}
                            ${iss.suggested_fix ? `
                                <div>
                                    <div class="issue-field-label" style="color:#166534;">Suggested Replacement:</div>
                                    <div class="code-box suggested">${escapeHtml(iss.suggested_fix)}</div>
                                </div>
                            ` : ''}
                        </div>
                    ` : ''}
                </div>
            `;

            // Toggle Accordion Click
            card.querySelector(".issue-card-header").addEventListener("click", () => {
                card.classList.toggle("open");
            });

            issuesContainer.appendChild(card);
        });
    }

    function escapeHtml(text) {
        if (!text) return "";
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function formatMarkdown(md) {
        if (!md) return "";
        // If content is already HTML with tags
        if (md.trim().startsWith("<p>") || md.trim().startsWith("<div>")) {
            return md;
        }
        let html = escapeHtml(md);
        // Bold: **text**
        html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
        // Inline code: `code`
        html = html.replace(/`([^`]+)`/g, "<code style='background:#F1F5F9; padding:2px 5px; border-radius:4px; font-size:12px;'>$1</code>");
        // Bullet lines: - item or * item
        html = html.replace(/^[-•*]\s+(.*)$/gm, "<div style='margin-left: 12px; margin-bottom: 4px; display:flex; gap:6px;'><span style='color:#6C2BD9;'>•</span><span>$1</span></div>");
        // Numbered lists: 1. item
        html = html.replace(/^(\d+)\.\s+(.*)$/gm, "<div style='margin-left: 12px; margin-bottom: 4px; display:flex; gap:6px;'><strong style='color:#6C2BD9;'>$1.</strong><span>$2</span></div>");
        // Paragraphs
        html = html.replace(/\n\n+/g, "</p><p style='margin-top: 8px;'>");
        return `<p>${html}</p>`;
    }

    // ==========================================
    // Tab 2: Side-by-Side SQL Diff
    // ==========================================
    function renderSqlDiffTab(opts, inventory) {
        inventory = inventory || [];
        diffDatasetSelect.innerHTML = "";
        const diffEmptyNotice = document.getElementById("diffEmptyNotice");
        const diffNonSqlNotice = document.getElementById("diffNonSqlNotice");
        const diffContentContainer = document.getElementById("diffContentContainer");
        const diffSelectorRow = document.getElementById("diffSelectorRow");
        const diffDetectedIssuesBox = document.getElementById("diffDetectedIssuesBox");
        const diffDetectedIssuesList = document.getElementById("diffDetectedIssuesList");
        const diffExplanationBox = document.getElementById("diffExplanationBox");
        const diffImprovementsBox = document.getElementById("diffImprovementsBox");
        const diffImprovementsList = document.getElementById("diffImprovementsList");

        // Identify all SQL datasets in inventory (or fallback to opts)
        let sqlDatasets = [];
        if (inventory.length > 0) {
            sqlDatasets = inventory.filter(d => (d.query_type || "SQL") === "SQL");
        } else {
            sqlDatasets = Object.keys(opts)
                .filter(k => (opts[k].query_type || "SQL") === "SQL")
                .map(k => ({ name: k, query_type: "SQL", is_orphan: false, query_text: opts[k].original_query || "" }));
        }

        if (sqlDatasets.length === 0) {
            // Requirement 7: Exact message
            if (diffEmptyNotice) {
                diffEmptyNotice.style.display = "block";
                diffEmptyNotice.innerText = "No SQL datasets were detected in this report. SQL comparison is not applicable.";
            }
            if (diffContentContainer) diffContentContainer.style.display = "none";
            if (diffSelectorRow) diffSelectorRow.style.display = "none";
            if (diffNonSqlNotice) diffNonSqlNotice.style.display = "none";
            return;
        }

        if (diffEmptyNotice) diffEmptyNotice.style.display = "none";
        if (diffContentContainer) diffContentContainer.style.display = "grid";
        if (diffSelectorRow) diffSelectorRow.style.display = "flex";
        if (diffNonSqlNotice) diffNonSqlNotice.style.display = "none";

        sqlDatasets.forEach(ds => {
            const option = document.createElement("option");
            option.value = ds.name;
            option.innerText = ds.is_orphan ? `${ds.name} (Orphan Candidate)` : ds.name;
            diffDatasetSelect.appendChild(option);
        });

        function updateDiffView(dsName) {
            const opt = opts[dsName];
            const inv = sqlDatasets.find(d => d.name === dsName);

            if (diffNonSqlNotice) diffNonSqlNotice.style.display = "none";

            if (opt) {
                // Active SQL dataset with optimization proposal
                diffOriginalSql.innerText = opt.original_query || "";
                diffSuggestedSql.innerText = opt.suggested_query || "";

                if (opt.fields_pruned && opt.fields_pruned.length > 0) {
                    diffPrunedWarning.style.display = "block";
                    diffPrunedWarning.innerText = `⚠️ Unused columns fetched: ${opt.fields_pruned.join(', ')}`;
                } else {
                    diffPrunedWarning.style.display = "none";
                }

                const detected = opt.detected_issues || [];
                if (diffDetectedIssuesBox && diffDetectedIssuesList) {
                    if (detected.length > 0) {
                        diffDetectedIssuesBox.style.display = "block";
                        diffDetectedIssuesList.innerHTML = detected.map(i => `<li>${escapeHtml(i)}</li>`).join("");
                    } else {
                        diffDetectedIssuesBox.style.display = "none";
                        diffDetectedIssuesList.innerHTML = "";
                    }
                }

                const reasons = opt.optimization_reasons || [];
                if (diffExplanationBox && diffReasonsList) {
                    if (reasons.length > 0) {
                        diffExplanationBox.style.display = "block";
                        diffReasonsList.innerHTML = `<ul style="margin: 0 0 0 16px; padding: 0;">${reasons.map(r => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`;
                    } else {
                        diffExplanationBox.style.display = "none";
                        diffReasonsList.innerHTML = "";
                    }
                }

                const improvements = opt.suggested_improvements || [];
                if (diffImprovementsBox && diffImprovementsList) {
                    if (improvements.length > 0) {
                        diffImprovementsBox.style.display = "block";
                        diffImprovementsList.innerHTML = improvements.map(imp => `<li>${escapeHtml(imp)}</li>`).join("");
                    } else {
                        diffImprovementsBox.style.display = "none";
                        diffImprovementsList.innerHTML = "";
                    }
                }
            } else if (inv && inv.is_orphan) {
                // Orphan dataset - recommend removal
                diffOriginalSql.innerText = inv.query_text || "-- (No query text defined)";
                diffSuggestedSql.innerText = 
`-- ⚠️ ORPHAN DATASET: RECOMMEND REMOVAL
-- Status: 0 visual references, 0 parameter bindings, 0 expression references.
-- Recommendation: Remove this dataset from report definition rather than optimizing the query.
-- Removing this dataset eliminates unnecessary database queries and connection overhead on report load.`;

                if (diffPrunedWarning) {
                    diffPrunedWarning.style.display = "block";
                    diffPrunedWarning.innerText = "⚠️ Orphan Dataset: 0 visual references. Recommended for removal.";
                }

                if (diffDetectedIssuesBox && diffDetectedIssuesList) {
                    diffDetectedIssuesBox.style.display = "block";
                    diffDetectedIssuesList.innerHTML = `<li>Unused / Orphan Dataset '${escapeHtml(dsName)}' (0 visual references)</li><li>Redundant database query executed during report initialization</li>`;
                }

                if (diffExplanationBox && diffReasonsList) {
                    diffExplanationBox.style.display = "block";
                    diffReasonsList.innerHTML = `<ul style="margin: 0 0 0 16px; padding: 0;"><li>Scoped dependency analysis confirmed zero references across all report visual elements, groups, and expressions.</li><li>SQL query tuning is suppressed because removing the unneeded dataset is the optimal performance fix.</li></ul>`;
                }

                if (diffImprovementsBox && diffImprovementsList) {
                    diffImprovementsBox.style.display = "block";
                    diffImprovementsList.innerHTML = `<li>Validate dependencies in report visuals and remove dataset from report definition.</li><li>If this query was intended for future report visuals, explicitly project only required columns.</li>`;
                }
            } else {
                // Other SQL dataset without detected issues
                diffOriginalSql.innerText = (inv && inv.query_text) ? inv.query_text : "";
                diffSuggestedSql.innerText = (inv && inv.query_text) ? `-- Query in '${dsName}' follows standard projection and filter best practices.\n${inv.query_text}` : "";
                if (diffPrunedWarning) diffPrunedWarning.style.display = "none";
                if (diffDetectedIssuesBox) diffDetectedIssuesBox.style.display = "none";
                if (diffExplanationBox) diffExplanationBox.style.display = "none";
                if (diffImprovementsBox) diffImprovementsBox.style.display = "none";
            }
        }

        diffDatasetSelect.onchange = () => updateDiffView(diffDatasetSelect.value);
        // Default to first optimized dataset if available, otherwise first SQL dataset
        const firstOptDs = sqlDatasets.find(d => opts[d.name]);
        const defaultDiffDs = firstOptDs ? firstOptDs.name : sqlDatasets[0].name;
        diffDatasetSelect.value = defaultDiffDs;
        updateDiffView(defaultDiffDs);
    }

    // ==========================================
    // Tab 3: Field Utilization Matrix
    // ==========================================
    function renderMatrixTab(matrix) {
        matrixTableBody.innerHTML = "";
        const dsNames = Object.keys(matrix);

        if (dsNames.length === 0) {
            matrixTableBody.innerHTML = "<tr><td colspan='7' style='text-align:center;'>No dataset fields found.</td></tr>";
            return;
        }

        dsNames.forEach(name => {
            const info = matrix[name];
            const total = info.total_fields || 0;
            const used = info.used_count || 0;
            const unused = info.unused_count || 0;
            const rate = total > 0 ? `${Math.round((used / total) * 100)}%` : "N/A";

            let riskHtml = '<span class="badge badge-low">Optimal (100% Used)</span>';
            if (total > 0) {
                const pctUnused = unused / total;
                if (pctUnused > 0.7) {
                    riskHtml = '<span class="badge badge-critical">High Risk (>70%)</span>';
                } else if (pctUnused > 0.4) {
                    riskHtml = '<span class="badge badge-high">Medium Risk (40–70%)</span>';
                } else if (pctUnused > 0) {
                    riskHtml = '<span class="badge badge-medium">Low Risk (<40%)</span>';
                }
            }

            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${name}</strong></td>
                <td>${total}</td>
                <td><span style="color:#047857; font-weight:700;">${used}</span></td>
                <td><span style="color:${unused > 0 ? '#C2410C' : '#6B7280'}; font-weight:700;">${unused}</span></td>
                <td><strong>${rate}</strong></td>
                <td>${riskHtml}</td>
                <td style="max-width:280px; font-size:11.5px; color:var(--gray-600);">${(info.unused_fields && info.unused_fields.length > 0) ? info.unused_fields.join(', ') : 'None (Fully utilized)'}</td>
            `;
            matrixTableBody.appendChild(tr);
        });
    }

    // ==========================================
    // Tab Switching
    // ==========================================
    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.getAttribute("data-tab");
            tabBtns.forEach(b => b.classList.remove("active"));
            tabPanels.forEach(p => p.classList.remove("active"));

            btn.classList.add("active");
            document.getElementById(targetTab).classList.add("active");
        });
    });

    // ==========================================
    // Downloads Handlers
    // ==========================================
    btnDownloadHtml.addEventListener("click", async () => {
        if (!state.analysisData) {
            alert("Please click 'Analyze Report' to run diagnostic analysis first.");
            return;
        }
        showToast("Generating self-contained HTML report...");
        try {
            const res = await fetch("/api/export-html", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(state.analysisData)
            });
            if (!res.ok) throw new Error("Failed to export HTML");
            const blob = await res.blob();
            downloadBlob(blob, `Paginated_Report_Performance_Analysis_${state.reportId || 'Export'}.html`);
        } catch (e) {
            alert("HTML Download error: " + e.message);
        }
    });

    btnDownloadExcel.addEventListener("click", async () => {
        if (!state.analysisData) {
            alert("Please click 'Analyze Report' to run diagnostic analysis first.");
            return;
        }
        showToast("Generating formatted Excel workbook...");
        try {
            const res = await fetch("/api/export", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(state.analysisData)
            });
            if (!res.ok) throw new Error("Failed to export Excel");
            const blob = await res.blob();
            downloadBlob(blob, `Xebia_Diagnostic_${state.analysisData.report_name}.xlsx`);
        } catch (e) {
            alert("Excel Download error: " + e.message);
        }
    });

    function downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    // ==========================================
    // Modals
    // ==========================================
    btnHowItWorks.addEventListener("click", () => {
        modalHowItWorks.style.display = "flex";
    });

    modalCloseBtn.addEventListener("click", () => {
        modalHowItWorks.style.display = "none";
    });

    modalHowItWorks.addEventListener("click", (e) => {
        if (e.target === modalHowItWorks) {
            modalHowItWorks.style.display = "none";
        }
    });

})();
