# Email Reporting Setup Guide

## Overview

ChangeSafe sends automated email reports about LOC consumption to customer administrators. Emails are sent from the customer's own SMTP relay — no source code or analysis output ever leaves the deployment.

## Prerequisites
- ChangeSafe backend v1.x+ with email reporting feature
- Customer-provided SMTP credentials (host, port, username, password, TLS preference)
- At least one recipient email address

## Setup Steps

### 1. Navigate to Email Settings
Open `https://<your-changesafe-url>/settings/email` (admin access required).

### 2. Configure SMTP
| Field | Description |
|-------|-------------|
| Host | SMTP relay hostname (e.g., `smtp.customer.com`) |
| Port | SMTP port (587 for STARTTLS, 465 for SSL, 25 for plaintext) |
| Username | SMTP auth username |
| Password | SMTP auth password (encrypted at rest) |
| TLS | Enable for STARTTLS (recommended). Disable only for internal relays |
| From Address | Sender email (e.g., `changesafe@customer.com`) |
| From Name | Display name (default: "ChangeSafe") |

### 3. Add Recipients
Add one or more email addresses. These receive all automated reports.

### 4. Send Test Email
Click "Send Test Email" and confirm delivery in the recipient's inbox.

### 5. Configure Report Cadence
- **Off**: No scheduled reports (threshold alerts and expiry reminders still active)
- **Weekly**: Select day-of-week (default: Monday)
- **Monthly**: Select day-of-month (1-28, default: 1st)

Reports are sent at the configured hour (UTC).

### 6. Flentas BCC (Optional)
Enable to send a copy of each report to Flentas (`usage-reports@flentas.com`). This helps Flentas proactively manage your account — e.g., reaching out before your license expires.

**What is shared**: tier, LOC usage, expiry date, per-project breakdown.
**What is NOT shared**: source code, analysis output, graph data, user information.

## Verification Checklist

- [ ] Test email received by at least one recipient
- [ ] SMTP credentials verified (no "failed" status)
- [ ] Report cadence confirmed with customer
- [ ] Flentas BCC opt-in discussed with customer
- [ ] Master toggle set to "Enabled"

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Test email shows "failed" | Check SMTP credentials, host, port, TLS setting |
| No scheduled reports | Verify cadence is not "off" and master toggle is enabled |
| Emails going to spam | Ask customer to whitelist the From Address |
| "Email not configured" error | Save the SMTP config before sending test |

## Disabling Email
Toggle the master switch to OFF. All scheduled reports, threshold alerts, and expiry reminders are immediately suppressed. No code redeploy needed.
