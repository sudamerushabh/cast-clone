# Email Smoke Test Runbook

## Prerequisites
- Backend running locally (`uv run uvicorn app.main:app --reload`)
- MailHog running (`docker compose up mailhog`)
- Frontend running (`npm run dev` in cast-clone-frontend)

## Steps

### 1. Start MailHog
```bash
docker compose up mailhog
```
MailHog SMTP: `localhost:1025` (no auth)
MailHog Web UI: `http://localhost:8025`

### 2. Configure SMTP in Settings
1. Navigate to `http://localhost:3000/settings/email`
2. Enable the master toggle
3. SMTP settings:
   - Host: `localhost` (or `host.docker.internal` if backend is in Docker)
   - Port: `1025`
   - Username: (leave empty)
   - Password: (leave empty)
   - TLS: OFF
   - From: `changesafe@test.local`
   - From Name: `ChangeSafe`
4. Add a recipient email (any address — MailHog captures all)
5. Click **Save**

### 3. Send Test Email
1. In the "Test Send" section, enter any email address
2. Click **Send Test Email**
3. Open MailHog UI at `http://localhost:8025`
4. Verify the test email arrived with correct formatting

### 4. Test Threshold Alert
1. Seed a license near the LOC limit (e.g., 79% usage)
2. Trigger an analysis that pushes LOC past 90%
3. The license state should transition HEALTHY → WARN
4. Check MailHog for a `threshold_warn` email

### 5. Test Expiry Reminder
1. Upload a license with `exp` set to 7 days from now
2. Wait for the daily tick at 08:00 UTC (or manually invoke `expiry_reminder_tick()`)
3. Check MailHog for an expiry reminder email

### 6. Verify Flentas BCC
1. Enable the Flentas BCC toggle in Settings
2. Accept the disclosure modal
3. Send another test email
4. Check MailHog — the email should show BCC to `usage-reports@flentas.com`

## Troubleshooting
- **No email in MailHog**: Check that the backend can reach `localhost:1025`. If running in Docker, use `host.docker.internal:1025`.
- **SMTP connection refused**: Ensure MailHog is running (`docker compose ps mailhog`)
- **Email disabled**: Check the master toggle is ON in `/settings/email`
