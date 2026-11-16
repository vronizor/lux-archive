(() => {
  const root = document.documentElement;
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const lamp = document.getElementById("lamp");
  const mode = () => root.dataset.theme || (dark.matches ? "dark" : "light");
  const paintLamp = () => {
    if (!lamp) return;
    const m = mode();
    lamp.querySelector(".lamp-label").textContent = m === "dark" ? "Darkroom" : "Light table";
    lamp.title = m === "dark" ? "Switch on the light table" : "Go to the darkroom";
  };
  lamp?.addEventListener("click", () => {
    const next = mode() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("lux-theme", next); } catch (e) {}
    paintLamp();
  });
  dark.addEventListener?.("change", paintLamp);
  paintLamp();

  const LABELS = { done: "done", todo: "to do", part: "sheet missing" };
  const nextState = (stage, state) => {
    if (stage === "picked") return { todo: "skip", skip: "todo" }[state];
    return state === "done" ? "todo" : "done";
  };
  const asValue = (state) => (state === "todo" ? false : state);
  const toScans = (id) => {
    if (document.body.dataset.page === "roll") {
      const picks = document.getElementById("picks");
      document.getElementById("scans")?.scrollIntoView({ behavior: "smooth", block: "start" });
      picks?.focus({ preventScroll: true });
    } else {
      location.href = `/rolls/${id}#scans`;
    }
  };

  const paint = (data) => {
    document.querySelectorAll(`[data-roll="${data.id}"]`).forEach((box) => {
      box.querySelectorAll("[data-stage]").forEach((btn) => {
        const st = data.stages[btn.dataset.stage];
        btn.classList.remove("done", "todo", "skip", "part", "busy");
        btn.classList.add(st);
        btn.dataset.state = st;
        const label = btn.querySelector(".state");
        if (label) label.textContent = btn.dataset.stage === "picked" ? data.scans : LABELS[st];
        if (btn.dataset.stage === "picked") btn.title = `Scans: ${data.scans}`;
        btn.setAttribute("aria-label", `${btn.dataset.stage}: ${st}`);
      });
      box.closest("tr")?.classList.toggle("done", data.done);
    });
    document.querySelectorAll(`[data-roll="${data.id}"]`).forEach((box) => {
      const cell = box.closest("tr")?.querySelector(".where");
      if (cell) cell.textContent = data.where;
    });
    document.querySelectorAll(`form[data-for="${data.id}"]`).forEach((form) => {
      if (data.stages.filed !== "done") {
        form.querySelectorAll("[name=binder], [name=sleeve]").forEach((i) => (i.value = ""));
        form.querySelectorAll("[name=sleeves]").forEach((i) => (i.checked = false));
      }
      form.querySelectorAll("[data-mirror]").forEach((cb) => (cb.checked = data.stages[cb.dataset.mirror] === "done"));
      form.querySelectorAll("[data-mirror-was]").forEach((h) => (h.value = data.stages[h.dataset.mirrorWas] === "done" ? 1 : 0));
    });
  };

  const post = async (url, body) => {
    const res = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  };

  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-roll] [data-stage]");
    if (!btn) return;
    const id = btn.closest("[data-roll]").dataset.roll;
    const stage = btn.dataset.stage;
    const target = nextState(stage, btn.dataset.state);
    if (stage === "picked" && (!target || btn.closest(".stagebar"))) return toScans(id);
    btn.classList.add("busy");
    try {
      paint(await post(`/api/rolls/${id}/stage`, { stage, value: asValue(target) }));
    } catch (e) {
      btn.classList.remove("busy");
      alert("Could not save: " + e.message);
    }
  });

  const boxes = [...document.querySelectorAll(".rowsel")];
  const bar = document.getElementById("bulkbar");
  if (boxes.length && bar) {
    let last = null;
    const stageSel = document.getElementById("bulkstage");

    const selected = () => boxes.filter((b) => b.checked);
    const refresh = () => {
      const n = selected().length;
      bar.hidden = n === 0;
      document.getElementById("bulkcount").textContent = n;
      const kind = stageSel.value === "picked" ? "picked" : "tick";
      bar.querySelectorAll("[data-for]").forEach((b) => (b.hidden = b.dataset.for !== kind));
    };
    boxes.forEach((b, i) => b.addEventListener("click", (ev) => {
      if (ev.shiftKey && last !== null) {
        const [a, z] = [Math.min(last, i), Math.max(last, i)];
        for (let k = a; k <= z; k++) boxes[k].checked = b.checked;
      }
      last = i;
      refresh();
    }));
    document.getElementById("selall")?.addEventListener("change", (ev) => {
      boxes.forEach((b) => (b.checked = ev.target.checked));
      refresh();
    });
    document.getElementById("bulknone").addEventListener("click", () => {
      boxes.forEach((b) => (b.checked = false));
      const all = document.getElementById("selall");
      if (all) all.checked = false;
      refresh();
    });
    stageSel.addEventListener("change", refresh);
    bar.querySelectorAll("[data-bulk]").forEach((btn) => btn.addEventListener("click", async () => {
      const ids = selected().map((b) => b.value);
      const value = { done: "done", skip: "skip", all: "all", scanned: "scanned", clear: false }[btn.dataset.bulk];
      try {
        const res = await post("/api/bulk", { ids, stage: stageSel.value, value });
        res.updated.forEach(paint);
      } catch (e) {
        alert("Could not save: " + e.message);
      }
    }));
    refresh();
  }

  const placebar = document.getElementById("placebar");
  let undoLast = null;
  if (placebar) {
    const binder = placebar.dataset.binder;
    const sleeveIn = document.getElementById("rsleeve");
    const twoIn = document.getElementById("rtwo");
    const idIn = document.getElementById("placeid");
    const lastEl = document.getElementById("lastplaced");
    const undoBtn = document.getElementById("undo");
    const stack = [];
    const rowFor = (id) => document.querySelector(`.placeable[data-id="${id}"]`);
    const say = (text, warn) => { lastEl.textContent = text; lastEl.classList.toggle("warn", !!warn); };
    const place = async (raw) => {
      const num = parseInt(String(raw).replace(/^v/i, ""), 10);
      if (!num) return;
      const id = "V" + String(num).padStart(3, "0");
      const sleeve = parseInt(sleeveIn.value, 10) || 1;
      try {
        const res = await post(`/api/rolls/${id}/place`, { binder, sleeve, sleeves: twoIn.checked ? 2 : 1 });
        stack.push(res);
        sleeveIn.value = res.next;
        twoIn.checked = false;
        const row = rowFor(id);
        if (row) {
          row.classList.add("placed");
          row.querySelector(".loc").textContent = `→ ${res.where}`;
        }
        say(`${id} → ${res.where}` + (res.clash.length ? ` · shares a sleeve with ${res.clash.join(", ")}` : ""), res.clash.length);
        undoBtn.hidden = false;
      } catch (e) {
        let why = e.message;
        try { why = JSON.parse(why).detail || why; } catch (_) {}
        say(`Could not place ${id}: ${why}`, true);
      }
    };
    undoLast = async () => {
      const last = stack.pop();
      if (!last) return;
      const b = last.before;
      try {
        await post(`/api/rolls/${last.id}/place`, { binder: b.binder, sleeve: b.sleeve, sleeves: b.sleeves, undo: true, unfile: !b.filed });
        sleeveIn.value = last.sleeve;
        twoIn.checked = last.sleeves > 1;
        const was = b.filed ? b.where || "—" : "not filed";
        const row = rowFor(last.id);
        if (row) {
          row.classList.remove("placed");
          row.querySelector(".loc").textContent = was;
        }
        say(`Undid ${last.id}; back to ${was}.`);
        undoBtn.hidden = stack.length === 0;
      } catch (e) {
        stack.push(last);
        say("Could not undo: " + e.message, true);
      }
    };
    undoBtn.addEventListener("click", undoLast);
    document.querySelectorAll(".placeable").forEach((btn) => btn.addEventListener("click", () => {
      if (!btn.classList.contains("placed")) place(btn.dataset.id);
    }));
    document.getElementById("placeform").addEventListener("submit", (ev) => {
      ev.preventDefault();
      place(idIn.value);
      idIn.value = "";
    });
  }
  document.getElementById("rbinder")?.addEventListener("change", (ev) => ev.target.form.requestSubmit());

  document.querySelectorAll("input[list]").forEach((input) => {
    const list = document.getElementById(input.getAttribute("list"));
    if (!list) return;
    const options = [...list.options].map((o) => o.value).filter(Boolean);
    input.removeAttribute("list");
    const host = input.parentElement;
    if (getComputedStyle(host).position === "static") host.style.position = "relative";
    const box = document.createElement("div");
    box.className = "suggest";
    box.setAttribute("role", "listbox");
    box.hidden = true;
    host.appendChild(box);
    let shown = [], active = -1;
    const close = () => { box.hidden = true; active = -1; };
    const mark = () => [...box.children].forEach((b, k) => b.classList.toggle("on", k === active));
    const pick = (value) => {
      input.value = value;
      close();
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    };
    const open = () => {
      const words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
      shown = options.filter((o) => o !== input.value && words.every((w) => o.toLowerCase().includes(w))).slice(0, 8);
      box.replaceChildren(...shown.map((o) => {
        const b = document.createElement("button");
        b.type = "button";
        b.tabIndex = -1;
        b.textContent = o;
        b.addEventListener("pointerdown", (ev) => { ev.preventDefault(); pick(o); });
        return b;
      }));
      active = -1;
      if (!shown.length) return close();
      box.style.top = `${input.offsetTop + input.offsetHeight + 4}px`;
      box.style.left = `${input.offsetLeft}px`;
      box.style.width = `${Math.max(input.offsetWidth, 160)}px`;
      box.hidden = false;
    };
    input.addEventListener("focus", open);
    input.addEventListener("input", (ev) => ev.isTrusted && open());
    input.addEventListener("blur", close);
    input.addEventListener("keydown", (ev) => {
      if (box.hidden) {
        if (ev.key === "ArrowDown") { open(); ev.preventDefault(); }
        return;
      }
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        active = ev.key === "ArrowDown" ? (active + 1) % shown.length : active <= 0 ? shown.length - 1 : active - 1;
        mark();
      } else if (ev.key === "Enter" && active >= 0 && !ev.metaKey && !ev.ctrlKey) {
        ev.preventDefault();
        pick(shown[active]);
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        close();
      }
    });
  });

  const filedBox = document.getElementById("filedbox");
  if (filedBox) {
    const syncPlace = () => document.querySelectorAll("[data-place]").forEach((f) => {
      f.classList.toggle("off", !filedBox.checked);
      f.querySelectorAll("input").forEach((i) => (i.disabled = !filedBox.checked));
    });
    filedBox.addEventListener("change", syncPlace);
    syncPlace();
  }

  const keys = document.getElementById("keys");
  const showKeys = () => keys && !keys.open && keys.showModal();
  document.getElementById("kbd")?.addEventListener("click", showKeys);
  keys?.addEventListener("click", (ev) => ev.target === keys && keys.close());
  if (/Mac|iPhone|iPad/.test(navigator.platform)) document.querySelectorAll("kbd.mod").forEach((k) => (k.textContent = "⌘"));

  const page = document.body.dataset.page;
  const filters = document.getElementById("filters");
  document.addEventListener("click", (ev) => {
    if (filters?.open && !filters.contains(ev.target)) filters.open = false;
  });
  if (page === "index" && location.hash === "#search") document.querySelector(".search")?.focus();
  const rows = page === "index" ? [...document.querySelectorAll("table.rolls tbody tr")] : [];
  let cur = -1;
  const moveRow = (step) => {
    if (!rows.length) return;
    rows[cur]?.classList.remove("cur");
    cur = cur < 0 ? (step > 0 ? 0 : rows.length - 1) : Math.min(rows.length - 1, Math.max(0, cur + step));
    rows[cur].classList.add("cur");
    rows[cur].scrollIntoView({ block: "nearest" });
  };
  const gapNav = document.querySelector(".rollhead[data-gap-prev]");
  const photoIn = document.getElementById("photo-in");
  let photoByKey = false;
  photoIn?.addEventListener("change", () => {
    if (photoByKey && photoIn.files.length) photoIn.form.requestSubmit();
    photoByKey = false;
  });
  photoIn?.addEventListener("cancel", () => (photoByKey = false));
  document.querySelectorAll("input[data-autosubmit]").forEach((i) =>
    i.addEventListener("change", () => i.files.length && i.form.requestSubmit()));
  const typing = (el) => el?.isContentEditable || (/^(INPUT|TEXTAREA|SELECT)$/.test(el?.tagName) && !/^(checkbox|radio|button|submit|file)$/.test(el.type));
  const go = (url) => (location.href = url);

  const loupe = (() => {
    const btn = document.getElementById("loupe");
    if (!btn) return null;
    const zoomBox = document.getElementById("loupezoom");
    const lens = document.createElement("div");
    lens.className = "loupe";
    lens.hidden = true;
    lens.innerHTML = '<div class="loupe-hud"><span class="buf"></span><span class="picks"></span><span class="msg"></span></div>';
    document.body.append(lens);
    const hud = { buf: lens.querySelector(".buf"), picks: lens.querySelector(".picks"), msg: lens.querySelector(".msg") };
    const rollId = document.querySelector(".stagebar")?.dataset.roll;
    const picksField = document.getElementById("picks");
    const pickForm = document.getElementById("pickform");
    let buffer = "", msgTimer = null;
    const showHud = (msg) => {
      hud.buf.textContent = buffer ? `${buffer}▏` : "#";
      const picks = picksField?.value.trim();
      hud.picks.textContent = picks ? `Picks: ${picks}` : "Type a frame number, Enter to pick";
      if (msg !== undefined) {
        hud.msg.textContent = msg;
        clearTimeout(msgTimer);
        msgTimer = setTimeout(() => (hud.msg.textContent = ""), 2500);
      }
    };
    const pick = async (frame) => {
      try {
        const res = await post(`/api/rolls/${rollId}/pick`, { frame });
        if (picksField) {
          picksField.value = res.picks;
          picksField.dispatchEvent(new Event("input"));
        }
        paint(res);
        const head = document.querySelector("#scans h2 .muted");
        if (head) head.textContent = `· ${res.scans}`;
        showHud(`${res.added ? "+" : "−"} ${res.frame}`);
        return true;
      } catch (e) {
        let msg = e.message;
        try { msg = JSON.parse(msg).detail || msg; } catch (_) {}
        showHud(msg);
        return false;
      }
    };
    const key = (k) => {
      if (/^\d$/.test(k) && !/\d\d|A/.test(buffer)) buffer += k;
      else if ((k === "a" || k === "A") && /^\d{1,2}$/.test(buffer)) buffer += "A";
      else if (k === "Backspace" && buffer) buffer = buffer.slice(0, -1);
      else if (k === "Escape" && buffer) buffer = "";
      else if (k === "Enter" && buffer) {
        const f = buffer;
        buffer = "";
        showHud("…");
        pick(f);
        return true;
      } else return /^\d$/.test(k) || (k === "a" || k === "A") && !!buffer;
      showHud();
      return true;
    };
    pickForm?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const input = pickForm.querySelector("input");
      if (input.value.trim() && await pick(input.value.trim())) input.value = "";
    });
    const SPAN = [0.05, 0.5];
    const clamp = (v) => Math.min(SPAN[1], Math.max(SPAN[0], v));
    let on = false, fallback = 0.21, spans = {}, img = null, last = null;
    try {
      on = sessionStorage.getItem("lux-loupe") === "1";
      fallback = clamp(parseFloat(localStorage.getItem("lux-loupe-span")) || fallback);
      spans = JSON.parse(localStorage.getItem("lux-loupe-spans") || "{}");
    } catch (e) {}
    const save = () => {
      try {
        sessionStorage.setItem("lux-loupe", on ? "1" : "0");
        localStorage.setItem("lux-loupe-span", fallback);
        localStorage.setItem("lux-loupe-spans", JSON.stringify(spans));
      } catch (e) {}
    };
    const current = () => img || document.querySelector(".sleeveimg");
    const spanOf = (el) => spans[el?.dataset.sheet] || fallback;
    const power = (el) => lens.offsetWidth / (spanOf(el) * el.getBoundingClientRect().width);
    const label = () => {
      const el = current();
      btn.textContent = on && el ? `Loupe ×${power(el).toFixed(1)}` : "Loupe";
      btn.setAttribute("aria-pressed", on);
      if (zoomBox) zoomBox.hidden = !on;
      if (pickForm) pickForm.hidden = !on;
      if (!on) buffer = "";
      showHud();
      document.body.classList.toggle("loupe-on", on);
      if (!on) lens.hidden = true;
    };
    const place = () => {
      if (!on || !img || !last) return;
      const r = img.getBoundingClientRect();
      const { x, y, touch } = last;
      if (x < r.left || x > r.right || y < r.top || y > r.bottom) return (lens.hidden = true);
      lens.hidden = false;
      const p = power(img);
      const w = lens.offsetWidth, h = lens.offsetHeight;
      const keep = (v, size, max) => Math.min(max - size / 2 - 4, Math.max(size / 2 + 4, v));
      lens.style.left = `${keep(x, w, innerWidth)}px`;
      lens.style.top = `${keep(touch ? y - h * 0.75 : y, h, innerHeight)}px`;
      lens.style.backgroundImage = `url("${img.currentSrc || img.src}")`;
      lens.style.backgroundSize = `${r.width * p}px ${r.height * p}px`;
      lens.style.backgroundPosition = `${w / 2 - (x - r.left) * p}px ${h / 2 - (y - r.top) * p}px`;
    };
    const track = (ev) => {
      if (img !== ev.currentTarget) {
        img = ev.currentTarget;
        label();
      }
      last = { x: ev.clientX, y: ev.clientY, touch: ev.pointerType === "touch" };
      place();
    };
    const zoom = (dir) => {
      const el = current();
      if (!on || !el) return;
      const s = clamp(spanOf(el) * (dir > 0 ? 1 / 1.15 : 1.15));
      spans[el.dataset.sheet] = fallback = s;
      save();
      label();
      place();
    };
    const toggle = () => {
      on = !on;
      save();
      label();
      place();
    };
    document.querySelectorAll(".sleeveimg").forEach((el) => {
      el.addEventListener("pointermove", track);
      el.addEventListener("pointerdown", track);
      el.addEventListener("pointerleave", () => (lens.hidden = true));
      el.addEventListener("pointerup", (ev) => ev.pointerType === "touch" && (lens.hidden = true));
    });
    window.addEventListener("scroll", () => {
      const under = on && last && !last.touch && document.elementFromPoint(last.x, last.y)?.closest(".sleeveimg");
      if (!under) return (lens.hidden = true);
      if (img !== under) {
        img = under;
        label();
      }
      place();
    }, { passive: true });
    btn.addEventListener("click", toggle);
    zoomBox?.querySelectorAll("[data-zoom]").forEach((b) => b.addEventListener("click", () => zoom(+b.dataset.zoom)));
    label();
    return { toggle, zoom, key, refresh: place, isOn: () => on };
  })();

  document.addEventListener("keydown", (ev) => {
    if (ev.isComposing || ev.defaultPrevented) return;
    const t = ev.target;
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
      const form = t.closest?.("form.rollform") || document.querySelector("form.rollform");
      if (!form) return;
      ev.preventDefault();
      const open = form.querySelector('button[value="open"]');
      open ? form.requestSubmit(open) : form.requestSubmit();
      return;
    }
    const pair = { start_year: "end_year", end_year: "start_year", y0: "y1", y1: "y0" }[t.name];
    if (pair && (ev.key === "ArrowUp" || ev.key === "ArrowDown") && !ev.metaKey && !ev.ctrlKey && !ev.altKey) {
      ev.preventDefault();
      const other = t.form?.elements[pair];
      const cur = parseInt(t.value, 10);
      const thisYear = new Date().getFullYear();
      const next = Number.isNaN(cur)
        ? parseInt(other?.value, 10) || thisYear
        : cur + (ev.key === "ArrowUp" ? 1 : -1);
      t.value = Math.min(thisYear, Math.max(1900, next));
      t.select();
      return;
    }
    if (ev.key === "Escape" && filters?.open) {
      filters.open = false;
      filters.querySelector("summary").focus();
      return;
    }
    if (typing(t)) {
      if (ev.key === "Escape") t.blur();
      return;
    }
    if (ev.metaKey || ev.ctrlKey || ev.altKey || keys?.open) return;
    const k = ev.key;
    if (page === "index" && rows.length) {
      const row = rows[cur];
      const rowAct = {
        j: () => moveRow(1),
        k: () => moveRow(-1),
        x: () => row?.querySelector(".rowsel")?.dispatchEvent(new MouseEvent("click", { bubbles: true })),
        X: () => row?.querySelector(".rowsel")?.dispatchEvent(new MouseEvent("click", { bubbles: true, shiftKey: true })),
        Enter: row && !t.closest?.("a, button, input, select, textarea, summary") ? () => go(row.querySelector(".rid a").href) : null,
        Escape: bar && !bar.hidden ? () => document.getElementById("bulknone").click() : null,
      }[k];
      if (rowAct) {
        ev.preventDefault();
        return rowAct();
      }
    }
    if (page === "roll" && loupe?.isOn() && loupe.key(k)) {
      ev.preventDefault();
      return;
    }
    if (page === "roll" && ev.shiftKey && gapNav && (k === "ArrowLeft" || k === "ArrowRight")) {
      ev.preventDefault();
      const id = gapNav.dataset[k === "ArrowLeft" ? "gapPrev" : "gapNext"];
      if (id) go(`/rolls/${id}`);
      return;
    }
    const act = {
      "?": showKeys,
      n: () => go("/add"),
      i: () => go("/rolls"),
      h: () => go("/"),
      ".": () => go("/last"),
      d: () => go("/docs"),
      F: () => go("/field"),
      l: () => go("/load"),
      t: () => lamp?.click(),
      "/": () => (page === "index" ? document.querySelector(".search")?.select() : page === "refile" && document.getElementById("placeid") ? document.getElementById("placeid").focus() : go("/rolls#search")),
      u: page === "refile" && undoLast ? undoLast : null,
      f: page === "index" && filters ? () => { filters.open = true; filters.querySelector(".pop input[type=checkbox]")?.focus(); } : null,
    }[k] || (page === "roll" && {
      ArrowLeft: () => document.querySelector(".nav-arrow:not(.off)[aria-label^=Prev]")?.click(),
      ArrowRight: () => document.querySelector(".nav-arrow:not(.off)[aria-label^=Next]")?.click(),
      e: () => {
        const c = document.getElementById("contents");
        c?.focus();
        c?.setSelectionRange(c.value.length, c.value.length);
      },
      ...Object.fromEntries([1, 2, 3, 4].map((n) => [n, () => document.querySelectorAll(".stagebar [data-stage]")[n - 1]?.click()])),
      v: () => document.getElementById("flip")?.click(),
      z: () => loupe?.toggle(),
      x: () => loupe?.zoom(-1),
      c: () => loupe?.zoom(1),
      Escape: loupe?.isOn() ? () => loupe.toggle() : null,
      p: () => { photoByKey = true; photoIn?.click(); },
    }[k]);
    if (!act) return;
    ev.preventDefault();
    act();
  });

  const flip = document.getElementById("flip");
  flip?.addEventListener("click", () => {
    const neg = flip.getAttribute("aria-pressed") !== "true";
    document.querySelectorAll(".sleeveimg").forEach((img) => (img.src = neg ? img.dataset.neg : img.dataset.pos));
    document.querySelector(".sleeveimg")?.addEventListener("load", () => loupe?.refresh(), { once: true });
    flip.setAttribute("aria-pressed", neg);
    flip.textContent = neg ? "Show positive" : "Show negative";
  });

  const picksIn = document.getElementById("picks");
  const scansIn = document.getElementById("scans-in");
  const chipBox = document.getElementById("framechips");
  if (picksIn && scansIn && chipBox) {
    const expand = (text) => {
      const t = text.trim().toLowerCase();
      if (!t || ["none", "nothing", "-", "all", "*"].includes(t)) return [];
      const out = [];
      t.replace(/\s*[-–—]\s*/g, "-").split(/[,;\s]+/).forEach((p) => {
        const r = p.match(/^(\d{1,2})-(\d{1,2})$/);
        if (r) {
          const [a, z] = [+r[1], +r[2]].sort((x, y) => x - y);
          for (let n = a; n <= z && z - a <= 45; n++) out.push(String(n));
        } else if (/^\d{1,2}a?$/.test(p)) {
          out.push(p === "00" ? "00" : String(parseInt(p, 10)) + (p.endsWith("a") ? "A" : ""));
        }
      });
      return [...new Set(out)];
    };
    const draw = () => {
      const picks = expand(picksIn.value);
      const all = scansIn.value.trim().toLowerCase() === "all";
      const done = new Set(expand(scansIn.value));
      chipBox.replaceChildren(...picks.map((f) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "fchip" + (all || done.has(f) ? " on" : "");
        b.textContent = f;
        b.setAttribute("aria-pressed", all || done.has(f));
        b.addEventListener("click", () => {
          const cur = scansIn.value.trim().toLowerCase() === "all" ? new Set(picks) : new Set(expand(scansIn.value));
          cur.has(f) ? cur.delete(f) : cur.add(f);
          scansIn.value = [...picks.filter((x) => cur.has(x)), ...[...cur].filter((x) => !picks.includes(x))].join(", ");
          draw();
        });
        return b;
      }));
      chipBox.hidden = picks.length === 0;
    };
    picksIn.addEventListener("input", draw);
    scansIn.addEventListener("input", draw);
    document.querySelectorAll("[data-fill]").forEach((b) => b.addEventListener("click", () => {
      const target = document.getElementById(b.dataset.fill);
      target.value = b.dataset.from ? document.getElementById(b.dataset.from).value : b.dataset.value;
      draw();
    }));
    draw();
    if (location.hash === "#scans" && !picksIn.value) picksIn.focus();
  }
})();
