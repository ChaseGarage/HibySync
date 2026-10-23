import QtQuick
import ".."

Canvas {
    id: icon
    property string name: "music"
    property color ink: Theme.muted
    implicitWidth: 20
    implicitHeight: 20
    antialiasing: true
    onNameChanged: requestPaint()
    onInkChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        const c = getContext("2d")
        c.reset()
        c.scale(width / 24, height / 24)
        c.strokeStyle = ink
        c.fillStyle = ink
        c.lineWidth = 1.5
        c.lineCap = "round"
        c.lineJoin = "round"
        c.beginPath()
        if (name === "play") {
            c.moveTo(8, 5); c.lineTo(19, 12); c.lineTo(8, 19); c.closePath(); c.fill()
        } else if (name === "pause") {
            c.moveTo(8, 5); c.lineTo(8, 19); c.moveTo(16, 5); c.lineTo(16, 19)
        } else if (name === "stop") {
            c.rect(6, 6, 12, 12)
        } else if (name === "next" || name === "previous") {
            if (name === "previous") { c.translate(24, 0); c.scale(-1, 1) }
            c.moveTo(5, 6); c.lineTo(15, 12); c.lineTo(5, 18); c.closePath(); c.fill()
            c.moveTo(18, 5); c.lineTo(18, 19)
        } else if (name === "queue") {
            c.moveTo(3, 5); c.lineTo(21, 5); c.moveTo(3, 11); c.lineTo(21, 11); c.moveTo(3, 17); c.lineTo(12, 17)
            c.moveTo(17, 15); c.lineTo(21, 18); c.lineTo(17, 21)
        } else if (name === "volume") {
            c.moveTo(3, 9); c.lineTo(7, 9); c.lineTo(12, 5); c.lineTo(12, 19); c.lineTo(7, 15); c.lineTo(3, 15); c.closePath()
            c.moveTo(16, 8); c.quadraticCurveTo(20, 12, 16, 16)
        } else if (name === "repeat" || name === "repeatOne") {
            c.moveTo(4, 10); c.lineTo(4, 6); c.lineTo(20, 6); c.lineTo(17, 3); c.moveTo(20, 6); c.lineTo(17, 9)
            c.moveTo(20, 14); c.lineTo(20, 18); c.lineTo(4, 18); c.lineTo(7, 21); c.moveTo(4, 18); c.lineTo(7, 15)
            if (name === "repeatOne") { c.moveTo(11, 10); c.lineTo(13, 9); c.lineTo(13, 15) }
        } else if (name === "shuffle") {
            c.moveTo(3, 6); c.lineTo(7, 6); c.lineTo(16, 18); c.lineTo(21, 18); c.lineTo(18, 15); c.moveTo(21, 18); c.lineTo(18, 21)
            c.moveTo(3, 18); c.lineTo(7, 18); c.lineTo(16, 6); c.lineTo(21, 6); c.lineTo(18, 3); c.moveTo(21, 6); c.lineTo(18, 9)
        } else if (name === "up" || name === "down") {
            if (name === "down") { c.translate(0, 24); c.scale(1, -1) }
            c.moveTo(6, 15); c.lineTo(12, 9); c.lineTo(18, 15)
        } else if (name === "plus") {
            c.moveTo(12, 5); c.lineTo(12, 19); c.moveTo(5, 12); c.lineTo(19, 12)
        } else if (name === "more") {
            c.rect(5, 11, 1, 1); c.rect(11, 11, 1, 1); c.rect(17, 11, 1, 1)
        } else if (name === "chevron") {
            c.moveTo(9, 6); c.lineTo(15, 12); c.lineTo(9, 18)
        } else if (name === "back") {
            c.moveTo(11, 5); c.lineTo(4, 12); c.lineTo(11, 19)
            c.moveTo(4, 12); c.lineTo(21, 12)
        } else if (name === "folder") {
            c.moveTo(3, 6); c.lineTo(10, 6); c.lineTo(12, 8); c.lineTo(21, 8)
            c.lineTo(21, 19); c.lineTo(3, 19); c.closePath()
        } else if (name === "settings") {
            for (let i = 0; i < 3; i++) {
                let y = 6 + i * 6
                c.moveTo(3, y); c.lineTo(21, y)
            }
        } else if (name === "close") {
            c.moveTo(6, 6); c.lineTo(18, 18); c.moveTo(18, 6); c.lineTo(6, 18)
        } else {
            c.moveTo(9, 17); c.lineTo(9, 5); c.lineTo(20, 3); c.lineTo(20, 15)
            c.moveTo(9, 9); c.lineTo(20, 7)
        }
        c.stroke()
        if (name === "music") {
            c.beginPath(); c.ellipse(3, 15, 6, 5); c.fill()
            c.beginPath(); c.ellipse(14, 13, 6, 5); c.fill()
        } else if (name === "settings") {
            c.fillStyle = Theme.background
            c.fillRect(7, 3, 4, 6); c.strokeRect(7, 3, 4, 6)
            c.fillRect(14, 9, 4, 6); c.strokeRect(14, 9, 4, 6)
            c.fillRect(7, 15, 4, 6); c.strokeRect(7, 15, 4, 6)
        }
    }
}
