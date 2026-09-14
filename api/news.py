# Ghost rskIA — /api/news
# Calendrier économique (Forex Factory public feed) filtré, CORS ouvert.
from http.server import BaseHTTPRequestHandler
import json
import urllib.request
from datetime import datetime

FEED = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'


def parse_ts(s):
    try:
        return int(datetime.fromisoformat(str(s).replace('Z', '+00:00')).timestamp())
    except Exception:
        return None


class handler(BaseHTTPRequestHandler):

    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
        self.send_header('Cache-Control', 'public, max-age=600')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        try:
            req = urllib.request.Request(FEED, headers={'User-Agent': 'Mozilla/5.0'})
            items = json.loads(urllib.request.urlopen(req, timeout=20).read())
            out = []
            for it in items:
                imp = str(it.get('impact', '')).lower()
                if imp not in ('high', 'medium'):
                    continue
                ts = parse_ts(it.get('date', ''))
                if ts is None:
                    continue
                out.append({
                    'ts': ts,
                    'cur': it.get('country', ''),
                    'title': it.get('title', ''),
                    'high': imp == 'high',
                })
            self._send(200, out)
        except Exception as e:
            # Le client masquera simplement la bannière si ce champ existe
            self._send(200, {'error': str(e)[:200]})
