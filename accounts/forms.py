from django import forms
from django.contrib.auth import authenticate
from .models import User
from . import mfa as mfa_utils


class LoginForm(forms.Form):
    username = forms.CharField(max_length=100)
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        self._user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        username = cleaned.get('username')
        password = cleaned.get('password')

        if username and password:
            # Check if account is locked before even trying auth
            try:
                user = User.objects.get(username=username)
                if user.is_locked():
                    raise forms.ValidationError(
                        "Account is temporarily locked due to too many failed attempts. Try again later."
                    )
            except User.DoesNotExist:
                pass

            user = authenticate(self.request, username=username, password=password)
            if user is None:
                # Record the failure
                try:
                    u = User.objects.get(username=username)
                    u.record_failed_login()
                except User.DoesNotExist:
                    pass
                raise forms.ValidationError("Invalid username or password.")

            if not user.is_active:
                raise forms.ValidationError("This account has been deactivated.")

            self._user = user
        return cleaned

    def get_user(self):
        return self._user


class MFAVerifyForm(forms.Form):
    code = forms.CharField(
        max_length=6,
        min_length=6,
        label="6-digit code",
        widget=forms.TextInput(attrs={'autocomplete': 'one-time-code', 'inputmode': 'numeric'}),
    )

    def __init__(self, *args, secret=None, **kwargs):
        self.secret = secret
        super().__init__(*args, **kwargs)

    def clean_code(self):
        code = self.cleaned_data['code'].strip()
        if not mfa_utils.verify_totp(self.secret, code):
            raise forms.ValidationError("Invalid code. Make sure your device clock is correct.")
        return code


class MFASetupForm(forms.Form):
    """Confirm the user can produce a valid code before we enable MFA."""
    code = forms.CharField(max_length=6, min_length=6, label="Enter the code from your app")

    def __init__(self, *args, secret=None, **kwargs):
        self.secret = secret
        super().__init__(*args, **kwargs)

    def clean_code(self):
        code = self.cleaned_data['code'].strip()
        if not mfa_utils.verify_totp(self.secret, code):
            raise forms.ValidationError("Code doesn't match. Scan the QR code again.")
        return code


class ReauthForm(forms.Form):
    """Re-enter password before signing a record (required for e-signatures)."""
    password = forms.CharField(widget=forms.PasswordInput, label="Re-enter your password to confirm")

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data['password']
        if not self.user.check_password(password):
            raise forms.ValidationError("Incorrect password.")
        return password


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput, label="Current password")
    new_password = forms.CharField(
        widget=forms.PasswordInput, label="New password",
        min_length=12,
        help_text="Minimum 12 characters.",
    )
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm new password")

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        pw = self.cleaned_data['current_password']
        if not self.user.check_password(pw):
            raise forms.ValidationError("Current password is incorrect.")
        return pw

    def clean(self):
        cleaned = super().clean()
        new_pw = cleaned.get('new_password')
        confirm = cleaned.get('confirm_password')
        if new_pw and confirm and new_pw != confirm:
            raise forms.ValidationError("New passwords do not match.")
        return cleaned
