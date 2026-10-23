import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: page
    required property var controller
    readonly property var result: controller.importSummary
    spacing: 24
    Type {
        text: page.result.cancelled ? "Import cancelled" : page.result.failed || page.result.errors || page.result.cleanupErrors ? "Import finished with issues" : "Import complete"
        font.pixelSize: Theme.title; font.weight: Font.DemiBold
    }
    Type {
        text: (page.result.imported || 0) + " imported  ·  " + (page.result.replaced || 0) + " replaced  ·  " + (page.result.duplicate || 0) + " already present  ·  " + (page.result.skipped || 0) + " skipped  ·  " + (page.result.failed || 0) + " failed"
        color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true
    }
    Type { text: (page.result.removed || 0) + " verified original tracks removed · " + (page.result.retained || 0) + " scanned originals kept"; color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
    Type { visible: page.result.remaining > 0; text: (page.result.remaining || 0) + " files were not processed."; color: Theme.warning }
    Type { text: page.result.errors || ""; visible: text.length > 0; color: Theme.error; wrapMode: Text.Wrap; Layout.fillWidth: true }
    Type { text: page.result.recovery ? "Recovery copies: " + page.result.recovery : ""; visible: text.length > 0; color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
    Divider { Layout.fillWidth: true }
    ListView {
        id: files
        objectName: "importResultsList"
        model: page.controller.results
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ThinScrollBar {}
        delegate: Item {
            required property var record
            width: files.width
            height: details.implicitHeight + 32
            ColumnLayout {
                id: details
                x: 12; y: 16; width: parent.width - 24; spacing: 8
                RowLayout {
                    Type { text: record.filename; font.weight: Font.DemiBold; Layout.fillWidth: true }
                    Type { text: record.action; color: record.action === "failed" ? Theme.error : Theme.muted; font.pixelSize: Theme.small }
                }
                Type { text: page.controller.displayPath(record.destination); color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Type { text: record.error; visible: text.length > 0; color: Theme.error; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Type { text: record.cleanupError; visible: text.length > 0; color: Theme.warning; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
            Divider { anchors.bottom: parent.bottom; width: parent.width - 24; x: 12 }
        }
    }
    FlatButton { text: "Back to albums"; Layout.alignment: Qt.AlignRight; onClicked: page.controller.navigate("import") }
}
