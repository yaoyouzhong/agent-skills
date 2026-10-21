param([Parameter(Mandatory=$true)][string]$Source,
      [Parameter(Mandatory=$true)][string]$Destination,
      [Parameter(Mandatory=$true)][int]$TableIndex)
$ErrorActionPreference='Stop'
if (Test-Path -LiteralPath $Destination) { throw 'Use a new template destination.' }
if ($TableIndex -lt 0) { throw 'TableIndex is zero based and must be nonnegative.' }
$app=$null;$doc=$null;$new=$null;$noSave=[object]0
try {
 $app=New-Object -ComObject Word.Application
 $app.Visible=$false;$app.DisplayAlerts=0;$app.AutomationSecurity=3
 $doc=$app.Documents.Open($Source,$false,$true,$false)
 if($TableIndex -ge $doc.Tables.Count){throw 'Selected table does not exist.'}
 $new=$app.Documents.Add();$new.TrackRevisions=$false
 $new.Content.FormattedText=$doc.Tables.Item($TableIndex+1).Range.FormattedText
 foreach($property in @('TopMargin','BottomMargin','LeftMargin','RightMargin','PageWidth','PageHeight','HeaderDistance','FooterDistance')) {
   $new.PageSetup.$property=$doc.PageSetup.$property
 }
 $fmt=[object]16;$new.SaveAs2([ref]$Destination,[ref]$fmt)
} finally {
 if($new){$new.Close([ref]$noSave);[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($new)}
 if($doc){$doc.Close([ref]$noSave);[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($doc)}
 if($app){$app.Quit([ref]$noSave);[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($app)}
}
