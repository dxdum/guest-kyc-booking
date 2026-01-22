"""
Email service for sending verification and notification emails.
Uses Gmail API with OAuth2 credentials.

On Render (production): Uses GMAIL_TOKEN_JSON environment variable
On local development: Falls back to local file path
"""

import os
import json
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Gmail API configuration
# Production: Use GMAIL_TOKEN_JSON env var
# Local: Fall back to file path
GMAIL_TOKEN_PATH = r'C:\Users\dardu\gmail_token.json'
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'contact@uniko.ai')
SENDER_NAME = os.environ.get('SENDER_NAME', 'Guest Check-in System')


def get_gmail_credentials():
    """
    Get Gmail API credentials from environment variable or local file.

    Returns:
        dict: Token data for Gmail API, or None if not available
    """
    # First, try environment variable (for Render/production)
    gmail_token_json = os.environ.get('GMAIL_TOKEN_JSON')
    if gmail_token_json:
        try:
            token_data = json.loads(gmail_token_json)
            print("[EMAIL] Using credentials from GMAIL_TOKEN_JSON environment variable")
            return token_data
        except json.JSONDecodeError as e:
            print(f"[EMAIL ERROR] Failed to parse GMAIL_TOKEN_JSON: {e}")
            return None

    # Fall back to local file (for development)
    if os.path.exists(GMAIL_TOKEN_PATH):
        try:
            with open(GMAIL_TOKEN_PATH, 'r') as f:
                token_data = json.load(f)
            print(f"[EMAIL] Using credentials from local file: {GMAIL_TOKEN_PATH}")
            return token_data
        except Exception as e:
            print(f"[EMAIL ERROR] Failed to read {GMAIL_TOKEN_PATH}: {e}")
            return None

    print("[EMAIL ERROR] No Gmail credentials found. Set GMAIL_TOKEN_JSON env var or provide local token file.")
    return None


def get_gmail_service():
    """Get authenticated Gmail API service."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_data = get_gmail_credentials()
        if not token_data:
            return None

        creds = Credentials(
            token=token_data['token'],
            refresh_token=token_data['refresh_token'],
            token_uri=token_data['token_uri'],
            client_id=token_data['client_id'],
            client_secret=token_data['client_secret'],
            scopes=token_data['scopes']
        )

        service = build('gmail', 'v1', credentials=creds)
        return service
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to get Gmail service: {e}")
        return None


def send_email(to_email, subject, html_content, text_content=None):
    """
    Send an email using Gmail API.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML body of the email
        text_content: Plain text body (optional)

    Returns:
        dict with 'success' boolean and 'message' or 'error'
    """
    try:
        service = get_gmail_service()
        if not service:
            return {'success': False, 'error': 'Gmail API not configured'}

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

        # Encode and send
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')

        service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()

        print(f"[EMAIL SENT] To: {to_email}, Subject: {subject}")
        return {'success': True, 'message': 'Email sent successfully'}

    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
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
