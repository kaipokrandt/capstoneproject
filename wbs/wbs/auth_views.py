import json

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

User = get_user_model()


def _json_body(request: HttpRequest) -> dict:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


@require_GET
@ensure_csrf_cookie
def csrf(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"csrfToken": get_token(request)})


@require_POST
def register(request: HttpRequest) -> JsonResponse:
    data = _json_body(request)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    email = (data.get("email") or "").strip()

    if not username or not password:
        return JsonResponse(
            {"detail": "username and password are required"},
            status=400,
        )

    if User.objects.filter(username=username).exists():
        return JsonResponse({"detail": "username already exists"}, status=409)

    user = User.objects.create_user(username=username, email=email, password=password)
    login(request, user)
    return JsonResponse(
        {
            "id": user.id,
            "username": user.get_username(),
            "email": user.email,
        },
        status=201,
    )


@require_POST
def login_view(request: HttpRequest) -> JsonResponse:
    data = _json_body(request)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return JsonResponse(
            {"detail": "username and password are required"},
            status=400,
        )

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"detail": "invalid credentials"}, status=401)

    login(request, user)
    return JsonResponse(
        {
            "id": user.id,
            "username": user.get_username(),
            "email": user.email,
        }
    )


@require_POST
def logout_view(request: HttpRequest) -> JsonResponse:
    logout(request)
    return JsonResponse({"detail": "logged out"})


@require_GET
def me(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)

    return JsonResponse(
        {
            "authenticated": True,
            "id": request.user.id,
            "username": request.user.get_username(),
            "email": request.user.email,
        }
    )
