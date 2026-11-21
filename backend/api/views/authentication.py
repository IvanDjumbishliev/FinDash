from rest_framework.parsers import JSONParser
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from api.throttles import AuthenticationThrottle


class AuthEndpoint:
    parser_classes = [JSONParser]
    throttle_classes = [AuthenticationThrottle]


class LoginView(AuthEndpoint, TokenObtainPairView):
    pass


class RefreshView(AuthEndpoint, TokenRefreshView):
    pass


class LogoutView(AuthEndpoint, TokenBlacklistView):
    pass
