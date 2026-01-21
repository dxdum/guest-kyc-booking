"""
Email service for sending verification and notification emails.
Uses SMTP configuration from environment variables.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Email configuration from environment variables
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'contact@uniko.ai')
SENDER_NAME = os.environ.get('SENDER_NAME', 'Guest Check-in System')

# Development mode - if True, prints emails instead of sending
DEV_MODE = os.environ.get('EMAIL_DEV_MODE', 'true').lower() == 'true'


def send_email(to_email, subject, html_content, text_content=None):
    """
    Send an email using SMTP.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML body of the email
        text_content: Plain text body (optional, for email clients that don't support HTML)

    Returns:
        dict with 'success' boolean and 'message' or 'error'
    """
    if DEV_MODE:
        print(f"\n{'='*60}")
        print(f"[DEV MODE] Email would be sent:")
        print(f"To: {to_email}")
        print(f"From: {SENDER_NAME} <{SENDER_EMAIL}>")
        print(f"Subject: {subject}")
        print(f"{'='*60}")
        print(html_content[:500] + "..." if len(html_content) > 500 else html_content)
        print(f"{'='*60}\n")
        return {'success': True, 'message': 'Email logged (dev mode)'}

    if not SMTP_USER or not SMTP_PASSWORD:
        return {'success': False, 'error': 'SMTP credentials not configured'}

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg['To'] = to_email

        # Attach text and HTML parts
        if text_content:
            part1 = MIMEText(text_content, 'plain')
            msg.attach(part1)

        part2 = MIMEText(html_content, 'html')
        msg.attach(part2)

        # Connect and send
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())

        return {'success': True, 'message': 'Email sent successfully'}

    except smtplib.SMTPAuthenticationError:
        return {'success': False, 'error': 'SMTP authentication failed'}
    except smtplib.SMTPException as e:
        return {'success': False, 'error': f'SMTP error: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': f'Email error: {str(e)}'}


def send_verification_email(to_email, verification_code, user_name=None):
    """
    Send email verification code to new user.

    Args:
        to_email: Recipient email address
        verification_code: 6-digit verification code
        user_name: Optional user name for personalization
    """
    greeting = f"Hi {user_name}," if user_name else "Hi,"

    subject = f"Your verification code: {verification_code} - Guest Check-in System"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 40px 20px;">
            <tr>
                <td align="center">
                    <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 500px; background-color: #ffffff; border-radius: 12px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                        <!-- Header -->
                        <tr>
                            <td style="padding: 40px 40px 20px; text-align: center;">
                                <div style="background: linear-gradient(135deg, #3B82F6 0%, #1E40AF 100%); color: white; font-weight: bold; font-size: 24px; padding: 12px 24px; border-radius: 8px; display: inline-block;">
                                    GCS
                                </div>
                                <h1 style="margin: 20px 0 10px; color: #1f2937; font-size: 24px;">Verify Your Email</h1>
                            </td>
                        </tr>
                        <!-- Content -->
                        <tr>
                            <td style="padding: 0 40px 30px;">
                                <p style="color: #4b5563; font-size: 16px; line-height: 1.6; margin: 0 0 20px;">
                                    {greeting}
                                </p>
                                <p style="color: #4b5563; font-size: 16px; line-height: 1.6; margin: 0 0 20px;">
                                    Thanks for signing up for Guest Check-in System. Enter this code to verify your email:
                                </p>
                                <div style="text-align: center; margin: 30px 0;">
                                    <div style="display: inline-block; background: #F3F4F6; padding: 20px 40px; border-radius: 12px; border: 2px dashed #D1D5DB;">
                                        <span style="font-size: 36px; font-weight: 700; letter-spacing: 8px; color: #1F2937; font-family: 'Courier New', monospace;">
                                            {verification_code}
                                        </span>
                                    </div>
                                </div>
                                <p style="color: #6b7280; font-size: 14px; line-height: 1.6; margin: 20px 0 0; text-align: center;">
                                    This code will expire in 24 hours.
                                </p>
                                <p style="color: #6b7280; font-size: 14px; line-height: 1.6; margin: 10px 0 0; text-align: center;">
                                    If you didn't create an account, you can safely ignore this email.
                                </p>
                            </td>
                        </tr>
                        <!-- Footer -->
                        <tr>
                            <td style="padding: 20px 40px; background-color: #f9fafb; border-radius: 0 0 12px 12px; border-top: 1px solid #e5e7eb;">
                                <p style="color: #9ca3af; font-size: 12px; margin: 0; text-align: center;">
                                    Guest Check-in System by Uniko Labs
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    text_content = f"""
    {greeting}

    Thanks for signing up for Guest Check-in System. Enter this code to verify your email:

    {verification_code}

    This code will expire in 24 hours.

    If you didn't create an account, you can safely ignore this email.

    ---
    Guest Check-in System by Uniko Labs
    """

    return send_email(to_email, subject, html_content, text_content)
