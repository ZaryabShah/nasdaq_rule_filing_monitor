# nasdaq_rule_filing_monitor
A lightweight Python script that polls the NASDAQ Rule Filings page every minute, detects any newly added rule IDs, sends a Discord notification for each new filing, and records seen IDs in known_rows.json to avoid duplicate alerts.
