from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from utils.db import notifications_col, users_col
from utils.helpers import serialize

notifications_bp = Blueprint("notifications", __name__)

def require_admin_or_superadmin():
    uid = get_jwt_identity()
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user or user.get("role") not in ("admin", "super_admin"):
        return None, jsonify({"error": "Unauthorized"}), 403
    return user, None, None

@notifications_bp.route("", methods=["GET"])
@notifications_bp.route("/", methods=["GET"])
@jwt_required()
def get_notifications():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code

    uid_str = str(user["_id"])
    
    # Sort by newest first
    cursor = notifications_col.find({}).sort("created_at", -1).limit(100)
    notifications = list(cursor)

    # Add is_read flag based on whether current user is in read_by array
    for notif in notifications:
        notif["is_read"] = uid_str in notif.get("read_by", [])

    return jsonify(serialize(notifications)), 200

@notifications_bp.route("/<notif_id>/read", methods=["PUT"])
@jwt_required()
def mark_as_read(notif_id):
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code

    uid_str = str(user["_id"])
    
    try:
        notifications_col.update_one(
            {"_id": ObjectId(notif_id)},
            {"$addToSet": {"read_by": uid_str}}
        )
        return jsonify({"message": "Marked as read"}), 200
    except Exception as e:
        return jsonify({"error": "Failed to mark as read"}), 500
