import QtQuick
import QtQuick.Controls.Basic
import ".."

Popup {
    parent: Overlay.overlay
    x: parent.width - width
    y: 0
    implicitWidth: 400
    height: parent.height
    padding: 28
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    enter: null
    exit: null
    background: Rectangle { color: Theme.background; border.width: 1; border.color: Theme.divider }
    Overlay.modal: Rectangle { color: "#AA000000" }
}
