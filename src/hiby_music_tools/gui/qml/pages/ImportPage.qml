import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: page
    required property var controller
    signal settingsRequested()
    spacing: Theme.section
    RowLayout {
        Layout.fillWidth: true
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8
            Type { text: "Incoming Music"; font.pixelSize: Theme.title; font.weight: Font.DemiBold }
            Type {
                visible: page.controller.hasSession
                text: Theme.countLabel(page.controller.summary.albums, "album") + "  ·  " + Theme.countLabel(page.controller.summary.tracks, "track")
                color: Theme.muted; font.pixelSize: Theme.small
            }
        }
        Item { Layout.fillWidth: true }
        FlatButton {
            objectName: "scanButton"
            text: page.controller.busy ? "Cancel" : "Scan"
            visible: page.controller.hasSession || page.controller.busy
            onClicked: page.controller.busy ? page.controller.cancel() : page.controller.scan()
        }
    }
    RowLayout {
        visible: page.controller.summary.albums > 0
        spacing: 8
        Repeater {
            model: [{label: "All albums", value: "All"}, {label: "Needs review", value: "Needs Review"}, {label: "Ready", value: "Ready"}, {label: "Errors", value: "Error"}]
            FlatButton {
                required property var modelData
                text: modelData.label
                quiet: page.controller.filter !== modelData.value
                enabled: !page.controller.busy
                onClicked: page.controller.setFilter(modelData.value)
            }
        }
    }
    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        ListView {
            id: albumList
            objectName: "albumList"
            anchors.fill: parent
            clip: true
            model: page.controller.albums
            enabled: !page.controller.busy
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ThinScrollBar {}
            delegate: AlbumRow {
                width: albumList.width
                onClicked: page.controller.openAlbum(record.albumIndex)
            }
        }
        EmptyState {
            anchors.fill: parent
            visible: page.controller.summary.albums === 0
            title: page.controller.busy ? "Looking for music" : page.controller.hasSession ? "Nothing waiting here" : "No music scanned yet"
            subtitle: page.controller.busy ? "Reading metadata and artwork." : page.controller.hasSession ? "No supported audio found in this folder." : "Scan your incoming folder to begin."
            actionText: page.controller.busy ? "" : "Scan incoming music"
            onAction: page.controller.scan()
        }
        Type {
            anchors.centerIn: parent
            visible: page.controller.summary.albums > 0 && albumList.count === 0
            text: "No albums in this view."
            color: Theme.muted
        }
    }
    Divider { Layout.fillWidth: true }
    RowLayout {
        Layout.fillWidth: true
        spacing: 16
        FlatButton {
            id: folderButton
            objectName: "folderButton"
            quiet: true
            Layout.maximumWidth: page.width * 0.42
            text: page.controller.displayPath(page.controller.inbox)
            onClicked: page.settingsRequested()
            Accessible.name: "Change incoming folder"
        }
        Item { Layout.fillWidth: true }
        RowLayout {
            spacing: 16
            visible: page.controller.hasSession
            Status { status: "Ready"; compact: true }
            Type { text: page.controller.summary.ready + " ready"; color: Theme.muted; font.pixelSize: Theme.small }
            Status { status: "Needs Review"; compact: true }
            Type { text: page.controller.summary.review + page.controller.summary.errors + " to review"; color: Theme.muted; font.pixelSize: Theme.small }
        }
        FlatButton {
            objectName: "previewButton"
            text: "Preview import"
            visible: page.controller.hasSession
            enabled: page.controller.pathsMatch && !page.controller.busy
            onClicked: page.controller.preview()
        }
    }
}
