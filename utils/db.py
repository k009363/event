from pymongo import MongoClient
from pymongo.uri_parser import parse_uri
from config import Config
import logging

# Use certifi's up-to-date CA bundle to fix TLS/SSL handshake errors on Linux
try:
    import certifi
    _tls_ca = certifi.where()
except ImportError:
    _tls_ca = None

client = MongoClient(
    Config.MONGO_URI,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000,
    socketTimeoutMS=20000,
    tlsCAFile=_tls_ca,              # updated CA bundle → fixes SSL handshake errors
    tlsAllowInvalidCertificates=False,  # keep certificate validation on
)

# Extract DB name from URI, fall back to "event_management"
try:
    _db_name = parse_uri(Config.MONGO_URI).get("database") or "event_management"
except Exception:
    _db_name = "event_management"

db = client[_db_name]

# Collections
users_col        = db["users"]
main_events_col  = db["main_events"]
sub_events_col   = db["sub_events"]
bookings_col     = db["bookings"]
app_settings_col = db["app_settings"]
notifications_col = db["notifications"]

# Create indexes safely — never crash the server if Atlas is slow to respond
try:
    users_col.create_index("email", unique=True)
except Exception as e:
    logging.warning(f"[db] Could not create email index: {e}")
