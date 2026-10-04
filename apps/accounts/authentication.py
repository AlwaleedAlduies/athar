from rest_framework.authentication import SessionAuthentication

class CSRFSafeSessionAuthentication(SessionAuthentication):
    """Require CSRF even for anonymous cost-bearing AI/simulation POST requests."""
    def authenticate(self, request):
        if request.method not in {'GET', 'HEAD', 'OPTIONS', 'TRACE'}:
            self.enforce_csrf(request)
        return super().authenticate(request)
