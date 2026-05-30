from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
from utils.db import bookings_col, sub_events_col, main_events_col, users_col, notifications_col
from utils.helpers import serialize
from utils.email_utils import send_booking_confirmation_to_admin, build_whatsapp_link

bookings_bp = Blueprint("bookings", __name__)


@bookings_bp.route("/", methods=["POST"])
@jwt_required()
def create_booking():
    uid = get_jwt_identity()
    data = request.get_json()

    sub_id = data.get("sub_event_id")
    booking_date = data.get("booking_date")
    time_slot = data.get("time_slot")  # {start_time, end_time}
    offer_applied = data.get("offer_applied", False)
    rating_screenshot_name = data.get("rating_screenshot_name", "")
    # For outdoor events: client provides their venue location
    client_location = data.get("client_location") or {}
    # {venue_name, address, maps_link}

    if not all([sub_id, booking_date, time_slot]):
        return jsonify({"error": "sub_event_id, booking_date, time_slot required"}), 400

    sub_oid = ObjectId(sub_id) if ObjectId.is_valid(sub_id) else None
    sub = sub_events_col.find_one({"_id": sub_oid, "is_active": True})
    if not sub:
        return jsonify({"error": "Sub-event not found"}), 404

    time_slots = sub.get("time_slots", [])
    is_custom_time = len(time_slots) == 0  # no defined slots → user picks their own time

    if is_custom_time:
        # Custom-time mode: no availability check, keep whatever time the user sent.
        if not time_slot.get("start_time") or not time_slot.get("end_time"):
            return jsonify({"error": "Please provide your preferred start and end time"}), 400
        # Use the sub-event level offer (set by admin when is_available=false)
        slot_config = {
            "has_offer": sub.get("has_offer", False),
            "discount_percent": sub.get("discount_percent", 0),
        }
    else:
        # Slot-based mode: check for double booking on the exact slot
        existing = bookings_col.find_one({
            "sub_event_id": sub_oid,
            "booking_date": booking_date,
            "time_slot.start_time": time_slot["start_time"],
            "time_slot.end_time": time_slot["end_time"],
            "status": {"$nin": ["cancelled"]},
        })
        if existing:
            return jsonify({"error": "This time slot is already booked"}), 409

        slot_config = next(
            (s for s in time_slots
             if s["start_time"] == time_slot["start_time"] and s["end_time"] == time_slot["end_time"]),
            None,
        )
        if not slot_config:
            return jsonify({"error": "Time slot not found in event"}), 400

    # Cost calculation
    original_cost = sub.get("cost", 0) or sub.get("cost_min", 0)
    discount_percent = 0
    final_cost = original_cost

    if offer_applied and slot_config.get("has_offer"):
        discount_percent = slot_config.get("discount_percent", 0)
        final_cost = original_cost * (1 - discount_percent / 100)

    user = users_col.find_one({"_id": ObjectId(uid)})
    user_details = {
        "name": user.get("name"),
        "email": user.get("email"),
        "phone": user.get("phone"),
    }

    main_event = main_events_col.find_one({"_id": sub["main_event_id"]})

    booking = {
        "user_id": ObjectId(uid),
        "main_event_id": sub["main_event_id"],
        "sub_event_id": sub_oid,
        "booking_date": booking_date,
        "time_slot": time_slot,
        "offer_applied": offer_applied,
        "discount_percent": discount_percent,
        "original_cost": original_cost,
        "final_cost": round(final_cost, 2),
        "rating_screenshot_name": rating_screenshot_name,
        "user_details": user_details,
        "event_type": sub.get("event_type", "indoor"),
        "client_location": client_location,   # only relevant for outdoor
        "status": "pending",
        "created_at": datetime.utcnow(),
    }

    result = bookings_col.insert_one(booking)
    booking["_id"] = result.inserted_id

    try:
        notifications_col.insert_one({
            "type": "new_booking",
            "message": f"New booking created for {main_event.get('name', 'Event')} - {sub.get('name', '')}",
            "created_at": datetime.utcnow(),
            "read_by": []
        })
    except Exception as e:
        current_app.logger.warning(f"Notification error: {e}")

    # Send email + generate WhatsApp link
    whatsapp_link = None
    try:
        admin_contact = main_event.get("contact_no", "") if main_event else ""
        admin_email = main_event.get("email", "") if main_event else ""
        send_booking_confirmation_to_admin(
            admin_email, booking, user_details,
            sub.get("name", ""), main_event.get("name", "") if main_event else ""
        )
        whatsapp_link = build_whatsapp_link(
            admin_contact, booking, user_details,
            sub.get("name", ""), main_event.get("name", "") if main_event else ""
        )
    except Exception as e:
        current_app.logger.warning(f"Notification error: {e}")

    return jsonify({
        "booking": serialize(booking),
        "whatsapp_link": whatsapp_link,
    }), 201


@bookings_bp.route("/my", methods=["GET"])
@jwt_required()
def my_bookings():
    uid = get_jwt_identity()
    bookings = list(bookings_col.find({"user_id": ObjectId(uid)}).sort("created_at", -1))

    # Enrich with sub-event & main-event names
    for b in bookings:
        sub = sub_events_col.find_one({"_id": b.get("sub_event_id")}, {"name": 1})
        me = main_events_col.find_one({"_id": b.get("main_event_id")}, {"name": 1})
        b["sub_event_name"] = sub.get("name", "") if sub else ""
        b["main_event_name"] = me.get("name", "") if me else ""

    return jsonify(serialize(bookings)), 200


@bookings_bp.route("/<booking_id>", methods=["GET"])
@jwt_required()
def get_booking(booking_id):
    uid = get_jwt_identity()
    user = users_col.find_one({"_id": ObjectId(uid)})
    query = {"_id": ObjectId(booking_id)}
    if user.get("role") == "user":
        query["user_id"] = ObjectId(uid)
    booking = bookings_col.find_one(query)
    if not booking:
        return jsonify({"error": "Booking not found"}), 404
    return jsonify(serialize(booking)), 200
