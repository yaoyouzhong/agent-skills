param([Parameter(Mandatory=$true)][string]$InputPath,
      [Parameter(Mandatory=$true)][string]$OutputPath,
      [string]$Language='zh-Hans-CN')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime] | Out-Null
function Await-Operation($Operation,[Type]$ResultType) {
    $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    $task=$method.MakeGenericMethod($ResultType).Invoke($null,@($Operation))
    $task.GetAwaiter().GetResult()
}
if (Test-Path -LiteralPath $OutputPath) { throw 'Use a new OCR result path.' }
$file=Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync([IO.Path]::GetFullPath($InputPath))) ([Windows.Storage.StorageFile])
$stream=Await-Operation ($file.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
try {
    $decoder=Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap=Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    try {
        $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Language))
        if ($null -eq $engine) { throw "Installed Windows OCR language unavailable: $Language" }
        $result=Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines=@(foreach($line in $result.Lines) {
            @{text=$line.Text;words=@(foreach($word in $line.Words) {
                @{text=$word.Text;bbox=@($word.BoundingRect.X,$word.BoundingRect.Y,$word.BoundingRect.Width,$word.BoundingRect.Height)}
            })}
        })
        $value=@{engine='Windows.Media.Ocr';language=$Language;os_version=[Environment]::OSVersion.Version.ToString();
                 text=$result.Text;lines=$lines;confidence=$null;confidence_note='Windows OCR does not expose confidence scores.';
                 width=$bitmap.PixelWidth;height=$bitmap.PixelHeight;review_status='machine_unreviewed'}
        [IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputPath),($value | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
    } finally { if($bitmap){$bitmap.Dispose()} }
} finally { $stream.Dispose() }
