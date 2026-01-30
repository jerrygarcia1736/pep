# mobile_login_fix.py
# Fixes iOS Safari / mobile-only 500 errors right after login
# Caused by missing endpoints like:
# /apple-touch-icon.png, /favicon.ico, /manifest.json, etc.

from flask import request, send_from_directory

# Common extra paths requested by mobile browsers immediately after login/page load
MOBILE_PROBE_PATHS = {
    "/favicon.ico",
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
    "/site.webmanifest",
    "/manifest.json",
}


def register_mobile_login_fixes(app):
    """
    Register guards to prevent mobile-only Internal Server Errors.

    Usage in app.py:
        from mobile_login_fix import register_mobile_login_fixes
        register_mobile_login_fixes(app)
    """

    @app.before_request
    def _mobile_probe_guard():
        # request.endpoint can be None for missing/static mobile probe paths
        if request.endpoint is None:
            return None

        # Always allow static files
        if request.endpoint == "static":
            return None

        # Allow known mobile probe paths
        if request.path in MOBILE_PROBE_PATHS:
            return None

        return None

    # Optional: Serve these assets if present in /static
    @app.get("/apple-touch-icon.png")
    def apple_touch_icon():
        return send_from_directory("static", "apple-touch-icon.png")

    @app.get("/apple-touch-icon-precomposed.png")
    def apple_touch_icon_precomposed():
        return send_from_directory("static", "apple-touch-icon.png")

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory("static", "favicon.ico")

    @app.get("/site.webmanifest")
    def site_webmanifest():
        return send_from_directory("static", "site.webmanifest")

    @app.get("/manifest.json")
    def manifest_json():
        return send_from_directory("static", "manifest.json")
