import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: page
    required property var manager
    readonly property var session: manager.sync
    readonly property var metrics: session.progress
    readonly property bool running: session.running
    readonly property bool awaitingBytes: (metrics.state === "Copying" || metrics.state === "Updating") && metrics.fileDone === null
    readonly property bool success: session.state === "complete"
    spacing: height < 600 ? 12 : 20
    RowLayout {
        Layout.fillWidth: true
        ColumnLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 8
            Type {
                objectName: "deviceSyncTitle"
                text: page.running ? "Syncing Music" : page.success ? "Sync Complete" : page.session.state === "cancelled" ? "Sync cancelled" : page.session.state === "disconnected" ? "Device disconnected" : page.session.state === "stale" ? "Sync needs review" : "Sync Completed with Errors"
                font.pixelSize: Theme.title; font.weight: Font.DemiBold
                Layout.fillWidth: true; wrapMode: Text.Wrap
            }
            Type { text: page.manager.deviceName + " · " + (page.running ? page.metrics.state : page.success ? "Your music is up to date." : "Completed work is preserved"); color: page.success ? Theme.success : Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true }
        }
        Item { Layout.fillWidth: true }
        FlatButton { objectName: "cancelDeviceSync"; visible: page.running; text: page.session.cancelRequested ? "Cancelling…" : "Cancel Sync"; enabled: !page.session.cancelRequested; onClicked: page.manager.cancel() }
        FlatButton { visible: !page.running; text: "Device"; quiet: true; onClicked: page.session.dashboardView() }
    }
    ColumnLayout {
        visible: page.running
        spacing: 10; Layout.fillWidth: true
        RowLayout {
            Layout.fillWidth: true
            Type { text: page.metrics.filesDone + " / " + page.metrics.filesTotal + " files verified"; color: Theme.muted; font.pixelSize: Theme.small; Layout.fillWidth: true }
            Type { text: page.awaitingBytes ? "Awaiting byte progress" : Math.floor(page.metrics.overallFraction * 100) + "% of transfer bytes"; color: Theme.muted; font.pixelSize: 12 }
        }
        TransferLine { objectName: "deviceOverallBar"; fraction: page.awaitingBytes ? -1 : page.metrics.overallFraction; Layout.fillWidth: true }
        Type { text: page.metrics.bytesText + " to device"; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
        Type { text: page.metrics.overallFraction >= 1 ? "Transfer bytes copied · verification and removals must finish before sync completes" : ""; visible: text.length > 0; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Divider { Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4 }
        Type { objectName: "deviceCurrentTitle"; text: page.metrics.title || page.metrics.state; font.pixelSize: 18; Layout.fillWidth: true }
        Type { text: page.metrics.detail || page.metrics.relpath; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
        RowLayout {
            Layout.fillWidth: true
            Type { objectName: "deviceFileState"; text: page.metrics.state; color: Theme.warning; font.pixelSize: Theme.small; Layout.fillWidth: true }
            Type { text: page.metrics.fileFraction >= 0 ? Math.floor(page.metrics.fileFraction * 100) + "%" : "In progress"; color: Theme.muted; font.pixelSize: 12 }
        }
        TransferLine { objectName: "deviceCurrentBar"; fraction: page.metrics.fileFraction; ink: Theme.success; Layout.fillWidth: true }
        RowLayout {
            Layout.fillWidth: true
            Type { text: page.metrics.fileBytesText || "Waiting for the transport"; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
            Type { text: page.metrics.speed; color: Theme.muted; font.pixelSize: 12 }
        }
    }
    RowLayout {
        visible: !page.running
        Layout.fillWidth: true; spacing: 20
        Repeater {
            model: [ {label: "New",value: page.session.report.new || 0}, {label: "Updated",value: page.session.report.updated || 0},
                     {label: "Removed",value: page.session.report.removed || 0}, {label: "Failed",value: page.session.report.failures || 0},
                     {label: "Skipped",value: page.session.report.skipped || 0} ]
            Column {
                required property var modelData
                spacing: 6
                Type { text: modelData.label; color: Theme.muted; font.pixelSize: 12 }
                Type { text: String(modelData.value); color: modelData.label === "Failed" && modelData.value > 0 ? Theme.error : page.success ? Theme.success : Theme.text; font.pixelSize: 24 }
            }
        }
        Item { Layout.fillWidth: true }
    }
    Type { visible: !page.running && text.length > 0; text: page.session.report.errors || ""; color: page.session.state === "cancelled" || page.session.state === "stale" ? Theme.warning : Theme.error; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 3; font.pixelSize: Theme.small }
    Divider { Layout.fillWidth: true }
    RowLayout {
        Layout.fillWidth: true
        Type { text: page.running ? "Recent activity" : "Activity"; font.pixelSize: 17; font.weight: Font.DemiBold; Layout.fillWidth: true }
        FlatButton { text: "Latest"; quiet: true; visible: page.running && !activity.follow; onClicked: { activity.follow = true; activity.positionViewAtEnd() } }
    }
    ListView {
        id: activity
        objectName: "deviceSyncActivity"
        property bool follow: true
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 70
        model: page.session.activity; clip: true
        ScrollBar.vertical: ThinScrollBar {}
        onDraggingChanged: if (dragging) follow = false
        WheelHandler { onWheel: function(event) { activity.follow = false; event.accepted = false } }
        onCountChanged: if (follow) Qt.callLater(function() { activity.positionViewAtEnd() })
        delegate: Item {
            id: entry
            required property var record
            width: activity.width; height: Math.max(66, labels.implicitHeight + 24)
            RowLayout {
                anchors.fill: parent; anchors.margins: 12; spacing: 12
                Rectangle { Layout.preferredWidth: 6; Layout.preferredHeight: 6; radius: 3; color: entry.record.status === "Completed" ? Theme.success : entry.record.status === "Failed" ? Theme.error : entry.record.status === "Skipped" ? Theme.muted : Theme.warning }
                ColumnLayout {
                    id: labels
                    Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 5
                    Type { text: entry.record.title || entry.record.relpath; Layout.fillWidth: true }
                    Type { text: entry.record.relpath; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
                    Type { text: entry.record.error || ""; visible: text.length > 0; color: entry.record.status === "Failed" ? Theme.error : Theme.muted; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 3 }
                }
                ColumnLayout {
                    spacing: 5
                    Type { text: entry.record.operation === "new" ? "Add" : entry.record.operation === "updated" ? "Update" : "Remove"; color: Theme.muted; font.pixelSize: 12; Layout.alignment: Qt.AlignRight }
                    Type { text: entry.record.status; color: entry.record.status === "Completed" ? Theme.success : entry.record.status === "Failed" ? Theme.error : entry.record.status === "Skipped" ? Theme.muted : Theme.warning; font.pixelSize: 12; Layout.alignment: Qt.AlignRight }
                }
            }
            Divider { width: parent.width; anchors.bottom: parent.bottom; opacity: .5 }
        }
        Type { anchors.centerIn: parent; visible: activity.count === 0; text: page.running ? "Revalidating before writing…" : "No files were transferred"; color: Theme.muted }
    }
    RowLayout {
        visible: !page.running
        Layout.fillWidth: true
        Type { text: page.session.report.recovery ? "Recovery log: " + page.session.report.recovery : ""; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideMiddle }
        FlatButton { text: "Copy log path"; quiet: true; visible: Boolean(page.session.report.recovery); onClicked: page.session.copyLogPath() }
        FlatButton { objectName: "retryDeviceSync"; text: "Retry Failed"; visible: !page.success && page.session.state !== "stale"; enabled: page.manager.connected && !page.manager.busy; onClicked: page.session.request() }
        FlatButton { objectName: "refreshAfterSync"; text: "Refresh"; enabled: !page.manager.busy; onClicked: page.session.refresh() }
    }
}
