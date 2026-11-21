from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny
from api.views.views import CreateUserView
from api.views.authentication import LoginView, LogoutView, RefreshView

from .health import health

urlpatterns = [
    path("healthz/", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/user/register/", CreateUserView.as_view(), name="register"),
    path("api/token/", LoginView.as_view(), name="get_token"),
    path("api/token/refresh/", RefreshView.as_view(), name="refresh"),
    path("api/token/logout/", LogoutView.as_view(), name="token-logout"),
    path("api-auth/", include("rest_framework.urls")),
    path("api/", include("api.urls")),
]


if not settings.PRODUCTION:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(permission_classes=[AllowAny]), name="openapi-schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="openapi-schema", permission_classes=[AllowAny]),
             name="swagger-ui"),
    ]
