param([Parameter(Mandatory=$true)][string]$InputPath,[Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
if (Test-Path -LiteralPath $OutputPath) { throw 'Use a new raster path.' }
$source=$null;$bitmap=$null;$graphics=$null
try {
    $source=[Drawing.Image]::FromFile([IO.Path]::GetFullPath($InputPath))
    $scale=[Math]::Min(1.0,3200.0/[Math]::Max($source.Width,$source.Height))
    $width=[Math]::Max(1,[int]($source.Width*$scale));$height=[Math]::Max(1,[int]($source.Height*$scale))
    $bitmap=[Drawing.Bitmap]::new($width,$height)
    $graphics=[Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([Drawing.Color]::White)
    $graphics.DrawImage($source,0,0,$width,$height)
    $bitmap.Save([IO.Path]::GetFullPath($OutputPath),[Drawing.Imaging.ImageFormat]::Png)
} finally {
    if($graphics){$graphics.Dispose()};if($bitmap){$bitmap.Dispose()};if($source){$source.Dispose()}
}
