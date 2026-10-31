// SPDX-License-Identifier: AGPL-3.0-only
import AppKit
import Foundation

let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
for size in [16,32,128,256,512] {
    for scale in [1,2] {
        let pixels = size*scale
        let representation = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:pixels,pixelsHigh:pixels,
            bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,
            colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:representation)
        let factor = CGFloat(pixels)/1024
        let transform = NSAffineTransform(); transform.scale(by: factor); transform.concat()
        let background = NSBezierPath(roundedRect:NSRect(x:52,y:52,width:920,height:920),xRadius:214,yRadius:214)
        let gradient = NSGradient(starting:NSColor(srgbRed:0.20,green:0.85,blue:0.51,alpha:1),
                                  ending:NSColor(srgbRed:0.03,green:0.58,blue:0.32,alpha:1))!
        gradient.draw(in:background,angle:-75)
        NSColor.white.setFill()
        for index in 0..<4 {
            NSBezierPath(roundedRect:NSRect(x:230+CGFloat(index)*150,y:270,width:108,height:160+CGFloat(index)*100),
                         xRadius:26,yRadius:26).fill()
        }
        NSGraphicsContext.restoreGraphicsState()
        let filename = "icon_\(size)x\(size)\(scale==2 ? "@2x" : "").png"
        try representation.representation(using:.png,properties:[:])!.write(to:destination.appendingPathComponent(filename))
    }
}
