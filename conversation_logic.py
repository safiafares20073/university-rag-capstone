"""Multi-part requests, citation offsets and safe editing of chat branches."""
import re
from copy import deepcopy
def split_requests(question):
    parts=re.split(r'(?:[؟?\n]+\s*|\s+(?:و|وكمان|وأيضًا|وايضا|and)\s*)(?=(?:كم|ما\s|ماهي|ماهو|هل\s|كيف|متى|أين|اين|what\s|how\s|when\s|where\s))',question.strip(),flags=re.I)
    return [p.strip(' ؟?\n') for p in parts if p.strip(' ؟?\n')] or [question]
def merge_results(parts,results):
    answers,sources,chunks=[],[],[]
    offset=0
    for part,result in zip(parts,results):
        answer=result['answer']
        numbers=[s['number'] for s in result.get('sources',[])]
        cited=[int(x) for group in re.findall(r'\[([\d,،\s]+)\]',answer) for x in re.findall(r'\d+',group)]
        maximum=max(numbers+cited+[0])
        answer=re.sub(r'\[([\d,،\s]+)\]',lambda m:'['+', '.join(str(int(x)+offset) for x in re.findall(r'\d+',m.group(1)))+']',answer)
        sources.extend(dict(s,number=s['number']+offset) for s in result.get('sources',[]))
        chunks.extend(result.get('retrieved_chunks',[]))
        answers.append(f'**{part}**\n\n{answer}')
        offset+=maximum
    return dict(answer='\n\n'.join(answers),sources=sources,retrieved_chunks=list({c['id']:c for c in chunks}.values()),search_question=' | '.join(parts))
def trim_for_edit(messages,index):
    if not 0<=index<len(messages) or messages[index]['role']!='user':raise ValueError('يمكن تعديل رسالة المستخدم فقط.')
    return deepcopy(messages[:index])
def restore_history(messages):
    return [{'role':m['role'],'content':m['content']} for m in messages if m['role'] in {'user','assistant'} and not m.get('error')][-12:]
