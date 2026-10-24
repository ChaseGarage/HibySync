import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."
import "../components"

ColumnLayout {
    id: page
    required property var manager
    required property var sourceController
    readonly property bool active: sourceController.page === "device"
    onActiveChanged: if (active) manager.activate()
    spacing: height < 600 ? 12 : 20
    RowLayout {
        Layout.fillWidth: true; spacing: 12
        ColumnLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 10
            Type { text: "Device"; font.pixelSize: Theme.title; font.weight: Font.DemiBold }
            RowLayout {
                spacing: 8
                Rectangle { width: 7; height: 7; radius: 4; color: page.manager.connected ? Theme.success : page.manager.status === "Unavailable" ? Theme.error : Theme.muted }
                Type { objectName: "deviceStatus"; text: page.manager.deviceName + " · " + page.manager.status; color: page.manager.connected ? Theme.success : Theme.muted }
            }
        }
        Item { Layout.fillWidth: true }
        FlatButton { objectName: "chooseDeviceButton"; text: "Choose device"; quiet: true; enabled: !page.manager.busy; onClicked: picker.open() }
        FlatButton { objectName: "refreshDeviceButton"; text: page.manager.comparing ? "Cancel" : "Refresh"; enabled: !page.manager.busy || page.manager.comparing; onClicked: page.manager.comparing ? page.manager.cancel() : page.manager.refresh(false) }
    }
    ListView {
        id: changes
        objectName: "deviceChangesList"
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 80
        model: page.manager.rows; clip: true
        activeFocusOnTab: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ThinScrollBar {}
        header: ColumnLayout {
            width: changes.width
            spacing: 16
            ColumnLayout {
                visible: page.manager.musicRoot.length > 0
                Layout.fillWidth: true; spacing: 6
                Type { text: page.manager.identity; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
                Type { objectName: "deviceMusicRoot"; text: page.manager.musicRoot; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap; maximumLineCount: 2; Layout.fillWidth: true }
                Type { text: page.manager.transport + "  ·  " + page.manager.storage; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
            Type {
                objectName: "deviceMessage"
                text: page.manager.message; visible: text.length > 0
                color: page.manager.status === "Unavailable" || page.manager.summary.conflicts > 0 ? Theme.error : Theme.muted
                wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: Theme.small
            }
            ColumnLayout {
                visible: page.manager.comparing
                spacing: 8; Layout.fillWidth: true
                Type { text: page.manager.phase; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap; maximumLineCount: 2; Layout.fillWidth: true }
                Rectangle {
                    Layout.fillWidth: true; height: 2; color: Theme.divider
                    Rectangle { height: 2; width: parent.width * (page.manager.progress < 0 ? .2 : Math.min(1, page.manager.progress)); color: Theme.muted }
                }
            }
            Flow {
                id: overview
                visible: page.manager.connected
                Layout.fillWidth: true; Layout.preferredHeight: implicitHeight
                spacing: 16
                readonly property int columns: Math.max(1, Math.min(3, Math.floor(width / 210)))
                Repeater {
                    model: [ {label: page.manager.summary.uncertain > 0 ? "Matching tracks · fast check" : "Synced tracks", value: page.manager.summary.synced + page.manager.summary.uncertain, ink: Theme.success},
                             {label: "Tracks to transfer", value: page.manager.summary.transfer, ink: Theme.warning},
                             {label: "Tracks to remove", value: page.manager.summary.remove, ink: Theme.error} ]
                    Column {
                        required property var modelData
                        width: (overview.width - (overview.columns - 1) * overview.spacing) / overview.columns
                        spacing: 8
                        Type { text: modelData.label; color: Theme.muted; font.pixelSize: Theme.small }
                        Type { text: String(modelData.value); color: modelData.ink; font.pixelSize: 26 }
                    }
                }
            }
            Divider { Layout.fillWidth: true }
            RowLayout {
                Layout.fillWidth: true
                Type { text: "Changes to Sync"; font.pixelSize: 18; font.weight: Font.DemiBold; Layout.fillWidth: true }
                FlatButton { objectName: "verifyDeviceButton"; text: "Verify contents"; quiet: true; enabled: page.manager.connected && !page.manager.busy; onClicked: page.manager.refresh(true) }
            }
            Item { Layout.preferredHeight: 8 }
        }
        delegate: Item {
            id: entry
            required property var record
            width: changes.width
            height: record.header ? 56 : fileRow.implicitHeight
            AbstractButton {
                id: group
                objectName: "deviceGroup_" + entry.record.kind
                visible: entry.record.header
                width: parent.width; height: 52
                hoverEnabled: true; activeFocusOnTab: true
                Accessible.name: entry.record.title + " " + (entry.record.count || 0) + " files"
                background: Rectangle { color: group.hovered || group.activeFocus ? Theme.hover : "transparent"; radius: Theme.radius }
                contentItem: RowLayout {
                    spacing: 12
                    Icon { name: entry.record.expanded ? "down" : "chevron"; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                    Type { text: entry.record.title; Layout.fillWidth: true }
                    Type { text: String(entry.record.count || 0); color: entry.record.kind === "remove" || entry.record.kind === "conflicts" ? Theme.error : Theme.warning; font.pixelSize: Theme.small }
                    Type { text: entry.record.sizeText || ""; color: Theme.muted; font.pixelSize: Theme.small; Layout.rightMargin: 12 }
                }
                onClicked: page.manager.toggleGroup(entry.record.kind)
            }
            DeviceChangeRow { id: fileRow; visible: !entry.record.header; width: parent.width; record: entry.record }
        }
        footer: EmptyState {
            width: changes.width
            height: visible ? Math.max(120, changes.height - (changes.headerItem ? changes.headerItem.height : 0)) : 0
            visible: changes.count === 0 && !page.manager.comparing
            title: page.manager.connected ? (page.manager.complete ? "Your music is up to date." : "Ready to compare") : "Your R1, when you're ready"
            subtitle: page.manager.connected ? "Local Library → HiBy /Music" : "Connect and mount your player, then Refresh."
            actionText: ""
        }
    }
    Divider { Layout.fillWidth: true }
    RowLayout {
        Layout.fillWidth: true; spacing: 12
        ColumnLayout {
            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 5
            Type { objectName: "devicePendingCount"; text: page.manager.summary.changes + " changes pending" }
            Type { text: page.manager.summary.transferSize + " to transfer"; color: Theme.muted; font.pixelSize: 12 }
        }
        Item { Layout.fillWidth: true }
        FlatButton { objectName: "previewDeviceButton"; text: "Preview changes"; quiet: true; enabled: page.manager.canPreview; onClicked: page.manager.showPreview() }
        FlatButton { objectName: "syncDeviceButton"; text: "Sync Device"; primary: true; enabled: page.manager.sync.canStart; onClicked: page.manager.sync.request() }
    }
    Type { text: "Local Library → HiBy /Music · Transfers verified before completion"; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }

    Modal {
        id: picker
        objectName: "devicePicker"
        width: Math.min(parent.width - 48, 620); height: Math.min(parent.height - 64, 400)
        contentItem: ColumnLayout {
            spacing: 16
            RowLayout {
                Type { text: "Choose device music"; font.pixelSize: 22; Layout.fillWidth: true }
                IconButton { glyph: "close"; text: "Close device chooser"; onClicked: picker.close() }
            }
            Type { text: "Only /Music on a mounted, USB-identified HiBy R1 is accepted. A local folder or an MTP URI cannot substitute for a device mount."; color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ListView {
                id: targets
                Layout.fillWidth: true; Layout.fillHeight: true; model: page.manager.choices; clip: true
                ScrollBar.vertical: ThinScrollBar {}
                delegate: AbstractButton {
                    id: choice
                    required property var record
                    objectName: "deviceChoice_" + record.key
                    width: targets.width; height: 64
                    hoverEnabled: true; activeFocusOnTab: true
                    background: Rectangle { color: choice.hovered || choice.activeFocus ? Theme.hover : "transparent"; radius: Theme.radius }
                    contentItem: ColumnLayout {
                        spacing: 6
                        Type { text: choice.record.name + " · " + choice.record.storage; Layout.fillWidth: true }
                        Type { text: choice.record.music; color: Theme.muted; font.pixelSize: 12; elide: Text.ElideLeft; Layout.fillWidth: true }
                    }
                    onClicked: { picker.close(); page.manager.choose(record.key) }
                }
                Type { anchors.centerIn: parent; visible: targets.count === 0; text: "No validated music roots detected"; color: Theme.muted }
            }
            FlatButton { text: "Choose mounted /Music folder…"; onClicked: { picker.close(); deviceFolder.open() } }
        }
    }
    FolderDialog {
        id: deviceFolder
        title: "Choose the R1's mounted Music folder"
        onAccepted: page.manager.chooseFolder(selectedFolder)
    }
    Modal {
        id: preview
        objectName: "devicePreviewDialog"
        visible: page.manager.previewOpen
        width: Math.min(parent.width - 48, 780); height: Math.min(parent.height - 64, 600)
        closePolicy: Popup.NoAutoClose
        contentItem: ColumnLayout {
            spacing: 16
            Type { text: "Sync preview"; font.pixelSize: 22; font.weight: Font.DemiBold }
            Type { text: page.manager.localRoot + " → " + page.manager.musicRoot; color: Theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 12 }
            Type { text: page.manager.summary.transfer + " transfers · " + page.manager.summary.transferSize + " · " + page.manager.summary.remove + " removals"; color: page.manager.summary.remove > 0 ? Theme.error : Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Type { text: "Review only. No files will be changed. Device-only audio listed as Remove requires separate confirmation before sync can apply it."; color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ListView {
                id: previewFiles
                objectName: "devicePreviewFiles"
                Layout.fillWidth: true; Layout.fillHeight: true; model: page.manager.previewRows; clip: true
                ScrollBar.vertical: ThinScrollBar {}
                delegate: DeviceChangeRow { width: previewFiles.width }
            }
            FlatButton { objectName: "closeDevicePreview"; text: "Close preview"; Layout.alignment: Qt.AlignRight; onClicked: page.manager.closePreview() }
        }
    }
    Modal {
        id: confirmation
        objectName: "deviceSyncConfirmation"
        visible: page.manager.sync.confirmationOpen
        width: Math.min(parent.width - 48, 720); height: Math.min(parent.height - 64, 560)
        closePolicy: Popup.NoAutoClose
        onOpened: removeConsent.selected = false
        contentItem: ColumnLayout {
            spacing: 16
            Type { text: "Sync music to your R1?"; font.pixelSize: 22; font.weight: Font.DemiBold }
            Type { text: page.manager.localRoot + " → " + page.manager.musicRoot; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 3 }
            Type { text: page.manager.summary.transfer + " transfers · " + page.manager.summary.transferSize + " · " + page.manager.summary.remove + " removals"; color: page.manager.summary.remove > 0 ? Theme.error : Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Type { visible: page.manager.transport.indexOf("MTP") >= 0; text: "MTP replacement may briefly move the old filename. Verified originals are retained in recovery storage; unsupported native moves fail safely."; color: Theme.warning; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
            ListView {
                id: confirmationFiles
                objectName: "deviceConfirmationFiles"
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                model: page.manager.sync.confirmationRows
                ScrollBar.vertical: ThinScrollBar {}
                delegate: DeviceChangeRow { width: confirmationFiles.width }
            }
            ToggleRow {
                id: removeConsent
                objectName: "deviceRemovalConsent"
                visible: page.manager.summary.remove > 0
                Layout.fillWidth: true
                text: "Permanently remove the " + page.manager.summary.remove + " listed device files"
                onClicked: selected = !selected
            }
            RowLayout {
                Layout.fillWidth: true
                FlatButton { text: "Keep reviewing"; quiet: true; onClicked: page.manager.sync.invalidate() }
                Item { Layout.fillWidth: true }
                FlatButton {
                    objectName: "confirmDeviceSync"
                    text: "Start Sync"; primary: true
                    enabled: !page.manager.busy && (page.manager.summary.remove === 0 || removeConsent.selected)
                    onClicked: page.manager.sync.confirm(removeConsent.selected)
                }
            }
        }
    }

}
