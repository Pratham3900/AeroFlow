from django import forms
from .models import RefundRequest


class RefundRequestForm(forms.ModelForm):
    class Meta:
        model = RefundRequest
        fields = ["reason", "requested_amount"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 3, "placeholder": "Tell us why you're requesting a refund..."})}


class RefundDecisionForm(forms.Form):
    STATUS_CHOICES = [
        (RefundRequest.STATUS_APPROVED, "Approve"),
        (RefundRequest.STATUS_PROCESSING, "Mark Processing"),
        (RefundRequest.STATUS_COMPLETED, "Mark Completed"),
        (RefundRequest.STATUS_REJECTED, "Reject"),
    ]
    status = forms.ChoiceField(choices=STATUS_CHOICES)
    remarks = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class RebookingDecisionForm(forms.Form):
    remarks = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
