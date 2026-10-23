import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

Flickable {
    id: page
    objectName: "reviewPage"
    required property var controller
    property bool editing: false
    signal artworkRequested(int trackIndex)
    signal trackRequested(int trackIndex)
    contentWidth: width
    contentHeight: reviewContent.height
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ThinScrollBar {}
    Connections {
        target: page.controller
        function onSelectionChanged() { if (page.controller.page !== "review") page.editing = false }
    }
    ColumnLayout {
        id: reviewContent
        width: page.width
        height: Math.max(implicitHeight, page.height)
        spacing: Theme.section
        RowLayout {
            FlatButton { text: "←  Incoming Music"; quiet: true; onClicked: { page.editing = false; page.controller.navigate("import") } }
            Item { Layout.fillWidth: true }
            FlatButton {
                objectName: "skipAlbumButton"
                text: page.controller.album.skipped ? "Restore album" : "Skip album"
                enabled: !page.controller.busy
                quiet: true
                onClicked: page.controller.toggleSkip()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 28
            ColumnLayout {
                spacing: 8
                Artwork {
                    Layout.preferredWidth: page.width < 850 ? 144 : 176
                    Layout.preferredHeight: width
                    source: page.controller.album.image || ""
                }
                FlatButton { objectName: "changeArtworkButton"; text: "Change artwork"; quiet: true; Layout.alignment: Qt.AlignHCenter; enabled: !page.controller.busy; onClicked: page.artworkRequested(-1) }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 12
                Type { text: page.controller.album.artist || ""; color: Theme.muted; font.pixelSize: 16; Layout.fillWidth: true }
                Type {
                    text: page.controller.album.title || ""; font.pixelSize: 28; font.weight: Font.DemiBold
                    Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2
                }
                Type {
                    text: (page.controller.album.year || "") + "  ·  " + Theme.countLabel(page.controller.album.count || 0, "track") + (page.controller.album.skipped ? "  ·  Skipped" : "")
                    color: Theme.muted; font.pixelSize: Theme.small
                }
                Status { status: page.controller.album.status || "Needs Review" }
                FlatButton { objectName: "editAlbumButton"; text: page.editing ? "Hide album fields" : "Edit album metadata"; quiet: true; onClicked: page.editing = !page.editing }
            }
        }
        ColumnLayout {
            visible: page.editing
            Layout.fillWidth: true
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                spacing: 16
                Field { id: artist; editorName: "albumArtistInput"; label: "Album artist"; text: page.controller.album.albumArtist || ""; Layout.fillWidth: true }
                Field { id: title; editorName: "albumTitleInput"; label: "Album title"; text: page.controller.album.albumTitle || ""; Layout.fillWidth: true }
                Field { id: year; editorName: "albumYearInput"; label: "Release year"; text: page.controller.album.releaseYear || ""; Layout.preferredWidth: 120 }
            }
            RowLayout {
                Type {
                    text: page.controller.album.mixed ? "Mixed album fields. Applying replaces these values for all tracks." : "Track artists stay unchanged."
                    color: Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true
                }
                FlatButton {
                    objectName: "applyAlbumButton"
                    text: "Apply to all tracks"
                    enabled: !page.controller.busy
                    onClicked: { page.controller.applyAlbum(artist.text, title.text, year.text); page.editing = false }
                }
            }
        }
        Type {
            visible: text.length > 0
            text: page.controller.album.issues || ""
            color: Theme.warning; font.pixelSize: Theme.small
            wrapMode: Text.Wrap; maximumLineCount: 3; Layout.fillWidth: true
        }
        Divider { Layout.fillWidth: true }
        RowLayout {
            Type { text: "Tracks"; font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            Type { text: "Select a track to edit"; color: Theme.muted; font.pixelSize: Theme.small }
        }
        ListView {
            id: tracks
            objectName: "trackList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 120
            Layout.preferredHeight: 180
            clip: true
            model: page.controller.tracks
            enabled: !page.controller.busy
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ThinScrollBar {}
            delegate: AbstractButton {
                id: trackRow
                required property var record
                objectName: "trackRow" + record.trackIndex
                width: tracks.width
                height: 64
                hoverEnabled: true
                activeFocusOnTab: true
                Accessible.name: record.title + ", " + record.artist
                background: Rectangle { color: trackRow.hovered || trackRow.activeFocus ? Theme.hover : "transparent"; radius: Theme.radius }
                contentItem: RowLayout {
                    spacing: 16
                    Type { text: trackRow.record.number; color: Theme.muted; Layout.preferredWidth: 36; Layout.leftMargin: 12 }
                    Type { text: trackRow.record.title; Layout.fillWidth: true }
                    Type { text: trackRow.record.artist; color: Theme.muted; Layout.preferredWidth: tracks.width * 0.25 }
                    Type { text: "Edited"; visible: trackRow.record.edited; color: Theme.muted; font.pixelSize: 12 }
                    Status { status: trackRow.record.status; compact: true }
                    Icon { name: "chevron"; width: 16; height: 16; Layout.rightMargin: 12 }
                }
                Divider { anchors.bottom: parent.bottom; width: parent.width - 24; x: 12 }
                onClicked: page.trackRequested(record.trackIndex)
            }
        }
        RowLayout {
            Type { text: "Changes stay pending until import."; color: Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true }
            FlatButton { text: "Done reviewing"; enabled: !page.controller.busy; onClicked: page.controller.navigate("import") }
            FlatButton { text: "Preview import"; enabled: page.controller.pathsMatch && !page.controller.busy; onClicked: page.controller.preview() }
        }
    }
}
