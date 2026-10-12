import AppKit

let width = 2500, height = 1686
let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
let dark = NSColor(calibratedRed: 0.12, green: 0.26, blue: 0.12, alpha: 1)
let cream = NSColor(calibratedRed: 0.95, green: 0.97, blue: 0.92, alpha: 1)
let accent = NSColor(calibratedRed: 0.85, green: 0.93, blue: 0.87, alpha: 1)
dark.setFill()
NSBezierPath(rect: NSRect(x: 0, y: 0, width: width, height: height)).fill()
let labels = ["My Attendance", "Leave History", "Salary Inquiry", "Time Out Report", "Attendance Status", "Help Center"]
let subtitles = ["Your monthly record", "Your leave records", "Pay and estimates", "Bus return & school count", "Daily report & manual edits", "Review & resolve tickets"]
let symbols = ["checkmark.circle", "clock.arrow.circlepath", "dollarsign.circle", "bus", "person.3", "tray.full"]
func drawText(_ text: String, rect: NSRect, size: CGFloat, bold: Bool, color: NSColor) {
    let paragraph = NSMutableParagraphStyle(); paragraph.alignment = .center
    let attrs: [NSAttributedString.Key: Any] = [.font: bold ? NSFont.boldSystemFont(ofSize: size) : NSFont.systemFont(ofSize: size), .foregroundColor: color, .paragraphStyle: paragraph]
    (text as NSString).draw(in: rect, withAttributes: attrs)
}
for index in 0..<6 {
    let column = index % 3, row = index / 3
    let x = CGFloat(column) * 833.33, y = CGFloat(1 - row) * 843
    let tile = NSRect(x: x + 22, y: y + 22, width: 789, height: 799)
    cream.setFill(); NSBezierPath(roundedRect: tile, xRadius: 38, yRadius: 38).fill()
    drawText("CSIE  /  ADMIN", rect: NSRect(x: x + 45, y: y + 720, width: 740, height: 58), size: 30, bold: true, color: dark)
    accent.setFill(); NSBezierPath(ovalIn: NSRect(x: x + 293, y: y + 380, width: 245, height: 245)).fill()
    if let icon = NSImage(systemSymbolName: symbols[index], accessibilityDescription: nil) {
        let tint = icon.withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 140, weight: .regular))!
        tint.draw(in: NSRect(x: x + 340, y: y + 428, width: 150, height: 150))
    }
    drawText(labels[index], rect: NSRect(x: x + 35, y: y + 240, width: 765, height: 95), size: 60, bold: true, color: dark)
    drawText(subtitles[index], rect: NSRect(x: x + 45, y: y + 155, width: 740, height: 70), size: 34, bold: false, color: dark)
}
NSGraphicsContext.restoreGraphicsState()
let output = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "assets/admin_rich_menu.png"
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: output))
print(output)
