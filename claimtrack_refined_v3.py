# ==============================================================
# DGACE-ESD Claim Track  (v3.6)
# ==============================================================
# Features:
#   ✅ Multi-specialization for Auditors (Medical, Travel, LTC, Other)
#   ✅ Role-based menus (Claimants vs Officials)
#   ✅ Awaiting Budget stage
#   ✅ Dashboard with auto-visuals
#   ✅ Admin password reset, user deactivate
# ==============================================================

import os, time, random, string
from datetime import datetime
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from werkzeug.security import generate_password_hash, check_password_hash


# ==============================================================
# 🔧 MAINTENANCE MODE (Enable this when DB compute hours are exhausted)
# ==============================================================
MAINTENANCE_MODE = False   # Set to False once compute is restored

if MAINTENANCE_MODE:
    st.title("🔧 ClaimTrack – Under Maintenance")
    st.warning("""
    The ClaimTrack system is temporarily unavailable  
    while compute resources are being restored.

    Please check back soon.
    """)
    st.stop()
# ==============================================================

# ---------------- CONFIG -----------------
from sqlalchemy.pool import NullPool

DEFAULT_SQLITE = "sqlite:///data/claims_refined_v3.db"
DB_URL = os.environ.get("DATABASE_URL", DEFAULT_SQLITE)
os.makedirs("data", exist_ok=True)

# Use NullPool for Neon / serverless DBs to allow autosuspend
engine = create_engine(
    DB_URL,
    echo=False,
    future=True,
    poolclass=NullPool
)

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

WORKFLOW_CHAIN = ["Diarist", "Auditor", "AAO", "SAO", "Director", "DDO"]
AWAITING_ROLES = ["Auditor", "AAO", "SAO"]

# ---------------- MODELS -----------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String, index=True)
    password_hash = Column(String)
    role = Column(String)
    specialization = Column(String, default="All")  # Multi-select specializations
    location = Column(String)
    phone = Column(String)
    official_id = Column(String)
    is_admin = Column(Boolean, default=False)
    active = Column(Boolean, default=True)

class Claim(Base):
    __tablename__ = "claims"
    id = Column(Integer, primary_key=True)
    uid = Column(String, unique=True, index=True)
    submitter_id = Column(Integer, ForeignKey("users.id"))
    submitter = relationship("User", foreign_keys=[submitter_id])
    claim_type = Column(String)
    amount = Column(Float)
    date_of_bill = Column(String)
    remarks = Column(Text)
    created_at = Column(DateTime, default=func.now())
    status = Column(String, default="Pending")
    current_stage = Column(String, default="Diarist")
    location = Column(String)
    archived = Column(Boolean, default=False)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_user = relationship("User", foreign_keys=[assigned_to])

class WorkflowLog(Base):
    __tablename__ = "workflow_logs"
    id = Column(Integer, primary_key=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=True)
    claim = relationship("Claim", foreign_keys=[claim_id])
    stage = Column(String)
    action = Column(String)
    remarks = Column(Text)
    acted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    timestamp = Column(DateTime, default=func.now())

# ---------------- DATABASE INITIALIZATION -----------------
# Only create tables for local SQLite (DEV).
# Do NOT touch Neon DB schema on every app start.
if DB_URL.startswith("sqlite"):
    try:
        Base.metadata.create_all(engine)
    except Exception as e:
        print("⚠️ Database initialization error:", e)




def get_db(): return SessionLocal()
def make_uid():
    return "CT-" + datetime.now().strftime("%Y%m%d") + "-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
def has_role(user_roles, role):
    if not user_roles: return False
    roles = [r.strip() for r in user_roles.split(",")]
    return role in roles or "Admin" in roles
def get_next_role(role):
    try:
        idx = WORKFLOW_CHAIN.index(role)
        return WORKFLOW_CHAIN[idx + 1] if idx + 1 < len(WORKFLOW_CHAIN) else None
    except ValueError:
        return None
def get_prev_role(role):
    try:
        idx = WORKFLOW_CHAIN.index(role)
        return WORKFLOW_CHAIN[idx - 1] if idx - 1 >= 0 else None
    except ValueError:
        return None

def find_specialized_officer(db, location, claim_type):
    """Find auditor whose specialization list includes the claim type."""
    auditors = db.query(User).filter(
        User.role.like("%Auditor%"),
        User.location == location,
        User.active == True
    ).all()
    for officer in auditors:
        if officer.specialization == "All":
            return officer
        specs = [s.strip().lower() for s in officer.specialization.split(",")]
        if claim_type.lower() in specs:
            return officer
    return auditors[0] if auditors else None

# ---------------- STREAMLIT CONFIG -----------------
st.set_page_config(page_title="DGACE-ESD Bill Tracking System", layout="wide")
st.title("DGACE-ESD Bill Tracking System")

if "user" not in st.session_state:
    st.session_state["user"] = None


# Seed admin ONLY when a real user session exists
if not MAINTENANCE_MODE and st.session_state.get("user"):
    db = get_db()
    if not db.query(User).filter(User.email == "admin@org.in").first():
        db.add(User(
            name="Admin",
            email="admin@org.in",
            password_hash=generate_password_hash("admin123"),
            role="Admin",
            location="New Delhi",
            specialization="All",
            is_admin=True
        ))
        db.commit()
    db.close()


# ---------------- LOGIN/SIGNUP -----------------
def login():
    st.subheader("Login")
    email = st.text_input("Email", key="login_email")
    pwd = st.text_input("Password", type="password", key="login_pwd")
    if st.button("Login", key="login_btn"):
        db = get_db()
        user = db.query(User).filter(User.email == email, User.active == True).first()
        if user and check_password_hash(user.password_hash, pwd):
            st.session_state["user"] = {"id": user.id, "name": user.name,
                "email": user.email, "role": user.role,
                "location": user.location, "is_admin": user.is_admin}
            st.success("✅ Login successful! Redirecting...")
            time.sleep(1); st.rerun()
        else:
            st.error("Invalid credentials")
        db.close()

def signup():
    st.subheader("Claimant Sign-Up")
    name = st.text_input("Full name", key="signup_name")
    email = st.text_input("Email", key="signup_email")
    pwd = st.text_input("Password", type="password", key="signup_pwd")
    loc = st.selectbox("Location", ["New Delhi","Mumbai","Kolkata","Chennai","Bangalore"], key="signup_loc")
    if st.button("Sign Up", key="signup_btn"):
        db = get_db()
        if db.query(User).filter(User.email == email).first():
            st.error("Email already exists")
        else:
            db.add(User(name=name, email=email,
                password_hash=generate_password_hash(pwd),
                role="Claimant", location=loc))
            db.commit()
            st.success("Account created successfully!")
        db.close()

if not st.session_state["user"]:
    col1, col2 = st.columns(2)
    with col1: login()
    with col2: signup()
    st.stop()

db = get_db()
user = db.query(User).get(st.session_state["user"]["id"])

# ---------------- SIDEBAR -----------------
if user.role == "Claimant":
    menu = ["Submit Claim", "My Claims"]
else:
    menu = ["Pending With Me", "My Claims"]
    if has_role(user.role, "Director") or has_role(user.role, "DG"):
        menu.append("Dashboard")
    if user.is_admin:
        menu.append("Admin")

choice = st.sidebar.selectbox("Menu", menu)
st.sidebar.info(f"{user.name} ({user.role}) – {user.location}")

if st.sidebar.button("Logout", key="logout_btn"):
    st.session_state.clear()
    st.success("✅ Successfully logged out!")
    time.sleep(1)
    st.rerun()

# ---------------- ADMIN PANEL -----------------
if choice == "Admin":
    if not user.is_admin:
        st.error("Admin only"); st.stop()
    st.header("Admin Panel")
    st.subheader("Create/Assign Roles")
    name = st.text_input("Name", key="admin_name")
    email = st.text_input("Email", key="admin_email")
    pwd = st.text_input("Password", type="password", key="admin_pwd")
    role = st.selectbox("Role", ["Diarist","Auditor","AAO","SAO","Director","DDO","Claimant"], key="admin_role")
    loc = st.selectbox("Location", ["New Delhi","Mumbai","Kolkata","Chennai","Bangalore"], key="admin_loc")

    if role == "Auditor":
        spec_list = st.multiselect(
            "Specialization (select multiple)",
            ["Medical", "Travel", "LTC", "Other"],
            default=["Medical"], key="admin_spec_multi"
        )
        spec = ",".join(spec_list) if spec_list else "All"
    else:
        spec = "All"

    phone = st.text_input("Phone", key="admin_phone")
    if st.button("Add/Update User", key="admin_add"):
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            existing.role, existing.specialization, existing.location, existing.phone = role, spec, loc, phone
            db.commit(); st.success("User updated successfully")
        else:
            db.add(User(name=name or email, email=email,
                password_hash=generate_password_hash(pwd),
                role=role, specialization=spec,
                location=loc, phone=phone))
            db.commit(); st.success("User added successfully")
    st.markdown("---")
    st.subheader("Reset Password")
    reset_email = st.text_input("Email to reset", key="reset_email")
    new_pwd = st.text_input("New password", type="password", key="reset_pwd")
    if st.button("Reset Password", key="reset_btn"):
        target = db.query(User).filter(User.email == reset_email).first()
        if target:
            target.password_hash = generate_password_hash(new_pwd)
            db.commit(); st.success("Password reset successfully")
        else:
            st.error("User not found")

    st.markdown("---")

    st.subheader("Activate / Deactivate User")

    users = db.query(User).filter(User.is_admin == False).order_by(User.name).all()

    def user_label(u):
        status = "🟢 Active" if u.active else "🔴 Inactive"
        return f"{u.name} ({u.email}) – {u.role} – {u.specialization} – {status}"

    selected_label = st.selectbox(
        "Select user",
        [user_label(u) for u in users]
    )

    selected_user = next(u for u in users if user_label(u) == selected_label)

    action_label = "Deactivate User" if selected_user.active else "Reactivate User"
    button_color = "secondary" if selected_user.active else "primary"

    if st.button(action_label, key="toggle_user_btn", type=button_color):
        selected_user.active = not selected_user.active
        db.commit()
        st.success(
            f"User {'deactivated' if not selected_user.active else 'reactivated'} successfully."
        )
        st.rerun()

                
    st.markdown("---")
    st.dataframe(pd.read_sql(db.query(User).statement, db.bind)[["id","name","email","role","specialization","location","active"]])
    
    # ------------------------------------------------------------------
    # ARCHIVE / RESTORE CLAIMS SECTION
    # ------------------------------------------------------------------
    st.markdown("---")
    st.subheader("📁 Archive / Restore Claims")

    tab1, tab2 = st.tabs(["🟢 Active Claims", "🗄️ Archived Claims"])

    # ---------------- ACTIVE CLAIMS (ARCHIVE) ----------------
    with tab1:
        st.write("Select claims to archive:")

        active_claims = db.query(Claim).filter(Claim.archived == False).all()

        if active_claims:
            selected_to_archive = st.multiselect(
                "Active Claims:",
                options=[c.id for c in active_claims],
                format_func=lambda cid: next(
                    f"{c.uid} — {c.claim_type} — ₹{c.amount} — {c.submitter.name if c.submitter else 'Unknown'} — {c.current_stage}"
                    for c in active_claims if c.id == cid
                )

            )

            if st.button("📦 Archive Selected Claims", type="primary"):
                if selected_to_archive:
                    for cid in selected_to_archive:
                        claim = db.query(Claim).get(cid)
                        claim.archived = True
                    db.commit()
                    st.success("Selected claims archived successfully.")
                    st.rerun()
                else:
                    st.warning("No claim selected.")
        else:
            st.info("No active claims found.")

    # ---------------- ARCHIVED CLAIMS (RESTORE) ----------------
    with tab2:
        st.write("Select archived claims to restore:")

        archived_claims = db.query(Claim).filter(Claim.archived == True).all()

        if archived_claims:
            selected_to_restore = st.multiselect(
                "Archived Claims:",
                options=[c.id for c in archived_claims],
                format_func=lambda cid: next(
                    f"{c.uid} — {c.claim_type} — ₹{c.amount} — {c.submitter.name if c.submitter else 'Unknown'} — ARCHIVED"
                    for c in archived_claims if c.id == cid
                )

            )

            if st.button("♻️ Restore Selected Claims"):
                if selected_to_restore:
                    for cid in selected_to_restore:
                        claim = db.query(Claim).get(cid)
                        claim.archived = False
                    db.commit()
                    st.success("Selected claims restored successfully.")
                    st.rerun()
                else:
                    st.warning("No claim selected.")
        else:
            st.info("No archived claims found.")


    db.close(); st.stop()

# ---------------- SUBMIT CLAIM -----------------
if choice == "Submit Claim":
    st.header("Submit New Claim")

    with st.form("new_claim"):
        ctype = st.selectbox("Claim Type", ["Medical", "Travel", "LTC", "Other"], key="submit_type")
        amt = st.number_input("Amount (₹)", min_value=0.0, key="submit_amt")
        dob = st.date_input("Bill Date", key="submit_dob")
        remarks = st.text_area("Remarks (optional)", key="submit_remarks")

        submit = st.form_submit_button("Submit Claim", key="submit_claim_btn")

    if submit:

        # ----------- VALIDATION ------------
        if amt <= 0:
            st.error("Please enter a valid amount")
            st.stop()

        # -------------------------------------------------------------
        # 1️⃣ DUPLICATE CHECK: Amount + Bill Date + Type + User
        # -------------------------------------------------------------
        duplicate = db.query(Claim).filter(
            Claim.submitter_id == user.id,
            Claim.amount == amt,
            Claim.date_of_bill == str(dob),
            Claim.claim_type == ctype
        ).first()

        if duplicate:
            st.warning(
                f"A similar claim already exists:\n\n"
                f"• Claim ID: {duplicate.uid}\n"
                f"• Type: {ctype}\n"
                f"• Amount: ₹{amt}\n"
                f"• Bill Date: {dob}\n\n"
                "If this was accidental, press *Cancel*. "
                "If intentional, click *Submit Anyway* to continue."
            )

            col1, col2 = st.columns(2)
            with col1:
                proceed = st.button("Submit Anyway")
            with col2:
                cancel = st.button("Cancel")

            if cancel:
                st.info("Submission cancelled.")
                st.stop()

            if not proceed:
                st.stop()       # Stop until user decides

        # -------------------------------------------------------------
        # 2️⃣ PROCEED WITH NORMAL CLAIM CREATION
        # -------------------------------------------------------------

        uid = make_uid()
        claim = Claim(
            uid=uid,
            submitter_id=user.id,
            claim_type=ctype,
            amount=amt,
            date_of_bill=str(dob),
            remarks=remarks,
            location=user.location,
            status="Pending",
            current_stage="Diarist"
        )

        # Do NOT skip Diarist on initial submission
        claim.current_stage = "Diarist"
        claim.assigned_to = None

        db.add(claim)
        db.commit()

        # Workflow log (unchanged)
        db.add(WorkflowLog(
            claim_id=claim.id,
            stage="Employee",
            action="Submitted",
            remarks="Initial submission",
            acted_by=user.id
        ))
        db.commit()

        st.success(
            f"Claim {uid} submitted successfully and registered with Diarist. "
            "It will be routed to the appropriate Auditor shortly."
        )


        db.close()
        st.stop()


# ---------------- MY CLAIMS -----------------
if choice == "My Claims":
    st.header("My Claims Overview")
    claims = db.query(Claim).filter(
        Claim.submitter_id == user.id, Claim.archived == False
    ).order_by(Claim.created_at.desc()).all()
    if not claims:
        st.info("No claims found.")
    else:
        for c in claims:
            status = "🟠 Awaiting Budget" if c.current_stage == "Awaiting Budget" else c.status
            assigned = db.query(User).get(c.assigned_to).name if c.assigned_to else "Unassigned"
            st.markdown(f"**UID:** {c.uid} | **Type:** {c.claim_type} | **Amount:** ₹{c.amount} | "
                        f"**Stage:** {c.current_stage} | **Status:** {status} | **Assigned:** {assigned}")
            
            # ------------------------------------------------------------
            # ⭐ NEW FEATURE: RESUBMIT CLAIM IF RETURNED TO EMPLOYEE
            # ------------------------------------------------------------
            if c.current_stage == "Employee" and c.status == "Returned":
                st.warning("This claim has been returned for correction.")

                if st.button(f"🔄 Resubmit Claim {c.uid}", key=f"resub_{c.id}"):
                    c.current_stage = "Diarist"          # Send back into workflow
                    c.status = "Pending"

                    db.add(WorkflowLog(
                        claim_id=c.id,
                        stage="Employee",
                        action="Resubmitted",
                        remarks="Claim resubmitted after correction",
                        acted_by=user.id
                    ))
                    db.commit()

                    st.success("Claim resubmitted successfully! It has been sent to Diarist.")
                    st.rerun()

            
            logs = db.query(WorkflowLog).filter(WorkflowLog.claim_id == c.id).order_by(WorkflowLog.timestamp).all()
            if logs:
                df = pd.DataFrame([
                    {
                        "Stage": L.stage, "Action": L.action, "Remarks": L.remarks,
                        "By": db.query(User).get(L.acted_by).name if db.query(User).get(L.acted_by) else "System",
                        "Time": L.timestamp
                    } for L in logs
                ])
                st.dataframe(df)
    db.close(); st.stop()

# ---------------- PENDING WITH ME -----------------
if choice == "Pending With Me":
    st.header("Claims Pending With Me")
    roles = [r.strip() for r in (user.role or "").split(",")]
    for role_item in roles:
        if role_item not in WORKFLOW_CHAIN:
            continue
        st.subheader(f"As {role_item} — Location: {user.location}")
        q = db.query(Claim).filter(Claim.archived == False)
        q_stage = q.filter(Claim.current_stage == role_item)
        awaiting_q = q.filter(Claim.current_stage == "Awaiting Budget")
        if not has_role(user.role, "DG") and not user.is_admin:
            q_stage = q_stage.filter(Claim.location == user.location)
            awaiting_q = awaiting_q.filter(Claim.location == user.location)
        if role_item == "Auditor":
            rows_stage = q_stage.filter(
                (Claim.assigned_to == user.id) | (Claim.assigned_to == None)
            ).order_by(Claim.created_at).all()
            if user.specialization != "All":
                specs = [s.strip().lower() for s in user.specialization.split(",")]
                rows_stage = [c for c in rows_stage if (c.assigned_to == user.id) or (c.claim_type.lower() in specs)]
        else:
            rows_stage = q_stage.order_by(Claim.created_at).all()
        rows_awaiting = []
        if has_role(user.role, "DG") or user.is_admin or role_item in AWAITING_ROLES:
            rows_awaiting = awaiting_q.order_by(Claim.created_at).all()
            if role_item == "Auditor":
                rows_awaiting = [
                    c for c in rows_awaiting
                    if (c.assigned_to == user.id)
                    or (c.assigned_to is None and (user.specialization == "All" or c.claim_type.lower() in specs))
                ]
        rows = rows_stage + rows_awaiting
        if not rows:
            st.info("No pending items.")
        else:
            for c in rows:
                submitter_name = c.submitter.name if c.submitter else "Deleted user"

                st.markdown(
                    f"**Claimant:** {submitter_name}  \n"
                    f"**UID:** {c.uid} | **Type:** {c.claim_type} | **Amount:** ₹{c.amount} | **Stage:** {c.current_stage}"
                )

                with st.form(f"form_{c.id}"):
                    # Base action for everyone
                    action_opts = ["Send back for review"]

                    # Forward only for non-Director levels
                    if role_item not in ["Director"] and not has_role(user.role, "DG"):
                        action_opts.insert(0, "Forward for approval")

                    # Approval only for Director / DG
                    if role_item in ["Director"] or has_role(user.role, "DG"):
                        action_opts.append("Mark Approved (complete)")

                    if role_item in AWAITING_ROLES:
                        action_opts.append("Mark Awaiting Budget")
                    if c.current_stage == "Awaiting Budget" and role_item in AWAITING_ROLES:
                        action_opts.append("Unpark and Forward")
                    action = st.selectbox("Action", action_opts, key=f"actsel_{c.id}")
                    remarks = st.text_area("Remarks (required)", key=f"actrem_{c.id}")
                    assign_to_option = None
                    if action == "Forward for approval" and get_next_role(role_item) == "Auditor":
                        auditors = db.query(User).filter(
                            User.role.like("%Auditor%"),
                            User.location == c.location,
                            User.active == True
                        ).all()
                        options = [f"{a.id} – {a.name} ({a.specialization})" for a in auditors]
                        assign_choice = st.selectbox("Assign to Auditor", options, key=f"assign_{c.id}")
                        assign_to_option = int(assign_choice.split(" – ")[0]) if assign_choice else None
                    submit = st.form_submit_button("Confirm Action", key=f"confirm_{c.id}")
                    if submit:
                        if not remarks.strip():
                            st.error("Remarks are required.")
                        else:
                            nxt = get_next_role(role_item)
                            if action == "Forward for approval":
                                if nxt == "Auditor":
                                    target = db.query(User).get(assign_to_option) if assign_to_option else find_specialized_officer(db, c.location, c.claim_type)
                                    c.assigned_to = target.id if target else None
                                    c.current_stage = "Auditor"
                                else:
                                    c.current_stage = nxt or "AwaitingPayment"
                                c.status = "In Progress"
                                db.add(WorkflowLog(claim_id=c.id, stage=role_item,
                                                   action=f"Forwarded to {c.current_stage}", remarks=remarks,
                                                   acted_by=user.id))
                            elif action == "Send back for review":
                                c.current_stage = get_prev_role(role_item) or "Employee"
                                c.status = "Returned"
                                db.add(WorkflowLog(claim_id=c.id, stage=role_item,
                                                   action=f"Returned to {c.current_stage}",
                                                   remarks=remarks, acted_by=user.id))
                            elif action == "Mark Awaiting Budget":
                                c.current_stage = "Awaiting Budget"
                                c.status = "Awaiting Budget"
                                db.add(WorkflowLog(claim_id=c.id, stage=role_item,
                                                   action="Marked Awaiting Budget", remarks=remarks,
                                                   acted_by=user.id))
                            elif action == "Unpark and Forward":
                                c.current_stage = get_next_role(role_item) or "DDO"
                                c.status = "In Progress"
                                db.add(WorkflowLog(claim_id=c.id, stage="Awaiting Budget",
                                                   action=f"Unparked to {c.current_stage}",
                                                   remarks=remarks, acted_by=user.id))
                            elif action == "Mark Approved (complete)":
                                c.current_stage = "AwaitingPayment"
                                c.status = "Approved"
                                db.add(WorkflowLog(claim_id=c.id, stage=role_item,
                                                   action="Final Approval", remarks=remarks,
                                                   acted_by=user.id))
                            db.commit()
                            st.success("✅ Action processed successfully.")
    db.close(); st.stop()

# ---------------- DASHBOARD -----------------
if choice == "Dashboard":
    if not (has_role(user.role, "Director") or has_role(user.role, "DG")):
        st.error("Dashboard restricted."); st.stop()
    st.header("Dashboard")
    cols = st.columns(4)
    with cols[0]:
        loc = st.selectbox("Location", ["All","New Delhi","Mumbai","Kolkata","Chennai","Bangalore"], key="dash_loc")
    with cols[1]:
        ctype = st.selectbox("Claim Type", ["All","Medical","Travel","LTC","Other"], key="dash_type")
    with cols[2]:
        stage = st.selectbox("Stage", ["All"] + WORKFLOW_CHAIN + ["Awaiting Budget","Returned","Approved"], key="dash_stage")
    with cols[3]:
        min_days = st.number_input("Minimum Days Pending", min_value=0, value=0, key="dash_mindays")
    q = db.query(Claim).filter(Claim.archived == False)

    # Restrict Director to own location (DG/Admin see all)
    if has_role(user.role, "Director") and not has_role(user.role, "DG") and not user.is_admin:
        q = q.filter(Claim.location == user.location)

    if loc != "All": q = q.filter(Claim.location == loc)
    if ctype != "All": q = q.filter(Claim.claim_type == ctype)
    if stage != "All": q = q.filter(Claim.current_stage == stage)
    claims = q.all()
    data = []
    for c in claims:
        days = (datetime.now() - c.created_at).days if c.created_at else 0
        if days >= min_days:
            assigned = db.query(User).get(c.assigned_to).name if c.assigned_to else "Unassigned"
            data.append({
                "UID": c.uid,
                "Claimant": c.submitter.name if c.submitter else "Deleted user",
                "Type": c.claim_type,
                "Amount": c.amount,
                "Stage": c.current_stage,
                "Status": c.status,
                "Location": c.location,
                "Days": days,
                "Assigned": assigned
            })

    if not data:
        st.info("No matching claims found.")
    else:
        df = pd.DataFrame(data)
        tab1, tab2 = st.tabs(["📋 Summary", "📊 Visuals"])
        with tab1:
            st.dataframe(df)
            st.subheader("Average Processing Time per Role")
            logs = pd.read_sql(db.query(WorkflowLog).statement, db.bind)
            if not logs.empty:
                logs["timestamp"] = pd.to_datetime(logs["timestamp"])
                logs["prev"] = logs.groupby("claim_id")["timestamp"].shift(1)
                logs["delta_days"] = (logs["timestamp"] - logs["prev"]).dt.total_seconds() / 86400
                avg = logs.groupby("stage")["delta_days"].mean().reset_index().dropna()
                if not avg.empty:
                    st.dataframe(avg.rename(columns={"stage": "Role", "delta_days": "Avg Days"}))
        with tab2:
            df["flag"] = df["Stage"].apply(lambda x: "Awaiting Budget" if x == "Awaiting Budget" else "Other")
            st.plotly_chart(px.bar(df, x="Stage", color="flag", title="Claims by Stage (🟠 Awaiting Budget Highlighted)"))
            st.plotly_chart(px.pie(df, names="Type", title="Claims by Type"))
            st.plotly_chart(px.bar(df, x="Location", y="Amount", title="Total Amount by Location"))
    db.close(); st.stop()

st.caption("DGACE-ESD Bill Tracking System – Multi-specialization + Role Segregation + Dashboard Enhancements")
