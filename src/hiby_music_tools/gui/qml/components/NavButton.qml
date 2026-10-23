import QtQuick
import QtQuick.Controls.Basic
import ".."

AbstractButton {
    id: control
    property bool selected: false
    implicitWidth: contentItem.implicitWidth + 32
    implicitHeight: 64
    hoverEnabled: true
    activeFocusOnTab: true
    Accessible.name: text
    contentItem: Type {
        text: control.text
        horizontalAlignment: Text.AlignHCenter
        color: control.selected || control.hovered || control.activeFocus ? Theme.text : Theme.muted
        font.weight: control.selected ? Font.DemiBold : Font.Normal
    }
    background: Item {
        Rectangle {
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 32
            height: 2
            color: Theme.success
            visible: control.selected
        }
    }
}
