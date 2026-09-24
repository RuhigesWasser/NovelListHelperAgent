using System.Text.Json;
using Microsoft.Win32;

namespace ShiyeDesktop;

internal sealed record WindowPlacement(int X, int Y, int Width, int Height, int Dpi, bool Maximized);

internal static class DesktopPreferences
{
    public static WindowPlacement? ReadWindow(string root)
    {
        try { return JsonSerializer.Deserialize<WindowPlacement>(File.ReadAllText(Path.Combine(root, ".local", "desktop-window.json"))); }
        catch (Exception error) when (error is IOException or JsonException or UnauthorizedAccessException) { return null; }
    }

    public static void SaveWindow(string root, WindowPlacement placement)
    {
        string directory = Path.Combine(root, ".local"); Directory.CreateDirectory(directory);
        string path = Path.Combine(directory, "desktop-window.json"), temp = path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(placement)); File.Move(temp, path, true);
    }

    public static string ReadTheme(string root)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, ".local", "ui-settings.json")));
            string? value = document.RootElement.GetProperty("theme").GetString();
            return value is "dark" or "light" ? value : "system";
        }
        catch (Exception error) when (error is IOException or JsonException or KeyNotFoundException or UnauthorizedAccessException) { return "system"; }
    }

    public static bool IsDark(string theme)
    {
        if (theme != "system") return theme == "dark";
        using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
        return key?.GetValue("AppsUseLightTheme") is int value && value == 0;
    }
}
