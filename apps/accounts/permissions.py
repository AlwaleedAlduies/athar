from rest_framework.permissions import BasePermission, SAFE_METHODS


def is_admin(user):
    return user.is_authenticated and user.is_admin


class AdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or is_admin(request.user)


class AdminOnly(BasePermission):
    def has_permission(self, request, view):
        return is_admin(request.user)


def api_exception_handler(exc, context):
    from rest_framework.views import exception_handler
    response = exception_handler(exc, context)
    if response is not None:
        response.data = {'error': response.data, 'status': response.status_code}
    return response
