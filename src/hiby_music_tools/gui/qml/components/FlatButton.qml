import QtQuick
import QtQuick.Controls.Basic
import ".."

AbstractButton {
    id: control
    property bool primary: false
    property bool quiet: false
    implicitWidth: Math.max(64, contentItem.implicitWidth + 28)
    implicitHeight: 36
    padding: 0
    hoverEnabled: true
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.38
    Accessible.role: Accessible.Button
    Accessible.name: text
    contentItem: Type {
        text: control.text
        horizontalAlignment: Text.AlignHCenter
        color: control.primary ? Theme.background : Theme.text
        font.weight: control.primary ? Font.DemiBold : Font.Normal
    }
    background: Rectangle {
        radius: Theme.radius
        color: control.primary ? (control.hovered ? "#DADDDC" : Theme.text)
                               : control.hovered ? Theme.hover : control.quiet ? "transparent" : Theme.surface
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.muted
    }
}
