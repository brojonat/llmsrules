---
name: resend-email
description: Send transactional emails via Resend using SMTP or HTTP API. Use when integrating Resend for magic links, scheduled emails, cancellation, or listing sent emails. Covers API keys, SMTP config, scheduled_at, and Go integration patterns.
---

# Resend Email Integration

[Resend](https://resend.com) is a transactional email service. It supports both SMTP and a REST API. Use SMTP for simple sends and the HTTP API for scheduled emails, cancellation, and listing.

## API keys

Resend has scoped API keys. This matters:

| Key type | Can send | Can schedule | Can cancel | Can list |
|----------|----------|-------------|------------|----------|
| Send-only (`re_...`) | Yes | Yes (via HTTP API) | No | No |
| Full access (`re_...`) | Yes | Yes | Yes | Yes |

**Best practice**: use a send-only key for SMTP/sending and a separate full-access key for admin operations (cancel, list). Never use the full-access key for routine sends.

```
SMTP_PASS=re_eiuw...        # send-only, used for SMTP and scheduled sends
RESEND_SUDO_KEY=re_Ak8U...  # full-access, used for cancel/list operations
```

## Domain verification

Before sending, your domain must be verified in Resend. Add the DNS records (TXT, CNAME) from the Resend dashboard. The `from` address must use a verified domain.

If you don't have your own domain verified, you can use a domain from another project that's already set up — just make sure the `SMTP_FROM` address uses that domain.

## Sending via SMTP (Go)

Standard `net/smtp` works. The SMTP password is the Resend API key.

```go
auth := smtp.PlainAuth("", "resend", apiKey, "smtp.resend.com")
addr := "smtp.resend.com:587"
smtp.SendMail(addr, auth, from, []string{to}, []byte(msg))
```

Config:
```
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASS=re_your_api_key
```

## Sending via HTTP API

```bash
curl -X POST https://api.resend.com/emails \
  -H "Authorization: Bearer re_your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "App <noreply@yourdomain.com>",
    "to": ["user@example.com"],
    "subject": "Hello",
    "text": "Plain text body"
  }'
```

Response: `{"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"}`

## Scheduled emails

Use the `scheduled_at` parameter in the HTTP API (not available via SMTP):

```go
payload := map[string]any{
    "from":         "App <noreply@yourdomain.com>",
    "to":           []string{"user@example.com"},
    "subject":      "Reminder",
    "text":         "Your reminder body",
    "scheduled_at": sendAt.UTC().Format(time.RFC3339),
}
```

`scheduled_at` accepts:
- ISO 8601 / RFC3339: `"2026-05-16T00:18:20Z"`
- Natural language: `"in 1 min"`, `"in 30 days"`

**Important**: Save the returned email ID — you'll need it to cancel. Log it and/or return it in your API response.

## Cancelling scheduled emails

Requires a full-access API key (send-only keys return 401):

```bash
curl -X POST https://api.resend.com/emails/{id}/cancel \
  -H "Authorization: Bearer re_full_access_key" \
  -H "Content-Type: application/json"
```

In Go:
```go
req, _ := http.NewRequest("POST", "https://api.resend.com/emails/"+emailID+"/cancel", nil)
req.Header.Set("Authorization", "Bearer "+sudoKey)
```

## Listing emails

Also requires full-access key:

```bash
curl -X GET 'https://api.resend.com/emails?limit=100' \
  -H "Authorization: Bearer re_full_access_key"
```

Query params:
- `limit` (1-100, default 20)
- `after` / `before` (email ID for pagination)

Response includes `id`, `to`, `from`, `subject`, `scheduled_at`, `last_event`, `created_at`.

Filter for scheduled emails:
```bash
curl -s -H "Authorization: Bearer $KEY" \
  "https://api.resend.com/emails?limit=100" | \
  jq '.data[] | select(.scheduled_at != null)'
```

## Go integration pattern

Use an interface so you can swap between console (dev) and real (prod) senders:

```go
type EmailSender interface {
    Send(to, subject, body string) error
    SendScheduled(to, subject, body string, sendAt time.Time) (emailID string, err error)
    CancelScheduled(emailID string) error
}
```

- `ConsoleSender`: prints to stdout in dev, returns fake IDs
- `SMTPSender`: uses SMTP for `Send`, Resend HTTP API for `SendScheduled`/`CancelScheduled`
- Switch based on whether `SMTP_HOST` is set

The `SMTPSender` needs two keys:
```go
type SMTPSender struct {
    Host    string
    Port    string
    User    string
    Pass    string // send-only key, doubles as SMTP password
    From    string
    SudoKey string // full-access key for cancel/list
}
```

## Gotchas

- **Send-only vs full-access keys**: The SMTP password/send key cannot cancel or list emails. You get a 401 with `"This API key is restricted to only send emails"`. Use a separate full-access key.
- **Domain verification required**: Sending from an unverified domain returns `550 The domain is not verified`.
- **SMTP user is always "resend"**: Not your email, not your API key — literally the string `resend`.
- **Scheduled emails can't be modified**: You can only cancel and re-create.
- **Max 50 recipients per email**: Use multiple sends for bulk.
