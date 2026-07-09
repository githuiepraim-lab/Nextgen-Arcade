from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, time, threading, datetime, random, json

app = Flask(__name__, static_folder='static')
CORS(app)

# ── CONFIG ────────────────────────────────────────────────────────
AT_USERNAME  = os.environ.get("AT_USERNAME", "sandbox")
AT_APIKEY    = os.environ.get("AT_APIKEY",   "atsk_test")
STAFF_PHONE  = os.environ.get("STAFF_PHONE", "+254700000000")
ADMIN_PHONE  = os.environ.get("ADMIN_PHONE", "+254700000000")

# ── GAME PRICING ──────────────────────────────────────────────────
DEFAULT_PRICES = {
    "EA FC 25": 0, "Call of Duty: Black Ops 6": 50,
    "NBA 2K25": 0, "God of War Ragnarok": 100,
    "GTA V": 0, "Mortal Kombat 1": 50,
    "Spider-Man 2": 100, "Gran Turismo 7": 50,
    "Hogwarts Legacy": 100, "Elden Ring": 150,
}

# ── STATE ─────────────────────────────────────────────────────────
_lock       = threading.Lock()
sessions    = []
stations    = {i: {"occupied": False} for i in range(1, 8)}
pending     = []
customers   = []
games_lib   = [{"name": k, "surcharge": v} for k, v in DEFAULT_PRICES.items()]
settings    = {"rate": 200, "till": "522533", "name": "NextGen Arcade"}
integ_checks= {}   # station_id -> [ms timestamps]
integ_log   = []   # audit trail

# ── SMS ───────────────────────────────────────────────────────────
def send_sms(phone, msg):
    if not phone: return
    if phone.startswith("0"): phone = "+254" + phone[1:]
    elif not phone.startswith("+"): phone = "+254" + phone
    try:
        import africastalking
        africastalking.initialize(AT_USERNAME, AT_APIKEY)
        africastalking.SMS.send(msg, [phone])
        print(f"[SMS ✓] {phone[:10]}...")
    except Exception as e:
        print(f"[SMS ✗] {e}")

def sms_async(phone, msg):
    threading.Thread(target=send_sms, args=(phone, msg), daemon=True).start()

# ── CHARGE CALC ───────────────────────────────────────────────────
def get_game_surcharge(game_name):
    for g in games_lib:
        if g["name"] == game_name:
            return g.get("surcharge", 0)
    return 0

def calc_charge(game, duration_mins):
    rate     = settings.get("rate", 200)
    time_fee = round((duration_mins / 60) * rate)
    game_fee = get_game_surcharge(game)
    total    = time_fee + game_fee
    return {"time_fee": time_fee, "game_fee": game_fee, "total": total,
            "breakdown": f"KES {time_fee:,} (time) + KES {game_fee:,} (game) = KES {total:,}"}

# ── INTEGRITY SCHEDULER ───────────────────────────────────────────
def schedule_checks(sid, end_ms):
    now = int(time.time() * 1000)
    dur = end_ms - now
    if dur < 60000: return []
    window = dur / 4
    times = []
    for i in range(4):
        lo = int(window * i + window * 0.1)
        hi = int(window * i + window * 0.9)
        t  = now + random.randint(lo, hi)
        if t < end_ms: times.append(t)
    with _lock: integ_checks[sid] = times
    print(f"[Integrity] Stn {sid}: {len(times)} checks scheduled")
    return times

# ── BACKGROUND THREADS ────────────────────────────────────────────
def expiry_watcher():
    """Watches session end times, sends SMS when timer expires"""
    while True:
        now = int(time.time() * 1000)
        with _lock:
            items = list(stations.items())
        for sid, data in items:
            if not data.get("occupied"): continue
            if not data.get("endTime"): continue
            if now < data["endTime"]: continue
            if data.get("timer_notified"): continue
            # Mark notified
            with _lock:
                if stations.get(sid): stations[sid]["timer_notified"] = True
            player  = data.get("player","Customer")
            game    = data.get("game","")
            total   = data.get("charge", 0)
            bdown   = data.get("breakdown", f"KES {total:,}")
            c_phone = data.get("phone","")

            # SMS customer
            sms_async(c_phone,
                f"Hi {player}! ⏰ Your NextGen Arcade session has ended.\n"
                f"PS5 #{sid} | {game}\n"
                f"Total: {bdown}\n"
                f"Please pay at the counter. Thank you for playing! 🎮")

            # SMS staff
            sms_async(STAFF_PHONE,
                f"⏰ SESSION ENDED — NextGen Arcade\n"
                f"Station: PS5 #{sid}\n"
                f"Player: {player}\n"
                f"Game: {game}\n"
                f"Bill: {bdown}\n"
                f"Please collect payment & release station.")

            print(f"[Timer] Station {sid} expired — SMS sent to {c_phone} & staff")
        time.sleep(5)

def integrity_watcher():
    """Fires random CCTV spot-check SMS to admin"""
    while True:
        now = int(time.time() * 1000)
        with _lock:
            check_copy = {k: list(v) for k, v in integ_checks.items()}
        for sid, times in check_copy.items():
            with _lock:
                data = stations.get(sid, {})
            if not data.get("occupied"):
                with _lock: integ_checks.pop(sid, None)
                continue
            due = [t for t in times if t <= now]
            if not due: continue
            with _lock:
                integ_checks[sid] = [t for t in times if t > now]
            fired_n = 4 - len(integ_checks.get(sid, []))
            elapsed = round((now - data.get("startTime", now)) / 60000)
            remain  = max(0, round((data.get("endTime", now) - now) / 60000))
            entry   = {
                "station": sid, "player": data.get("player",""),
                "game": data.get("game",""), "check_num": fired_n,
                "timestamp": datetime.datetime.now().isoformat(),
                "elapsed": elapsed, "remaining": remain, "verified": None
            }
            with _lock:
                integ_log.insert(0, entry)
                if len(integ_log) > 300: integ_log.pop()
            sms_async(ADMIN_PHONE,
                f"🔍 INTEGRITY CHECK {fired_n}/4 — NextGen Arcade\n"
                f"Station: PS5 #{sid}\n"
                f"Player: {data.get('player','')}\n"
                f"Game: {data.get('game','')}\n"
                f"Elapsed: {elapsed}min | Remaining: {remain}min\n"
                f"Time: {datetime.datetime.now().strftime('%H:%M:%S')}\n"
                f"⚠️ Please verify on CCTV.")
            print(f"[Integrity] Check {fired_n}/4 for Station {sid}")
        time.sleep(8)

threading.Thread(target=expiry_watcher,   daemon=True).start()
threading.Thread(target=integrity_watcher, daemon=True).start()

# ── ROUTES ────────────────────────────────────────────────────────

@app.route("/api/stations")
def api_stations():
    with _lock: return jsonify(dict(stations))

@app.route("/api/station/<int:sid>")
def api_station(sid):
    with _lock: return jsonify(stations.get(sid, {}))

@app.route("/api/pricing/estimate", methods=["POST"])
def api_estimate():
    d = request.json or {}
    return jsonify(calc_charge(d.get("game",""), int(d.get("duration", 60))))

@app.route("/api/book", methods=["POST"])
def api_book():
    d = request.json or {}
    sid      = int(d.get("station", 0))
    player   = d.get("player","").strip()
    game     = d.get("game","").strip()
    duration = max(5, int(d.get("duration", 60)))
    phone    = d.get("phone","").strip()
    pay      = d.get("payMethod","Cash")
    cid      = d.get("cid","")

    if not player or not game:
        return jsonify({"error": "Missing player or game"}), 400
    with _lock:
        if stations.get(sid, {}).get("occupied"):
            return jsonify({"error": "Station occupied"}), 409

    charge   = calc_charge(game, duration)
    now      = int(time.time() * 1000)
    end_time = now + duration * 60 * 1000

    with _lock:
        stations[sid] = {
            "occupied": True, "player": player, "game": game,
            "duration": duration, "startTime": now, "endTime": end_time,
            "charge": charge["total"], "time_fee": charge["time_fee"],
            "game_fee": charge["game_fee"], "breakdown": charge["breakdown"],
            "payMethod": pay, "phone": phone, "cid": cid,
            "timer_notified": False,
        }

    schedule_checks(sid, end_time)

    sms_async(phone,
        f"Hi {player}! ✅ Checked in at NextGen Arcade 🎮\n"
        f"Station: PS5 #{sid} | {game}\n"
        f"Duration: {duration} min\n"
        f"Charge: {charge['breakdown']}\n"
        f"Payment: {pay}\nEnjoy your game!")

    return jsonify({"ok": True, "charge": charge, "endTime": end_time,
                    "checks_scheduled": len(integ_checks.get(sid, []))})

@app.route("/api/end/<int:sid>", methods=["POST"])
def api_end(sid):
    with _lock: data = dict(stations.get(sid, {}))
    if not data.get("occupied"):
        return jsonify({"error": "Not occupied"}), 400
    now    = int(time.time() * 1000)
    actual = max(1, round((now - data.get("startTime", now)) / 60000))
    charge = calc_charge(data["game"], actual)
    phone  = data.get("phone","")
    entry  = {
        "id": len(sessions)+1, "station": sid,
        "player": data["player"], "game": data["game"],
        "date": datetime.datetime.now().strftime("%d/%m/%Y"),
        "time": datetime.datetime.now().strftime("%H:%M"),
        "duration": actual, "time_fee": charge["time_fee"],
        "game_fee": charge["game_fee"], "charge": charge["total"],
        "breakdown": charge["breakdown"],
        "payMethod": data.get("payMethod","Cash"),
        "phone": phone, "cid": data.get("cid",""),
    }
    with _lock:
        sessions.insert(0, entry)
        stations[sid] = {"occupied": False}
        integ_checks.pop(sid, None)

    sms_async(phone,
        f"Hi {data['player']}! 🧾 NextGen Arcade Receipt\n"
        f"PS5 #{sid} | {data['game']} | {actual} min\n"
        f"Charge: {charge['breakdown']}\n"
        f"Payment: {data.get('payMethod','Cash')}\n"
        f"Thanks for playing! Come back soon 🎮")

    return jsonify({"ok": True, "session": entry})

@app.route("/api/pending")
def api_get_pending():
    with _lock: return jsonify(list(pending))

@app.route("/api/pending", methods=["POST"])
def api_add_pending():
    d = request.json or {}
    sid = d.get("station")
    with _lock:
        global pending
        pending = [p for p in pending if p.get("station") != sid]
        pending.append(d)
    # Notify staff of new self check-in
    sms_async(STAFF_PHONE,
        f"📱 SELF CHECK-IN — NextGen Arcade\n"
        f"Station: PS5 #{sid}\n"
        f"Player: {d.get('player','')}\n"
        f"Game: {d.get('game','')}\n"
        f"Duration: {d.get('duration',0)} min\n"
        f"Charge: {d.get('breakdown','')}\n"
        f"⚠️ Please approve on staff dashboard.")
    return jsonify({"ok": True})

@app.route("/api/approve/<int:sid>", methods=["POST"])
def api_approve(sid):
    with _lock:
        global pending
        item = next((p for p in pending if p.get("station") == sid), None)
        if not item: return jsonify({"error": "Not found"}), 404
        pending = [p for p in pending if p.get("station") != sid]
        stations[sid] = {**item, "timer_notified": False}
    schedule_checks(sid, item.get("endTime", 0))
    # SMS customer confirmation
    sms_async(item.get("phone",""),
        f"Hi {item.get('player','')}! ✅ Your station has been activated.\n"
        f"PS5 #{sid} | {item.get('game','')} | {item.get('duration',0)} min\n"
        f"Your timer starts now. Enjoy! 🎮")
    return jsonify({"ok": True})

@app.route("/api/sessions")
def api_sessions():
    sf = request.args.get("station")
    gf = request.args.get("game")
    df = request.args.get("date")
    with _lock: r = list(sessions)
    if sf: r = [s for s in r if str(s["station"]) == sf]
    if gf: r = [s for s in r if s["game"] == gf]
    if df: r = [s for s in r if s["date"] == df]
    return jsonify(r)

@app.route("/api/games")
def api_games():
    with _lock: return jsonify(list(games_lib))

@app.route("/api/games", methods=["POST"])
def api_update_games():
    global games_lib
    data = request.json or {}
    gl = data.get("games", [])
    with _lock:
        if gl and isinstance(gl[0], dict):
            games_lib = gl
        else:
            games_lib = [{"name": g, "surcharge": 0} for g in gl]
    return jsonify({"ok": True})

@app.route("/api/settings")
def api_settings():
    return jsonify(dict(settings))

@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    settings.update(request.json or {})
    return jsonify({"ok": True})

@app.route("/api/customers")
def api_customers():
    with _lock: return jsonify(list(customers))

@app.route("/api/customers", methods=["POST"])
def api_add_customer():
    with _lock: customers.append(request.json or {})
    return jsonify({"ok": True})

@app.route("/api/customers/<cid>", methods=["DELETE"])
def api_del_customer(cid):
    global customers
    with _lock: customers = [c for c in customers if c.get("id") != cid]
    return jsonify({"ok": True})

@app.route("/api/stk", methods=["POST"])
def api_stk():
    d = request.json or {}
    phone = d.get("phone","")
    amt   = d.get("amount", 0)
    bdown = d.get("breakdown", f"KES {amt:,}")
    sms_async(phone,
        f"NextGen Arcade: M-Pesa payment request\n"
        f"Amount: {bdown}\n"
        f"Enter your M-Pesa PIN to confirm. Ref: NG{int(time.time())}")
    return jsonify({"ok": True, "ref": f"NG{int(time.time())}"})

@app.route("/api/stats")
def api_stats():
    today = datetime.datetime.now().strftime("%d/%m/%Y")
    with _lock:
        sess = list(sessions)
        occ  = sum(1 for s in stations.values() if s.get("occupied"))
    today_s = [s for s in sess if s["date"] == today]
    gc, gr  = {}, {}
    for s in sess:
        gc[s["game"]] = gc.get(s["game"],0) + 1
        gr[s["game"]] = gr.get(s["game"],0) + s["charge"]
    top = max(gc, key=gc.get) if gc else "—"
    return jsonify({
        "total_sessions": len(sess),
        "today_sessions": len(today_s),
        "total_revenue":  sum(s["charge"] for s in sess),
        "today_revenue":  sum(s["charge"] for s in today_s),
        "total_time_fee": sum(s.get("time_fee",0) for s in sess),
        "total_game_fee": sum(s.get("game_fee",0) for s in sess),
        "occupied": occ, "available": 7-occ,
        "mpesa_sessions": sum(1 for s in sess if s["payMethod"]=="M-Pesa"),
        "cash_sessions":  sum(1 for s in sess if s["payMethod"]=="Cash"),
        "top_game": top, "game_counts": gc, "game_revenue": gr,
        "avg_duration": round(sum(s["duration"] for s in sess)/len(sess)) if sess else 0,
        "total_hours": round(sum(s["duration"] for s in sess)/60, 1),
        "integrity_today": len([l for l in integ_log
            if l["timestamp"][:10]==datetime.date.today().isoformat()]),
    })

@app.route("/api/integrity/log")
def api_integ_log():
    with _lock: return jsonify(integ_log[:100])

@app.route("/api/integrity/verify", methods=["POST"])
def api_integ_verify():
    d = request.json or {}
    with _lock:
        for l in integ_log:
            if l["station"]==d.get("station") and l["timestamp"]==d.get("timestamp"):
                l["verified"]    = d.get("verified", True)
                l["verified_at"] = datetime.datetime.now().isoformat()
                break
    return jsonify({"ok": True})

@app.route("/api/integrity/schedule/<int:sid>")
def api_integ_schedule(sid):
    now = int(time.time() * 1000)
    with _lock: times = list(integ_checks.get(sid, []))
    result = []
    for i, t in enumerate(times):
        result.append({
            "check_num": i+1,
            "due_in_mins": max(0, round((t-now)/60000)),
            "due_at": datetime.datetime.fromtimestamp(t/1000).strftime("%H:%M:%S"),
            "fired": t <= now,
        })
    return jsonify(result)

@app.route("/")
def index(): return send_from_directory("static","index.html")

@app.route("/<path:p>")
def static_f(p): return send_from_directory("static", p)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
