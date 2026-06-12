// Resume Maker - frontend workflow logic.
// Steps: analyze JD -> tailor resume -> review diff / approve keywords -> download PDFs.

const state = {
  jdAnalysis: null,
  tailored: null, // { tailored_resume, diff }
  coverLetter: null, // { paragraphs, company, role }
};

const els = {
  jdText: document.getElementById("jd-text"),
  company: document.getElementById("company"),
  role: document.getElementById("role"),

  btnAnalyze: document.getElementById("btn-analyze"),
  statusAnalyze: document.getElementById("status-analyze"),
  stepAnalysis: document.getElementById("step-analysis"),
  analysisOutput: document.getElementById("analysis-output"),

  btnTailor: document.getElementById("btn-tailor"),
  statusTailor: document.getElementById("status-tailor"),
  stepTailor: document.getElementById("step-tailor"),

  titleLineDiff: document.getElementById("title-line-diff"),
  summaryDiff: document.getElementById("summary-diff"),
  skillsDiff: document.getElementById("skills-diff"),
  competenciesDiff: document.getElementById("competencies-diff"),
  honestyWarnings: document.getElementById("honesty-warnings"),

  btnDownloadResume: document.getElementById("btn-download-resume"),
  btnPreviewCoverLetter: document.getElementById("btn-preview-cover-letter"),
  statusRender: document.getElementById("status-render"),

  stepCoverLetter: document.getElementById("step-cover-letter"),
  coverLetterPreview: document.getElementById("cover-letter-preview"),
  btnCopyCoverLetter: document.getElementById("btn-copy-cover-letter"),
  btnDownloadCoverLetter: document.getElementById("btn-download-cover-letter"),
  statusCoverLetter: document.getElementById("status-cover-letter"),

  stepError: document.getElementById("step-error"),
  errorOutput: document.getElementById("error-output"),
};

function showError(message) {
  els.stepError.classList.remove("hidden");
  els.errorOutput.textContent = message;
  els.stepError.scrollIntoView({ behavior: "smooth", block: "start" });
}

function clearError() {
  els.stepError.classList.add("hidden");
  els.errorOutput.textContent = "";
}

function setStatus(el, text, kind) {
  el.textContent = text;
  el.className = "status" + (kind ? " " + kind : "");
}

async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail;
    try {
      const data = await resp.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      detail = await resp.text();
    }
    throw new Error(`${resp.status} ${resp.statusText}: ${detail}`);
  }
  return resp.json();
}

async function postForFile(url, body, filename) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail;
    try {
      const data = await resp.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      detail = await resp.text();
    }
    throw new Error(`${resp.status} ${resp.statusText}: ${detail}`);
  }
  const blob = await resp.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

function tagList(items) {
  const wrap = document.createElement("div");
  wrap.className = "tag-list";
  for (const item of items) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = item;
    wrap.appendChild(tag);
  }
  return wrap;
}

function renderAnalysis(analysis) {
  els.analysisOutput.innerHTML = "";

  const title = document.createElement("p");
  title.innerHTML = `<strong>Detected job title:</strong> ${analysis.job_title || "(unknown)"}`;
  els.analysisOutput.appendChild(title);

  const sections = [
    ["Hard skills / keywords", analysis.hard_keywords],
    ["Soft skills", analysis.soft_keywords],
    ["Must-haves", analysis.must_haves],
  ];

  for (const [label, items] of sections) {
    if (!items || items.length === 0) continue;
    const heading = document.createElement("p");
    heading.innerHTML = `<strong>${label}:</strong>`;
    heading.style.marginBottom = "0";
    els.analysisOutput.appendChild(heading);
    els.analysisOutput.appendChild(tagList(items));
  }
}

// `onEdit`, if provided, is called with the new text whenever the user edits
// the "Tailored" side. Used to write changes back into state.tailored.tailored_resume
// so the edited text is what gets sent to the PDF renderer.
function renderDiffPair(container, label, original, tailored, onEdit) {
  const pair = document.createElement("div");
  pair.className = "diff-pair";

  const origCol = document.createElement("div");
  origCol.innerHTML = `<div class="label">Original ${label}</div><div class="original">${escapeHtml(original)}</div>`;

  const tailoredCol = document.createElement("div");
  const tailoredLabel = document.createElement("div");
  tailoredLabel.className = "label";
  tailoredLabel.textContent = `Tailored ${label}`;
  tailoredCol.appendChild(tailoredLabel);

  if (onEdit) {
    const textarea = document.createElement("textarea");
    textarea.className = "tailored tailored-edit";
    textarea.value = tailored == null ? "" : String(tailored);
    textarea.rows = Math.max(2, Math.ceil((textarea.value.length || 1) / 60));
    textarea.addEventListener("input", () => {
      onEdit(textarea.value);
      // Auto-grow to fit content.
      textarea.style.height = "auto";
      textarea.style.height = `${textarea.scrollHeight}px`;
    });
    tailoredCol.appendChild(textarea);
  } else {
    const div = document.createElement("div");
    div.className = "tailored";
    div.textContent = tailored == null ? "" : String(tailored);
    tailoredCol.appendChild(div);
  }

  pair.appendChild(origCol);
  pair.appendChild(tailoredCol);
  container.appendChild(pair);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

function renderHonestyWarnings(warnings) {
  if (!warnings || warnings.length === 0) {
    els.honestyWarnings.classList.add("hidden");
    els.honestyWarnings.innerHTML = "";
    return;
  }

  const items = warnings
    .map(
      (w) =>
        `<li><strong>${escapeHtml(w.location)}:</strong> "${escapeHtml(w.tailored_text)}" ` +
        `contains number(s) not found in your master resume: ${escapeHtml(w.suspicious_numbers.join(", "))}</li>`
    )
    .join("");

  els.honestyWarnings.innerHTML = `
    <div class="warning-box">
      <h4>⚠ Honesty check: possible new numbers introduced</h4>
      <ul>${items}</ul>
      <p style="margin: 0.4rem 0 0;">Review these bullets before downloading - the LLM should only reword/reorder, not invent metrics.</p>
    </div>
  `;
  els.honestyWarnings.classList.remove("hidden");
}

// Renders one skills/competencies section. `groups` is the diff list (for
// display) and `targetGroups` is the live array inside
// state.tailored.tailored_resume that gets sent to the PDF renderer - both
// arrays are kept in the same order/length so index `gi` lines up between
// them. Removing a category splices it out of both and re-renders, so
// removed categories (e.g. "Additional Skills"/"Additional Competencies")
// are simply absent from the resume sent on download.
function renderSkillSectionDiff(container, groups, label, targetGroups) {
  container.innerHTML = "";
  if (!targetGroups) return;
  groups.forEach((group, gi) => {
    const wrap = document.createElement("div");
    wrap.className = "diff-group";

    const headerRow = document.createElement("div");
    headerRow.className = "category-row";

    const categoryName = document.createElement("div");
    categoryName.className = "category";
    categoryName.textContent = group.category;
    headerRow.appendChild(categoryName);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn-remove-category";
    removeBtn.textContent = "Remove category";
    removeBtn.title = `Remove "${group.category}" from the resume`;
    removeBtn.addEventListener("click", () => {
      groups.splice(gi, 1);
      targetGroups.splice(gi, 1);
      renderSkillSectionDiff(container, groups, label, targetGroups);
    });
    headerRow.appendChild(removeBtn);

    wrap.appendChild(headerRow);
    renderDiffPair(wrap, label, group.original.join(", "), group.tailored.join(", "), (val) => {
      const items = val.split(",").map((s) => s.trim()).filter((s) => s.length > 0);
      if (targetGroups[gi]) targetGroups[gi].keywords = items;
    });
    container.appendChild(wrap);
  });
}

function renderTailoringDiff(result) {
  const { diff, honesty_warnings } = result;

  renderHonestyWarnings(honesty_warnings);

  const tailoredResume = state.tailored.tailored_resume;

  // Title line
  els.titleLineDiff.innerHTML = "<h3>Title Line</h3>";
  renderDiffPair(els.titleLineDiff, "title", diff.title_line.original, diff.title_line.tailored, (val) => {
    tailoredResume.title_line = val;
  });

  // Professional summary
  els.summaryDiff.innerHTML = "<h3>Professional Summary</h3>";
  renderDiffPair(els.summaryDiff, "summary", diff.summary.original, diff.summary.tailored, (val) => {
    tailoredResume.summary = val;
  });

  // Skills (technical) and Core Competencies (soft) share the same rendering.
  renderSkillSectionDiff(els.skillsDiff, diff.skills, "skills", tailoredResume.skills);
  renderSkillSectionDiff(
    els.competenciesDiff,
    diff.core_competencies || [],
    "competencies",
    tailoredResume.core_competencies
  );

  els.stepTailor.classList.remove("hidden");
  els.stepTailor.scrollIntoView({ behavior: "smooth", block: "start" });
}

// --- Event handlers --------------------------------------------------------

els.btnAnalyze.addEventListener("click", async () => {
  clearError();
  const jdText = els.jdText.value.trim();
  if (!jdText) {
    setStatus(els.statusAnalyze, "Please paste a job description first.", "error");
    return;
  }

  els.btnAnalyze.disabled = true;
  setStatus(els.statusAnalyze, "Analyzing with local LLM... this can take a minute.", "");

  try {
    const analysis = await postJSON("/api/analyze", { jd_text: jdText });
    state.jdAnalysis = analysis;
    renderAnalysis(analysis);

    // Auto-fill company/role from the JD if the user hasn't typed their own.
    if (!els.company.value.trim() && analysis.company_name) {
      els.company.value = analysis.company_name;
    }
    if (!els.role.value.trim() && analysis.job_title) {
      els.role.value = analysis.job_title;
    }

    els.stepAnalysis.classList.remove("hidden");
    els.stepAnalysis.scrollIntoView({ behavior: "smooth", block: "start" });
    setStatus(els.statusAnalyze, "Done.", "success");
  } catch (err) {
    setStatus(els.statusAnalyze, "Failed.", "error");
    showError(err.message);
  } finally {
    els.btnAnalyze.disabled = false;
  }
});

els.btnTailor.addEventListener("click", async () => {
  clearError();
  if (!state.jdAnalysis) return;

  els.btnTailor.disabled = true;
  setStatus(els.statusTailor, "Tailoring resume with local LLM... this can take a minute or two.", "");

  try {
    const result = await postJSON("/api/tailor", { jd_analysis: state.jdAnalysis });
    state.tailored = result;
    renderTailoringDiff(result);
    setStatus(els.statusTailor, "Done.", "success");
  } catch (err) {
    setStatus(els.statusTailor, "Failed.", "error");
    showError(err.message);
  } finally {
    els.btnTailor.disabled = false;
  }
});

els.btnDownloadResume.addEventListener("click", async () => {
  clearError();
  if (!state.tailored) return;

  els.btnDownloadResume.disabled = true;
  setStatus(els.statusRender, "Rendering resume PDF...", "");

  try {
    await postForFile(
      "/api/render/resume",
      {
        resume: state.tailored.tailored_resume,
        company: els.company.value.trim(),
        role: els.role.value.trim(),
        jd_analysis: state.jdAnalysis || {},
      },
      "resume.pdf"
    );
    setStatus(els.statusRender, "Resume PDF downloaded.", "success");
  } catch (err) {
    setStatus(els.statusRender, "Failed.", "error");
    showError(err.message);
  } finally {
    els.btnDownloadResume.disabled = false;
  }
});

function renderCoverLetterPreview(coverLetter) {
  const { paragraphs, company, role } = coverLetter;
  const contact = state.tailored?.tailored_resume?.contact;

  const lines = [];
  if (contact?.name) lines.push(contact.name);
  if (role) {
    lines.push(`Re: Application for ${role}${company ? ` at ${company}` : ""}`);
  }
  lines.push("");
  lines.push("Dear Hiring Manager,");
  lines.push("");
  for (const para of paragraphs) {
    lines.push(para);
    lines.push("");
  }
  lines.push("Sincerely,");
  if (contact?.name) lines.push(contact.name);

  els.coverLetterPreview.textContent = lines.join("\n");
  els.stepCoverLetter.classList.remove("hidden");
  els.stepCoverLetter.scrollIntoView({ behavior: "smooth", block: "start" });
}

els.btnPreviewCoverLetter.addEventListener("click", async () => {
  clearError();
  if (!state.jdAnalysis) return;

  els.btnPreviewCoverLetter.disabled = true;
  setStatus(els.statusRender, "Generating cover letter with local LLM...", "");

  try {
    const coverLetter = await postJSON("/api/cover-letter", {
      jd_analysis: state.jdAnalysis,
      company: els.company.value.trim(),
      role: els.role.value.trim(),
    });
    state.coverLetter = coverLetter;
    renderCoverLetterPreview(coverLetter);
    setStatus(els.statusRender, "Done.", "success");
  } catch (err) {
    setStatus(els.statusRender, "Failed.", "error");
    showError(err.message);
  } finally {
    els.btnPreviewCoverLetter.disabled = false;
  }
});

els.btnCopyCoverLetter.addEventListener("click", async () => {
  clearError();
  try {
    await navigator.clipboard.writeText(els.coverLetterPreview.textContent);
    setStatus(els.statusCoverLetter, "Copied to clipboard.", "success");
  } catch (err) {
    setStatus(els.statusCoverLetter, "Failed to copy.", "error");
    showError(err.message);
  }
});

els.btnDownloadCoverLetter.addEventListener("click", async () => {
  clearError();
  if (!state.jdAnalysis) return;

  els.btnDownloadCoverLetter.disabled = true;
  setStatus(els.statusCoverLetter, "Rendering cover letter PDF...", "");

  try {
    await postForFile(
      "/api/render/cover-letter",
      {
        jd_analysis: state.jdAnalysis,
        company: els.company.value.trim(),
        role: els.role.value.trim(),
        hiring_manager: "",
        paragraphs: state.coverLetter?.paragraphs || [],
      },
      "cover_letter.pdf"
    );
    setStatus(els.statusCoverLetter, "Cover letter PDF downloaded.", "success");
  } catch (err) {
    setStatus(els.statusCoverLetter, "Failed.", "error");
    showError(err.message);
  } finally {
    els.btnDownloadCoverLetter.disabled = false;
  }
});
