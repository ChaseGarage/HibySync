import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: page
    spacing: 16
    Component.onCompleted: libraryPlaylists.refresh()
    RowLayout {
        Layout.fillWidth: true
        FlatButton { visible: libraryPlaylists.selected.length > 0; text: "←  Playlists"; quiet: true; onClicked: libraryPlaylists.open("") }
        Type { text: libraryPlaylists.name || "Your playlists"; font.pixelSize: 22; Layout.fillWidth: true }
        FlatButton { objectName: "newPlaylist"; text: "New playlist"; onClicked: { naming.renaming = false; playlistName.text = ""; naming.open() } }
        FlatButton { visible: libraryPlaylists.selected.length > 0; text: "Rename"; quiet: true; onClicked: { naming.renaming = true; playlistName.text = libraryPlaylists.name; naming.open() } }
    }
    Type { visible: libraryPlaylists.message.length > 0; text: libraryPlaylists.message; color: Theme.error; wrapMode: Text.Wrap; Layout.fillWidth: true }
    RowLayout {
        visible: libraryPlaylists.selected.length > 0
        enabled: !libraryPlaylists.busy && libraryPlaylists.count > 0
        FlatButton { objectName: "playPlaylist"; text: "Play"; onClicked: libraryPlaylists.play(false) }
        FlatButton { text: "Shuffle"; quiet: true; onClicked: libraryPlaylists.play(true) }
        Type { text: "Unavailable tracks are kept here and skipped during playback."; color: Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true; wrapMode: Text.Wrap }
    }
    ListView {
        id: list
        objectName: "playlistList"
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true
        model: libraryPlaylists.selected.length ? libraryPlaylists.model : libraryPlaylists.lists
        activeFocusOnTab: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ThinScrollBar {}
        delegate: Item {
            id: row
            required property var record
            required property int index
            width: list.width; height: 66
            Rectangle { anchors.fill: parent; color: mouse.containsMouse ? Theme.hover : list.currentIndex === row.index ? Theme.surface : "transparent"; radius: Theme.radius }
            MouseArea {
                id: mouse
                anchors.fill: parent; hoverEnabled: true
                onClicked: { list.currentIndex = row.index; if (!libraryPlaylists.selected.length) libraryPlaylists.open(row.record.id) }
            }
            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 12
                LibraryCover { visible: libraryPlaylists.selected.length > 0; Layout.preferredWidth: 44; Layout.preferredHeight: 44; source: row.record.image || "" }
                ColumnLayout {
                    Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 4
                    Type { text: row.record.title || row.record.name || ""; Layout.fillWidth: true; color: row.record.id === playback.currentTrackId && libraryPlaylists.selected.length ? Theme.success : Theme.text }
                    Type { text: libraryPlaylists.selected.length ? (row.record.missing ? "Unavailable · " : "") + (row.record.artist || "") : Theme.countLabel(row.record.count || 0, "track"); color: row.record.missing ? Theme.warning : Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true }
                }
                Type { visible: libraryPlaylists.selected.length > 0; text: row.record.durationText || ""; color: Theme.muted; font.pixelSize: Theme.small }
                IconButton { visible: libraryPlaylists.selected.length > 0; glyph: "up"; text: "Move earlier"; enabled: row.index > 0 && !libraryPlaylists.busy; onClicked: libraryPlaylists.move(row.record.entryId, row.index - 1) }
                IconButton { visible: libraryPlaylists.selected.length > 0; glyph: "down"; text: "Move later"; enabled: row.index < list.count - 1 && !libraryPlaylists.busy; onClicked: libraryPlaylists.move(row.record.entryId, row.index + 1) }
                IconButton { visible: libraryPlaylists.selected.length > 0; glyph: "close"; text: "Remove from playlist"; enabled: !libraryPlaylists.busy; onClicked: libraryPlaylists.remove(row.record.entryId) }
                FlatButton { visible: !libraryPlaylists.selected.length; text: "Open"; quiet: true; onClicked: libraryPlaylists.open(row.record.id) }
            }
            Divider { anchors.bottom: parent.bottom; width: parent.width; opacity: 0.5 }
        }
        EmptyState {
            anchors.fill: parent; visible: list.count === 0 && !libraryPlaylists.busy
            title: libraryPlaylists.selected.length ? "Make it yours" : "Music for every mood"
            subtitle: "Use Add to playlist from a song or album menu."
            actionText: ""
        }
    }
    Modal {
        id: naming
        property bool renaming: false
        width: Math.min(parent.width - 48, 420)
        contentItem: ColumnLayout {
            spacing: 20
            Type { text: naming.renaming ? "Rename playlist" : "New playlist"; font.pixelSize: 22 }
            Field { id: playlistName; editorName: "playlistNameInput"; placeholderText: "Playlist name"; Layout.fillWidth: true }
            RowLayout {
                Item { Layout.fillWidth: true }
                FlatButton { text: "Cancel"; quiet: true; onClicked: naming.close() }
                FlatButton { objectName: "savePlaylistName"; text: "Save"; enabled: playlistName.text.trim().length > 0 && !libraryPlaylists.busy; onClicked: { if (naming.renaming) libraryPlaylists.rename(playlistName.text); else libraryPlaylists.create(playlistName.text); naming.close() } }
            }
        }
    }
}
