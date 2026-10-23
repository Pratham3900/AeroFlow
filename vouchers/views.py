from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404
from django.shortcuts import render, get_object_or_404

from .models import Voucher


@login_required
def my_vouchers(request):
    vouchers = Voucher.objects.filter(passenger=request.user).select_related("booking")
    return render(request, "vouchers/list.html", {"vouchers": vouchers})


@login_required
def download_voucher(request, pk):
    voucher = get_object_or_404(Voucher, pk=pk)
    if voucher.passenger_id != request.user.id and not (request.user.is_staff_role or request.user.is_admin_role):
        raise Http404
    if not voucher.pdf_file:
        raise Http404
    response = HttpResponse(voucher.pdf_file.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="voucher_{voucher.voucher_code}.pdf"'
    return response
