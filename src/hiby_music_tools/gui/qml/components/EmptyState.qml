import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: state
    property string title: "Your next great listen"
    property string subtitle: "Scan your incoming folder to begin."
    property string actionText: "Scan incoming music"
    signal action()
    ColumnLayout {
        anchors.centerIn: parent
        spacing: 16
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            width: 76; height: 76; radius: 8; color: Theme.surface
            Icon { anchors.centerIn: parent; width: 32; height: 32; name: "music" }
        }
        Type { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 8; text: title; font.pixelSize: 20; font.weight: Font.Medium }
        Type { Layout.alignment: Qt.AlignHCenter; text: subtitle; color: Theme.muted }
        FlatButton { objectName: "emptyScanButton"; Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 8; text: actionText; primary: true; visible: actionText.length > 0; onClicked: state.action() }
    }
}
