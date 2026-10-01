import os
import re
import time
import hashlib
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_cohere import CohereEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter


# =========================
# 1. إعداد المسارات
# =========================

PROJECT_DIR = Path(__file__).resolve().parent

# مصادر الجامعة؛ لا تحتاجين نقلها إلى مجلد المشروع
DATA_DIR = PROJECT_DIR / "docs"

# قاعدة البيانات تُحفظ داخل مجلد المشروع
DB_DIR = PROJECT_DIR / "chroma_db_cohere"

COLLECTION_NAME = "university_sources_v1"
EMBEDDING_MODEL = "embed-v4.0"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
BATCH_SIZE = 16

load_dotenv(PROJECT_DIR / ".env")

API_KEY = os.getenv("COHERE_API_KEY")

# التعرف على علامات الصفحات في ملفَي الرسوم واللائحة
PAGE_MARKER = re.compile(
    r"^===.*?الصفحة الأصلية\s+(\d+).*?===\s*$",
    re.MULTILINE,
)


# =========================
# 2. البيانات الوصفية
# =========================

def get_metadata(file_path):
    relative = file_path.relative_to(DATA_DIR)
    folders = relative.parts[:-1]

    return {
        "source": str(file_path),
        "source_file": file_path.name,
        "relative_path": relative.as_posix(),
        "college": folders[0] if folders else "عام",
        "department": "/".join(folders[1:]) if len(folders) > 1 else "",
    }


# =========================
# 3. قراءة المصادر
# =========================

def load_pdf(file_path):
    reader = PdfReader(str(file_path))
    metadata = get_metadata(file_path)
    documents = []

    for page_index, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()

        # تجاهل الصفحات التي لا تحتوي على نص
        if not text:
            continue

        page_metadata = {
            **metadata,
            "page": page_index,
            "page_number": page_index + 1,
            "unit_index": page_index,
        }

        documents.append(
            Document(
                page_content=text,
                metadata=page_metadata,
            )
        )

    return documents


def load_text(file_path):
    text = file_path.read_text(encoding="utf-8-sig").strip()

    if not text:
        return []

    metadata = get_metadata(file_path)
    markers = list(PAGE_MARKER.finditer(text))

    # ملف نصي عادي، لا يحتوي على علامات صفحات
    if not markers:
        return [
            Document(
                page_content=text,
                metadata={**metadata, "unit_index": 0},
            )
        ]

    # الاحتفاظ بالمعلومات العامة مثل تاريخ اللائحة
    header = text[:markers[0].start()].strip()
    documents = []

    original_names = {
        "Fees_text.txt": "Fees.pdf",
        "Academic_Regulations_text.txt":
            "لائحة-الأكاديمية-للطلبة-فصلي-سنوي.pdf",
    }

    original_name = original_names.get(file_path.name)

    for index, marker in enumerate(markers):
        page_number = int(marker.group(1))

        end = (
            markers[index + 1].start()
            if index + 1 < len(markers)
            else len(text)
        )

        page_text = text[marker.end():end].strip()

        if not page_text:
            continue

        content = (
            f"{header}\n\n{page_text}"
            if header
            else page_text
        )

        page_metadata = {
            **metadata,
            "page": page_number - 1,
            "page_number": page_number,
            "unit_index": index,
        }

        if original_name:
            page_metadata["original_source_file"] = original_name

        documents.append(
            Document(
                page_content=content,
                metadata=page_metadata,
            )
        )

    return documents


# =========================
# 4. التقطيع والفهرسة
# =========================

def main():
    if not API_KEY:
        raise RuntimeError(
            "لم أجد COHERE_API_KEY في ملف .env بجانب ingest.py"
        )

    if not DATA_DIR.is_dir():
        raise FileNotFoundError(
            f"مجلد المصادر غير موجود: {DATA_DIR}"
        )

    files = sorted(
        (
            path
            for path in DATA_DIR.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {".pdf", ".txt", ".md"}
        ),
        key=lambda path: path.as_posix().lower(),
    )

    if not files:
        raise RuntimeError("لم أجد ملفات PDF أو TXT أو MD.")

    documents = []
    failed_files = []

    print(f"عدد ملفات المصادر: {len(files)}")

    for index, file_path in enumerate(files, start=1):
        relative = file_path.relative_to(DATA_DIR)
        print(f"[{index}/{len(files)}] قراءة: {relative}")

        try:
            if file_path.suffix.lower() == ".pdf":
                loaded = load_pdf(file_path)
            else:
                loaded = load_text(file_path)

            documents.extend(loaded)

            if not loaded:
                print("  تنبيه: هذا الملف لا يحتوي على نص قابل للقراءة.")

        except Exception as error:
            failed_files.append(str(relative))
            print(f"  تعذر قراءة الملف: {error}")

    # نتوقف قبل تغيير الفهرس إذا فشلت قراءة أحد الملفات
    if failed_files:
        raise RuntimeError(
            "توقفت الفهرسة بسبب ملفات تعذرت قراءتها:\n"
            + "\n".join(failed_files)
        )

    if not documents:
        raise RuntimeError("لم يُستخرج أي نص من المصادر.")

    print(f"\nعدد الصفحات/الوحدات النصية: {len(documents)}")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "،", " ", ""],
    )

    chunks = []
    chunk_ids = []

    # نقطع كل صفحة منفصلة للحفاظ على رقمها
    for document in documents:
        page_chunks = splitter.split_documents([document])

        for chunk_index, chunk in enumerate(page_chunks):
            chunk.metadata["chunk_index"] = chunk_index

            identity = (
                f"{EMBEDDING_MODEL}|"
                f"{CHUNK_SIZE}|{CHUNK_OVERLAP}|"
                f"{chunk.metadata['relative_path']}|"
                f"{chunk.metadata['unit_index']}|"
                f"{chunk_index}|{chunk.page_content}"
            )

            chunk_id = hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest()

            chunks.append(chunk)
            chunk_ids.append(chunk_id)

    print(f"عدد المقاطع: {len(chunks)}")

    embeddings = CohereEmbeddings(
        model=EMBEDDING_MODEL,
        cohere_api_key=API_KEY,
    )

    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(DB_DIR),
    )

    existing_ids = set(vectorstore.get(include=[])["ids"])
    current_ids = set(chunk_ids)

    pending = [
        (chunk, chunk_id)
        for chunk, chunk_id in zip(chunks, chunk_ids)
        if chunk_id not in existing_ids
    ]

    print(f"المقاطع الجديدة المطلوب تخزينها: {len(pending)}")

    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]

        vectorstore.add_documents(
            documents=[item[0] for item in batch],
            ids=[item[1] for item in batch],
        )

        completed = start + len(batch)
        print(f"تم تخزين {completed}/{len(pending)} مقطع جديد.")

        if completed < len(pending):
            time.sleep(15)

    # إزالة المقاطع القديمة بعد نجاح تخزين النسخة الحالية
    stale_ids = list(existing_ids - current_ids)

    for start in range(0, len(stale_ids), 500):
        vectorstore.delete(ids=stale_ids[start:start + 500])

    stored_count = len(vectorstore.get(include=[])["ids"])

    print("\nنجحت الفهرسة!")
    print(f"عدد المقاطع المحفوظة: {stored_count}")
    print(f"مكان قاعدة البيانات: {DB_DIR}")


if __name__ == "__main__":
    main()