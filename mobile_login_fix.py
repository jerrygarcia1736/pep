# mobile_login_fix.py
# Fixes iOS Safari / mobile-only 500 errors right after login.
# Mobile browsers often request extra assets immediately after login/page load:
#   /apple-touch-icon.png, /favicon.ico, /manifest.json, etc.
# If your app has aggressive redirect/onboarding logic, these can trigger crashes.
#
# This module:
#  1) Adds a defensive before_request guard for request.endpoint == None
#  2) Whitelists common mobile probe paths
#  3) Provides SAFE icon/manifest routes that return 204 if files are missing (never 500)

from flask import request, send_from_directory, Response

MOBILE_PROBE_PATHS = {
    "/favicon.ico",
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
    "/site.webmanifest",
    "/manifest.json",
    "/robots.txt",
}

def _safe_static(filename: str) -> Response:
    """Serve a static asset if present; otherwise return 204 (no content).
    We intentionally do NOT raise, to prevent any misconfigured error handlers from turning it into a 500.
    """
    try:
        return send_from_directory("static", filename)
    except Exception:
        return Response("", status=204)

def register_mobile_login_fixes(app):
    @app.before_request
    def _mobile_probe_guard():
        # When a request doesn't match any route, endpoint can be None.
        # Some apps crash if they assume endpoint is a string.
        if request.endpoint is None:
            return None

        # Always allow static files
        if request.endpoint == "static":
            return None

        # Allow known mobile probe paths
        if request.path in MOBILE_PROBE_PATHS:
            return None

        return None

    # Safe asset routes
    @app.get("/apple-touch-icon.png")
    def apple_touch_icon():
        return _safe_static("apple-touch-icon.png")

    @app.get("/apple-touch-icon-precomposed.png")
    def apple_touch_icon_precomposed():
        # iOS sometimes requests this older name
        return _safe_static("apple-touch-icon.png")

    @app.get("/favicon.ico")
    def favicon():
        return _safe_static("favicon.ico")

    @app.get("/site.webmanifest")
    def site_webmanifest():
        return _safe_static("site.webmanifest")

    @app.get("/manifest.json")
    def manifest_json():
        return _safe_static("manifest.json")

    @app.get("/robots.txt")
    def robots_txt():
        return _safe_static("robots.txt")
