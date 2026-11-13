"""Windows-only, fail-closed cleanup for verified temporary attachments."""

import ctypes
import hashlib
import os
from ctypes import wintypes
from pathlib import Path


class CleanupRejected(ValueError):
    """Cleanup authorization failed before deletion was attempted."""


class CleanupUncertain(RuntimeError):
    """Deletion was attempted, but its final outcome is not confirmed."""


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("low", wintypes.DWORD),
        ("high", wintypes.DWORD),
    ]


class FILE_INFO(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("creation", FILETIME),
        ("access", FILETIME),
        ("write", FILETIME),
        ("volume", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]


class FILE_DISPOSITION_INFO(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOL)]


GENERIC_READ = 0x80000000
DELETE = 0x10000
READ_ATTRIBUTES = 0x80
SHARE_READ = 0x1
SHARE_DELETE = 0x4
OPEN_EXISTING = 3
OPEN_REPARSE = 0x00200000
BACKUP_SEMANTICS = 0x02000000
REPARSE_ATTRIBUTE = 0x400
DIRECTORY_ATTRIBUTE = 0x10
FILE_DISPOSITION_INFO_CLASS = 4
INVALID_HANDLE = ctypes.c_void_p(-1).value


def _windows_api():
    if os.name != "nt":
        raise CleanupRejected("Windows is required")

    api = ctypes.WinDLL("kernel32", use_last_error=True)

    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    api.CreateFileW.restype = wintypes.HANDLE

    api.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILE_INFO),
    ]
    api.GetFileInformationByHandle.restype = wintypes.BOOL

    api.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    api.GetFinalPathNameByHandleW.restype = wintypes.DWORD

    api.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    api.ReadFile.restype = wintypes.BOOL

    api.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    api.SetFileInformationByHandle.restype = wintypes.BOOL

    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL

    return api


def _normalized(path):
    return os.path.normcase(os.path.normpath(str(path)))


def _open(api, path, directory):
    access = READ_ATTRIBUTES if directory else GENERIC_READ | DELETE
    flags = OPEN_REPARSE | (BACKUP_SEMANTICS if directory else 0)

    handle = api.CreateFileW(
        str(path),
        access,
        SHARE_READ | SHARE_DELETE,
        None,
        OPEN_EXISTING,
        flags,
        None,
    )

    if handle in (None, INVALID_HANDLE):
        raise ctypes.WinError(ctypes.get_last_error())

    return handle


def _info(api, handle):
    result = FILE_INFO()

    if not api.GetFileInformationByHandle(handle, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())

    return result


def _file_id(info):
    return (info.index_high << 32) | info.index_low


def _final_path(api, handle):
    buffer = ctypes.create_unicode_buffer(32768)
    count = api.GetFinalPathNameByHandleW(
        handle, buffer, len(buffer), 0
    )

    if not count:
        raise ctypes.WinError(ctypes.get_last_error())

    if count >= len(buffer):
        raise CleanupRejected("Resolved pathname too long")

    result = buffer.value

    if result.startswith("\\\\?\\"):
        result = result[4:]

    return _normalized(result)


def _hash_handle(api, handle):
    digest = hashlib.sha256()
    buffer = ctypes.create_string_buffer(1024 * 1024)
    count = wintypes.DWORD()

    while True:
        if not api.ReadFile(
            handle,
            buffer,
            len(buffer),
            ctypes.byref(count),
            None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        if not count.value:
            break

        digest.update(buffer.raw[:count.value])

    return digest.hexdigest()


def cleanup_verified(temp, work, file_identity, work_identity, expected_sha256):
    """Delete only a fully authorized temporary attachment.

    Returns True after successful disposition, handle closure, and
    confirmation that the temporary pathname no longer exists.

    This function does not write audit records. The caller must
    durably record CLEANUP_PENDING before invoking it.
    """
    temp = Path(temp)
    work = Path(work)

    if temp.parent != work:
        raise CleanupRejected("Temporary pathname outside work directory")

    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(c not in "0123456789abcdef" for c in expected_sha256)
    ):
        raise CleanupRejected("Invalid expected SHA-256")

    api = _windows_api()
    directory_handle = None
    attachment_handle = None
    deletion_attempted = False
    error = None

    try:
        directory_handle = _open(api, work, directory=True)
        attachment_handle = _open(api, temp, directory=False)

        directory_info = _info(api, directory_handle)
        attachment_info = _info(api, attachment_handle)

        if _file_id(directory_info) != work_identity.st_ino:
            raise CleanupRejected("Directory identity changed")

        if _file_id(attachment_info) != file_identity.st_ino:
            raise CleanupRejected("Attachment identity changed")

        if not directory_info.attributes & DIRECTORY_ATTRIBUTE:
            raise CleanupRejected("Expected directory")

        if attachment_info.attributes & DIRECTORY_ATTRIBUTE:
            raise CleanupRejected("Attachment is a directory")

        if (
            directory_info.attributes & REPARSE_ATTRIBUTE
            or attachment_info.attributes & REPARSE_ATTRIBUTE
        ):
            raise CleanupRejected("Reparse point forbidden")

        if attachment_info.links != 1:
            raise CleanupRejected("Multiple hard links forbidden")

        if directory_info.volume != attachment_info.volume:
            raise CleanupRejected("Volume mismatch")

        directory_path = _final_path(api, directory_handle)
        attachment_path = _final_path(api, attachment_handle)

        if directory_path != _normalized(work):
            raise CleanupRejected("Directory pathname changed")

        if attachment_path != _normalized(temp):
            raise CleanupRejected("Attachment pathname changed")

        if os.path.dirname(attachment_path) != directory_path:
            raise CleanupRejected("Attachment outside verified directory")

        if _hash_handle(api, attachment_handle) != expected_sha256:
            raise CleanupRejected("Attachment SHA-256 mismatch")

        disposition = FILE_DISPOSITION_INFO(1)

        # From this point onward, errors must not imply retention.
        deletion_attempted = True

        if not api.SetFileInformationByHandle(
            attachment_handle,
            FILE_DISPOSITION_INFO_CLASS,
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    except BaseException as exc:
        error = exc

    finally:
        for handle in (attachment_handle, directory_handle):
            if handle is not None:
                try:
                    if not api.CloseHandle(handle):
                        raise ctypes.WinError(ctypes.get_last_error())
                except BaseException as exc:
                    if error is None:
                        error = exc

    if error is not None:
        if deletion_attempted:
            raise CleanupUncertain(
                "Deletion outcome uncertain: " + str(error)
            ) from error
        raise error

    try:
        if os.path.lexists(temp):
            raise CleanupUncertain(
                "Temporary pathname still exists after deletion"
            )
    except OSError as exc:
        raise CleanupUncertain(
            "Unable to confirm temporary pathname removal"
        ) from exc

    return True
