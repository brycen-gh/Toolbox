Add-Type -AssemblyName System.Drawing
$destination = Join-Path $PSScriptRoot '../assets/icons'
$navy = [Drawing.ColorTranslator]::FromHtml('#082c50')
$blue = [Drawing.ColorTranslator]::FromHtml('#008fee')
$cyan = [Drawing.ColorTranslator]::FromHtml('#81e5ff')
$white = [Drawing.ColorTranslator]::FromHtml('#e4faff')
$names = @('learning','chat','database','terminal','network','security','backup','logs','monitoring','automation','upload','folder','web','mail','key','replay')
function Box($x,$y,$w,$h) {
    $rect = [Drawing.Rectangle]::new($x,$y,$w,$h)
    $brush = [Drawing.Drawing2D.LinearGradientBrush]::new($rect,$cyan,$blue,90)
    $g.FillRectangle($brush,$rect); $g.DrawRectangle($outline,$rect); $brush.Dispose()
}
function Line($x,$y,$a,$b) { $g.DrawLine($ink,$x,$y,$a,$b) }
function Oval($x,$y,$w,$h) {
    $rect = [Drawing.Rectangle]::new($x,$y,$w,$h)
    $brush = [Drawing.Drawing2D.LinearGradientBrush]::new($rect,$cyan,$blue,90)
    $g.FillEllipse($brush,$rect); $g.DrawEllipse($outline,$rect); $brush.Dispose()
}
foreach ($name in $names) {
    $path = Join-Path $destination "$name.png"
    if (Test-Path -LiteralPath $path) { throw "Refusing to replace $path" }
    $canvas = [Drawing.Bitmap]::new(512,512)
    $g = [Drawing.Graphics]::FromImage($canvas)
    $g.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.ScaleTransform(4,4)
    $outline = [Drawing.Pen]::new($navy,4)
    $ink = [Drawing.Pen]::new($white,5)
    $ink.StartCap = $ink.EndCap = [Drawing.Drawing2D.LineCap]::Round
    switch ($name) {
        learning { Box 16 35 46 65; Box 62 35 46 65; Line 64 39 64 99; Line 25 49 51 49; Line 75 49 99 49; Line 25 65 51 65; Line 75 65 99 65 }
        chat { Box 15 23 81 61; Box 46 57 65 42; $g.FillPolygon([Drawing.SolidBrush]::new($blue),[Drawing.Point[]]@([Drawing.Point]::new(26,78),[Drawing.Point]::new(26,103),[Drawing.Point]::new(48,78))); Line 28 40 79 40; Line 28 56 68 56; Line 61 76 97 76 }
        database { Box 25 33 78 64; Oval 25 80 78 24; Oval 25 22 78 28; $g.DrawArc($ink,28,48,72,26,0,180); $g.DrawArc($ink,28,67,72,26,0,180) }
        terminal { Box 14 26 100 77; Line 29 46 46 61; Line 46 61 29 77; Line 60 79 91 79 }
        network { Line 64 45 64 76; Line 29 76 99 76; Line 29 76 29 90; Line 99 76 99 90; Box 43 18 42 31; Box 12 87 34 26; Box 82 87 34 26 }
        security { $points=[Drawing.Point[]]@([Drawing.Point]::new(64,14),[Drawing.Point]::new(105,31),[Drawing.Point]::new(98,79),[Drawing.Point]::new(64,113),[Drawing.Point]::new(30,79),[Drawing.Point]::new(23,31)); $g.FillPolygon([Drawing.SolidBrush]::new($blue),$points); $g.DrawPolygon($outline,$points); Line 43 61 58 77; Line 58 77 85 46 }
        backup { Box 19 58 90 46; $g.DrawArc($outline,31,16,67,68,190,260); $g.DrawArc($ink,31,16,67,68,190,250); Line 36 27 33 49; Line 33 49 52 43; Line 31 82 75 82; Oval 90 78 8 8 }
        logs { Box 30 15 70 99; Line 44 35 84 35; Line 44 53 84 53; Line 44 71 84 71; Line 44 89 72 89 }
        monitoring { Box 14 23 100 72; Line 44 108 84 108; Line 64 95 64 108; Line 25 65 42 65; Line 42 65 52 43; Line 52 43 66 80; Line 66 80 78 55; Line 78 55 103 55 }
        automation { Oval 23 32 82 65; Box 43 20 42 17; Line 64 20 64 12; Oval 38 49 13 13; Oval 77 49 13 13; Line 45 80 83 80; Box 12 51 11 25; Box 105 51 11 25 }
        upload { Box 23 85 82 24; Line 64 80 64 21; Line 64 21 42 44; Line 64 21 86 44 }
        folder { Box 16 28 45 24; Box 16 44 96 60; Line 27 56 98 56 }
        web { Oval 15 15 98 98; $g.DrawEllipse($ink,42,20,44,88); Line 20 64 108 64; $g.DrawArc($ink,20,28,88,35,0,180); $g.DrawArc($ink,20,66,88,35,180,180) }
        mail { Box 15 29 98 72; Line 20 35 64 69; Line 64 69 108 35; Line 20 95 46 73; Line 108 95 82 73 }
        key { Oval 17 24 49 49; Line 60 65 104 109; Line 89 94 103 80; Line 77 82 90 69; $g.FillEllipse([Drawing.SolidBrush]::new($navy),31,38,20,20) }
        replay { $g.DrawArc($outline,19,19,90,90,40,290); $g.DrawArc([Drawing.Pen]::new($blue,10),19,19,90,90,40,290); Line 99 27 107 50; Line 107 50 83 48; $points=[Drawing.Point[]]@([Drawing.Point]::new(50,44),[Drawing.Point]::new(50,85),[Drawing.Point]::new(82,64)); $g.FillPolygon([Drawing.SolidBrush]::new($cyan),$points); $g.DrawPolygon($outline,$points) }
    }
    $small = [Drawing.Bitmap]::new(128,128)
    $sg = [Drawing.Graphics]::FromImage($small)
    $sg.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $sg.DrawImage($canvas,0,0,128,128)
    $small.Save($path,[Drawing.Imaging.ImageFormat]::Png)
    $sg.Dispose(); $small.Dispose(); $outline.Dispose(); $ink.Dispose(); $g.Dispose(); $canvas.Dispose()
}
$preview = [Drawing.Bitmap]::new(720,620)
$g = [Drawing.Graphics]::FromImage($preview)
$g.Clear([Drawing.ColorTranslator]::FromHtml('#172433'))
$font = [Drawing.Font]::new('Segoe UI',12)
for ($i=0; $i -lt $names.Count; $i++) {
    $x = ($i % 4)*180; $y = [math]::Floor($i/4)*155
    $im = [Drawing.Image]::FromFile((Join-Path $destination ($names[$i]+'.png')))
    $g.DrawImage($im,($x+26),($y+5),128,128)
    $g.DrawString($names[$i],$font,[Drawing.Brushes]::White,($x+28),($y+130))
    $im.Dispose()
}
$preview.Save((Join-Path $PSScriptRoot '../docs/extra-icons-preview.png'),[Drawing.Imaging.ImageFormat]::Png)
$font.Dispose(); $g.Dispose(); $preview.Dispose()
