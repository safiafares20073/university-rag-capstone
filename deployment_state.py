"""Server-held deployment credential. Never expose it to browsers or Git."""
import os
import httpx

def rpc(name, **params):
    url=os.getenv('SUPABASE_URL','').rstrip('/')
    key=os.getenv('SUPABASE_PUBLISHABLE_KEY','').strip()
    token=os.getenv('DEPLOYMENT_TOKEN','').strip()
    if not url.startswith('https://') or not url.endswith('.supabase.co') or not key or not token:
        raise RuntimeError('Deployment settings missing or invalid.')
    with httpx.Client(timeout=120,follow_redirects=False) as client:
        response=client.post(url+'/rest/v1/rpc/'+name,headers={'apikey':key,'Content-Type':'application/json'},json={'p_token':token,**params})
    if not response.is_success:
        if 'DEPLOYMENT_BUDGET_REACHED' in response.text:
            from api_budget import BudgetBlocked
            raise BudgetBlocked('Persistent deployment budget reached.')
        raise RuntimeError('Deployment service request failed (HTTP '+str(response.status_code)+').')
    return response.json() if response.content else None

class RemoteBudgetLedger:
    def reserve(self,amount,endpoint,model):
        from uuid import uuid4
        request_id=str(uuid4())
        rpc('rag_reserve',p_request_id=request_id,p_amount_micro=amount,p_endpoint=endpoint,p_model=model)
        return request_id
    def settle(self,request_id,amount):
        rpc('rag_settle',p_request_id=request_id,p_amount_micro=amount)
    def status(self):return rpc('rag_budget_status')
