from pathlib import Path

from flask import Flask, send_from_directory

from config import FRONTEND_DIST_DIR
from realtime import init_realtime, socketio
from routes import api_bp


def create_app():
    app = Flask(__name__, static_folder=None)
    app.register_blueprint(api_bp)
    init_realtime(app)

    @app.route("/")
    @app.route("/<path:path>")
    def spa(path: str = ""):
        """
        Serve the built React app for everything that isn't an API route.
        Falls back to index.html for any unknown path so client-side
        shortcuts (e.g. a deep link) still load the SPA shell.
        """
        if not FRONTEND_DIST_DIR.exists():
            return (
                "Frontend build not found. Run:\n"
                "  cd frontend && npm install && npm run build\n"
                "then restart the server.",
                503,
            )

        requested = FRONTEND_DIST_DIR / path
        if path and requested.is_file():
            return send_from_directory(FRONTEND_DIST_DIR, path)
        return send_from_directory(FRONTEND_DIST_DIR, "index.html")

    return app


app = create_app()


if __name__ == "__main__":
    if socketio:
        socketio.run(app, debug=False, host="127.0.0.1", port=5000, allow_unsafe_werkzeug=True)
    else:
        app.run(debug=False, host="127.0.0.1", port=5000)
