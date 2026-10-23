import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: field
    property alias text: editor.text
    property alias label: caption.text
    property alias placeholderText: editor.placeholderText
    property alias editorName: editor.objectName
    signal accepted()
    spacing: 8
    Type { id: caption; color: Theme.muted; font.pixelSize: 12; visible: text.length > 0 }
    TextField {
        id: editor
        Layout.fillWidth: true
        Layout.preferredHeight: 40
        leftPadding: 12
        rightPadding: 12
        color: Theme.text
        placeholderTextColor: Theme.muted
        selectedTextColor: Theme.text
        selectionColor: "#42474D"
        font.family: Theme.family
        font.pixelSize: Theme.body
        selectByMouse: true
        onAccepted: field.accepted()
        Accessible.name: caption.text
        background: Rectangle {
            color: Theme.surface
            radius: Theme.radius
            border.width: editor.activeFocus ? 1 : 0
            border.color: Theme.muted
        }
    }
}
