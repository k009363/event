from flask import Blueprint, Response, request
from utils.db import main_events_col, sub_events_col
from utils.helpers import serialize
import os

seo_bp = Blueprint("seo", __name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


@seo_bp.route("/sitemap.xml", methods=["GET"])
def sitemap():
    """Dynamic XML sitemap including all active main events and sub-events."""
    base = FRONTEND_URL.rstrip("/")
    from datetime import date
    today = date.today().isoformat()

    urls = [
        {"loc": f"{base}/",        "priority": "1.0", "changefreq": "weekly"},
        {"loc": f"{base}/events",  "priority": "0.9", "changefreq": "daily"},
        {"loc": f"{base}/login",   "priority": "0.3", "changefreq": "monthly"},
        {"loc": f"{base}/register","priority": "0.4", "changefreq": "monthly"},
    ]

    # Main events
    main_events = list(main_events_col.find({"is_active": True}, {"_id": 1, "name": 1}))
    for ev in main_events:
        eid = str(ev["_id"])
        urls.append({
            "loc": f"{base}/events/{eid}/sub-events",
            "priority": "0.8",
            "changefreq": "weekly",
        })

    # Sub-events
    sub_events = list(sub_events_col.find({"is_active": True}, {"_id": 1, "main_event_id": 1}))
    for sub in sub_events:
        sid = str(sub["_id"])
        mid = str(sub["main_event_id"])
        urls.append({
            "loc": f"{base}/events/{mid}/sub-events/{sid}/book",
            "priority": "0.7",
            "changefreq": "daily",
        })

    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml_lines.append(f"""  <url>
    <loc>{u['loc']}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>{u['changefreq']}</changefreq>
    <priority>{u['priority']}</priority>
  </url>""")
    xml_lines.append("</urlset>")

    return Response("\n".join(xml_lines), mimetype="application/xml")


@seo_bp.route("/robots.txt", methods=["GET"])
def robots():
    base = FRONTEND_URL.rstrip("/")
    content = f"""User-agent: *
Allow: /
Allow: /events
Allow: /events/
Disallow: /api/
Disallow: /dashboard
Disallow: /admin
Disallow: /superadmin
Disallow: /login
Disallow: /register
Sitemap: {base}/sitemap.xml
"""
    return Response(content, mimetype="text/plain")
