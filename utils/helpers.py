from bson import ObjectId
import json
from datetime import datetime


def serialize(doc):
    """Recursively convert MongoDB document to JSON-serializable dict."""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize(d) for d in doc]
    if isinstance(doc, dict):
        return {k: serialize(v) for k, v in doc.items()}
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


def make_object_id(id_str):
    try:
        return ObjectId(id_str)
    except Exception:
        return None
