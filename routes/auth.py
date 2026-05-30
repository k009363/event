from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
import bcrypt
from datetime import datetime
from bson import ObjectId
from utils.db import users_col, notifications_col
from utils.helpers import serialize

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    password = data.get("password", "")

    if not all([name, email, phone, password]):
        return jsonify({"error": "All fields are required"}), 400

    if users_col.find_one({"email": email}):
        return jsonify({"error": "Email already registered"}), 409

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = {
        "name": name,
        "email": email,
        "phone": phone,
        "password": hashed,
        "role": "user",
        "is_active": True,
        "created_at": datetime.utcnow(),
    }
    result = users_col.insert_one(user)
    user["_id"] = result.inserted_id

    try:
        notifications_col.insert_one({
            "type": "new_user",
            "message": f"New user registered: {name}",
            "created_at": datetime.utcnow(),
            "read_by": []
        })
    except Exception as e:
        print(f"Notification error: {e}")

    token = create_access_token(identity=str(result.inserted_id))
    return jsonify({
        "token": token,
        "user": serialize({k: v for k, v in user.items() if k != "password"}),
    }), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = users_col.find_one({"email": email})
    if not user or not bcrypt.checkpw(password.encode(), user["password"].encode()):
        return jsonify({"error": "Invalid email or password"}), 401

    if not user.get("is_active", True):
        return jsonify({"error": "Account is deactivated"}), 403

    token = create_access_token(identity=str(user["_id"]))
    return jsonify({
        "token": token,
        "user": serialize({k: v for k, v in user.items() if k != "password"}),
    }), 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    uid = get_jwt_identity()
    user = users_col.find_one({"_id": ObjectId(uid)})
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(serialize({k: v for k, v in user.items() if k != "password"})), 200


@auth_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    uid = get_jwt_identity()
    data = request.get_json()
    updates = {}
    for field in ["name", "phone"]:
        if data.get(field):
            updates[field] = data[field].strip()
    if data.get("password"):
        updates["password"] = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()

    users_col.update_one({"_id": ObjectId(uid)}, {"$set": updates})
    user = users_col.find_one({"_id": ObjectId(uid)})
    return jsonify(serialize({k: v for k, v in user.items() if k != "password"})), 200
