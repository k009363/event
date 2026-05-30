from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime, timedelta
from utils.db import (
    users_col, main_events_col, sub_events_col, bookings_col
)
from utils.helpers import serialize
from utils.cloudinary_utils import upload_image
from utils.email_utils import build_whatsapp_link

admin_bp = Blueprint("admin", __name__)


def require_admin_or_superadmin():
    uid = get_jwt_identity()
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user or user.get("role") not in ("admin", "super_admin"):
        return None, jsonify({"error": "Unauthorized"}), 403
    return user, None, None


# ─── Dashboard ───────────────────────────────────────────────────────────────

@admin_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def dashboard():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code

    if user["role"] == "super_admin":
        main_event_ids = [e["_id"] for e in main_events_col.find({}, {"_id": 1})]
    else:
        assigned = user.get("assigned_event")
        main_event_ids = [assigned] if assigned else []

    total_bookings = bookings_col.count_documents({"main_event_id": {"$in": main_event_ids}})
    pending = bookings_col.count_documents({"main_event_id": {"$in": main_event_ids}, "status": "pending"})
    confirmed = bookings_col.count_documents({"main_event_id": {"$in": main_event_ids}, "status": "confirmed"})
    sub_event_count = sub_events_col.count_documents({"main_event_id": {"$in": main_event_ids}})

    return jsonify({
        "total_bookings": total_bookings,
        "pending_bookings": pending,
        "confirmed_bookings": confirmed,
        "sub_event_count": sub_event_count,
    }), 200


# ─── Dashboard Chart ─────────────────────────────────────────────────────────

@admin_bp.route("/dashboard/chart", methods=["GET"])
@jwt_required()
def dashboard_chart():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code

    days      = int(request.args.get("days", 7))
    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")

    today = datetime.utcnow().date()
    if date_from and date_to:
        start_str = date_from
        end_str   = date_to
    else:
        end_str   = today.strftime("%Y-%m-%d")
        start_str = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(end_str,   "%Y-%m-%d").date()
    date_range = []
    cur = start_dt
    while cur <= end_dt:
        date_range.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    is_superadmin = user["role"] == "super_admin"

    if is_superadmin:
        # Per-event breakdown — group by date + main_event_id
        pipeline = [
            {"$match": {"booking_date": {"$gte": start_str, "$lte": end_str}}},
            {"$group": {
                "_id": {"date": "$booking_date", "event_id": "$main_event_id"},
                "count": {"$sum": 1},
                "revenue": {"$sum": "$final_cost"},
            }},
            {"$sort": {"_id.date": 1}},
        ]
        rows = list(bookings_col.aggregate(pipeline))

        # Build event name lookup
        event_ids = {r["_id"]["event_id"] for r in rows if r["_id"].get("event_id")}
        name_map = {}
        for eid in event_ids:
            ev = main_events_col.find_one({"_id": eid}, {"name": 1})
            name_map[str(eid)] = ev["name"] if ev else str(eid)

        # Index rows by (date, event_name)
        raw = {}  # date -> {event_name: {count, revenue}}
        for r in rows:
            ds = r["_id"]["date"]
            eid = str(r["_id"].get("event_id", ""))
            ev_name = name_map.get(eid, "Unknown")
            raw.setdefault(ds, {})[ev_name] = {
                "count": r["count"],
                "revenue": round(r["revenue"], 2),
            }

        event_names = sorted(name_map.values())

        chart = []
        for ds in date_range:
            entry = {"date": ds}
            day_data = raw.get(ds, {})
            for ev_name in event_names:
                entry[ev_name + "_count"]   = day_data.get(ev_name, {}).get("count", 0)
                entry[ev_name + "_revenue"] = day_data.get(ev_name, {}).get("revenue", 0)
            chart.append(entry)

        return jsonify({
            "data": chart,
            "events": event_names,
            "start": start_str,
            "end": end_str,
            "is_superadmin": True,
        }), 200

    else:
        # Admin: only their assigned event
        assigned = user.get("assigned_event")
        base_q = {"main_event_id": assigned} if assigned else {"main_event_id": None}

        pipeline = [
            {"$match": {**base_q, "booking_date": {"$gte": start_str, "$lte": end_str}}},
            {"$group": {"_id": "$booking_date", "count": {"$sum": 1},
                        "revenue": {"$sum": "$final_cost"}}},
            {"$sort": {"_id": 1}},
        ]
        raw = {r["_id"]: r for r in bookings_col.aggregate(pipeline)}

        chart = [
            {"date": ds, "count": raw.get(ds, {}).get("count", 0),
             "revenue": round(raw.get(ds, {}).get("revenue", 0), 2)}
            for ds in date_range
        ]

        return jsonify({
            "data": chart,
            "events": [],
            "start": start_str,
            "end": end_str,
            "is_superadmin": False,
        }), 200


# ─── Main Event (admin updates their mapped event) ───────────────────────────

@admin_bp.route("/main-event", methods=["GET"])
@jwt_required()
def get_mapped_main_event():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code
    assigned = user.get("assigned_event")
    if not assigned:
        return jsonify({"error": "No event assigned"}), 404
    event = main_events_col.find_one({"_id": assigned})
    return jsonify(serialize(event)), 200


@admin_bp.route("/main-event", methods=["PUT"])
@jwt_required()
def update_mapped_main_event():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code
    assigned = user.get("assigned_event")
    if not assigned:
        return jsonify({"error": "No event assigned"}), 404

    data = request.get_json()
    allowed = ["name", "address", "map_location", "contact_no", "email",
               "website", "description", "images", "is_active"]
    updates = {k: data[k] for k in allowed if k in data}
    updates["updated_at"] = datetime.utcnow()
    main_events_col.update_one({"_id": assigned}, {"$set": updates})
    return jsonify({"message": "Updated"}), 200


@admin_bp.route("/main-event/upload-image", methods=["POST"])
@jwt_required()
def upload_main_event_image():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    url = upload_image(request.files["image"], folder="main_events")
    return jsonify({"url": url}), 200


# ─── Sub Events ──────────────────────────────────────────────────────────────

@admin_bp.route("/sub-events", methods=["GET"])
@jwt_required()
def list_sub_events():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code

    if user["role"] == "super_admin":
        main_event_id_param = request.args.get("main_event_id")
        if main_event_id_param and ObjectId.is_valid(main_event_id_param):
            query = {"main_event_id": ObjectId(main_event_id_param)}
        else:
            query = {}
    else:
        assigned = user.get("assigned_event")
        query = {"main_event_id": assigned} if assigned else {"main_event_id": None}

    subs = list(sub_events_col.find(query).sort("created_at", -1))
    return jsonify(serialize(subs)), 200


@admin_bp.route("/sub-events", methods=["POST"])
@jwt_required()
def create_sub_event():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code

    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    if user["role"] == "super_admin":
        main_event_id = data.get("main_event_id")
        if not main_event_id or not ObjectId.is_valid(main_event_id):
            return jsonify({"error": "main_event_id required for super admin"}), 400
        main_oid = ObjectId(main_event_id)
    else:
        main_oid = user.get("assigned_event")
        if not main_oid:
            return jsonify({"error": "No event assigned"}), 400

    # Validate no duplicate time slots
    slots = data.get("time_slots", [])
    seen = set()
    for s in slots:
        key = (s.get("start_time"), s.get("end_time"))
        if key in seen:
            return jsonify({"error": f"Duplicate time slot: {key}"}), 400
        seen.add(key)

    sub = {
        "main_event_id": main_oid,
        "name": name,
        "description": data.get("description", ""),
        "cost_type": data.get("cost_type", "single"),
        "cost": data.get("cost", 0),
        "cost_min": data.get("cost_min", 0),
        "cost_max": data.get("cost_max", 0),
        "images": data.get("images", []),
        "event_type": data.get("event_type", "indoor"),
        "time_slots": slots,
        "is_active": True,
        "created_at": datetime.utcnow(),
    }
    result = sub_events_col.insert_one(sub)
    sub["_id"] = result.inserted_id
    return jsonify(serialize(sub)), 201


@admin_bp.route("/sub-events/<sub_id>", methods=["PUT"])
@jwt_required()
def update_sub_event(sub_id):
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code

    sub_oid = ObjectId(sub_id) if ObjectId.is_valid(sub_id) else None
    sub = sub_events_col.find_one({"_id": sub_oid})
    if not sub:
        return jsonify({"error": "Not found"}), 404

    if user["role"] != "super_admin" and sub.get("main_event_id") != user.get("assigned_event"):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    allowed = ["name", "description", "cost_type", "cost", "cost_min", "cost_max",
               "images", "event_type", "time_slots", "is_active"]
    updates = {k: data[k] for k in allowed if k in data}

    if "time_slots" in updates:
        seen = set()
        for s in updates["time_slots"]:
            key = (s.get("start_time"), s.get("end_time"))
            if key in seen:
                return jsonify({"error": f"Duplicate time slot: {key}"}), 400
            seen.add(key)

    updates["updated_at"] = datetime.utcnow()
    sub_events_col.update_one({"_id": sub_oid}, {"$set": updates})
    return jsonify({"message": "Updated"}), 200


@admin_bp.route("/sub-events/<sub_id>", methods=["DELETE"])
@jwt_required()
def delete_sub_event(sub_id):
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code
    sub_oid = ObjectId(sub_id) if ObjectId.is_valid(sub_id) else None
    sub_events_col.update_one({"_id": sub_oid}, {"$set": {"is_active": False}})
    return jsonify({"message": "Deleted"}), 200


@admin_bp.route("/sub-events/<sub_id>/upload-image", methods=["POST"])
@jwt_required()
def upload_sub_event_image(sub_id):
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    url = upload_image(request.files["image"], folder="sub_events")
    # Append to sub event images
    sub_oid = ObjectId(sub_id) if ObjectId.is_valid(sub_id) else None
    sub_events_col.update_one({"_id": sub_oid}, {"$push": {"images": url}})
    return jsonify({"url": url}), 200


# ─── Bookings ────────────────────────────────────────────────────────────────

@admin_bp.route("/bookings", methods=["GET"])
@jwt_required()
def list_bookings():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code

    status_filter = request.args.get("status")
    date_from     = request.args.get("date_from")   # YYYY-MM-DD
    date_to       = request.args.get("date_to")     # YYYY-MM-DD

    if user["role"] == "super_admin":
        query = {}
    else:
        assigned = user.get("assigned_event")
        query = {"main_event_id": assigned} if assigned else {"main_event_id": None}

    if status_filter:
        query["status"] = status_filter

    if date_from or date_to:
        date_q = {}
        if date_from: date_q["$gte"] = date_from
        if date_to:   date_q["$lte"] = date_to
        query["booking_date"] = date_q

    bookings = list(bookings_col.find(query).sort("booking_date", -1))

    # Enrich
    for b in bookings:
        sub = sub_events_col.find_one({"_id": b.get("sub_event_id")}, {"name": 1})
        me = main_events_col.find_one({"_id": b.get("main_event_id")}, {"name": 1, "contact_no": 1})
        b["sub_event_name"] = sub.get("name", "") if sub else ""
        b["main_event_name"] = me.get("name", "") if me else ""
        b["main_event_contact"] = me.get("contact_no", "") if me else ""

        contact = me.get("contact_no", "") if me else ""
        b["whatsapp_link"] = build_whatsapp_link(
            contact, b, b.get("user_details", {}),
            b.get("sub_event_name", ""), b.get("main_event_name", "")
        )

    return jsonify(serialize(bookings)), 200


@admin_bp.route("/bookings/<booking_id>/status", methods=["PUT"])
@jwt_required()
def update_booking_status(booking_id):
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code
    data = request.get_json()
    status = data.get("status")
    valid_statuses = ["pending", "confirmed", "cancelled", "completed", "visited"]
    if status not in valid_statuses:
        return jsonify({"error": f"Status must be one of {valid_statuses}"}), 400

    b_oid = ObjectId(booking_id) if ObjectId.is_valid(booking_id) else None
    bookings_col.update_one({"_id": b_oid}, {"$set": {"status": status, "updated_at": datetime.utcnow()}})
    return jsonify({"message": "Status updated"}), 200


# ─── Admin Reports (Pro plan only) ───────────────────────────────────────────

@admin_bp.route("/reports", methods=["GET"])
@jwt_required()
def admin_reports():
    user, err, code = require_admin_or_superadmin()
    if err:
        return err, code

    # Super-admin always allowed; admin needs 'reports' permission
    if user["role"] == "admin" and "reports" not in user.get("permissions", []):
        return jsonify({"error": "You do not have permission to access reports"}), 403

    date_from      = request.args.get("date_from", "")
    date_to        = request.args.get("date_to",   "")
    main_event_id  = request.args.get("main_event_id", "")   # super_admin filter by event
    admin_id_param = request.args.get("admin_id",      "")   # super_admin filter by admin

    # Build base query
    if user["role"] == "super_admin":
        if main_event_id and ObjectId.is_valid(main_event_id):
            base_q = {"main_event_id": ObjectId(main_event_id)}
        elif admin_id_param and ObjectId.is_valid(admin_id_param):
            # Look up the admin's assigned event
            target_admin = users_col.find_one({"_id": ObjectId(admin_id_param)}, {"assigned_event": 1})
            assigned = target_admin.get("assigned_event") if target_admin else None
            base_q = {"main_event_id": assigned} if assigned else {"main_event_id": None}
        else:
            base_q = {}   # all events
    else:
        assigned = user.get("assigned_event")
        base_q = {"main_event_id": assigned} if assigned else {"main_event_id": None}

    if date_from and date_to:
        base_q["booking_date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        base_q["booking_date"] = {"$gte": date_from}
    elif date_to:
        base_q["booking_date"] = {"$lte": date_to}

    # ── Sub-event wise ────────────────────────────────────────────────────────
    sub_pipeline = [
        {"$match": base_q},
        {"$group": {
            "_id": "$sub_event_id",
            "count":        {"$sum": 1},
            "total_amount": {"$sum": "$final_cost"},
        }},
        {"$sort": {"total_amount": -1}},
    ]
    sub_rows = list(bookings_col.aggregate(sub_pipeline))

    sub_wise = []
    for r in sub_rows:
        sub = sub_events_col.find_one({"_id": r["_id"]}, {"name": 1})
        sub_wise.append({
            "sub_event_name": sub["name"] if sub else "Unknown",
            "count":          r["count"],
            "total_amount":   round(r["total_amount"], 2),
        })

    # ── Date wise ─────────────────────────────────────────────────────────────
    date_pipeline = [
        {"$match": base_q},
        {"$group": {
            "_id":          "$booking_date",
            "count":        {"$sum": 1},
            "total_amount": {"$sum": "$final_cost"},
        }},
        {"$sort": {"_id": 1}},
    ]
    date_rows = list(bookings_col.aggregate(date_pipeline))
    date_wise = [
        {"date": r["_id"], "count": r["count"], "total_amount": round(r["total_amount"], 2)}
        for r in date_rows
    ]

    grand_count  = sum(r["count"]        for r in sub_wise)
    grand_amount = round(sum(r["total_amount"] for r in sub_wise), 2)

    # ── Matrix (sub-event × date cross-tab) ───────────────────────────────────
    matrix_pipeline = [
        {"$match": base_q},
        {"$group": {
            "_id": {"sub_event_id": "$sub_event_id", "date": "$booking_date"},
            "count":        {"$sum": 1},
            "total_amount": {"$sum": "$final_cost"},
        }},
    ]
    matrix_rows = list(bookings_col.aggregate(matrix_pipeline))

    # Pivot into per-row cells keyed by date
    # Preserve sub-event row order from sub_wise (sorted by total_amount desc)
    cells_by_sub = {}   # sub_event_id_str -> {date: {count, total_amount}}
    for r in matrix_rows:
        sid = str(r["_id"]["sub_event_id"])
        cells_by_sub.setdefault(sid, {})[r["_id"]["date"]] = {
            "count":        r["count"],
            "total_amount": round(r["total_amount"], 2),
        }

    # Build sub-event name lookup in the same order as sub_wise (uses sub_rows _id)
    sub_id_order = [str(r["_id"]) for r in sub_rows]
    sub_name_lookup = {str(r["_id"]): sw["sub_event_name"] for r, sw in zip(sub_rows, sub_wise)}

    matrix_dates = sorted({r["_id"]["date"] for r in matrix_rows})

    matrix_built_rows = []
    for sid in sub_id_order:
        cells = cells_by_sub.get(sid, {})
        row_count  = sum(c["count"]        for c in cells.values())
        row_amount = round(sum(c["total_amount"] for c in cells.values()), 2)
        matrix_built_rows.append({
            "sub_event_name": sub_name_lookup.get(sid, "Unknown"),
            "cells":          cells,
            "row_count":      row_count,
            "row_amount":     row_amount,
        })

    # Column totals — keyed by date
    col_totals = {}
    for d in matrix_dates:
        c_sum = 0
        a_sum = 0.0
        for sid in sub_id_order:
            cell = cells_by_sub.get(sid, {}).get(d)
            if cell:
                c_sum += cell["count"]
                a_sum += cell["total_amount"]
        col_totals[d] = {"count": c_sum, "total_amount": round(a_sum, 2)}

    matrix = {
        "dates":      matrix_dates,
        "rows":       matrix_built_rows,
        "col_totals": col_totals,
    }

    # ── Top stats (derived from existing aggregates — no extra DB call) ───────
    top_stats = {
        "top_sub_by_count":   max(sub_wise,  key=lambda r: r["count"],        default=None),
        "top_sub_by_amount":  sub_wise[0] if sub_wise else None,  # already sorted by amount desc
        "top_date_by_count":  max(date_wise, key=lambda r: r["count"],        default=None),
        "top_date_by_amount": max(date_wise, key=lambda r: r["total_amount"], default=None),
    }

    # Resolve display label for the selected filter
    context_label = ""
    if user["role"] == "super_admin":
        if main_event_id and ObjectId.is_valid(main_event_id):
            me = main_events_col.find_one({"_id": ObjectId(main_event_id)}, {"name": 1})
            context_label = me["name"] if me else ""
        elif admin_id_param and ObjectId.is_valid(admin_id_param):
            adm = users_col.find_one({"_id": ObjectId(admin_id_param)}, {"name": 1})
            context_label = f"Admin: {adm['name']}" if adm else ""

    return jsonify({
        "sub_wise":      sub_wise,
        "date_wise":     date_wise,
        "matrix":        matrix,
        "top_stats":     top_stats,
        "grand_count":   grand_count,
        "grand_amount":  grand_amount,
        "date_from":     date_from,
        "date_to":       date_to,
        "context_label": context_label,
    }), 200
