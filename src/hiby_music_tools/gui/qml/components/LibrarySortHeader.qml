import QtQuick
import QtQuick.Controls.Basic
import ".."

AbstractButton {
    id: control
    property bool selected: false
    property bool descending: false
    property bool alignRight: false
    implicitHeight: 32
    hoverEnabled: true
    activeFocusOnTab: true
    Accessible.name: "Sort by " + text
    contentItem: Type {
        text: control.text + (control.selected ? (control.descending ? "  ↓" : "  ↑") : "")
        color: control.selected || control.hovered || control.activeFocus ? Theme.text : Theme.muted
        font.pixelSize: Theme.small
        horizontalAlignment: control.alignRight ? Text.AlignRight : Text.AlignLeft
    }
    background: Item {}
}
