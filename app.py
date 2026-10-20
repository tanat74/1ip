"""IP info service.

Shows the client's public IP address and its geolocation.

The service is a single-file HTTP server built on the Python standard
library only. It resolves the real client IP behind a trusted reverse
proxy (via ``X-Forwarded-For``), looks up geolocation data from
https://ipwho.is and caches the result.
"""

import html
import ipaddress
import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

PORT = int(os.getenv("PORT", "8085"))

# Networks that are allowed to set X-Forwarded-For. Only the first
# untrusted address in the chain is trusted as the real client IP.
TRUSTED = [
    ipaddress.ip_network(x.strip(), strict=False)
    for x in os.getenv("TRUSTED_PROXY", "").split(",")
    if x.strip()
]

# How long a successful geolocation lookup is cached, in seconds.
TTL = int(os.getenv("GEO_CACHE_TTL", "3600"))

# Timeout for the upstream geolocation request, in seconds.
TIMEOUT = float(os.getenv("GEO_TIMEOUT", "5"))

GEO_API_URL = "https://ipwho.is/"
USER_AGENT = "IP-Info-Service/1.0"

# How long a failed lookup is cached, in seconds (avoids hammering the
# upstream on every request for the same bad IP).
ERROR_TTL = 60

cache = {}
lock = Lock()


def is_trusted(ip):
    """Return True if ``ip`` belongs to one of the trusted networks."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in TRUSTED)


def client_ip(handler):
    """Resolve the real client IP for a request.

    If the peer is not a trusted proxy, its address is used as-is.
    Otherwise the ``X-Forwarded-For`` chain is walked from right to left
    and the first untrusted address is returned.
    """
    peer = handler.client_address[0]

    if not is_trusted(peer):
        return peer

    forwarded = handler.headers.get("X-Forwarded-For", "")

    if not forwarded:
        return peer

    chain = [
        x.strip()
        for x in forwarded.split(",")
        if x.strip()
    ]

    chain.append(peer)

    for address in reversed(chain):
        try:
            ipaddress.ip_address(address)
        except ValueError:
            return peer

        if not is_trusted(address):
            return address

    return chain[0]


def fetch_geo(ip):
    """Fetch geolocation data for ``ip`` from the upstream API.

    Returns the parsed JSON payload on success, or None on any error.
    """
    address = ipaddress.ip_address(ip)

    if not address.is_global:
        raise ValueError("Private IP")

    req = urllib.request.Request(
        GEO_API_URL + ip,
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        result = json.load(response)

    if result.get("success"):
        return result

    return None


def get_geo(ip):
    """Return cached geolocation data for ``ip``, fetching it if needed."""
    now = time.time()

    with lock:
        item = cache.get(ip)
        if item and now - item[0] < item[2]:
            return item[1]

    data = None
    lifetime = ERROR_TTL

    try:
        data = fetch_geo(ip)
        if data is not None:
            lifetime = TTL
    except Exception as exc:  # noqa: BLE001 - report and keep serving
        print("GeoIP error:", ip, str(exc), flush=True)

    with lock:
        cache[ip] = (time.time(), data, lifetime)

    return data


def clear_cache():
    """Drop all cached geolocation entries (used by tests)."""
    with lock:
        cache.clear()


STYLE = """
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #111827;
    color: white;
    font-family: Arial, sans-serif;
}

.content {
    width: 100%;
    max-width: 900px;
    padding: 30px 20px;
    text-align: center;
}

.label {
    color: #9ca3af;
    font-size: 22px;
    margin-bottom: 20px;
}

.ip-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 15px;
    margin-bottom: 35px;
}

.ip {
    font-size: clamp(32px, 7vw, 85px);
    font-weight: bold;
    overflow-wrap: anywhere;
    min-width: 0;
}

.copy-btn {
    flex-shrink: 0;
    background: #1f2937;
    color: #d1d5db;
    border: 1px solid #374151;
    border-radius: 12px;
    padding: 12px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.2s, color 0.2s;
}

.copy-btn:hover {
    background: #374151;
    color: white;
}

.copy-btn:active {
    transform: scale(0.95);
}

.copy-btn svg {
    width: 24px;
    height: 24px;
}

.copy-btn.copied {
    color: #4ade80;
    border-color: #166534;
}

.geo {
    width: 100%;
    max-width: 450px;
    margin: auto;
    text-align: left;
}

.row {
    display: flex;
    justify-content: space-between;
    gap: 20px;
    padding: 12px 0;
    border-bottom: 1px solid #374151;
}

.name {
    color: #9ca3af;
}

.value {
    font-weight: 600;
    text-align: right;
    overflow-wrap: anywhere;
}

.error {
    color: #9ca3af;
    text-align: center;
}

@media (max-width: 600px) {
    .ip-wrap {
        gap: 10px;
    }

    .copy-btn {
        padding: 10px;
    }

    .copy-btn svg {
        width: 20px;
        height: 20px;
    }

    .row {
        gap: 12px;
    }
}
"""

SCRIPT = """
<script>
let copyTimer;

async function copyIP() {
    const ip = document.getElementById('ip').textContent;
    const btn = document.getElementById('copy-btn');
    const icon = document.getElementById('copy-icon');

    const copySvg = icon.innerHTML;

    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(ip);
        } else {
            const area = document.createElement('textarea');
            area.value = ip;
            area.style.position = 'fixed';
            area.style.opacity = '0';

            document.body.appendChild(area);
            area.focus();
            area.select();

            const ok = document.execCommand('copy');
            area.remove();

            if (!ok) {
                throw new Error('Copy failed');
            }
        }

        clearTimeout(copyTimer);

        icon.innerHTML = '<path d="M20 6 9 17l-5-5"/>';
        btn.classList.add('copied');
        btn.title = 'Скопировано!';
        btn.setAttribute('aria-label', 'Скопировано');

        copyTimer = setTimeout(() => {
            icon.innerHTML = copySvg;
            btn.classList.remove('copied');
            btn.title = 'Копировать IP';
            btn.setAttribute('aria-label', 'Копировать IP');
        }, 2000);

    } catch (error) {
        console.error('Copy error:', error);
        btn.title = 'Не удалось скопировать';
    }
}
</script>
"""


def esc(value):
    """HTML-escape a value, rendering empty values as an em dash."""
    return html.escape(str(value or "—"))


def render(ip, data):
    """Render the HTML page for ``ip`` with optional geolocation ``data``."""
    rows = []

    if data:
        conn = data.get("connection") or {}
        flag = data.get("flag") or {}

        fields = [
            (
                "Страна",
                str(flag.get("emoji") or "") + " " +
                str(data.get("country") or "—"),
            ),
            ("Регион", data.get("region")),
            ("Город", data.get("city")),
            ("Провайдер", conn.get("isp")),
            ("Организация", conn.get("org")),
            (
                "ASN",
                "AS" + str(conn["asn"]) if conn.get("asn") else "—",
            ),
        ]

        for name, value in fields:
            rows.append(
                '<div class="row">'
                '<span class="name">' + esc(name) + '</span>'
                '<span class="value">' + esc(value) + '</span>'
                '</div>'
            )

    else:
        rows.append(
            '<div class="error">'
            'Геоданные временно недоступны'
            '</div>'
        )

    return (
        '<!DOCTYPE html>'
        '<html lang="ru">'
        '<head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" '
        'content="width=device-width,initial-scale=1">'
        '<title>Мой IP</title>'
        '<style>' + STYLE + '</style>'
        '</head>'
        '<body>'
        '<main class="content">'

        '<div class="label">Ваш IP-адрес</div>'

        '<div class="ip-wrap">'
        '<div class="ip" id="ip">' + esc(ip) + '</div>'

        '<button '
        'type="button" '
        'class="copy-btn" '
        'id="copy-btn" '
        'onclick="copyIP()" '
        'title="Копировать IP" '
        'aria-label="Копировать IP">'

        '<svg id="copy-icon" '
        'xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 24 24" '
        'fill="none" '
        'stroke="currentColor" '
        'stroke-width="2" '
        'stroke-linecap="round" '
        'stroke-linejoin="round">'

        '<rect x="8" y="8" width="13" height="13" rx="2"/>'
        '<path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>'

        '</svg>'
        '</button>'
        '</div>'

        '<div class="geo">' + "".join(rows) + '</div>'

        '</main>'
        + SCRIPT +
        '</body>'
        '</html>'
    )


class Handler(BaseHTTPRequestHandler):
    """HTTP handler serving the IP page and a plain-text /api endpoint."""

    def do_GET(self):
        ip = client_ip(self)

        if self.path == "/api":
            body = (ip + "\n").encode()
            content_type = "text/plain; charset=utf-8"
        else:
            data = get_geo(ip)
            body = render(ip, data).encode("utf-8")
            content_type = "text/html; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        # Keep the default access log but route it through print so it
        # shows up in `docker logs` without the default stderr formatting.
        print("%s - %s" % (self.address_string(), format % args), flush=True)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("IP API started on port", PORT, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
