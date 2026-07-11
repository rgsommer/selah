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


# Visitor-facing upload page (the QR points here). No admin controls, no
# password — it's a local-network, upload-only form.
UPLOAD_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Add a photo</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#f4f2ec;color:#333}
    .card{max-width:460px;margin:0 auto}
    .hdr{background:linear-gradient(135deg,#b5651d,#d98b3f);color:#fff;padding:26px 22px;border-radius:0 0 18px 18px}
    .hdr h1{margin:0;font-size:22px}
    .hdr p{margin:4px 0 0;opacity:.9;font-size:14px}
    .body{padding:22px}
    label{display:block;font-weight:600;margin:16px 0 6px;font-size:14px}
    input[type=text],input[type=file]{width:100%;box-sizing:border-box;padding:12px;
      border:1px solid #ddd;border-radius:10px;font-size:16px;background:#fff}
    .hint{font-size:12px;color:#999;margin-top:6px}
    button{width:100%;margin-top:22px;padding:15px;background:#b5651d;color:#fff;border:0;
      border-radius:999px;font-size:17px;font-weight:700}
    button:disabled{opacity:.5}
    .msg{margin-top:16px;padding:12px;border-radius:10px;text-align:center;font-weight:600;display:none}
    .ok{background:#e7f6ec;color:#1c7a3f}
    .err{background:#fdecea;color:#c0392b}
  </style>
</head>
<body>
  <div class="card">
    <div class="hdr"><h1>&#128247; Add a photo</h1><p>{{owner}}</p></div>
    <div class="body">
      <label>Your name</label>
      <input type="text" id="name" placeholder="e.g. Laura" autocomplete="name">
      <label>Caption (optional)</label>
      <input type="text" id="caption" placeholder="What's happening in the photo?">
      <label>Photos or video</label>
      <input type="file" id="files" accept="image/*,video/*" multiple>
      <div class="hint">A few at a time is best. Large videos may take a moment.</div>
      <button id="btn" onclick="up()">Add to the display</button>
      <div class="msg" id="msg"></div>
    </div>
  </div>
  <script>
    function show(cls,txt){var m=document.getElementById('msg');m.className='msg '+cls;m.style.display='block';m.textContent=txt;}
    function up(){
      var f=document.getElementById('files').files;
      if(!f.length){show('err','Please choose at least one photo.');return;}
      var fd=new FormData();
      for(var i=0;i<f.length;i++) fd.append('media', f[i]);
      fd.append('name', document.getElementById('name').value);
      fd.append('caption', document.getElementById('caption').value);
      var b=document.getElementById('btn'); b.disabled=true; b.textContent='Uploading…';
      fetch('/upload',{method:'POST',body:fd})
        .then(r=>r.json().then(d=>({ok:r.ok,d:d})))
        .then(x=>{ if(x.ok){show('ok',x.d.message||'Added!'); document.getElementById('files').value='';}
                   else show('err',x.d.error||'Upload failed.'); })
        .catch(e=>show('err','Upload failed: '+e))
        .finally(()=>{b.disabled=false;b.textContent='Add to the display';});
    }
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

    @_app.route("/upload", methods=["GET", "POST"])
    def upload():
        # GET -> the visitor upload page (the QR points here).
        if request.method == "GET":
            owner = config.get("display_owner_name", "the family display")
            return render_template_string(UPLOAD_HTML, owner=owner)

        # POST -> save uploaded files into the slideshow (same pipeline as email).
        files = [f for f in request.files.getlist("media") if f and f.filename]
        if not files:
            return jsonify({"error": "No file selected"}), 400
        name = (request.form.get("name") or "").strip() or "Visitor"
        caption = (request.form.get("caption") or "").strip()
        valid_exts = tuple(config.get("valid_extensions", [".jpg", ".jpeg", ".png", ".mp4"]))
        try:
            from werkzeug.utils import secure_filename
        except Exception:
            def secure_filename(x):
                return os.path.basename(x or "")
        from modules.email_handler import save_media_bytes, log_media

        saved = skipped = 0
        for f in files:
            fn = secure_filename(f.filename) or "photo"
            if not fn.lower().endswith(valid_exts):
                skipped += 1
                continue
            try:
                data = f.read()
                dest, is_new = save_media_bytes(data, fn, config, sender=name)
            except Exception as e:
                log_error(f"Web upload save failed: {e}")
                skipped += 1
                continue
            if not dest or not is_new:         # error, or exact-duplicate content
                skipped += 1
                continue
            try:
                log_media(dest, name, None, caption)
            except Exception:
                pass
            try:
                from modules.pending_photos import add as _padd
                _padd(dest)                    # surface at the next rotation
            except Exception:
                pass
            try:
                from modules.new_photo_hint import note_new_photo
                note_new_photo(kind="upload")
            except Exception:
                pass
            # Count QR/web uploads on the leaderboard too (the form collects the
            # uploader's name). Skip the anonymous "Visitor" fallback.
            if name and name != "Visitor":
                try:
                    from modules.leaderboard import update_leaderboard
                    update_leaderboard(name, 1)
                except Exception:
                    pass
            saved += 1

        if saved:
            who = "" if name == "Visitor" else f", {name}"
            msg = f"Thanks{who}! Added {saved} photo{'s' if saved != 1 else ''} to the display."
            return jsonify({"message": msg, "saved": saved, "skipped": skipped})
        return jsonify({"error": "Nothing added — unsupported type, or already on the display."}), 400

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

    port = int(config.get("web_control_port", 5000))

    def _run():
        try:
            _app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        except Exception as e:
            log_error(f"Web server error: {e}", critical=True, config=config)

    _server_thread = threading.Thread(target=_run, daemon=True, name="selah-web")
    _server_thread.start()
    print(f"[Web Control] Server started on http://0.0.0.0:{port}  (upload page: /upload)")


def get_pending_commands():
    """Pop all pending commands from the web interface queue."""
    commands = list(_shared_state.get("command_queue", []))
    _shared_state["command_queue"] = []
    return commands
