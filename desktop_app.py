import threading
import webview
from app_admin import create_app

flask_app = create_app()


def run_flask():
    flask_app.run(
        host="127.0.0.1",
        port=5050,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    webview.create_window(
        "Shreeji Auto Service — Admin Panel",
        "http://127.0.0.1:5050/admin",
        width=1400,
        height=860,
        resizable=True,
        min_size=(1024, 600),
    )
    webview.start()
