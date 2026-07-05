from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json, os, time, threading, datetime, random, math

app = Flask(__name__, static_folder='static')
CORS(app)

# ── CONFIG ────────────────────────────────────────────────────────
AT_USERNAME   = os.environ.get("AT_USERNAME",  "sandbox")
AT_APIKEY     = os.environ.get("AT_APIKEY",    "atsk_test")
STAFF_PHONE   = os.environ.get("STAFF_PHONE",  "+254700000000")
ADMIN_PHONE   = os.environ.get("ADMIN_PHONE",  "+254700000000")

# ── GAME PRICING TABLE ────────────────────────────────────────────
# Each game can have an extra flat fee on top of hourly rate
DEFAULT_GAME_PRICES = {
    "EA FC 25":               0,
    "Call of Duty: Black Ops 6": 50,   # +KES 50 per session
    "NBA 2K25":               0,
    "God of War Ragnarok":    100,
    "GTA V":                  0,
    "Mortal Kombat 1":        50,
    "Spider-Man 2":           100,
    "Gran Turismo 7":         50,
    "Hogwarts Legacy":        100,
    "Elden Ring":             150,     # premium game
}

# ── STORE ─────────────────────────────────────────────────────────
sessions    = []
stations    = {i: {"occupied": False} for i in range(1, 8)}
pending     = []
customers   = []
games_lib   = list(DEFAULT_GAME_PRICES.keys())
game_prices = dict(DEFAULT_GAME_PRICES)      # mutable per-game surcharges
settings    = {
    "rate":       200,    # KES per hour
    "till":       "522533",
    "name":       "NextGen Arcade",
    "currency":   "KES",
}

# ── AI INTEGRITY CHECK STATE ──────────────────────────────────────
# Stores scheduled check timestamps per station
integrity_checks  = {}   # {station_id: [timestamp_ms, ...]}
integrity_log     = []   # history of all checks sent

# ── SMS ───────────────────────────────────────────────────────────
def send_sms(phone, message):
    try:
        import africastalking
        africastalking.initialize(AT_USERNAME, AT_APIKEY)
        if phone.startswith("0"):
            phone = "+254" + phone[1:]
        elif not phone.startswith("+"):
            phone = "+254" + phone
        africastalking.SMS.send(message, [phone])
        return True
    except Exception as e:
        print(f"[SMS] {phone}: {str(e)[:80]}")
        return False

# ── CHARGE CALCULATOR ─────────────────────────────────────────────
def calc_charge(game, duration_mins, rate=None):
    """Total = (hourly_rate × hours) + game_surcharge"""
    r        = rate or settings["rate"]
    time_fee = round((duration_mins / 60) * r)
    game_fee = game_prices.get(game, 0)
    total    = time_fee + game_fee
    return {
        "time_fee":  time_fee,
        "game_fee":  game_fee,
        "total":     total,
        "breakdown": f"KES {time_fee:,} (time) + KES {game_fee:,} (game) = KES {total:,}"
    }

# ── AI INTEGRITY WATCHER ──────────────────────────────────────────
def schedule_integrity_checks(station_id, end_time_ms):
    """
    For each active session, AI picks 4 random timestamps within
    the session window and schedules admin spot-check alerts.
    These are staggered so the admin cannot predict them.
    """
    now      = int(time.time() * 1000)
    duration = end_time_ms - now
    if duration <= 0:
        return []

    # Pick 4 random moments spread across the session
    # Divide into 4 windows, pick random point in each
    window = duration / 4
    times  = []
    for i in range(4):
        # Random point within each quarter, with some jitter
        t = now + int(window * i) + random.randint(
            int(window * 0.15),
            int(window * 0.85)
        )
        if t < end_time_ms:
            times.append(t)

    integrity_checks[station_id] = times
    print(f"[Integrity] Station {station_id}: {len(times)} checks scheduled")
    return times

def integrity_watcher():
    """Background thread that fires spot-check SMS at scheduled times"""
    while True:
        now = int(time.time() * 1000)
        for sid, check_times in list(integrity_checks.items()):
            if not stations.get(sid, {}).get("occupied"):
                # Session ended — remove checks
                integrity_checks.pop(sid, None)
                continue

            station_data = stations[sid]
            due = [t for t in check_times if t <= now]
            if not due:
                continue

            # Remove fired checks
            integrity_checks[sid] = [t for t in check_times if t > now]

            # Build alert message
            elapsed   = round((now - station_data.get("startTime", now)) / 60000)
            remaining = max(0, round((station_data.get("endTime", now) - now) / 60000))
            player    = station_data.get("player", "Unknown")
            game      = station_data.get("game", "Unknown")
            check_num = 4 - len(integrity_checks.get(sid, []))  # which check this is
            total_chk = 4

            msg = (
                f"🎮 NEXTGEN ARCADE — INTEGRITY CHECK #{check_num}/{total_chk}\n"
                f"Station: PS5 #{sid}\n"
                f"Player:  {player}\n"
                f"Game:    {game}\n"
                f"Time:    {elapsed}min elapsed | {remaining}min left\n"
                f"⚠️ Please verify on CCTV that PS5 #{sid} is in use "
                f"by the correct player. Time: {datetime.datetime.now().strftime('%H:%M:%S')}"
            )

            # Log it
            log_entry = {
                "station":    sid,
                "player":     player,
                "game":       game,
                "check_num":  check_num,
                "timestamp":  datetime.datetime.now().isoformat(),
                "elapsed":    elapsed,
                "remaining":  remaining,
                "verified":   None,   # admin marks this
            }
            integrity_log.insert(0, log_entry)
            if len(integrity_log) > 200:
                integrity_log.pop()

            # Fire SMS to admin
            threading.Thread(
                target=send_sms,
                args=(ADMIN_PHONE, msg),
                daemon=True
            ).start()
            print(f"[Integrity] Check #{check_num} fired for Station {sid} ({player})")

        time.sleep(8)  # check every 8 seconds

# ── SESSION EXPIRY WATCHER ────────────────────────────────────────
def expiry_watcher():
    while True:
        now = int(time.time() * 1000)
        for sid, data in list(stations.items()):
            if data.get("occupied") and data.get("endTime"):
                if now >= data["endTime"] and not data.get("notified"):
                    stations[sid]["notified"] = True
                    player  = data.get("player", "Customer")
                    game    = data.get("game", "")
                    total   = data.get("charge", 0)
                    c_phone = data.get("phone", "")
                    bdown   = data.get("breakdown", f"KES {total:,}")

                    # SMS customer
                    if c_phone:
                        threading.Thread(target=send_sms, args=(c_phone,
                            f"Hi {player}! ⏰ Your NextGen Arcade session has ended.\n"
                            f"PS5 #{sid} | {game}\n"
                            f"Total charge: {bdown}\n"
                            f"Please pay at the counter. Thank you! 🎮"
                        ), daemon=True).start()

                    # SMS staff
                    threading.Thread(target=send_sms, args=(STAFF_PHONE,
                        f"⏰ NextGen Arcade: Session ENDED\n"
                        f"Station: PS5 #{sid}\n"
                        f"Player: {player} | {game}\n"
                        f"Bill: {bdown}\n"
                        f"Please release station and collect payment."
                    ), daemon=True).start()

        time.sleep(10)

# Start background threads
threading.Thread(target=expiry_watcher,   daemon=True).start()
threading.Thread(target=integrity_watcher, daemon=True).start()

# ── API ROUTES ────────────────────────────────────────────────────

@app.route("/api/stations", methods=["GET"])
def get_stations():
    return jsonify(stations)

@app.route("/api/station/<int:sid>", methods=["GET"])
def get_station(sid):
    return jsonify(stations.get(sid, {}))

@app.route("/api/pricing/estimate", methods=["POST"])
def estimate():
    """Return charge breakdown before booking"""
    d    = request.json
    game = d.get("game", "")
    dur  = int(d.get("duration", 60))
    c    = calc_charge(game, dur)
    return jsonify(c)

@app.route("/api/book", methods=["POST"])
def book_station():
    d        = request.json
    sid      = d.get("station")
    player   = d.get("player", "").strip()
    game     = d.get("game", "").strip()
    duration = int(d.get("duration", 60))
    phone    = d.get("phone", "").strip()
    pay      = d.get("payMethod", "Cash")
    cid      = d.get("cid", "")

    if not player or not game:
        return jsonify({"error": "Missing fields"}), 400
    if stations.get(sid, {}).get("occupied"):
        return jsonify({"error": "Station already occupied"}), 409

    charge   = calc_charge(game, duration)
    now      = int(time.time() * 1000)
    end_time = now + duration * 60 * 1000

    stations[sid] = {
        "occupied":  True,
        "player":    player,
        "game":      game,
        "duration":  duration,
        "startTime": now,
        "endTime":   end_time,
        "charge":    charge["total"],
        "time_fee":  charge["time_fee"],
        "game_fee":  charge["game_fee"],
        "breakdown": charge["breakdown"],
        "payMethod": pay,
        "phone":     phone,
        "cid":       cid,
        "notified":  False,
    }

    # Schedule AI integrity checks
    check_times = schedule_integrity_checks(sid, end_time)

    # SMS confirmation to customer
    if phone:
        threading.Thread(target=send_sms, args=(phone,
            f"Hi {player}! ✅ Checked in at NextGen Arcade 🎮\n"
            f"Station: PS5 #{sid} | {game}\n"
            f"Duration: {duration} min\n"
            f"Charge: {charge['breakdown']}\n"
            f"Payment: {pay} | Enjoy your session!"
        ), daemon=True).start()

    return jsonify({
        "ok":         True,
        "charge":     charge,
        "endTime":    end_time,
        "checks_scheduled": len(check_times),
    })

@app.route("/api/end/<int:sid>", methods=["POST"])
def end_session(sid):
    data = stations.get(sid, {})
    if not data.get("occupied"):
        return jsonify({"error": "Station not occupied"}), 400

    now    = int(time.time() * 1000)
    actual = max(1, round((now - data.get("startTime", now)) / 60000))
    charge = calc_charge(data["game"], actual)
    phone  = data.get("phone", "")

    entry = {
        "id":        len(sessions) + 1,
        "station":   sid,
        "player":    data["player"],
        "game":      data["game"],
        "date":      datetime.datetime.now().strftime("%d/%m/%Y"),
        "time":      datetime.datetime.now().strftime("%H:%M"),
        "duration":  actual,
        "time_fee":  charge["time_fee"],
        "game_fee":  charge["game_fee"],
        "charge":    charge["total"],
        "breakdown": charge["breakdown"],
        "payMethod": data.get("payMethod", "Cash"),
        "phone":     phone,
        "cid":       data.get("cid", ""),
    }
    sessions.insert(0, entry)

    # Clear station + integrity checks
    stations[sid] = {"occupied": False}
    integrity_checks.pop(sid, None)

    # SMS receipt to customer
    if phone:
        threading.Thread(target=send_sms, args=(phone,
            f"Hi {data['player']}! 🧾 NextGen Arcade Receipt\n"
            f"PS5 #{sid} | {data['game']} | {actual} min\n"
            f"Charge: {charge['breakdown']}\n"
            f"Payment: {data.get('payMethod','Cash')}\n"
            f"Thanks for playing! Come back soon 🎮"
        ), daemon=True).start()

    return jsonify({"ok": True, "session": entry})

@app.route("/api/pending", methods=["GET"])
def get_pending():
    return jsonify(pending)

@app.route("/api/pending", methods=["POST"])
def add_pending():
    global pending
    d = request.json
    pending = [p for p in pending if p["station"] != d.get("station")]
    pending.append(d)
    return jsonify({"ok": True})

@app.route("/api/approve/<int:sid>", methods=["POST"])
def approve_pending(sid):
    global pending
    item = next((p for p in pending if p["station"] == sid), None)
    if not item:
        return jsonify({"error": "No pending check-in"}), 404
    stations[sid] = {**item, "notified": False}
    pending = [p for p in pending if p["station"] != sid]
    # Schedule integrity checks
    schedule_integrity_checks(sid, item.get("endTime", 0))
    return jsonify({"ok": True})

@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    sf = request.args.get("station")
    gf = request.args.get("game")
    df = request.args.get("date")
    r  = sessions
    if sf: r = [s for s in r if str(s["station"]) == sf]
    if gf: r = [s for s in r if s["game"] == gf]
    if df: r = [s for s in r if s["date"] == df]
    return jsonify(r)

@app.route("/api/games", methods=["GET"])
def get_games():
    return jsonify([
        {"name": g, "surcharge": game_prices.get(g, 0)}
        for g in games_lib
    ])

@app.route("/api/games", methods=["POST"])
def update_games():
    global games_lib, game_prices
    data = request.json
    if "games" in data:
        # Accepts list of {name, surcharge} or plain list
        if data["games"] and isinstance(data["games"][0], dict):
            games_lib   = [g["name"] for g in data["games"]]
            game_prices = {g["name"]: g.get("surcharge", 0) for g in data["games"]}
        else:
            games_lib = data["games"]
    return jsonify({"ok": True})

@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(settings)

@app.route("/api/settings", methods=["POST"])
def update_settings():
    settings.update(request.json)
    return jsonify({"ok": True})

@app.route("/api/customers", methods=["GET"])
def get_customers():
    return jsonify(customers)

@app.route("/api/customers", methods=["POST"])
def add_customer():
    customers.append(request.json)
    return jsonify({"ok": True})

@app.route("/api/customers/<cid>", methods=["DELETE"])
def del_customer(cid):
    global customers
    customers = [c for c in customers if c["id"] != cid]
    return jsonify({"ok": True})

@app.route("/api/stk", methods=["POST"])
def stk_push():
    d     = request.json
    phone = d.get("phone", "")
    amt   = d.get("amount", 0)
    name  = d.get("name", "Customer")
    bdown = d.get("breakdown", f"KES {amt:,}")
    if phone:
        send_sms(phone,
            f"NextGen Arcade: Payment of {bdown} requested.\n"
            f"Enter your M-Pesa PIN to confirm. Ref: NG{int(time.time())}")
    return jsonify({"ok": True, "ref": f"NG{int(time.time())}"})

@app.route("/api/stats", methods=["GET"])
def get_stats():
    today      = datetime.datetime.now().strftime("%d/%m/%Y")
    today_sess = [s for s in sessions if s["date"] == today]
    game_counts, game_revenue = {}, {}
    for s in sessions:
        game_counts[s["game"]]   = game_counts.get(s["game"], 0) + 1
        game_revenue[s["game"]]  = game_revenue.get(s["game"], 0) + s["charge"]
    top = max(game_counts, key=game_counts.get) if game_counts else "—"
    return jsonify({
        "total_sessions": len(sessions),
        "today_sessions": len(today_sess),
        "total_revenue":  sum(s["charge"] for s in sessions),
        "today_revenue":  sum(s["charge"] for s in today_sess),
        "total_time_fee": sum(s.get("time_fee",0) for s in sessions),
        "total_game_fee": sum(s.get("game_fee",0) for s in sessions),
        "occupied":       sum(1 for s in stations.values() if s.get("occupied")),
        "available":      7 - sum(1 for s in stations.values() if s.get("occupied")),
        "mpesa_sessions": sum(1 for s in sessions if s["payMethod"] == "M-Pesa"),
        "cash_sessions":  sum(1 for s in sessions if s["payMethod"] == "Cash"),
        "top_game":       top,
        "game_counts":    game_counts,
        "game_revenue":   game_revenue,
        "avg_duration":   round(sum(s["duration"] for s in sessions)/len(sessions)) if sessions else 0,
        "total_hours":    round(sum(s["duration"] for s in sessions)/60, 1),
        "integrity_checks_today": len([l for l in integrity_log
                                       if l["timestamp"][:10] == datetime.date.today().isoformat()]),
    })

# ── INTEGRITY ENDPOINTS ───────────────────────────────────────────
@app.route("/api/integrity/log", methods=["GET"])
def get_integrity_log():
    return jsonify(integrity_log[:50])

@app.route("/api/integrity/verify", methods=["POST"])
def verify_check():
    """Admin marks a check as verified (seen on CCTV)"""
    d        = request.json
    station  = d.get("station")
    ts       = d.get("timestamp")
    verified = d.get("verified", True)
    for log in integrity_log:
        if log["station"] == station and log["timestamp"] == ts:
            log["verified"] = verified
            log["verified_at"] = datetime.datetime.now().isoformat()
            break
    return jsonify({"ok": True})

@app.route("/api/integrity/schedule/<int:sid>", methods=["GET"])
def get_schedule(sid):
    """Show admin when the next integrity checks are due"""
    times  = integrity_checks.get(sid, [])
    now    = int(time.time() * 1000)
    result = []
    for i, t in enumerate(times):
        mins_away = round((t - now) / 60000)
        result.append({
            "check_num":  i+1,
            "due_in_mins": max(0, mins_away),
            "due_at":     datetime.datetime.fromtimestamp(t/1000).strftime("%H:%M:%S"),
            "fired":      t <= now,
        })
    return jsonify(result)

# ── Serve HTML ────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("static", path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
