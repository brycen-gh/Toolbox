Add-Type -AssemblyName System.Drawing
$destination = Join-Path $PSScriptRoot '../assets/icons/stop.png'
if (Test-Path -LiteralPath $destination) { throw "Refusing to replace $destination" }
$canvas = [Drawing.Bitmap]::new(512,512)
$graphics = [Drawing.Graphics]::FromImage($canvas)
$graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.ScaleTransform(4,4)
$rectangle = [Drawing.Rectangle]::new(24,24,80,80)
$brush = [Drawing.Drawing2D.LinearGradientBrush]::new($rectangle,[Drawing.ColorTranslator]::FromHtml('#81e5ff'),[Drawing.ColorTranslator]::FromHtml('#008fee'),90)
$outline = [Drawing.Pen]::new([Drawing.ColorTranslator]::FromHtml('#082c50'),4)
$graphics.FillRectangle($brush,$rectangle)
$graphics.DrawRectangle($outline,$rectangle)
$small = [Drawing.Bitmap]::new(128,128)
$scaled = [Drawing.Graphics]::FromImage($small)
$scaled.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$scaled.DrawImage($canvas,0,0,128,128)
$small.Save($destination,[Drawing.Imaging.ImageFormat]::Png)
$scaled.Dispose()
$small.Dispose()
$outline.Dispose()
$brush.Dispose()
$graphics.Dispose()
$canvas.Dispose()
