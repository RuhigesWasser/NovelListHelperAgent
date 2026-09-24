using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace ShiyeDesktop;

internal static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        string root = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        int option = Array.IndexOf(args, "--root");
        if (option >= 0 && option + 1 < args.Length) root = Path.GetFullPath(args[option + 1]);
        bool smoke = args.Contains("--smoke");
        string? preview = args.FirstOrDefault(arg => arg.StartsWith("--startup-preview="))?.Split('=', 2)[1];
        Application.Run(new DesktopWindow(root, smoke, preview));
    }
}

internal sealed class DesktopWindow : Form
{
    readonly string root;
    readonly bool smoke;
    readonly StartupView startup = new();
    readonly string? preview;
    bool starting, attempted, webConfigured, restoreMaximized;
    WebView2 web = new() { Dock = DockStyle.Fill };
    readonly HttpClient http = new(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(4) };
    Process? backend;
    Process? setup;
    JsonElement state;
    string address = "";
    bool closing;
    FormWindowState lastWindowState = FormWindowState.Normal;
    string theme = "system";
    [DllImport("dwmapi.dll")]
    static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);
    CoreWebView2Environment? environment;

    public DesktopWindow(string root, bool smoke, string? preview = null)
    {
        this.root = root; this.smoke = smoke; this.preview = preview;
        Text = "拾页"; Width = 1280; Height = 850;
        MinimumSize = new Size(760, 540);
        Font = new Font("Microsoft YaHei UI", 9F);
        BackColor = Color.FromArgb(246, 247, 249); StartPosition = FormStartPosition.Manual;
        theme = DesktopPreferences.ReadTheme(root);
        HandleCreated += (_, _) => { if ((!smoke && preview == null) || preview == "window") RestorePlacement(); ApplyTheme(); };
        Resize += (_, _) => { if (WindowState != FormWindowState.Minimized) lastWindowState = WindowState; };
        SystemEvents.UserPreferenceChanged += SystemThemeChanged;
        Controls.Add(web); Controls.Add(startup); startup.BringToFront();
        startup.RetryRequested += async (_, _) => await StartAsync();
        startup.OpenLogsRequested += (_, _) => {
            string logs = Path.Combine(root, ".local", "logs");
            Directory.CreateDirectory(logs);
            Process.Start(new ProcessStartInfo(logs) { UseShellExecute = true });
        };
        if (smoke) { if (preview == null) WindowState = FormWindowState.Minimized; ShowInTaskbar = false; }
        Shown += async (_, _) => { if (restoreMaximized) WindowState = FormWindowState.Maximized; if (preview != null) await PreviewAsync(); else await StartAsync(); };
        FormClosed += (_, _) => { SystemEvents.UserPreferenceChanged -= SystemThemeChanged; http.Dispose(); backend?.Dispose(); };
        FormClosing += OnClosing;
    }

    void RestorePlacement()
    {
        var saved = DesktopPreferences.ReadWindow(root);
        var screen = saved == null ? Screen.FromPoint(Cursor.Position) : Screen.FromRectangle(new Rectangle(saved.X, saved.Y, Math.Max(1, saved.Width), Math.Max(1, saved.Height)));
        Rectangle area = screen.WorkingArea;
        double scale = saved != null && saved.Dpi > 0 ? (double)DeviceDpi / saved.Dpi : 1;
        int width = saved == null ? (int)(area.Width * .92) : (int)(saved.Width * scale);
        int height = saved == null ? (int)(area.Height * .92) : (int)(saved.Height * scale);
        width = Math.Clamp(width, Math.Min(760, area.Width), area.Width);
        height = Math.Clamp(height, Math.Min(540, area.Height), area.Height);
        MinimumSize = new Size(Math.Min(760, area.Width), Math.Min(540, area.Height));
        int x = saved == null ? area.Left + (area.Width - width) / 2 : Math.Clamp(saved.X, area.Left, area.Right - width);
        int y = saved == null ? area.Top + (area.Height - height) / 2 : Math.Clamp(saved.Y, area.Top, area.Bottom - height);
        Bounds = new Rectangle(x, y, width, height);
        restoreMaximized = saved?.Maximized == true;
        if (restoreMaximized) WindowState = FormWindowState.Maximized;
    }

    void SystemThemeChanged(object sender, UserPreferenceChangedEventArgs e)
    {
        if (theme == "system" && IsHandleCreated && !closing) BeginInvoke(new Action(ApplyTheme));
    }

    void ApplyTheme()
    {
        bool dark = DesktopPreferences.IsDark(theme);
        BackColor = dark ? Color.FromArgb(32, 33, 32) : Color.White;
        startup.SetDark(dark); web.DefaultBackgroundColor = BackColor;
        if (IsHandleCreated) { int value = dark ? 1 : 0; DwmSetWindowAttribute(Handle, 20, ref value, sizeof(int)); }
        if (web.CoreWebView2 != null)
            web.CoreWebView2.Profile.PreferredColorScheme = theme == "dark" ? CoreWebView2PreferredColorScheme.Dark : theme == "light" ? CoreWebView2PreferredColorScheme.Light : CoreWebView2PreferredColorScheme.Auto;
    }

    async Task<bool> FindBackendAsync()
    {
        string file = Path.Combine(root, ".local", "server.json");
        if (!File.Exists(file)) return false;
        try
        {
            var value = JsonDocument.Parse(await File.ReadAllTextAsync(file)).RootElement.Clone();
            int port = value.GetProperty("port").GetInt32();
            if (port < 1 || port > 65535) return false;
            string url = $"http://127.0.0.1:{port}";
            var health = JsonDocument.Parse(await http.GetStringAsync(url + "/health"));
            if (health.RootElement.GetProperty("app").GetString() != "novel-list-helper") return false;
            state = value; address = url; return true;
        }
        catch (Exception e) when (e is IOException or HttpRequestException or TaskCanceledException or JsonException or KeyNotFoundException) { return false; }
    }

    bool RuntimeReady()
    {
        string file = Path.Combine(root, ".runtime", "ready.json");
        if (!File.Exists(file) || !File.Exists(PythonPath)) return false;
        try
        {
            var ready = JsonDocument.Parse(File.ReadAllText(file)).RootElement;
            string hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Path.Combine(root, "uv.lock"))))
                + Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Path.Combine(root, "pyproject.toml"))));
            return string.Equals(ready.GetProperty("root").GetString(), root, StringComparison.OrdinalIgnoreCase)
                && ready.GetProperty("hash").GetString() == hash;
        }
        catch (Exception e) when (e is IOException or JsonException or KeyNotFoundException) { return false; }
    }
    string PythonPath => Path.Combine(root, ".runtime", "venv", "Scripts", "python.exe");

    async Task SetupAsync()
    {
        if (smoke) throw new InvalidOperationException("Smoke test requires an existing ready backend/runtime.");
        startup.SetStage(1, "准备运行环境", "首次使用需要下载 Python 和依赖，全部保存在应用目录。");
        var answer = MessageBox.Show(this,
            "首次使用或更新需要下载私有 Python 和依赖，全部保存到程序目录的 .runtime 中。不会修改系统 PATH 或注册开机启动。是否允许安装？",
            "准备本地运行环境", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
        if (answer != DialogResult.Yes) throw new OperationCanceledException("已取消安装。");
        startup.SetStage(1, "正在准备运行环境", "首次下载可能需要几分钟。完成后会自动打开书库。");
        var info = new ProcessStartInfo("powershell.exe") { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (string arg in new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", Path.Combine(root, "scripts", "launcher.ps1"), "-Mode", "setup" }) info.ArgumentList.Add(arg);
        using var process = Process.Start(info) ?? throw new IOException("无法启动环境安装程序。");
        setup = process;
        Directory.CreateDirectory(Path.Combine(root, ".local", "logs"));
        try
        {
        var output = SaveLogAsync(process.StandardOutput, "desktop-setup.out.log");
        var error = SaveLogAsync(process.StandardError, "desktop-setup.err.log");
        await process.StandardInput.WriteLineAsync("y"); process.StandardInput.Close();
        await process.WaitForExitAsync();
        await Task.WhenAll(output, error);
        if (process.ExitCode != 0) throw new IOException("环境准备未完成。请查看启动日志，检查网络连接后重试。");
        }
        finally { setup = null; }
    }

    async Task PreviewAsync()
    {
        startup.SetStage(1, "正在准备运行环境", "首次下载可能需要几分钟。完成后会自动打开书库。");
        startup.AppendLog("界面预览，不执行下载或安装。");
        if (preview == "error") startup.ShowError("无法连接下载服务器。请检查网络连接后重试。");
        if (!smoke) return;
        await Task.Delay(200);
        Directory.CreateDirectory(Path.Combine(root, ".local"));
        if (preview == "window")
        {
            Rectangle bounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
            var placement = new WindowPlacement(bounds.X, bounds.Y, bounds.Width, bounds.Height, DeviceDpi, WindowState == FormWindowState.Maximized);
            await File.WriteAllTextAsync(Path.Combine(root, ".local", "desktop-window-check.json"), JsonSerializer.Serialize(new { placement, workArea = Screen.FromControl(this).WorkingArea }));
            DesktopPreferences.SaveWindow(root, placement);
        }
        using var bitmap = new Bitmap(startup.Width, startup.Height);
        startup.DrawToBitmap(bitmap, startup.ClientRectangle);
        bitmap.Save(Path.Combine(root, ".local", "desktop-startup-" + (preview == "error" ? "error" : "setup") + ".png"));
        Close();
    }

    async Task StartAsync()
    {
        if (starting || closing) return;
        starting = true; startup.Visible = true; startup.BringToFront(); startup.Begin();
        if (attempted && web.CoreWebView2 == null)
        {
            Controls.Remove(web); web.Dispose(); web = new WebView2 { Dock = DockStyle.Fill };
            Controls.Add(web); startup.BringToFront(); webConfigured = false;
        }
        attempted = true;
        try
        {
            if (!File.Exists(Path.Combine(root, "app", "main.py"))) throw new IOException("应用文件不完整，请解压完整发行包。");
            try { CoreWebView2Environment.GetAvailableBrowserVersionString(); }
            catch (WebView2RuntimeNotFoundException)
            {
                throw new InvalidOperationException("缺少 Microsoft Edge WebView2 Runtime。请安装微软共享运行环境，或使用 Start.cmd 的浏览器模式。");
            }
            if (!await FindBackendAsync())
            {
                if (!RuntimeReady()) await SetupAsync();
                if (closing) return;
                if (backend is { HasExited: false }) { backend.Kill(entireProcessTree: true); await backend.WaitForExitAsync(); }
                backend?.Dispose(); backend = null;
                startup.SetStage(2, "正在启动本地服务", "连接本机服务，书籍和任务记录将自动载入。");
                Directory.CreateDirectory(Path.Combine(root, ".local", "logs"));
                var info = new ProcessStartInfo(PythonPath) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true };
                foreach (string arg in new[] { "-B", "-m", "app.main", "--no-browser" }) info.ArgumentList.Add(arg);
                info.Environment["PYTHONUTF8"] = "1"; info.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
                backend = Process.Start(info) ?? throw new IOException("无法启动后端。");
                _ = SaveLogAsync(backend.StandardOutput, "desktop-server.out.log");
                _ = SaveLogAsync(backend.StandardError, "desktop-server.err.log");
                for (int i = 0; i < 120 && !backend.HasExited; i++)
                {
                    if (await FindBackendAsync()) break;
                    await Task.Delay(250);
                }
                if (address == "") throw new IOException("本地服务启动失败，请查看 .local/logs 中的日志。");
            }
            if (closing) return;
            startup.SetStage(3, "正在打开书库", "环境已就绪，正在加载应用界面。");
            environment = await CoreWebView2Environment.CreateAsync(userDataFolder: Path.Combine(root, ".local", "webview2"));
            await web.EnsureCoreWebView2Async(environment);
            if (closing) return;
            if (!webConfigured)
            {
            webConfigured = true;
            ApplyTheme();
            web.CoreWebView2.WebMessageReceived += (_, e) =>
            {
                if (!e.Source.StartsWith(address + "/", StringComparison.OrdinalIgnoreCase)) return;
                try
                {
                    using var data = JsonDocument.Parse(e.WebMessageAsJson);
                    if (data.RootElement.GetProperty("type").GetString() != "appearance") return;
                    var choice = data.RootElement.GetProperty("theme").GetString();
                    if (choice is "system" or "light" or "dark") { theme = choice; ApplyTheme(); }
                }
                catch (Exception error) when (error is JsonException or KeyNotFoundException or InvalidOperationException) { }
            };
            web.CoreWebView2.Settings.IsPasswordAutosaveEnabled = false;
            web.CoreWebView2.Settings.IsGeneralAutofillEnabled = false;
            web.CoreWebView2.NavigationStarting += (_, e) =>
            {
                if (!e.Uri.StartsWith(address + "/", StringComparison.OrdinalIgnoreCase) && e.Uri != address)
                { e.Cancel = true; OpenExternal(e.Uri); }
            };
            web.CoreWebView2.NewWindowRequested += async (_, e) =>
            {
                if (e.Uri.StartsWith("blob:" + address, StringComparison.OrdinalIgnoreCase))
                {
                    var pending = e.GetDeferral();
                    try
                    {
                    var window = new Form { Text = "原图", Width = 900, Height = 800 };
                    var image = new WebView2 { Dock = DockStyle.Fill }; window.Controls.Add(image); window.Show(this);
                    await image.EnsureCoreWebView2Async(environment); e.NewWindow = image.CoreWebView2; e.Handled = true;
                    window.FormClosed += (_, _) => image.Dispose();
                    }
                    finally { pending.Complete(); }
                }
                else { e.Handled = true; OpenExternal(e.Uri); }
            };
            web.CoreWebView2.NavigationCompleted += async (_, e) =>
            {
                if (closing) return;
                if (e.IsSuccess) { startup.Complete(); web.BringToFront(); }
                else startup.ShowError("页面未能加载。可以重试，或打开日志目录查看详情。");
                if (smoke)
                {
                    await File.WriteAllTextAsync(Path.Combine(root, ".local", "desktop-smoke.json"),
                        JsonSerializer.Serialize(new { success = e.IsSuccess, address, runtime = environment.BrowserVersionString }));
                    Close();
                }
            };
            }
            web.CoreWebView2.Navigate(address);
        }
        catch (Exception error)
        {
            if (closing) return;
            if (!smoke) startup.ShowError(error.Message);
            else
            {
                Directory.CreateDirectory(Path.Combine(root, ".local"));
                await File.WriteAllTextAsync(Path.Combine(root, ".local", "desktop-smoke.json"), JsonSerializer.Serialize(new { success = false, error = error.Message }));
            }
            if (smoke) Close();
        }
        finally { starting = false; }
    }

    async Task SaveLogAsync(StreamReader reader, string name)
    {
        await using var writer = new StreamWriter(Path.Combine(root, ".local", "logs", name), false);
        while (await reader.ReadLineAsync() is string line)
        {
            await writer.WriteLineAsync(line); await writer.FlushAsync();
            if (!closing && !startup.IsDisposed) startup.AppendLog(line);
        }
    }
    static void OpenExternal(string value)
    {
        if (Uri.TryCreate(value, UriKind.Absolute, out var url) && url.Scheme is "http" or "https")
            Process.Start(new ProcessStartInfo(value) { UseShellExecute = true });
    }
    async void OnClosing(object? sender, FormClosingEventArgs e)
    {
        if (closing) return;
        if (!smoke && preview == null)
        {
            Rectangle bounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
            try { DesktopPreferences.SaveWindow(root, new WindowPlacement(bounds.X, bounds.Y, bounds.Width, bounds.Height, DeviceDpi, lastWindowState == FormWindowState.Maximized)); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { startup.AppendLog("窗口尺寸未能保存：" + error.Message); }
        }
        closing = true;
        if (setup is { HasExited: false }) setup.Kill(entireProcessTree: true);
        if (backend is { HasExited: false })
        {
            e.Cancel = true; startup.Visible = true; startup.BringToFront();
            startup.SetStage(2, "正在退出拾页", "正在停止本次启动的服务，已保存的内容会保留。");
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, address + "/api/shutdown");
                request.Headers.Add("X-Session-Token", state.GetProperty("token").GetString());
                using var response = await http.SendAsync(request);
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(75));
                await backend.WaitForExitAsync(timeout.Token);
            }
            catch { if (!backend.HasExited) backend.Kill(entireProcessTree: true); }
            Close(); return;
        }

    }
}
