import os
from pathlib import Path

import cohere
from dotenv import load_dotenv
from langchain_cohere import CohereEmbeddings


# قراءة المفتاح من ملف .env بجانب هذا الملف
PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")

api_key = os.getenv("COHERE_API_KEY")

if not api_key:
    raise ValueError(
        "لم يتم العثور على المفتاح. "
        "ضعي COHERE_API_KEY في ملف .env"
    )


# الاختبار الأول: إنشاء متجه للنص
print("1. اختبار التضمين...")

embeddings = CohereEmbeddings(
    model="embed-v4.0",
    cohere_api_key=api_key,
)

vectors = embeddings.embed_documents(
    ["معلومات القبول والتسجيل في الجامعة."]
)

if not vectors or not vectors[0]:
    raise RuntimeError("لم يتم إنشاء المتجه.")

print("نجح اختبار التضمين.")


# الاختبار الثاني: كتابة إجابة
print("\n2. اختبار توليد الإجابة...")

client = cohere.ClientV2(api_key=api_key)

response = client.chat(
    model=os.getenv(
        "COHERE_CHAT_MODEL",
        "command-a-03-2025",
    ),
    messages=[
        {
            "role": "user",
            "content": "اكتب بالعربية: الاتصال يعمل بنجاح.",
        }
    ],
    max_tokens=100,
)

answer = "\n".join(
    block.text
    for block in (response.message.content or [])
    if getattr(block, "type", "") == "text"
)

if not answer.strip():
    raise RuntimeError("لم تصل إجابة نصية.")

print(answer)
print("\nنجح الاختباران!")
