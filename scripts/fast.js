/* In-page driver for the zhihuishu review-test paper.
 *
 * Everything here is one `evaljs` round trip per phase instead of per question.
 * Four behaviours are load-bearing and each one was learned from a wrong number:
 *
 *  1. Answers commit when you LEAVE a question via 下一题 (`.pre-next .next-topic`).
 *     Jumping with the answer card (`.content-reviewS .custom-tree-answer-normal`)
 *     discards the pending selection, so the paper submits at 16.7%/50%.
 *     -> `swipeAll` walks front to back; `goTo` is for READING only.
 *  2. Clicking an already-selected option toggles it OFF. -> `pick` reads the
 *     checked icon/checkbox and clicks only what is missing.
 *  3. Multi-select needs one click per label with a pause; three clicks in one
 *     batch register one. -> `pick` clicks each missing letter and re-reads.
 *  4. `reviewTopicData` lags `currentQues` after a jump, so `readOne` can pair a
 *     stem with the previous question's number. -> `synced()` compares ids and
 *     `readOne` reports `__LAG__` instead of a plausible wrong pair.
 */
(function () {
  window.__F = {
    v: function () {
      var el = document.querySelector('.reviewTestOrExam');
      return el && el.__vue__ ? el.__vue__ : null;
    },
    sleep: function (ms) {
      return new Promise(function (r) { setTimeout(r, ms + Math.random() * 220); });
    },
    synced: function () {
      var v = this.v();
      if (!v) return false;
      var c = v.$data.currentQues || {};
      var t = v.$data.reviewTopicData || {};
      var tid = t.questionId || t.id;
      if (tid == null || c.questionId == null) return true;
      return String(tid) === String(c.questionId);
    },
    goTo: async function (n) {
      var v = this.v();
      if (!v) return false;
      for (var attempt = 0; attempt < 4; attempt++) {
        if (String((v.$data.currentQues || {}).sort) === String(n) && this.synced()) return true;
        var nodes = document.querySelectorAll('.content-reviewS .custom-tree-answer-normal');
        var hit = null;
        for (var i = 0; i < nodes.length; i++) {
          if ((nodes[i].innerText || '').trim() === String(n)) { hit = nodes[i]; break; }
        }
        if (!hit) return false;
        hit.click();
        var par = hit.closest ? hit.closest('.el-tree-node__content') : null;
        if (par) par.click();
        for (var t = 0; t < 40; t++) {
          await this.sleep(120);
          if (String((v.$data.currentQues || {}).sort) === String(n) && this.synced()) return true;
        }
      }
      return String((v.$data.currentQues || {}).sort) === String(n) && this.synced();
    },
    readOne: function () {
      var v = this.v();
      if (!v) return { err: 'no vue' };
      var d = v.$data, t = d.reviewTopicData || {}, c = d.currentQues || {};
      var tid = t.questionId || t.id;
      if (tid != null && c.questionId != null && String(tid) !== String(c.questionId)) {
        return { sort: c.sort, qtype: c.questionType, typeName: t.questionTypeName,
                 stem: '__LAG__', opts: [], state: c.answerState, lag: true };
      }
      return {
        sort: c.sort,
        qid: c.questionId,
        qtype: c.questionType,
        typeName: t.questionTypeName,
        stem: (t.content || ''),
        opts: (t.optionVos || []).map(function (o) {
          return { sort: o.sort, text: (o.content || '') };
        }),
        state: c.answerState
      };
    },
    readAll: async function (n) {
      var out = [];
      for (var i = 1; i <= n; i++) {
        var ok = await this.goTo(i);
        var q = this.readOne();
        if (!ok || q.stem === '__LAG__') {
          // One retry after resyncing: a lag read is a stale pair, not an answer.
          await this.sleep(500);
          await this.goTo(i);
          q = this.readOne();
        }
        out.push(q);
      }
      return out;
    },
    stateOf: function (n) {
      var v = this.v();
      if (!v) return null;
      var s = (v.$data.sheetData && v.$data.sheetData.partSheetVos) || [];
      for (var i = 0; i < s.length; i++) {
        var qs = s[i].questionSheetVos || [];
        for (var j = 0; j < qs.length; j++) {
          if (String(qs[j].sort) === String(n)) return qs[j].answerState;
        }
      }
      return null;
    },
    // Every question's stored answer, straight from the answer sheet.
    sheet: function () {
      var v = this.v();
      if (!v) return {};
      var s = (v.$data.sheetData && v.$data.sheetData.partSheetVos) || [];
      var o = {};
      s.forEach(function (p) {
        (p.questionSheetVos || []).forEach(function (q) { o[q.sort] = q.answerState; });
      });
      return o;
    },
    pick: function (letters) {
      var q = document.querySelector('.questionContent');
      if (!q) return 'NO_Q';
      var want = (typeof letters === 'string' ? letters.split('') : letters).map(function (x) {
        return String(x).toUpperCase();
      });
      var radios = q.querySelectorAll('ul.radio-view li');
      if (radios.length) {
        var isOn = function (li) {
          var e = li.querySelector('.checkIcon');
          return !!(e && /checkedIcon/.test(e.className));
        };
        var letterOf = function (li) {
          var s = (li.querySelector('.letterSort') || {}).innerText || '';
          return s.replace(/[^A-Za-z]/g, '').toUpperCase();
        };
        for (var i = 0; i < radios.length; i++) {
          if (want.indexOf(letterOf(radios[i])) >= 0 && !isOn(radios[i])) {
            radios[i].click();
            return 'R_' + letterOf(radios[i]);
          }
        }
        for (var k = 0; k < radios.length; k++) {
          if (want.indexOf(letterOf(radios[k])) >= 0 && isOn(radios[k])) {
            return 'R_' + letterOf(radios[k]) + '_KEPT';
          }
        }
        return 'NO_R_OPT';
      }
      return 'C_PENDING';
    },
    // Multi-select: click each missing box separately, re-reading between clicks.
    pickMulti: async function (letters) {
      var q = document.querySelector('.questionContent');
      if (!q) return 'NO_Q';
      var want = (typeof letters === 'string' ? letters.split('') : letters).map(function (x) {
        return String(x).toUpperCase();
      });
      var labs = q.querySelectorAll('.checkbox-views label.el-checkbox');
      if (!labs.length) return 'NO_C_OPT';
      var stateOf = function (lab) {
        var b = lab.querySelector('input[type=checkbox]');
        return b ? b.checked : false;
      };
      var letterOf = function (lab) {
        var s = (lab.querySelector('.letterSort') || {}).innerText || '';
        return s.replace(/[^A-Za-z]/g, '').toUpperCase();
      };
      for (var pass = 0; pass < 3; pass++) {
        var dirty = false;
        for (var i = 0; i < labs.length; i++) {
          var L = letterOf(labs[i]);
          var on = stateOf(labs[i]);
          var need = want.indexOf(L) >= 0;
          if (need !== on) {
            labs[i].click();
            dirty = true;
            await this.sleep(230);
          }
        }
        if (!dirty) break;
      }
      return 'C_DONE';
    },
    selection: function () {
      var q = document.querySelector('.questionContent');
      if (!q) return null;
      var radios = q.querySelectorAll('ul.radio-view li');
      if (radios.length) {
        for (var i = 0; i < radios.length; i++) {
          var e = radios[i].querySelector('.checkIcon');
          if (e && /checkedIcon/.test(e.className)) {
            var s = (radios[i].querySelector('.letterSort') || {}).innerText || '';
            return s.replace(/[^A-Za-z]/g, '').toUpperCase();
          }
        }
        return '';
      }
      var out = '';
      var labs = q.querySelectorAll('.checkbox-views label.el-checkbox');
      for (var j = 0; j < labs.length; j++) {
        var b = labs[j].querySelector('input[type=checkbox]');
        if (b && b.checked) {
          var s2 = (labs[j].querySelector('.letterSort') || {}).innerText || '';
          out += s2.replace(/[^A-Za-z]/g, '').toUpperCase();
        }
      }
      return out;
    },
    nextTopic: function () {
      var b = document.querySelector('.pre-next .next-topic');
      if (!b) return false;
      b.click();
      return true;
    },
    // Sequential walk. plan = {sort: "AC"} for every question on the paper.
    // Returns {sort: "OK_AC/state2"} - the suffix is the *committed* answerState,
    // which is the only proof the answer registered; the old report ended in the
    // click result and every caller's `endswith("->2")` check was therefore dead.
    swipeAll: async function (plan) {
      var rep = {};
      var keys = Object.keys(plan).map(Number).sort(function (a, b) { return a - b; });
      if (!keys.length) return rep;
      await this.goTo(keys[0]);
      for (var i = 0; i < keys.length; i++) {
        var n = keys[i];
        var letters = plan[String(n)] || plan[n];
        var want = (typeof letters === 'string' ? letters.split('') : letters)
          .map(function (x) { return String(x).toUpperCase(); }).sort().join('');
        var isMulti = !!document.querySelector('.questionContent .checkbox-views label.el-checkbox');
        for (var attempt = 0; attempt < 3; attempt++) {
          if (isMulti) { await this.pickMulti(want); }
          else { this.pick(want); }
          await this.sleep(260);
          if ((this.selection() || '') === want) break;
        }
        var got = this.selection() || '';
        if (i < keys.length - 1) {
          if (!this.nextTopic()) { rep[n] = 'NO_NEXT_' + got; continue; }
          await this.sleep(620);
        }
        var st = this.stateOf(n);
        rep[n] = (got === want ? 'OK_' : 'BAD_') + got + '/want=' + want + '/state' + st;
      }
      return rep;
    },
    answerAll: async function (plan) {
      var rep = await this.swipeAll(plan);
      await this.sleep(360);
      return rep;
    }
  };
  return 'FAST_READY';
})()
