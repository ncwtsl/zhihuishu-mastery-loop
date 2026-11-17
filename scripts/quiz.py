"""Reading the review-test page: base info, question data, answer-sheet state.

The Vue instance on `.reviewTestOrExam` is the only reliable source: the DOM
lags it, and `reviewTopicData` lags `currentQues`. Every read here goes through
one place so a mismatch is reported instead of being silently paired with the
wrong question number.
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from cdp import WS, connect, evaljs, page_ws  # noqa: E402

QUIZ_URL = "studentReviewTestOrExam"


def conn(url_filter=QUIZ_URL):
    """(ws, target) for the open quiz tab."""
    url, info = page_ws(config.PORT, url_filter)
    return connect(url), info


BASE_JS = ("JSON.stringify((function(){var el=document.querySelector('.reviewTestOrExam');"
           "if(!el||!el.__vue__)return {nc:1};var d=el.__vue__.$data;var b=d.baseInfor||{};"
           "return {et:b.examTestId,ep:b.examPaperId,qc:b.questionCount,"
           "paper:b.examPaperName||'',kid:b.knowledgeId||null};})())")


def get_base(ws, tries=8, delay=1.5):
    """Poll for baseInfor.

    It is empty until the paper finishes rendering; the old code read it once and
    died with `KeyError: 'qc'` (or worse, opened a paper with a null id and got a
    blank preview). Repeated failure is its own signal: the paper never loaded.
    """
    for _ in range(tries):
        raw = evaljs(ws, BASE_JS, timeout=20)
        try:
            b = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            b = None
        if isinstance(b, dict) and b.get("qc"):
            return b
        config.sleep(delay)
    raise RuntimeError("BASE_EMPTY")


QDATA_JS = """
JSON.stringify((function(){
  var v = document.querySelector('.reviewTestOrExam');
  if(!v || !v.__vue__) return JSON.stringify({err:'no vue'});
  var d = v.__vue__.$data, t = d.reviewTopicData || {}, c = d.currentQues || {};
  var tid = t.questionId || t.id;
  var lag = (tid != null && c.questionId != null && String(tid) !== String(c.questionId));
  return JSON.stringify({
    sort: c.sort, qid: c.questionId, qtype: c.questionType, typeName: t.questionTypeName,
    stem: lag ? '__LAG__' : (t.content||''),
    opts: (t.optionVos||[]).map(function(o){ return {sort:o.sort, id:o.id, text:(o.content||'')}; }),
    state: c.answerState, lag: lag
  });
})())
"""


def read_question(ws):
    raw = evaljs(ws, QDATA_JS, timeout=20)
    try:
        return json.loads(raw) if isinstance(raw, str) else {"err": "no value"}
    except ValueError:
        return {"err": "bad json"}


STATES_JS = """
JSON.stringify((function(){
  var v=document.querySelector('.reviewTestOrExam');
  if(!v||!v.__vue__) return JSON.stringify({err:'no vue'});
  var d=v.__vue__.$data;
  var s=(d.sheetData && d.sheetData.partSheetVos) || [];
  var st={};
  s.forEach(function(p){ (p.questionSheetVos||[]).forEach(function(q){ st[q.sort]=q.answerState; }); });
  return JSON.stringify({st:st, pro:((document.querySelector('.answer-pro .pro')||{}).innerText||'').trim()});
})())
"""


def states(ws):
    """{sort: answerState} plus the answering-progress text.

    `pro` is answering progress, NOT mastery. It is returned only so a caller can
    debug why the two were confused; never record it as mastery.
    """
    raw = evaljs(ws, STATES_JS, timeout=20)
    try:
        return json.loads(raw) if isinstance(raw, str) else {"st": {}, "pro": ""}
    except ValueError:
        return {"st": {}, "pro": ""}


def pending(ws):
    """Sorts whose answerState is not committed (state != 2)."""
    st = states(ws).get("st") or {}
    return [k for k, v in st.items() if str(v) != "2"]
