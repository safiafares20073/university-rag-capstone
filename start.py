"""Deployment bootstrap; initial embedding requires explicit opt-in."""
import os
import sys
import subprocess
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
from llm_backend import DB_DIR,COLLECTION_NAME,EMBEDDING_MODEL
def main():
    ready=False
    if (DB_DIR/'chroma.sqlite3').is_file():
        import chromadb
        try:
            c=chromadb.PersistentClient(path=str(DB_DIR)).get_collection(COLLECTION_NAME,embedding_function=None)
            m=c.metadata or {}
            ready=m.get('index_ready') and m.get('provider')=='openai' and m.get('embedding_model')==EMBEDDING_MODEL
        except Exception:pass
    if not ready:
        if os.getenv('BUILD_INDEX_ON_START')!='1':raise SystemExit('Run python ingest.py first, or explicitly enable BUILD_INDEX_ON_START=1.')
        subprocess.run([sys.executable,str(ROOT/'ingest.py')],cwd=ROOT,check=True)
    os.execv(sys.executable,[sys.executable,'-m','streamlit','run',str(ROOT/'app.py'),'--server.address=0.0.0.0',f'--server.port={os.getenv("PORT","8501")}'])
if __name__=='__main__':main()
