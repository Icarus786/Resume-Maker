# Resume Maker

A local, offline web app that tailors your resume and writes a cover letter
for a specific job description, using your locally-running Llama 3.1 (via
Ollama). Runs entirely on your PC - nothing is sent to the cloud.

## How it works

1. You keep your **master resume** as content-only data in
   [`data/master_resume.yaml`](data/master_resume.yaml).
2. The fixed, ATS-friendly layout lives in
   [`templates/resume_template.tex`](templates/resume_template.tex) and
   [`templates/cover_letter_template.tex`](templates/cover_letter_template.tex)
   (LaTeX, compiled to PDF via MiKTeX).
3. Paste a job description into the web UI. The app:
   - Analyzes the JD for ATS keywords (hard skills, soft skills, must-haves).
   - Asks Llama 3.1 to **reword and reorder** your existing resume content to
     better match the JD - it never invents new experience, employers, tools,
     or numbers.
   - Proposes additional keywords from the JD that aren't in your resume yet,
     for **you to approve** before they're added (to an "Additional Skills"
     group).
   - Runs a deterministic **honesty check** that flags any new numbers
     introduced into tailored bullets, as a backstop against fabrication.
   - Generates a grounded cover letter for the role.
4. Download the tailored resume and cover letter as PDFs. Each job you apply
   to gets its own folder under `output/<company>_<role>/`.

## One-time setup

1. **Python 3.11+** - confirm with `python --version`.
2. **Ollama** with a Llama 3.1 model pulled:
   ```
   ollama pull llama3.1
   ```
   (On this machine the installed tag is `Llama3.1:latest` - if yours
   differs, set the `OLLAMA_MODEL` environment variable.)
3. **MiKTeX** (for PDF generation): https://miktex.org/download
   - After installing, reopen your terminal so `pdflatex` is on PATH.
   - The first compile may prompt to auto-install missing LaTeX packages -
     allow it.
4. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```
5. Verify everything is set up:
   ```
   python check_env.py
   ```
   All three checks (Python packages, pdflatex, Ollama+model) should pass.

## Set up your master resume

Edit [`data/master_resume.yaml`](data/master_resume.yaml) with your real,
truthful information. It already contains Shrey's resume as a starting
example - replace it with your own.

If you'd rather start from your existing resume text, use the bootstrap
helper (one-time):
```
python bootstrap_resume.py path\to\your_resume.txt
```
This asks the LLM to **extract** (not embellish) your resume text into the
YAML structure. Review and correct the output by hand afterwards - especially
`title_line`, skill groupings, and any fields left blank.

Validate your YAML loads correctly:
```
python -m app.models
```

Render a PDF to check the layout (requires MiKTeX):
```
python -m app.render
```
Output goes to `output/resume.pdf`.

## Run the app

```
run.bat
```
or
```
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000 in your browser.

### Workflow

1. **Paste a job description** (and optionally the company/role names).
2. Click **Analyze** - shows detected hard skills, soft skills, and
   must-haves.
3. Click **Tailor Resume** - shows a side-by-side diff of your original vs.
   tailored bullets/skills/title line, plus any honesty-check warnings and a
   list of proposed keywords you can check to include.
4. Click **Download Resume PDF** and **Download Cover Letter PDF**.

PDFs are saved under `output/<company>_<role>/` (or `output/` if no
company/role is given).

## Project layout

| Path | Purpose |
|------|---------|
| `data/master_resume.yaml` | Your resume content (edit this) |
| `templates/resume_template.tex` | Resume PDF layout (LaTeX) |
| `templates/cover_letter_template.tex` | Cover letter PDF layout (LaTeX) |
| `app/config.py` | Paths, Ollama/LaTeX settings (env-overridable) |
| `app/models.py` | Resume schema (Pydantic) + YAML loader |
| `app/llm.py` | Ollama client: JD analysis, tailoring, cover letters, bootstrap |
| `app/honesty_guard.py` | Flags new numbers introduced during tailoring |
| `app/render.py` | Fills templates and runs `pdflatex` |
| `app/main.py` | FastAPI app and routes |
| `app/static/` | Browser UI (HTML/CSS/JS) |
| `check_env.py` | Verifies Ollama, model, and pdflatex are ready |
| `bootstrap_resume.py` | One-time: extract YAML from your existing resume text |
| `output/` | Generated PDFs, organized per job application |

## Configuration

Environment variables (all optional, see `app/config.py`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `Llama3.1:latest` | Model name (case-sensitive) |
| `OLLAMA_TEMPERATURE` | `0.2` | Lower = more deterministic |
| `OLLAMA_TIMEOUT_SECONDS` | `300` | Increase if generation is slow |
| `PDFLATEX_BINARY` | `pdflatex` | Override if not on PATH |
