import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

Modal {
    id: dialog
    required property var manager
    objectName: "libraryDeleteDialog"
    visible: manager.open
    width: Math.min(parent.width - 48, 600)
    height: Math.min(parent.height - 64, 460)
    closePolicy: Popup.NoAutoClose
    contentItem: ColumnLayout {
        spacing: 16
        Type { text: dialog.manager.state === "results" ? "Deletion results" : "Permanently delete " + (dialog.manager.scope === "album" ? "album" : "song") + "?"; font.pixelSize: 22; font.weight: Font.DemiBold; Layout.fillWidth: true }
        Type { text: dialog.manager.label; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Type {
            visible: dialog.manager.state === "confirm"
            text: Theme.countLabel(dialog.manager.count, "audio file") + " will be permanently removed. This bypasses Trash and cannot be undone. Folder artwork and other files will stay. Playback will stop."
            color: Theme.warning; wrapMode: Text.Wrap; Layout.fillWidth: true
        }
        Type { text: dialog.manager.message; visible: text.length > 0; color: Theme.error; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Type { text: dialog.manager.phase; visible: dialog.manager.busy; color: Theme.muted; font.pixelSize: 12; Layout.fillWidth: true }
        ListView {
            id: files
            Layout.fillWidth: true; Layout.fillHeight: true
            model: dialog.manager.rows; clip: true
            ScrollBar.vertical: ThinScrollBar {}
            delegate: Column {
                required property var record
                width: files.width; spacing: 6; height: implicitHeight + 12
                Type { text: record.path; width: parent.width; wrapMode: Text.Wrap; font.pixelSize: 12 }
                Type { text: record.error || (record.status === "missing" ? "Already missing; remove from index" : record.status === "deleted" ? "Deleted" : ""); visible: text.length > 0; width: parent.width; wrapMode: Text.Wrap; color: record.error ? Theme.error : Theme.muted; font.pixelSize: 12 }
                Divider { width: parent.width }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            FlatButton { objectName: "cancelLibraryDelete"; text: dialog.manager.busy && dialog.manager.state === "deleting" ? "Stop deleting" : dialog.manager.state === "results" ? "Close" : "Cancel"; quiet: true; onClicked: dialog.manager.busy ? dialog.manager.cancel() : dialog.manager.dismiss() }
            Item { Layout.fillWidth: true }
            FlatButton {
                objectName: "confirmLibraryDelete"
                text: "Delete permanently"
                destructive: true
                visible: dialog.manager.state === "confirm"
                enabled: dialog.manager.canConfirm
                onClicked: dialog.manager.confirm()
            }
        }
    }
}
