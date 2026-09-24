using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
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
        Application.Run(new DesktopWindow(root, smoke));
    }
}

internal sealed class DesktopWindow : Form
{
    readonly string root;
    readonly bool smoke;
    readonly Label status = new() { Dock = DockStyle.Top, Height = 32, Text = "正在启动本地服务…", TextAlign = ContentAlignment.MiddleLeft };
    readonly WebView2 web = new() { Dock = DockStyle.Fill };
    readonly HttpClient http = new(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(4) };
    Process? backend;
    Process? setup;
    JsonElement state;
    string address = "";
    bool closing;
    CoreWebView2Environment? environment;

    public DesktopWindow(string root, bool smoke)
    {
        this.root = root; this.smoke = smoke;
        Text = "拾页 · 小说书单"; Width = 1280; Height = 850;
        MinimumSize = new Size(760, 540);
        Font = new Font("Microsoft YaHei UI", 9F);
        BackColor = Color.FromArgb(246, 247, 249); StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(web); Controls.Add(status);
        if (smoke) { WindowState = FormWindowState.Minimized; ShowInTaskbar = false; }
        Shown += async (_, _) => await StartAsync();
        FormClosing += OnClosing;
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
        var answer = MessageBox.Show(this,
            "首次使用或更新需要下载私有 Python 和依赖，全部保存到程序目录的 .runtime 中。不会修改系统 PATH 或注册开机启动。是否允许安装？",
            "准备本地运行环境", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
        if (answer != DialogResult.Yes) throw new OperationCanceledException("已取消安装。");
        status.Text = "正在准备环境，首次下载可能需要几分钟…";
        var info = new ProcessStartInfo("powershell.exe") { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (string arg in new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", Path.Combine(root, "scripts", "launcher.ps1"), "-Mode", "setup" }) info.ArgumentList.Add(arg);
        using var process = Process.Start(info) ?? throw new IOException("无法启动环境安装程序。");
        setup = process;
        var output = process.StandardOutput.ReadToEndAsync(); var error = process.StandardError.ReadToEndAsync();
        await process.StandardInput.WriteLineAsync("y"); process.StandardInput.Close();
        await process.WaitForExitAsync();
        string log = await output + "\n" + await error;
        setup = null;
        Directory.CreateDirectory(Path.Combine(root, ".local", "logs"));
        await File.WriteAllTextAsync(Path.Combine(root, ".local", "logs", "desktop-setup.log"), log);
        if (process.ExitCode != 0) throw new IOException("环境准备失败，请查看 .local/logs/desktop-setup.log。");
    }

    async Task StartAsync()
    {
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
            environment = await CoreWebView2Environment.CreateAsync(userDataFolder: Path.Combine(root, ".local", "webview2"));
            await web.EnsureCoreWebView2Async(environment);
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
                status.Visible = !e.IsSuccess;
                status.Text = e.IsSuccess ? "本机运行 · 数据保存在程序目录" : "页面加载失败，可关闭后重新打开。";
                if (smoke)
                {
                    await File.WriteAllTextAsync(Path.Combine(root, ".local", "desktop-smoke.json"),
                        JsonSerializer.Serialize(new { success = e.IsSuccess, address, runtime = environment.BrowserVersionString }));
                    Close();
                }
            };
            web.Source = new Uri(address);
        }
        catch (Exception error)
        {
            if (!smoke) MessageBox.Show(this, error.Message, "拾页", MessageBoxButtons.OK, MessageBoxIcon.Information);
            else
            {
                Directory.CreateDirectory(Path.Combine(root, ".local"));
                await File.WriteAllTextAsync(Path.Combine(root, ".local", "desktop-smoke.json"), JsonSerializer.Serialize(new { success = false, error = error.Message }));
            }
            Close();
        }
    }

    async Task SaveLogAsync(StreamReader reader, string name)
    {
        await using var writer = new StreamWriter(Path.Combine(root, ".local", "logs", name), false);
        while (await reader.ReadLineAsync() is string line) { await writer.WriteLineAsync(line); await writer.FlushAsync(); }
    }
    static void OpenExternal(string value)
    {
        if (Uri.TryCreate(value, UriKind.Absolute, out var url) && url.Scheme is "http" or "https")
            Process.Start(new ProcessStartInfo(value) { UseShellExecute = true });
    }
    async void OnClosing(object? sender, FormClosingEventArgs e)
    {
        if (closing) return;
        if (setup is { HasExited: false }) setup.Kill(entireProcessTree: true);
        if (backend is { HasExited: false })
        {
            e.Cancel = true; closing = true; status.Text = "正在停止本次启动的服务…";
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
        web.Dispose(); http.Dispose();
    }
}
