from flask import Blueprint, request, jsonify
from utils.db import main_events_col, sub_events_col, bookings_col, app_settings_col
from utils.helpers import serialize
from bson import ObjectId
from datetime import datetime, date

public_bp = Blueprint("public", __name__)


@public_bp.route("/events/main", methods=["GET"])
def list_main_events():
    try:
        events = list(main_events_col.find({"is_active": True}, {"email": 0}))
        return jsonify(serialize(events)), 200
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"list_main_events error: {e}")
        return jsonify({"error": "Unable to fetch events", "detail": str(e)}), 500


@public_bp.route("/events/main/<event_id>", methods=["GET"])
def get_main_event(event_id):
    try:
        oid = ObjectId(event_id) if ObjectId.is_valid(event_id) else None
        event = main_events_col.find_one({"_id": oid, "is_active": True})
        if not event:
            return jsonify({"error": "Event not found"}), 404
        return jsonify(serialize(event)), 200
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"get_main_event error: {e}")
        return jsonify({"error": "Unable to fetch event"}), 500


@public_bp.route("/events/main/<event_id>/sub-events", methods=["GET"])
def list_sub_events(event_id):
    try:
        oid = ObjectId(event_id) if ObjectId.is_valid(event_id) else None
        subs = list(sub_events_col.find({"main_event_id": oid, "is_active": True}))
        return jsonify(serialize(subs)), 200
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"list_sub_events error: {e}")
        return jsonify({"error": "Unable to fetch sub-events"}), 500


@public_bp.route("/events/sub/<sub_id>", methods=["GET"])
def get_sub_event(sub_id):
    try:
        oid = ObjectId(sub_id) if ObjectId.is_valid(sub_id) else None
        sub = sub_events_col.find_one({"_id": oid, "is_active": True})
        if not sub:
            return jsonify({"error": "Sub-event not found"}), 404
        return jsonify(serialize(sub)), 200
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"get_sub_event error: {e}")
        return jsonify({"error": "Unable to fetch event"}), 500


@public_bp.route("/events/sub/<sub_id>/availability", methods=["GET"])
def check_availability(sub_id):
    """Return time slots for a date, marking which are already booked."""
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "date param required (YYYY-MM-DD)"}), 400

    oid = ObjectId(sub_id) if ObjectId.is_valid(sub_id) else None
    sub = sub_events_col.find_one({"_id": oid, "is_active": True})
    if not sub:
        return jsonify({"error": "Sub-event not found"}), 404

    booked_slots = list(bookings_col.find(
        {"sub_event_id": oid, "booking_date": date_str, "status": {"$nin": ["cancelled"]}},
        {"time_slot": 1}
    ))
    booked_times = {(b["time_slot"]["start_time"], b["time_slot"]["end_time"]) for b in booked_slots}

    slots = []
    for slot in sub.get("time_slots", []):
        key = (slot["start_time"], slot["end_time"])
        slots.append({
            **slot,
            "is_booked": key in booked_times,
            "bookable": slot.get("is_available", True) and key not in booked_times,
        })

    return jsonify({"slots": serialize(slots), "date": date_str}), 200


@public_bp.route("/stats", methods=["GET"])
def get_stats():
    try:
        total_customers = 170 + users_col_count()
        total_bookings  = 245 + bookings_col.count_documents({})
        pipeline = [{"$group": {"_id": None, "avg": {"$avg": "$rating"}}}]
        agg = list(main_events_col.aggregate(pipeline))
        avg_rating = round(agg[0]["avg"], 1) if agg else 4.8
        return jsonify({
            "total_customers": total_customers,
            "total_bookings":  total_bookings,
            "avg_rating":      avg_rating,
        }), 200
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"get_stats error: {e}")
        return jsonify({"total_customers": 170, "total_bookings": 245, "avg_rating": 4.8}), 200


def users_col_count():
    from utils.db import users_col as uc
    return uc.count_documents({"role": "user"})


@public_bp.route("/settings/public", methods=["GET"])
def get_public_settings():
    try:
        settings = app_settings_col.find_one({}, {
            "mail_password": 0, "mail_username": 0,
            "mail_server": 0, "mail_port": 0, "mail_use_tls": 0,
        })
        return jsonify(serialize(settings or {})), 200
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"get_public_settings error: {e}")
        return jsonify({}), 200  # return empty — footer uses defaults
