/* Niezapominajka 1.0 – skrypty interfejsu (bez zewnętrznych bibliotek)
   Copyright (C) 2026 Maksymilian Staszewski – licencja AGPL-3.0-or-later. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const csrf = document.body.dataset.csrf || "";

  /* ---------- Menu boczne na telefonie ---------- */
  const sidebar = $("#sidebar"), scrim = $("#scrim");
  function drawer(open) {
    if (!sidebar) return;
    sidebar.classList.toggle("open", open);
    scrim && scrim.classList.toggle("open", open);
  }
  $$("[data-drawer]").forEach(b => b.addEventListener("click", () => drawer(!sidebar.classList.contains("open"))));
  scrim && scrim.addEventListener("click", () => drawer(false));
  document.addEventListener("keydown", e => { if (e.key === "Escape") drawer(false); });

  /* ---------- Przyciski: drukuj / cofnij / odśwież (bez skryptów wbudowanych w HTML – CSP) ---------- */
  $$("[data-action]").forEach(b => b.addEventListener("click", () => {
    const a = b.dataset.action;
    if (a === "print") window.print();
    else if (a === "back") history.back();
    else if (a === "reload") location.reload();
  }));

  /* ---------- Ostrzeżenia, które można ukryć na tym urządzeniu ---------- */
  $$("[data-dismiss-key]").forEach(box => {
    const key = "nz-hide-" + box.dataset.dismissKey;
    try { if (localStorage.getItem(key) === "1") { box.hidden = true; return; } } catch (e) {}
    const btn = box.querySelector("[data-dismiss]");
    btn && btn.addEventListener("click", () => {
      box.hidden = true;
      try { localStorage.setItem(key, "1"); } catch (e) {}
    });
  });

  /* ---------- Potwierdzenia ---------- */
  const cdlg = $("#confirm-dialog");
  $$("form[data-confirm]").forEach(form => {
    form.addEventListener("submit", e => {
      if (form.dataset.confirmed === "1") return;
      e.preventDefault();
      if (!cdlg || !cdlg.showModal) {
        if (window.confirm(form.dataset.confirm)) { form.dataset.confirmed = "1"; HTMLFormElement.prototype.submit.call(form); }
        return;
      }
      $("#confirm-title").textContent = form.dataset.confirmTitle || "Potwierdź";
      $("#confirm-text").textContent = form.dataset.confirm;
      const ok = $("#confirm-ok");
      const label = form.dataset.confirmOk || "Usuń";
      ok.querySelector("span").textContent = label;
      ok.className = "btn " + (label === "Usuń" ? "btn-danger-solid" : "btn-primary");
      ok.querySelector("svg").style.display = label === "Usuń" ? "" : "none";
      cdlg.returnValue = "";
      cdlg.onclose = () => {
        if (cdlg.returnValue === "ok") { form.dataset.confirmed = "1"; HTMLFormElement.prototype.submit.call(form); }
      };
      cdlg.showModal();
    });
  });

  /* ---------- Hasła ---------- */
  $$("[data-toggle-pw]").forEach(btn => btn.addEventListener("click", () => {
    const inp = document.getElementById(btn.dataset.togglePw);
    if (!inp) return;
    inp.type = inp.type === "password" ? "text" : "password";
    btn.setAttribute("aria-label", inp.type === "password" ? "Pokaż hasło" : "Ukryj hasło");
  }));
  $$("input[data-strength]").forEach(inp => {
    const bar = document.getElementById(inp.dataset.strength);
    const rules = document.getElementById(inp.dataset.strength + "-rules");
    const userEl = inp.dataset.username ? document.getElementById(inp.dataset.username) : null;
    function check() {
      const v = inp.value, login = userEl ? (userEl.value || "").toLowerCase() : "";
      const res = {
        len: v.length >= 12,
        lower: /[a-ząćęłńóśźż]/.test(v),
        upper: /[A-ZĄĆĘŁŃÓŚŹŻ]/.test(v),
        digit: /\d/.test(v),
        special: /[^\p{L}\p{N}\s]|_/u.test(v),
        variety: new Set(v).size >= 6 && !(login && v.toLowerCase().includes(login)),
      };
      let score = Object.values(res).filter(Boolean).length;
      if (v.length >= 16 && score === 6) score = 7;
      if (rules) $$("li", rules).forEach(li => li.classList.toggle("ok", !!res[li.dataset.rule]));
      if (bar) {
        bar.style.width = (v ? Math.max(8, score / 7 * 100) : 0) + "%";
        bar.style.background = score >= 7 ? "var(--ok)" : score === 6 ? "#6E9B5A" : score >= 4 ? "var(--soon)" : "var(--overdue)";
      }
    }
    inp.addEventListener("input", check);
    userEl && userEl.addEventListener("input", check);
    check();
  });

  /* ---------- Kopiowanie ---------- */
  $$("[data-copy]").forEach(btn => btn.addEventListener("click", async () => {
    const el = document.getElementById(btn.dataset.copy);
    if (!el) return;
    const text = el.textContent.trim();
    try { await navigator.clipboard.writeText(text); }
    catch (e) {
      const r = document.createRange(); r.selectNodeContents(el);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r); document.execCommand("copy");
    }
    const span = btn.lastChild, old = span.textContent;
    span.textContent = "Skopiowano";
    setTimeout(() => (span.textContent = old), 1600);
  }));

  /* ---------- Formularz terminu ---------- */
  const recurring = $("[data-recurring]"), recurFields = $("#recur-fields");
  function syncRecur() { if (recurFields) recurFields.hidden = !recurring.checked; }
  recurring && recurring.addEventListener("change", syncRecur);

  const cat = $("[data-category-select]"), catNew = $("#category_new"), newHint = $("[data-new-hint]");
  cat && cat.addEventListener("change", () => {
    const opt = cat.selectedOptions[0];
    const isNew = cat.value === "__new__";
    if (catNew) { catNew.hidden = !isNew; catNew.required = isNew; if (isNew) catNew.focus(); }
    if (newHint) newHint.hidden = !isNew;
    if (opt && opt.dataset.iv && recurring) {
      recurring.checked = true;
      $("#interval_value").value = opt.dataset.iv;
      $("#interval_unit").value = opt.dataset.iu || "months";
      syncRecur();
    }
  });

  const objSel = $("[data-object-select]"), respSel = $("#responsible_employee_id");
  if (objSel && respSel) {
    let auto = respSel.value === "" || respSel.value === (objSel.selectedOptions[0] || {}).dataset?.resp;
    respSel.addEventListener("change", () => { auto = false; });
    objSel.addEventListener("change", () => {
      const r = (objSel.selectedOptions[0] || {}).dataset?.resp || "";
      if (auto || respSel.value === "") { respSel.value = r; auto = true; }
    });
  }

  /* ---------- Oznaczanie wykonania ---------- */
  function addInterval(d, n, unit) {
    const r = new Date(d.getTime());
    if (unit === "days") { r.setDate(r.getDate() + n); return r; }
    const months = unit === "years" ? n * 12 : n;
    const day = r.getDate();
    r.setDate(1); r.setMonth(r.getMonth() + months);
    const last = new Date(r.getFullYear(), r.getMonth() + 1, 0).getDate();
    r.setDate(Math.min(day, last));
    return r;
  }
  const iso = d => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const doneForm = $("[data-done-form]");
  if (doneForm) {
    const plan = $("[data-plan-next]"), nextBox = $("#next-fields"), next = $("#next_date"), doneDate = $("#done_date");
    plan.addEventListener("change", () => { nextBox.hidden = !plan.checked; next.required = plan.checked; });
    next.required = plan.checked;
    const iv = parseInt(doneForm.dataset.iv, 10), iu = doneForm.dataset.iu;
    let touched = false;
    next.addEventListener("input", () => { touched = true; });
    doneDate.addEventListener("change", () => {
      if (!iv || doneForm.dataset.base !== "done" || touched || !doneDate.value) return;
      const p = doneDate.value.split("-").map(Number);
      next.value = iso(addInterval(new Date(p[0], p[1] - 1, p[2]), iv, iu));
    });
  }

  /* ---------- Konto użytkownika: uprawnienia ---------- */
  const roleSel = $("[data-role-select]"), permBox = $("#perm-box");
  roleSel && permBox && roleSel.addEventListener("change", () => { permBox.hidden = roleSel.value === "owner"; });
  $$("[data-perm-row]").forEach(row => {
    const boxes = $$("[data-perm]", row), all = $("[data-perm-all]", row);
    const view = boxes.find(b => b.dataset.perm === "view");
    const sync = () => { all.checked = boxes.every(b => b.checked); };
    boxes.forEach(b => b.addEventListener("change", () => {
      if (b !== view && b.checked) view.checked = true;
      if (b === view && !b.checked) boxes.forEach(x => (x.checked = false));
      sync();
    }));
    all.addEventListener("change", () => { boxes.forEach(b => (b.checked = all.checked)); });
    sync();
  });

  /* ---------- Licznik znaków ---------- */
  $$("[data-count]").forEach(out => {
    const ta = document.getElementById(out.dataset.count);
    const upd = () => (out.textContent = ta.value.length);
    ta.addEventListener("input", upd); upd();
  });

  /* ---------- Powiększanie zdjęć ---------- */
  const pdlg = $("#photo-dialog");
  $$("img[data-zoom]").forEach(img => img.addEventListener("click", () => {
    if (!pdlg || !pdlg.showModal) { window.open(img.src, "_blank"); return; }
    $("#photo-dialog-img").src = img.src; pdlg.showModal();
  }));

  /* ---------- Powiadomienia SMS / e-mail ---------- */
  const ndlg = $("#notify-dialog");
  const ua = navigator.userAgent || "";
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const state = { data: null, channel: "sms", contact: null, firstName: "" };

  function firstName(name) { return (name || "").trim().split(/\s+/)[0] || ""; }
  function fill(tpl) { return (tpl || "").split("{osoba}").join(state.firstName); }

  function renderContacts() {
    const list = $("#notify-contacts");
    list.innerHTML = "";
    const key = state.channel === "sms" ? "phone" : "email";
    const items = state.data.contacts.filter(c => c[key]);
    $("#notify-nocontacts").hidden = items.length > 0;
    $("#notify-nocontacts").textContent = state.channel === "sms"
      ? "Brak osób z numerem telefonu. Uzupełnij telefon w karcie pracownika lub konta."
      : "Brak osób z adresem e-mail. Uzupełnij e-mail w karcie pracownika lub konta.";
    let chosen = items.find(c => state.contact && c.key === state.contact.key) || items.find(c => c.default) || items[0] || null;
    items.forEach(c => {
      const lab = document.createElement("label");
      lab.className = "contact";
      const inp = document.createElement("input");
      inp.type = "radio"; inp.name = "notify-contact"; inp.value = c.key; inp.checked = chosen === c;
      const info = document.createElement("span"); info.className = "cinfo";
      const strong = document.createElement("strong"); strong.textContent = c.name;
      const small = document.createElement("small"); small.textContent = c.info + " · " + c[key] + (c.default ? " · odpowiedzialny" : "");
      info.append(strong, small); lab.append(inp, info); list.append(lab);
      inp.addEventListener("change", () => selectContact(c, true));
    });
    selectContact(chosen, false);
  }

  function selectContact(c, userAction) {
    const prev = state.firstName;
    state.contact = c;
    state.firstName = c ? firstName(c.name) : "";
    const ta = $("#notify-text"), subj = $("#notify-subject");
    const tpl = state.channel === "sms" ? state.data.sms : state.data.email_body;
    if (!userAction || !ta.dataset.edited) {
      ta.value = fill(tpl);
    } else if (prev && state.firstName) {
      ta.value = ta.value.split(prev).join(state.firstName);
    }
    if (!subj.dataset.edited) subj.value = fill(state.data.email_subject);
    $("#notify-send").disabled = !c;
  }

  function setChannel(ch) {
    state.channel = ch;
    $$("[data-channel]", ndlg).forEach(a => a.classList.toggle("active", a.dataset.channel === ch));
    $$("[data-for=email]", ndlg).forEach(el => (el.hidden = ch !== "email"));
    $("#notify-text").dataset.edited = "";
    $("#notify-text").rows = ch === "sms" ? 5 : 9;
    const btn = $("#notify-send");
    btn.querySelector("span").textContent = ch === "sms" ? "Otwórz SMS" : "Otwórz e-mail";
    renderContacts();
  }

  if (ndlg) {
    $("#notify-text").addEventListener("input", e => (e.target.dataset.edited = "1"));
    $("#notify-subject").addEventListener("input", e => (e.target.dataset.edited = "1"));
    $$("[data-channel]", ndlg).forEach(a => a.addEventListener("click", e => { e.preventDefault(); setChannel(a.dataset.channel); }));
    $("#notify-send").addEventListener("click", async () => {
      const c = state.contact; if (!c) return;
      const text = $("#notify-text").value.trim();
      const err = $("#notify-error"); err.hidden = true;
      const address = state.channel === "sms" ? c.phone : c.email;
      let url;
      if (state.channel === "sms") {
        url = "sms:" + address + (isIOS ? "&" : "?") + "body=" + encodeURIComponent(text);
      } else {
        url = "mailto:" + encodeURIComponent(address) + "?subject=" + encodeURIComponent($("#notify-subject").value) + "&body=" + encodeURIComponent(text);
      }
      try {
        const r = await fetch("/api/powiadomienie", {
          method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
          body: JSON.stringify({ csrf, term_id: state.data.term.id, channel: state.channel, recipient: c.name, address, text }),
        });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "Błąd zapisu");
      } catch (e) {
        err.textContent = "Nie udało się zapisać powiadomienia w dzienniku: " + e.message; err.hidden = false; return;
      }
      window.location.href = url;
      ndlg.close();
    });
    $("#notify-copy").addEventListener("click", async () => {
      const btn = $("#notify-copy"), label = btn.querySelector("span");
      let text = $("#notify-text").value.trim();
      if (state.channel === "email" && $("#notify-subject").value.trim()) text = $("#notify-subject").value.trim() + "\n\n" + text;
      const ok = await copyText(text);
      label.textContent = ok ? "Skopiowano" : "Nie udało się";
      setTimeout(() => (label.textContent = "Kopiuj"), 1800);
    });
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      let ok = false; try { ok = document.execCommand("copy"); } catch (e2) {}
      ta.remove(); return ok;
    }
  }

  /* ---------- Tryb ciemny ---------- */
  const root = document.documentElement;
  function themeLabels() {
    $$("[data-theme-label]").forEach(l => (l.textContent = root.dataset.theme === "dark" ? "Tryb jasny" : "Tryb ciemny"));
    const meta = $('meta[name="theme-color"]');
    if (meta) meta.content = root.dataset.theme === "dark" ? "#0F1626" : "#1F3B70";
  }
  themeLabels();
  $$("[data-theme-toggle]").forEach(b => b.addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("nz-theme", root.dataset.theme); } catch (e) {}
    themeLabels();
  }));

  /* ---------- Pokazywanie sekcji zależnie od wyboru (np. bramka SMS) ---------- */
  $$("[data-show-group]").forEach(sel => {
    const form = sel.form || document;
    const upd = () => $$("[data-group]", form).forEach(g => (g.hidden = g.dataset.group !== sel.value));
    sel.addEventListener("change", upd); upd();
  });

  $$("[data-notify]").forEach(btn => btn.addEventListener("click", async () => {
    if (!ndlg) return;
    btn.disabled = true;
    try {
      const r = await fetch("/api/terminy/" + btn.dataset.notify + "/powiadomienie", { credentials: "same-origin" });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Błąd");
      state.data = data; state.contact = null;
      $("[data-n=title]", ndlg).textContent = data.term.title;
      $("[data-n=object]", ndlg).textContent = data.term.object;
      $("[data-n=due]", ndlg).textContent = data.term.due;
      $("[data-n=left]", ndlg).textContent = data.term.left;
      $("#notify-error").hidden = true;
      $("#notify-subject").dataset.edited = "";
      setChannel("sms");
      if (ndlg.showModal) ndlg.showModal(); else ndlg.setAttribute("open", "");
    } catch (e) {
      alert("Nie można przygotować powiadomienia: " + e.message);
    } finally { btn.disabled = false; }
  }));

  /* ---------- Aplikacja na telefon (PWA) ---------- */
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {}));
  }
})();
