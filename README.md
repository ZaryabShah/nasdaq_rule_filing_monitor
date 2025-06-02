# NASDAQ Rule-Filing Monitor

A lightweight Python bot that polls the NASDAQ Rule Filings page every minute and notifies a Discord channel when a new rule filing appears.

## Table of Contents

1. [Features](#features)  
2. [Prerequisites](#prerequisites)  
3. [Installation](#installation)  
4. [Configuration](#configuration)  
5. [Usage](#usage)  
6. [How It Works](#how-it-works)  
7. [State File (`known_rows.json`)](#state-file-known_rowsjson)  
8. [Customizing](#customizing)  
9. [Troubleshooting](#troubleshooting)  
10. [License](#license)  

---

## Features

- ✔ Polls NASDAQ Rule Filings (current year) once per minute by default.  
- ✔ Automatically rotates through a pool of authenticated HTTP proxies to reduce IP-based throttling.  
- ✔ Selects a random User-Agent from a customizable list on each request.  
- ✔ Parses the table of filings, extracts each row’s ID and description.  
- ✔ Filters out already-seen IDs (persisted in `known_rows.json`).  
- ✔ When a new filing is detected, sends a Discord webhook with:  
  - Filing ID (e.g., `SR-NASDAQ-2025-001`)  
  - Filing description  
  - UTC timestamp of detection  
- ✔ Maintains local state (`known_rows.json`) so each filing ID is notified only once.  
- ✔ Simple “check” mode can be added to fetch & print counts without modifying state or sending messages.

---

## Prerequisites

- Python 3.8 or later  
- Access to valid proxy credentials (IP, port, username, password).  
- A Discord webhook URL with permissions to post in your target channel.  

### Python Dependencies

```text
requests
beautifulsoup4
