from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("django-admin/", admin.site.urls),

    path("", include("dashboard.urls")),
    path("accounts/", include("accounts.urls")),
    path("flights/", include("flights.urls")),
    path("bookings/", include("bookings.urls")),
    path("recovery/", include("recovery.urls")),
    path("vouchers/", include("vouchers.urls")),
    path("notifications/", include("notifications.urls")),
    path("reports/", include("reports.urls")),
    path("admin-panel/", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "core.error_views.custom_403"
handler404 = "core.error_views.custom_404"
handler500 = "core.error_views.custom_500"
