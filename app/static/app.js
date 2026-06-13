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

  stepGap: document.getElementById("step-gap"),
  gapReport: document.getElementById("gap-report"),

  stepReview: document.getElementById("step-review"),
  stepPlaceholder: document.getElementById("step-placeholder"),
  reviewTabs: document.getElementById("review-tabs"),
  tabResume: document.getElementById("tab-resume"),
  tabCoverLetter: document.getElementById("tab-cover-letter"),

  resumeSubtabs: document.getElementById("resume-subtabs"),

  titleLineDiff: document.getElementById("title-line-diff"),
  summaryDiff: document.getElementById("summary-diff"),
  skillsDiff: document.getElementById("skills-diff"),
  suggestedSkills: document.getElementById("suggested-skills"),
  competenciesDiff: document.getElementById("competencies-diff"),
  experienceDiff: document.getElementById("experience-diff"),
  projectsDiff: document.getElementById("projects-diff"),
  certificationsList: document.getElementById("certifications-list"),
  awardsList: document.getElementById("awards-list"),
  honestyWarnings: document.getElementById("honesty-warnings"),

  btnDownloadResume: document.getElementById("btn-download-resume"),
  statusRender: document.getElementById("status-render"),

  clSubject: document.getElementById("cl-subject"),
  clBody: document.getElementById("cl-body"),
  btnRegenerateCoverLetter: document.getElementById("btn-regenerate-cover-letter"),
  btnCopyCoverLetter: document.getElementById("btn-copy-cover-letter"),
  btnDownloadCoverLetter: document.getElementById("btn-download-cover-letter"),
  statusCoverLetter: document.getElementById("status-cover-letter"),

  stepError: document.getElementById("step-error"),
  errorOutput: document.getElementById("error-output"),

  categorizeModal: document.getElementById("categorize-modal"),
  categorizeList: document.getElementById("categorize-list"),
  btnCategorizeSubmit: document.getElementById("btn-categorize-submit"),
  statusCategorize: document.getElementById("status-categorize"),
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

// Renders the gap/match report: how well the candidate's real background
// supports each JD requirement (strong/partial/missing) plus actionable
// suggestions. Hidden if there's nothing to show.
function renderGapReport(report) {
  if (!report || (!report.requirements?.length && !report.suggestions?.length)) {
    els.stepGap.classList.add("hidden");
    els.gapReport.innerHTML = "";
    return;
  }

  const order = { strong: 0, partial: 1, missing: 2 };
  const reqs = [...(report.requirements || [])].sort(
    (a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3)
  );

  const counts = { strong: 0, partial: 0, missing: 0 };
  for (const r of reqs) if (r.status in counts) counts[r.status]++;

  const rows = reqs
    .map((r) => {
      const evidence = r.evidence
        ? `<span class="gap-evidence">${escapeHtml(r.evidence)}</span>`
        : "";
      return (
        `<li class="gap-item gap-${escapeHtml(r.status)}">` +
        `<span class="gap-status">${escapeHtml(r.status)}</span>` +
        `<span class="gap-req">${escapeHtml(r.requirement)}</span>${evidence}</li>`
      );
    })
    .join("");

  const suggestions = (report.suggestions || []).length
    ? `<div class="gap-suggestions"><h4>Suggestions</h4><ul>${report.suggestions
        .map((s) => `<li>${escapeHtml(s)}</li>`)
        .join("")}</ul></div>`
    : "";

  els.gapReport.innerHTML = `
    <p class="hint" style="margin-top:0;">How well your real experience fits this job.</p>
    <p class="gap-summary">
      <span class="gap-pill gap-strong">${counts.strong} strong</span>
      <span class="gap-pill gap-partial">${counts.partial} partial</span>
      <span class="gap-pill gap-missing">${counts.missing} missing</span>
    </p>
    <ul class="gap-list">${rows}</ul>
    ${suggestions}
  `;
  els.stepGap.classList.remove("hidden");
}

// Renders the "crucial skills you may have" opt-in checklist. `skills` is the
// list of crucial JD skills the resume lacked (gap_report.suggested_skills).
// The user ticks the ones they actually have; "Add selected" routes them into
// the tailored resume's skills section via /api/add-skills and re-renders.
function renderSuggestedSkills(skills) {
  els.suggestedSkills.innerHTML = "";
  if (!skills || !skills.length) {
    els.suggestedSkills.classList.add("hidden");
    return;
  }

  const box = document.createElement("div");
  box.className = "suggest-box";
  box.innerHTML =
    `<h4>Crucial skills this job wants</h4>` +
    `<p class="hint" style="margin:0 0 0.6rem;">The job centers on these, but they're not on your resume. ` +
    `Tick any you genuinely have and we'll add them to your Skills.</p>`;

  const list = document.createElement("div");
  list.className = "suggest-list";
  for (const skill of skills) {
    const id = `suggest-${skill.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
    const label = document.createElement("label");
    label.className = "suggest-item";
    label.htmlFor = id;
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = id;
    cb.value = skill;
    const span = document.createElement("span");
    span.textContent = skill;
    label.appendChild(cb);
    label.appendChild(span);
    list.appendChild(label);
  }
  box.appendChild(list);

  const actions = document.createElement("div");
  actions.className = "actions";
  const addBtn = document.createElement("button");
  addBtn.textContent = "Add selected to Skills";
  const status = document.createElement("span");
  status.className = "status";
  actions.appendChild(addBtn);
  actions.appendChild(status);
  box.appendChild(actions);
  els.suggestedSkills.appendChild(box);
  els.suggestedSkills.classList.remove("hidden");

  addBtn.addEventListener("click", async () => {
    const chosen = [...list.querySelectorAll("input:checked")].map((c) => c.value);
    if (!chosen.length) {
      setStatus(status, "Tick at least one skill first.", "error");
      return;
    }
    addBtn.disabled = true;
    setStatus(status, "Adding…", "");
    try {
      const resp = await postJSON("/api/add-skills", {
        skills_section: state.tailored.tailored_resume.skills,
        skill_names: chosen,
      });
      // Update the live resume + re-render the skills diff.
      state.tailored.tailored_resume.skills = resp.skills;
      rebuildSkillsDiff();
      // Drop the just-added skills from the suggestion list.
      const remaining = skills.filter((s) => !chosen.includes(s));
      renderSuggestedSkills(remaining);
    } catch (err) {
      setStatus(status, "Failed.", "error");
      showError(err.message);
    } finally {
      addBtn.disabled = false;
    }
  });
}

// Rebuilds the skills diff from the current tailored resume after skills are
// added. Each group's "original" is its pre-existing keywords; newly added
// ones show as tailored-only additions.
function rebuildSkillsDiff() {
  const groups = state.tailored.tailored_resume.skills || [];
  const diffGroups = groups.map((g) => ({
    category: g.category,
    original: [...g.keywords],
    tailored: [...g.keywords],
    low_relevance: false,
  }));
  renderSkillSectionDiff(els.skillsDiff, diffGroups, "skills", state.tailored.tailored_resume.skills);
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
    wrap.className = "diff-group" + (group.low_relevance ? " low-relevance" : "");

    const headerRow = document.createElement("div");
    headerRow.className = "category-row";

    const categoryName = document.createElement("div");
    categoryName.className = "category";
    categoryName.textContent = group.category;
    headerRow.appendChild(categoryName);

    if (group.low_relevance) {
      const badge = document.createElement("span");
      badge.className = "low-relevance-badge";
      badge.textContent = "Low relevance for this job - consider removing";
      headerRow.appendChild(badge);
    }

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

// Renders an experience/projects bullet diff. `entries` is the diff list
// ({label, sublabel, bullets:[{original, tailored}]}) and `targetEntries` is
// the live array inside state.tailored.tailored_resume (experience or
// projects) so edits to the tailored bullet text are written back and reach
// the PDF. Entry index `ei` and bullet index `bi` line up between the two.
function renderBulletSectionDiff(container, entries, targetEntries) {
  container.innerHTML = "";
  if (!entries || !entries.length) return;
  if (!targetEntries) return;

  entries.forEach((entry, ei) => {
    if (!entry.bullets || !entry.bullets.length) return;
    const wrap = document.createElement("div");
    wrap.className = "diff-group";

    const heading = document.createElement("div");
    heading.className = "bullet-entry-head";
    const head = entry.label || "";
    const sub = entry.sublabel ? ` — ${entry.sublabel}` : "";
    heading.textContent = head + sub;
    wrap.appendChild(heading);

    entry.bullets.forEach((bullet, bi) => {
      renderDiffPair(wrap, "bullet", bullet.original, bullet.tailored, (val) => {
        if (targetEntries[ei] && Array.isArray(targetEntries[ei].bullets)) {
          targetEntries[ei].bullets[bi] = val;
        }
      });
    });

    container.appendChild(wrap);
  });
}

function renderTailoringDiff(result) {
  const { diff, honesty_warnings, gap_report } = result;

  renderHonestyWarnings(honesty_warnings);
  renderGapReport(gap_report);
  renderSuggestedSkills(gap_report?.suggested_skills);

  els.stepPlaceholder.classList.add("hidden");

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

  // Experience / project bullets (reworded for the role; facts preserved).
  renderBulletSectionDiff(els.experienceDiff, diff.experience || [], tailoredResume.experience);
  renderBulletSectionDiff(els.projectsDiff, diff.projects || [], tailoredResume.projects);

  // Certifications & awards (static facts, read-only).
  renderExtras(tailoredResume);

  els.stepReview.classList.remove("hidden");
  switchTab("resume");
  switchSubtab("overview");
  els.stepReview.scrollIntoView({ behavior: "smooth", block: "start" });

  // The resume is now visible. Generate the cover letter in the background so
  // the user can start reviewing/editing the resume without waiting.
  generateCoverLetterInBackground();
}

// --- Tabs --------------------------------------------------------------------

function switchTab(name) {
  els.tabResume.classList.toggle("hidden", name !== "resume");
  els.tabCoverLetter.classList.toggle("hidden", name !== "cover-letter");
  for (const tab of els.reviewTabs.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.tab === name);
  }
}

// Sub-tabs within the Resume tab (Title & Summary / Skills / Experience / ...).
function switchSubtab(name) {
  for (const panel of els.tabResume.querySelectorAll(".subtab-panel")) {
    panel.classList.toggle("hidden", panel.id !== `sub-${name}`);
  }
  for (const tab of els.resumeSubtabs.querySelectorAll(".subtab")) {
    tab.classList.toggle("active", tab.dataset.subtab === name);
  }
}

// Renders certifications and awards (read-only static facts from the resume).
function renderExtras(resume) {
  function fill(container, items, emptyMsg) {
    container.innerHTML = "";
    if (!items || !items.length) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = emptyMsg;
      container.appendChild(p);
      return;
    }
    const ul = document.createElement("ul");
    ul.className = "extras-list";
    for (const item of items) {
      const li = document.createElement("li");
      li.textContent = item;
      ul.appendChild(li);
    }
    container.appendChild(ul);
  }
  fill(els.certificationsList, resume.certifications, "No certifications listed.");
  fill(els.awardsList, resume.awards, "No awards listed.");
}

// --- Cover letter ------------------------------------------------------------

// Sets the cover-letter editor to a "loading" state while it generates in the
// background.
function setCoverLetterLoading() {
  els.clBody.value = "Writing your cover letter in the background…";
  els.clBody.disabled = true;
  setStatus(els.statusCoverLetter, "Generating in the background…", "");
}

// Renders the cover letter into the subject line + single body textarea. The
// body is one editable block (paragraphs joined by blank lines). state.coverLetter
// holds {company, role} for context; subject/body are read from the inputs at
// copy/download time so edits are always respected.
function renderCoverLetter(coverLetter) {
  els.clBody.disabled = false;
  if (!coverLetter || !coverLetter.paragraphs || !coverLetter.paragraphs.length) {
    state.coverLetter = null;
    els.clBody.value = "";
    els.clBody.placeholder =
      "Cover letter couldn't be generated (the local model may have been busy). Use Regenerate to try again.";
    setStatus(els.statusCoverLetter, "Not generated.", "error");
    return;
  }

  const company = coverLetter.company || "";
  const role = coverLetter.role || "";
  state.coverLetter = { company, role };

  // Default Re: line (editable).
  els.clSubject.value =
    role ? `Re: Application for ${role}${company ? ` at ${company}` : ""}` : "";

  // Single body block: paragraphs separated by a blank line.
  els.clBody.value = coverLetter.paragraphs.join("\n\n");
  setStatus(els.statusCoverLetter, "Ready — edit freely.", "success");
}

// Split the single body block back into paragraphs (on blank lines) for the
// PDF renderer, which expects a list.
function coverLetterParagraphs() {
  return els.clBody.value
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}

// Assemble the full cover-letter plain text (with subject/salutation/signature)
// for copying to the clipboard.
function coverLetterText() {
  const contact = state.tailored?.tailored_resume?.contact;
  const lines = [];
  if (contact?.name) lines.push(contact.name);
  if (els.clSubject.value.trim()) lines.push(els.clSubject.value.trim());
  lines.push("");
  lines.push("Dear Hiring Manager,");
  lines.push("");
  for (const para of coverLetterParagraphs()) {
    lines.push(para);
    lines.push("");
  }
  lines.push("Sincerely,");
  if (contact?.name) lines.push(contact.name);
  return lines.join("\n");
}

// Generate the cover letter in the background, grounded in the tailored resume.
async function generateCoverLetterInBackground() {
  if (!state.jdAnalysis || !state.tailored) return;
  setCoverLetterLoading();
  try {
    const coverLetter = await postJSON("/api/cover-letter", {
      jd_analysis: state.jdAnalysis,
      company: els.company.value.trim(),
      role: els.role.value.trim(),
      resume: state.tailored.tailored_resume,
    });
    renderCoverLetter(coverLetter);
  } catch (err) {
    renderCoverLetter(null);
    setStatus(els.statusCoverLetter, "Failed — use Regenerate to retry.", "error");
  }
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
    // Surface the right pane with a hint until the user tailors.
    if (els.stepReview.classList.contains("hidden")) {
      els.stepPlaceholder.classList.remove("hidden");
    }
    setStatus(els.statusAnalyze, "Done.", "success");
  } catch (err) {
    setStatus(els.statusAnalyze, "Failed.", "error");
    showError(err.message);
  } finally {
    els.btnAnalyze.disabled = false;
  }
});

// Shows the categorization modal for `needs_categorization` entries and
// resolves with a map of {lowercase keyword -> chosen category}.
function promptForCategories(needsCategorization) {
  return new Promise((resolve) => {
    els.categorizeList.innerHTML = "";
    setStatus(els.statusCategorize, "", "");

    for (const entry of needsCategorization) {
      const row = document.createElement("div");
      row.className = "categorize-row";

      const label = document.createElement("span");
      label.className = "keyword";
      label.textContent = entry.keyword;
      row.appendChild(label);

      const select = document.createElement("select");
      select.dataset.keyword = entry.keyword.toLowerCase();
      for (const category of entry.categories) {
        const option = document.createElement("option");
        option.value = category;
        option.textContent = category;
        select.appendChild(option);
      }
      const extraOption = document.createElement("option");
      extraOption.value = entry.extra_category;
      extraOption.textContent = `${entry.extra_category} (catch-all)`;
      extraOption.selected = true;
      select.appendChild(extraOption);

      row.appendChild(select);
      els.categorizeList.appendChild(row);
    }

    els.categorizeModal.classList.remove("hidden");

    const onSubmit = () => {
      const overrides = {};
      for (const select of els.categorizeList.querySelectorAll("select")) {
        overrides[select.dataset.keyword] = select.value;
      }
      els.categorizeModal.classList.add("hidden");
      els.btnCategorizeSubmit.removeEventListener("click", onSubmit);
      resolve(overrides);
    };
    els.btnCategorizeSubmit.addEventListener("click", onSubmit);
  });
}

els.btnTailor.addEventListener("click", async () => {
  clearError();
  if (!state.jdAnalysis) return;

  els.btnTailor.disabled = true;
  setStatus(els.statusTailor, "Tailoring resume & cover letter with local LLM... this can take a minute or two.", "");

  try {
    let categoryOverrides = {};
    let result;
    while (true) {
      result = await postJSON("/api/tailor", {
        jd_analysis: state.jdAnalysis,
        category_overrides: categoryOverrides,
        company: els.company.value.trim(),
        role: els.role.value.trim(),
      });
      if (!result.needs_categorization) break;

      setStatus(els.statusTailor, "Waiting for keyword categorization...", "");
      const chosen = await promptForCategories(result.needs_categorization);
      categoryOverrides = { ...categoryOverrides, ...chosen };
      setStatus(els.statusTailor, "Tailoring resume & cover letter with local LLM... this can take a minute or two.", "");
    }

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

// Tab switching in the right pane.
els.reviewTabs.addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (tab) switchTab(tab.dataset.tab);
});

// Sub-tab switching within the Resume tab.
els.resumeSubtabs.addEventListener("click", (e) => {
  const tab = e.target.closest(".subtab");
  if (tab) switchSubtab(tab.dataset.subtab);
});

els.btnRegenerateCoverLetter.addEventListener("click", async () => {
  clearError();
  if (!state.jdAnalysis || !state.tailored) return;

  els.btnRegenerateCoverLetter.disabled = true;
  setStatus(els.statusCoverLetter, "Regenerating cover letter with local LLM...", "");

  try {
    const coverLetter = await postJSON("/api/cover-letter", {
      jd_analysis: state.jdAnalysis,
      company: els.company.value.trim(),
      role: els.role.value.trim(),
      resume: state.tailored.tailored_resume,
    });
    renderCoverLetter(coverLetter);
  } catch (err) {
    setStatus(els.statusCoverLetter, "Failed.", "error");
    showError(err.message);
  } finally {
    els.btnRegenerateCoverLetter.disabled = false;
  }
});

els.btnCopyCoverLetter.addEventListener("click", async () => {
  clearError();
  if (!coverLetterParagraphs().length) {
    setStatus(els.statusCoverLetter, "Nothing to copy yet.", "error");
    return;
  }
  try {
    await navigator.clipboard.writeText(coverLetterText());
    setStatus(els.statusCoverLetter, "Copied to clipboard.", "success");
  } catch (err) {
    setStatus(els.statusCoverLetter, "Failed to copy.", "error");
    showError(err.message);
  }
});

els.btnDownloadCoverLetter.addEventListener("click", async () => {
  clearError();
  if (!state.jdAnalysis) return;

  const paragraphs = coverLetterParagraphs();
  if (!paragraphs.length) {
    setStatus(els.statusCoverLetter, "Nothing to download yet.", "error");
    return;
  }

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
        subject: els.clSubject.value.trim(),
        paragraphs,
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
