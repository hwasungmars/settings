# Google Cloud OAuth 2.0 & MCP Setup Guide

Follow these steps once to connect your Gmail account to the `email` plugin's MCP server.

---

## Step 1: Create Google Cloud OAuth `gmail-credentials.json`

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create a new project (e.g., `triage-gmail-agent`) or select an existing project.
2. **Enable the Gmail API**:
   - Go to **APIs & Services > Library**.
   - Search for **Gmail API** and click **Enable**.
3. **Configure the OAuth Consent Screen**:
   - Go to **APIs & Services > OAuth consent screen** (or **Google Auth Platform > Audience**).
   - Select **External** (or **Internal** if using Google Workspace) and fill in the required app name and your email address.
   - Under **Test users**, add your own Gmail address so your account is authorised to sign in.
4. **Create OAuth Client Credentials**:
   - Go to **APIs & Services > Credentials** -> **+ Create Credentials > OAuth client ID**.
   - Application type: **Desktop app**.
   - Click **Create** and then **Download JSON**.
5. Save the downloaded file to:
   ```text
   ~/vaults/personal/! PRIVATE/gmail-credentials.json
   ```

---

## Step 2: Authorise Your Gmail Account (One-Time Browser Flow)

Run the MCP server with the `--auth` flag in your terminal:

```bash
python3 ~/.gemini/config/plugins/email/mcp_server/gmail_mcp_server.py --auth
```

This opens a browser window where you sign in with Google and grant `gmail.modify` and `gmail.labels` permissions. Once complete, a refreshable token is saved automatically to:

```text
~/vaults/personal/! PRIVATE/gmail-token.json
```

You can verify the connection anytime with:

```bash
python3 ~/.gemini/config/plugins/email/mcp_server/gmail_mcp_server.py --status
```
