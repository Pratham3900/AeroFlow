class AuditRequestMiddleware:
    """
    Two responsibilities:

    1. (Existing) Extension point for request-scoped auditing without
       changing view signatures - core.utils.log_action still takes
       `request` explicitly wherever it's called.

    2. Browser back-button / cache protection for authenticated pages.
       Every server-side view in this project already re-checks
       authentication on every request (via @login_required /
       @staff_required / @admin_required), so a *fresh* request after
       logout is already correctly rejected. The gap this closes is the
       browser's own cache and back-forward cache (bfcache): without
       these headers, pressing Back after logout can redisplay a
       previously-rendered authenticated page straight from the
       browser's cache, without the server ever being asked again.
       Setting Cache-Control: no-store (plus the legacy headers below)
       tells the browser never to cache the response and makes the page
       ineligible for bfcache, so Back always triggers a real request
       that hits the normal login-required checks.

       Only applied when the request was made by an authenticated user,
       so public pages (login, register, marketing-style pages) are left
       cacheable as normal.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if getattr(request, "user", None) and request.user.is_authenticated:
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"

        return response
