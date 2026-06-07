from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
import bcrypt
from utils.db import users_col, main_events_col, sub_events_col, app_settings_col
from utils.helpers import serialize
from utils.cloudinary_utils import upload_image

superadmin_bp = Blueprint("superadmin", __name__)


def require_superadmin():
    uid = get_jwt_identity()
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user or user.get("role") != "super_admin":
        return None, jsonify({"error": "Super admin access required"}), 403
    return user, None, None


# ─── Main Events ─────────────────────────────────────────────────────────────

@superadmin_bp.route("/main-events", methods=["GET"])
@jwt_required()
def list_main_events():
    sa, err, code = require_superadmin()
    if err:
        return err, code
    events = list(main_events_col.find().sort("created_at", -1))

    # Attach admin info
    for e in events:
        if e.get("assigned_admin"):
            admin = users_col.find_one({"_id": e["assigned_admin"]}, {"password": 0})
            e["admin_info"] = {k: v for k, v in (admin or {}).items()}
    return jsonify(serialize(events)), 200


@superadmin_bp.route("/main-events", methods=["POST"])
@jwt_required()
def create_main_event():
    sa, err, code = require_superadmin()
    if err:
        return err, code

    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    event = {
        "name": name,
        "address": data.get("address", ""),
        "map_location": data.get("map_location", ""),
        "contact_no": data.get("contact_no", ""),
        "email": data.get("email", ""),
        "website": data.get("website", ""),
        "description": data.get("description", ""),
        "images": data.get("images", []),
        "rating": data.get("rating", 5.0),
        "total_bookings": 0,
        "total_customers": 0,
        "assigned_admin": None,
        "is_active": True,
        "created_at": datetime.utcnow(),
    }
    result = main_events_col.insert_one(event)
    event["_id"] = result.inserted_id
    return jsonify(serialize(event)), 201


@superadmin_bp.route("/main-events/<event_id>", methods=["PUT"])
@jwt_required()
def update_main_event(event_id):
    sa, err, code = require_superadmin()
    if err:
        return err, code

    oid = ObjectId(event_id) if ObjectId.is_valid(event_id) else None
    data = request.get_json()
    allowed = ["name", "address", "map_location", "contact_no", "email",
               "website", "description", "images", "rating", "is_active"]
    updates = {k: data[k] for k in allowed if k in data}

    if "assigned_admin" in data:
        admin_id = data["assigned_admin"]
        if admin_id and ObjectId.is_valid(admin_id):
            admin_oid = ObjectId(admin_id)
            users_col.update_one({"_id": admin_oid}, {"$set": {"assigned_event": oid}})
            updates["assigned_admin"] = admin_oid
        elif admin_id is None:
            updates["assigned_admin"] = None

    updates["updated_at"] = datetime.utcnow()
    main_events_col.update_one({"_id": oid}, {"$set": updates})
    return jsonify({"message": "Updated"}), 200


@superadmin_bp.route("/main-events/<event_id>", methods=["DELETE"])
@jwt_required()
def delete_main_event(event_id):
    sa, err, code = require_superadmin()
    if err:
        return err, code
    oid = ObjectId(event_id) if ObjectId.is_valid(event_id) else None
    main_events_col.update_one({"_id": oid}, {"$set": {"is_active": False}})
    return jsonify({"message": "Deleted"}), 200


@superadmin_bp.route("/main-events/<event_id>/upload-image", methods=["POST"])
@jwt_required()
def upload_event_image(event_id):
    sa, err, code = require_superadmin()
    if err:
        return err, code
    if "image" not in request.files:
        return jsonify({"error": "No image"}), 400
    url = upload_image(request.files["image"], folder="main_events")
    oid = ObjectId(event_id) if ObjectId.is_valid(event_id) else None
    main_events_col.update_one({"_id": oid}, {"$push": {"images": url}})
    return jsonify({"url": url}), 200


# ─── Admin Management ────────────────────────────────────────────────────────

@superadmin_bp.route("/admins", methods=["GET"])
@jwt_required()
def list_admins():
    sa, err, code = require_superadmin()
    if err:
        return err, code
    admins = list(users_col.find({"role": "admin"}, {"password": 0}))

    for a in admins:
        if a.get("assigned_event"):
            ev = main_events_col.find_one({"_id": a["assigned_event"]}, {"name": 1})
            a["assigned_event_name"] = ev.get("name", "") if ev else ""

    return jsonify(serialize(admins)), 200


@superadmin_bp.route("/admins", methods=["POST"])
@jwt_required()
def create_admin():
    sa, err, code = require_superadmin()
    if err:
        return err, code

    data = request.get_json()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    password = data.get("password", "")
    assigned_event_id = data.get("assigned_event")

    if not all([name, email, password]):
        return jsonify({"error": "name, email, password required"}), 400

    if users_col.find_one({"email": email}):
        return jsonify({"error": "Email already exists"}), 409

    assigned_oid = ObjectId(assigned_event_id) if assigned_event_id and ObjectId.is_valid(assigned_event_id) else None

    VALID_PERMISSIONS = {"event_settings", "bookings", "reports"}
    permissions = [p for p in data.get("permissions", ["event_settings", "bookings"]) if p in VALID_PERMISSIONS]

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    admin = {
        "name": name,
        "email": email,
        "phone": phone,
        "password": hashed,
        "role": "admin",
        "permissions": permissions,
        "assigned_event": assigned_oid,
        "is_active": True,
        "created_at": datetime.utcnow(),
    }
    result = users_col.insert_one(admin)

    if assigned_oid:
        main_events_col.update_one({"_id": assigned_oid}, {"$set": {"assigned_admin": result.inserted_id}})

    admin["_id"] = result.inserted_id
    return jsonify(serialize({k: v for k, v in admin.items() if k != "password"})), 201


@superadmin_bp.route("/admins/<admin_id>", methods=["PUT"])
@jwt_required()
def update_admin(admin_id):
    sa, err, code = require_superadmin()
    if err:
        return err, code

    a_oid = ObjectId(admin_id) if ObjectId.is_valid(admin_id) else None
    data = request.get_json()
    updates = {}
    VALID_PERMISSIONS = {"dashboard", "event_settings", "bookings", "reports", "customers"}
    for f in ["name", "phone", "is_active"]:
        if f in data:
            updates[f] = data[f]
    if "email" in data and data["email"]:
        new_email = data["email"].strip().lower()
        existing = users_col.find_one({"email": new_email, "_id": {"$ne": a_oid}})
        if existing:
            return jsonify({"error": "Email already in use by another account"}), 400
        updates["email"] = new_email
    if "permissions" in data:
        updates["permissions"] = [p for p in data["permissions"] if p in VALID_PERMISSIONS]

    if "assigned_event" in data:
        ev_id = data["assigned_event"]
        ev_oid = ObjectId(ev_id) if ev_id and ObjectId.is_valid(ev_id) else None
        updates["assigned_event"] = ev_oid
        if ev_oid:
            main_events_col.update_one({"_id": ev_oid}, {"$set": {"assigned_admin": a_oid}})

    if "password" in data and data["password"]:
        updates["password"] = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()

    users_col.update_one({"_id": a_oid}, {"$set": updates})
    admin = users_col.find_one({"_id": a_oid}, {"password": 0})
    return jsonify(serialize(admin)), 200


@superadmin_bp.route("/admins/<admin_id>", methods=["DELETE"])
@jwt_required()
def delete_admin(admin_id):
    sa, err, code = require_superadmin()
    if err:
        return err, code
    a_oid = ObjectId(admin_id) if ObjectId.is_valid(admin_id) else None
    users_col.update_one({"_id": a_oid}, {"$set": {"is_active": False}})
    return jsonify({"message": "Deactivated"}), 200


# ─── App Settings ─────────────────────────────────────────────────────────────

@superadmin_bp.route("/settings", methods=["GET"])
@jwt_required()
def get_settings():
    sa, err, code = require_superadmin()
    if err:
        return err, code
    settings = app_settings_col.find_one({}) or {}
    return jsonify(serialize(settings)), 200


@superadmin_bp.route("/settings", methods=["PUT"])
@jwt_required()
def update_settings():
    sa, err, code = require_superadmin()
    if err:
        return err, code

    data = request.get_json()
    allowed = [
        # Owner / business info
        "footer_powered_by", "footer_contact", "footer_email", "footer_website",
        # Developer info
        "developer_name", "developer_url", "developer_tagline",
        # Social media URLs
        "social_instagram", "social_facebook", "social_twitter", "social_youtube",
        # Email / SMTP
        "mail_server", "mail_port", "mail_use_tls", "mail_username", "mail_password",
        # General
        "site_name", "slideshow_texts",
    ]
    updates = {k: data[k] for k in allowed if k in data}
    updates["updated_at"] = datetime.utcnow()

    app_settings_col.update_one({}, {"$set": updates}, upsert=True)
    return jsonify({"message": "Settings updated"}), 200


# ─── Users ───────────────────────────────────────────────────────────────────

@superadmin_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    sa, err, code = require_superadmin()
    if err:
        return err, code
    users = list(users_col.find({"role": "user"}, {"password": 0}))
    return jsonify(serialize(users)), 200


@superadmin_bp.route("/users/<user_id>", methods=["PUT"])
@jwt_required()
def update_user(user_id):
    sa, err, code = require_superadmin()
    if err:
        return err, code

    u_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
    data = request.get_json()
    updates = {}
    for f in ["name", "phone", "is_active"]:
        if f in data:
            updates[f] = data[f]

    if "password" in data and data["password"]:
        updates["password"] = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()

    users_col.update_one({"_id": u_oid}, {"$set": updates})
    user = users_col.find_one({"_id": u_oid}, {"password": 0})
    return jsonify(serialize(user)), 200
