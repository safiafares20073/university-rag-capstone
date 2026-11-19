"""Publish an existing OpenAI index once, or restore it without paid embedding calls."""
import base64,gzip,hashlib,json,math,os
from pathlib import Path
from dotenv import load_dotenv
from deployment_state import rpc
ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
MODEL='text-embedding-3-small'
COLLECTION='university_openai_v1'

def validate(data):
    if data.get('model')!=MODEL or data.get('provider')!='openai' or not data.get('records'):
        raise ValueError('Snapshot model/provider mismatch or empty snapshot.')
    ids=set()
    for row in data['records']:
        if not isinstance(row['id'],str) or row['id'] in ids or not isinstance(row['text'],str):raise ValueError('Invalid snapshot record.')
        ids.add(row['id'])
        if len(row['embedding'])!=1536 or not all(type(x) in (int,float) and math.isfinite(x) for x in row['embedding']):raise ValueError('Invalid embedding.')

def publish():
    import chromadb
    from llm_backend import DB_DIR,EMBEDDING_MODEL
    if EMBEDDING_MODEL!=MODEL:raise ValueError('Unexpected embedding model.')
    if not (DB_DIR/'chroma.sqlite3').exists():raise FileNotFoundError('Local OpenAI index missing.')
    collection=chromadb.PersistentClient(path=str(DB_DIR)).get_collection(COLLECTION,embedding_function=None)
    meta=collection.metadata or {}
    if meta.get('provider')!='openai' or meta.get('embedding_model')!=MODEL or not meta.get('index_ready'):raise ValueError('Index is not ready.')
    stored=collection.get(include=['embeddings','documents','metadatas'])
    data={'provider':'openai','model':MODEL,'records':[]}
    for id_,embedding,text,metadata in zip(stored['ids'],stored['embeddings'],stored['documents'],stored['metadatas']):
        clean={k:v for k,v in (metadata or {}).items() if k!='source'}
        data['records'].append({'id':id_,'embedding':embedding.tolist(),'text':text,'metadata':clean})
    validate(data)
    packed=gzip.compress(json.dumps(data,ensure_ascii=False,allow_nan=False).encode(),mtime=0)
    print('Publishing existing vectors:',len(data['records']),'chunks;',round(len(packed)/1024/1024,2),'MB. No embedding API calls.',flush=True)
    rpc('rag_publish_index',p_payload=base64.b64encode(packed).decode(),p_sha256=hashlib.sha256(packed).hexdigest())
    print('INDEX PUBLISHED')

def _restore_index():
    import chromadb
    from llm_backend import DB_DIR
    DB_DIR.mkdir(parents=True,exist_ok=True)
    client=chromadb.PersistentClient(path=str(DB_DIR))
    try:
        current=client.get_collection(COLLECTION,embedding_function=None)
        meta=current.metadata or {}
        if meta.get('provider')=='openai' and meta.get('embedding_model')==MODEL and meta.get('index_ready') and current.count():return
    except Exception:pass
    response=rpc('rag_get_index')
    packed=base64.b64decode(response['payload'],validate=True)
    if len(packed)>45000000 or hashlib.sha256(packed).hexdigest()!=response['sha256']:raise ValueError('Snapshot integrity failure.')
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        raw=stream.read(150000001)
    if len(raw)>150000000:raise ValueError('Snapshot exceeds size limit.')
    data=json.loads(raw);validate(data)
    try:client.delete_collection(COLLECTION)
    except Exception:pass
    collection=client.create_collection(COLLECTION,embedding_function=None,metadata={'provider':'openai','embedding_model':MODEL,'index_ready':False})
    for i in range(0,len(data['records']),100):
        rows=data['records'][i:i+100]
        collection.add(ids=[r['id'] for r in rows],embeddings=[r['embedding'] for r in rows],documents=[r['text'] for r in rows],metadatas=[r['metadata'] or {'provider':'openai'} for r in rows])
    if collection.count()!=len(data['records']):raise RuntimeError('Incomplete index restore.')
    collection.modify(metadata={'provider':'openai','embedding_model':MODEL,'index_ready':True})

import threading
_INDEX_LOCK=threading.Lock()
def ensure_index():
    with _INDEX_LOCK:
        _restore_index()

if __name__=='__main__':publish()
