import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from urllib.parse import quote
from flask import current_app
from config import Config


def _get_smtp_settings():
    """
    Priority: MongoDB (set via UI) → .env (fallback).
    This is checked on every send so UI changes take effect immediately
    without restarting the server.
    """
    from utils.db import app_settings_col
    db = app_settings_col.find_one(
        {},
        {"mail_server": 1, "mail_port": 1, "mail_use_tls": 1,
         "mail_username": 1, "mail_password": 1}
    ) or {}

    # Use DB values if both username and password are present
    if db.get("mail_username") and db.get("mail_password"):
        return {
            "server":   db.get("mail_server")  or Config.MAIL_SERVER,
            "port":     int(db.get("mail_port") or Config.MAIL_PORT),
            "use_tls":  db.get("mail_use_tls", True),
            "username": db["mail_username"],
            "password": db["mail_password"],
            "source":   "database (UI settings)",
        }

    # Fall back to .env
    return {
        "server":   Config.MAIL_SERVER,
        "port":     Config.MAIL_PORT,
        "use_tls":  Config.MAIL_USE_TLS,
        "username": Config.MAIL_USERNAME,
        "password": Config.MAIL_PASSWORD,
        "source":   ".env file",
    }


def _send_raw(to_email: str, subject: str, html_body: str) -> bool:
    """Send an email using smtplib with dynamically loaded credentials."""
    cfg = _get_smtp_settings()

    if not cfg["username"] or not cfg["password"]:
        current_app.logger.warning("Email not sent — no SMTP credentials configured.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")   # RFC 2047 — supports emoji & Unicode
    msg["From"]    = cfg["username"]
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(cfg["server"], cfg["port"], timeout=15) as server:
            if cfg["use_tls"]:
                server.starttls()
            server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["username"], to_email, msg.as_bytes())
        current_app.logger.info(f"Email sent to {to_email} via {cfg['source']}")
        return True
    except Exception as e:
        current_app.logger.error(f"Email send error ({cfg['source']}): {e}")
        return False


def send_booking_confirmation_to_admin(
    admin_email, booking_details, user_details, sub_event_name, main_event_name
):
    """Send booking notification email to admin and return whatsapp link."""
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
      <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0;">New Booking Request</h1>
      </div>
      <div style="padding: 20px;">
        <h2 style="color: #333;">Booking Details</h2>
        <table style="width: 100%; border-collapse: collapse;">
          <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Event</td><td style="padding:8px;">{main_event_name} — {sub_event_name}</td></tr>
          <tr><td style="padding:8px;font-weight:bold;">Customer</td><td style="padding:8px;">{user_details.get('name')}</td></tr>
          <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Email</td><td style="padding:8px;">{user_details.get('email')}</td></tr>
          <tr><td style="padding:8px;font-weight:bold;">Phone</td><td style="padding:8px;">{user_details.get('phone')}</td></tr>
          <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Date</td><td style="padding:8px;">{booking_details.get('booking_date')}</td></tr>
          <tr><td style="padding:8px;font-weight:bold;">Time Slot</td><td style="padding:8px;">{booking_details.get('time_slot', {}).get('start_time')} – {booking_details.get('time_slot', {}).get('end_time')}</td></tr>
          <tr style="background:#f5f5f5;"><td style="padding:8px;font-weight:bold;">Amount</td><td style="padding:8px;">Rs. {booking_details.get('final_cost')}</td></tr>
          {"<tr><td style='padding:8px;font-weight:bold;'>Discount</td><td style='padding:8px;color:green;'>" + str(booking_details.get('discount_percent')) + "% OFF applied</td></tr>" if booking_details.get('offer_applied') else ""}
        </table>
      </div>
    </div>
    """

    _send_raw(
        to_email=admin_email,
        subject=f"New Booking: {sub_event_name} — {user_details.get('name')}",
        html_body=html_body,
    )

    return build_whatsapp_link(
        booking_details.get("main_event_contact", ""),
        booking_details, user_details, sub_event_name, main_event_name,
    )


def build_whatsapp_link(phone, booking_details, user_details, sub_event_name, main_event_name):
    clean_phone = "".join(filter(str.isdigit, str(phone or "")))
    msg = (
        f"Booking Request Received!\n"
        f"Event: {main_event_name} - {sub_event_name}\n"
        f"Customer: {user_details.get('name')}\n"
        f"Phone: {user_details.get('phone')}\n"
        f"Email: {user_details.get('email')}\n"
        f"Date: {booking_details.get('booking_date')}\n"
        f"Time: {booking_details.get('time_slot', {}).get('start_time')} - "
        f"{booking_details.get('time_slot', {}).get('end_time')}\n"
        f"Cost: Rs.{booking_details.get('final_cost')}\n"
        f"Status: Pending Confirmation\n"
        f"Please confirm the booking."
    )
    return f"https://wa.me/{clean_phone}?text={quote(msg)}"
