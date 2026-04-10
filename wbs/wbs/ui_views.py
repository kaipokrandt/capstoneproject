from django.shortcuts import redirect, render


def _require_ui_auth(request):
    if request.user.is_authenticated:
        return None
    return redirect(f"/app/login/?next={request.path}")


def app(request):
    if request.user.is_authenticated:
        return redirect("/app/dashboard/")
    return redirect("/app/login/")


def login(request):
    return render(request, "wbs/pages/login.html")


def dashboard(request):
    auth_redirect = _require_ui_auth(request)
    if auth_redirect is not None:
        return auth_redirect
    return render(request, 'wbs/pages/dashboard.html')


def patients(request):
    auth_redirect = _require_ui_auth(request)
    if auth_redirect is not None:
        return auth_redirect
    return render(request, 'wbs/pages/patients.html')


def devices(request):
    auth_redirect = _require_ui_auth(request)
    if auth_redirect is not None:
        return auth_redirect
    return render(request, 'wbs/pages/devices.html')


def sessions_live(request):
    auth_redirect = _require_ui_auth(request)
    if auth_redirect is not None:
        return auth_redirect
    return render(request, 'wbs/pages/sessions_live.html')


def sessions_compare(request):
    auth_redirect = _require_ui_auth(request)
    if auth_redirect is not None:
        return auth_redirect
    return render(request, 'wbs/pages/sessions_compare.html')


def reports(request):
    auth_redirect = _require_ui_auth(request)
    if auth_redirect is not None:
        return auth_redirect
    return render(request, 'wbs/pages/reports.html')
