import QtQuick
import QtQuick.Controls.Basic
import ".."

Slider {
    id: control
    implicitHeight: 28
    implicitWidth: 100
    padding: 5
    property color progressColor: Theme.muted
    hoverEnabled: true
    Accessible.name: "Position"
    background: Rectangle {
        x: control.leftPadding; y: (control.height - height) / 2
        width: control.availableWidth; height: 3; radius: 2
        color: Theme.divider
        Rectangle { width: control.visualPosition * parent.width; height: parent.height; radius: 2; color: control.enabled ? control.progressColor : Theme.divider }
    }
    handle: Rectangle {
        x: control.leftPadding + control.visualPosition * (control.availableWidth - width)
        y: (control.height - height) / 2
        width: 8; height: 8; radius: 4
        color: Theme.text
        visible: control.enabled && (control.hovered || control.pressed || control.activeFocus)
    }
}
