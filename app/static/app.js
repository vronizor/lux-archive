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

  const LABELS = { done: "done", todo: "to do", skip: "skipped" };
  const nextState = (stage, state) => {
    if (stage === "photographed") return { todo: "done", done: "skip", skip: "todo" }[state];
    return state === "done" ? "todo" : "done";
  };
  const asValue = (state) => (state === "todo" ? false : state);

  const paint = (data) => {
    document.querySelectorAll(`[data-roll="${data.id}"]`).forEach((box) => {
      box.querySelectorAll("[data-stage]").forEach((btn) => {
        const st = data.stages[btn.dataset.stage];
        btn.classList.remove("done", "todo", "skip", "busy");
        btn.classList.add(st);
        btn.dataset.state = st;
        const label = btn.querySelector(".state");
        if (label) label.textContent = LABELS[st];
        btn.setAttribute("aria-label", `${btn.dataset.stage}: ${st}`);
      });
      box.closest("tr")?.classList.toggle("done", data.done);
    });
    document.querySelectorAll(`form[data-for="${data.id}"]`).forEach((form) => {
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
    const skipBtn = document.getElementById("bulkskip");
    const selected = () => boxes.filter((b) => b.checked);
    const refresh = () => {
      const n = selected().length;
      bar.hidden = n === 0;
      document.getElementById("bulkcount").textContent = n;
      skipBtn.hidden = stageSel.value !== "photographed";
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
      const value = { done: "done", skip: "skip", clear: false }[btn.dataset.bulk];
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
        const res = await post(`/api/rolls/${id}/place`, { binder, sleeve });
        stack.push(res);
        sleeveIn.value = sleeve + 1;
        const row = rowFor(id);
        if (row) {
          row.classList.add("placed");
          row.querySelector(".loc").textContent = `→ ${binder}/${sleeve}`;
        }
        say(`${id} → ${binder}/${sleeve}` + (res.clash.length ? ` · shares the sleeve with ${res.clash.join(", ")}` : ""), res.clash.length);
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
        await post(`/api/rolls/${last.id}/place`, { binder: b.binder, sleeve: b.sleeve, undo: true, unfile: !b.filed });
        sleeveIn.value = last.sleeve;
        const row = rowFor(last.id);
        if (row) {
          row.classList.remove("placed");
          row.querySelector(".loc").textContent = b.filed ? (b.binder || "—") + (b.sleeve ? `/${b.sleeve}` : "") : "not filed";
        }
        say(`Undid ${last.id}; back to ${b.filed ? (b.binder || "—") + (b.sleeve ? "/" + b.sleeve : "") : "not filed"}.`);
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
    }[k]);
    if (!act) return;
    ev.preventDefault();
    act();
  });

  document.getElementById("invert")?.addEventListener("click", () => {
    document.getElementById("sleeveimg")?.classList.toggle("inverted");
  });
})();
