{% raw %}"""Email sending via SMTP."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from server.config import Settings
from server.log_config import get_logger

log = get_logger(__name__)

APP_NAME = "{% endraw %}{{cookiecutter.project_name}}{% raw %}"


async def send_magic_link_email(
    to_email: str,
    magic_link: str,
    settings: Settings,
) -> bool:
    """Send magic link email to user.

    Args:
        to_email: Recipient email address.
        magic_link: Full magic link URL.
        settings: Application settings.

    Returns:
        True if email was sent successfully.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Sign in to {APP_NAME}"
    msg["From"] = settings.email_from
    msg["To"] = to_email

    text_content = f"""
Sign in to {APP_NAME}

Click the link below to sign in:
{magic_link}

This link expires in 15 minutes.

If you didn't request this email, you can safely ignore it.
"""

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: system-ui, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .button {{
            display: inline-block;
            padding: 12px 24px;
            background-color: #2563eb;
            color: white;
            text-decoration: none;
            border-radius: 6px;
            margin: 20px 0;
        }}
        .footer {{ color: #666; font-size: 14px; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Sign in to {APP_NAME}</h1>
        <p>Click the button below to sign in:</p>
        <a href="{magic_link}" class="button">Sign In</a>
        <p>Or copy and paste this link:</p>
        <p><code>{magic_link}</code></p>
        <p class="footer">
            This link expires in 15 minutes.<br>
            If you didn't request this email, you can safely ignore it.
        </p>
    </div>
</body>
</html>
"""

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=(settings.smtp_pass.get_secret_value() if settings.smtp_pass else None),
            start_tls=True,
        )
        log.info("magic_link_email_sent", to=to_email)
        return True

    except Exception as e:
        log.error("magic_link_email_failed", to=to_email, error=str(e))
        return False
{% endraw %}