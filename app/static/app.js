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

  const LABELS = { done: "done", todo: "to do" };
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
        btn.classList.remove("done", "todo", "skip", "busy");
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
  const typing = (el) => el?.isContentEditable || (/^(INPUT|TEXTAREA|SELECT)$/.test(el?.tagName) && !/^(checkbox|radio|button|submit|file)$/.test(el.type));
  const go = (url) => (location.href = url);

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
    const act = {
      "?": showKeys,
      n: () => go("/add"),
      i: () => go("/rolls"),
      h: () => go("/"),
      d: () => go("/docs"),
      l: () => lamp?.click(),
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
    }[k]);
    if (!act) return;
    ev.preventDefault();
    act();
  });

  const flip = document.getElementById("flip");
  flip?.addEventListener("click", () => {
    const img = document.getElementById("sleeveimg");
    const neg = flip.getAttribute("aria-pressed") !== "true";
    img.src = neg ? img.dataset.neg : img.dataset.pos;
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
