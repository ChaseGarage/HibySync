import QtQuick
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: page
    required property var controller
    signal folderRequested(var field)
    spacing: 24
    FlatButton { text: "←  Incoming Music"; quiet: true; onClicked: page.controller.navigate("import") }
    Type { text: "Music folders"; font.pixelSize: Theme.title; font.weight: Font.DemiBold }
    Type { text: "Folder changes take effect on your next scan."; color: Theme.muted; font.pixelSize: Theme.small }
    ColumnLayout {
        Layout.fillWidth: true
        Layout.maximumWidth: 700
        spacing: 24
        RowLayout {
            spacing: 12
            Field { id: inbox; label: "Incoming downloads"; text: page.controller.inbox; Layout.fillWidth: true }
            IconButton { glyph: "folder"; text: "Choose incoming folder"; Layout.alignment: Qt.AlignBottom; onClicked: page.folderRequested(inbox) }
        }
        RowLayout {
            spacing: 12
            Field { id: library; label: "Music library"; text: page.controller.library; Layout.fillWidth: true }
            IconButton { glyph: "folder"; text: "Choose library folder"; Layout.alignment: Qt.AlignBottom; onClicked: page.folderRequested(library) }
        }
        FlatButton { text: "Use these folders"; enabled: !page.controller.busy; onClicked: { page.controller.setPaths(inbox.text, library.text); page.controller.navigate("import") } }
    }
    Item { Layout.fillHeight: true }
}
