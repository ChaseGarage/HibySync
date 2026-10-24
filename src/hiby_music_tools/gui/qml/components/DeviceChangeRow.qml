import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: row
    required property var record
    readonly property color accent: record.kind === "remove" || record.kind === "conflicts" ? Theme.error : Theme.warning
    implicitHeight: Math.max(72, details.implicitHeight + 24)
    RowLayout {
        anchors.fill: parent; anchors.margins: 12; spacing: 16
        ColumnLayout {
            id: details
            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 4
            Type { text: row.record.title || ""; Layout.fillWidth: true }
            Type { text: row.record.detail || ""; visible: text.length > 0; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
            Type { text: row.record.relpath || ""; visible: text.length > 0 && text !== row.record.title; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2 }
            Type { text: row.record.reason || ""; visible: text.length > 0; color: row.accent; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 3 }
        }
        ColumnLayout {
            spacing: 5; Layout.alignment: Qt.AlignTop
            Type { text: row.record.action || ({new:"Add",updated:"Update",remove:"Remove",uncertain:"Verify",conflicts:"Review"})[row.record.kind] || ""; color: row.accent; font.pixelSize: 12; Layout.alignment: Qt.AlignRight }
            Type { text: row.record.sizeText || ""; color: Theme.muted; font.pixelSize: 12; Layout.alignment: Qt.AlignRight }
        }
    }
    Divider { width: parent.width; anchors.bottom: parent.bottom; opacity: 0.5 }
}
