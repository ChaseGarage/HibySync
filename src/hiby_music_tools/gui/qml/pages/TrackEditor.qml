import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: panel
    required property var controller
    signal closeRequested()
    signal artworkRequested(int trackIndex)
    property bool originalsVisible: false
    spacing: 24
    RowLayout {
        Type { text: "Edit track"; font.pixelSize: 20; font.weight: Font.DemiBold; Layout.fillWidth: true }
        IconButton { text: "Close track editor"; glyph: "close"; onClicked: panel.closeRequested() }
    }
    Type { text: panel.controller.track.filename || ""; color: Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true }
    Field { id: title; editorName: "trackTitleInput"; label: "Track title"; text: panel.controller.track.title || ""; Layout.fillWidth: true }
    Field { id: artist; editorName: "trackArtistInput"; label: "Track artist"; text: panel.controller.track.artist || ""; Layout.fillWidth: true }
    RowLayout {
        spacing: 16
        Field { id: number; editorName: "trackNumberInput"; label: "Track number"; text: panel.controller.track.number || ""; Layout.fillWidth: true }
        Field { id: disc; editorName: "trackDiscInput"; label: "Disc number"; text: panel.controller.track.disc || ""; Layout.fillWidth: true }
    }
    Type { text: panel.controller.track.provenance || ""; color: Theme.muted; font.pixelSize: Theme.small }
    Type { text: panel.controller.track.issues || ""; visible: text.length > 0; color: Theme.warning; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
    Divider { Layout.fillWidth: true }
    FlatButton { text: "Choose artwork for this track"; quiet: true; onClicked: panel.artworkRequested(panel.controller.track.index) }
    FlatButton { text: panel.originalsVisible ? "Hide original tags" : "Show original tags"; quiet: true; onClicked: panel.originalsVisible = !panel.originalsVisible }
    Type {
        visible: panel.originalsVisible
        text: panel.controller.track.original || ""
        color: Theme.muted; font.pixelSize: Theme.small
        wrapMode: Text.Wrap; Layout.fillWidth: true
    }
    Item { Layout.fillHeight: true }
    FlatButton {
        objectName: "applyTrackButton"
        text: "Save pending changes"
        primary: true
        Layout.fillWidth: true
        enabled: !panel.controller.busy
        onClicked: {
            panel.controller.applyTrack(artist.text, title.text, number.text, disc.text)
            panel.closeRequested()
        }
    }
}
