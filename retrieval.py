import os
import re
import unicodedata
from pathlib import Path
from collections import defaultdict

import cohere
import chromadb
from dotenv import load_dotenv
from rank_bm25 import BM25Okapi
from langchain_cohere import CohereEmbeddings
from pypdf import PdfReader


# =========================
# 1. الإعدادات
# =========================

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "docs"
DB_DIR = PROJECT_DIR / "chroma_db_cohere"

COLLECTION_NAME = "university_sources_v1"
EMBEDDING_MODEL = "embed-v4.0"
RERANK_MODEL = "rerank-v3.5"

SEARCH_K = 20
RERANK_K = 30
TOP_K = 5

MAX_FULL_PLAN_CHARACTERS = 60000

load_dotenv(PROJECT_DIR / ".env")


# =========================
# 2. تجهيز كلمات البحث
# =========================

def tokenize(text):
    text = unicodedata.normalize("NFKC", text).lower()

    # إزالة التشكيل والتطويل
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    text = text.replace("ـ", "")

    # توحيد بعض أشكال الحروف للبحث بالكلمات
    text = text.translate(
        str.maketrans({
            "أ": "ا",
            "إ": "ا",
            "آ": "ا",
            "ٱ": "ا",
            "ى": "ي",
        })
    )

    return re.findall(r"\w+", text, flags=re.UNICODE)


def normalize_relative_path(path):
    return str(path).replace("\\", "/")


# =========================
# 3. تحميل الفهرس
# =========================

class UniversityRetriever:
    def __init__(self):
        api_key = os.getenv("COHERE_API_KEY")

        if not api_key:
            raise RuntimeError(
                "لم أجد COHERE_API_KEY في ملف .env"
            )

        if not (DB_DIR / "chroma.sqlite3").is_file():
            raise FileNotFoundError(
                f"لم أجد قاعدة البيانات في: {DB_DIR}\n"
                "تأكدي من وجود قاعدة البيانات الناتجة عن ingest.py."
            )

        self.client = chromadb.PersistentClient(
            path=str(DB_DIR)
        )

        self.collection = self.client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=None,
        )

        stored = self.collection.get(
            include=["documents", "metadatas"]
        )

        self.records = {}
        self.ids = []
        self.token_sets = []
        corpus = []

        for chunk_id, text, metadata in zip(
            stored["ids"],
            stored["documents"],
            stored["metadatas"],
        ):
            if not text or not text.strip():
                continue

            tokens = tokenize(text)

            if not tokens:
                continue

            self.records[chunk_id] = {
                "id": chunk_id,
                "text": text,
                "metadata": metadata or {},
            }

            self.ids.append(chunk_id)
            corpus.append(tokens)
            self.token_sets.append(set(tokens))

        if not self.ids:
            raise RuntimeError(
                "قاعدة البيانات لا تحتوي على نصوص."
            )

        self.bm25 = BM25Okapi(corpus)

        self.embeddings = CohereEmbeddings(
            model=EMBEDDING_MODEL,
            cohere_api_key=api_key,
        )

        self.cohere_client = cohere.ClientV2(
            api_key=api_key
        )

        print(f"تم تحميل {len(self.ids)} مقطعًا للبحث.")

    # =========================
    # 4. قائمة الخطط الدراسية
    # =========================

    def list_study_plans(self):
        """إرجاع أسماء ومسارات الخطط الموجودة في الفهرس."""
        plans = {}

        for record in self.records.values():
            metadata = record["metadata"]

            relative_path = normalize_relative_path(
                metadata.get("relative_path", "")
            )

            if not relative_path:
                continue

            filename = (
                metadata.get("source_file")
                or Path(relative_path).name
            )

            normalized_name = " ".join(tokenize(filename))

            is_study_plan = (
                "الخطة" in normalized_name
                or "خطة" in normalized_name
                or "study plan" in normalized_name
            )

            if is_study_plan:
                plans[relative_path] = {
                    "relative_path": relative_path,
                    "source_file": filename,
                }

        return sorted(
            plans.values(),
            key=lambda item: item["relative_path"],
        )

    # =========================
    # 5. قراءة خطة كاملة
    # =========================

    def load_full_plan(self, relative_path):
        """
        قراءة ملف الخطة الأصلي صفحة بصفحة.

        لا نجمع المقاطع المتداخلة، حتى لا يتكرر النص
        بسبب chunk_overlap.
        """
        relative_path = normalize_relative_path(relative_path)

        # يجب أن يكون الملف من الخطط المعروفة في الفهرس.
        allowed_paths = {
            plan["relative_path"]
            for plan in self.list_study_plans()
        }

        if relative_path not in allowed_paths:
            raise ValueError(
                "الخطة المطلوبة غير موجودة ضمن الخطط المفهرسة."
            )

        docs_dir = DATA_DIR.resolve()
        file_path = (docs_dir / relative_path).resolve()

        # منع قراءة ملفات خارج مجلد docs.
        if not file_path.is_relative_to(docs_dir):
            raise ValueError("مسار الخطة غير صالح.")

        if not file_path.is_file():
            raise FileNotFoundError(
                f"لم أجد ملف الخطة الأصلي داخل docs:\n"
                f"{relative_path}"
            )

        if file_path.suffix.lower() != ".pdf":
            raise ValueError(
                "قراءة الخطة كاملة تدعم ملفات PDF حاليًا."
            )

        indexed_records = [
            record
            for record in self.records.values()
            if normalize_relative_path(
                record["metadata"].get("relative_path", "")
            ) == relative_path
        ]

        if not indexed_records:
            raise ValueError(
                "لم أجد بيانات الخطة في الفهرس."
            )

        base_metadata = dict(
            indexed_records[0]["metadata"]
        )

        reader = PdfReader(str(file_path))
        pages = []
        total_characters = 0

        for page_number, page in enumerate(
            reader.pages,
            start=1,
        ):
            text = unicodedata.normalize(
                "NFKC",
                page.extract_text() or "",
            ).strip()

            if not text:
                continue

            total_characters += len(text)

            # لا نرسل جزءًا من الملف باعتباره خطة كاملة.
            if total_characters > MAX_FULL_PLAN_CHARACTERS:
                raise ValueError(
                    "الخطة أكبر من الحد المخصص للقراءة الكاملة."
                )

            pages.append({
                "id": (
                    f"full-plan:{relative_path}:{page_number}"
                ),
                "text": text,
                "metadata": {
                    **base_metadata,
                    "relative_path": relative_path,
                    "source": str(file_path),
                    "source_file": file_path.name,
                    "page": page_number - 1,
                    "page_number": page_number,
                },
            })

        if not pages:
            raise ValueError(
                "لم أتمكن من استخراج نص الخطة."
            )

        return pages

    # =========================
    # 6. البحث الدلالي
    # =========================

    def semantic_search(self, question):
        query_vector = self.embeddings.embed_query(question)

        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=min(
                SEARCH_K,
                self.collection.count(),
            ),
            include=[
                "documents",
                "metadatas",
                "distances",
            ],
        )

        return [
            chunk_id
            for chunk_id in results["ids"][0]
            if chunk_id in self.records
        ]

    # =========================
    # 7. البحث بالكلمات BM25
    # =========================

    def keyword_search(self, question):
        query_tokens = tokenize(question)

        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)
        query_set = set(query_tokens)

        matching_indices = [
            index
            for index, tokens in enumerate(self.token_sets)
            if tokens.intersection(query_set)
        ]

        ranked_indices = sorted(
            matching_indices,
            key=lambda index: float(scores[index]),
            reverse=True,
        )

        return [
            self.ids[index]
            for index in ranked_indices[:SEARCH_K]
        ]

    # =========================
    # 8. دمج النتائج باستخدام RRF
    # =========================

    def hybrid_search(self, question):
        semantic_ids = self.semantic_search(question)
        keyword_ids = self.keyword_search(question)

        fused_scores = defaultdict(float)

        for ranked_ids in (semantic_ids, keyword_ids):
            for rank, chunk_id in enumerate(
                ranked_ids,
                start=1,
            ):
                fused_scores[chunk_id] += 1.0 / (60 + rank)

        ranked_ids = sorted(
            fused_scores,
            key=lambda chunk_id: fused_scores[chunk_id],
            reverse=True,
        )

        return [
            {
                **self.records[chunk_id],
                "rrf_score": fused_scores[chunk_id],
            }
            for chunk_id in ranked_ids[:RERANK_K]
        ]

    # =========================
    # 9. إعادة ترتيب النتائج
    # =========================

    def retrieve(self, question, top_k=TOP_K):
        question = question.strip()

        if not question:
            raise ValueError("السؤال فارغ.")

        if top_k < 1:
            raise ValueError(
                "عدد النتائج يجب أن يكون أكبر من صفر."
            )

        candidates = self.hybrid_search(question)

        if not candidates:
            return []

        response = self.cohere_client.rerank(
            model=RERANK_MODEL,
            query=question,
            documents=[
                item["text"]
                for item in candidates
            ],
            top_n=min(top_k, len(candidates)),
        )

        return [
            {
                **candidates[result.index],
                "rerank_score": float(
                    result.relevance_score
                ),
            }
            for result in response.results
        ]


# =========================
# 10. عرض نتائج البحث
# =========================

def display_results(results):
    for rank, result in enumerate(results, start=1):
        metadata = result["metadata"]

        source = (
            metadata.get("original_source_file")
            or metadata.get("source_file")
            or metadata.get("relative_path")
            or "مصدر غير محدد"
        )

        page = metadata.get("page_number")
        page_label = (
            str(page) if page is not None else "غير متوفر"
        )

        print("\n" + "=" * 60)
        print(f"النتيجة: {rank}")
        print(f"المصدر: {source}")
        print(f"الصفحة الأصلية: {page_label}")
        print(f"الكلية: {metadata.get('college', 'عام')}")

        if "rerank_score" in result:
            print(
                "درجة إعادة الترتيب: "
                f"{result['rerank_score']:.4f}"
            )

        print(f"معرف المقطع: {result['id']}")
        print("-" * 60)
        print(result["text"])


# =========================
# 11. اختبار البحث تفاعليًا
# =========================

def main():
    retriever = UniversityRetriever()

    print("\nالبحث الهجين وإعادة الترتيب جاهزان.")
    print("اكتبي سؤالًا، أو اكتبي خروج لإنهاء البرنامج.")

    while True:
        question = input("\nسؤالك: ").strip()

        if question.lower() in {"خروج", "exit", "quit"}:
            break

        if not question:
            continue

        try:
            results = retriever.retrieve(question)
            display_results(results)

            if not results:
                print("لم تُسترجع مقاطع.")

        except Exception as error:
            print(f"\nتعذر تنفيذ البحث: {error}")
            print(
                "إذا ظهر خطأ 429، انتظري دقيقة ثم أعيدي السؤال."
            )


if __name__ == "__main__":
    main()