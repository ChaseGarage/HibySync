import QtQuick
import ".."

Rectangle {
    property real fraction: -1
    property color ink: Theme.muted
    implicitHeight: 4
    color: Theme.divider
    radius: 2
    Rectangle {
        height: parent.height; radius: 2; color: parent.ink
        width: parent.fraction < 0 ? 0 : parent.width * Math.max(0, Math.min(1, parent.fraction))
    }
}
