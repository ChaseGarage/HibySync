import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: page
    required property var controller
    spacing: 24
    FlatButton { text: "←  Incoming Music"; quiet: true; onClicked: page.controller.navigate("import") }
    Type { text: "Import preview"; font.pixelSize: Theme.title; font.weight: Font.DemiBold }
    Type { text: "Review destinations and changes. Originals are removed only after successful verification."; color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
    ListView {
        id: plans
        objectName: "planList"
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true
        model: page.controller.plan
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ThinScrollBar {}
        delegate: Item {
            id: operation
            required property var record
            required property int index
            property bool expanded: false
            width: plans.width
            height: column.implicitHeight + 40
            ColumnLayout {
                id: column
                x: 12; y: 20; width: parent.width - 24
                spacing: 10
                RowLayout {
                    Type { text: operation.record.filename; font.weight: Font.DemiBold; Layout.fillWidth: true }
                    Type { text: operation.record.action; color: Theme.muted; font.pixelSize: Theme.small }
                    FlatButton { text: operation.expanded ? "Less" : "Details"; quiet: true; onClicked: operation.expanded = !operation.expanded }
                }
                Type { text: "→  " + page.controller.displayPath(operation.record.destination); color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Type { visible: text.length > 0; text: operation.record.warning; color: Theme.warning; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
                FlatButton {
                    objectName: "conflictPolicy" + index
                    visible: operation.record.conflict
                    text: operation.record.policy === "replace" ? "Replace existing (backup kept)" : "Keep existing file"
                    enabled: !page.controller.busy
                    onClicked: page.controller.setConflict(operation.record.source, operation.record.policy === "replace" ? "keep" : "replace")
                }
                Type {
                    visible: operation.expanded
                    text: "Source: " + operation.record.source + "\n\nMetadata: " + operation.record.metadata + "\n\nArtwork: " + operation.record.artwork
                    color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true
                }
            }
            Divider { anchors.bottom: parent.bottom; width: parent.width - 24; x: 12 }
        }
    }
    RowLayout {
        Type { text: "Skipped and failed originals stay. Conflicts default to keeping existing files."; color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
        FlatButton { text: "Back to albums"; enabled: !page.controller.busy; onClicked: page.controller.navigate("import") }
        FlatButton { objectName: "importCopiesButton"; text: "Import files"; primary: true; enabled: page.controller.canImport; onClicked: page.controller.requestImport() }
    }
}
