import json
import re
import time
import unicodedata
from pathlib import Path
from datetime import datetime, timezone

from retrieval import UniversityRetriever


PROJECT_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = PROJECT_DIR / "golden_questions.json"
RESULTS_FILE = PROJECT_DIR / "retrieval_evaluation.json"

TOP_K = 5

# تقليل احتمال تجاوز حدود الحساب التجريبي
DELAY_SECONDS = 12


def normalize(text):
    """توحيد أشكال Unicode وإزالة المسافات للمقارنة النصية."""
    text = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"\s+", "", text)


def normalize_path(path):
    return unicodedata.normalize(
        "NFKC", str(path).replace("\\", "/")
    )


def supports_evidence(record, evidence):
    """لا يكفي تطابق الملف؛ يجب وجود النص الداعم أيضًا."""
    metadata = record["metadata"]

    same_source = (
        normalize_path(metadata.get("relative_path", ""))
        == normalize_path(evidence["relative_path"])
    )

    same_page = (
        metadata.get("page_number")
        == evidence["page_number"]
    )

    if not same_source or not same_page:
        return False

    text = normalize(record["text"])

    return all(
        normalize(anchor) in text
        for anchor in evidence["match_all"]
    )


def prepare_references(questions, records):
    """
    تحديد جميع المقاطع التي تطابق الأدلة المرجعية
    قبل تشغيل البحث، بصورة مستقلة عن نتائجه.
    """
    references = {}
    missing = []

    for question in questions:
        relevant_ids = set()

        for evidence in question["relevant_evidence"]:
            matching_ids = {
                chunk_id
                for chunk_id, record in records.items()
                if supports_evidence(record, evidence)
            }

            if not matching_ids:
                missing.append({
                    "question_id": question["id"],
                    "question": question["question"],
                    "evidence": evidence,
                })

            relevant_ids.update(matching_ids)

        references[question["id"]] = relevant_ids

    return references, missing


def retrieve_with_retry(retriever, question):
    """إعادة المحاولة عند تجاوز حد الاستخدام فقط."""
    for attempt in range(3):
        try:
            return retriever.retrieve(question, top_k=TOP_K)

        except Exception as error:
            status = getattr(error, "status_code", None)

            if status != 429 or attempt == 2:
                raise

            print("بلغنا حد الاستخدام؛ انتظار 60 ثانية...")
            time.sleep(60)


def save_report(report):
    RESULTS_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    if not QUESTIONS_FILE.is_file():
        raise FileNotFoundError(
            "ضعي golden_questions.json بجانب ملف التقييم."
        )

    dataset = json.loads(
        QUESTIONS_FILE.read_text(encoding="utf-8-sig")
    )

    questions = dataset["questions"]

    if len(questions) != 30:
        raise ValueError("نتوقع وجود 30 سؤالًا مرجعيًا.")

    retriever = UniversityRetriever()

    references, missing = prepare_references(
        questions, retriever.records
    )

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "top_k": TOP_K,
        "question_count": len(questions),
        "indexed_chunks": len(retriever.records),
        "status": "running",
        "metric_notes": [
            "Recall@5 لكل سؤال = عدد المقاطع المرجعية "
            "المسترجعة ضمن أول 5 / عدد المقاطع المرجعية.",
            "النتيجة العامة هي متوسط Recall@5 للأسئلة.",
            "Hit@5 يقيس وجود مقطع مرجعي واحد على الأقل؛ "
            "وهو مقياس مختلف عن Recall@5.",
            "المرجع مقيد بالمصادر والصفحات والنصوص "
            "المحددة في مجموعة الأسئلة.",
            "هذا تقييم للاسترجاع، وليس لصحة إجابة مولدة.",
        ],
        "results": [],
    }

    # التحقق من المرجع قبل استهلاك طلبات API
    if missing:
        report["status"] = "reference_validation_failed"
        report["missing_evidence"] = missing
        save_report(report)

        print("\nتوقّف الاختبار قبل إرسال الأسئلة.")
        print("بعض الأدلة لا تطابق مقطعًا كاملًا في الفهرس:")

        for item in missing:
            print(f"- {item['question_id']}: {item['question']}")

        print("\nأرسلي هذه النتيجة لنراجع تطابق الأدلة والتقطيع.")
        print(f"التفاصيل محفوظة في: {RESULTS_FILE}")
        return

    print("\nنجح التحقق من الأدلة المرجعية.")
    print("بدأ تقييم 30 سؤالًا. قد يستغرق عدة دقائق.\n")

    for index, question in enumerate(questions, start=1):
        question_id = question["id"]
        relevant_ids = references[question_id]

        print(f"[{index}/30] {question['question']}")

        entry = {
            "id": question_id,
            "question": question["question"],
            "reference_answer": question["reference_answer"],
            "relevant_evidence": question["relevant_evidence"],
            "relevant_chunk_ids": sorted(relevant_ids),
        }

        try:
            retrieved = retrieve_with_retry(
                retriever, question["question"]
            )[:TOP_K]

            retrieved_ids = {item["id"] for item in retrieved}
            matched_ids = relevant_ids.intersection(retrieved_ids)

            recall = len(matched_ids) / len(relevant_ids)
            hit = bool(matched_ids)

            entry.update({
                "status": "completed",
                "retrieved_chunks": retrieved,
                "matched_chunk_ids": sorted(matched_ids),
                "recall_at_5": recall,
                "hit_at_5": hit,
            })

            print(
                f"  Recall@5: {recall:.1%} | "
                f"مقاطع مرجعية مسترجعة: "
                f"{len(matched_ids)}/{len(relevant_ids)}"
            )

        except Exception as error:
            entry.update({
                "status": "error",
                "error": str(error),
                "recall_at_5": None,
                "hit_at_5": None,
            })

            print(f"  تعذر تنفيذ السؤال: {error}")

        report["results"].append(entry)

        # حفظ النتائج بعد كل سؤال لحماية العمل المكتمل
        save_report(report)

        if index < len(questions):
            time.sleep(DELAY_SECONDS)

    completed = [
        item
        for item in report["results"]
        if item["status"] == "completed"
    ]

    errors = len(questions) - len(completed)

    mean_recall = (
        sum(item["recall_at_5"] for item in completed)
        / len(completed)
        if completed
        else None
    )

    hit_rate = (
        sum(item["hit_at_5"] for item in completed)
        / len(completed)
        if completed
        else None
    )

    report["status"] = (
        "completed" if errors == 0 else "incomplete"
    )

    report["summary"] = {
        "completed_questions": len(completed),
        "failed_requests": errors,
        "mean_recall_at_5": mean_recall,
        "hit_rate_at_5": hit_rate,
        "target": "Recall@5 > 80%",
        "target_met": (
            mean_recall > 0.80
            if errors == 0 and mean_recall is not None
            else None
        ),
    }

    save_report(report)

    print("\n" + "=" * 60)
    print(f"الأسئلة المكتملة: {len(completed)}/30")
    print(f"أخطاء الطلبات: {errors}")

    if mean_recall is not None:
        print(f"متوسط Recall@5: {mean_recall:.2%}")
        print(f"Hit@5: {hit_rate:.2%}")

    if errors:
        print("التقييم غير مكتمل؛ لا نعتمد النتيجة النهائية بعد.")
    elif report["summary"]["target_met"]:
        print("تحقق هدف Recall@5 الأعلى من 80%.")
    else:
        print("لم يتحقق الهدف بعد؛ سنراجع النتائج لتحسين البحث.")

    print(f"حُفظ التقرير في: {RESULTS_FILE}")


if __name__ == "__main__":
    main()