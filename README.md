<p align="center">
  <img src="openfinderlogo.svg" alt="OpenFinder Logo" width="220" />
</p>

<h1 align="center">🎯 OpenFinder v2.0 - Universal AI LinkedIn Scout & Recruiter Intelligence</h1>

<p align="center">
  <strong>Open-Source Real-Time LinkedIn Posts Scout, Resume ATS Matcher & Recruiter Outreach Engine</strong><br>
  <em>Plug & Play with Claude Desktop, ChatGPT Actions, Cursor, Windsurf & Python CLI</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" />
  <img src="https://img.shields.io/badge/MCP-Protocol-purple.svg" />
  <img src="https://img.shields.io/badge/LinkedIn-Posts_Tab_Search-0077B5.svg" />
  <img src="https://img.shields.io/badge/ChatGPT-OpenAPI_Action-74aa9c.svg" />
  <img src="https://img.shields.io/badge/Claude-Desktop_&_Web-orange.svg" />
  <img src="https://img.shields.io/badge/FastAPI-v0.110+-009688.svg" />
  <img src="https://img.shields.io/badge/License-MIT-green.svg" />
</p>

---

## 💡 What is OpenFinder?

**OpenFinder** is a free, open-source AI scout that bridges **Claude**, **ChatGPT**, and **AI Coding IDEs** directly to real-time LinkedIn hiring posts, recruiter social updates, and resume ATS intelligence.

- 🔍 **`search_posts` (The "Posts" Tab)**: Search LinkedIn posts/content globally with recency filters (`past-24h`, `past-week`, `past-month`) to discover unlisted and informal recruiter hiring announcements.
- 🎯 **`parse_linkedin_post`**: Extracts author, company, raw post text, direct HR contact emails, phone numbers, and required tech stack from any post URL.
- 📄 **Deep Resume PDF Parser**: Extracts categorized tech stack (Frontend, Backend, Cloud, DBs), experience, and target roles.
- 📊 **ATS Match & Gap Scoring**: Computes multidimensional match % and identifies missing skills.
- ✉️ **Personalized Outreach Suite**: Generates 4 recruiter-converting formats (300-char LinkedIn Connection Notes, InMail DMs, Cover Emails with pre-filled HR email, and Follow-ups).

---

## ⚡ Quick Start CLI

### 1. Clone & Install
```bash
git clone https://github.com/thamodharangm/openfinder.git
cd openfinder
pip install -r requirements.txt
```

### 2. Run in Terminal

```bash
# 1. Search LinkedIn Posts (Recency: past-24h / past-week / past-month)
python scout.py --search-posts "React Developer hiring Bangalore" --date-posted past-24h

# 2. Extract HR Emails & Generate Outreach Pitch from any LinkedIn Post URL
python scout.py --post "https://www.linkedin.com/posts/codernkb_hiring-mernstack-developerintern-share-7497921508342878208-3o-y"

# 3. Match a LinkedIn Post against your Resume PDF
python scout.py --post "https://www.linkedin.com/posts/..." --resume "my_resume.pdf"
```

---

## 🛠️ MCP Tools Overview

| MCP Tool | Description |
| :--- | :--- |
| `search_posts` | Search LinkedIn posts/content globally by keyword (the "Posts" tab) with recency filters (`past-24h`, `past-week`, `past-month`). |
| `parse_linkedin_post` | Extract HR emails, contact numbers, required tech stack & generate pitches from any LinkedIn post URL. |
| `search_hiring_posts` | Find verified live recruiter hiring posts with mode and location filters. |
| `parse_resume` | Parse candidate PDF resume into structured profile, skills, and target roles. |
| `match_resume_to_jobs` | Run full ATS matching pipeline scoring resume against live recruiter posts. |
| `generate_recruiter_pitch` | Generate tailored connection notes (<300 chars), InMails, formal cover emails, and follow-ups. |

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
*(Replace the path with your local directory path).*
</details>

<details open>
<summary><h3>💬 2. ChatGPT (Custom GPT Action)</h3></summary>

1. Start the API server:
   ```bash
   python api_server.py
   ```
2. In ChatGPT, create a **Custom GPT** ➡️ Go to **Configure** ➡️ **Actions** ➡️ **Create new action**.
3. Import the OpenAPI schema from [`chatgpt_openapi_schema.json`](chatgpt_openapi_schema.json) or paste your live Render deployment URL.
</details>

<details open>
<summary><h3>⚡ 3. Cursor & Windsurf IDE (MCP)</h3></summary>

In Cursor or Windsurf settings ➡️ **Features** ➡️ **MCP Servers** ➡️ **Add New MCP Server**:
- **Name**: `openfinder`
- **Type**: `command`
- **Command**: `python D:/projects/research/linkedin-job-scout-mcp/server.py`
</details>

---

## 🌐 Deploy to Render (1-Click Free Hosting)

OpenFinder includes [`render.yaml`](render.yaml) & [`Dockerfile`](Dockerfile) for instant cloud deployment:
1. Push to GitHub.
2. Link your repository in [Render Dashboard](https://dashboard.render.com).
3. Access interactive Swagger UI at `https://<YOUR-RENDER-URL>/docs`.

---

## 📜 License
MIT License. Built for open-source AI job seekers and career scouts.
