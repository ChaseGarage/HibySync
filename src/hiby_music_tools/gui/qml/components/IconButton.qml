import QtQuick
import QtQuick.Controls.Basic
import ".."

AbstractButton {
    id: control
    property string glyph: "settings"
    property bool active: false
    property bool prominent: false
    implicitWidth: 36
    implicitHeight: 36
    hoverEnabled: true
    activeFocusOnTab: true
    Accessible.name: text
    contentItem: Item {
        Icon { name: control.glyph; anchors.centerIn: parent; ink: !control.enabled ? Theme.divider : control.active ? Theme.success : control.prominent || control.hovered ? Theme.text : Theme.muted }
    }
    background: Rectangle {
        radius: Theme.radius
        color: control.hovered || control.activeFocus ? Theme.hover : control.prominent ? Theme.surface : "transparent"
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.muted
    }
    Keys.onReturnPressed: clicked()
    Keys.onEnterPressed: clicked()
    ToolTip {
        visible: control.hovered && control.text.length > 0
        delay: 600
        text: control.text
        padding: 8
        contentItem: Type { text: control.text; font.pixelSize: 12 }
        background: Rectangle { color: Theme.surface; radius: Theme.radius; border.width: 1; border.color: Theme.divider }
    }
}
