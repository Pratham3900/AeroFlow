from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def notification_list(request):
    notifications = request.user.notifications.all()
    return render(request, "notifications/list.html", {"notifications": notifications})


@login_required
@require_POST
def mark_read(request, pk):
    """AJAX endpoint: mark a single notification as read."""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    return JsonResponse({"success": True, "unread_count": request.user.notifications.filter(is_read=False).count()})


@login_required
@require_POST
def mark_all_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return JsonResponse({"success": True})
