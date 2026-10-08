"""Ragas 0.4.3 / Cohere: 20 fixed reference questions, resumable evaluation.
Run from PyCharm alongside rag.py and golden_questions.json.
"""
import asyncio
import argparse
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from dotenv import load_dotenv
from langchain_cohere import ChatCohere
from langchain_core.callbacks import BaseCallbackHandler
from ragas import SingleTurnSample
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import Faithfulness, FactualCorrectness, LLMContextRecall
from ragas.run_config import RunConfig
from rag import UniversityRAG

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / 'golden_questions.json'
REPORT = ROOT / 'ragas_evaluation_final_v3.json'
SELECTED = ['Q01', 'Q02', 'Q03', 'Q06', 'Q07', 'Q09', 'Q10', 'Q13',
            'Q14', 'Q15', 'Q16', 'Q17', 'Q18', 'Q19', 'Q20', 'Q23',
            'Q24', 'Q25', 'Q27', 'Q30']
NAMES = ['faithfulness', 'factual_correctness', 'context_recall']

# Full sentences give short numeric references their intended subject.
# Values are unchanged; original reference text remains in the report.
REFERENCE_SENTENCES = {
    'Q01': 'الرسوم السنوية لتقنية المعلومات IT بعد التخفيض هي 592,500 ريال يمني، وقد تتغير بحسب المواد المسجلة.',
    'Q02': 'الرسوم السنوية لتقنية المعلومات باللغة الإنجليزية BIT بعد التخفيض هي 640,800 ريال يمني.',
    'Q03': 'معدل القبول المذكور للطب والجراحة هو 78%.',
    'Q06': 'رسوم التسجيل لبرنامج إدارة الأعمال في التعليم الإلكتروني هي 25,000 ريال يمني وتدفع مرة واحدة.',
    'Q09': 'درجة النجاح في المقرر أو البلوك هي 50%، والدرجة النهائية هي 100 درجة.',
    'Q10': 'يمنع الطالب من دخول الاختبار إذا تأخر عن موعد بدء الاختبار بأكثر من نصف ساعة.',
    'Q14': 'يعرض دليل التعليم الإلكتروني سبعة برامج بكالوريوس.',
    'Q17': 'مجموع الساعات المعتمدة في الخطة الجديدة لبكالوريوس تقنية المعلومات العربية هو 138 ساعة معتمدة.',
    'Q18': 'المدة القياسية لبكالوريوس تقنية المعلومات العربية بحسب الخطة أربع سنوات وثمانية مستويات؛ وقد تتراوح بين ثلاث وخمس سنوات بحسب نظام الساعات.',
    'Q19': 'المتطلب السابق لمشروع التخرج 2 في خطة تقنية المعلومات العربية هو مشروع التخرج 1 ورمزه BCIT08.',
    'Q20': 'في الخطة الجديدة لبكالوريوس الذكاء الاصطناعي، متطلبات التخصص الإجبارية 78 ساعة والاختيارية 15 ساعة.',
    'Q23': 'ماجستير إدارة الأعمال بالعربية 39 ساعة معتمدة موزعة على 24 ساعة إجبارية و6 ساعات اختيارية و9 ساعات للرسالة.',
    'Q24': 'رمز مقرر تحليل الدوائر الكهربائية 1 في الفصل الأول للهندسة الطبية الحيوية هو BME031.',
    'Q25': 'يتضمن الفصل الأول في خطة الهندسة المدنية مقرر جيولوجيا هندسية Engineering Geology ورمزه BCV061.',
    'Q27': 'المتطلب السابق للكيمياء التحليلية في الفصل الثاني من خطة المختبرات الطبية هو الكيمياء العامة والعضوية ورمزها BHS110.',
    'Q30': 'المتطلب السابق لمقرر نظرية الحق في خطة الشريعة والقانون هو نظرية القانون ورمزها BLA0201.',
}


def evaluation_response(text):
    # Citations and the standard contact recommendation are presentation,
    # not academic claims. Preserve the entire raw answer separately.
    text = re.sub(r'\[[\d,،\s]+\]', '', text)
    text = re.sub(r'لمزيد من الاستفسارات[^\n]*', '', text)
    return text.replace('**', '').strip()


class JudgeTrace(BaseCallbackHandler):
    def __init__(self):
        self.outputs = []

    def on_llm_end(self, response, **kwargs):
        for group in response.generations:
            for generation in group:
                self.outputs.append(generation.text)


def cohere_finished(result):
    """Recognize Cohere's COMPLETE, without accepting truncated output."""
    if not result.generations:
        return False
    for group in result.generations:
        if not group:
            return False
        for generation in group:
            info = generation.generation_info or {}
            message = getattr(generation, 'message', None)
            metadata = getattr(message, 'response_metadata', {}) or {}
            reason = info.get('finish_reason') or metadata.get('finish_reason')
            if reason is not None:
                reason = getattr(reason, 'value', reason)
                if str(reason).upper() not in {'COMPLETE', 'STOP', 'END_TURN', 'EOS_TOKEN'}:
                    return False
            if not getattr(generation, 'text', '').strip():
                return False
    return True


def save(report):
    report['updated_at'] = datetime.now(timezone.utc).isoformat()
    complete = [r for r in report['results'] if
                all(r.get('scores', {}).get(k) is not None for k in NAMES)]
    report['completed_questions'] = len(complete)
    report['summary'] = {}
    for name in NAMES:
        values = [r['scores'][name] for r in report['results']
                  if r.get('scores', {}).get(name) is not None]
        report['summary'][name] = {
            'mean': sum(values) / len(values) if values else None,
            'scored_questions': len(values), 'expected_questions': len(SELECTED),
        }
    report['status'] = 'complete' if len(complete) == len(SELECTED) else 'incomplete'
    temp = REPORT.with_suffix('.tmp')
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                               allow_nan=False), encoding='utf-8')
    temp.replace(REPORT)


def fingerprint(questions, model):
    digest = hashlib.sha256(json.dumps(questions, ensure_ascii=False,
                                      sort_keys=True).encode())
    digest.update(f'{model}|ragas={version("ragas")}|evaluation-v3'.encode())
    for filename in ['rag.py', 'retrieval.py', 'study_plans.py',
                     'reviewed_plan_counts.json']:
        path = ROOT / filename
        if path.exists():
            digest.update(filename.encode())
            digest.update(path.read_bytes())
    # Include original sources so a changed plan cannot reuse an old answer.
    for path in sorted((ROOT / 'docs').rglob('*')):
        if path.is_file() and path.suffix.lower() in {'.pdf', '.txt', '.md'}:
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


async def retry(operation, label):
    for attempt in range(4):
        try:
            return await operation()
        except Exception as error:
            status = getattr(error, 'status_code', None)
            if status == 429 and attempt < 3:
                print(f'  حد الطلبات في {label}؛ سأنتظر دقيقة ثم أعيد المحاولة.')
                await asyncio.sleep(60)
                continue
            raise


async def main():
    global SELECTED, REPORT
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true', help='Evaluate five diagnostic questions first.')
    args = parser.parse_args()
    if args.smoke:
        SELECTED = ['Q01', 'Q09', 'Q14', 'Q17', 'Q24']
        REPORT = ROOT / 'ragas_smoke_v3.json'
    load_dotenv(ROOT / '.env')
    key = os.getenv('COHERE_API_KEY')
    if not key:
        raise ValueError('لم أجد COHERE_API_KEY في .env')
    model = os.getenv('COHERE_EVAL_MODEL') or os.getenv('COHERE_CHAT_MODEL') or 'command-a-03-2025'
    data = json.loads(GOLDEN.read_text(encoding='utf-8-sig'))
    indexed = {q['id']: q for q in data['questions']}
    questions = [dict(indexed[qid]) for qid in SELECTED]
    for q in questions:
        q['original_question'] = q['question']
        q['original_reference'] = q['reference_answer']
        if q['id'] in {'Q17', 'Q18', 'Q19'}:
            q['question'] += ' باللغة العربية'
        q['reference_answer'] = REFERENCE_SENTENCES.get(q['id'], q['reference_answer'])
    if any(not q.get('question', '').strip() or
           not q.get('reference_answer', '').strip() for q in questions):
        raise ValueError('يوجد سؤال أو جواب مرجعي فارغ.')
    signature = fingerprint(questions, model)
    if REPORT.exists():
        report = json.loads(REPORT.read_text(encoding='utf-8'))
        if report.get('fingerprint') != signature:
            raise ValueError('تغيرت نسخة المشروع أو الأسئلة أو نموذج التقييم. '
                             'احتفظي بالتقرير السابق باسم آخر ثم أعيدي التشغيل.')
    else:
        report = dict(schema_version='1.0', evaluator='Ragas',
                      ragas_version=version('ragas'), judge_model=model,
                      question_ids=SELECTED, fingerprint=signature, results=[],
                      notes=[
                          'Fixed subset of the existing 30 reference questions; not a held-out test.',
                          'IT questions Q17-Q19 explicitly specify Arabic because the corpus has two language variants; original questions retained.',
                          'Short references expanded into full statements with the question subject; original references retained.',
                          'Raw answers retained; evaluation removes numeric citation markers and the standard contact recommendation only.',
                          'Arabic/numeric prompt instructions added; original metric algorithms and JSON schemas retained.',
                          'Each question starts a new conversation.',
                          'Contexts are the actual texts returned by UniversityRAG.answer; reference quotes are not inserted.',
                          'Factual correctness uses F1; it is not the AnswerCorrectness metric.',
                          'Scores are automated LLM judgments, not proof of perfect accuracy.',
                          'Judge may be the same model as the answering model; record this limitation.',
                          'Missing scores are null; means include only scored items and show coverage.',
                      ])
    save(report)
    if report['status'] == 'complete':
        print('التقييم مكتمل بالفعل. التقرير:', REPORT)
        return

    rag = UniversityRAG()
    judge = LangchainLLMWrapper(ChatCohere(
        cohere_api_key=key, model=model, temperature=0, max_tokens=4096),
        is_finished_parser=cohere_finished)
    config = RunConfig(timeout=240, max_retries=2, max_workers=1)
    metrics = [Faithfulness(llm=judge),
               FactualCorrectness(llm=judge, mode='f1'),
               LLMContextRecall(llm=judge)]
    for metric in metrics:
        for prompt in metric.get_prompts().values():
            prompt.instruction += (
                '\nThe sample is in Arabic. Preserve the language of the input claims. '
                'Preserve each full number: commas within numbers are thousands separators, '
                'not boundaries between claims (592,500 is one number). '
                'Compare Arabic and English equivalents by meaning. '
                'Dates such as 1994/1/12 and 12 January 1994 are equivalent. '
                'Keep a statement together with its subject; do not treat a bare numeric '
                'fragment as a separate factual claim. Do not invent missing facts. '
                'When extracting answer statements, do not add a year, place, article number '
                'or other factual qualifier from the question if it is absent from the answer. '
                'Return the exact JSON schema requested by this prompt.')
        metric.init(config)
    by_id = {r['id']: r for r in report['results']}
    print(f'بدأ تقييم {len(SELECTED)} أسئلة. النتائج تُحفظ بعد كل خطوة.')
    for number, question in enumerate(questions, 1):
        qid = question['id']
        row = by_id.get(qid)
        if row and all(row.get('scores', {}).get(k) is not None for k in NAMES):
            print(f'[{number}/{len(SELECTED)}] {qid}: مكتمل سابقًا.')
            continue
        if row is None:
            row = dict(id=qid, category=question['category'],
                       question=question['question'],
                       original_question=question['original_question'],
                       original_reference=question['original_reference'],
                       reference=question['reference_answer'], scores={}, errors={})
            report['results'].append(row)
            by_id[qid] = row
        print(f'[{number}/{len(SELECTED)}] {question["question"]}')
        if 'response' not in row:
            async def generate():
                rag.reset()
                return await asyncio.to_thread(rag.answer, question['question'])
            try:
                result = await retry(generate, 'توليد الإجابة')
                contexts = [r['text'] for r in result.get('retrieved_chunks', [])
                            if isinstance(r, dict) and r.get('text', '').strip()]
                if not isinstance(result.get('answer'), str) or not result['answer'].strip():
                    raise ValueError('إجابة فارغة')
                row.update(response=result['answer'], retrieved_contexts=contexts,
                           sources=result.get('sources', []),
                           search_question=result.get('search_question'))
                row['errors'].pop('generation', None)
                save(report)
                await asyncio.sleep(6)
            except Exception as error:
                row['errors']['generation'] = type(error).__name__
                save(report)
                print('  تعذر توليد الإجابة:', type(error).__name__)
                continue
        row['evaluation_response'] = evaluation_response(row['response'])
        sample = SingleTurnSample(user_input=row['question'],
                                  response=row['evaluation_response'], reference=row['reference'],
                                  retrieved_contexts=row['retrieved_contexts'])
        for name, metric in zip(NAMES, metrics):
            if row['scores'].get(name) is not None:
                continue
            trace = JudgeTrace()
            try:
                # An empty retrieved set cannot support any reference claim.
                if name == 'context_recall' and not row['retrieved_contexts']:
                    value = 0.0
                elif name == 'faithfulness' and not row['retrieved_contexts']:
                    raise ValueError('لا توجد نصوص لتقييم الاستناد إليها')
                else:
                    async def score():
                        return await metric.single_turn_ascore(sample, callbacks=[trace], timeout=240)
                    value = float(await retry(score, name))
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('درجة غير صالحة')
                row['scores'][name] = value
                row['errors'].pop(name, None)
                print(f'  {name}: {value:.2%}')
            except Exception as error:
                row['scores'][name] = None
                row['errors'][name] = type(error).__name__
                print(f'  {name}: لم يكتمل ({type(error).__name__})')
            row.setdefault('judge_outputs', {})[name] = trace.outputs
            save(report)
            await asyncio.sleep(6)
    print(f'\nالأسئلة المكتملة: {report["completed_questions"]}/{len(SELECTED)}')
    for name, summary in report['summary'].items():
        label = f'{summary["mean"]:.2%}' if summary['mean'] is not None else 'غير محسوب'
        print(f'{name}: {label} (تغطية {summary["scored_questions"]}/{len(SELECTED)})')
    print('حُفظ التقرير في:', REPORT)
    if report['status'] != 'complete':
        print('التقييم غير مكتمل؛ إعادة تشغيل الملف تستكمل الأجزاء الناقصة.')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\nتوقف التشغيل؛ النتائج المحفوظة متاحة للاستكمال.')
    except Exception as error:
        if isinstance(error, (ValueError, FileNotFoundError, KeyError)):
            print('تعذر بدء التقييم:', str(error))
        else:
            print('تعذر إكمال التقييم. نوع الخطأ:', type(error).__name__)
