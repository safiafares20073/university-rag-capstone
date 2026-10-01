from pathlib import Path
from pypdf import PdfReader


# مسار مجلد المراجع
DATA_DIR = Path(r"C:\Users\DELL\Downloads\المراجع")

if not DATA_DIR.is_dir():
    raise FileNotFoundError(f"المجلد غير موجود: {DATA_DIR}")


# جمع الملفات من جميع المجلدات الفرعية
supported_extensions = {".pdf", ".txt", ".md"}

files = sorted(
    path
    for path in DATA_DIR.rglob("*")
    if path.is_file()
    and path.suffix.lower() in supported_extensions
)

readable_files = 0
total_pdf_pages = 0
needs_review = []

print(f"عدد ملفات المصادر: {len(files)}\n")


# فحص إمكانية استخراج النص
for path in files:
    relative_path = path.relative_to(DATA_DIR)

    try:
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(str(path))

            page_count = len(reader.pages)
            total_pdf_pages += page_count
            text_pages = 0

            for page in reader.pages:
                text = page.extract_text() or ""

                if text.strip():
                    text_pages += 1

            print(f"الملف: {relative_path}")
            print(
                f"الصفحات: {page_count} | "
                f"صفحات استُخرج منها نص: {text_pages}\n"
            )

            if text_pages > 0:
                readable_files += 1

            if page_count == 0 or text_pages < page_count:
                needs_review.append(str(relative_path))

        else:
            text = path.read_text(encoding="utf-8")

            if text.strip():
                readable_files += 1
                print(f"{relative_path} | يحتوي على نص\n")
            else:
                needs_review.append(str(relative_path))
                print(f"{relative_path} | فارغ\n")

    except Exception as error:
        needs_review.append(str(relative_path))
        print(f"تعذرت قراءة: {relative_path}")
        print(f"السبب: {error}\n")


# ملخص النتائج
print("=" * 40)
print("نتيجة فحص المصادر")
print("=" * 40)

print(f"إجمالي الملفات: {len(files)}")
print(f"إجمالي صفحات PDF: {total_pdf_pages}")
print(f"ملفات استُخرج منها نص: {readable_files}")
print(f"ملفات تحتاج مراجعة: {len(needs_review)}")

if needs_review:
    print("\nالملفات التي تحتاج مراجعة:")

    for name in needs_review:
        print(f"- {name}")
else:
    print("\nاستُخرج نص من جميع الصفحات والملفات المفحوصة.")

print(
    "\nالصفحات بلا نص قد تكون صورًا تحتاج OCR أو صفحات فارغة. "
    "وجود نص مستخرج لا يضمن صحة النص العربي."
)

print("\nانتهى الفحص.")

print("\n--- أرقام الصفحات التي تحتاج مراجعة ---")

for path in files:
    if path.suffix.lower() != ".pdf":
        continue

    try:
        reader = PdfReader(str(path))
        missing_pages = []

        for page_number, page in enumerate(reader.pages, start=1):
            if not (page.extract_text() or "").strip():
                missing_pages.append(page_number)

        if missing_pages:
            print(f"\n{path.relative_to(DATA_DIR)}")
            print(f"الصفحات بلا نص: {missing_pages}")

    except Exception as error:
        print(f"تعذرت قراءة {path.name}: {error}")