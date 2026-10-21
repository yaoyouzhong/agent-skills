param(
    [Parameter(Mandatory=$true)][ValidateSet('ConvertWord','ConvertExcel','RenderWord','RenderExcel')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$InputPath,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [string]$SheetName
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$sourcePath = (Resolve-Path -LiteralPath $InputPath).Path
$destPath = [IO.Path]::GetFullPath($OutputPath)
if ($sourcePath -eq $destPath -or (Test-Path -LiteralPath $destPath)) { throw 'Output must be a new file, distinct from the source.' }
if (-not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($destPath)))) { throw 'Output parent does not exist.' }
$app = $null
$document = $null
$originalUpdateLinks = $null
$noSave = [object]0
try {
    if ($Mode -in @('ConvertExcel','RenderExcel')) {
        $app = New-Object -ComObject Excel.Application
        $app.Visible = $false
        $app.DisplayAlerts = $false
        $app.AutomationSecurity = 3
        $app.AskToUpdateLinks = $false
        $document = $app.Workbooks.Open($sourcePath, 0, $true)
        $document.CheckCompatibility = $false
        if ($Mode -eq 'RenderExcel') {
            if (-not $SheetName) { throw 'RenderExcel requires the selected target sheet.' }
            $worksheet=$document.Worksheets.Item($SheetName)
            $worksheet.ExportAsFixedFormat(0,$destPath)
            [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($worksheet)
        } else { $document.SaveAs($destPath, 51) }
    } else {
        $app = New-Object -ComObject Word.Application
        $app.Visible = $false
        $app.DisplayAlerts = 0
        $app.AutomationSecurity = 3
        $originalUpdateLinks = $app.Options.UpdateLinksAtOpen
        $app.Options.UpdateLinksAtOpen = $false
        $document = $app.Documents.Open($sourcePath, $false, $true, $false)
        if ($Mode -eq 'RenderWord') { $document.ExportAsFixedFormat($destPath, 17) }
        else { $wordFormat = [object]16; $document.SaveAs2([ref]$destPath, [ref]$wordFormat) }
    }
} finally {
    if ($null -ne $document) {
        if ($Mode -in @('ConvertExcel','RenderExcel')) { $document.Close($false) } else { $document.Close([ref]$noSave) }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
    }
    if ($null -ne $app) {
        if ($null -ne $originalUpdateLinks) { $app.Options.UpdateLinksAtOpen = $originalUpdateLinks }
        if ($Mode -in @('ConvertExcel','RenderExcel')) { $app.Quit() } else { $app.Quit([ref]$noSave) }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($app)
    }
}
if (-not (Test-Path -LiteralPath $destPath)) { throw 'Office did not produce the requested file.' }
Write-Output $destPath
