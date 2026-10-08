"""Deterministic plan selection and conservative semester-table counting.
No API requests. Ambiguous or damaged tables never produce a final count.
"""
import json
import hashlib
import re
import unicodedata
from pathlib import Path
from pypdf import PdfReader

ORDINALS = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth',
            'seventh', 'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth']
STOP = set('كم عدد مواد ماده مقررات مقرر تخصص برنامج بكالوريوس طالب طالبه دراسه ادرس يجب مطلوب مطلوبه تخرج للتخرج في من علي عليا انا هو هي اجمالي مجموع كل جميع خطه دراسيه لبرنامج للبرنامج علوم علم لعلوم جامعه كليه الجامعه دراسي'.split())


def normal(text):
    text = unicodedata.normalize('NFKC', text).lower()
    text = re.sub(r'[\u064b-\u065f\u0670ـ]', '', text)
    return text.translate(str.maketrans({'أ':'ا','إ':'ا','آ':'ا','ٱ':'ا',
                                       'ى':'ي','ی':'ي','ک':'ك','ة':'ه'}))


def tokens(text):
    answer = []
    for word in re.findall(r'\w+', normal(text)):
        if word.startswith('وال'):
            word = word[1:]
        if word == 'وجراحه':
            word = 'جراحه'
        if word.startswith('لل'):
            word = word[1:]
        if word.startswith('ال'):
            word = word[2:]
        if word.startswith(('لهندس','لتصميم','لذكاء','لاعمال','لنظم','لترجم')):
            word = word[1:]
        word = {'تقني': 'تقنيه', 'تثنيه': 'تقنيه', 'سيبراني': 'سيبراني',
                'سبيراني': 'سيبراني', 'سبراني': 'سيبراني'}.get(word, word)
        answer.append(word)
    return answer


# Apply the same normalization to stop words and questions.
STOP = {word for item in STOP for word in tokens(item)}
STOP.update({'ما', 'عن', 'هل', 'التي', 'الذي', 'دراستها', 'دراسته', 'لدي', 'عندي',
             'متطلب', 'متطلبات', 'سابق', 'سابقه', 'ساعات', 'معتمده', 'مده',
             'سنوات', 'مستويات', 'لتسجيل', 'لتخصص', 'بالتخصص'})


def count_question(text):
    words = set(tokens(text))
    return bool(words & {'كم','عدد','اجمالي','مجموع'}) and bool(
        words & {'مواد','ماده','مقررات','مقرر'})


def query_words(text):
    text = ' '.join(tokens(text))
    text = text.replace('تثنيه معلومات', 'تقنيه معلومات')
    for a, b in [('طب بشري','طب جراحه'), ('طب البشري','طب جراحه'),
                 ('تقنيه معلومات','تقنيه معلومات'),
                 ('هندسه طبيه','هندسه طبيه حيويه'),
                 ('هندسه الطبيه','هندسه طبيه حيويه'),
                 ('طب اسنان','طب جراحه فم اسنان'),
                 ('جرافكس','تصميم جرافيكي'), ('حاسبات','حوسبه')]:
        text = text.replace(a, b)
    words = set(tokens(text)) - STOP
    words -= {'عربي','عربيه','انجليزي','انجليزيه','بالانجليزي','بالعربي',
              'لغه','باللغه','بلغه','بالعربيه','بالانجليزيه','عربيي','العربيي',
              'قديمه','جديده','حسب','وفق','خطتي','حاليه'}
    return words


class StudyPlanService:
    def __init__(self, retriever, docs_dir):
        self.docs_dir = Path(docs_dir).resolve()
        self.plans = {}
        profile_path = Path(__file__).resolve().parent / 'reviewed_plan_counts.json'
        self.reviewed = {}
        if profile_path.is_file():
            profile_data = json.loads(profile_path.read_text(encoding='utf-8'))
            self.reviewed = {p['relative_path']: p for p in profile_data['plans']}
        for record in retriever.records.values():
            meta = record['metadata']
            path = str(meta.get('relative_path', '')).replace('\\', '/')
            name = meta.get('source_file') or Path(path).name
            t = normal(name)
            if path and path.lower().endswith('.pdf') and (
                    'خطه' in t or 'study plan' in t or 'ماجستير' in t or 'ماجستيير' in t):
                label = Path(name).stem.split(' - ')[0]
                label = re.sub(r'^الخطة الدراسية\s*', '', label)
                label = re.sub(r'^لبرنامج\s*', '', label)
                if label.startswith('لبكالوريوس'):
                    label = label[1:]
                if label.startswith('لل'):
                    label = label[1:] if label[2:].startswith('ال') else 'ال' + label[2:]
                elif label.startswith(('لهندسة','لتصميم','لعلوم','لذكاء','للاعمال','لنظم')):
                    label = label[1:]
                english = any(w in t for w in ['انجليزي','english'])
                masters = any(w in t for w in ['ماجستير','ماجستيير','master'])
                words = set(tokens(label)) - STOP
                if 'computing' in t:
                    words.update(['حوسبه','حاسوب'])
                self.plans[path] = dict(relative_path=path, source_file=name,
                                       label=label, words=words,
                                       english=english, masters=masters)

    def select(self, question):
        q = query_words(question)
        normalized = normal(question)
        masters = any(w in normalized for w in ['ماجستير','ماجستيير','master'])
        lang = None
        if 'انجليزي' in normalized or 'english' in normalized or re.search(r'\bbit\b', normalized):
            lang = True
        elif 'عربي' in normalized:
            lang = False
        q -= {'ماجستير','ماجستيير','master','bit','it'}
        if re.search(r'\b(?:it|bit)\b', normalized):
            q.update(['تقنيه','معلومات'])
        if not q:
            return None, 'ما اسم التخصص والدرجة العلمية المقصودان؟'
        candidates = []
        for p in self.plans.values():
            if p['masters'] != masters:
                continue
            # Every meaningful query word must match the program title.
            if q.issubset(p['words']):
                candidates.append(p)
        if not candidates:
            # A question contains course names and semester words in addition
            # to the program. Match the complete program name within it.
            generic = {'هندسه', 'طب', 'علوم', 'اداره', 'تقنيه', 'لغه', 'حوسبه'}
            for p in self.plans.values():
                if p['masters'] != masters:
                    continue
                anchors = query_words(p['label']) - {'ماجستير', 'ماجستيير', 'master', 'it', 'bit'}
                if anchors and anchors <= q and anchors - generic:
                    candidates.append(p)
            if candidates:
                specificity = max(len(query_words(p['label'])) for p in candidates)
                candidates = [p for p in candidates
                              if len(query_words(p['label'])) == specificity]
        if lang is not None and candidates and all({'تقنيه','معلومات'}.issubset(p['words']) for p in candidates):
            candidates = [p for p in candidates if p['english'] == lang]
        if len(candidates) == 1:
            return candidates[0], ''
        if len(candidates) > 1:
            labels = list(dict.fromkeys(p['label'] for p in candidates))
            if all('تقنية المعلومات' in p['label'] for p in candidates):
                return None, 'تقصدين تقنية المعلومات بالعربي أم بالإنجليزي؟'
            return None, 'أي برنامج تقصدين: ' + '، أم '.join(labels) + '؟'
        return None, ('لم أستطع مطابقة اسم البرنامج بدقة. اكتبي اسمه الرسمي '
                      'ولغة الدراسة إن كان له أكثر من خيار؛ لا تحتاجين اسم الملف.')

    def answer_programs(self, question):
        words = set(tokens(question))
        if not ('تخصصات' in words or ('برامج' in words and words & {'ما', 'ايش', 'اذكر', 'قائمه'})):
            return None
        if words & {'رسوم', 'قبول', 'شروط', 'مواد', 'مقررات', 'عدد'}:
            return None
        masters = bool(words & {'ماجستير', 'ماجستيير', 'master'})
        selected = sorted((p for p in self.plans.values() if p['masters'] == masters), key=lambda p: p['relative_path'])
        if not selected:
            return None
        groups, sources = {}, []
        for number, plan in enumerate(selected, 1):
            college = plan['relative_path'].split('/')[0]
            groups.setdefault(college, []).append(f"- {plan['label']} [{number}]")
            sources.append(dict(number=number, source_file=plan['source_file'], page_number=1,
                                chunk_id=f"plan-catalog:{plan['relative_path']}:1"))
        level = 'الماجستير' if masters else 'البكالوريوس'
        answer = f'هذه برامج {level} التي توجد لها خطط دراسية ضمن المصادر المتاحة:\n\n'
        answer += '\n\n'.join(college + ':\n' + '\n'.join(items) for college, items in groups.items())
        answer += '\n\nوجود خطة في المصادر لا يؤكد أن القبول في البرنامج مفتوح حاليًا.'
        return dict(answer=answer, sources=sources, retrieved_chunks=[], search_question=question)

    def read_pages(self, plan):
        path = (self.docs_dir / plan['relative_path']).resolve()
        if not path.is_relative_to(self.docs_dir) or not path.is_file():
            raise FileNotFoundError('ملف الخطة الأصلي غير موجود داخل docs: ' + plan['relative_path'])
        return [unicodedata.normalize('NFKC', p.extract_text() or '')
                for p in PdfReader(str(path)).pages]

    def records_for_plan(self, question):
        # In course questions the requested program normally follows "في".
        parts = re.split(r"\bفي\b", question)
        candidate_question = parts[-1].strip() if len(parts) > 1 else question
        candidate_question = re.sub(r"^(?:تخصص|برنامج)\s+", "", candidate_question)
        plan, clarification = self.select(candidate_question)
        if plan is None and len(parts) > 1:
            # "مقدمة في الكيمياء الحيوية" contains في inside a course name;
            # a complete-question fallback still finds the program title.
            plan, clarification = self.select(question)
        if plan is None:
            return [], clarification
        pages = self.read_pages(plan)
        if sum(len(page) for page in pages) > 60000:
            return [], 'الخطة أطول من حد القراءة الحالي؛ يلزم استخراج الجزء المطلوب منها قبل الإجابة.'
        records = [dict(id=f"full-plan:{plan['relative_path']}:{i}", text=text,
                        metadata=dict(source_file=plan['source_file'],
                                      relative_path=plan['relative_path'], page_number=i))
                   for i, text in enumerate(pages, 1) if text.strip()]
        if not records:
            return [], 'وجدت الخطة، لكن لم أستطع استخراج نصها للإجابة.'
        requested = self.requested_semesters(question)
        if requested:
            inspected = self.inspect(plan)
            selected = []
            for semester in requested:
                rows = inspected['tables'].get(semester, [])
                if not rows:
                    return [], f'لم أتمكن من قراءة جدول الفصل {semester} من هذه الخطة؛ للتأكد من مقرراته تواصل مع القسم.'
                grouped = {}
                for row in rows:
                    page = row['page_number']
                    lines = pages[page - 1].splitlines()
                    start = next((i for i, line in enumerate(lines)
                                  if line.strip() == row['row']), None)
                    if start is None:
                        return [], 'تعذر استخراج جدول الفصل المطلوب بشكل موثوق؛ للتأكد من مقرراته تواصل مع القسم.'
                    excerpt = [lines[start]]
                    for line in lines[start + 1:]:
                        if (re.match(r'^\s*\d{1,2}\s*\.?\s*(?:[A-Z]|\d{6})', line)
                            or re.search(r'total|semester|year|المجموع|الفصل', line, re.I)):
                            break
                        excerpt.append(line)
                    grouped.setdefault(page, []).append('\n'.join(excerpt).strip())
                for page, fragments in grouped.items():
                    selected.append(dict(
                        id=f"plan-semester:{plan['relative_path']}:{semester}:{page}",
                        text=f'صفوف جدول الفصل {semester} من الخطة:\n' + '\n'.join(fragments),
                        metadata=dict(source_file=plan['source_file'],
                                      relative_path=plan['relative_path'], page_number=page)))
            return selected, ''
        return records, ''

    @staticmethod
    def requested_semesters(question):
        q = normal(question)
        ordinals = {'اول': 1, 'اولي': 1, 'ثاني': 2, 'ثانيه': 2,
                    'ثالث': 3, 'ثالثه': 3, 'رابع': 4, 'رابعه': 4,
                    'خامس': 5, 'خامسه': 5, 'سادس': 6, 'سادسه': 6,
                    'سابع': 7, 'سابعه': 7, 'ثامن': 8, 'ثامنه': 8,
                    'تاسع': 9, 'تاسعه': 9, 'عاشر': 10, 'عاشره': 10}
        alternatives = '|'.join(sorted(ordinals, key=len, reverse=True))
        def values(noun):
            matches = re.findall(r'\b(?:ال)?' + noun + r'\s+(?:ال)?(' + alternatives + r'|\d{1,2})\b', q)
            return [int(v) if v.isdigit() else ordinals[v] for v in matches]
        years = values('سنه') or values('عام')
        semesters = values('فصل')
        if years and not semesters:
            return [2 * years[0] - 1, 2 * years[0]]
        if years and semesters and all(v <= 2 for v in semesters):
            return [2 * (years[0] - 1) + v for v in semesters]
        return list(dict.fromkeys(semesters))

    def inspect(self, plan):
        pages = self.read_pages(plan)
        tables = {}
        current = None
        issues = []
        diagnostics = []
        warnings = []
        year = 0
        # Original row numbers, not credit-hour totals, determine the count.
        page_lines = [(page_no, line) for page_no, page in enumerate(pages, 1)
                      for line in page.splitlines()]
        lines = [line for _, line in page_lines]
        for index, (page_no, raw) in enumerate(page_lines):
            compact = re.sub(r'\s+', '', raw).lower()
            year_heading = re.search(r'(?<![a-z])(' + '|'.join(ORDINALS) + r')year', compact)
            if year_heading and len(raw.strip()) < 100:
                year = ORDINALS.index(year_heading.group(1)) + 1
            heading = re.search(r'(?<![a-z])(' + '|'.join(ORDINALS) + r'|summer)semester', compact)
            ahead = '\n'.join(lines[index+1:index+25]).lower()
            is_table = bool(re.search(r'code|الكود|رمز', ahead)) and bool(re.search(r'course|المقرر', ahead))
            arabic_semester = None
            ar_ordinals = ['الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس', 'السابع', 'الثامن', 'التاسع', 'العاشر']
            normalized_heading = re.sub(r'\s+', '', normal(raw))
            if len(raw.strip()) < 100 and not re.search(r'\d', raw):
                for ar_index, ar_word in enumerate(ar_ordinals, 1):
                    ar_word = normal(ar_word)
                    if 'الفصل' + ar_word in normalized_heading or ar_word + 'الفصل' in normalized_heading:
                        arabic_semester = ar_index
                        break
            is_thesis = plan['masters'] and normalized_heading in {'الرسالهالعلميه', 'العلميهالرساله', 'thesis'}
            if 'summary' in compact or 'ملخص' in normalized_heading:
                heading = None
                arabic_semester = None
            if (heading or arabic_semester or is_thesis) and is_table and not re.search(r"\d", raw):
                semester = 900 if is_thesis else (arabic_semester or (100 if heading.group(1) == 'summer' else ORDINALS.index(heading.group(1)) + 1))
                if year and semester in {1, 2}:
                    semester = 2 * (year - 1) + semester
                if semester in tables and tables[semester]:
                    issues.append(f'تعرفت على أكثر من جدول للفصل {semester}؛ يلزم تحديد السنة أو إصدار الخطة ومراجعة الاستخراج.')
                tables.setdefault(semester, [])
                current = semester
                continue
            # Alternatives are not additional courses required of every student.
            if re.search(r'(elective|optional)\s+(program\s+)?requirements', raw, re.I) or (
                    not re.match(r'^\s*\d', raw) and ('متطلبات' in normal(raw) or 'مقررات' in normal(raw)) and 'اختيار' in normal(raw) and not heading):
                current = None
            if current is None:
                continue
            # Works with glued codes such as 1BUST03Arabic and spaced codes.
            row = re.match(r'^\s*\.?(\d{1,2})\.?\s*\**\s*((?:[A-Z]\s*(?:[A-Z]\s*){0,7}(?:\d(?:\s*\d){0,6}|[xX](?:\s*[xX]){0,2}))|(?:[A-Z]{2,7}(?=Elective)))', raw)
            expected = len(tables[current]) + 1
            if row is None:
                numeric_row = re.match(r'^\s*' + str(expected) + r'(\d{6,7})(?=[A-Za-z])', raw)
                if numeric_row:
                    tables[current].append(dict(number=expected, code=numeric_row.group(1), row=raw.strip(), page_number=page_no))
                    continue
            if row:
                ordinal = int(row.group(1))
                code = re.sub(r'\s+', '', row.group(2))
                # Numeric values must not be interpreted as credits or totals.
                tables[current].append(dict(number=ordinal, code=code,
                                            row=raw.strip(), page_number=page_no))
            elif re.match(r'^\s*\d{1,2}', raw) and re.search(r'elective|اخت[يی]ار', raw, re.I):
                ordinal = int(re.match(r'^\s*(\d{1,2})', raw).group(1))
                tables[current].append(dict(number=ordinal, code=f'ELECTIVE-{current}-{ordinal}', row=raw.strip(), page_number=page_no))
            elif re.match(r'^\s*' + str(expected) + r'\s*[–—-]+\s*$', raw):
                # Count a documented position without inventing its missing course name.
                tables[current].append(dict(number=expected, code=None, row=raw.strip(), page_number=page_no))
                warnings.append(f'يوجد صف بلا اسم أو رمز مقرر واضح في الصفحة {page_no}.')
            elif re.match(r'^\s*' + str(expected) + r'\s*\**\s*[A-Za-z]', raw):
                tables[current].append(dict(number=expected, code=None, row=raw.strip(), page_number=page_no))
                if 'specialization' not in raw.lower():
                    warnings.append(f'يوجد مقرر بلا رمز واضح في الصفحة {page_no}.')
            elif re.match(r'^\s*\d{1,2}\s*\**\s*[A-Z]', raw):
                issues.append(f'صف مقرر لم يستخرج كاملًا في الصفحة {page_no}.')
                diagnostics.append({'page_number': page_no, 'line': raw.strip()})
        if not tables:
            issues.append('لم أتعرف على جداول فصول كاملة قابلة للعد؛ هذه الخطة تحتاج استخراجًا مناسبًا لنمط جدولها.')
        numbers = sorted(s for s in tables if s not in {100, 900})
        if numbers and numbers != list(range(1, max(numbers)+1)):
            issues.append('لم أتمكن من استخراج جميع جداول الفصول والتحقق من تسلسلها.')
        if numbers and not plan['masters'] and max(numbers) not in {8,9,10,12}:
            issues.append('لم أتحقق من اكتمال عدد الفصول في هذه الخطة.')
        for semester, rows in tables.items():
            found = [r['number'] for r in rows]
            if not found or found != list(range(1, len(rows)+1)):
                issues.append(f'تسلسل الصفوف المستخرجة للفصل {semester} ناقص أو مكرر؛ يلزم مراجعة الجدول الأصلي.')
        # Repeated non-elective codes across semester tables need review.
        seen = {}
        for semester, rows in tables.items():
            for row in rows:
                if re.search(r'elective|اختيار', row['row'], re.I):
                    continue
                if row['code'] is None:
                    continue
                if row['code'] in seen:
                    warnings.append(f"تكرر رمز {row['code']}؛ يلزم التحقق من تكرار المقرر أو خطأ الرمز في الوثيقة.")
                seen[row['code']] = semester
        # Empty course pages cannot silently be treated as complete.
        if any(not p.strip() for p in pages):
            issues.append('توجد صفحة بلا نص مستخرج؛ يلزم التأكد أنها ليست جدول مقررات مصورًا.')
        return dict(status='needs_review' if issues else 'parsed', warnings=list(dict.fromkeys(warnings)),
                    issues=list(dict.fromkeys(issues)), diagnostics=diagnostics, tables=tables,
                    relative_path=plan['relative_path'], source_file=plan['source_file'],
                    total=sum(len(rows) for rows in tables.values()) if not issues else None)

    def reviewed_count(self, plan, question):
        profile = self.reviewed.get(plan['relative_path'])
        if profile is None:
            return None
        path = (self.docs_dir / plan['relative_path']).resolve()
        if not path.is_relative_to(self.docs_dir) or not path.is_file():
            return None
        if hashlib.sha256(path.read_bytes()).hexdigest() != profile['sha256']:
            return None
        required = profile['required_courses']
        elective = profile['elective_courses_to_take']
        taught = required + elective
        thesis = profile['thesis_items']
        answer = f"بحسب الخطة المرفقة لبرنامج {plan['label']}، تدرس {taught} مقررًا: {required} إجباريًا و{elective} اختياريًا تختارها من البدائل المعتمدة."
        if thesis:
            answer += ' إضافةً إلى رسالة الماجستير، التي عُرضت منفصلة عن المقررات الدراسية في هذا العدد.'
        sources = [dict(number=i, source_file=plan['source_file'], page_number=page,
                        chunk_id=f"reviewed-plan:{plan['relative_path']}:{page}")
                   for i, page in enumerate(profile['source_pages'], 1)]
        answer += ' [' + ', '.join(str(s['number']) for s in sources) + ']'
        return dict(answer=answer, sources=sources, retrieved_chunks=[], search_question=question)

    def answer_count(self, question):
        plan, clarification = self.select(question)
        if plan is None:
            return dict(answer=clarification, sources=[], retrieved_chunks=[], search_question=question)
        if 'قديم' in normal(question):
            return dict(answer='عدد الخطة القديمة يحتاج قراءة ملخصها منفصلًا؛ لن أستخدم جداول الخطة الأخرى لإعطاء عدد.', sources=[], retrieved_chunks=[], search_question=question)
        reviewed = self.reviewed_count(plan, question)
        if reviewed is not None:
            return reviewed
        result = self.inspect(plan)
        page_numbers = sorted({row['page_number'] for rows in result['tables'].values() for row in rows})
        if not page_numbers:
            page_numbers = [1]
        sources = [dict(number=i, source_file=plan['source_file'], page_number=page,
                        chunk_id=f"plan-count:{plan['relative_path']}:{page}")
                   for i, page in enumerate(page_numbers, 1)]
        refs = ', '.join(str(s['number']) for s in sources)
        if {'تقنيه', 'معلومات'}.issubset(plan['words']) and not plan['masters']:
            pages = self.read_pages(plan)
            source_text = ''.join(pages)
            if all(marker in source_text for marker in ['University Requirements (19', 'Faculty Requirements (26', 'Compulsory Program Requirements (75', 'Optional Program Requirements (18']) and result.get('total') == 51:
                answer = ('بحسب جدول متطلبات خطة تقنية المعلومات، العدد **50 مقررًا**: '
                          '9 متطلبات جامعة، و10 متطلبات كلية، و25 مقرر تخصص إجباريًا، '
                          'و6 مقررات اختيارية تختارها من 15 مقررًا متاحًا. [1, 2]\n\n'
                          'يوجد اختلاف بين هذا الجدول وتوزيع الفصول في الوثيقة؛ '
                          'لتأكيد العدد في الخطة المعتمدة لك، تواصل مع القسم. [3]')
                conflict_sources = [dict(number=i, source_file=plan['source_file'], page_number=page, chunk_id=f"plan-conflict:{plan['relative_path']}:{page}") for i, page in enumerate([3,4,6],1)]
                return dict(answer=answer, sources=conflict_sources, retrieved_chunks=[], search_question=question)
        if result['status'] != 'parsed':
            answer = ('وجدت خطة ' + plan['label'] + '، لكن لا أستطيع إعطاء عدد موثوق للمقررات منها الآن. '
                      + ' '.join(result['issues'][:3]) + f' [{refs}]')
        else:
            counts = [('الرسالة' if s == 900 else 'الفصل الصيفي' if s == 100 else f'الفصل {s}') + ': ' + str(len(result['tables'][s])) for s in sorted(result['tables'])]
            electives = sum(bool(re.search(r'elective|اختيار', row['row'], re.I))
                            for rows in result['tables'].values() for row in rows)
            thesis_items = len(result['tables'].get(900, []))
            taught_positions = result['total'] - thesis_items
            answer = (f"يسرد توزيع الفصول في خطة {plan['label']} {taught_positions} موضعًا للمقررات، "
                      f"ويشمل {electives} مواضع اختيارية. لا يشمل هذا العدد قائمة البدائل الاختيارية الإضافية. [{refs}]\n\n"
                      'التوزيع: ' + '، '.join(counts)
                      + '.')
            if thesis_items:
                answer += '\nوتوجد رسالة علمية منفصلة عن هذا العدد.'
            if result.get('warnings'):
                answer += '\n\nتنبيه بشأن الخطة: ' + ' '.join(result['warnings'][:3]) + '\nالعدد أعلاه لصفوف توزيع الفصول؛ لا يحسم التناقضات في أسماء المقررات أو رموزها.'
        return dict(answer=answer, sources=sources, retrieved_chunks=[], search_question=question)

    def audit(self):
        results = []
        for plan in sorted(self.plans.values(), key=lambda x: x['relative_path']):
            try:
                results.append(self.inspect(plan))
            except Exception as error:
                results.append(dict(relative_path=plan['relative_path'], status='error', issues=[str(error)], total=None))
        return results


if __name__ == '__main__':
    from types import SimpleNamespace
    root = Path(__file__).resolve().parent
    docs = root / 'docs'
    if not docs.is_dir():
        raise FileNotFoundError('لم أجد مجلد docs بجانب هذا الملف.')
    records = {str(i): dict(metadata=dict(relative_path=str(path.relative_to(docs)), source_file=path.name))
               for i, path in enumerate(docs.rglob('*.pdf'))}
    service = StudyPlanService(SimpleNamespace(records=records), docs)
    results = service.audit()
    target = root / 'study_plan_audit.json'
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'تم فحص {len(results)} خطة. التقرير: {target}')
    for result in results:
        print(result['status'], result['total'], result['relative_path'])
