(function(){
  window.__F = {
    v: function(){ return document.querySelector('.reviewTestOrExam').__vue__; },
    sleep: function(ms){ return new Promise(function(r){ setTimeout(r, ms); }); },
    goTo: async function(n){
      var v = this.v();
      for (var attempt = 0; attempt < 4; attempt++){
        if (String((v.$data.currentQues||{}).sort) === String(n)) return true;
        var nodes = document.querySelectorAll('.content-reviewS .custom-tree-answer-normal');
        var done = false;
        for (var i=0;i<nodes.length;i++){
          if ((nodes[i].innerText||'').trim() === String(n)){
            var idx = i;
            nodes[i].click();
            var par = nodes[i].closest ? nodes[i].closest('.el-tree-node__content') : null;
            if (par) par.click();
            done = true; break;
          }
        }
        if (!done) return false;
        for (var t=0;t<50;t++){
          await this.sleep(120);
          if (String((v.$data.currentQues||{}).sort) === String(n) && this.synced()) return true;
        }
      }
      return String((v.$data.currentQues||{}).sort) === String(n) && this.synced();
    },
    // True when reviewTopicData already belongs to currentQues (guards against the
    // async render lag that used to pair a stem with the previous question's number).
    synced: function(){
      var v = this.v();
      var c = v.$data.currentQues || {};
      var t = v.$data.reviewTopicData || {};
      var tid = t.questionId || t.id;
      if (tid == null || c.questionId == null) return true;
      return String(tid) === String(c.questionId);
    },
    readOne: function(){
      var v = this.v();
      var t = v.$data.reviewTopicData || {};
      var c = v.$data.currentQues || {};
      // reviewTopicData lags behind currentQues after a jump; if the ids disagree
      // the stem belongs to another question, so report the mismatch instead of
      // letting it be paired with the wrong sort number.
      var tid = t.questionId || t.id;
      if (tid != null && c.questionId != null && String(tid) !== String(c.questionId)) {
        return {sort:c.sort, qtype:c.questionType, typeName:t.questionTypeName,
                stem:'__LAG__', opts:[], state:c.answerState, lag:true};
      }
      return {
        sort: c.sort, qtype: c.questionType, typeName: t.questionTypeName,
        stem: (t.content||''),
        opts: (t.optionVos||[]).map(function(o){ return {sort:o.sort, text:(o.content||'')}; }),
        state: c.answerState
      };
    },
    readAll: async function(n){
      var out = [];
      for (var i = 1; i <= n; i++){
        await this.goTo(i);
        out.push(this.readOne());
      }
      return out;
    },
    pick: function(letters){
      var q = document.querySelector('.questionContent');
      if(!q) return 'NO_Q';
      var want = letters.slice();
      var radios = q.querySelectorAll('ul.radio-view li');
      if (radios.length){
        // Clicking an already-selected option DESELECTS it (the widget toggles),
        // so only click when the icon is not checked yet.
        var isOn = function(li){
          var e = li.querySelector('.checkIcon');
          return !!(e && /checkedIcon/.test(e.className));
        };
        for (var i=0;i<radios.length;i++){
          var s0 = (radios[i].querySelector('.letterSort')||{}).innerText||'';
          var L0 = s0.replace(/[^A-Za-z]/g,'').toUpperCase();
          if (want.indexOf(L0) >= 0 && !isOn(radios[i])){ radios[i].click(); return 'R_'+L0; }
        }
        for (var k=0;k<radios.length;k++){
          var sk = (radios[k].querySelector('.letterSort')||{}).innerText||'';
          var Lk = sk.replace(/[^A-Za-z]/g,'').toUpperCase();
          if (want.indexOf(Lk) >= 0 && isOn(radios[k])) return 'R_'+Lk+'_KEPT';
        }
        return 'NO_R_OPT';
      }
      var labs = q.querySelectorAll('.checkbox-views label.el-checkbox');
      var clicked = [];
      for (var j=0;j<labs.length;j++){
        var s2 = (labs[j].querySelector('.letterSort')||{}).innerText||'';
        var L2 = s2.replace(/[^A-Za-z]/g,'').toUpperCase();
        var box = labs[j].querySelector('input[type=checkbox]');
        var isOn = box ? box.checked : false;
        var need = want.indexOf(L2) >= 0;
        if (need !== isOn){ labs[j].click(); clicked.push(L2); }
      }
      return 'C_' + clicked.join('');
    },
    // Current selection for the visible question, as a letter string ("A" / "AC").
    selection: function(){
      var q = document.querySelector('.questionContent');
      if(!q) return null;
      var radios = q.querySelectorAll('ul.radio-view li');
      if (radios.length){
        for (var i=0;i<radios.length;i++){
          var e = radios[i].querySelector('.checkIcon');
          if (e && /checkedIcon/.test(e.className)){
            var s = (radios[i].querySelector('.letterSort')||{}).innerText||'';
            return s.replace(/[^A-Za-z]/g,'').toUpperCase();
          }
        }
        return '';
      }
      var labs = q.querySelectorAll('.checkbox-views label.el-checkbox');
      var out = '';
      for (var j=0;j<labs.length;j++){
        var b = labs[j].querySelector('input[type=checkbox]');
        if (b && b.checked){
          var s2 = (labs[j].querySelector('.letterSort')||{}).innerText||'';
          out += s2.replace(/[^A-Za-z]/g,'').toUpperCase();
        }
      }
      return out;
    },
    // Answers are only committed when you LEAVE a question via 下一题; jumping
    // around with the answer-card tree silently drops the pending selection.
    // So walk the paper front to back and verify after each step.
    nextTopic: function(){
      var b = document.querySelector('.pre-next .next-topic');
      if(!b) return false;
      b.click(); return true;
    },
    // Sequential swipe: goto 1, then pick+next for every question in plan.
    swipeAll: async function(plan){
      var rep = {};
      var keys = Object.keys(plan).sort(function(a,b){ return (+a)-(+b); });
      var first = +keys[0];
      await this.goTo(first);
      for (var i=0;i<keys.length;i++){
        var n = +keys[i];
        var letters = plan[keys[i]];
        if (typeof letters === 'string') letters = letters.split('');
        var want = letters.slice().sort().join('');
        var got = '';
        for (var attempt=0; attempt<3; attempt++){
          this.pick(letters);
          await this.sleep(240);
          got = this.selection() || '';
          if (got === want) break;
        }
        rep[n] = (got===want?'OK_':'BAD_')+got+'/want='+want;
        if (i < keys.length-1){
          var moved = this.nextTopic();
          await this.sleep(700);
          if (!moved) rep[n] += '+NO_NEXT';
        }
      }
      return rep;
    },
    answerAll: async function(plan){
      var rep = await this.swipeAll(plan);
      await this.sleep(400);
      return rep;
    }
  };
  return 'FAST_READY';
})()
