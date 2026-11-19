"""User-scoped Supabase storage. No service-role credentials."""
import os
import json
import base64
from uuid import uuid4
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions
class AccountStore:
    def __init__(self):
        url=os.getenv('SUPABASE_URL','').strip();key=os.getenv('SUPABASE_PUBLISHABLE_KEY','').strip()
        if not url.startswith('https://') or not key:raise ValueError('أضف إعدادات Supabase إلى الأسرار.')
        if key.startswith('sb_secret_'):raise ValueError('استخدم publishable وليس secret أو service_role.')
        if key.count('.')==2:
            try:claims=json.loads(base64.urlsafe_b64decode(key.split('.')[1]+'==='))
            except (ValueError,TypeError):raise ValueError('مفتاح Supabase غير صالح.') from None
            if claims.get('role')!='anon':raise ValueError('لا تستخدم service_role.')
        self.client=create_client(url,key,options=SyncClientOptions(persist_session=False))
        self.user_id=None;self.email=None
    def login(self,email,password):
        r=self.client.auth.sign_in_with_password({'email':email.strip(),'password':password})
        if not r.user or not r.session:raise ValueError('لم يكتمل الدخول.')
        self.user_id=r.user.id;self.email=r.user.email
        return r
    def signup(self,email,password):
        if len(password)<12:raise ValueError('كلمة المرور 12 حرفًا على الأقل.')
        return self.client.auth.sign_up({'email':email.strip(),'password':password})
    def logout(self):
        try:self.client.auth.sign_out()
        finally:self.user_id=None;self.email=None
    def require_user(self):
        r=self.client.auth.get_user()
        if not r.user or r.user.id!=self.user_id:raise PermissionError('انتهت الجلسة.')
        return self.user_id
    def list_chats(self):
        uid=self.require_user()
        return self.client.table('conversations').select('id,title,updated_at').eq('user_id',uid).order('updated_at',desc=True).execute().data
    def load_chat(self,chat_id):
        uid=self.require_user()
        rows=self.client.table('conversations').select('*').eq('id',chat_id).eq('user_id',uid).limit(1).execute().data
        if not rows:raise LookupError('المحادثة غير متاحة.')
        return rows[0]
    def save_chat(self,chat_id,title,messages,last_question):
        uid=self.require_user()
        if len(messages)>500:raise ValueError('ابدأ محادثة جديدة؛ بلغنا حد الرسائل.')
        row=dict(id=chat_id or str(uuid4()),user_id=uid,title=title[:100],messages=messages,last_search_question=last_question)
        self.client.table('conversations').upsert(row,on_conflict='id').execute()
        return row['id']
    def delete_chat(self,chat_id):
        uid=self.require_user()
        self.client.table('conversations').delete().eq('id',chat_id).eq('user_id',uid).execute()
    def save_feedback(self,score,note):
        uid=self.require_user()
        self.client.table('feedback').insert({'user_id':uid,'score':score,'note':note[:5000]}).execute()
