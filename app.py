from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json, os
import time

app = Flask(__name__)
app.secret_key = "school_game_secret"

DATA_FILE = "data.json"
USERS_FILE = "users.json"
GAME_FILE = "game.json"
ADMIN_PASSWORD = "admin123"

# 초기 파일 생성
for path, default in [(DATA_FILE, {}), (USERS_FILE, {}), (GAME_FILE, {"running": False, "answer": None, "bets": [], "results": {}})]:
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)

# 파일 헬퍼
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def load_data():
    return load_json(DATA_FILE)

def save_data(d):
    save_json(DATA_FILE, d)

def load_users():
    return load_json(USERS_FILE)

def save_users(u):
    save_json(USERS_FILE, u)

def load_game():
    return load_json(GAME_FILE)

def save_game(g):
    save_json(GAME_FILE, g)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("로그아웃되었습니다.")
    return redirect(url_for("index"))

# PLAY: 보여줄 때는 현재 보유금과 game.running 상태 전달
@app.route("/play", methods=["GET"])
def play():
    if "user" not in session:
        flash("로그인이 필요합니다.")
        return redirect(url_for("login"))

    user = session["user"]
    data = load_data()
    money = data.get(user["name"], 0)
    game = load_game()
    # game_running True  => 배팅 허용 (게임이 진행중)
    return render_template("play.html", user=user, money=money, game_running=game.get("running", False))

# 배팅 제출: 게임이 'running' 상태일 때만 허용
@app.route("/check_answer", methods=["POST"])
def check_answer():
    user = session.get("user")
    if not user:
        flash("로그인이 필요합니다.")
        return redirect(url_for("login"))

    game = load_game()
    if not game.get("running", False):
        flash("현재는 베팅을 받을 수 없는 상태입니다. 관리자가 게임을 시작해야 합니다.")
        return redirect(url_for("play"))

    student_id = user["id"]
    name = user["name"]
    selected = request.form.get("answer")
    bet_str = request.form.get("bet", "0")

    # 서버측 검증
    try:
        bet = int(bet_str)
    except ValueError:
        flash("배팅 금액은 정수로 입력하세요.")
        return redirect(url_for("play"))
    if bet <= 0:
        flash("배팅 금액은 1 이상이어야 합니다.")
        return redirect(url_for("play"))

    data = load_data()
    if name not in data:
        data[name] = 0
    current_money = data[name]
    if bet > current_money:
        flash("배팅 금액이 보유금보다 큽니다.")
        return redirect(url_for("play"))

    # 즉시 차감
    data[name] = current_money - bet
    save_data(data)

    # 게임에 배팅 기록 추가
    bet_record = {
        "student_id": student_id,
        "name": name,
        "bet": bet,
        "choice": selected,
        "time": int(time.time())
    }
    game["bets"].append(bet_record)
    # clear previous personal result (so waiting page knows it's pending)
    if "results" not in game:
        game["results"] = {}
    if student_id in game["results"]:
        game["results"].pop(student_id, None)
    save_game(game)

    # 세션에 'waiting' 표시 (선택적)
    session["waiting"] = True
    return redirect(url_for("waiting"))

# 대기 페이지: 폴링으로 결과 확인
@app.route("/waiting")
def waiting():
    if "user" not in session:
        flash("로그인이 필요합니다.")
        return redirect(url_for("login"))
    return render_template("waiting.html")

# AJAX: 클라이언트가 자신의 베팅 결과/잔액을 폴링으로 확인
@app.route("/bet_status")
def bet_status():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401
    user = session["user"]
    student_id = user["id"]

    data = load_data()
    game = load_game()

    # 결과가 있으면 반환
    results = game.get("results", {})
    if student_id in results:
        # 반환 후에도 사용자 세션의 waiting 제거(클라이언트에서 처리 가능)
        message = results[student_id]
        money = data.get(user["name"], 0)
        return jsonify({"resolved": True, "message": message, "money": money})

    # 아직 정산 전
    return jsonify({"resolved": False})

@app.route("/result")
def result():
    # 단독 열람용 (정산 후 직접 들어올 수도 있도록)
    if "user" not in session:
        flash("로그인이 필요합니다.")
        return redirect(url_for("login"))
    user = session["user"]
    data = load_data()
    money = data.get(user["name"], 0)
    # game results may include personal message
    game = load_game()
    msg = game.get("results", {}).get(user["id"], None)
    if msg:
        return render_template("result.html", result=msg, money=money)
    else:
        flash("아직 결과가 발표되지 않았습니다.")
        return redirect(url_for("waiting"))

@app.route("/ranking")
def ranking():
    data = load_data()
    users = load_users()
    ranking_data = []
    for student_id, info in users.items():
        name = info["name"]
        money = data.get(name, 0)
        ranking_data.append((student_id, name, money))
    ranking_data.sort(key=lambda x: x[2], reverse=True)
    user = session.get("user")
    my_id = user["id"] if user else ""
    my_name = user["name"] if user else ""
    my_money = data.get(my_name, 0)
    return render_template("ranking.html", ranking=ranking_data, my_id=my_id, my_name=my_name, my_money=my_money)

# 관리자 로그인
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password")
        if password == ADMIN_PASSWORD:
            session["admin"] = True
            flash("관리자 로그인 성공!")
            return redirect(url_for("admin"))
        else:
            flash("비밀번호가 올바르지 않습니다.")
            return redirect(url_for("admin_login"))
    return render_template("admin_login.html")

# 관리자 페이지 + 동작: register / start / stop(정산) / set_answer
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        flash("관리자 비밀번호를 입력해주세요.")
        return redirect(url_for("admin_login"))

    game = load_game()
    users = load_users()
    data = load_data()
    
    if request.method == "POST":
        action = request.form.get("action")

        if action == "register":
            student_id = request.form.get("student_id")
            name = request.form.get("name")
            password = request.form.get("password")
            users[student_id] = {"name": name, "password": password}
            save_users(users)
            data[name] = data.get(name, 100)
            save_data(data)
            flash(f"{name} 학생 계정이 등록되었습니다. 기본 100G 지급됨.")
            return redirect(url_for("admin"))

        elif action == "start":
            game["running"] = True
            save_game(game)
            flash("게임 시작! 학생들이 배팅할 수 있습니다.")
            return redirect(url_for("admin"))

        elif action == "stop_betting":
            game["running"] = False  # 더 이상 배팅 불가
            save_game(game)
            flash("배팅이 종료되었습니다. 학생은 더 이상 배팅할 수 없습니다.")
            return redirect(url_for("admin"))

        elif action == "settle":
            correct = game.get("answer")
            bets = game.get("bets", [])
            results = {}
            for b in bets:
                sid = b["student_id"]
                name = b["name"]
                bet = int(b["bet"])
                choice = b["choice"]
                if name not in data:
                    data[name] = 0
                if correct is None:
                    data[name] += bet
                    results[sid] = f"정답이 설정되지 않았습니다. 배팅금 {bet}G 환불. (현재: {data[name]}G)"
                else:
                    if choice == correct:
                        payout = bet * 2
                        data[name] += payout
                        results[sid] = f"정답! {choice} 선택 → 지급 {payout}G (현재: {data[name]}G)"
                    else:
                        results[sid] = f"오답. {choice} 선택 → 배팅 {bet}G 손실 (현재: {data[name]}G)"
            save_data(data)
            game["bets"] = []
            game["results"] = results
            save_game(game)
            flash("정산 완료!")
            return redirect(url_for("admin"))

        elif action == "set_answer":
            answer = request.form.get("answer")
            if answer in ["A","B","C","D"]:
                game["answer"] = answer
                save_game(game)
                flash(f"정답 '{answer}'로 설정됨.")
            else:
                flash("정답을 올바르게 선택하세요.")
            return redirect(url_for("admin"))

        elif action == "set_money":
            tgt_id = request.form.get("target_student_id")
            amount_str = request.form.get("amount")
            if not tgt_id or not amount_str:
                flash("학번과 금액을 모두 입력하세요.")
                return redirect(url_for("admin"))
            try:
                amount = int(amount_str)
            except ValueError:
                flash("금액은 정수만 가능합니다.")
                return redirect(url_for("admin"))
            tgt_name = users[tgt_id]["name"]
            data[tgt_name] = amount
            save_data(data)
            flash(f"{tgt_name}({tgt_id}) 금액 {amount}G로 설정됨.")
            return redirect(url_for("admin"))

    balances = {sid:data.get(info["name"],0) for sid, info in users.items()}

    return render_template("admin.html", users=users, game=game, balances=balances)

# 로그인
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        student_id = request.form.get("student_id")
        name = request.form.get("name")
        password = request.form.get("password")
        users = load_users()
        if student_id in users:
            if users[student_id]["name"] == name and users[student_id]["password"] == password:
                session["user"] = {"id": student_id, "name": name}
                return redirect(url_for("play"))
        flash("로그인 실패! 학번, 이름, 비밀번호를 확인하세요.")
        return redirect(url_for("login"))
    return render_template("login.html")

if __name__ == "__main__":
    app.run(debug=True)
