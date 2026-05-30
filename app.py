from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from config import Config
import bcrypt, os

app = Flask(__name__)
app.config.from_object(Config)

# Support multiple frontend origins — split by comma in .env
# e.g. FRONTEND_URL=http://localhost:3000,http://192.168.1.10:3000,https://yourdomain.com
_origins = [o.strip() for o in Config.FRONTEND_URL.split(",") if o.strip()]
CORS(app, resources={r"/api/*": {"origins": _origins}}, supports_credentials=True)
jwt = JWTManager(app)
# Email is sent via smtplib directly (credentials loaded from MongoDB at send-time,
# falling back to .env). Flask-Mail is not used.

# Register blueprints
from routes.auth import auth_bp
from routes.public import public_bp
from routes.bookings import bookings_bp
from routes.admin import admin_bp
from routes.superadmin import superadmin_bp
from routes.superadmin_bookings import sa_bookings_bp
from routes.seo import seo_bp
from routes.notifications import notifications_bp

app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(public_bp, url_prefix="/api")
app.register_blueprint(bookings_bp, url_prefix="/api/bookings")
app.register_blueprint(admin_bp, url_prefix="/api/admin")
app.register_blueprint(superadmin_bp, url_prefix="/api/superadmin")
app.register_blueprint(sa_bookings_bp, url_prefix="/api/superadmin")
app.register_blueprint(notifications_bp, url_prefix="/api/notifications")
app.register_blueprint(seo_bp)  # /sitemap.xml and /robots.txt at root level


def seed_superadmin():
    """Create super admin on first run if not exists."""
    from utils.db import users_col
    from datetime import datetime
    if not users_col.find_one({"role": "super_admin"}):
        hashed = bcrypt.hashpw(Config.SUPER_ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()
        users_col.insert_one({
            "name": Config.SUPER_ADMIN_NAME,
            "email": Config.SUPER_ADMIN_EMAIL,
            "phone": "",
            "password": hashed,
            "role": "super_admin",
            "is_active": True,
            "created_at": datetime.utcnow(),
        })
        print(f"Super admin created: {Config.SUPER_ADMIN_EMAIL}")


def seed_app_settings():
    """Seed default app settings."""
    from utils.db import app_settings_col
    if not app_settings_col.find_one({}):
        app_settings_col.insert_one({
            "footer_powered_by": "EventPro",
            "footer_contact": "+91 97421 35871",
            "footer_email": "info@eventpro.com",
            "footer_website": "https://www.eventpro.com",
            "site_name": "EventPro",
            # Developer info
            "developer_name": "Your Developer Name",
            "developer_url": "https://yourportfolio.com",
            "developer_tagline": "Crafted with ❤️",
            # Social media
            "social_instagram": "",
            "social_facebook": "",
            "social_twitter": "",
            "slideshow_texts": [
                "Create Memories That Last Forever",
                "Your Dream Event Starts Here",
                "Celebrations Made Special",
                "Book Your Perfect Moment",
            ],
        })


with app.app_context():
    try:
        seed_superadmin()
        seed_app_settings()
    except Exception as _seed_err:
        import logging
        logging.warning(f"[startup] Seed skipped (MongoDB may be slow): {_seed_err}")


@app.route("/api/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    # host="0.0.0.0" makes Flask reachable from any IP (LAN, public, etc.)
    # Set DEBUG=false in production
    debug_mode = os.getenv("FLASK_ENV", "development") == "development"
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
