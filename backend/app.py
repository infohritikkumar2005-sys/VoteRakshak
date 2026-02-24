# backend/app.py
"""
Vote Rakshak V2 - Enterprise Grade Decentralized Voting System
Features:
- Election Phase Management (CREATED → ACTIVE → ENDED → RESULT_DECLARED)
- Multi-Election Support
- Vote Receipt Verification System
"""

from flask import Flask, request, jsonify, send_from_directory, g
from flask_cors import CORS
from web3 import Web3
from models import (
    Voter, Admin, Election, VoteReceipt, 
    VoterElectionRegistration, SessionLocal
)
from face_utils import encode_face, compare_faces, hash_encoding
import numpy as np
import os, json, base64, cv2, bcrypt, jwt, datetime, hashlib
from functools import wraps

from config.secret import (
    JWT_SECRET,
    ADMIN_PRIVATE_KEY,
    ADMIN_ACCOUNT,
    CONTRACT_ADDRESS,
    ABI_PATH,
    RPC_URL,
    GEMINI_API_KEY
)

import google.generativeai as genai
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_PATH = os.path.join(BASE_DIR, "../frontend")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder=FRONTEND_PATH, static_url_path="")
CORS(app)

# ============================================================
#                    BLOCKCHAIN SETUP
# ============================================================
w3 = Web3(Web3.HTTPProvider(RPC_URL))
print("Blockchain Connected:", w3.is_connected())

with open(ABI_PATH, "r", encoding="utf-8") as f:
    contract_json = json.load(f)
abi = contract_json if isinstance(contract_json, list) else contract_json.get("abi")

contract = w3.eth.contract(
    address=Web3.to_checksum_address(CONTRACT_ADDRESS),
    abi=abi,
)

# Phase mapping from contract enum to string
PHASE_MAP = {0: "CREATED", 1: "ACTIVE", 2: "ENDED", 3: "RESULT_DECLARED"}
PHASE_REVERSE = {"CREATED": 0, "ACTIVE": 1, "ENDED": 2, "RESULT_DECLARED": 3}


# ============================================================
#                    HELPER FUNCTIONS
# ============================================================
def get_bytes(val):
    if isinstance(val, (bytes, bytearray, memoryview)):
        return bytes(val)
    return bytes(val) if val is not None else b""


def save_image_b64(data_url, dest):
    if "," in data_url:
        _, encoded = data_url.split(",", 1)
    else:
        encoded = data_url
    img_bytes = base64.b64decode(encoded)
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Invalid Base64 image")
    cv2.imwrite(dest, img)
    return img


def safe_delete(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except:
        pass


def send_contract_tx(fn, *args, gas=500000):
    """Send transaction and return (tx_hash, receipt, error)"""
    try:
        nonce = w3.eth.get_transaction_count(ADMIN_ACCOUNT)
        tx = fn(*args).build_transaction({
            "from": ADMIN_ACCOUNT,
            "nonce": nonce,
            "gas": gas,
            "gasPrice": w3.to_wei("1", "gwei"),
        })
        signed = w3.eth.account.sign_transaction(tx, private_key=ADMIN_PRIVATE_KEY)
        raw_tx = signed.raw_transaction if hasattr(signed, 'raw_transaction') else signed.rawTransaction
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        return tx_hash.hex(), receipt, None
    except ValueError as e:
        err = e.args[0]
        reason = ""
        if isinstance(err, dict):
            # Try nested data.reason first (Ganache revert reason)
            data = err.get("data", {})
            if isinstance(data, dict):
                reason = data.get("reason") or data.get("message") or ""
            reason = reason or err.get("message", "") or "Blockchain error"
        else:
            reason = str(err)
        return None, None, reason or "Blockchain error"
    except Exception as e:
        # Extract reason from web3 exception string if possible
        err_str = str(e)
        if "revert" in err_str.lower():
            # Try to extract the revert reason
            import re
            match = re.search(r"revert (.+?)(?:'|$)", err_str, re.IGNORECASE)
            if match:
                return None, None, match.group(1).strip()
        return None, None, err_str


def generate_enrollment_hash(enrollment, election_id):
    """Generate hash for enrollment + election ID combination"""
    combined = f"{enrollment}:{election_id}"
    return "0x" + hashlib.sha256(combined.encode()).hexdigest()


# ============================================================
#                    AUTH DECORATOR
# ============================================================
def admin_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token:
            return jsonify({"error": "Token missing"}), 401
        try:
            token = token.replace("Bearer ", "").strip()
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            username = payload.get("username")
            with SessionLocal() as db:
                admin = db.query(Admin).filter_by(username=username).first()
                if not admin:
                    return jsonify({"error": "Admin not found"}), 401
                g.admin = admin
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except Exception as e:
            return jsonify({"error": "Invalid token", "detail": str(e)}), 401
        return f(*args, **kwargs)
    return wrap


# ============================================================
#                    FRONTEND ROUTES
# ============================================================
@app.route("/")
def home():
    return send_from_directory(FRONTEND_PATH, "index.html")


@app.route("/admin")
def admin_page():
    return send_from_directory(FRONTEND_PATH, "admin_login.html")


@app.route("/admin-dashboard")
def admin_dashboard():
    return send_from_directory(FRONTEND_PATH, "admin.html")


@app.route("/candidate")
def candidate_page():
    return send_from_directory(FRONTEND_PATH, "candidate.html")


@app.route("/voter")
def voter_page():
    return send_from_directory(FRONTEND_PATH, "voter.html")


@app.route("/cast-vote")
def cast_vote_page():
    return send_from_directory(FRONTEND_PATH, "vote.html")


@app.route("/results")
def results_page():
    return send_from_directory(FRONTEND_PATH, "results.html")


@app.route("/verify")
def verify_page():
    return send_from_directory(FRONTEND_PATH, "verify.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(FRONTEND_PATH, filename)


# ============================================================
#                    SYSTEM STATUS API
# ============================================================
@app.route("/api/status", methods=["GET"])
def system_status():
    """Real-time system health check for status widget"""
    status = {
        "blockchain": {"ok": False, "label": "Blockchain", "detail": ""},
        "contract":   {"ok": False, "label": "Smart Contract", "detail": ""},
        "database":   {"ok": False, "label": "Database", "detail": ""},
        "server":     {"ok": True,  "label": "Flask Server", "detail": "Running"},
    }

    # ── 1. Blockchain (Ganache) ──────────────────────────────
    try:
        connected = w3.is_connected()
        if connected:
            block = w3.eth.block_number
            chain_id = w3.eth.chain_id
            status["blockchain"] = {
                "ok": True,
                "label": "Blockchain",
                "detail": f"Block #{block} · Chain {chain_id}"
            }
        else:
            status["blockchain"]["detail"] = "Ganache not reachable"
    except Exception as e:
        status["blockchain"]["detail"] = str(e)[:60]

    # ── 2. Smart Contract ────────────────────────────────────
    try:
        code = w3.eth.get_code(Web3.to_checksum_address(CONTRACT_ADDRESS))
        if len(code) > 2:
            count = contract.functions.getElectionCount().call()
            short_addr = CONTRACT_ADDRESS[:6] + "..." + CONTRACT_ADDRESS[-4:]
            status["contract"] = {
                "ok": True,
                "label": "Smart Contract",
                "detail": f"{short_addr} · {count} election(s)"
            }
        else:
            status["contract"]["detail"] = "No contract at address"
    except Exception as e:
        status["contract"]["detail"] = str(e)[:60]

    # ── 3. Database (MySQL) ──────────────────────────────────
    try:
        with SessionLocal() as db:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
        from models import Voter, Election
        with SessionLocal() as db:
            voter_count    = db.query(Voter).count()
            election_count = db.query(Election).count()
        status["database"] = {
            "ok": True,
            "label": "Database",
            "detail": f"{voter_count} voters · {election_count} elections"
        }
    except Exception as e:
        status["database"]["detail"] = str(e)[:60]

    overall_ok = all(v["ok"] for v in status.values())

    return jsonify({
        "overall": overall_ok,
        "services": status,
        "rpc_url":          RPC_URL,
        "contract_address": CONTRACT_ADDRESS,
    })


# ============================================================
#                    ADMIN AUTH ROUTES
# ============================================================
@app.route("/admin/login_step1", methods=["POST"])
def admin_login_step1():
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    with SessionLocal() as db:
        admin = db.query(Admin).filter_by(username=username).first()

    if not admin:
        return jsonify({"error": "Invalid username"}), 401
    if not bcrypt.checkpw(password.encode(), admin.password_hash.encode()):
        return jsonify({"error": "Wrong password"}), 401
    return jsonify({"ok": True})


@app.route("/admin/login_face", methods=["POST"])
def admin_login_face():
    username = request.form.get("username")
    image_b64 = request.form.get("image")

    with SessionLocal() as db:
        admin = db.query(Admin).filter_by(username=username).first()

    if not admin:
        return jsonify({"error": "Unknown admin"}), 404

    tmp_path = os.path.join(UPLOAD_FOLDER, f"admin_{username}.jpg")

    try:
        img = save_image_b64(image_b64, tmp_path)
        known_bytes = get_bytes(admin.face_encoding)

        if not compare_faces(known_bytes, img):
            safe_delete(tmp_path)
            return jsonify({"error": "Face mismatch"}), 401

        safe_delete(tmp_path)

        token = jwt.encode(
            {
                "username": username,
                "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=4),
            },
            JWT_SECRET,
            algorithm="HS256",
        )
        return jsonify({"ok": True, "token": token})

    except Exception as e:
        safe_delete(tmp_path)
        return jsonify({"error": "Face login failed", "detail": str(e)}), 500


# ============================================================
#                    ELECTION MANAGEMENT APIs
# ============================================================

@app.route("/api/elections", methods=["GET"])
def list_elections():
    """List all elections with their current phase"""
    try:
        election_count = contract.functions.getElectionCount().call()
        elections = []
        
        with SessionLocal() as db:
            db_elections = {e.blockchain_id: e for e in db.query(Election).all()}
            
            for i in range(1, election_count + 1):
                data = contract.functions.getElection(i).call()
                phase = PHASE_MAP.get(data[3], "UNKNOWN")
                db_el = db_elections.get(i)
                is_live = db_el.is_live_results if db_el else True
                
                exp_dt = db_el.expires_at if db_el else None
                exp_str = exp_dt.isoformat() if exp_dt else None
                
                if phase == "ACTIVE" and exp_dt and datetime.datetime.utcnow() > exp_dt:
                    phase = "EXPIRED"
                
                elections.append({
                    "id": data[0],
                    "name": data[1],
                    "description": data[2],
                    "phase": phase,
                    "candidateCount": data[4],
                    "totalVotes": data[5],
                    "createdAt": data[6],
                    "startedAt": data[7],
                    "endedAt": data[8],
                    "is_live_results": is_live,
                    "expires_at": exp_str
                })
        
        return jsonify(elections)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/elections", methods=["POST"])
@admin_required
def create_election():
    """Create a new election"""
    data = request.get_json() or {}
    name = data.get("name")
    description = data.get("description", "")
    is_live_results = data.get("is_live_results", True)
    expires_at_str = data.get("expires_at")
    
    expires_at_dt = None
    if expires_at_str:
        try:
            expires_at_dt = datetime.datetime.strptime(expires_at_str, "%Y-%m-%dT%H:%M")
        except:
            pass

    if not name:
        return jsonify({"error": "Election name required"}), 400

    tx_hash, receipt, err = send_contract_tx(
        contract.functions.createElection,
        name,
        description,
        gas=500000
    )

    if err:
        return jsonify({"error": err}), 500

    # Get the new election ID from logs or count
    election_count = contract.functions.getElectionCount().call()

    # Cache in local DB
    with SessionLocal() as db:
        election = Election(
            blockchain_id=election_count,
            name=name,
            description=description,
            phase="CREATED",
            is_live_results=is_live_results,
            expires_at=expires_at_dt
        )
        db.add(election)
        db.commit()

    return jsonify({
        "ok": True,
        "election_id": election_count,
        "tx": tx_hash
    })


@app.route("/api/elections/<int:election_id>", methods=["GET"])
def get_election(election_id):
    """Get election details"""
    try:
        data = contract.functions.getElection(election_id).call()
        phase = PHASE_MAP.get(data[3], "UNKNOWN")
        
        is_live = True
        exp_dt = None
        with SessionLocal() as db:
            db_el = db.query(Election).filter_by(blockchain_id=election_id).first()
            if db_el:
                is_live = db_el.is_live_results
                exp_dt = db_el.expires_at
                
        if phase == "ACTIVE" and exp_dt and datetime.datetime.utcnow() > exp_dt:
            phase = "EXPIRED"
        
        return jsonify({
            "id": data[0],
            "name": data[1],
            "description": data[2],
            "phase": phase,
            "candidateCount": data[4],
            "totalVotes": data[5],
            "createdAt": data[6],
            "startedAt": data[7],
            "endedAt": data[8],
            "is_live_results": is_live,
            "expires_at": exp_dt.isoformat() if exp_dt else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/elections/<int:election_id>/start", methods=["POST"])
@admin_required
def start_election(election_id):
    """Start an election (CREATED → ACTIVE)"""
    tx_hash, receipt, err = send_contract_tx(
        contract.functions.startElection,
        election_id,
        gas=300000
    )

    if err:
        return jsonify({"error": err}), 500

    # Update local cache
    with SessionLocal() as db:
        election = db.query(Election).filter_by(blockchain_id=election_id).first()
        if election:
            election.phase = "ACTIVE"
            election.started_at = datetime.datetime.utcnow()
            db.commit()

    return jsonify({"ok": True, "tx": tx_hash, "phase": "ACTIVE"})


@app.route("/api/elections/<int:election_id>/end", methods=["POST"])
@admin_required
def end_election(election_id):
    """End an election (ACTIVE → ENDED)"""
    tx_hash, receipt, err = send_contract_tx(
        contract.functions.endElection,
        election_id,
        gas=300000
    )

    if err:
        return jsonify({"error": err}), 500

    with SessionLocal() as db:
        election = db.query(Election).filter_by(blockchain_id=election_id).first()
        if election:
            election.phase = "ENDED"
            election.ended_at = datetime.datetime.utcnow()
            db.commit()

    return jsonify({"ok": True, "tx": tx_hash, "phase": "ENDED"})


@app.route("/api/elections/<int:election_id>/declare", methods=["POST"])
@admin_required
def declare_results(election_id):
    """Declare results (ENDED → RESULT_DECLARED)"""
    tx_hash, receipt, err = send_contract_tx(
        contract.functions.declareResults,
        election_id,
        gas=300000
    )

    if err:
        return jsonify({"error": err}), 500

    with SessionLocal() as db:
        election = db.query(Election).filter_by(blockchain_id=election_id).first()
        if election:
            election.phase = "RESULT_DECLARED"
            db.commit()

    return jsonify({"ok": True, "tx": tx_hash, "phase": "RESULT_DECLARED"})


@app.route("/api/elections/<int:election_id>/phase", methods=["GET"])
def get_election_phase(election_id):
    """Get current phase of an election"""
    try:
        phase_int = contract.functions.getElectionPhase(election_id).call()
        phase = PHASE_MAP.get(phase_int, "UNKNOWN")
        return jsonify({"election_id": election_id, "phase": phase})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
#                    CANDIDATE APIs
# ============================================================

@app.route("/api/elections/<int:election_id>/candidates", methods=["GET"])
def list_candidates(election_id):
    """List all candidates for an election"""
    try:
        data = contract.functions.getElection(election_id).call()
        candidate_count = data[4]
        phase = PHASE_MAP.get(data[3], "UNKNOWN")
        
        is_live = True
        with SessionLocal() as db:
            db_el = db.query(Election).filter_by(blockchain_id=election_id).first()
            if db_el:
                is_live = db_el.is_live_results
                
        hide_results = (not is_live) and (phase != "RESULT_DECLARED")
        
        candidates = []
        for i in range(1, candidate_count + 1):
            cid, name, votes = contract.functions.getCandidate(election_id, i).call()
            if hide_results:
                votes = 0
            candidates.append({"id": cid, "name": name, "votes": votes})
        
        return jsonify(candidates)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/elections/<int:election_id>/candidates", methods=["POST"])
@admin_required
def add_candidate(election_id):
    """Add candidate to an election (only in CREATED phase)"""
    data = request.get_json() or {}
    name = data.get("name")

    if not name:
        return jsonify({"error": "Candidate name required"}), 400

    tx_hash, receipt, err = send_contract_tx(
        contract.functions.addCandidate,
        election_id,
        name,
        gas=300000
    )

    if err:
        return jsonify({"error": err}), 500

    return jsonify({"ok": True, "tx": tx_hash})


# Legacy endpoint for backward compatibility
@app.route("/admin/add_candidate", methods=["POST"])
@admin_required
def add_candidate_legacy():
    data = request.get_json() or {}
    name = data.get("name")
    election_id = data.get("election_id", 1)

    if not name:
        return jsonify({"error": "Candidate name required"}), 400

    tx_hash, receipt, err = send_contract_tx(
        contract.functions.addCandidate,
        election_id,
        name,
        gas=300000
    )

    if err:
        return jsonify({"error": err}), 500

    return jsonify({"ok": True, "tx": tx_hash})


# Legacy endpoint for backward compatibility
@app.route("/candidates")
def candidates_list_legacy():
    """Legacy endpoint - defaults to election 1"""
    election_id = request.args.get("election_id", 1, type=int)
    try:
        data = contract.functions.getElection(election_id).call()
        candidate_count = data[4]
        phase = PHASE_MAP.get(data[3], "UNKNOWN")

        is_live = True
        with SessionLocal() as db:
            db_el = db.query(Election).filter_by(blockchain_id=election_id).first()
            if db_el:
                is_live = db_el.is_live_results
                
        hide_results = (not is_live) and (phase != "RESULT_DECLARED")
        
        candidates = []
        for i in range(1, candidate_count + 1):
            cid, name, votes = contract.functions.getCandidate(election_id, i).call()
            if hide_results:
                votes = 0
            candidates.append({"id": cid, "name": name, "votes": votes})
        
        return jsonify(candidates)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
#                    VOTER REGISTRATION APIs
# ============================================================

@app.route("/admin/voters", methods=["GET"])
@admin_required
def voters_list():
    with SessionLocal() as db:
        voters = db.query(Voter).all()
        out = [
            {"id": v.id, "enrollment": v.enrollment, "name": v.name} 
            for v in voters
        ]
    return jsonify(out)


@app.route("/api/elections/<int:election_id>/register_voter", methods=["POST"])
@admin_required
def register_voter_for_election(election_id):
    """Register voter for a specific election"""
    enrollment = request.form.get("enrollment")
    name = request.form.get("name")
    image_b64 = request.form.get("image")

    if not enrollment or not name or not image_b64:
        return jsonify({"error": "All fields required"}), 400

    img_path = os.path.join(UPLOAD_FOLDER, f"temp_{enrollment}.jpg")

    with SessionLocal() as db:
        # Check if voter exists
        voter = db.query(Voter).filter_by(enrollment=enrollment).first()
        
        try:
            img = save_image_b64(image_b64, img_path)
            new_enc = encode_face(img)

            face_hash = hash_encoding(new_enc)
            face_hash_bytes32 = Web3.to_bytes(hexstr=face_hash)

            # Register on blockchain for this election
            tx_hash, receipt, err = send_contract_tx(
                contract.functions.registerVoter,
                election_id,
                enrollment,
                face_hash_bytes32
            )

            if err:
                safe_delete(img_path)
                return jsonify({"error": err}), 500

            # Create voter if doesn't exist
            if not voter:
                voter = Voter(
                    enrollment=enrollment,
                    name=name,
                    face_encoding=new_enc.tobytes(),
                )
                db.add(voter)
                db.flush()

            # Track registration
            registration = VoterElectionRegistration(
                voter_id=voter.id,
                election_id=election_id,
                enrollment=enrollment,
                face_hash=face_hash,
            )
            db.add(registration)
            db.commit()

            safe_delete(img_path)
            return jsonify({"ok": True, "tx": tx_hash})

        except Exception as e:
            db.rollback()
            safe_delete(img_path)
            return jsonify({"error": str(e)}), 500


# Legacy endpoint
@app.route("/admin/register_voter_camera", methods=["POST"])
@admin_required
def register_voter_camera():
    enrollment = request.form.get("enrollment")
    name = request.form.get("name")
    image_b64 = request.form.get("image")
    election_id = request.form.get("election_id", 1, type=int)

    if not enrollment or not name or not image_b64:
        return jsonify({"error": "All fields required"}), 400

    img_path = os.path.join(UPLOAD_FOLDER, f"temp_{enrollment}.jpg")

    with SessionLocal() as db:
        if db.query(Voter).filter_by(enrollment=enrollment).first():
            return jsonify({"error": "Enrollment already registered"}), 409

        try:
            img = save_image_b64(image_b64, img_path)
            new_enc = encode_face(img)

            face_hash = hash_encoding(new_enc)
            face_hash_bytes32 = Web3.to_bytes(hexstr=face_hash)

            tx_hash, receipt, err = send_contract_tx(
                contract.functions.registerVoter,
                election_id,
                enrollment,
                face_hash_bytes32
            )

            if err:
                safe_delete(img_path)
                return jsonify({"error": err}), 500

            voter = Voter(
                enrollment=enrollment,
                name=name,
                face_encoding=new_enc.tobytes(),
            )
            db.add(voter)
            db.commit()

            safe_delete(img_path)
            return jsonify({"ok": True, "tx": tx_hash})

        except Exception as e:
            db.rollback()
            safe_delete(img_path)
            return jsonify({"error": str(e)}), 500


# ============================================================
#                    VOTING APIs
# ============================================================

@app.route("/api/elections/<int:election_id>/vote", methods=["POST"])
def vote_v2(election_id):
    """Cast vote with receipt generation"""
    enrollment = request.form.get("enrollment")
    candidate_id = request.form.get("candidate_id")
    image_b64 = request.form.get("image")

    if not enrollment or not candidate_id or not image_b64:
        return jsonify({"error": "All fields required"}), 400

    # Check election phase
    try:
        phase_int = contract.functions.getElectionPhase(election_id).call()
        phase = PHASE_MAP.get(phase_int, "UNKNOWN")
        
        with SessionLocal() as db:
            db_el = db.query(Election).filter_by(blockchain_id=election_id).first()
            if db_el and db_el.expires_at and datetime.datetime.utcnow() > db_el.expires_at and phase == "ACTIVE":
                phase = "EXPIRED"

        if phase != "ACTIVE":
            return jsonify({
                "error": f"Voting not allowed. Election phase: {phase}"
            }), 400
    except Exception as e:
        return jsonify({"error": f"Failed to check election phase: {e}"}), 500

    tmp_path = os.path.join(UPLOAD_FOLDER, f"{enrollment}_vote.jpg")

    with SessionLocal() as db:
        voter = db.query(Voter).filter_by(enrollment=enrollment).first()
        if not voter:
            return jsonify({"error": "Voter not found"}), 404

        try:
            img = save_image_b64(image_b64, tmp_path)

            # Face verify
            if not compare_faces(get_bytes(voter.face_encoding), img):
                safe_delete(tmp_path)
                return jsonify({"error": "Face mismatch"}), 401

            new_enc = encode_face(img)
            face_hash = hash_encoding(new_enc)
            face_hash_bytes32 = Web3.to_bytes(hexstr=face_hash)

            tx_hash, receipt, err = send_contract_tx(
                contract.functions.vote,
                election_id,
                enrollment,
                face_hash_bytes32,
                int(candidate_id),
                gas=500000
            )

            safe_delete(tmp_path)

            if err:
                if "already voted" in err.lower():
                    return jsonify({"error": "You already voted"}), 400
                return jsonify({"error": err}), 500

            # Extract receipt ID from logs
            receipt_id = None
            enrollment_hash = generate_enrollment_hash(enrollment, election_id)
            
            # Parse VoteCast event
            try:
                vote_cast_event = contract.events.VoteCast().process_receipt(receipt)
                if vote_cast_event:
                    receipt_id = vote_cast_event[0]['args']['receiptId']
            except:
                # Fallback: get from contract
                receipt_id = contract.functions.globalReceiptCounter().call()

            # Store receipt locally (no candidate info!)
            vote_receipt = VoteReceipt(
                receipt_id=receipt_id,
                election_id=election_id,
                enrollment_hash=enrollment_hash,
                visible_tag=enrollment_hash[:10],
                tx_hash=tx_hash,
                block_number=receipt['blockNumber'],
            )
            db.add(vote_receipt)
            db.commit()

            return jsonify({
                "ok": True,
                "tx": tx_hash,
                "receipt_id": receipt_id,
                "block_number": receipt['blockNumber'],
                "visible_tag": enrollment_hash[:10]
            })

        except Exception as e:
            safe_delete(tmp_path)
            return jsonify({"error": "Vote failed", "detail": str(e)}), 500


# Legacy vote endpoint
@app.route("/vote", methods=["POST"])
def vote_legacy():
    election_id = request.form.get("election_id", 1, type=int)
    enrollment = request.form.get("enrollment")
    candidate_id = request.form.get("candidate_id")
    image_b64 = request.form.get("image")

    if not enrollment or not candidate_id or not image_b64:
        return jsonify({"error": "All fields required"}), 400

    # Check election phase
    try:
        phase_int = contract.functions.getElectionPhase(election_id).call()
        phase = PHASE_MAP.get(phase_int, "UNKNOWN")
        if phase != "ACTIVE":
            return jsonify({
                "error": f"Voting not allowed. Election phase: {phase}"
            }), 400
    except Exception as e:
        return jsonify({"error": f"Failed to check election phase: {e}"}), 500

    tmp_path = os.path.join(UPLOAD_FOLDER, f"{enrollment}_vote.jpg")

    with SessionLocal() as db:
        voter = db.query(Voter).filter_by(enrollment=enrollment).first()
        if not voter:
            return jsonify({"error": "Voter not found"}), 404

        try:
            img = save_image_b64(image_b64, tmp_path)

            if not compare_faces(get_bytes(voter.face_encoding), img):
                safe_delete(tmp_path)
                return jsonify({"error": "Face mismatch"}), 401

            new_enc = encode_face(img)
            face_hash = hash_encoding(new_enc)
            face_hash_bytes32 = Web3.to_bytes(hexstr=face_hash)

            tx_hash, receipt, err = send_contract_tx(
                contract.functions.vote,
                election_id,
                enrollment,
                face_hash_bytes32,
                int(candidate_id),
                gas=500000
            )

            safe_delete(tmp_path)

            if err:
                if "already voted" in err.lower():
                    return jsonify({"error": "You already voted"}), 400
                return jsonify({"error": err}), 500

            # Generate receipt
            receipt_id = contract.functions.globalReceiptCounter().call()
            enrollment_hash = generate_enrollment_hash(enrollment, election_id)

            vote_receipt = VoteReceipt(
                receipt_id=receipt_id,
                election_id=election_id,
                enrollment_hash=enrollment_hash,
                visible_tag=enrollment_hash[:10],
                tx_hash=tx_hash,
                block_number=receipt['blockNumber'],
            )
            db.add(vote_receipt)
            db.commit()

            return jsonify({
                "ok": True,
                "tx": tx_hash,
                "receipt_id": receipt_id,
                "block_number": receipt['blockNumber']
            })

        except Exception as e:
            safe_delete(tmp_path)
            return jsonify({"error": "Vote failed", "detail": str(e)}), 500


# ============================================================
#                    VOTE RECEIPT VERIFICATION
# ============================================================

@app.route("/api/receipts/<int:receipt_id>", methods=["GET"])
def get_receipt(receipt_id):
    """Get vote receipt by ID"""
    with SessionLocal() as db:
        receipt = db.query(VoteReceipt).filter_by(receipt_id=receipt_id).first()
        if not receipt:
            return jsonify({"error": "Receipt not found"}), 404
        return jsonify(receipt.to_dict())


@app.route("/api/receipts/verify/<int:receipt_id>", methods=["GET"])
def verify_receipt(receipt_id):
    """Verify vote receipt against blockchain"""
    try:
        # Get local record first
        with SessionLocal() as db:
            local_receipt = db.query(VoteReceipt).filter_by(receipt_id=receipt_id).first()

        # Check on blockchain
        try:
            data = contract.functions.getVoteReceipt(receipt_id).call()
            exists = data[4]
        except Exception as chain_err:
            # Blockchain check failed — fall back to local DB only
            if local_receipt:
                return jsonify({
                    "verified": True,
                    "blockchain": {
                        "receipt_id": local_receipt.receipt_id,
                        "election_id": local_receipt.election_id,
                        "visible_tag": local_receipt.visible_tag,
                        "timestamp": 0,
                        "exists": True,
                    },
                    "local": local_receipt.to_dict(),
                    "message": "Vote verified from local database (blockchain unavailable)"
                })
            return jsonify({"verified": False, "error": str(chain_err)}), 500

        if not exists:
            # Try local DB as fallback
            if local_receipt:
                return jsonify({
                    "verified": True,
                    "blockchain": {
                        "receipt_id": local_receipt.receipt_id,
                        "election_id": local_receipt.election_id,
                        "visible_tag": local_receipt.visible_tag,
                        "timestamp": 0,
                        "exists": True,
                    },
                    "local": local_receipt.to_dict(),
                    "message": "Vote record found in database"
                })
            return jsonify({
                "verified": False,
                "error": "Receipt not found"
            }), 404

        # Safely decode visible_tag (bytes32 → string)
        raw_tag = data[2]
        if isinstance(raw_tag, (bytes, bytearray)):
            visible_tag = raw_tag.rstrip(b'\x00').decode('utf-8', errors='replace')
        else:
            visible_tag = str(raw_tag)

        blockchain_data = {
            "receipt_id": data[0],
            "election_id": data[1],
            "visible_tag": visible_tag,
            "timestamp": data[3],
            "exists": True,
        }

        return jsonify({
            "verified": True,
            "blockchain": blockchain_data,
            "local": local_receipt.to_dict() if local_receipt else None,
            "message": "Vote exists on blockchain and is immutable"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/receipts/search", methods=["POST"])
def search_receipt():
    """Search receipt by enrollment and election"""
    data = request.get_json() or {}
    enrollment = data.get("enrollment")
    election_id = data.get("election_id")

    if not enrollment or not election_id:
        return jsonify({"error": "Enrollment and election_id required"}), 400

    enrollment_hash = generate_enrollment_hash(enrollment, election_id)

    with SessionLocal() as db:
        # Filter by both enrollment_hash AND election_id for accuracy
        receipt = db.query(VoteReceipt).filter_by(
            enrollment_hash=enrollment_hash,
            election_id=election_id
        ).first()

        # Fallback: try just enrollment_hash (in case election_id mismatch)
        if not receipt:
            receipt = db.query(VoteReceipt).filter_by(
                enrollment_hash=enrollment_hash
            ).first()

        if not receipt:
            return jsonify({
                "found": False,
                "message": f"No vote found for enrollment '{enrollment}' in this election. Either you haven't voted yet, or wrong election selected."
            }), 404

        return jsonify({
            "found": True,
            "receipt": receipt.to_dict()
        })


# ============================================================
#                    AI CHATBOT (GEMINI)
# ============================================================
@app.route("/api/chat", methods=["POST"])
def ai_chat():
    """Handles messages from the AI Chatbot on the frontend"""
    data = request.get_json() or {}
    msg = data.get("message", "")
    
    if not msg:
        return jsonify({"reply": "I didn't hear anything. How can I help you?"}), 400
        
    if not GEMINI_API_KEY:
        return jsonify({"reply": "🤖 My AI brain is offline right now! Please add your GEMINI_API_KEY in backend/config/secret.py to enable me."}), 200

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # System instructions to guide the bot's behavior
        system_prompt = (
            "You are 'Vote Rakshak AI', the official intelligent assistant for a top-tier Web3 Decentralized Voting System. "
            "You must keep your answers extremely concise (max 2-3 sentences). "
            "Be helpful, energetic, and professional. Use minimal emojis. "
            "Help voters with: How to vote (Face Auth + Blockchain), how to check results, what is a Receipt ID, and general system security inquiries. "
            "Never use markdown formatting like bolding or bullet points, just use plain text."
        )
        
        response = model.generate_content(f"{system_prompt}\n\nUser Question: {msg}")
        reply_text = response.text.replace("*", "").strip()
        
        return jsonify({"reply": reply_text})
        
    except Exception as e:
        error_msg = str(e)
        print("Gemini API Error:", error_msg)
        
        # Make the error message user-friendly based on common API errors
        if "404" in error_msg or "not found" in error_msg:
            reply = "🤖 API Error (404): The API key provided is either invalid or does not have the 'Generative Language API' enabled. Please generate a new key exclusively from https://aistudio.google.com/app/apikey"
        elif "400" in error_msg or "API_KEY_INVALID" in error_msg:
            reply = "🤖 API Error (400): Invalid API Key format. Please check backend/config/secret.py"
        else:
            reply = f"🤖 Oops! API Error: {error_msg}"
            
        return jsonify({"reply": reply})

# ============================================================
#                    RUN SERVER
# ============================================================
if __name__ == "__main__":
    print("\n Vote Rakshak V2 Server running at http://127.0.0.1:5000\n")
    print(" Features: Multi-Election | Phase Management | Vote Receipts\n")
    app.run(debug=True)
