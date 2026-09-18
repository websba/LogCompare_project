"""Local Tkinter UI for side-by-side log comparison."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox, ttk

from diff_engine import AlignedLine, DiffResult, compare_logs

COLORS = {
    "match": "#c8e6c9",
    "mismatch": "#f8bbd0",
    "gap": "#eeeeee",
    "prefix": "#e0e0e0",
    "search_hit": "#fff59d",
    "search_current": "#ffb300",
}


@dataclass
class SideSearch:
    """Per-pane search state."""

    query: tk.StringVar
    count_var: tk.StringVar
    matches: list[tuple[str, str]] = field(default_factory=list)
    current: int = -1
    last_query: str = ""


class LogDiffApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Log 左右比對工具")
        self.geometry("1100x740")
        self.minsize(800, 520)

        self._syncing_scroll = False
        self._ignore_ts = tk.BooleanVar(value=False)
        self._ignore_mode = tk.StringVar(value="marker")
        self._skip_n = tk.StringVar(value="19")
        self._skip_marker = tk.StringVar(value="[M:")
        self._status_var = tk.StringVar(value="就緒")
        self._progress_var = tk.DoubleVar(value=0.0)
        self._event_queue: queue.Queue[tuple] = queue.Queue()
        self._comparing = False

        self._left_search = SideSearch(
            query=tk.StringVar(value=""),
            count_var=tk.StringVar(value="0/0"),
        )
        self._right_search = SideSearch(
            query=tk.StringVar(value=""),
            count_var=tk.StringVar(value="0/0"),
        )

        self._build_ui()
        self._configure_tags(self.left_text)
        self._configure_tags(self.right_text)
        self._bind_scroll_sync()
        self.after(50, self._poll_queue)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 8, 8, 4))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="清除左", command=self._clear_left).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(toolbar, text="清除右", command=self._clear_right).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        ttk.Checkbutton(
            toolbar,
            text="忽略時間戳",
            variable=self._ignore_ts,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(
            toolbar,
            text="分隔字串之前",
            variable=self._ignore_mode,
            value="marker",
        ).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Entry(toolbar, textvariable=self._skip_marker, width=8).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Radiobutton(
            toolbar,
            text="前 N 字元",
            variable=self._ignore_mode,
            value="chars",
        ).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Label(toolbar, text="N:").pack(side=tk.LEFT)
        ttk.Entry(toolbar, textvariable=self._skip_n, width=5).pack(
            side=tk.LEFT, padx=(2, 12)
        )
        self._compare_btn = ttk.Button(toolbar, text="比對", command=self._compare)
        self._compare_btn.pack(side=tk.LEFT)

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        left_frame = ttk.Frame(paned)
        right_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)
        paned.add(right_frame, weight=1)

        self._build_side_header(left_frame, "左：log1（可貼上）", self._left_search, "left")
        self._build_side_header(right_frame, "右：log2（可貼上）", self._right_search, "right")

        self.left_text = self._make_text(left_frame)
        self.right_text = self._make_text(right_frame)

        status = ttk.Frame(self, padding=(8, 0, 8, 8))
        status.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(status, textvariable=self._status_var).pack(side=tk.LEFT, padx=(0, 8))
        self._progress = ttk.Progressbar(
            status,
            mode="determinate",
            maximum=100,
            variable=self._progress_var,
        )
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_side_header(
        self,
        parent: ttk.Frame,
        title: str,
        search: SideSearch,
        side: str,
    ) -> None:
        header = ttk.Frame(parent)
        header.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(header, text=title).pack(side=tk.LEFT)

        search_bar = ttk.Frame(header)
        search_bar.pack(side=tk.RIGHT)
        ttk.Label(search_bar, text="搜尋").pack(side=tk.LEFT, padx=(0, 2))
        entry = ttk.Entry(search_bar, textvariable=search.query, width=16)
        entry.pack(side=tk.LEFT, padx=(0, 4))
        entry.bind("<Return>", lambda _e, s=side: self._search_next(s))
        search.query.trace_add(
            "write",
            lambda *_args, s=side: self._on_search_query_changed(s),
        )
        ttk.Button(
            search_bar,
            text="上一個",
            width=6,
            command=lambda s=side: self._search_prev(s),
        ).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(
            search_bar,
            text="下一個",
            width=6,
            command=lambda s=side: self._search_next(s),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(search_bar, textvariable=search.count_var, width=8).pack(side=tk.LEFT)

    def _make_text(self, parent: ttk.Frame) -> tk.Text:
        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.BOTH, expand=True)

        yscroll = ttk.Scrollbar(wrap, orient=tk.VERTICAL)
        xscroll = ttk.Scrollbar(wrap, orient=tk.HORIZONTAL)
        text = tk.Text(
            wrap,
            wrap=tk.NONE,
            undo=True,
            font=("Consolas", 10),
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
        )
        yscroll.config(command=text.yview)
        xscroll.config(command=text.xview)

        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        return text

    def _configure_tags(self, widget: tk.Text) -> None:
        for name, color in COLORS.items():
            widget.tag_configure(name, background=color)
        widget.tag_configure("gap_line", background=COLORS["gap"])
        # Search highlights should sit above diff colors.
        widget.tag_raise("search_hit")
        widget.tag_raise("search_current")

    def _bind_scroll_sync(self) -> None:
        self.left_text.configure(
            yscrollcommand=lambda *args: self._on_scroll(self.left_text, "y", *args),
            xscrollcommand=lambda *args: self._on_scroll(self.left_text, "x", *args),
        )
        self.right_text.configure(
            yscrollcommand=lambda *args: self._on_scroll(self.right_text, "y", *args),
            xscrollcommand=lambda *args: self._on_scroll(self.right_text, "x", *args),
        )

        for widget in (self.left_text, self.right_text):
            widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
            widget.bind("<Shift-MouseWheel>", self._on_shift_mousewheel, add="+")
            widget.bind("<Button-4>", self._on_mousewheel, add="+")
            widget.bind("<Button-5>", self._on_mousewheel, add="+")

    def _sibling(self, widget: tk.Text) -> tk.Text:
        return self.right_text if widget is self.left_text else self.left_text

    def _on_scroll(self, source: tk.Text, axis: str, *args: str) -> None:
        sibling = self._sibling(source)
        if axis == "y":
            self._update_scrollbar(source, "y", args)
            if not self._syncing_scroll:
                self._syncing_scroll = True
                try:
                    sibling.yview_moveto(args[0])
                finally:
                    self._syncing_scroll = False
        else:
            self._update_scrollbar(source, "x", args)
            if not self._syncing_scroll:
                self._syncing_scroll = True
                try:
                    sibling.xview_moveto(args[0])
                finally:
                    self._syncing_scroll = False

    def _update_scrollbar(self, text: tk.Text, axis: str, args: tuple[str, ...]) -> None:
        parent = text.master
        for child in parent.winfo_children():
            if not isinstance(child, ttk.Scrollbar):
                continue
            if axis == "y" and str(child.cget("orient")) == tk.VERTICAL:
                child.set(*args)
            elif axis == "x" and str(child.cget("orient")) == tk.HORIZONTAL:
                child.set(*args)

    def _on_mousewheel(self, event: tk.Event) -> str | None:
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1

        if self._syncing_scroll:
            return "break"
        self._syncing_scroll = True
        try:
            self.left_text.yview_scroll(delta, "units")
            self.right_text.yview_scroll(delta, "units")
        finally:
            self._syncing_scroll = False
        return "break"

    def _on_shift_mousewheel(self, event: tk.Event) -> str | None:
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1

        if self._syncing_scroll:
            return "break"
        self._syncing_scroll = True
        try:
            self.left_text.xview_scroll(delta, "units")
            self.right_text.xview_scroll(delta, "units")
        finally:
            self._syncing_scroll = False
        return "break"

    def _side_objects(self, side: str) -> tuple[tk.Text, SideSearch]:
        if side == "left":
            return self.left_text, self._left_search
        return self.right_text, self._right_search

    def _clear_search_tags(self, widget: tk.Text) -> None:
        widget.tag_remove("search_hit", "1.0", tk.END)
        widget.tag_remove("search_current", "1.0", tk.END)

    def _reset_search(self, side: str) -> None:
        widget, search = self._side_objects(side)
        self._clear_search_tags(widget)
        search.matches.clear()
        search.current = -1
        search.last_query = ""
        search.count_var.set("0/0")

    def _on_search_query_changed(self, side: str) -> None:
        _, search = self._side_objects(side)
        if search.query.get() == "":
            self._reset_search(side)

    def _collect_matches(self, widget: tk.Text, needle: str) -> list[tuple[str, str]]:
        matches: list[tuple[str, str]] = []
        if not needle:
            return matches
        start = "1.0"
        while True:
            pos = widget.search(needle, start, stopindex=tk.END, nocase=False)
            if not pos:
                break
            end = f"{pos}+{len(needle)}c"
            matches.append((pos, end))
            start = end
        return matches

    def _apply_search_highlights(self, widget: tk.Text, search: SideSearch) -> None:
        self._clear_search_tags(widget)
        for start, end in search.matches:
            widget.tag_add("search_hit", start, end)
        if 0 <= search.current < len(search.matches):
            start, end = search.matches[search.current]
            widget.tag_add("search_current", start, end)
            widget.mark_set(tk.INSERT, end)
            widget.see(start)
        total = len(search.matches)
        if total == 0:
            search.count_var.set("0/0")
        else:
            search.count_var.set(f"{search.current + 1}/{total}")

    def _ensure_matches(self, side: str) -> SideSearch:
        widget, search = self._side_objects(side)
        needle = search.query.get()
        if needle != search.last_query:
            search.matches = self._collect_matches(widget, needle)
            search.last_query = needle
            search.current = -1
        return search

    def _search_next(self, side: str) -> None:
        widget, search = self._side_objects(side)
        self._ensure_matches(side)
        if not search.matches:
            search.count_var.set("0/0")
            self._clear_search_tags(widget)
            return
        search.current = (search.current + 1) % len(search.matches)
        self._apply_search_highlights(widget, search)

    def _search_prev(self, side: str) -> None:
        widget, search = self._side_objects(side)
        self._ensure_matches(side)
        if not search.matches:
            search.count_var.set("0/0")
            self._clear_search_tags(widget)
            return
        if search.current < 0:
            search.current = len(search.matches) - 1
        else:
            search.current = (search.current - 1) % len(search.matches)
        self._apply_search_highlights(widget, search)

    def _clear_left(self) -> None:
        self.left_text.delete("1.0", tk.END)
        self._reset_search("left")

    def _clear_right(self) -> None:
        self.right_text.delete("1.0", tk.END)
        self._reset_search("right")

    def _parse_ignore_options(self) -> tuple[int | None, str | None]:
        """Return (skip_chars, skip_marker); both None when ignore is off."""
        if not self._ignore_ts.get():
            return None, None

        mode = self._ignore_mode.get()
        if mode == "marker":
            marker = self._skip_marker.get()
            if marker == "":
                raise ValueError("分隔字串不可為空")
            return None, marker

        raw = self._skip_n.get().strip()
        try:
            n = int(raw)
        except ValueError as exc:
            raise ValueError("N 必須是非負整數") from exc
        if n < 0:
            raise ValueError("N 必須是非負整數")
        return n, None

    def _compare(self) -> None:
        if self._comparing:
            return
        try:
            skip_chars, skip_marker = self._parse_ignore_options()
        except ValueError as exc:
            messagebox.showerror("參數錯誤", str(exc))
            return

        left_raw = self.left_text.get("1.0", "end-1c")
        right_raw = self.right_text.get("1.0", "end-1c")

        self._comparing = True
        self._compare_btn.configure(state=tk.DISABLED)
        self._progress_var.set(0.0)
        self._status_var.set("開始比對…")

        def worker() -> None:
            try:

                def on_progress(value: float, message: str) -> None:
                    self._event_queue.put(("progress", value, message))

                result = compare_logs(
                    left_raw,
                    right_raw,
                    skip_chars=skip_chars,
                    skip_marker=skip_marker,
                    progress=on_progress,
                )
                self._event_queue.put(("done", result))
            except Exception as exc:  # noqa: BLE001 - show any worker failure in UI
                self._event_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            while True:
                event = self._event_queue.get_nowait()
                kind = event[0]
                if kind == "progress":
                    _, value, message = event
                    self._progress_var.set(value)
                    self._status_var.set(message)
                elif kind == "done":
                    _, result = event
                    self._render_result(result)
                    self._progress_var.set(100.0)
                    self._status_var.set("完成")
                    self._comparing = False
                    self._compare_btn.configure(state=tk.NORMAL)
                elif kind == "error":
                    _, message = event
                    self._status_var.set("比對失敗")
                    self._comparing = False
                    self._compare_btn.configure(state=tk.NORMAL)
                    messagebox.showerror("比對失敗", message)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    def _render_result(self, result: DiffResult) -> None:
        self._fill_side(self.left_text, result.left)
        self._fill_side(self.right_text, result.right)
        self._reset_search("left")
        self._reset_search("right")
        self.left_text.yview_moveto(0)
        self.right_text.yview_moveto(0)

    def _fill_side(self, widget: tk.Text, lines: list[AlignedLine]) -> None:
        widget.delete("1.0", tk.END)
        if not lines:
            return

        display_parts: list[str] = []
        for line in lines:
            if line.is_gap:
                # Space keeps the gap row visible so background tag can show.
                display_parts.append(" ")
            else:
                display_parts.append(line.text)
        widget.insert("1.0", "\n".join(display_parts))

        for idx, line in enumerate(lines):
            line_no = idx + 1
            if line.is_gap:
                widget.tag_add("gap_line", f"{line_no}.0", f"{line_no}.end")
                continue
            for span in line.spans:
                widget.tag_add(
                    span.tag,
                    f"{line_no}.{span.start}",
                    f"{line_no}.{span.end}",
                )


def main() -> None:
    app = LogDiffApp()
    app.mainloop()


if __name__ == "__main__":
    main()
