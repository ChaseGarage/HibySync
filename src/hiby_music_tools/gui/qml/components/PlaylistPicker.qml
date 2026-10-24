import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

Modal {
    id: picker
    objectName: "playlistPicker"
    visible: libraryPlaylists.choosing
    width: Math.min(parent.width - 48, 460); height: Math.min(parent.height - 64, 450)
    closePolicy: Popup.NoAutoClose
    contentItem: ColumnLayout {
        spacing: 16
        RowLayout {
            Type { text: "Add to playlist"; font.pixelSize: 22; Layout.fillWidth: true }
            IconButton { glyph: "close"; text: "Close playlist chooser"; enabled: !libraryPlaylists.busy; onClicked: libraryPlaylists.dismiss() }
        }
        Type { text: libraryPlaylists.message; visible: text.length > 0; color: Theme.error; wrapMode: Text.Wrap; Layout.fillWidth: true }
        ListView {
            id: list
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; model: libraryPlaylists.lists
            ScrollBar.vertical: ThinScrollBar {}
            delegate: FlatButton {
                required property var record
                objectName: "addToPlaylist_" + record.id
                width: list.width; quiet: true
                text: record.name + " · " + Theme.countLabel(record.count, "track")
                enabled: !libraryPlaylists.busy
                onClicked: libraryPlaylists.addTo(record.id)
            }
            Type { anchors.centerIn: parent; visible: list.count === 0; text: "Create your first playlist below"; color: Theme.muted }
        }
        RowLayout {
            Layout.fillWidth: true
            Field { id: newName; placeholderText: "New playlist name"; Layout.fillWidth: true }
            FlatButton { text: "Create"; enabled: !libraryPlaylists.busy && newName.text.trim().length > 0; onClicked: { libraryPlaylists.create(newName.text); newName.text = "" } }
        }
    }
}
