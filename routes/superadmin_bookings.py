"""
Super admin bookings endpoint — reuses admin bookings logic with super_admin privilege.
Registered in app.py via admin_bp since require_admin_or_superadmin allows super_admin.
The superadmin_bp also exposes /superadmin/bookings by delegating to admin logic.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
from utils.db import bookings_col, sub_events_col, main_events_col, users_col
from utils.helpers import serialize
from utils.email_utils import build_whatsapp_link

sa_bookings_bp = Blueprint("sa_bookings", __name__)


@sa_bookings_bp.route("/bookings", methods=["GET"])
@jwt_required()
def list_all_bookings():
    uid = get_jwt_identity()
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user or user.get("role") != "super_admin":
        return jsonify({"error": "Unauthorized"}), 403

    status_filter = request.args.get("status")
    query = {}
    if status_filter:
        query["status"] = status_filter

    bookings = list(bookings_col.find(query).sort("created_at", -1))
    for b in bookings:
        sub = sub_events_col.find_one({"_id": b.get("sub_event_id")}, {"name": 1})
        me = main_events_col.find_one({"_id": b.get("main_event_id")}, {"name": 1, "contact_no": 1})
        b["sub_event_name"] = sub.get("name", "") if sub else ""
        b["main_event_name"] = me.get("name", "") if me else ""
        contact = me.get("contact_no", "") if me else ""
        b["whatsapp_link"] = build_whatsapp_link(
            contact, b, b.get("user_details", {}),
            b.get("sub_event_name", ""), b.get("main_event_name", "")
        )

    return jsonify(serialize(bookings)), 200


@sa_bookings_bp.route("/bookings/<booking_id>/status", methods=["PUT"])
@jwt_required()
def update_booking_status(booking_id):
    uid = get_jwt_identity()
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user or user.get("role") != "super_admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    status = data.get("status")
    valid_statuses = ["pending", "confirmed", "cancelled", "completed", "visited"]
    if status not in valid_statuses:
        return jsonify({"error": f"Status must be one of {valid_statuses}"}), 400

    b_oid = ObjectId(booking_id) if ObjectId.is_valid(booking_id) else None
    bookings_col.update_one({"_id": b_oid}, {"$set": {"status": status, "updated_at": datetime.utcnow()}})
    return jsonify({"message": "Status updated"}), 200
