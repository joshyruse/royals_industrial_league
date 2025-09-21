from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.views.generic import RedirectView

from league.views import healthz
from league import views as league_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("league.urls")),
    path("login/", auth_views.LoginView.as_view(template_name="league/login.html"), name="league_login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("healthz", healthz, name="healthz"),
    path("accounts/login/", RedirectView.as_view(pattern_name="league_login", permanent=False)),
    path("accounts/", include("django.contrib.auth.urls")),
    # Explicit password reset routes (ensure names exist for email templates)
    path("password_reset/", league_views.ThemedPasswordResetView.as_view(
        template_name="account/password_reset.html",
        email_template_name="emails/password_reset.html",
        subject_template_name="emails/password_reset_subject.txt"
    ), name="password_reset"),
    path("password_reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="account/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", league_views.ThemedPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(template_name="account/password_reset_complete.html"), name="password_reset_complete"),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path("__debug__/", include(debug_toolbar.urls)),
    ]
