"""Cumulative, conservative LOCAL API budget; not a replacement for provider billing.

Every HTTP attempt reserves cost before it can reach OpenAI. Reservations are
never refunded, including errors/timeouts, so the ledger deliberately overcounts.
No monthly reset. Preserve this SQLite file and use one shared persistent disk.
"""
import asyncio
import io
import json
import math
import os
import sqlite3
import time
import wave
from decimal import Decimal, ROUND_CEILING
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parent
DEFAULT_DB=ROOT/'app_data'/'openai_budget.sqlite3'
LIMIT_MICRO=12_000_000
# Stop conservatively before 12 USD, leaving room for estimation differences.
MARGIN_MICRO=500_000
CHAT_MODELS={'gpt-4.1-mini','gpt-4.1-mini-2025-04-14'}
EMBED_MODELS={'text-embedding-3-small'}
AUDIO_MODELS={'gpt-4o-mini-transcribe','gpt-4o-mini-transcribe-2025-12-15'}

class BudgetBlocked(ValueError):
    pass

def positive_int(value):
    if type(value) is not int or value<1:raise BudgetBlocked('Invalid output token limit.')
    return value

def micro(amount):
    return int(Decimal(str(amount)).to_integral_value(rounding=ROUND_CEILING))

def quote(request,body):
    """Upper-biased reservation; reject unknown models/modalities before network."""
    if request.url.scheme!='https' or request.url.host!='api.openai.com' or request.url.port not in (None,443):
        raise BudgetBlocked('This budget client only permits the official OpenAI endpoint.')
    if request.method!='POST':raise BudgetBlocked('Only budgeted POST endpoints are enabled.')
    path=request.url.path
    if path in {'/v1/chat/completions','/v1/embeddings'}:
        try:data=json.loads(body)
        except (ValueError,TypeError):raise BudgetBlocked('Invalid request JSON.') from None
        if not isinstance(data,dict):raise BudgetBlocked('Invalid JSON object.')
        model=data.get('model')
        # UTF-8 byte length overestimates text token count; include framing margin.
        input_bound=len(body)+4096
        if path=='/v1/chat/completions':
            if model not in CHAT_MODELS:raise BudgetBlocked('Model has no approved budget price.')
            if data.get('stream') or data.get('tools') or data.get('functions'):
                raise BudgetBlocked('Streaming and tool calls are not budgeted in this version.')
            for message in data.get('messages',[]):
                if not isinstance(message,dict) or not isinstance(message.get('content'),str):
                    raise BudgetBlocked('Only text chat messages are budgeted.')
            n=positive_int(data.get('n',1))
            output=positive_int(data.get('max_completion_tokens',data.get('max_tokens')))
            # Prices per million tokens; microdollars per token are 0.4 and 1.6.
            # Additional factor 2 deliberately reserves above the price estimate.
            amount=micro((Decimal(input_bound)*Decimal('.4')+Decimal(n*output)*Decimal('1.6'))*2)
        else:
            if model not in EMBED_MODELS:raise BudgetBlocked('Embedding model not budgeted.')
            inputs=data.get('input')
            if not (isinstance(inputs,str) or (isinstance(inputs,list) and all(isinstance(x,str) for x in inputs))):
                raise BudgetBlocked('Only text embedding input is budgeted.')
            amount=micro(Decimal(input_bound)*Decimal('.02')*2)
        return model,max(amount,1)
    if path=='/v1/audio/transcriptions':
        # Bound duration and reserve a generous flat $0.50. Do not accept arbitrary
        # compressed media where duration cannot be checked before sending.
        if len(body)>21*1024*1024:raise BudgetBlocked('Recording exceeds the size limit.')
        try:
            header=('Content-Type: '+request.headers['content-type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()
            parts=BytesParser(policy=default).parsebytes(header+body)
            fields={p.get_param('name',header='content-disposition'):p.get_payload(decode=True) for p in parts.iter_parts()}
            model=fields['model'].decode()
            with wave.open(io.BytesIO(fields['file']),'rb') as wav:
                if wav.getframerate()<8000 or wav.getcomptype()!='NONE':raise ValueError()
                seconds=wav.getnframes()/wav.getframerate()
            if not 0<seconds<=120:raise ValueError()
        except Exception:raise BudgetBlocked('Use a PCM WAV recording no longer than two minutes.') from None
        if model not in AUDIO_MODELS:raise BudgetBlocked('Transcription model not budgeted.')
        return model,500_000
    raise BudgetBlocked('Endpoint not covered by the budget.')

class BudgetLedger:
    def __init__(self,path=None,limit_micro=LIMIT_MICRO,margin_micro=MARGIN_MICRO):
        self.path=Path(path or os.getenv('OPENAI_BUDGET_DB',str(DEFAULT_DB)))
        # This package cannot accidentally be configured above the requested $12.
        self.limit=min(limit_micro,LIMIT_MICRO)
        self.margin=margin_micro
        if self.limit<=0 or not 0<=self.margin<self.limit:raise ValueError('Invalid budget.')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('create table if not exists reservations(id integer primary key, created_at real not null, endpoint text not null, model text not null, amount_micro integer not null check(amount_micro>0))')
    def connect(self):return sqlite3.connect(self.path,timeout=30)
    def reserve(self,amount,endpoint,model):
        if type(amount) is not int or amount<=0:raise ValueError('Invalid reservation.')
        with self.connect() as db:
            db.execute('begin immediate')
            used=db.execute('select coalesce(sum(amount_micro),0) from reservations').fetchone()[0]
            if used+amount>self.limit-self.margin:
                raise BudgetBlocked('Local budget reached. Requests stopped to preserve the remaining balance.')
            db.execute('insert into reservations(created_at,endpoint,model,amount_micro) values(?,?,?,?)',(time.time(),endpoint,model,amount))
    def status(self):
        with self.connect() as db:
            used,count=db.execute('select coalesce(sum(amount_micro),0),count(*) from reservations').fetchone()
        return {'limit_usd':self.limit/1_000_000,'reserved_estimate_usd':used/1_000_000,
                'remaining_before_stop_usd':max(0,self.limit-self.margin-used)/1_000_000,
                'attempts':count,'automatic_monthly_reset':False}

def denied(request,error):
    return httpx.Response(429,request=request,json={'error':{'message':str(error),'type':'local_budget','code':'local_budget_exceeded'}})

class BudgetTransport(httpx.BaseTransport):
    def __init__(self,ledger=None,inner=None):
        self.ledger=ledger or default_ledger()
        self.inner=inner or httpx.HTTPTransport(retries=0,proxy=os.getenv('HTTPS_PROXY') or os.getenv('https_proxy'))
    def handle_request(self,request):
        try:
            model,amount=quote(request,request.read())
            reservation=self.ledger.reserve(amount,request.url.path,model)
        except BudgetBlocked as e:return denied(request,e)
        # Unknown network outcomes keep their reservation. No automatic refund.
        response=self.inner.handle_request(request)
        if hasattr(self.ledger,'settle') and response.is_success:
            response.read()
            actual=response_cost(request.url.path,model,response.json())
            if actual is not None:
                self.ledger.settle(reservation,actual)
        return response
    def close(self):self.inner.close()

class AsyncBudgetTransport(httpx.AsyncBaseTransport):
    def __init__(self,ledger=None,inner=None):
        self.ledger=ledger or default_ledger()
        self.inner=inner or httpx.AsyncHTTPTransport(retries=0,proxy=os.getenv('HTTPS_PROXY') or os.getenv('https_proxy'))
    async def handle_async_request(self,request):
        body=await request.aread()
        try:
            model,amount=quote(request,body)
            reservation=await asyncio.to_thread(self.ledger.reserve,amount,request.url.path,model)
        except BudgetBlocked as e:return denied(request,e)
        response=await self.inner.handle_async_request(request)
        if hasattr(self.ledger,'settle') and response.is_success:
            await response.aread()
            actual=response_cost(request.url.path,model,response.json())
            if actual is not None:
                await asyncio.to_thread(self.ledger.settle,reservation,actual)
        return response
    async def aclose(self):await self.inner.aclose()

def default_ledger():
    # Hosted mode must never silently fall back to a fresh local counter.
    if os.getenv('HOSTED_DEPLOYMENT')=='1':
        from deployment_state import RemoteBudgetLedger
        return RemoteBudgetLedger()
    return BudgetLedger()

def response_cost(endpoint,model,data):
    """Token-priced usage; keep full reservation on unknown/audio/error outcomes."""
    usage=data.get('usage')
    if not isinstance(usage,dict):return None
    def valid(value):
        if type(value) is not int or value<0:raise ValueError('Invalid token usage.')
        return Decimal(value)
    if endpoint=='/v1/embeddings' and model in EMBED_MODELS:
        return micro(valid(usage['prompt_tokens'])*Decimal('.02'))
    if endpoint=='/v1/chat/completions' and model in CHAT_MODELS:
        if data.get('service_tier','default') not in (None,'default','auto'):return None
        prompt=valid(usage['prompt_tokens']);output=valid(usage['completion_tokens'])
        cached=valid((usage.get('prompt_tokens_details') or {}).get('cached_tokens',0))
        if cached>prompt:raise ValueError('Invalid cached-token usage.')
        return micro((prompt-cached)*Decimal('.4')+cached*Decimal('.1')+output*Decimal('1.6'))
    return None

def budget_http_client():
    return httpx.Client(transport=BudgetTransport(),timeout=60,follow_redirects=False)
def budget_async_http_client():
    return httpx.AsyncClient(transport=AsyncBudgetTransport(),timeout=60,follow_redirects=False)

if __name__=='__main__':
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    print(json.dumps(default_ledger().status(),ensure_ascii=False,indent=2))
    print('Reservations are conservative estimates, not your OpenAI bill. Do not delete or reset the ledger.')
