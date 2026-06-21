import html
import socket
import threading
import time
import webbrowser
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import webview


APP_TITLE = "Shreeji Auto Service - Admin Panel"
HOST = "127.0.0.1"
HEALTH_PATH = "/health"
START_PATH = "/admin"
SERVER_START_TIMEOUT_SECONDS = 12


class DesktopAPI:
    def open_external(self, url):
        webbrowser.open(url)


LOADING_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      color-scheme: light;
      --brand: #a20405;
      --ink: #1f2933;
      --muted: #6b7280;
      --panel: #ffffff;
      --bg: #f6f7f9;
      --line: #e5e7eb;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
    }

    .panel {
      width: min(420px, calc(100vw - 40px));
      display: grid;
      gap: 18px;
      justify-items: center;
      padding: 36px 42px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
      text-align: center;
    }

    .spinner {
      width: 42px;
      height: 42px;
      border: 4px solid var(--line);
      border-top-color: var(--brand);
      border-radius: 50%;
      animation: spin 0.9s linear infinite;
    }

    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0;
    }

    p {
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }

    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
  </style>
</head>
<body>
  <main class="panel" role="status" aria-live="polite">
    <div class="spinner" aria-hidden="true"></div>
    <h1>Starting Shreeji Admin...</h1>
    <p>Preparing the desktop dashboard</p>
  </main>
</body>
</html>
"""


def build_error_html(message):
    escaped_message = html.escape(str(message))
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #f6f7f9;
      color: #1f2933;
      font-family: "Segoe UI", Arial, sans-serif;
    }}

    .panel {{
      width: min(560px, calc(100vw - 40px));
      padding: 34px 38px;
      background: #fff;
      border: 1px solid #fecaca;
      border-radius: 8px;
      box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
    }}

    h1 {{
      margin: 0 0 12px;
      color: #991b1b;
      font-size: 22px;
      letter-spacing: 0;
    }}

    p {{
      margin: 0;
      color: #4b5563;
      line-height: 1.5;
      font-size: 14px;
    }}

    code {{
      display: block;
      margin-top: 16px;
      padding: 12px;
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      color: #374151;
      white-space: pre-wrap;
      word-break: break-word;
    }}
  </style>
</head>
<body>
  <main class="panel" role="alert">
    <h1>Shreeji Admin could not start</h1>
    <p>Please close this window and start the application again.</p>
    <code>{escaped_message}</code>
  </main>
</body>
</html>
"""


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def run_flask_server(flask_app, port):
    flask_app.run(
        host=HOST,
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


def wait_for_server(port, timeout=SERVER_START_TIMEOUT_SECONDS):
    deadline = time.time() + timeout
    url = f"http://{HOST}:{port}{HEALTH_PATH}"

    while time.time() < deadline:
        try:
            with urlopen(url, timeout=0.5):
                return
        except HTTPError:
            return
        except (OSError, URLError):
            time.sleep(0.1)

    raise TimeoutError("Flask server did not respond before the startup timeout.")


class DesktopApp:
    def __init__(self):
        self.window = None
        self.port = None
        self.server_ready = threading.Event()

    @property
    def dashboard_url(self):
        return f"http://{HOST}:{self.port}{START_PATH}"

    def create_window(self):
        self.window = webview.create_window(
            APP_TITLE,
            html=LOADING_HTML,
            js_api=DesktopAPI(),
            width=1400,
            height=860,
            resizable=True,
            min_size=(1024, 600),
        )
        return self.window

    def start(self):
        self.create_window()
        webview.start(self.bootstrap)

    def bootstrap(self):
        try:
            flask_app = self.load_flask_app()
            self.port = find_free_port()
            self.start_flask_thread(flask_app)
            wait_for_server(self.port)

            db_thread = self.start_database_thread(flask_app)
            db_thread.join(timeout=20)

            from services.cache_sync import start_background_sync
            start_background_sync(flask_app)

            self.server_ready.set()
            self.window.load_url(self.dashboard_url)

        except Exception as error:
            print(f"Desktop startup failed: {error}", flush=True)
            if self.window:
                self.window.load_html(build_error_html(error))

    def load_flask_app(self):
        from app_admin import app as flask_app

        return flask_app

    def start_flask_thread(self, flask_app):
        thread = threading.Thread(
            target=run_flask_server,
            args=(flask_app, self.port),
            name="flask-admin-server",
            daemon=True,
        )
        thread.start()
        return thread

    def start_database_thread(self, flask_app):
        import db_neon

        return db_neon.start_background_init(flask_app)


if __name__ == "__main__":
    DesktopApp().start()
