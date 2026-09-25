"""Small HTTPS JSON transport with bounded responses, timeouts, and GET retries."""

import json
import time
import urllib.error
import urllib.request
from .models import ValidationError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward provider credentials to a redirected host.
        return None


def request_json(url: str, *, headers=None, payload=None, timeout=20):
    if not url.startswith("https://"):
        raise ValidationError("Provider wajib menggunakan HTTPS.")
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})})
    opener = urllib.request.build_opener(NoRedirect())
    attempts = 3 if body is None else 1
    for attempt in range(attempts):
        try:
            with opener.open(request, timeout=timeout) as response:
                data = response.read(10 * 1024 * 1024 + 1)
                if len(data) > 10 * 1024 * 1024:
                    raise ValidationError("Respons provider melebihi batas ukuran.")
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise ValidationError(f"Provider mengembalikan HTTP {exc.code}; periksa kredensial, kuota, dan akses.") from None
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise ValidationError("Koneksi atau JSON provider gagal; tidak ada fallback ke harga buatan.") from None
