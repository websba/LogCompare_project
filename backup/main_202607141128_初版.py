"""Local Tkinter UI for side-by-side log comparison."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from diff_engine import AlignedLine, DiffResult, compare_logs

COLORS = {
    "match": "#c8e6c9",
    "mismatch": "#f8bbd0",
    "gap": "#eeeeee",
    "prefix": "#e0e0e0",
}


class LogDiffApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Log 左右比對工具")
        self.geometry("1100x700")
        self.minsize(800, 500)

        self._syncing_scroll = False
        self._ignore_ts = tk.BooleanVar(value=False)
        self._ignore_mode = tk.StringVar(value="marker")
        self._skip_n = tk.StringVar(value="19")
        self._skip_marker = tk.StringVar(value="[M:")

        self._build_ui()
        self._configure_tags(self.left_text)
        self._configure_tags(self.right_text)
        self._bind_scroll_sync()

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
        ttk.Button(toolbar, text="比對", command=self._compare).pack(side=tk.LEFT)

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left_frame = ttk.Frame(paned)
        right_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)
        paned.add(right_frame, weight=1)

        ttk.Label(left_frame, text="左：log1（可貼上）").pack(anchor=tk.W)
        ttk.Label(right_frame, text="右：log2（可貼上）").pack(anchor=tk.W)

        self.left_text = self._make_text(left_frame)
        self.right_text = self._make_text(right_frame)

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
        # Keep the source's own scrollbar in sync via the default set protocol.
        # We re-attach scrollbars in _make_text; update them here.
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
        # Windows / macOS use delta; X11 uses Button-4/5
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

    def _clear_left(self) -> None:
        self.left_text.delete("1.0", tk.END)

    def _clear_right(self) -> None:
        self.right_text.delete("1.0", tk.END)

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
        try:
            skip_chars, skip_marker = self._parse_ignore_options()
        except ValueError as exc:
            messagebox.showerror("參數錯誤", str(exc))
            return

        left_raw = self.left_text.get("1.0", "end-1c")
        right_raw = self.right_text.get("1.0", "end-1c")
        result = compare_logs(
            left_raw,
            right_raw,
            skip_chars=skip_chars,
            skip_marker=skip_marker,
        )
        self._render_result(result)

    def _render_result(self, result: DiffResult) -> None:
        self._fill_side(self.left_text, result.left)
        self._fill_side(self.right_text, result.right)
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
