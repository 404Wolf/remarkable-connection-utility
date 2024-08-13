from .BackupController import BackupController
from .Backup import Backup
from .BackupFile import BackupFile

rm1_backup_types = {
    'Full (OS + Data)': [
        # [name, btype, mountpoint], See BackupFile.__init__()
        ['mmcblk1boot0', 'bin', '/dev/mmcblk1boot0'],
        ['mmcblk1boot1', 'bin', '/dev/mmcblk1boot1'],
        ['mmcblk1', 'bin', '/dev/mmcblk1']],
    'Only OS': [
        ['mmcblk1boot0', 'bin', '/dev/mmcblk1boot0'],
        ['mmcblk1boot1', 'bin', '/dev/mmcblk1boot1'],
        ['mmcblk1p1', 'bin', '/dev/mmcblk1p1'],
        ['mmcblk1p2', 'bin', '/dev/mmcblk1p2'],
        ['mmcblk1p3', 'bin', '/dev/mmcblk1p3']],
    'Only Data (low)': [
        ['mmcblk1p5', 'bin', '/dev/mmcblk1p5'],
        ['mmcblk1p6', 'bin', '/dev/mmcblk1p6'],
        ['mmcblk1p7', 'bin', '/dev/mmcblk1p7']],
    'Only Data (high)': [
        ['mmcblk1p7-user', 'tar', '$HOME'],
        ['mmcblk1-share', 'tar', '/usr/share/remarkable']]}

rm2_backup_types = {
    'Only Data (high)': [
        ['mmcblk2p4-user', 'tar', '$HOME'],
        ['mmcblk2-share', 'tar', '/usr/share/remarkable']],
    'Only Data (low)': [
        ['mmcblk2p4', 'softbin', '/dev/mmcblk2p4']]}
