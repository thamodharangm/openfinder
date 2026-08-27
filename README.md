<p align="center">
  <img src="openfinderlogo.svg" alt="OpenFinder Logo" width="220" />
</p>

<h1 align="center">🎯 OpenFinder v2.0 - Universal AI Career & LinkedIn Scout</h1>

<p align="center">
  <strong>Open-Source Real-Time Job Scout, Resume Matcher & Recruiter Intelligence Engine</strong><br>
  <em>Plug & Play with Claude Desktop, ChatGPT Actions, Cursor, Windsurf & Python CLI</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" />
  <img src="https://img.shields.io/badge/MCP-Protocol-purple.svg" />
  <img src="https://img.shields.io/badge/ChatGPT-OpenAPI_Action-74aa9c.svg" />
  <img src="https://img.shields.io/badge/Claude-Desktop_&_Web-orange.svg" />
  <img src="https://img.shields.io/badge/FastAPI-v0.110+-009688.svg" />
  <img src="https://img.shields.io/badge/License-MIT-green.svg" />
</p>

---

## 💡 What is OpenFinder?

**OpenFinder** is a free, open-source AI scout that bridges **Claude**, **ChatGPT**, and **AI Coding IDEs** directly to real-time LinkedIn hiring posts and job listings.

- 🔍 **Live LinkedIn Search**: 100% real-time verified jobs with direct clickable apply links (`https://in.linkedin.com/jobs/view/...`).
- 📄 **Deep Resume PDF Parser**: Extracts categorized tech stack (Frontend, Backend, Cloud, DBs), experience, and target roles.
- 🎯 **ATS Match & Gap Scoring**: Computes multidimensional match % and suggests actionable resume tailoring points.
- ✉️ **AI Outreach Suite**: Generates 4 recruiter-converting formats (300-char LinkedIn Connection Notes, InMail DMs, Cover Emails, Follow-ups).

---

## ⚡ Quick Start (In 30 Seconds)

### 1. Clone & Install
```bash
git clone https://github.com/thamodharangm/openfinder.git
cd openfinder
pip install -r requirements.txt
```

### 2. Run Instant Search in Terminal
```bash
# Search by Role & Location
python scout.py "React Developer" "Bangalore"

# Match against your Resume PDF
python scout.py --resume "D:/my_resume.pdf" --location "Chennai"
```

---

## 🔌 How to Use with Any AI Platform

<details open>
<summary><h3>🤖 1. Claude Desktop (MCP Setup)</h3></summary>

Add OpenFinder to your Claude Desktop config:
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "openfinder": {
      "command": "python",
      "args": [
        "D:/projects/research/linkedin-job-scout-mcp/server.py"
      ],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```
*(Replace the path with your local folder path using forward slashes `/`).*

**Restart Claude Desktop** — The 🔨 tool icon will appear automatically!
</details>

<details open>
<summary><h3>💬 2. ChatGPT (Custom GPT Action)</h3></summary>

1. Start the API server:
   ```bash
   python api_server.py
   ```
2. In ChatGPT, create a **Custom GPT** ➡️ Go to **Configure** ➡️ **Actions** ➡️ **Create new action**.
3. Import the OpenAPI schema from [`chatgpt_openapi_schema.json`](file:///d:/projects/research/linkedin-job-scout-mcp/chatgpt_openapi_schema.json) or paste your server URL (e.g. deployed on Render / ngrok).
4. Save and start chatting!
</details>

<details open>
<summary><h3>⚡ 3. Cursor & Windsurf IDE (MCP)</h3></summary>

In Cursor or Windsurf settings ➡️ **Features** ➡️ **MCP Servers** ➡️ **Add New MCP Server**:
- **Name**: `openfinder`
- **Type**: `command`
- **Command**: `python d:/projects/research/linkedin-job-scout-mcp/server.py`
</details>

---

## 🗣️ Example Prompts to Ask AI

Once connected to Claude or ChatGPT, you can ask natural language questions:

- 🔹 *"Find 5 recent Remote React Developer jobs on LinkedIn."*
- 🔹 *"Here is my resume at `D:/my_resume.pdf`. Find top 5 matching Python Backend jobs in Bangalore with ATS score > 70%."*
- 🔹 *"Write a personalized LinkedIn connection note under 300 characters for the top matched job."*

---

## 🛠️ MCP Tools & API Endpoints

| Tool / Endpoint | Purpose | Inputs |
|---|---|---|
| `search_linkedin_hiring` / `GET /api/search-hiring-posts` | Finds live verified LinkedIn jobs with apply links & skills. | `keywords`, `location`, `remote_only`, `max_results` |
| `search_jobs_by_resume` / `POST /api/search-jobs-by-resume` | Analyzes PDF resume + finds & ranks matching jobs by ATS %. | `resume_path` (or file upload), `location` |
| `parse_resume` / `POST /api/parse-resume` | Categorizes candidate skills, experience level, target roles. | `pdf_path` (or file upload) |
| `generate_recruiter_pitch` / `POST /api/generate-pitch` | Generates Connection notes (<300 chars), InMail, Cover Emails. | `job_title`, `company_name`, `matched_skills` |

---

## 📂 Project Architecture

```text
linkedin-job-scout-mcp/
├── server.py                   # Standard FastMCP stdio server (Claude Desktop, Cursor)
├── api_server.py               # Dual-protocol REST & SSE server (ChatGPT Actions, Web)
├── scout.py                    # Dead-simple CLI search & resume matcher
├── test_pipeline.py            # Automated end-to-end test suite
├── chatgpt_openapi_schema.json # Plug-and-play ChatGPT action schema
├── claude_desktop_config.json  # 1-click Claude Desktop config snippet
├── core/
│   ├── linkedin_finder.py      # Direct live LinkedIn guest search & skill extraction
│   ├── resume_parser.py        # PDF skill categorization & experience estimator
│   ├── matcher.py              # Multi-dimensional ATS match engine
│   ├── pitch_generator.py      # Recruiter outreach message suite
│   ├── cache.py                # Local SQLite sub-second response cache
│   └── spam_filter.py          # Engagement bait & spam remover
├── config.py                   # Taxonomy rules & search defaults
└── requirements.txt            # Python dependencies
```

---

## 📄 License
MIT License - Free and open-source for all developers and job seekers worldwide.
