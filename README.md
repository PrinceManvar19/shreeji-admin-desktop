# Shreeji Admin Desktop

Windows desktop app for Shreeji Auto Service garage management.

## Build
pip install -r requirements.txt
pyinstaller ShreejiAdmin.spec --noconfirm

## Releases
Download the latest installer from the Releases tab.

## Note
This app is not deployed to any server.
Admin features requiring local data (attendance, salary, workers)
run only on the installed desktop app.

## Admin Email OTP Login (Temporarily Disabled)

Admin IDs such as `ADMIN001` currently log in directly. The email OTP service is kept in the codebase for later re-enable.
Set these environment variables in `.env` locally and in Railway/production:

```text
ADMIN_OTP_EMAIL=owner@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=1
SMTP_USERNAME=your-smtp-username
SMTP_PASSWORD=your-smtp-app-password
SMTP_FROM_EMAIL=your-sender-email@example.com
```

Customer login is unchanged. If SMTP is not configured during local development,
the OTP can be generated for local testing and written through the normal app log path when the route flow is re-enabled.
