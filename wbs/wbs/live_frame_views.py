"""
Stateless live-frame relay.

POST /api/live-frame/  — bridge pushes latest parsed frame (no auth, no DB)
GET  /api/live-frame/  — browser polls latest frame (no auth required)

The frame is stored in Django's default in-memory cache under key 'live_frame'.
It expires after 10 seconds so a stale/stopped bridge shows no data.
"""
import json

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

CACHE_KEY = "live_frame"
CACHE_TTL = 10  # seconds — frame is considered stale after this


@csrf_exempt
@require_http_methods(["GET", "POST"])
def live_frame(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"detail": "invalid json"}, status=400)

        required = {"adc_base64", "gw", "gh"}
        if not required.issubset(data.keys()):
            return JsonResponse({"detail": f"missing fields: {required - data.keys()}"}, status=400)

        frame = {
            "adc_base64":  data["adc_base64"],
            "gw":          int(data["gw"]),
            "gh":          int(data["gh"]),
            "total_load":  float(data.get("total_load", 0)),
            "battery_pct": int(data.get("battery_pct", 100)),
            "ax":          int(data.get("ax", 0)),
            "ay":          int(data.get("ay", 0)),
            "az":          int(data.get("az", 0)),
            "flags":       int(data.get("flags", 0)),
        }
        cache.set(CACHE_KEY, frame, timeout=CACHE_TTL)
        return JsonResponse({"ok": True})

    # GET
    frame = cache.get(CACHE_KEY)
    if frame is None:
        return JsonResponse({"detail": "no data"}, status=404)
    return JsonResponse(frame)
