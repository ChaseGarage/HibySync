import QtQuick
import QtQuick.Layouts
import ".."

RowLayout {
    property string status: "Ready"
    property bool compact: false
    spacing: 8
    Rectangle {
        width: 6; height: 6; radius: 3
        color: status === "Error" ? Theme.error : status === "Needs Review" ? Theme.warning : Theme.success
    }
    Type { text: status; color: Theme.muted; font.pixelSize: Theme.small; visible: !compact }
}
