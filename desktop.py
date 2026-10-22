"""Desktop app for searching CloudWatch logs.  Run with:  python desktop.py"""
from __future__ import annotations

import csv
import queue
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import logquery as lq

APP_NAME = "CloudWatch Log Search"
USER_CONFIG = Path.home() / ".cloudwatch-log-search" / "config.yaml"
CUSTOM = "Custom…"

# Background threads must not touch Tk widgets; they post callbacks here and
# the UI thread runs them (see App.poll).
UI_QUEUE: "queue.Queue" = queue.Queue()


def in_background(work, on_done):
    """Run work() in a thread, then on_done(result, error) on the UI thread."""
    def run():
        try:
            result, err = work(), None
        except Exception as e:  # noqa: BLE001 - shown to the user
            result, err = None, e
        UI_QUEUE.put(lambda: on_done(result, err))
    threading.Thread(target=run, daemon=True).start()


def bundled_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def config_path() -> Path:
    """Keep the user's config in their home folder so it survives app updates."""
    if not USER_CONFIG.exists():
        USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(bundled_path("config.yaml"), USER_CONFIG)
    return USER_CONFIG


class LogGroupPicker(tk.Toplevel):
    """Dialog that lists the account's log groups and lets you tick some."""

    def __init__(self, master, client, selected: list[str], on_done):
        super().__init__(master)
        self.title("Choose log groups")
        self.geometry("560x480")
        self.transient(master)
        self.client, self.on_done, self.all = client, on_done, []
        self.chosen = set(selected)

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Filter:").pack(side="left")
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(top, textvariable=self.filter).pack(side="left", fill="x", expand=True, padx=6)

        self.listbox = tk.Listbox(self, selectmode="multiple", activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=8)
        self.listbox.bind("<<ListboxSelect>>", self.sync)
        self.status = ttk.Label(self, text="Loading log groups…", padding=(8, 4))
        self.status.pack(fill="x")

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Use selected", command=self.done).pack(side="right", padx=6)
        in_background(lambda: lq.list_log_groups(self.client, max_items=5000), self.loaded)

    def loaded(self, groups, err):
        if not self.winfo_exists():
            return
        if err:
            self.status.config(text=f"Could not list log groups: {err}")
            return
        self.all = groups
        self.refresh()

    def visible(self):
        f = self.filter.get().lower()
        return [g for g in self.all if f in g.lower()]

    def refresh(self):
        self.listbox.delete(0, "end")
        for i, g in enumerate(self.visible()):
            self.listbox.insert("end", g)
            if g in self.chosen:
                self.listbox.selection_set(i)
        self.status.config(text=f"{len(self.all)} log groups · {len(self.chosen)} selected")

    def sync(self, _=None):
        shown = self.visible()
        picked = {shown[i] for i in self.listbox.curselection()}
        self.chosen = (self.chosen - set(shown)) | picked
        self.status.config(text=f"{len(self.all)} log groups · {len(self.chosen)} selected")

    def done(self):
        self.on_done(sorted(self.chosen))
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1150x720")
        self.minsize(800, 500)
        self.cfg_file = config_path()
        self.cfg = lq.load_config(self.cfg_file)
        self.custom_groups: list[str] = []
        self.rows: list[dict] = []
        self.build()
        self.on_source()
        self.poll()

    def poll(self):
        while not UI_QUEUE.empty():
            UI_QUEUE.get_nowait()()
        self.after(50, self.poll)

    # ---------- layout ----------
    def build(self):
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        self.region = tk.StringVar(value=self.cfg["region"])
        self.profile = tk.StringVar(value=self.cfg["profile"] or "")
        self.labels = {v.get("label", k): k for k, v in self.cfg["sources"].items()}
        self.source = tk.StringVar(value=next(iter(self.labels), CUSTOM))
        self.range = tk.StringVar(value="Last 1 hour")

        def field(label, widget):
            ttk.Label(bar, text=label).pack(side="left", padx=(8, 2))
            widget.pack(side="left")

        field("Logs:", ttk.Combobox(bar, textvariable=self.source, state="readonly", width=12,
                                    values=list(self.labels) + [CUSTOM]))
        self.source.trace_add("write", lambda *_: self.on_source())
        ttk.Button(bar, text="Log groups…", command=self.pick_groups).pack(side="left", padx=4)
        field("Time:", ttk.Combobox(bar, textvariable=self.range, state="readonly", width=15,
                                    values=list(lq.RANGES)))
        field("Region:", ttk.Entry(bar, textvariable=self.region, width=12))
        field("AWS profile:", ttk.Entry(bar, textvariable=self.profile, width=14))

        self.groups_label = ttk.Label(self, padding=(16, 0), foreground="gray")
        self.groups_label.pack(fill="x")

        self.tabs = ttk.Notebook(self, padding=8)
        self.tabs.pack(fill="x")

        simple = ttk.Frame(self.tabs, padding=8)
        self.term = tk.StringVar()
        self.level = tk.StringVar(value="Any")
        self.limit = tk.IntVar(value=200)
        ttk.Label(simple, text="Search (all words must match):").pack(side="left")
        e = ttk.Entry(simple, textvariable=self.term, width=50)
        e.pack(side="left", padx=6, fill="x", expand=True)
        e.bind("<Return>", lambda _: self.run())
        ttk.Label(simple, text="Level:").pack(side="left")
        ttk.Combobox(simple, textvariable=self.level, state="readonly", width=7,
                     values=list(lq.LEVEL_PATTERNS)).pack(side="left", padx=4)
        ttk.Label(simple, text="Max rows:").pack(side="left")
        ttk.Spinbox(simple, from_=10, to=10000, increment=50, textvariable=self.limit,
                    width=7).pack(side="left", padx=4)
        self.tabs.add(simple, text="Simple search")

        saved = ttk.Frame(self.tabs, padding=8)
        self.saved_name = tk.StringVar()
        self.saved_term = tk.StringVar()
        ttk.Label(saved, text="Query:").pack(side="left")
        self.saved_box = ttk.Combobox(saved, textvariable=self.saved_name, state="readonly", width=35)
        self.saved_box.pack(side="left", padx=6)
        ttk.Label(saved, text="Search term (if needed):").pack(side="left")
        se = ttk.Entry(saved, textvariable=self.saved_term, width=35)
        se.pack(side="left", padx=6)
        se.bind("<Return>", lambda _: self.run())
        self.tabs.add(saved, text="Saved queries")

        adv = ttk.Frame(self.tabs, padding=8)
        self.adv_text = tk.Text(adv, height=6, font=("Courier", 11), wrap="none")
        self.adv_text.insert("1.0", lq.build_query())
        self.adv_text.pack(fill="x")
        self.tabs.add(adv, text="Advanced (Insights query)")

        actions = ttk.Frame(self, padding=(8, 0))
        actions.pack(fill="x")
        self.run_btn = ttk.Button(actions, text="▶  Run", command=self.run)
        self.run_btn.pack(side="left")
        ttk.Button(actions, text="Export CSV…", command=self.export).pack(side="left", padx=6)
        ttk.Button(actions, text="Show query", command=self.show_query).pack(side="left")
        self.status = ttk.Label(actions, text="Ready")
        self.status.pack(side="left", padx=12)

        table = ttk.Frame(self, padding=8)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, show="headings")
        ys = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self.show_row)
        ttk.Label(self, text="Tip: double-click a row to see the full log line.",
                  foreground="gray", padding=(16, 0, 0, 6)).pack(anchor="w")

    # ---------- helpers ----------
    def source_key(self):
        return self.labels.get(self.source.get())

    def log_groups(self) -> list[str]:
        key = self.source_key()
        return self.cfg["sources"][key].get("log_groups", []) if key else self.custom_groups

    def on_source(self):
        key = self.source_key()
        saved = list(self.cfg["sources"][key].get("saved_queries", {})) if key else []
        self.saved_box["values"] = saved
        self.saved_name.set(saved[0] if saved else "")
        groups = self.log_groups()
        self.groups_label.config(
            text="Log groups: " + (", ".join(groups) if groups else "none — click “Log groups…”"))

    def client(self):
        return lq.make_client(self.region.get().strip(), self.profile.get().strip() or None)

    def pick_groups(self):
        try:
            client = self.client()
        except Exception as e:
            messagebox.showerror(APP_NAME, f"AWS login problem:\n{e}")
            return
        LogGroupPicker(self, client, self.log_groups(), self.set_groups)

    def set_groups(self, groups):
        key = self.source_key()
        if key:
            self.cfg["sources"][key]["log_groups"] = groups
            self.cfg["region"] = self.region.get().strip()
            self.cfg["profile"] = self.profile.get().strip() or None
            lq.save_config(self.cfg, self.cfg_file)  # remember for next time
        else:
            self.custom_groups = groups
        self.on_source()

    def current_query(self) -> str:
        tab = self.tabs.index(self.tabs.select())
        if tab == 0:
            return lq.build_query(self.term.get(), self.level.get(), int(self.limit.get()))
        if tab == 1:
            key = self.source_key()
            saved = self.cfg["sources"][key].get("saved_queries", {}) if key else {}
            if self.saved_name.get() not in saved:
                raise ValueError("No saved query selected.")
            return lq.fill_template(saved[self.saved_name.get()], self.saved_term.get())
        return self.adv_text.get("1.0", "end").strip()

    def show_query(self):
        try:
            messagebox.showinfo("Query", self.current_query())
        except ValueError as e:
            messagebox.showwarning(APP_NAME, str(e))

    # ---------- running ----------
    def run(self):
        try:
            query = self.current_query()
            groups = self.log_groups()
            if not groups:
                raise ValueError("Pick some log groups first (click “Log groups…”).")
            client = self.client()
        except Exception as e:
            messagebox.showwarning(APP_NAME, str(e))
            return
        start, end = lq.time_window(self.range.get())
        self.run_btn.state(["disabled"])
        self.status.config(text="Querying CloudWatch…")

        in_background(lambda: lq.run_query(client, groups, query, start, end), self.show_rows)

    def show_rows(self, rows, err=None):
        self.run_btn.state(["!disabled"])
        if err:
            self.status.config(text="Failed")
            messagebox.showerror(APP_NAME, f"{type(err).__name__}: {err}")
            return
        self.rows = rows
        self.status.config(text=f"{len(rows)} rows")
        cols = []
        for r in rows:
            cols += [k for k in r if k not in cols]
        cols = cols or ["@timestamp", "@message"]
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = cols
        for c in cols:
            wide = c == "@message"
            self.tree.heading(c, text=c)
            self.tree.column(c, width=750 if wide else 210, stretch=wide)
        for i, r in enumerate(rows):
            vals = [str(r.get(c, "")).replace("\n", " ")[:2000] for c in cols]
            self.tree.insert("", "end", iid=str(i), values=vals)

    def show_row(self, _=None):
        sel = self.tree.selection()
        if not sel:
            return
        row = self.rows[int(sel[0])]
        win = tk.Toplevel(self)
        win.title("Log entry")
        win.geometry("800x450")
        text = tk.Text(win, wrap="word", font=("Courier", 11))
        text.pack(fill="both", expand=True)
        for k, v in row.items():
            text.insert("end", f"{k}:\n{v}\n\n")
        text.config(state="disabled")

    def export(self):
        if not self.rows:
            messagebox.showinfo(APP_NAME, "Nothing to export yet — run a query first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="logs.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        fields = list(dict.fromkeys(k for r in self.rows for k in r))
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(self.rows)
        self.status.config(text=f"Saved {len(self.rows)} rows to {path}")


if __name__ == "__main__":
    App().mainloop()
