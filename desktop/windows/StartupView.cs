using System.Diagnostics;
using System.Drawing.Drawing2D;

namespace ShiyeDesktop;

internal sealed class StartupView : UserControl
{
    static readonly Color Accent = Color.FromArgb(34, 34, 34);
    readonly Panel card = new Surface();
    readonly Label logo = new() { Text = "拾", BackColor = Accent, ForeColor = Color.White, TextAlign = ContentAlignment.MiddleCenter };
    readonly Label brand = new() { Text = "拾页", ForeColor = Color.FromArgb(29, 42, 49) };
    readonly Label caption = new() { Text = "本地小说书库", ForeColor = Color.FromArgb(111, 123, 131) };
    readonly Label title = new() { ForeColor = Color.FromArgb(29, 42, 49) };
    readonly Label description = new() { ForeColor = Color.FromArgb(99, 112, 122) };
    readonly Label[] steps = new Label[4];
    readonly BusyBar progress = new();
    readonly Label elapsed = new() { ForeColor = Color.FromArgb(126, 137, 144) };
    readonly Label footnote = new() { Text = "运行环境和书库保存在应用目录", ForeColor = Color.FromArgb(126, 137, 144) };
    readonly Button details = new SoftButton() { Text = "查看启动日志" };
    readonly Button retry = new SoftButton() { Text = "重试", Visible = false };
    readonly Button folder = new SoftButton() { Text = "打开日志目录", Visible = false };
    readonly TextBox log = new() { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, BorderStyle = BorderStyle.None, BackColor = Color.FromArgb(245, 247, 248), ForeColor = Color.FromArgb(74, 87, 98), Visible = false };
    readonly System.Windows.Forms.Timer timer = new() { Interval = 1000 };
    readonly Stopwatch clock = new();
    bool expanded;
    public event EventHandler? RetryRequested;
    public event EventHandler? OpenLogsRequested;

    public StartupView()
    {
        Dock = DockStyle.Fill; AutoScroll = true; AutoScaleMode = AutoScaleMode.None;
        BackColor = Color.FromArgb(248, 248, 247);
        Font = new Font("Microsoft YaHei UI", 10F);
        logo.Font = new Font(Font.FontFamily, 18F, FontStyle.Bold);
        brand.Font = new Font(Font.FontFamily, 14F, FontStyle.Bold);
        caption.Font = new Font(Font.FontFamily, 9F);
        title.Font = new Font(Font.FontFamily, 16F, FontStyle.Bold);
        description.Font = new Font(Font.FontFamily, 10F);
        elapsed.Font = footnote.Font = new Font(Font.FontFamily, 9F);
        log.Font = new Font("Consolas", 9F);
        foreach (var button in new[] { details, retry, folder })
        {
            button.FlatStyle = FlatStyle.Flat; button.FlatAppearance.BorderSize = 0;
            button.BackColor = Color.FromArgb(241, 241, 240); button.ForeColor = Accent;
            button.Cursor = Cursors.Hand;
        }
        retry.BackColor = Accent; retry.ForeColor = Color.White;
        var names = new[] { "检查环境", "准备环境", "启动服务", "打开书库" };
        for (int i = 0; i < steps.Length; i++)
        {
            steps[i] = new Label { Text = $"{i + 1:00}  {names[i]}", TextAlign = ContentAlignment.MiddleLeft, Font = new Font(Font.FontFamily, 9F) };
            card.Controls.Add(steps[i]);
        }
        card.Controls.AddRange(new Control[] { logo, brand, caption, title, description, progress, elapsed, details, retry, folder, log, footnote });
        Controls.Add(card);
        details.Click += (_, _) => { expanded = !expanded; log.Visible = expanded; details.Text = expanded ? "收起日志" : "查看启动日志"; Arrange(); };
        retry.Click += (_, _) => RetryRequested?.Invoke(this, EventArgs.Empty);
        folder.Click += (_, _) => OpenLogsRequested?.Invoke(this, EventArgs.Empty);
        timer.Tick += (_, _) => elapsed.Text = $"已用时 {clock.Elapsed:mm\\:ss}";
        Begin();
    }

    int S(int value) => (int)Math.Round(value * DeviceDpi / 96.0);
    protected override void OnResize(EventArgs e) { base.OnResize(e); if (card != null) Arrange(); }
    protected override void OnDpiChangedAfterParent(EventArgs e) { base.OnDpiChangedAfterParent(e); Arrange(); }
    void Arrange()
    {
        int width = Math.Min(S(560), Math.Max(S(300), ClientSize.Width - S(32)));
        int height = S(expanded ? 365 : 288);
        AutoScrollMinSize = new Size(0, height + S(24));
        card.SetBounds(Math.Max(S(12), (ClientSize.Width - width) / 2), Math.Max(S(12), (ClientSize.Height - height) / 2) + AutoScrollPosition.Y, width, height);
        int left = S(26), inner = width - left * 2;
        logo.SetBounds(left, S(22), S(36), S(36));
        brand.SetBounds(left + S(49), S(18), inner - S(49), S(27));
        caption.SetBounds(left + S(50), S(43), inner - S(50), S(22));
        title.SetBounds(left, S(79), inner, S(34));
        description.SetBounds(left, S(119), inner, S(38));
        for (int i = 0; i < steps.Length; i++) steps[i].SetBounds(left + inner * i / 4, S(165), inner / 4, S(25));
        progress.SetBounds(left, S(195), inner, S(3));
        elapsed.SetBounds(left, S(205), inner, S(22));
        details.SetBounds(left, S(235), S(110), S(30));
        folder.SetBounds(left + S(119), S(235), S(123), S(30));
        retry.SetBounds(width - left - S(78), S(235), S(78), S(30));
        log.SetBounds(left, S(275), inner, S(65));
        footnote.SetBounds(left, height - S(22), inner, S(20));
    }

    public void Begin()
    {
        clock.Restart(); timer.Start(); elapsed.Text = "已用时 00:00";
        retry.Visible = folder.Visible = false; progress.Running = true;
        log.Clear(); SetStage(0, "正在启动拾页", "检查运行环境，随后打开本地书库。");
    }
    public void SetStage(int current, string heading, string note)
    {
        title.Text = heading; description.Text = note;
        for (int i = 0; i < steps.Length; i++) steps[i].ForeColor = i <= current ? Accent : Color.FromArgb(155, 164, 171);
        AppendLog(heading);
    }
    public void AppendLog(string line)
    {
        if (IsDisposed) return;
        if (log.TextLength > 24000) log.Text = log.Text[^16000..];
        log.AppendText(line + Environment.NewLine);
    }
    public void ShowError(string message)
    {
        timer.Stop(); clock.Stop(); title.Text = "暂时无法打开拾页";
        description.Text = message; progress.Running = false;
        retry.Visible = folder.Visible = true; AppendLog(message);
        expanded = true; log.Visible = true; details.Text = "收起日志"; Arrange();
    }
    public void Complete() { timer.Stop(); clock.Stop(); progress.Running = false; Visible = false; }
    protected override void Dispose(bool disposing)
    {
        if (disposing) timer.Dispose();
        base.Dispose(disposing);
    }

    static GraphicsPath Rounded(Rectangle bounds, int radius)
    {
        var path = new GraphicsPath(); int d = radius * 2;
        path.AddArc(bounds.Left, bounds.Top, d, d, 180, 90);
        path.AddArc(bounds.Right - d, bounds.Top, d, d, 270, 90);
        path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
        path.AddArc(bounds.Left, bounds.Bottom - d, d, d, 90, 90);
        path.CloseFigure(); return path;
    }

    sealed class Surface : Panel
    {
        public Surface() { DoubleBuffered = true; BackColor = Color.White; }
        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            if (Width < 24 || Height < 24) return;
            using var path = Rounded(ClientRectangle, 12 * DeviceDpi / 96);
            var old = Region; Region = new Region(path); old?.Dispose();
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e); e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using var path = Rounded(new Rectangle(0, 0, Width - 1, Height - 1), 12 * DeviceDpi / 96);
            using var pen = new Pen(Color.FromArgb(226, 226, 220)); e.Graphics.DrawPath(pen, path);
        }
    }

    sealed class SoftButton : Button
    {
        bool hover;
        public SoftButton() { SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true); }
        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Parent?.BackColor ?? Color.White); e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using var path = Rounded(new Rectangle(0, 0, Width - 1, Height - 1), 6 * DeviceDpi / 96);
            using var fill = new SolidBrush(hover ? ControlPaint.Dark(BackColor, .04f) : BackColor);
            e.Graphics.FillPath(fill, path);
            TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, ForeColor, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -5, -5));
        }
    }

    sealed class BusyBar : Control
    {
        readonly System.Windows.Forms.Timer animation = new() { Interval = 40 };
        int offset;
        bool running;
        public bool Running { get => running; set { running = value; animation.Enabled = value && Visible; Invalidate(); } }
        public BusyBar()
        {
            DoubleBuffered = true;
            animation.Tick += (_, _) => { offset = (offset + 7) % Math.Max(1, Width + Width / 3); Invalidate(); };
        }
        protected override void OnVisibleChanged(EventArgs e) { base.OnVisibleChanged(e); animation.Enabled = Visible && running; }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(Color.FromArgb(236, 236, 230));
            if (running) { using var brush = new SolidBrush(Color.FromArgb(91, 91, 82)); e.Graphics.FillRectangle(brush, offset - Width / 3, 0, Width / 3, Height); }
        }
        protected override void Dispose(bool disposing) { if (disposing) animation.Dispose(); base.Dispose(disposing); }
    }
}
