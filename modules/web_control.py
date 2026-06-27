"""Web control interface for Selah Display System.

Flask-based web UI for remote control. Runs in a background thread.
Endpoints: /, /next, /previous, /pause, /resume, /status, /upload, /config
"""

import os
import json
import time
import threading
from modules.logger import log_error

try:
    from flask import Flask, request, jsonify, render_template_string
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

_app = None
_server_thread = None
_shared_state = {
    "config": {},
    "screens": {},
    "command_queue": [],
}

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Selah Display Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;
               padding: 20px; background: #1a1a2e; color: #eee; }
        h1 { color: #e6a817; text-align: center; }
        .btn { display: inline-block; padding: 15px 30px; margin: 8px;
               background: #16213e; color: #fff; border: 2px solid #0f3460;
               border-radius: 8px; cursor: pointer; font-size: 16px;
               text-align: center; min-width: 100px; }
        .btn:hover { background: #0f3460; }
        .btn:active { background: #e6a817; color: #000; }
        .controls { text-align: center; margin: 20px 0; }
        .status { background: #16213e; padding: 15px; border-radius: 8px; margin: 15px 0; }
        .upload-form { background: #16213e; padding: 15px; border-radius: 8px; margin: 15px 0; }
        .message { text-align: center; padding: 10px; color: #4ecca3; }
    </style>
</head>
<body>
    <h1>Selah Display</h1>
    <div class="controls">
        <button class="btn" onclick="send('previous')">Previous</button>
        <button class="btn" onclick="send('pause')">Pause</button>
        <button class="btn" onclick="send('resume')">Resume</button>
        <button class="btn" onclick="send('next')">Next</button>
        <button class="btn" onclick="send('favorite')">&#10084; Favorite</button>
    </div>
    <div class="status" id="status">Loading status...</div>
    <div class="upload-form">
        <h3>Upload Media</h3>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="media" accept="image/*,video/*">
            <button class="btn" type="submit">Upload</button>
        </form>
    </div>
    <div class="message" id="msg"></div>
    <script>
        function send(action) {
            fetch('/' + action, {method: 'POST'})
                .then(r => r.json())
                .then(d => { document.getElementById('msg').textContent = d.message || 'Done'; })
                .catch(e => { document.getElementById('msg').textContent = 'Error: ' + e; });
        }
        function loadStatus() {
            fetch('/status').then(r => r.json()).then(d => {
                let html = '<b>Status:</b> ' + (d.slideshow_active ? 'Playing' : 'Paused');
                html += '<br><b>Media files:</b> ' + (d.total_files || 0);
                html += '<br><b>Uptime:</b> ' + (d.uptime || 'unknown');
                document.getElementById('status').innerHTML = html;
            }).catch(() => {});
        }
        loadStatus();
        setInterval(loadStatus, 10000);
    </script>
</body>
</html>
"""


def start_web_server(config, screens):
    """Start Flask web server in a background thread. Non-blocking."""
    global _app, _server_thread, _shared_state

    if not HAS_FLASK:
        log_error("Flask not installed. Web control disabled. Run: pip install flask")
        return

    if _server_thread and _server_thread.is_alive():
        return

    _shared_state["config"] = config
    _shared_state["screens"] = screens
    _shared_state["start_time"] = time.time()

    _app = Flask(__name__)
    _app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

    password = config.get("web_control_password", "")

    @_app.route("/")
    def dashboard():
        return render_template_string(DASHBOARD_HTML)

    @_app.route("/status")
    def status():
        uptime_secs = int(time.time() - _shared_state.get("start_time", time.time()))
        hours, rem = divmod(uptime_secs, 3600)
        mins, secs = divmod(rem, 60)
        return jsonify({
            "slideshow_active": True,
            "total_files": 0,
            "uptime": f"{hours}h {mins}m {secs}s",
        })

    @_app.route("/next", methods=["POST"])
    def next_image():
        _shared_state["command_queue"].append("next")
        return jsonify({"message": "Skipping to next image"})

    @_app.route("/previous", methods=["POST"])
    def previous_image():
        _shared_state["command_queue"].append("previous")
        return jsonify({"message": "Going to previous image"})

    @_app.route("/favorite", methods=["POST"])
    def favorite():
        try:
            import os
            from modules.now_showing import get_current
            from modules.favorites import add_favorite
            path = get_current()
            if not path:
                return jsonify({"message": "Nothing on screen yet"})
            if add_favorite(path):
                return jsonify({"message": f"❤ Favorited {os.path.basename(path)}"})
            return jsonify({"message": "Already a favorite"})
        except Exception as e:
            return jsonify({"message": f"Error: {e}"})

    @_app.route("/pause", methods=["POST"])
    def pause():
        _shared_state["command_queue"].append("pause")
        return jsonify({"message": "Slideshow paused"})

    @_app.route("/resume", methods=["POST"])
    def resume():
        _shared_state["command_queue"].append("resume")
        return jsonify({"message": "Slideshow resumed"})

    @_app.route("/upload", methods=["POST"])
    def upload():
        if "media" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        file = request.files["media"]
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400
        valid_exts = tuple(config.get("valid_extensions", [".jpg", ".jpeg", ".png", ".mp4"]))
        if not file.filename.lower().endswith(valid_exts):
            return jsonify({"error": "Invalid file type"}), 400
        dest_dir = config.get("display_dir", "media/display")
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, file.filename)
        file.save(dest_path)
        return jsonify({"message": f"Uploaded {file.filename}", "path": dest_path})

    @_app.route("/config", methods=["POST"])
    def update_config():
        token = request.args.get("token") or request.form.get("token") or ""
        if password and token != password:
            return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json()
        if data:
            for key, value in data.items():
                config[key] = value
            try:
                with open("display_config.json", "w") as f:
                    json.dump(config, f, indent=2)
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        return jsonify({"message": "Config updated"})

    def _run():
        try:
            _app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
        except Exception as e:
            log_error(f"Web server error: {e}", critical=True, config=config)

    _server_thread = threading.Thread(target=_run, daemon=True, name="selah-web")
    _server_thread.start()
    print("[Web Control] Server started on http://0.0.0.0:5000")


def get_pending_commands():
    """Pop all pending commands from the web interface queue."""
    commands = list(_shared_state.get("command_queue", []))
    _shared_state["command_queue"] = []
    return commands
