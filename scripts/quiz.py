"""Helpers for the zhihuishu review-test page."""
import sys, io, json, time
import config
from cdp import WS, page_ws, evaljs

def conn(url_filter="studentReviewTestOrExam"):
    url, info = page_ws(config.PORT, url_filter)
    return WS(url), info

QDATA_JS = """
(function(){
  var v = document.querySelector('.reviewTestOrExam').__vue__;
  if(!v) return JSON.stringify({err:'no vue'});
  var d = v.$data, t = d.reviewTopicData || {}, c = d.currentQues || {};
  var opts = (t.optionVos||[]).map(function(o){ return {sort:o.sort, id:o.id, text:(o.content||'').trim(), isCorrect:o.isCorrect}; });
  return JSON.stringify({
    sort: c.sort, qid: c.questionId, qtype: c.questionType, typeName: t.questionTypeName,
    stem: (t.content||'').trim(),
    opts: opts,
    userAnswer: t.userAnswerVo ? JSON.stringify(t.userAnswerVo).slice(0,300) : null,
    result: t.result, analysis: t.analysisVo ? JSON.stringify(t.analysisVo).slice(0,500) : null,
    answerState: c.answerState
  });
})()
"""

def read_question(ws):
    return json.loads(evaljs(ws, QDATA_JS, timeout=20))

JUMP_JS = """
(function(n){
  var btns = document.querySelectorAll('.reviewS.stu-sheet .sheet-box .el-scrollbar__view *');
  // fallback: find leaf nodes whose text is exactly n
  var target=null;
  document.querySelectorAll('.reviewS [class*=sheet], .reviewS li, .reviewS span, .reviewS div').forEach(function(el){
    if(el.children.length===0 && (el.innerText||'').trim()===String(n)) target=el;
  });
  if(!target) return 'NO_SHEET_ITEM_'+n;
  target.click();
  return 'OK';
})(%d)
"""

def jump(ws, n):
    return evaljs(ws, JUMP_JS % int(n), timeout=20)

NEXT_JS = """
(function(){
  var b = document.querySelector('.pre-next .next-topic');
  if(!b) return 'NO_NEXT';
  b.click(); return 'OK';
})()
"""

def next_q(ws):
    return evaljs(ws, NEXT_JS, timeout=20)

CHOOSE_JS = """
(function(letter){
  var q = document.querySelector('.questionContent');
  if(!q) return 'NO_Q';
  var lis = q.querySelectorAll('ul.radio-view li');
  for(var i=0;i<lis.length;i++){
    var l=(lis[i].querySelector('.letterSort')||{}).innerText||'';
    if(l.replace(/[^A-Za-z]/g,'').toUpperCase()===letter){
      lis[i].click(); return 'CLICKED_'+letter;
    }
  }
  return 'NO_OPTION_'+letter;
})(%s)
"""

def choose(ws, letter):
    return evaljs(ws, CHOOSE_JS % json.dumps(letter), timeout=20)

CLICK_ONE_JS = r"""
(function(letter){
  var q=document.querySelector('.questionContent');
  if(!q) return 'NO_Q';
  var labs=q.querySelectorAll('.checkbox-views label.el-checkbox');
  for(var i=0;i<labs.length;i++){
    var ls=labs[i].querySelector('.letterSort');
    var t=ls?ls.innerText.trim().replace(/[^A-Za-z]/g,'').toUpperCase():'';
    if(t===letter){ labs[i].click(); return 'CLICKED_'+letter; }
  }
  return 'NO_OPTION_'+letter;
})(%s)
"""

MULTI_READ_JS = r"""
JSON.stringify((function(){
  var q=document.querySelector('.questionContent'); var o={};
  if(!q) return o;
  q.querySelectorAll('.checkbox-views label.el-checkbox').forEach(function(l){
    var ls=l.querySelector('.letterSort');
    var t=ls?ls.innerText.trim().replace(/[^A-Za-z]/g,'').toUpperCase():'';
    var b=l.querySelector('input[type=checkbox]');
    o[t]=b?b.checked:false;
  });
  return o;
})())
"""


def multi_state(ws):
    return json.loads(evaljs(ws, MULTI_READ_JS, timeout=20))


def choose_multi(ws, letters, tries=3):
    """Click each wanted checkbox one at a time (batched clicks cancel each other)."""
    want = set(x.upper() for x in letters)
    log = []
    for _ in range(tries):
        cur = multi_state(ws)
        if not isinstance(cur, dict):
            return "MULTI_ERR"
        need = [L for L in sorted(want) if not cur.get(L)]
        drop = [L for L, on in cur.items() if on and L not in want]
        if not need and not drop:
            return "MULTI_OK:" + ",".join(sorted(want))
        for L in need + drop:
            evaljs(ws, CLICK_ONE_JS % json.dumps(L), timeout=20)
            log.append(L)
            time.sleep(1.0)
    cur = multi_state(ws)
    got = sorted([L for L, on in (cur or {}).items() if on])
    return "MULTI_PARTIAL:%s(want %s)" % (",".join(got), ",".join(sorted(want)))


QTYPE_JS = """
(function(){
  var q = document.querySelector('.questionContent');
  if(!q) return JSON.stringify({err:'no q'});
  var num = ((q.querySelector('.letterSortNum')||{}).innerText||'').trim();
  var radios = q.querySelectorAll('ul.radio-view li').length;
  var checks = q.querySelectorAll('.checkbox-views label.el-checkbox').length;
  var inputs = q.querySelectorAll('input[type=text],textarea').length;
  return JSON.stringify({num:num, radios:radios, checks:checks, inputs:inputs});
})()
"""

def qtype(ws):
    return json.loads(evaljs(ws, QTYPE_JS, timeout=20))

STATES_JS = """
JSON.stringify((function(){
  var v=document.querySelector('.reviewTestOrExam').__vue__;
  var s=v.$data.sheetData ? v.$data.sheetData.partSheetVos : [];
  var st={};
  s.forEach(function(p){ (p.questionSheetVos||[]).forEach(function(q){ st[q.sort]=q.answerState; }); });
  return {st:st, pro:(document.querySelector('.answer-pro .pro')||{}).innerText};
})())
"""

def states(ws):
    return json.loads(evaljs(ws, STATES_JS, timeout=20))

def answer_all(ws, answers, tries=3):
    """answers: {sort_number: 'A' or ['A','C']}"""
    report = {}
    for n, ans in sorted(answers.items(), key=lambda kv: int(kv[0])):
        n = str(n)
        for attempt in range(1, tries + 1):
            jump(ws, int(n)); time.sleep(1.0)
            if isinstance(ans, list):
                r = choose_multi(ws, ans)
            else:
                r = choose(ws, ans)
            time.sleep(1.3)
            st = states(ws)["st"].get(str(n))
            report[n] = f"{r}->state{st}"
            if str(st) == "2":
                break
    return report
