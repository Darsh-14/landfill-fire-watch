// API base URL. `make api-local` serves the API on port 8001 for local use.
// scripts/deploy_web.py rewrites this file with the deployed HTTP API URL (stack output ApiUrl).
window.LFW_CONFIG = { apiBase: "http://localhost:8001" };
