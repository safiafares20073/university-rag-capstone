"""University Assistant: account-scoped chats and a bilingual Streamlit interface."""
import base64
import os
import re
from copy import deepcopy
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from account_store import AccountStore
from conversation_logic import trim_for_edit,restore_history
ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
for name in ['OPENAI_API_KEY','OPENAI_CHAT_MODEL','OPENAI_EMBEDDING_MODEL','OPENAI_RERANK_MODEL',
             'OPENAI_TRANSCRIBE_MODEL','SUPABASE_URL','SUPABASE_PUBLISHABLE_KEY','VECTOR_DB_DIR',
             'HOSTED_DEPLOYMENT','DEPLOYMENT_TOKEN']:
    if not os.getenv(name):
        try:value=st.secrets.get(name)
        except (FileNotFoundError,KeyError):value=None
        if value:os.environ[name]=str(value)
st.set_page_config(page_title='المساعد الجامعي',page_icon='🎓',layout='centered')
st.session_state.setdefault('language','ar');st.session_state.setdefault('theme','dark')
def U(ar,en):return ar if st.session_state.language=='ar' else en
# These preferences are available before authentication as well as during chat.
with st.sidebar:
    st.subheader(U('الإعدادات','Settings'))
    st.selectbox('اللغة / Language',['ar','en'],key='language',format_func=lambda x:'العربية' if x=='ar' else 'English')
    st.radio(U('المظهر','Theme'),['dark','light'],key='theme',horizontal=True,
        format_func=lambda x, labels={'dark':U('ليلي','Dark'),'light':U('نهاري','Light')}:labels[x])
    st.divider()
ar=st.session_state.language=='ar';light=st.session_state.theme=='light'
bg,fg,surface,border=('#f5f6f8','#182230','#ffffffed','#d1d8e0') if light else ('#071224','#edf4ff','#14243dbb','#436184')
side='right' if ar else 'left'
align='right' if ar else 'left'
direction='rtl' if ar else 'ltr'
button_bg,button_fg,button_hover=('#e7f0ff','#214b7e','#d5e6ff') if light else ('#263e64','#f3f7ff','#355381')
st.markdown(f'''<style>

.stApp {{background:radial-gradient(circle at 70% 5%,{'#ffffff' if light else '#25315b'},{bg} 65%);color:{fg};}}
.stApp,.stApp button,.stApp input,.stApp textarea {{font-family:Arial,sans-serif;}}
.stMainBlockContainer {{max-width:900px;padding-top:3.5rem;}}
[data-testid="stToolbarActions"],[data-testid="stAppDeployButton"],.stDeployButton,#MainMenu,footer {{display:none !important;}}
[data-testid="stHeader"] {{background:transparent;}}
[data-testid="stSidebar"] {{background:{surface};backdrop-filter:blur(24px);direction:{'rtl' if ar else 'ltr'};}}
[data-testid="stExpandSidebarButton"] {{position:fixed;left:{'auto' if ar else '12px'};right:{'12px' if ar else 'auto'};top:12px;z-index:10000;display:flex !important;visibility:visible !important;opacity:1 !important;background:{button_bg} !important;color:{button_fg} !important;border:1px solid {border};border-radius:10px;}}
[data-testid="stAppViewContainer"] {{flex-direction:{'row-reverse' if ar else 'row'};}}
[data-testid="stChatMessage"],[data-testid="stForm"] {{background:{surface};border:1px solid {border};border-radius:20px;backdrop-filter:blur(18px);box-shadow:0 8px 28px #00000014;}}
[data-testid="stChatMessageContent"],[data-testid="stTextArea"] textarea {{direction:{'rtl' if ar else 'ltr'};text-align:{'right' if ar else 'left'};}}
[data-testid="stChatMessageContent"] p {{line-height:1.9;color:{fg};}}
[data-testid="stTextArea"] textarea,[data-testid="stTextInput"] input {{color:{fg};background:{surface};}}
h1,h2,h3,p,label {{color:{fg};}}
.brand {{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;direction:{direction};margin:16px 0 24px;text-align:center;}}
.brand img {{width:136px;height:136px;object-fit:contain;}} .brand h1 {{font-size:1.9rem;margin:0;padding:0;line-height:1.5;}}
.waiting {{text-align:center;padding:12px;animation:pulse 1s infinite;}}
@keyframes pulse {{50%{{opacity:.45;transform:translateY(-3px)}}}}
@media(prefers-reduced-motion:reduce){{.waiting{{animation:none}}}}
@media(max-width:600px){{.stMainBlockContainer{{padding:3.2rem 12px 2rem}}.brand img{{width:112px;height:112px}}}}
[data-testid="stMain"] {{direction:{direction};text-align:{align};}}
[data-testid="stWidgetLabel"],[data-testid="stCaptionContainer"], [data-testid="stMarkdownContainer"] {{text-align:{align};direction:{direction};}}
.brand h1 {{text-align:center;}}
[data-testid="stTabs"] [role="tablist"] {{direction:{direction};justify-content:flex-start;}}
[data-testid="stCheckbox"] label {{direction:{direction};text-align:{align};gap:8px;}}
[data-testid="stTextInput"] input {{direction:{direction};text-align:{align};}}
[data-testid="stTextInput"] input[type="password"],input[aria-label="البريد الإلكتروني"],input[aria-label="Email"] {{direction:ltr;text-align:left;}}
[data-testid="stButton"] button,[data-testid="stFormSubmitButton"] button {{background:{button_bg};color:{button_fg};border:1px solid {border};border-radius:12px;}}
[data-testid="stButton"] button:hover,[data-testid="stFormSubmitButton"] button:hover {{background:{button_hover};color:{button_fg};border-color:{button_fg};}}
[data-testid="stButton"] button p,[data-testid="stFormSubmitButton"] button p {{color:inherit;}}
[data-testid="stTextInputRootElement"],[data-baseweb="input"],[data-baseweb="base-input"], [data-baseweb="select"] > div {{background:{'#ffffff' if light else '#15253e'};color:{fg};}}
[data-testid="stChatInput"], [data-testid="stChatInput"] > div {{background:{'#ffffff' if light else '#15253e'};color:{fg};border-radius:20px;}}
[data-testid="stChatInput"] textarea {{direction:{direction};text-align:{align};color:{fg};background:transparent;}}
[data-testid="stChatInput"] button {{background:{button_bg};color:{button_fg};}}
[data-testid="stBottom"], [data-testid="stBottomBlockContainer"] {{background:transparent !important;box-shadow:none !important;}}
[data-testid="stTabs"] button[role="tab"] {{color:{fg};}}
[data-testid="stRadio"] label,[data-testid="stSelectbox"] label {{color:{fg};}}
[data-testid="stSelectbox"] [data-baseweb="select"] * {{color:{fg};}}
input::placeholder,textarea::placeholder {{color:{'#64748b' if light else '#b1c0d6'};opacity:1;}}
/* Match all semantic text, popups and form controls to the selected app palette. */
[data-testid="stToolbar"] {{background:transparent !important;}}
[data-testid="stSidebar"] {{color:{fg} !important;}}
[data-testid="stSidebarCollapseButton"] {{display:flex !important;visibility:visible !important;opacity:1 !important;}}
[data-testid="stSidebarCollapseButton"] button {{color:{fg} !important;}}
[data-testid="stExpandSidebarButton"] svg,[data-testid="stExpandSidebarButton"] span {{color:{button_fg} !important;fill:currentColor;}}
[data-testid="stMarkdownContainer"] :is(p,li,span,strong,em),
[data-testid="stWidgetLabel"] *,[data-testid="stCaptionContainer"] *,
[data-testid="stExpander"] summary,[data-testid="stExpander"] summary *,
[data-testid="stRadio"] label *,[data-testid="stCheckbox"] label *,
[data-testid="stTabs"] [role="tab"] *,[data-testid="stSpinner"] *,
[data-testid="stSlider"] label *,[data-testid="stAlert"] p {{color:{fg} !important;}}
[data-testid="stButton"] button p,[data-testid="stFormSubmitButton"] button p {{color:{button_fg} !important;}}
[data-testid="stSelectbox"] [data-baseweb="select"],
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stSelectbox"] [data-baseweb="select"] > div > div {{background-color:{'#ffffff' if light else '#15253e'} !important;color:{fg} !important;border-color:{border} !important;}}
[data-testid="stSelectbox"] [data-baseweb="select"] :is(input,span,svg) {{color:{fg} !important;-webkit-text-fill-color:{fg} !important;}}
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] [role="option"],
[data-baseweb="menu"], [data-baseweb="menu"] li {{background:{'#ffffff' if light else '#15253e'} !important;color:{fg} !important;}}
[data-baseweb="popover"] [role="option"] *,[data-baseweb="menu"] li * {{color:{fg} !important;}}
[data-baseweb="popover"] [role="option"]:hover {{background:{button_hover} !important;}}
[data-testid="stTextInput"] [data-baseweb="input"] *,[data-testid="stTextArea"] textarea {{background-color:{'#ffffff' if light else '#15253e'} !important;color:{fg} !important;}}
[data-testid="stChatInput"], [data-testid="stChatInput"] > div {{background:{'#ffffff' if light else '#15253e'} !important;box-shadow:none !important;border-color:{border} !important;color:{fg} !important;}}
[data-testid="stChatInput"] textarea {{background:transparent !important;color:{fg} !important;-webkit-text-fill-color:{fg} !important;}}
[data-testid="stChatInput"] button,[data-testid="stChatInput"] button * {{color:{button_fg} !important;}}
.st-key-message_box {{background:transparent !important;border:0 !important;box-shadow:none !important;}}
/* A collapsed native sidebar has zero width; never show its overflowing children. */
[data-testid="stSidebar"][aria-expanded="false"] {{display:none !important;visibility:hidden !important;overflow:hidden !important;pointer-events:none !important;}}
[data-testid="stSidebar"][aria-expanded="false"] * {{visibility:hidden !important;pointer-events:none !important;}}
[data-testid="stSidebarResizeHandle"] {{display:none !important;}}
/* Keep list markers adjacent to their Arabic text rather than at opposite edges. */
[data-testid="stChatMessageContent"] [data-testid="stMarkdownContainer"] {{direction:{direction};text-align:{align};min-width:0;width:100%;}}
[data-testid="stChatMessageContent"] :is(ul,ol) {{direction:{direction} !important;text-align:{align} !important;padding-inline-start:1.5rem !important;padding-inline-end:0 !important;margin-inline:0 !important;list-style-position:outside !important;}}
[data-testid="stChatMessageContent"] li {{display:list-item !important;direction:{direction} !important;text-align:{align} !important;unicode-bidi:normal;line-height:1.9;padding-inline-start:.2rem;}}
[data-testid="stChatMessageContent"] li > p {{text-align:{align} !important;direction:{direction} !important;margin-block:.35rem;}}
[data-testid="stChatMessageContent"] :is(p,h1,h2,h3,h4,blockquote) {{text-align:{align} !important;direction:{direction} !important;}}
[data-testid="stChatMessageContent"] :is(pre,code) {{direction:ltr;unicode-bidi:isolate;text-align:left;}}
[data-testid="stStatusWidget"],[data-testid="stConnectionStatus"],
[data-testid="stStatusWidgetRunningIcon"],[data-testid="stStatusWidgetRunningManIcon"],
[data-testid="stToolbarItems"] {{display:none !important;}}
.st-key-guest_entry {{margin-top:-.4rem;margin-bottom:.25rem;}}
/* The recorder uses a WaveSurfer shadow tree. Keep its real microphone waveform,
   add a center baseline, and adjust color without synthetic animation. */
[data-testid="stChatInput"] div::part(scroll) {{background:linear-gradient(to bottom,transparent calc(50% - .6px),{'#244b75' if light else '#a9c5eb'} calc(50% - .6px),{'#244b75' if light else '#a9c5eb'} calc(50% + .6px),transparent calc(50% + .6px));}}
</style>''',unsafe_allow_html=True)
if light:
    st.markdown("""<style>
    [data-testid="stSidebar"] {background:#f0f6ff !important;}
    h1,h2,h3,h4,[data-testid="stHeading"] * {color:#204d80 !important;}
    [data-testid="stForm"],[data-testid="stChatMessage"] {background:#f7faff !important;border-color:#cbdcf1 !important;}
    [data-testid="stSelectbox"] {color:#182f4d !important;}
    [data-testid="stSelectbox"] div {background-color:#ffffff !important;color:#182f4d !important;border-color:#bdd1eb !important;}
    [data-testid="stSelectbox"] :is(input,span,svg,p) {color:#182f4d !important;-webkit-text-fill-color:#182f4d !important;}
    [data-baseweb="popover"],[data-baseweb="popover"] > div,
    [data-baseweb="popover"] [role="listbox"], [data-baseweb="popover"] [role="option"],
    [data-baseweb="menu"], [data-baseweb="menu"] li {background-color:#ffffff !important;color:#182f4d !important;}
    [data-baseweb="popover"] [role="option"]:hover {background:#e7f0ff !important;}
    [data-testid="stFormSubmitButton"] button,[data-testid="stButton"] button {background:#e7f0ff !important;border-color:#bdd1eb !important;}
    [data-testid="stFormSubmitButton"] button:hover,[data-testid="stButton"] button:hover {background:#d5e6ff !important;}
    [data-testid="stTextInput"] [data-baseweb="input"] {border-color:#bdd1eb !important;}
    [data-testid="stChatInput"] {border:1px solid #bdd1eb !important;}
    /* Streamlit 1.65 uses a React Aria dropdown, not a BaseWeb popover. */
    [data-testid="stSelectboxVirtualDropdown"],
    [data-testid="stSelectboxVirtualDropdown"] :is(div,ul,li,[role="listbox"],[role="option"]) {background-color:#ffffff !important;color:#182f4d !important;border-color:#bdd1eb !important;}
    [data-testid="stSelectboxVirtualDropdown"] * {color:#182f4d !important;-webkit-text-fill-color:#182f4d !important;}
    [data-testid="stSelectboxVirtualDropdown"] [role="option"]:is(:hover,[data-focused="true"],[aria-selected="true"]) {background-color:#e7f0ff !important;}
    [data-testid="stChatInput"] div::part(wave),[data-testid="stChatInput"] div::part(progress) {filter:brightness(.38) saturate(1.4);}
    </style>""",unsafe_allow_html=True)
robot=ROOT/'assets'/'robot.png'
image='<span style="font-size:100px">🤖</span>'
if robot.is_file():image='<img alt="روبوت المساعد الجامعي" src="data:image/png;base64,'+base64.b64encode(robot.read_bytes()).decode()+'">'
st.markdown('<div class="brand">'+image+'<h1>'+U('المساعد الجامعي','University Assistant')+'</h1></div>',unsafe_allow_html=True)
st.session_state.setdefault('guest',False)
# Guests can enter even when the account service is temporarily unavailable.
if 'account' not in st.session_state and not st.session_state.guest:
    try:st.session_state.account=AccountStore()
    except Exception:st.session_state.account=None
store=st.session_state.get('account')
if not st.session_state.guest and not (store and store.user_id):
    if store is None:
        st.warning(U('خدمة الحسابات غير متاحة الآن. يمكنك المتابعة كضيف.','Account service is unavailable. You can continue as a guest.'))
        if st.button(U('إعادة الاتصال','Reconnect')):
            st.session_state.pop('account',None);st.rerun()
    st.caption(U('سجّل الدخول للاحتفاظ بمحادثاتك والرجوع إليها من أي جهاز.','Sign in to save your chats and access them from another device.'))
    login,signup=st.tabs([U('تسجيل الدخول','Sign in'),U('إنشاء حساب','Create account')])
    with login:
        with st.form('login',clear_on_submit=False):
            email=st.text_input(U('البريد الإلكتروني','Email'),key='login_email')
            password=st.text_input(U('كلمة المرور','Password'),type='password',key='login_password')
            submit=st.form_submit_button(U('دخول','Sign in'),disabled=store is None,use_container_width=True)
        if submit:
            try:
                with st.spinner(U('جارٍ تسجيل الدخول…','Signing in…')):
                    store.login(email,password)
                st.session_state.pop('login_password',None)
                st.rerun()
            except Exception:st.error(U('تعذر الدخول. تحقق من البيانات وتأكيد البريد.','Sign in failed. Check your credentials and email confirmation.'))
    with signup:
        with st.form('signup',clear_on_submit=False):
            new_email=st.text_input(U('البريد الإلكتروني','Email'),key='signup_email')
            new_password=st.text_input(U('كلمة المرور (12 حرفًا على الأقل)','Password (at least 12 characters)'),type='password',key='signup_password')
            confirm=st.text_input(U('تأكيد كلمة المرور','Confirm password'),type='password',key='signup_confirm')
            consent=st.checkbox(U('أوافق على حفظ المحادثات في حسابي وإرسال أسئلتي والتسجيلات التي أحوّلها إلى OpenAI.','I agree to store chats in my account and send questions and audio I transcribe to OpenAI.'))
            register=st.form_submit_button(U('إنشاء الحساب','Create account'),disabled=store is None,use_container_width=True)
        if register:
            if not consent or new_password!=confirm or len(new_password)<12:
                st.error(U('تحقق من الموافقة وتطابق كلمة المرور وطولها.','Check consent, password length and confirmation.'))
            else:
                try:
                    with st.spinner(U('جارٍ إنشاء الحساب…','Creating your account…')):
                        store.signup(new_email,new_password)
                    st.success(U('تم إرسال طلب التسجيل. أكّد بريدك ثم سجّل الدخول.','Registration submitted. Confirm your email, then sign in.'))
                except Exception:st.error(U('تعذر إنشاء الحساب. تحقق من البيانات أو حاول لاحقًا.','Account creation failed. Check the details or try later.'))
    st.divider()
    if st.button(U('المتابعة كضيف','Continue as guest'),key='guest_entry',use_container_width=True):
        st.session_state.guest=True
        for key in ('login_password','signup_password','signup_confirm'):
            st.session_state.pop(key,None)
        st.rerun()
    st.caption(U('يمكنك استخدام المساعد كضيف دون إنشاء حساب. تُرسل أسئلتك والصوت الذي تحوّله إلى OpenAI؛ محادثات الضيف تبقى في الجلسة الحالية فقط.','Try the assistant without an account. Questions and audio you transcribe are sent to OpenAI; guest chats last only for this session.'))
    st.stop()
if 'rag' not in st.session_state:
    try:
        if os.getenv('HOSTED_DEPLOYMENT')=='1':
            with st.spinner(U('جارٍ تجهيز البحث…','Preparing search…')):
                from deploy_index import ensure_index
                ensure_index()
        from rag import UniversityRAG
        st.session_state.rag=UniversityRAG()
    except Exception:
        st.info(U('المساعد قيد التهيئة. يرجى المحاولة لاحقًا.','The assistant is being prepared. Please try again later.'));st.stop()
rag=st.session_state.rag;rag.language=st.session_state.language
st.session_state.setdefault('messages',[]);st.session_state.setdefault('active_chat',None);st.session_state.setdefault('draft','')
if st.session_state.pop('clear_draft',False):st.session_state.draft=''
def persist():
    if st.session_state.guest:
        st.session_state.unsaved=False
        return
    messages=st.session_state.messages
    if not messages:return
    title=next((m['content'] for m in messages if m['role']=='user'),U('محادثة','Chat'))[:100]
    st.session_state.active_chat=store.save_chat(st.session_state.active_chat,title,messages,rag.last_search_question)
    st.session_state.unsaved=False
def reset_chat():
    st.session_state.messages=[];st.session_state.active_chat=None;st.session_state.draft=''
    st.session_state.pop('pending_edit',None);rag.reset()
with st.sidebar:
    st.header(U('القائمة','Menu'));st.caption(U('وضع الضيف','Guest mode') if st.session_state.guest else store.email)
    if st.session_state.get('unsaved'):
        st.warning(U('توجد تغييرات لم تُحفظ. أعد الحفظ قبل الانتقال.','Some changes are not saved. Retry before switching chats.'))
        if st.button(U('إعادة حفظ المحادثة','Retry saving')):
            try:persist();st.rerun()
            except Exception:st.error(U('تعذر الحفظ الآن.','Saving failed.'))
    if st.button(U('＋ محادثة جديدة','＋ New chat'),disabled=bool(st.session_state.get('unsaved')),use_container_width=True):reset_chat();st.rerun()
    chats=[]
    if st.session_state.guest:
        st.info(U('محادثة الضيف مؤقتة. سجّل الدخول لحفظ محادثاتك عبر الأجهزة.','Guest chats are temporary. Sign in to save chats across devices.'))
    else:
        st.subheader(U('المحادثات المحفوظة','Saved chats'))
        try:chats=store.list_chats()
        except Exception:st.error(U('تعذر تحميل المحادثات. أعد تسجيل الدخول إذا استمرت المشكلة.','Could not load chats. Sign in again if this persists.'))
    for c in chats:
        if st.button(c['title'],key='open_'+c['id'],disabled=bool(st.session_state.get('unsaved')),use_container_width=True):
            try:
                row=store.load_chat(c['id']);st.session_state.active_chat=row['id'];st.session_state.messages=row['messages']
                rag.history=restore_history(row['messages']);rag.last_search_question=row.get('last_search_question')
                st.session_state.draft='';st.session_state.pop('pending_edit',None);st.rerun()
            except Exception:st.error(U('تعذر فتح المحادثة.','Could not open chat.'))
    if st.session_state.active_chat:
        with st.expander(U('حذف هذه المحادثة','Delete this chat')):
            confirm_delete=st.checkbox(U('أؤكد حذف المحادثة نهائيًا','Permanently delete this chat'),key='confirm_'+st.session_state.active_chat)
            if st.button(U('حذف','Delete'),disabled=not confirm_delete):
                try:store.delete_chat(st.session_state.active_chat);reset_chat();st.rerun()
                except Exception:st.error(U('تعذر الحذف.','Deletion failed.'))
    if st.session_state.guest and st.session_state.messages:
        if st.button(U('مسح محادثة الضيف','Clear guest chat')):reset_chat();st.rerun()
    if st.button(U('تسجيل الدخول' if st.session_state.guest else 'تسجيل الخروج','Sign in' if st.session_state.guest else 'Sign out')):
        if store and store.user_id:
            try:store.logout()
            except Exception:pass
        language,theme=st.session_state.language,st.session_state.theme
        st.session_state.clear();st.session_state.language=language;st.session_state.theme=theme;st.rerun()
    with st.expander(U('تقييم التجربة','Feedback')):
        with st.form('feedback',clear_on_submit=True):
            score=st.slider(U('الرضا العام','Overall satisfaction'),1,5,3);note=st.text_area(U('ملاحظاتك','Comments'))
            send_feedback=st.form_submit_button(U('حفظ','Save'),disabled=st.session_state.guest)
            if st.session_state.guest:st.caption(U('سجّل الدخول لإرسال تقييمك.','Sign in to submit feedback.'))
        if send_feedback:
            try:store.save_feedback(score,note);st.success(U('شكرًا لملاحظاتك.','Thank you for your feedback.'))
            except Exception:st.error(U('تعذر حفظ التقييم.','Could not save feedback.'))
for i,message in enumerate(st.session_state.messages):
    with st.chat_message(message['role'],avatar=str(robot) if message['role']=='assistant' and robot.is_file() else None):
        visible_text=re.split(r'(?im)^\s*(?:\*\*)?(?:المصادر|المراجع|Sources|Resources|References)\s*[:：](?:\*\*)?\s*$',message['content'],maxsplit=1)[0]
        st.markdown(re.sub(r'\s*\[[\d,،\s]+\]','',visible_text))
        if message['role']=='user' and st.button(U('تعديل','Edit'),key=f'edit_{i}'):
            st.session_state.pending_edit=i;st.session_state.draft=message['content'];st.rerun()
latest=next((m['content'] for m in reversed(st.session_state.messages) if m['role']=='user'),'')
if latest:
    suggestions=[U('وما شروط القبول في نفس التخصص؟','What are the admission requirements for the same program?'),U('وكم مدة الدراسة فيه؟','How long does that program take?'),U('وما الرسوم السنوية له؟','What is its annual tuition?')]
    if re.search('رسوم|تكلفة|tuition|fee',latest,re.I):suggestions=[U('وهل توجد رسوم تسجيل إضافية؟','Are there separate registration fees?'),U('وكم معدل القبول لهذا التخصص؟','What is the admission threshold for this program?'),U('وهل تختلف رسوم التعليم الإلكتروني؟','Are e-learning fees different?')]
    suggestions+=[U('وهل تتوفر خطة دراسية لهذا التخصص؟','Is a study plan available for this program?'),U('وما الوثائق المطلوبة للتسجيل فيه؟','Which documents are required for admission?')]
    asked={m['content'].strip() for m in st.session_state.messages if m['role']=='user'}
    suggestions=[x for x in suggestions if x not in asked][:3]
else:suggestions=[U('ما التخصصات المتاحة؟','Which programs are available?'),U('كم رسوم تقنية المعلومات بالعربي؟','What is the tuition for the Arabic IT program?'),U('ما شروط القبول في طب الأسنان؟','What are the dentistry admission requirements?')]
st.caption(U('أسئلة مقترحة','Suggested questions'))
for col,suggestion in zip(st.columns(3),suggestions):
    if col.button(suggestion,use_container_width=True):st.session_state.draft=suggestion;st.rerun()
if 'pending_edit' in st.session_state:st.info(U('حفظ التعديل يعيد الإجابة ويحذف الرسائل التالية للسؤال المعدّل.','Saving edits regenerates the answer and removes subsequent messages.'))
if st.session_state.get('request_error'):
    st.error(st.session_state.pop('request_error'))
st.caption(U('اكتب أو استخدم الميكروفون داخل مربع الرسالة. التسجيل بحد أقصى دقيقتين؛ راجع النص قبل إرساله.','Type or use the microphone inside the message box. Record up to two minutes; review the transcript before sending.'))
# Prefill is assigned before widget creation (suggestions, edits, and transcripts).
if st.session_state.draft:
    st.session_state.composer=st.session_state.draft
    st.session_state.draft=''
with st.container(key='message_box'):
    prompt=st.chat_input(U('اكتب سؤالك…','Ask a question…'),key='composer',max_chars=5000,
        accept_audio=True,audio_sample_rate=16000,max_upload_size=20,submit_mode='disable')
send=False;draft=''
if prompt:
    draft=prompt if isinstance(prompt,str) else prompt.text
    audio=None if isinstance(prompt,str) else getattr(prompt,'audio',None)
    if audio is not None:
        try:
            with st.spinner(U('جارٍ تحويل الصوت إلى نص…','Transcribing audio…')):
                import io,wave
                with wave.open(io.BytesIO(audio.getvalue()),'rb') as recording:
                    seconds=recording.getnframes()/recording.getframerate()
                if not 0<seconds<=120:raise ValueError('Recording exceeds two minutes.')
                from llm_backend import client
                result=client().audio.transcriptions.create(model=os.getenv('OPENAI_TRANSCRIBE_MODEL','gpt-4o-mini-transcribe'),file=('question.wav',audio.getvalue(),'audio/wav'))
            st.session_state.draft=((draft or '')+' '+result.text).strip()[:5000]
            st.rerun()
        except Exception:
            st.session_state.draft=draft or ''
            st.session_state.request_error=U('تعذر تحويل التسجيل. تأكد أن مدته لا تتجاوز دقيقتين وحاول مجددًا.','Could not transcribe. Keep the recording under two minutes and try again.')
            st.rerun()
    else:send=True
if send and draft.strip():
    original=deepcopy(st.session_state.messages);old_history=deepcopy(rag.history);old_search=rag.last_search_question
    base=trim_for_edit(original,st.session_state.pending_edit) if 'pending_edit' in st.session_state else original
    rag.history=restore_history(base);rag.last_search_question=next((m.get('search_question') or m['content'] for m in reversed(base) if m['role']=='user'),None)
    wait=st.empty();wait.markdown('<div class="waiting">⌛ '+U('أبحث وأجهّز الإجابة…','Finding evidence…')+'</div>',unsafe_allow_html=True)
    try:
        result=rag.answer(draft.strip())
        st.session_state.messages=base+[{'role':'user','content':draft.strip(),'search_question':result.get('search_question')},{'role':'assistant','content':result['answer'],'sources':result.get('sources',[])}]
        st.session_state.pop('pending_edit',None)
        try:persist()
        except Exception:st.session_state.unsaved=True
        st.session_state.clear_draft=True;st.rerun()
    except Exception as error:
        rag.history=old_history;rag.last_search_question=old_search;wait.empty()
        if getattr(error,'code',None)=='local_budget_exceeded':
            st.warning(U('توقف الاستخدام لحماية الميزانية المحددة. لا تحذف سجل الميزانية.','Usage stopped to protect the budget. Do not delete the budget ledger.'));st.stop()
        st.session_state.draft=draft
        st.session_state.request_error=U('تعذر إكمال الطلب. بقي السؤال في الحقل لإعادة المحاولة.','Request failed. Your question remains in the field for retry.')
        st.rerun()
