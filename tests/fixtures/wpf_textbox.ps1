# A WPF window with a focused text box (no Win32 caret), for tests/test_caret.py.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File wpf_textbox.ps1 <seconds> [password]
# With "password" the window holds a WPF PasswordBox instead (tests/test_redteam.py, R159).
param([int]$Seconds = 15, [string]$Kind = "text")
Add-Type -AssemblyName PresentationFramework
$w = New-Object System.Windows.Window
$w.Title = "PF caret test"
$w.Width = 500; $w.Height = 200; $w.Left = 200; $w.Top = 200
$w.Topmost = $true
if ($Kind -eq "password") {
    $tb = New-Object System.Windows.Controls.PasswordBox
    $tb.FontSize = 20
    $w.Content = $tb
    $w.Add_ContentRendered({ $w.Activate() | Out-Null; $tb.Focus() | Out-Null })
} else {
    $tb = New-Object System.Windows.Controls.TextBox
    $tb.Text = "hello caret"
    $tb.FontSize = 20
    $w.Content = $tb
    $w.Add_ContentRendered({ $w.Activate() | Out-Null; $tb.Focus() | Out-Null; $tb.CaretIndex = 5 })
}
$t = New-Object System.Windows.Threading.DispatcherTimer
$t.Interval = [TimeSpan]::FromSeconds($Seconds)
$t.Add_Tick({ $w.Close() })
$t.Start()
$w.ShowDialog() | Out-Null
