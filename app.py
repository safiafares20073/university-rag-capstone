import base64
from copy import deepcopy
import hmac
import os
import re
import sqlite3
from uuid import uuid4
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
ROBOT_PATH = PROJECT_DIR / "assets" / "robot.png"
load_dotenv(PROJECT_DIR / ".env")

st.set_page_config(page_title="المساعد الجامعي", page_icon="🎓", layout="centered",
                   initial_sidebar_state="auto")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Amiri:wght@400;700&display=swap');
.stApp {background: radial-gradient(ellipse at 50% 12%, #11234a 0, #040d1d 48%); color:#edf4ff;}
.stApp, .stApp button, .stApp input, .stApp textarea,
.stApp h1, .stApp h2, .stApp h3 {font-family:'Amiri', serif;}
.stMainBlockContainer {max-width:820px; padding-top:4.5rem;}
[data-testid="stHeader"] {background:transparent;}
[data-testid="stAppDeployButton"],
.stDeployButton, [data-testid="stDecoration"] {display:none;}
#MainMenu {display:none;}
/* نخفي Deploy فقط؛ يبقى شريط التحكم متاحًا لفتح القائمة. */
[data-testid="stToolbar"] {visibility:visible !important;}
[data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] {
    display:flex !important; visibility:visible !important; opacity:1 !important;
    position:fixed !important; top:.65rem !important; left:.75rem !important;
    z-index:10000 !important;}
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="collapsedControl"] button {
    display:flex !important; align-items:center; gap:.4rem;
    visibility:visible !important; opacity:1 !important;
    min-width:100px; min-height:44px; padding:.35rem .75rem;
    border:1px solid #4168b0; border-radius:12px;
    background:#112347 !important; color:#edf4ff !important;}
[data-testid="stSidebarCollapsedControl"] button::after,
[data-testid="collapsedControl"] button::after {
    content:"القائمة"; font-family:'Amiri',serif; font-size:1.1rem;}
[data-testid="stSidebar"] {background:#0b1528; direction:rtl;}
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label {text-align:right;}
.brand {direction:rtl; text-align:center; margin:0 0 1rem;}
.brand h1 {font-size:2rem; margin:0; padding:0; color:#f1f6ff;}
.brand p {color:#97afce; font-size:1.05rem; margin:.2rem 0;}
.hero {text-align:center; direction:rtl; margin:1rem 0 1.5rem;}
.robot-ring {width:240px; height:240px; margin:0 auto 1.1rem; border-radius:50%;
    padding:4px; background:linear-gradient(140deg,#58bcff,#4165ff 56%,#b867f4);
    box-shadow:0 0 42px #2556dc44;}
.robot-inner {height:100%; width:100%; border-radius:50%; overflow:hidden;
    background:radial-gradient(circle,#102754,#061024 75%);}
.robot-inner img {width:94%; height:94%; object-fit:contain; margin:3%;}
.hero h2 {font-size:1.7rem; color:#edf4ff; margin:0; padding:0;}
.hero p {color:#a4b8d5; font-size:1.15rem; margin:.3rem 0;}
.hero.compact .robot-ring {width:110px; height:110px; margin-bottom:.3rem;}
[data-testid="stChatMessage"] {background:#101b2e; border:1px solid #223047;
    border-radius:22px 22px 22px 5px; margin:.7rem 0; padding:1rem;
    width:92%; direction:ltr; box-shadow:0 8px 25px #00000018;}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background:linear-gradient(135deg,#205bbd,#353da5); border-color:#4e71d7;
    border-radius:22px 22px 5px 22px; margin-left:auto; width:fit-content; max-width:87%;}
[data-testid="stChatMessageAvatarUser"] {display:none;}
[data-testid="stChatMessageContent"] {direction:rtl; text-align:right; min-width:0;}
[data-testid="stChatMessageContent"] p {font-size:1.16rem; line-height:1.9;}
[data-testid="stChatMessageContent"] li {text-align:right;}
[data-testid="stChatMessageContent"] ul, [data-testid="stChatMessageContent"] ol {padding-right:1.4rem;}
[data-testid="stChatMessageContent"] code {direction:ltr; unicode-bidi:embed;}
[data-testid="stChatInput"] {border-radius:28px; border:1px solid #293954; background:#101b2e;}
[data-testid="stChatInput"] textarea {direction:rtl; text-align:right; font-size:1.1rem;}
[data-testid="stChatInputSubmitButton"] {color:#6ba8ff;}
[data-testid="stBottom"] > div {background:#040d1d;}
[data-testid="stForm"] {direction:rtl; border-color:#253a5c; border-radius:20px;}
[data-testid="stTextInput"] input {direction:rtl;}
[data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button {border-radius:14px;}
@media (max-width:600px) {
    .stMainBlockContainer {padding:4rem 1rem 5rem;}
    .robot-ring {width:205px; height:205px;}
    .brand h1 {font-size:1.65rem;}
    [data-testid="stChatMessage"] {width:98%; padding:.8rem;}
}
</style>
""", unsafe_allow_html=True)


def hero(compact=False):
    if ROBOT_PATH.is_file():
        encoded = base64.b64encode(ROBOT_PATH.read_bytes()).decode("ascii")
        size = " compact" if compact else ""
        st.markdown(
            f'<div class="hero{size}"><div class="robot-ring"><div class="robot-inner">'
            f'<img src="data:image/png;base64,{encoded}" alt="روبوت المساعد الجامعي يحمل شعار الجامعة">'
            '</div></div></div>', unsafe_allow_html=True,
        )
    if not compact:
        st.markdown('<div class="hero"><h2>أهلًا بك، كيف أساعدك؟</h2>'
                    '<p>اسأل عن التخصصات والرسوم والقبول والخطط الدراسية.</p></div>',
                    unsafe_allow_html=True)


def show_message(message):
    avatar = str(ROBOT_PATH) if message["role"] == "assistant" and ROBOT_PATH.is_file() else None
    with st.chat_message(message["role"], avatar=avatar):
        content = message["content"]
        if message["role"] == "assistant":
            # نحتفظ بالمراجع في نتيجة الراغ، ونخفي أرقامها من فقاعات المحادثة فقط.
            content = re.sub(r"\s*\[[\d,،\s]+\]", "", content)
        st.markdown(content)
        if message.get("sources"):
            with st.expander("📚 المصادر"):
                shown = set()
                for source in message["sources"]:
                    name = source.get("source_file", "مصدر غير محدد")
                    page = source.get("page_number", "غير محددة")
                    identity = (name, str(page))
                    if identity not in shown:
                        st.write(f"{name} — الصفحة: {page}")
                        shown.add(identity)


st.markdown('<div class="brand"><h1>المساعد الجامعي</h1>'
            '<p>جامعة العلوم والتكنولوجيا</p></div>', unsafe_allow_html=True)

# دخول بسيط بكلمة مشتركة للتجربة الجامعية.
password = os.getenv("APP_PASSWORD", "")
if not password:
    st.info("أضيفي APP_PASSWORD إلى ملف .env ثم أعيدي تشغيل الواجهة.")
    st.stop()

if not st.session_state.get("authenticated", False):
    hero()
    with st.form("login"):
        entered = st.text_input("كلمة الدخول", type="password", placeholder="ادخل 1234")
        submitted = st.form_submit_button("دخول إلى المساعد", use_container_width=True)
    if submitted:
        if hmac.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
            st.session_state.authenticated = True
            st.rerun()
        st.error("كلمة الدخول غير صحيحة.")
    st.stop()

# لا نحفظ المساعد في cache عام: سياق كل مستخدم مستقل.
if "rag" not in st.session_state:
    try:
        from rag import UniversityRAG
        with st.spinner("جاري تجهيز المساعد…"):
            st.session_state.rag = UniversityRAG()
    except Exception as error:
        st.error("تعذر تجهيز المساعد. تحققي من ملف .env وقاعدة البيانات وملفات المشروع.")
        st.caption(f"نوع الخطأ: {type(error).__name__}")
        st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []


def save_conversation():
    messages = st.session_state.messages
    first_question = next((m["content"] for m in messages if m["role"] == "user"), "محادثة جديدة")
    st.session_state.conversations[st.session_state.active_conversation] = {
        "title": first_question[:38] + ("…" if len(first_question) > 38 else ""),
        "messages": deepcopy(messages),
        "history": deepcopy(st.session_state.rag.history),
        "last_search_question": st.session_state.rag.last_search_question,
    }


def new_conversation():
    st.session_state.active_conversation = uuid4().hex
    st.session_state.messages = []
    st.session_state.rag.reset()
    save_conversation()


def open_conversation(conversation_id):
    save_conversation()
    conversation = st.session_state.conversations[conversation_id]
    st.session_state.active_conversation = conversation_id
    st.session_state.messages = deepcopy(conversation["messages"])
    st.session_state.rag.history = deepcopy(conversation["history"])
    st.session_state.rag.last_search_question = conversation["last_search_question"]


if "conversations" not in st.session_state:
    st.session_state.conversations = {}
    st.session_state.active_conversation = uuid4().hex
    save_conversation()

with st.sidebar:
    st.header("🎓 المساعد الجامعي")
    st.caption("اسأل بلغتك الطبيعية، ويمكنك متابعة السؤال في نفس المحادثة.")
    if st.button("＋ محادثة جديدة", use_container_width=True):
        if st.session_state.messages:
            save_conversation()
            new_conversation()
        st.rerun()
    st.subheader("المحادثات السابقة")
    conversations = [
        (conversation_id, conversation)
        for conversation_id, conversation in st.session_state.conversations.items()
        if conversation["messages"]
    ]
    if not conversations:
        st.caption("ستظهر محادثاتك هنا بعد إرسال أول سؤال.")
    for conversation_id, conversation in reversed(conversations):
        active = conversation_id == st.session_state.active_conversation
        if st.button(conversation["title"], key=f"conversation_{conversation_id}",
                     disabled=active, use_container_width=True):
            open_conversation(conversation_id)
            st.rerun()
    if st.button("تسجيل الخروج", use_container_width=True):
        st.session_state.rag.reset()
        st.session_state.clear()
        st.rerun()
    with st.expander("تقييم التجربة"):
        with st.form("feedback", clear_on_submit=True):
            tester = st.text_input("اسم أو رمز المشارك")
            score = st.slider("ما مدى رضاك عن الإجابات؟", 1, 5, 3)
            note = st.text_area("ملاحظاتك")
            save = st.form_submit_button("حفظ التقييم")
        if save:
            try:
                data_dir = PROJECT_DIR / "app_data"
                data_dir.mkdir(exist_ok=True)
                with sqlite3.connect(data_dir / "feedback.sqlite3") as connection:
                    connection.execute("CREATE TABLE IF NOT EXISTS feedback "
                                       "(created_at TEXT, tester TEXT, score INTEGER, note TEXT)")
                    connection.execute("INSERT INTO feedback VALUES (datetime('now'), ?, ?, ?)",
                                       (tester.strip(), score, note.strip()))
                st.success("تم حفظ تقييمك، شكرًا لك.")
            except (OSError, sqlite3.Error):
                st.error("تعذر حفظ التقييم، حاول مرة أخرى.")

hero(compact=bool(st.session_state.messages))
for message in st.session_state.messages:
    show_message(message)

suggestions = [
    "ما التخصصات المتاحة في الجامعة؟",
    "كم رسوم تقنية المعلومات بالعربي؟",
    "ما شروط القبول والتسجيل؟",
    "كم مدة دراسة تقنية المعلومات بالعربي؟",
]
question = None
st.markdown('<p style="direction:rtl;text-align:right;color:#a4b8d5">أسئلة مقترحة</p>',
            unsafe_allow_html=True)
columns = st.columns(2)
for index, suggestion in enumerate(suggestions):
    with columns[index % 2]:
        if st.button(suggestion, key=f"suggestion_{index}", use_container_width=True):
            question = suggestion

typed_question = st.chat_input("اكتب سؤالك هنا…")
question = typed_question or question
if question and question.strip():
    question = question.strip()
    user_message = {"role": "user", "content": question}
    st.session_state.messages.append(user_message)
    show_message(user_message)
    rag = st.session_state.rag
    old_history = list(rag.history)
    old_question = rag.last_search_question
    try:
        with st.spinner("أبحث في المصادر وأجهّز إجابتك…"):
            result = rag.answer(question)
        reply = {"role": "assistant", "content": result["answer"],
                 "sources": result.get("sources", [])}
    except Exception as error:
        rag.history = old_history
        rag.last_search_question = old_question
        text = "تعذر إكمال الطلب. أعد إرسال السؤال."
        if getattr(error, "status_code", None) == 429:
            text = "بلغنا حد الطلبات المؤقت. انتظر دقيقة ثم أعد إرسال السؤال."
        reply = {"role": "assistant", "content": text, "sources": []}
    st.session_state.messages.append(reply)
    save_conversation()
    st.rerun()
