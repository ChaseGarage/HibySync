import QtQuick
import QtQuick.Controls.Basic
import ".."

ScrollBar {
    id: bar
    padding: 2
    implicitWidth: 8
    contentItem: Rectangle { implicitWidth: 4; radius: 2; color: bar.pressed ? Theme.muted : Theme.divider; opacity: bar.size < 1 ? 1 : 0 }
    background: Item {}
}
